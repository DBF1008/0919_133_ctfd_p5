from sqlalchemy.sql.expression import union_all

from CTFd.cache import cache
from CTFd.models import Awards, Brackets, Challenges, Solves, Teams, Users, db
from CTFd.utils import get_config
from CTFd.utils.dates import unix_time_to_utc


def _build_score_subquery(solves_column, awards_column, admin=False):
    """
    Build the aggregated solves/awards score subquery for one account kind.

    ``solves_column`` and ``awards_column`` are the matching account columns on
    each table (e.g. ``Solves.user_id`` and ``Awards.user_id``); they must be
    passed separately because solves and awards live in different tables.

    The returned subquery has one row per account with the columns
    ``account_id``, ``score``, ``date`` and ``id``. It is the single source of
    truth shared by every standings query and by the per-account score helpers
    on the Users/Teams models.

    ``date`` holds the timestamp of the account's last scoring event (solve or
    award) and ``id`` is only retained as a final, stable tiebreaker for rows
    that share the exact same timestamp.

    When ``admin`` is False, solves and awards after the configured freeze time
    are excluded.
    """
    scores = (
        db.session.query(
            solves_column.label("account_id"),
            db.func.sum(Challenges.value).label("score"),
            db.func.max(Solves.date).label("date"),
            db.func.max(Solves.id).label("id"),
        )
        .join(Challenges)
        .filter(Challenges.value != 0)
        .group_by(solves_column)
    )

    awards = (
        db.session.query(
            awards_column.label("account_id"),
            db.func.sum(Awards.value).label("score"),
            db.func.max(Awards.date).label("date"),
            db.func.max(Awards.id).label("id"),
        )
        .filter(Awards.value != 0)
        .group_by(awards_column)
    )

    # Filter out solves and awards that are at/after the freeze time point.
    freeze = get_config("freeze")
    if not admin and freeze:
        scores = scores.filter(Solves.date < unix_time_to_utc(freeze))
        awards = awards.filter(Awards.date < unix_time_to_utc(freeze))

    # Combine awards and solves with a union. They must have identical columns.
    results = union_all(scores, awards).alias("results")

    # Sum each of the results by account id to get the final score.
    return (
        db.session.query(
            results.columns.account_id,
            db.func.sum(results.columns.score).label("score"),
            db.func.max(results.columns.date).label("date"),
            db.func.max(results.columns.id).label("id"),
        )
        .group_by(results.columns.account_id)
        .subquery()
    )


def _get_standings(
    model,
    account_column,
    awards_column,
    id_label=None,
    count=None,
    bracket_id=None,
    admin=False,
    fields=None,
):
    """
    Single parameterized entry point behind every public standings query.

    Only the account ``model`` (Users or Teams) and the ``account_column`` that
    links solves/awards to that model differ between callers.

    Ties are broken by the actual timestamp of the account's last scoring
    event (the account that reached the score first wins). Unlike
    AUTO_INCREMENT ids, whose allocation order is not guaranteed to match the
    commit order under concurrent MySQL inserts, the solve timestamp reflects
    when the score was really reached. The row id is used only as a
    deterministic fallback for identical timestamps.

    Challenges & Awards with a value of zero are filtered out of the
    calculations to avoid incorrect tie breaks.
    """
    if fields is None:
        fields = []

    sumscores = _build_score_subquery(
        account_column,
        awards_column,
        admin=admin,
    )

    account_columns = [
        model.id.label("account_id"),
        model.oauth_id.label("oauth_id"),
        model.name.label("name"),
    ]
    if id_label is not None:
        account_columns.append(model.id.label(id_label))
    if model is Users:
        account_columns.append(model.team_id.label("team_id"))
    account_columns += [
        model.bracket_id.label("bracket_id"),
        Brackets.name.label("bracket_name"),
    ]
    if admin:
        account_columns += [model.hidden, model.banned]
    account_columns.append(sumscores.columns.score)
    account_columns.extend(fields)

    standings_query = (
        db.session.query(*account_columns)
        .join(sumscores, model.id == sumscores.columns.account_id)
        .join(Brackets, isouter=True)
        .order_by(
            sumscores.columns.score.desc(),
            sumscores.columns.date.asc(),
            sumscores.columns.id.asc(),
        )
    )

    # Admins can see every account; the public cannot see banned/hidden ones.
    if not admin:
        standings_query = standings_query.filter(
            model.banned == False,
            model.hidden == False,
        )

    if bracket_id is not None:
        standings_query = standings_query.filter(model.bracket_id == bracket_id)

    if count is None:
        return standings_query.all()
    return standings_query.limit(count).all()


def get_account_score(account, admin=False):
    """
    Return the score of a single account (User or Team) using the exact same
    calculation as the standings queries.

    This is the shared implementation behind ``Users.get_score`` and
    ``Teams.get_score`` so that per-account scores and standings scores can
    never drift apart.
    """
    if isinstance(account, Users):
        solves_column, awards_col = Solves.user_id, Awards.user_id
    else:
        solves_column, awards_col = Solves.team_id, Awards.team_id

    sumscores = _build_score_subquery(solves_column, awards_col, admin=admin)
    result = (
        db.session.query(sumscores.c.score)
        .filter(sumscores.c.account_id == account.id)
        .first()
    )
    return int(result.score or 0) if result else 0


@cache.memoize(timeout=60)
def get_standings(count=None, bracket_id=None, admin=False, fields=None):
    """
    Get standings for the current CTF mode as a list of rows containing
    account_id, name, and score e.g. [(account_id, name, score)].

    Mode-aware wrapper around :func:`_get_standings`.
    """
    from CTFd.utils.modes import get_model

    if fields is None:
        fields = []
    model = get_model()
    return _get_standings(
        model=model,
        account_column=Solves.account_id,
        awards_column=Awards.account_id,
        count=count,
        bracket_id=bracket_id,
        admin=admin,
        fields=fields,
    )


@cache.memoize(timeout=60)
def get_team_standings(count=None, bracket_id=None, admin=False, fields=None):
    """
    Get team standings as a list of rows containing team_id, name, and score
    e.g. [(team_id, team_name, score)].

    Thin wrapper around :func:`_get_standings`.
    """
    if fields is None:
        fields = []
    return _get_standings(
        model=Teams,
        account_column=Solves.team_id,
        awards_column=Awards.team_id,
        id_label="team_id",
        count=count,
        bracket_id=bracket_id,
        admin=admin,
        fields=fields,
    )


@cache.memoize(timeout=60)
def get_user_standings(count=None, bracket_id=None, admin=False, fields=None):
    """
    Get user standings as a list of rows containing user_id, name, and score
    e.g. [(user_id, user_name, score)].

    Thin wrapper around :func:`_get_standings`.
    """
    if fields is None:
        fields = []
    return _get_standings(
        model=Users,
        account_column=Solves.user_id,
        awards_column=Awards.user_id,
        id_label="user_id",
        count=count,
        bracket_id=bracket_id,
        admin=admin,
        fields=fields,
    )
