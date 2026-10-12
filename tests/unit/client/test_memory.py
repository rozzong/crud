import pytest

from crud import (
    ConstraintError,
    CRUDError,
    FieldError,
    InMemoryConflictError,
    InMemoryConstraintError,
    InMemoryError,
    InMemoryFieldError,
    InMemoryQueryError,
    InMemoryStorageError,
    QueryError,
    StorageError,
)


@pytest.mark.parametrize(
    ("error", "categories"),
    [
        (InMemoryFieldError, (InMemoryError, FieldError)),
        (InMemoryQueryError, (InMemoryError, QueryError)),
        (InMemoryStorageError, (InMemoryError, StorageError)),
        (InMemoryConstraintError, (InMemoryError, InMemoryStorageError, ConstraintError)),
        (InMemoryConflictError, (InMemoryError, InMemoryStorageError, StorageError)),
    ],
)
def test_in_memory_errors_are_caught_as_backend_agnostic_errors(
    error: type[CRUDError], categories: tuple[type[CRUDError], ...]
) -> None:
    for category in (*categories, CRUDError):
        assert issubclass(error, category)
