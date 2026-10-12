from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import override

from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import ColumnProperty, PropComparator, QueryableAttribute, RelationshipProperty
from sqlalchemy.sql.expression import ColumnElement
from sqlmodel import SQLModel

from crud.core import filter as f
from crud.core.expression import Computation

from .errors import SQLFieldError, SQLQueryError

type Condition = ColumnElement[bool]

type Column = QueryableAttribute[object]


def _get_attribute(model_cls: type, name: str) -> Column:
    attribute = getattr(model_cls, name, None)
    if not isinstance(attribute, QueryableAttribute):
        raise SQLFieldError(f"{model_cls.__name__} has no field {name!r}")
    return attribute


def _get_column(model_cls: type, name: str) -> Column:
    attribute = _get_attribute(model_cls, name)
    if not isinstance(attribute.property, ColumnProperty):
        raise SQLFieldError(f"{model_cls.__name__}.{name} is not a column")
    return attribute


@dataclass(frozen=True)
class SQLHop:
    """A relationship crossed by a field path."""

    name: str
    """Qualified relationship name, such as `Hero.team`. Hops are compared by name."""

    comparator: PropComparator[object] = field(compare=False)
    """The relationship's comparator, which builds the `has`/`any` subquery."""

    is_to_many: bool
    """Whether the relationship holds a collection (`any`) rather than one row (`has`)."""


@dataclass(frozen=True)
class SQLColumn:
    """A `Field`, resolved to the column it ends on."""

    column: ColumnElement[object]
    """The column at the end of the path."""

    hops: tuple[SQLHop, ...] = ()
    """Relationships crossed to reach the column, outermost first."""


@dataclass(frozen=True)
class SQLValue:
    """A constant, kept raw so SQLAlchemy can bind it, or expand it for `in_`."""

    value: object
    """The Python value."""


@dataclass(frozen=True)
class SQLCondition:
    """A computed `Filter`."""

    clause: Condition
    """The boolean SQL expression."""


type SQLTerm = SQLColumn | SQLValue | SQLCondition


def _to_condition(term: SQLTerm) -> Condition:
    if not isinstance(term, SQLCondition):
        raise SQLQueryError(f"Expected a condition, got {type(term).__name__}")
    return term.clause


def _compute_and(values: Iterable[SQLTerm]) -> SQLTerm:
    return SQLCondition(and_(*map(_to_condition, values)))


def _compute_or(values: Iterable[SQLTerm]) -> SQLTerm:
    return SQLCondition(or_(*map(_to_condition, values)))


def _compute_not(values: Iterable[SQLTerm]) -> SQLTerm:
    (operand,) = values
    return SQLCondition(not_(_to_condition(operand)))


def _compare_in(column: ColumnElement[object], values: object) -> Condition:
    if not isinstance(values, tuple):
        raise SQLQueryError(f"`in_` takes a tuple of values, got {type(values).__name__}")
    return column.in_(values)


def _merge_hops(a: tuple[SQLHop, ...], b: tuple[SQLHop, ...]) -> tuple[SQLHop, ...]:
    """Return the hops that reach both columns: one path must extend the other."""
    shorter, longer = sorted((a, b), key=len)
    if longer[: len(shorter)] != shorter:
        raise SQLQueryError("Cannot compare fields reached through different relationships")
    return longer


def _make_comparison(
    compare: Callable[[ColumnElement[object], object], Condition],
) -> Computation[SQLTerm]:
    """Build a computation that applies `compare` to a field and a field or a constant.

    Each relationship hop wraps the condition in `has(...)` or `any(...)`, so a filter on
    a related field needs no explicit join.
    """

    def compute(values: Iterable[SQLTerm]) -> SQLTerm:
        left, right = values
        if not isinstance(left, SQLColumn):
            raise SQLQueryError("A comparison takes a field first")
        match right:
            case SQLColumn():
                other, hops = right.column, _merge_hops(left.hops, right.hops)
            case SQLValue():
                other, hops = right.value, left.hops
            case SQLCondition():
                raise SQLQueryError("Cannot compare a field to a condition")
        condition = compare(left.column, other)
        for hop in reversed(hops):
            comparator = hop.comparator
            condition = comparator.any(condition) if hop.is_to_many else comparator.has(condition)
        return SQLCondition(condition)

    return compute


@dataclass(kw_only=True)
class SQLBackend[M: SQLModel](f.FilterBackend[SQLTerm]):
    """Computes a `Filter` into a SQLAlchemy WHERE condition on one model."""

    model_cls: type[M]
    """The model the filter's field paths start from."""

    def _resolve_field(self, field: f.Field) -> SQLColumn:
        model_cls: type = self.model_cls
        *relationship_names, column_name = field.path
        hops: list[SQLHop] = []
        for name in relationship_names:
            attribute = _get_attribute(model_cls, name)
            relationship = attribute.property
            if not isinstance(relationship, RelationshipProperty):
                raise SQLFieldError(f"{model_cls.__name__}.{name} is not a relationship")
            hops.append(
                SQLHop(
                    name=f"{model_cls.__name__}.{name}",
                    comparator=attribute.comparator,
                    is_to_many=bool(relationship.uselist),
                )
            )
            model_cls = relationship.mapper.class_
        column = _get_column(model_cls, column_name).expression
        return SQLColumn(column=column, hops=tuple(hops))

    @override
    def _make_operations(self) -> Mapping[f.Operation, Computation[SQLTerm]]:
        return {
            f.Operation.EQ: _make_comparison(lambda column, value: column == value),
            f.Operation.NE: _make_comparison(lambda column, value: column != value),
            f.Operation.LT: _make_comparison(lambda column, value: column < value),
            f.Operation.LE: _make_comparison(lambda column, value: column <= value),
            f.Operation.GT: _make_comparison(lambda column, value: column > value),
            f.Operation.GE: _make_comparison(lambda column, value: column >= value),
            f.Operation.IN: _make_comparison(_compare_in),
            f.Operation.CONTAINS: _make_comparison(lambda column, value: column.contains(value)),
            f.Operation.AND: _compute_and,
            f.Operation.OR: _compute_or,
            f.Operation.NOT: _compute_not,
        }

    @override
    def cast(self, value: object) -> SQLTerm:
        if isinstance(value, f.Field):
            return self._resolve_field(value)
        return SQLValue(value)
