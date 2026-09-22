from sqlalchemy.sql.expression import union_all

from CTFd.cache import cache
from CTFd.models import Awards, Brackets, Challenges, Solves, Teams, Users, db
from CTFd.utils import get_config
from CTFd.utils.dates import unix_time_to_utc
from CTFd.utils.modes import get_model


def _get_account_columns(account_type):
    """
    Resolve the (Solves, Awards) columns that identify an account.

    "account" follows the configured user mode while "user" and "team"
    address users and teams directly.
    """
    if account_type == "account":
        return Solves.account_id, Awards.account_id
    elif account_type == "user":
        return Solves.user_id, Awards.user_id
    elif account_type == "team":
        return Solves.team_id, Awards.team_id
    raise ValueError("account_type must be one of 'account', 'user', 'team'")


def _get_standings(
    account_type,
    Model,
    id_label,
    count=None,
    bracket_id=None,
    admin=False,
    fields=None,
    extra_columns=(),
):
    """
    Single parameterized entry point for standings queries.

    Returns a list of rows containing the account id (labeled with id_label),
    oauth_id, name, bracket info, and score.

    Ties are broken by who reached a given score first based on the timestamp
    of their most recent scoring event (solve or award). Solve IDs are not
    used for tie-breaking because AUTO_INCREMENT IDs are not guaranteed to
    match commit order under concurrent inserts (e.g. on MySQL/InnoDB),
    which would make tied rankings unstable between queries. The account id
    is used as a final deterministic tie-breaker for identical timestamps.

    Challenges & Awards with a value of zero are filtered out of the
    calculations to avoid incorrect tie breaks.
    """
    if fields is None:
        fields = []
    solve_column, award_column = _get_account_columns(account_type)

    scores = (
        db.session.query(
            solve_column.label("account_id"),
            db.func.sum(Challenges.value).label("score"),
            db.func.max(Solves.date).label("date"),
        )
        .join(Challenges)
        .filter(Challenges.value != 0)
        .group_by(solve_column)
    )

    awards = (
        db.session.query(
            award_column.label("account_id"),
            db.func.sum(Awards.value).label("score"),
            db.func.max(Awards.date).label("date"),
        )
        .filter(Awards.value != 0)
        .group_by(award_column)
    )

    """
    Filter out solves and awards that are before a specific time point.
    """
    freeze = get_config("freeze")
    if not admin and freeze:
        scores = scores.filter(Solves.date < unix_time_to_utc(freeze))
        awards = awards.filter(Awards.date < unix_time_to_utc(freeze))

    """
    Combine awards and solves with a union. They should have the same amount of columns
    """
    results = union_all(scores, awards).alias("results")

    """
    Sum each of the results by the account id to get their score.
    """
    sumscores = (
        db.session.query(
            results.columns.account_id,
            db.func.sum(results.columns.score).label("score"),
            db.func.max(results.columns.date).label("date"),
        )
        .group_by(results.columns.account_id)
        .subquery()
    )

    """
    Admins can see scores for all users but the public cannot see banned users.

    Filters out banned users.
    Properly resolves value ties by the timestamp of the latest scoring event.
    """
    columns = [
        Model.id.label(id_label),
        Model.oauth_id.label("oauth_id"),
        Model.name.label("name"),
        *extra_columns,
        Model.bracket_id.label("bracket_id"),
        Brackets.name.label("bracket_name"),
    ]
    if admin:
        columns += [Model.hidden, Model.banned]
    columns += [sumscores.columns.score, *fields]

    standings_query = db.session.query(*columns).join(
        sumscores, Model.id == sumscores.columns.account_id
    )

    if admin:
        standings_query = standings_query.join(Brackets, isouter=True)
    else:
        standings_query = standings_query.join(Brackets, isouter=True).filter(
            Model.banned == False, Model.hidden == False
        )

    standings_query = standings_query.order_by(
        sumscores.columns.score.desc(),
        sumscores.columns.date.asc(),
        Model.id.asc(),
    )

    # Filter on a bracket if asked
    if bracket_id is not None:
        standings_query = standings_query.filter(Model.bracket_id == bracket_id)

    # Only select a certain amount of accounts if asked.
    if count is None:
        standings = standings_query.all()
    else:
        standings = standings_query.limit(count).all()

    return standings


def get_account_score(account_id, account_type="account", admin=False):
    """
    Compute a single account's score using the same rules as the standings.

    This is the single source of truth for score calculation so that
    Users.get_score and Teams.get_score cannot drift from the scoreboard.
    """
    solve_column, award_column = _get_account_columns(account_type)

    solves = db.session.query(db.func.sum(Challenges.value).label("score")).join(
        Challenges, Solves.challenge_id == Challenges.id
    )
    solves = solves.filter(solve_column == account_id, Challenges.value != 0)

    awards = db.session.query(db.func.sum(Awards.value).label("score"))
    awards = awards.filter(award_column == account_id, Awards.value != 0)

    freeze = get_config("freeze")
    if not admin and freeze:
        solves = solves.filter(Solves.date < unix_time_to_utc(freeze))
        awards = awards.filter(Awards.date < unix_time_to_utc(freeze))

    solve_score = solves.scalar() or 0
    award_score = awards.scalar() or 0
    return int(solve_score) + int(award_score)


@cache.memoize(timeout=60)
def get_standings(count=None, bracket_id=None, admin=False, fields=None):
    """
    Get standings as a list of tuples containing account_id, name, and score e.g. [(account_id, team_name, score)].

    Ties are broken by who reached a given score first based on the timestamp
    of the solve. Two users can have the same score but the user whose last
    scoring event happened earlier will be considered the tie-winner.
    """
    return _get_standings(
        "account",
        get_model(),
        "account_id",
        count=count,
        bracket_id=bracket_id,
        admin=admin,
        fields=fields,
    )


@cache.memoize(timeout=60)
def get_team_standings(count=None, bracket_id=None, admin=False, fields=None):
    return _get_standings(
        "team",
        Teams,
        "team_id",
        count=count,
        bracket_id=bracket_id,
        admin=admin,
        fields=fields,
    )


@cache.memoize(timeout=60)
def get_user_standings(count=None, bracket_id=None, admin=False, fields=None):
    return _get_standings(
        "user",
        Users,
        "user_id",
        count=count,
        bracket_id=bracket_id,
        admin=admin,
        fields=fields,
        extra_columns=(Users.team_id.label("team_id"),),
    )
