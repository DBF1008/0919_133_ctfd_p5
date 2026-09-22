import datetime

from CTFd.cache import clear_standings
from CTFd.models import Teams, Users
from CTFd.utils.scores import (
    get_account_score,
    get_standings,
    get_team_standings,
    get_user_standings,
)
from tests.helpers import (
    create_ctfd,
    destroy_ctfd,
    gen_award,
    gen_bracket,
    gen_challenge,
    gen_solve,
    gen_team,
    gen_user,
)


def test_standings_tie_break_uses_solve_date_not_id():
    """
    Tied scores must be broken by the timestamp of the latest scoring event,
    not by the solve row ID. AUTO_INCREMENT IDs are not guaranteed to match
    commit order under concurrent inserts, so the earlier solve must win the
    tie even when its row was inserted later (higher ID).
    """
    app = create_ctfd()
    with app.app_context():
        gen_challenge(app.db)
        user1 = gen_user(app.db, name="user1", email="user1@examplectf.com")
        user2 = gen_user(app.db, name="user2", email="user2@examplectf.com")

        # user1's solve is inserted first (lower ID) but has a LATER date
        solve1 = gen_solve(app.db, user_id=user1.id, challenge_id=1)
        solve1.date = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)

        # user2's solve is inserted second (higher ID) but has an EARLIER date
        solve2 = gen_solve(app.db, user_id=user2.id, challenge_id=1)
        solve2.date = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)

        app.db.session.commit()
        clear_standings()

        standings = get_standings()
        assert len(standings) == 2
        assert standings[0].score == standings[1].score == 100
        # user2 reached the score first in time and must win the tie
        assert standings[0].account_id == user2.id
        assert standings[1].account_id == user1.id

        user_standings = get_user_standings()
        assert user_standings[0].user_id == user2.id
        assert user_standings[1].user_id == user1.id
    destroy_ctfd(app)


def test_get_account_score_matches_model_and_standings():
    """get_account_score, Users.get_score, and the standings must agree"""
    app = create_ctfd()
    with app.app_context():
        gen_challenge(app.db)
        user = gen_user(app.db, name="user1", email="user1@examplectf.com")
        gen_solve(app.db, user_id=user.id, challenge_id=1)
        gen_award(app.db, user_id=user.id, value=50)
        clear_standings()

        standings = get_standings()
        assert standings[0].score == 150
        assert get_account_score(user.id, account_type="user") == 150
        assert get_account_score(user.id, account_type="account") == 150
        assert Users.query.filter_by(id=user.id).first().get_score() == 150
    destroy_ctfd(app)


def test_team_get_score_matches_team_standings():
    """Teams.get_score must agree with get_team_standings"""
    app = create_ctfd(user_mode="teams")
    with app.app_context():
        gen_challenge(app.db)
        team = gen_team(app.db)
        member = team.members[0]
        gen_solve(app.db, user_id=member.id, team_id=team.id, challenge_id=1)
        gen_award(app.db, user_id=member.id, team_id=team.id, value=25)
        clear_standings()

        team_standings = get_team_standings()
        assert team_standings[0].team_id == team.id
        assert team_standings[0].score == 125

        team = Teams.query.filter_by(id=team.id).first()
        assert team.get_score() == 125
        assert get_account_score(team.id, account_type="team") == 125

        standings = get_standings()
        assert standings[0].account_id == team.id
        assert standings[0].score == 125
    destroy_ctfd(app)


def test_standings_bracket_filter():
    """Bracket filtering must only return accounts in the requested bracket"""
    app = create_ctfd()
    with app.app_context():
        gen_challenge(app.db)
        gen_bracket(app.db, name="bracket1", type="users")
        gen_bracket(app.db, name="bracket2", type="users")

        user1 = gen_user(
            app.db, name="user1", email="user1@examplectf.com", bracket_id=1
        )
        user2 = gen_user(
            app.db, name="user2", email="user2@examplectf.com", bracket_id=2
        )
        gen_solve(app.db, user_id=user1.id, challenge_id=1)
        gen_solve(app.db, user_id=user2.id, challenge_id=1)
        clear_standings()

        standings = get_standings()
        assert len(standings) == 2

        bracket1_standings = get_standings(bracket_id=1)
        assert len(bracket1_standings) == 1
        assert bracket1_standings[0].account_id == user1.id
        assert bracket1_standings[0].bracket_id == 1

        bracket2_standings = get_user_standings(bracket_id=2)
        assert len(bracket2_standings) == 1
        assert bracket2_standings[0].user_id == user2.id
    destroy_ctfd(app)


def test_bracket_composite_indexes_exist():
    """Users and Teams must have a composite index covering bracket filters"""
    expected = ("bracket_id", "banned", "hidden")
    user_indexes = {tuple(idx.columns.keys()) for idx in Users.__table__.indexes}
    team_indexes = {tuple(idx.columns.keys()) for idx in Teams.__table__.indexes}
    assert expected in user_indexes
    assert expected in team_indexes
