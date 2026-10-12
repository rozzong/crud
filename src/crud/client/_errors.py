class CRUDError(Exception):
    """Base class of every error a CRUD client raises, whatever its backend.

    Each backend client raises its own subclasses, which also derive from one of the
    categories below, so callers can catch them without knowing the backend.
    """


class RecordError(CRUDError):
    """A record class cannot be used: its fields are unknown, or it cannot be built."""


class FieldError(CRUDError):
    """A field the stored records do not have, or that is not usable where it is named."""


class QueryError(CRUDError):
    """A filter or an ordering the backend cannot run."""


class StorageError(CRUDError):
    """The storage failed to carry out an operation."""


class ConstraintError(StorageError):
    """A write breaks a rule of the storage, such as a required, unique or foreign key field."""


class TransactionError(CRUDError):
    """A transaction a client cannot run in, such as one opened on another storage."""
