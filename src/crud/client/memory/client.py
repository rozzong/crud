from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import final, override

from crud.core import filter as f

from .._client import Blueprint, CRUDClient, Projection, Transaction
from .._errors import CRUDError
from .backend import InMemoryBackend, InMemoryCondition, _to_condition
from .database import InMemoryDatabase, InMemorySession, InMemoryTable, Row, _TableState
from .errors import InMemoryConstraintError, InMemoryQueryError, InMemoryTransactionError


@final
@dataclass(frozen=True, eq=False)
class InMemoryTransaction(Transaction):
    """A transaction of `InMemoryClient`: a working copy of one database."""

    database: InMemoryDatabase
    """The database the copy was taken from. Every client on it can run in the transaction."""

    session: InMemorySession
    """The working copy, which a successful transaction commits."""


@final
@dataclass(kw_only=True)
class InMemoryClient[B: Blueprint, K: Projection](CRUDClient[B, K]):
    """A client on one table of an `InMemoryDatabase`, such as a stand-in for tests.

    It follows SQL's semantics where they matter to filters: comparing to `None` is unknown
    except for `== None` and `!= None`, which test for `None` as `IS NULL` does.
    """

    database: InMemoryDatabase
    """The database holding the table. Share one across clients to share their records."""

    table_name: str
    """Name of the table holding the records."""

    @property
    def _table(self) -> InMemoryTable:
        return self.database.get_table(self.table_name)

    @cached_property
    def _backend(self) -> InMemoryBackend:
        return InMemoryBackend(database=self.database, table=self._table)

    def _get_session(self, transaction: Transaction) -> InMemorySession:
        if (
            not isinstance(transaction, InMemoryTransaction)
            or transaction.database is not self.database
        ):
            raise InMemoryTransactionError(
                f"{type(transaction).__name__} was not opened on the database of this client"
            )
        return transaction.session

    def _compile_filter(self, filter: f.Filter) -> InMemoryCondition:
        return _to_condition(filter.evaluate(self._backend))

    def _check_columns(self, names: Iterable[str]) -> None:
        for name in names:
            self._table.get_column(name)

    def _check_rows(self, rows: Sequence[Row]) -> None:
        table = self._table
        keys: set[object] = set()
        for row in rows:
            for name in table.required:
                if row[name] is None:
                    raise InMemoryConstraintError(f"{table.name}.{name} is required")
            key = row[table.key]
            if key in keys:
                raise InMemoryConstraintError(f"{table.name}.{table.key} {key!r} is repeated")
            keys.add(key)

    def _write_table(self, session: InMemorySession, rows: Sequence[Row], next_key: int) -> None:
        self._check_rows(rows)
        session.tables[self.table_name] = _TableState(rows=tuple(rows), next_key=next_key)
        session.is_dirty = True

    def _filter_rows(self, session: InMemorySession, filter: f.Filter | None) -> list[bool]:
        """Tell, for each record of the table in order, whether it matches `filter`."""
        rows = session.tables[self.table_name].rows
        if filter is None:
            return [True] * len(rows)
        condition = self._compile_filter(filter)
        return [condition.test(session, row) is True for row in rows]

    def _sort_rows(self, rows: list[Row], order_by: Sequence[f.Order]) -> None:
        # Sorting by the last order first, stably, sorts by the first order first.
        for order in reversed(order_by):
            match order.field.path:
                case (column_name,):
                    name = self._table.get_column(column_name)
                case path:
                    raise InMemoryQueryError(f"Cannot order by related field {'.'.join(path)!r}")
            try:
                # As in SQLite, `None` sorts before every other value.
                rows.sort(
                    key=lambda row: (row[name] is not None, row[name]),
                    reverse=order.is_descending,
                )
            except TypeError as error:
                raise InMemoryQueryError(f"Cannot order by {name!r}: {error}") from error

    @override
    def _convert_error(self, error: Exception) -> CRUDError | None:
        # Every failure is raised as an `InMemoryError` already: anything else is a bug.
        return None

    @override
    def _open_transaction(self) -> InMemoryTransaction:
        return InMemoryTransaction(database=self.database, session=self.database.open_session())

    @override
    def _handle_successful_transaction(self, transaction: Transaction) -> None:
        self.database.commit(self._get_session(transaction))

    @override
    def _handle_failed_transaction(self, transaction: Transaction) -> None:
        # Nothing reached the database: the working copy is simply dropped.
        pass

    @override
    def _close_transaction(self, transaction: Transaction) -> None:
        pass

    @override
    def _create(
        self,
        transaction: Transaction,
        rows: Sequence[Mapping[str, object]],
        key_names: Sequence[str],
    ) -> Iterable[Mapping[str, object]]:
        session = self._get_session(transaction)
        table = self._table
        self._check_columns(self.blueprint_cls.get_fields())
        self._check_columns(key_names)
        state = session.tables[self.table_name]
        next_key = state.next_key
        created: list[Row] = []
        for row in rows:
            record = {name: None for name in table.columns} | dict(row)
            key = record[table.key]
            if key is None:
                record[table.key] = key = next_key
            if isinstance(key, int):
                next_key = max(next_key, key + 1)
            created.append(record)
        self._write_table(session, (*state.rows, *created), next_key)
        return [{name: record[name] for name in key_names} for record in created]

    @override
    def _read(
        self,
        transaction: Transaction,
        filter: f.Filter | None,
        names: Sequence[str],
        order_by: Sequence[f.Order],
        limit: int | None,
    ) -> Iterable[Mapping[str, object]]:
        session = self._get_session(transaction)
        self._check_columns(names)
        rows = session.tables[self.table_name].rows
        matches = self._filter_rows(session, filter)
        selected = [row for row, is_match in zip(rows, matches, strict=True) if is_match]
        self._sort_rows(selected, order_by)
        if limit is not None:
            selected = selected[:limit]
        return [{name: row[name] for name in names} for row in selected]

    @override
    def _update(
        self,
        transaction: Transaction,
        filter: f.Filter,
        values: Mapping[str, object],
    ) -> int:
        session = self._get_session(transaction)
        self._check_columns(values)
        state = session.tables[self.table_name]
        matches = self._filter_rows(session, filter)
        rows = [
            {**row, **values} if is_match else row
            for row, is_match in zip(state.rows, matches, strict=True)
        ]
        count = sum(matches)
        if count:
            self._write_table(session, rows, state.next_key)
        return count

    @override
    def _destroy(self, transaction: Transaction, filter: f.Filter) -> int:
        session = self._get_session(transaction)
        state = session.tables[self.table_name]
        matches = self._filter_rows(session, filter)
        rows = [row for row, is_match in zip(state.rows, matches, strict=True) if not is_match]
        count = sum(matches)
        if count:
            self._write_table(session, rows, state.next_key)
        return count
