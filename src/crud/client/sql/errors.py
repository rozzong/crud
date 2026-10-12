from .._errors import (
    ConstraintError,
    CRUDError,
    FieldError,
    QueryError,
    StorageError,
    TransactionError,
)


class SQLError(CRUDError):
    """Base class of every error `SQLClient` raises."""


class SQLFieldError(SQLError, FieldError):
    """A field the model does not have, or that is not a column or relationship as needed."""


class SQLQueryError(SQLError, QueryError):
    """A filter or an ordering that cannot be turned into SQL."""


class SQLStorageError(SQLError, StorageError):
    """The database failed to carry out a statement or a commit."""


class SQLConstraintError(SQLStorageError, ConstraintError):
    """A write breaks a constraint of the database, such as `NOT NULL` or a foreign key."""


class SQLTransactionError(SQLError, TransactionError):
    """A transaction that is not an `SQLClient` one on the same engine."""
