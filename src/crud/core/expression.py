from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar, override


@dataclass(frozen=True, kw_only=True)
class Expression[T, H: Hashable](ABC):
    """A node in an expression tree, computed bottom-up by a `Backend`.

    Its atoms hold values of the input space `T` and its operators are keyed in `H`, so only
    a backend over those same spaces can compute it.
    """

    @abstractmethod
    def _get_children(self) -> Sequence["Expression[T, H]"]: ...

    @property
    def children(self) -> Sequence["Expression[T, H]"]:
        return self._get_children()

    @abstractmethod
    def evaluate[V](self, backend: "Backend[T, H, V]") -> V: ...


@dataclass(frozen=True, kw_only=True)
class Atom[T, H: Hashable](Expression[T, H], ABC):
    """A leaf: it holds a value of the input space `T`, which a backend casts."""

    @abstractmethod
    def _get_value(self) -> T: ...

    @override
    def _get_children(self) -> Sequence[Expression[T, H]]:
        return ()

    @override
    def evaluate[V](self, backend: "Backend[T, H, V]") -> V:
        return backend.cast(self._get_value())


@dataclass(frozen=True, kw_only=True)
class Operator[T, H: Hashable, E: Expression](Expression[T, H], ABC):
    """A node that combines the values of its operands."""

    arity: ClassVar[int | None] = None
    """Exact number of operands this operator takes, or `None` for any number."""

    operands: tuple[E, ...]
    """The expressions this operator combines, in order."""

    def __post_init__(self) -> None:
        if self.arity is not None and len(self.operands) != self.arity:
            raise ValueError(
                f"{type(self).__name__} takes {self.arity} operands, got {len(self.operands)}"
            )

    @abstractmethod
    def _get_key(self) -> H: ...

    @property
    def key(self) -> H:
        """What a backend looks up to find how to compute this operator."""
        return self._get_key()

    @override
    def _get_children(self) -> Sequence[Expression[T, H]]:
        return self.operands

    def _broadcast[V](self, backend: "Backend[T, H, V]") -> Iterator[V]:
        return (operand.evaluate(backend) for operand in self.operands)

    def _reduce[V](self, backend: "Backend[T, H, V]", values: Iterable[V]) -> V:
        return backend.compute(self.key, values)

    @override
    def evaluate[V](self, backend: "Backend[T, H, V]") -> V:
        return self._reduce(backend, self._broadcast(backend))


type Computation[V] = Callable[[Iterable[V]], V]


class Backend[T, H: Hashable, V](ABC):
    """Computes expressions whose atoms hold `T` values into values of type `V`.

    Operators are computed through a mapping from their key, of type `H`, to a computation.
    """

    @abstractmethod
    def _make_operations(self) -> Mapping[H, Computation[V]]: ...

    @abstractmethod
    def cast(self, value: T) -> V:
        """Convert an atom's value from the input space to the computation space."""

    @cached_property
    def operations(self) -> Mapping[H, Computation[V]]:
        return self._make_operations()

    def compute(self, key: H, values: Iterable[V]) -> V:
        """Combine an operator's evaluated operands with the computation registered for `key`."""
        try:
            computation = self.operations[key]
        except KeyError as e:
            raise TypeError(
                f"{type(self).__name__} cannot compute operation with key '{key!r}'"
            ) from e
        return computation(values)
