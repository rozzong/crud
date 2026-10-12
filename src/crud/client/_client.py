from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from functools import cache
from typing import Self

from ..core.filter import Filter, Order
from ._errors import CRUDError, RecordError


class Record:
    """Base class for typed records of some of a stored record's fields.

    Subclasses are dataclasses by default, whose fields are named after the stored ones. Any
    other class can be a record too, as long as it overrides `_get_fields`.
    """

    @classmethod
    def _get_fields(cls) -> Sequence[str]:
        if not is_dataclass(cls):
            raise RecordError(f"{cls.__name__} is not a dataclass, so it must override _get_fields")
        return tuple(field.name for field in fields(cls))

    @classmethod
    @cache
    def get_fields(cls) -> Sequence[str]:
        """Return the names of the fields, in order."""
        return cls._get_fields()


class Projection(Record):
    """What `read` returns: the fields it reads, built from them as keyword arguments."""

    @classmethod
    def build(cls, values: Mapping[str, object]) -> Self:
        """Build the projection from the value of each of its fields, by name."""
        try:
            return cls(**values)
        except (TypeError, ValueError) as error:
            raise RecordError(f"Cannot build {cls.__name__} from {dict(values)!r}") from error


class Blueprint(Record):
    """What `create` and `update` write: exactly the fields it declares.

    Nothing is filled in for the fields it leaves out: writing them is up to the storage.
    """

    def get_values(self) -> Mapping[str, object]:
        """Return the value of every field, by name."""
        return {name: getattr(self, name) for name in self.get_fields()}


class Transaction:
    """An open transaction, as `CRUDClient.transaction` yields it.

    Pass it as `transaction=` to run operations of any client on the same storage in it. Each
    backend has its own subclass, which callers need not know about.
    """


@dataclass(kw_only=True)
class CRUDClient[B: Blueprint, K: Projection](ABC):
    """Backend-agnostic CRUD over one kind of record.

    `B` is what `create` takes, and `K` what it returns for each record it stores.

    Every operation raises a `CRUDError` when it fails: a backend raises its own subclasses,
    which derive from the categories `FieldError`, `QueryError`, `StorageError` and so on.

    A backend implements the protected hooks. Each one that takes a `Transaction` must raise
    `TransactionError` if it was opened on another storage, which unwrapping the backend's own
    subclass checks.
    """

    blueprint_cls: type[B]
    """The blueprint `create` takes, one per record to store."""

    key_cls: type[K]
    """The projection `create` returns for each record it stores, such as its primary key.

    It is read back from the storage, so it may hold fields the storage fills in, such as an
    auto-incremented id.
    """

    @abstractmethod
    def _convert_error(self, error: Exception) -> CRUDError | None:
        """Convert an error of the backend library into a `CRUDError`.

        Return `None` for any other error, such as a bug, to let it through unchanged.
        """

    @abstractmethod
    def _open_transaction(self) -> Transaction: ...

    @abstractmethod
    def _handle_successful_transaction(self, transaction: Transaction) -> None: ...

    @abstractmethod
    def _handle_failed_transaction(self, transaction: Transaction) -> None: ...

    @abstractmethod
    def _close_transaction(self, transaction: Transaction) -> None: ...

    @abstractmethod
    def _create(
        self,
        transaction: Transaction,
        rows: Sequence[Mapping[str, object]],
        key_names: Sequence[str],
    ) -> Iterable[Mapping[str, object]]:
        """Store one record per row, which holds the fields of `blueprint_cls`.

        Return the named fields of each stored record, one mapping per row and in their order.
        Raise `FieldError` if the stored records have no such field.
        """

    @abstractmethod
    def _read(
        self,
        transaction: Transaction,
        filter: Filter | None,
        names: Sequence[str],
        order_by: Sequence[Order],
        limit: int | None,
    ) -> Iterable[Mapping[str, object]]:
        """Read the named fields of the matching records, one mapping per record.

        Raise `FieldError` if the stored records have no such field.
        """

    @abstractmethod
    def _update(
        self, transaction: Transaction, filter: Filter, values: Mapping[str, object]
    ) -> int:
        """Set `values` on the matching records and return how many there were.

        Raise `FieldError` if the stored records have no such field.
        """

    @abstractmethod
    def _destroy(self, transaction: Transaction, filter: Filter) -> int: ...

    @contextmanager
    def _convert_errors(self) -> Generator[None]:
        try:
            yield
        except CRUDError:
            raise
        except Exception as error:
            converted = self._convert_error(error)
            if converted is None:
                raise
            raise converted from error

    @contextmanager
    def transaction(self) -> Generator[Transaction]:
        """Open a transaction that commits on success and rolls back on error.

        Pass it as `transaction=` to run several operations in it, on this client or any other
        on the same storage. Errors raised inside the block are let through unchanged, and a
        failed commit raises `StorageError`.
        """
        with self._convert_errors():
            transaction = self._open_transaction()
        try:
            yield transaction
            with self._convert_errors():
                self._handle_successful_transaction(transaction)
        except BaseException:
            self._handle_failed_transaction(transaction)
            raise
        finally:
            self._close_transaction(transaction)

    @contextmanager
    def _use_transaction(self, transaction: Transaction | None) -> Generator[Transaction]:
        if transaction is not None:
            # The caller owns the transaction, including the commit.
            yield transaction
            return
        with self.transaction() as new_transaction:
            yield new_transaction

    def create(self, items: Iterable[B], *, transaction: Transaction | None = None) -> Sequence[K]:
        """Store one record per item and return the key of each, in the order of `items`."""
        rows = tuple(item.get_values() for item in items)
        if not rows:
            return []
        key_names = self.key_cls.get_fields()
        with self._convert_errors(), self._use_transaction(transaction) as active:
            keys = self._create(active, rows, key_names)
            return [self.key_cls.build(key) for key in keys]

    def read[P: Projection](
        self,
        filter: Filter | None,
        shape: type[P],
        *,
        order_by: Sequence[Order] = (),
        limit: int | None = None,
        transaction: Transaction | None = None,
    ) -> Sequence[P]:
        """Read the matching records as `shape`, fetching only the fields it declares.

        A `None` filter matches every record. For instance, `read(Field("name") == "John", Birth)`
        with
        `@dataclass class Birth(Projection): born_on: date` fetches nothing but the birth dates.
        """
        names = shape.get_fields()
        with self._convert_errors(), self._use_transaction(transaction) as active:
            rows = self._read(active, filter, names, order_by, limit)
            return [shape.build(row) for row in rows]

    def update(
        self, filter: Filter, values: Blueprint, *, transaction: Transaction | None = None
    ) -> int:
        """Set the fields of `values` on the matching records and return how many there were.

        For instance, `update(Field("name") == "Bruce", Rename(super_name="The Dark Knight"))`
        with `@dataclass class Rename(Blueprint): super_name: str`.
        """
        with self._convert_errors(), self._use_transaction(transaction) as active:
            return self._update(active, filter, values.get_values())

    def destroy(self, filter: Filter, *, transaction: Transaction | None = None) -> int:
        """Destroy the matching records and return how many there were."""
        with self._convert_errors(), self._use_transaction(transaction) as active:
            return self._destroy(active, filter)
