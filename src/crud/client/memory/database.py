from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from threading import Lock

from .errors import InMemoryConflictError, InMemoryFieldError

type Row = Mapping[str, object]


@dataclass(frozen=True)
class InMemoryRelationship:
    """Links each record to the records of `table` whose `remote` column equals its `local` one.

    It is one-to-many or many-to-one alike: a filter through it matches when any related
    record does.
    """

    table: str
    """Name of the related table."""

    local: str
    """Column of this table, such as a foreign key or the primary key."""

    remote: str
    """Column of the related table, such as its primary key or a foreign key."""


@dataclass(frozen=True)
class InMemoryTable:
    """The schema of one table: which fields its records have, and how they relate to others."""

    name: str
    """Name relationships refer to the table by."""

    columns: Sequence[str]
    """Every column of the table, primary key included. A record leaving one out holds `None`."""

    key: str = "id"
    """Column holding the primary key: an integer the table assigns when a record leaves it out."""

    required: Sequence[str] = ()
    """Columns that may not hold `None`."""

    relationships: Mapping[str, InMemoryRelationship] = field(default_factory=dict)
    """Relationships filters can cross, by field name."""

    def get_column(self, name: str) -> str:
        """Return `name` if it is a column, or raise `InMemoryFieldError`."""
        if name in self.columns:
            return name
        if name in self.relationships:
            raise InMemoryFieldError(f"{self.name}.{name} is not a column")
        raise InMemoryFieldError(f"{self.name} has no field {name!r}")

    def get_relationship(self, name: str) -> InMemoryRelationship:
        """Return the relationship named `name`, or raise `InMemoryFieldError`."""
        relationship = self.relationships.get(name)
        if relationship is not None:
            return relationship
        if name in self.columns:
            raise InMemoryFieldError(f"{self.name}.{name} is not a relationship")
        raise InMemoryFieldError(f"{self.name} has no field {name!r}")


@dataclass(frozen=True)
class _TableState:
    """The records of a table at one point in time. Neither it nor its rows are ever mutated."""

    rows: tuple[Row, ...] = ()
    """Every record, holding every column."""

    next_key: int = 1
    """Key the table assigns to the next record that leaves it out."""


@dataclass
class InMemorySession:
    """A working copy of the database: writes replace its tables, and a commit stores them."""

    base_version: int
    """Version of the database the copy was taken from."""

    tables: dict[str, _TableState]
    """State of every table, by name."""

    is_dirty: bool = False
    """Whether the session wrote anything, and so has something to commit."""


@dataclass
class InMemoryDatabase:
    """Tables held in memory, which every client on them shares.

    Each session works on its own copy. A session that wrote commits only if no other one
    committed since it began, or it raises `InMemoryConflictError`.
    """

    tables: Sequence[InMemoryTable]
    """The schema of every table."""

    _states: dict[str, _TableState] = field(init=False)
    _version: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        self._states = {table.name: _TableState() for table in self.tables}
        for table in self.tables:
            self._check_table(table)

    def _check_table(self, table: InMemoryTable) -> None:
        if table.key not in table.columns:
            raise ValueError(f"{table.name}: the key {table.key!r} is not a column")
        for name in table.required:
            if name not in table.columns:
                raise ValueError(f"{table.name}: the required {name!r} is not a column")
        for name, relationship in table.relationships.items():
            if name in table.columns:
                raise ValueError(f"{table.name}: {name!r} is both a column and a relationship")
            if relationship.local not in table.columns:
                raise ValueError(f"{table.name}.{name}: {relationship.local!r} is not a column")
            related = self.get_table(relationship.table)
            if relationship.remote not in related.columns:
                raise ValueError(
                    f"{table.name}.{name}: {relationship.remote!r} is not a column of "
                    f"{related.name}"
                )

    def get_table(self, name: str) -> InMemoryTable:
        """Return the schema of the table named `name`."""
        for table in self.tables:
            if table.name == name:
                return table
        raise ValueError(f"No table named {name!r}")

    def open_session(self) -> InMemorySession:
        """Copy the committed state of every table into a new session."""
        with self._lock:
            return InMemorySession(base_version=self._version, tables=dict(self._states))

    def commit(self, session: InMemorySession) -> None:
        """Store the tables of `session`, unless another session committed since it began."""
        if not session.is_dirty:
            return
        with self._lock:
            if session.base_version != self._version:
                raise InMemoryConflictError("Another transaction committed since this one began")
            self._states = dict(session.tables)
            self._version += 1
        session.base_version, session.is_dirty = self._version, False
