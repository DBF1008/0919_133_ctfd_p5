#!/usr/bin/env python
# -*- coding: utf-8 -*-
import datetime

from CTFd.models import Solves, Submissions, Users
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
    register_user,
)


def test_standings_tiebreak_by_solve_date_not_id():
    """Equal scores are ordered by who reached the score first, not by Solves id."""
    app = create_ctfd()
    with app.app_context():
        register_user(app, name="user1", email="user1@examplectf.com")
        register_user(app, name="user2", email="user2@examplectf.com")
        user1 = Users.query.filter_by(id=2).first()
        user2 = Users.query.filter_by(id=3).first()

        chal1 = gen_challenge(app.db, name="chal1", value=100)
        chal2 = gen_challenge(app.db, name="chal2", value=100)

        # Seed solves directly so their AUTO_INCREMENT ids disagree with the
        # real chronological order, as can happen under concurrent MySQL
        # inserts: the earlier solve has the HIGHER id. Core inserts are used
        # because Solves is joined-table-inherited from Submissions.
        early_date = datetime.datetime(2017, 10, 6, 10, 0, 0)
        late_date = datetime.datetime(2017, 10, 7, 10, 0, 0)
        late_id = 100
        early_id = 101

        app.db.session.execute(
            Submissions.__table__.insert(),
            [
                {
                    "id": late_id,
                    "challenge_id": chal1.id,
                    "user_id": user2.id,
                    "date": late_date,
                    "type": "correct",
                    "provided": "rightkey",
                },
                {
                    "id": early_id,
                    "challenge_id": chal2.id,
                    "user_id": user1.id,
                    "date": early_date,
                    "type": "correct",
                    "provided": "rightkey",
                },
            ],
        )
        app.db.session.execute(
            Solves.__table__.insert(),
            [
                {"id": late_id, "challenge_id": chal1.id, "user_id": user2.id},
                {"id": early_id, "challenge_id": chal2.id, "user_id": user1.id},
            ],
        )
        app.db.session.commit()

        assert Solves.query.filter_by(id=early_id).first().user_id == user1.id
        assert Solves.query.filter_by(id=late_id).first().user_id == user2.id

        standings = get_standings()
        assert [s.account_id for s in standings] == [user1.id, user2.id]

        user_standings = get_user_standings()
        assert [s.user_id for s in user_standings] == [user1.id, user2.id]
    destroy_ctfd(app)


def test_get_score_matches_standings_users_mode():
    """Users.get_score uses the same calculation as the standings queries."""
    app = create_ctfd()
    with app.app_context():
        register_user(app, name="user1", email="user1@examplectf.com")
        user1 = Users.query.filter_by(id=2).first()

        chal = gen_challenge(app.db, value=100)
        gen_solve(app.db, user_id=user1.id, challenge_id=chal.id)
        gen_award(app.db, user_id=user1.id, value=50)

        assert user1.get_score() == 150
        assert get_account_score(user1) == 150
        standings = get_standings()
        assert int(standings[0].score) == 150
        user_standings = get_user_standings()
        assert int(user_standings[0].score) == 150
    destroy_ctfd(app)


def test_get_score_matches_standings_teams_mode():
    """Teams.get_score uses the same calculation as the team standings."""
    app = create_ctfd(user_mode="teams")
    with app.app_context():
        user = gen_user(app.db, name="user1", email="user1@examplectf.com")
        team = gen_team(app.db, name="team1", email="team1@examplectf.com")
        user.team_id = team.id
        team.members.append(user)

        chal = gen_challenge(app.db, value=100)
        gen_solve(app.db, user_id=user.id, team_id=team.id, challenge_id=chal.id)
        gen_award(app.db, user_id=user.id, team_id=team.id, value=50)
        app.db.session.commit()

        assert team.get_score() == 150
        assert get_account_score(team) == 150
        standings = get_standings()
        assert int(standings[0].score) == 150
        team_standings = get_team_standings()
        assert int(team_standings[0].score) == 150
    destroy_ctfd(app)


def test_team_award_counts_in_team_score():
    """A team-only award (no user_id) contributes to the team's score."""
    app = create_ctfd(user_mode="teams")
    with app.app_context():
        user = gen_user(app.db, name="user1", email="user1@examplectf.com")
        team = gen_team(app.db, name="team1", email="team1@examplectf.com")
        user.team_id = team.id
        team.members.append(user)
        app.db.session.commit()

        gen_award(app.db, user_id=None, team_id=team.id, value=25)

        assert team.get_score() == 25
        assert int(get_team_standings()[0].score) == 25
    destroy_ctfd(app)


def test_get_standings_matches_get_team_standings():
    """The mode-aware and explicit team entry points return the same rows."""
    app = create_ctfd(user_mode="teams")
    with app.app_context():
        for i in range(2):
            user = gen_user(
                app.db,
                name=f"solver{i}",
                email=f"solver{i}@examplectf.com",
            )
            team = gen_team(
                app.db,
                name=f"team{i}",
                email=f"team{i}@examplectf.com",
            )
            user.team_id = team.id
            team.members.append(user)
            chal = gen_challenge(app.db, name=f"chal{i}", value=100)
            gen_solve(
                app.db,
                user_id=user.id,
                team_id=team.id,
                challenge_id=chal.id,
            )

        generic = get_standings()
        teams = get_team_standings()
        assert len(generic) == len(teams)
        for generic_row, team_row in zip(generic, teams):
            assert generic_row.account_id == team_row.team_id
            assert generic_row.name == team_row.name
            assert int(generic_row.score) == int(team_row.score)
    destroy_ctfd(app)


def test_bracket_filter_users_mode():
    """Standings can be filtered by bracket_id using the indexed column."""
    app = create_ctfd()
    with app.app_context():
        gen_bracket(app.db, name="bracket_a")
        gen_bracket(app.db, name="bracket_b")

        register_user(app, name="user1", email="user1@examplectf.com")
        register_user(app, name="user2", email="user2@examplectf.com")
        user1 = Users.query.filter_by(id=2).first()
        user2 = Users.query.filter_by(id=3).first()
        user1.bracket_id = 1
        user2.bracket_id = 2

        chal1 = gen_challenge(app.db, name="chal1", value=100)
        chal2 = gen_challenge(app.db, name="chal2", value=200)
        gen_solve(app.db, user_id=user1.id, challenge_id=chal1.id)
        gen_solve(app.db, user_id=user2.id, challenge_id=chal2.id)
        app.db.session.commit()

        standings = get_standings(bracket_id=1)
        assert len(standings) == 1
        assert standings[0].account_id == user1.id
        assert int(standings[0].score) == 100

        user_standings = get_user_standings(bracket_id=2)
        assert len(user_standings) == 1
        assert user_standings[0].user_id == user2.id
        assert int(user_standings[0].score) == 200
    destroy_ctfd(app)


def test_bracket_filter_teams_mode():
    """Team standings can be filtered by bracket_id."""
    app = create_ctfd(user_mode="teams")
    with app.app_context():
        gen_bracket(app.db, name="bracket_a", type="teams")

        user = gen_user(app.db, name="solver", email="solver@examplectf.com")
        team = gen_team(app.db, name="team1", email="team1@examplectf.com")
        user.team_id = team.id
        team.members.append(user)
        team.bracket_id = 1
        chal = gen_challenge(app.db, value=100)
        gen_solve(app.db, user_id=user.id, team_id=team.id, challenge_id=chal.id)
        app.db.session.commit()

        assert len(get_team_standings(bracket_id=1)) == 1
        assert len(get_team_standings(bracket_id=999)) == 0
    destroy_ctfd(app)


def test_zero_value_challenges_excluded():
    """Zero value challenges/awards do not affect score or tie-breaking."""
    app = create_ctfd()
    with app.app_context():
        register_user(app, name="user1", email="user1@examplectf.com")
        user1 = Users.query.filter_by(id=2).first()

        chal = gen_challenge(app.db, value=0)
        gen_solve(app.db, user_id=user1.id, challenge_id=chal.id)
        gen_award(app.db, user_id=user1.id, value=0)

        assert user1.get_score() == 0
        assert get_standings() == []
    destroy_ctfd(app)


def test_bracket_standings_indexes_exist():
    """The composite indexes backing bracket standings queries exist."""
    from sqlalchemy import inspect

    from CTFd.models import db

    app = create_ctfd()
    with app.app_context():
        inspector = inspect(db.engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("users")}
        assert "ix_users_bracket_standings" in indexes
        indexes = {idx["name"] for idx in inspector.get_indexes("teams")}
        assert "ix_teams_bracket_standings" in indexes
    destroy_ctfd(app)
