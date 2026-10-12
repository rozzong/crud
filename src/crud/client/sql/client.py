from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import final, override

from sqlalchemy import Engine, delete, insert, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.expression import UnaryExpression
from sqlmodel import Session, SQLModel
from sqlmodel.sql.expression import Select

from crud.core import filter as f

from .._client import Blueprint, CRUDClient, Projection, Transaction
from .._errors import CRUDError
from .backend import Condition, SQLBackend, _get_column, _to_condition
from .errors import SQLConstraintError, SQLQueryError, SQLStorageError, SQLTransactionError


@final
@dataclass(frozen=True, eq=False)
class SQLTransaction(Transaction):
    """A transaction of `SQLClient`: a session on one engine."""

    engine: Engine
    """The engine the session runs on. Every client on it can run in the transaction."""

    session: Session
    """The session running the transaction."""


@final
@dataclass(kw_only=True)
class SQLClient[B: Blueprint, K: Projection, M: SQLModel](CRUDClient[B, K]):
    model_cls: type[M]
    """The table model holding the records."""

    engine: Engine
    """Engine to open sessions on. Share one across clients to share its connection pool."""

    @cached_property
    def _backend(self) -> SQLBackend[M]:
        return SQLBackend(model_cls=self.model_cls)

    def _get_session(self, transaction: Transaction) -> Session:
        if not isinstance(transaction, SQLTransaction) or transaction.engine is not self.engine:
            raise SQLTransactionError(
                f"{type(transaction).__name__} was not opened on the engine of this client"
            )
        return transaction.session

    def _compile_filter(self, filter: f.Filter) -> Condition:
        return _to_condition(filter.evaluate(self._backend))

    def _check_columns(self, names: Iterable[str]) -> None:
        for name in names:
            _get_column(self.model_cls, name)

    def _make_order_clause(self, order: f.Order) -> UnaryExpression[object]:
        match order.field.path:
            case (column_name,):
                column = _get_column(self.model_cls, column_name)
            case path:
                raise SQLQueryError(f"Cannot order by related field {'.'.join(path)!r}")
        return column.desc() if order.is_descending else column.asc()

    @override
    def _convert_error(self, error: Exception) -> CRUDError | None:
        match error:
            case IntegrityError():
                return SQLConstraintError(str(error.orig))
            case SQLAlchemyError():
                return SQLStorageError(str(error))
            case _:
                return None

    @override
    def _open_transaction(self) -> SQLTransaction:
        session = Session(self.engine, expire_on_commit=False)
        return SQLTransaction(engine=self.engine, session=session)

    @override
    def _handle_successful_transaction(self, transaction: Transaction) -> None:
        self._get_session(transaction).commit()

    @override
    def _handle_failed_transaction(self, transaction: Transaction) -> None:
        self._get_session(transaction).rollback()

    @override
    def _close_transaction(self, transaction: Transaction) -> None:
        self._get_session(transaction).close()

    @override
    def _create(
        self,
        transaction: Transaction,
        rows: Sequence[Mapping[str, object]],
        key_names: Sequence[str],
    ) -> Iterable[Mapping[str, object]]:
        session = self._get_session(transaction)
        self._check_columns(self.blueprint_cls.get_fields())
        key_columns = (_get_column(self.model_cls, name) for name in key_names)
        # Without sorting, a batched insert may return its rows in any order.
        statement = insert(self.model_cls).returning(*key_columns, sort_by_parameter_order=True)
        return [
            dict(zip(key_names, row, strict=True)) for row in session.exec(statement, params=rows)
        ]

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
        statement = Select(*(_get_column(self.model_cls, name) for name in names))
        if filter is not None:
            statement = statement.where(self._compile_filter(filter))
        if order_by:
            statement = statement.order_by(*(self._make_order_clause(o) for o in order_by))
        if limit is not None:
            statement = statement.limit(limit)
        return (dict(zip(names, row, strict=True)) for row in session.exec(statement))

    @override
    def _update(
        self,
        transaction: Transaction,
        filter: f.Filter,
        values: Mapping[str, object],
    ) -> int:
        session = self._get_session(transaction)
        self._check_columns(values)
        statement = update(self.model_cls).where(self._compile_filter(filter)).values(values)
        return session.exec(statement).rowcount

    @override
    def _destroy(self, transaction: Transaction, filter: f.Filter) -> int:
        session = self._get_session(transaction)
        result = session.exec(delete(self.model_cls).where(self._compile_filter(filter)))
        return result.rowcount
