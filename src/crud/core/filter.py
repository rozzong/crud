from abc import ABC
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar, override

from .expression import Atom, Backend, Expression, Operator


class Operation(Enum):
    EQ = auto()
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    IN = auto()
    CONTAINS = auto()
    AND = auto()
    OR = auto()
    NOT = auto()


class Filter(Expression[object, Operation], ABC):
    """A boolean expression, combinable with `&`, `|` and `~`."""

    def __and__(self, other: "Filter") -> "And":
        return And(operands=_flatten(self, other, And))

    def __or__(self, other: "Filter") -> "Or":
        return Or(operands=_flatten(self, other, Or))

    def __invert__(self) -> "Not":
        return Not(operands=(self,))

    def __bool__(self) -> bool:
        raise TypeError(
            f"{type(self).__name__} has no truth value: combine filters with &, | and ~, "
            "not `and`, `or` and `not`"
        )


@dataclass(frozen=True)
class Constant[T](Atom[T, Operation]):
    value: T
    """The raw Python value."""

    @override
    def _get_value(self) -> T:
        return self.value


@dataclass(frozen=True, eq=False, init=False)
class Field(Atom["Field", Operation]):
    """Reference to a named field. Extra names traverse relationships first.

    Comparison operators build filters, against a constant or another field:
    `Field("age") >= 18`, `Field("graduated_on") > Field("married_on")`,
    `Field("squad", "name") == "Avengers"`.
    """

    path: tuple[str, ...]
    """The relationships to cross, in order, then the name of the field they lead to."""

    def __init__(self, *path: str) -> None:
        if not path:
            raise ValueError("Field takes at least one name")
        object.__setattr__(self, "path", path)

    @override
    def _get_value(self) -> "Field":
        return self

    def __hash__(self) -> int:
        return hash((Field, self.path))

    def __eq__(self, other: object) -> "Eq":  # ty: ignore[invalid-method-override]
        return Eq(operands=(self, _to_operand(other)))

    def __ne__(self, other: object) -> "Ne":  # ty: ignore[invalid-method-override]
        return Ne(operands=(self, _to_operand(other)))

    def __lt__(self, other: object) -> "Lt":
        return Lt(operands=(self, _to_operand(other)))

    def __le__(self, other: object) -> "Le":
        return Le(operands=(self, _to_operand(other)))

    def __gt__(self, other: object) -> "Gt":
        return Gt(operands=(self, _to_operand(other)))

    def __ge__(self, other: object) -> "Ge":
        return Ge(operands=(self, _to_operand(other)))

    def in_(self, values: Iterable[object]) -> "In":
        return In(operands=(self, Constant(tuple(values))))

    def contains(self, other: object) -> "Contains":
        return Contains(operands=(self, _to_operand(other)))


type Operand = Field | Constant[object]


def _to_operand(value: object) -> Operand:
    """Use fields and constants as they are, and wrap anything else in a `Constant`."""
    if isinstance(value, Field | Constant):
        return value
    return Constant(value)


def _is_same_operand(a: Operand, b: Operand) -> bool:
    match a, b:
        case Field(), Field():
            return a.path == b.path
        case Constant(), Constant():
            return bool(a.value == b.value)
        case _:
            return False


@dataclass(frozen=True)
class Order:
    """How to sort results: by one field, in one direction."""

    field: Field
    """The field to sort on."""

    is_descending: bool = False
    """Sort from largest to smallest instead of smallest to largest."""


class FilterOperator[E: Expression[object, Operation]](Operator[object, Operation, E], Filter, ABC):
    """A filter computed by the backend entry for its `operation`."""

    operation: ClassVar[Operation]
    """Key a `FilterBackend` uses to find how to compute this node."""

    @override
    def _get_key(self) -> Operation:
        return self.operation


class Eq(FilterOperator[Operand]):
    arity = 2
    operation = Operation.EQ

    @override
    def __bool__(self) -> bool:
        """Compare the operands structurally, so `==` on fields still works in tuples and sets."""
        return _is_same_operand(*self.operands)


class Ne(FilterOperator[Operand]):
    arity = 2
    operation = Operation.NE

    @override
    def __bool__(self) -> bool:
        return not _is_same_operand(*self.operands)


class Lt(FilterOperator[Operand]):
    arity = 2
    operation = Operation.LT


class Le(FilterOperator[Operand]):
    arity = 2
    operation = Operation.LE


class Gt(FilterOperator[Operand]):
    arity = 2
    operation = Operation.GT


class Ge(FilterOperator[Operand]):
    arity = 2
    operation = Operation.GE


class In(FilterOperator[Operand]):
    arity = 2
    operation = Operation.IN


class Contains(FilterOperator[Operand]):
    arity = 2
    operation = Operation.CONTAINS


class And(FilterOperator[Filter]):
    operation = Operation.AND


class Or(FilterOperator[Filter]):
    operation = Operation.OR


class Not(FilterOperator[Filter]):
    arity = 1
    operation = Operation.NOT


def _flatten(a: Filter, b: Filter, cls: type[And] | type[Or]) -> tuple[Filter, ...]:
    out: list[Filter] = []
    for node in (a, b):
        if isinstance(node, cls):
            out.extend(node.operands)
        else:
            out.append(node)
    return tuple(out)


@dataclass(kw_only=True)
class FilterBackend[V](Backend[object, Operation, V], ABC):
    """Computes each filter operator through an `Operation` mapping.

    `cast` receives a `Field` for field references, and the raw value for constants.
    """

    def __post_init__(self) -> None:
        missing = set(Operation) - self.operations.keys()
        if missing:
            names = sorted(operation.name for operation in missing)
            raise TypeError(f"{type(self).__name__} does not implement {names}")
