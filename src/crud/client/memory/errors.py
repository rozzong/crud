from .._errors import (
    ConstraintError,
    CRUDError,
    FieldError,
    QueryError,
    StorageError,
    TransactionError,
)


class InMemoryError(CRUDError):
    """Base class of every error `InMemoryClient` raises."""


class InMemoryFieldError(InMemoryError, FieldError):
    """A field the table does not have, or that is not a column or relationship as needed."""


class InMemoryQueryError(InMemoryError, QueryError):
    """A filter or an ordering that cannot be run on the stored values."""


class InMemoryStorageError(InMemoryError, StorageError):
    """The database failed to carry out an operation or a commit."""


class InMemoryConstraintError(InMemoryStorageError, ConstraintError):
    """A write leaves a required column empty, or repeats a primary key."""


class InMemoryTransactionError(InMemoryError, TransactionError):
    """A transaction that is not an `InMemoryClient` one on the same database."""


class InMemoryConflictError(InMemoryStorageError):
    """A transaction wrote to the database after another one committed since it began."""
