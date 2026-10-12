import pytest

from crud import (
    ConstraintError,
    CRUDError,
    FieldError,
    QueryError,
    SQLConstraintError,
    SQLError,
    SQLFieldError,
    SQLHop,
    SQLQueryError,
    SQLStorageError,
    StorageError,
)
from crud.client.sql.backend import _merge_hops


def test_hops_merge_only_along_one_path() -> None:
    # Hops compare by name only, so the comparator is irrelevant here.
    team, leader, rival = (
        SQLHop(name=name, comparator=None, is_to_many=False)  # pyright: ignore[reportArgumentType]
        for name in ("Hero.team", "Team.leader", "Team.rival")
    )
    assert _merge_hops((team,), (team, leader)) == (team, leader)
    assert _merge_hops((), (team,)) == (team,)
    with pytest.raises(SQLQueryError, match="different relationships"):
        _merge_hops((team, leader), (team, rival))


@pytest.mark.parametrize(
    ("error", "categories"),
    [
        (SQLFieldError, (SQLError, FieldError)),
        (SQLQueryError, (SQLError, QueryError)),
        (SQLStorageError, (SQLError, StorageError)),
        (SQLConstraintError, (SQLError, SQLStorageError, ConstraintError, StorageError)),
    ],
)
def test_sql_errors_are_caught_as_backend_agnostic_errors(
    error: type[CRUDError], categories: tuple[type[CRUDError], ...]
) -> None:
    for category in (*categories, CRUDError):
        assert issubclass(error, category)
