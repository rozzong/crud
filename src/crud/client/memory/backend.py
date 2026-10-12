from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import override

from crud.core import filter as f
from crud.core.expression import Computation

from .database import InMemoryDatabase, InMemoryRelationship, InMemorySession, InMemoryTable, Row
from .errors import InMemoryQueryError


@dataclass(frozen=True)
class InMemoryHop:
    """A relationship crossed by a field path."""

    name: str
    """Qualified relationship name, such as `hero.team`."""

    relationship: InMemoryRelationship
    """The relationship crossed."""


@dataclass(frozen=True)
class InMemoryColumn:
    """A `Field`, resolved to the column it ends on."""

    name: str
    """The column at the end of the path."""

    hops: tuple[InMemoryHop, ...] = ()
    """Relationships crossed to reach the column, outermost first."""


@dataclass(frozen=True)
class InMemoryValue:
    """A constant."""

    value: object
    """The Python value."""


type Truth = bool | None
"""SQL's three-valued logic: `None` is unknown, as when comparing to `None`."""


@dataclass(frozen=True)
class InMemoryCondition:
    """A computed `Filter`: it matches the records for which `test` returns `True`."""

    test: Callable[[InMemorySession, Row], Truth]
    """Test a record, looking up the records it relates to in the session."""


type InMemoryTerm = InMemoryColumn | InMemoryValue | InMemoryCondition


def _to_condition(term: InMemoryTerm) -> InMemoryCondition:
    if not isinstance(term, InMemoryCondition):
        raise InMemoryQueryError(f"Expected a condition, got {type(term).__name__}")
    return term


def _compute_and(values: Iterable[InMemoryTerm]) -> InMemoryTerm:
    conditions = tuple(map(_to_condition, values))

    def test(session: InMemorySession, row: Row) -> Truth:
        truths = [condition.test(session, row) for condition in conditions]
        if False in truths:
            return False
        return None if None in truths else True

    return InMemoryCondition(test)


def _compute_or(values: Iterable[InMemoryTerm]) -> InMemoryTerm:
    conditions = tuple(map(_to_condition, values))

    def test(session: InMemorySession, row: Row) -> Truth:
        truths = [condition.test(session, row) for condition in conditions]
        if True in truths:
            return True
        return None if None in truths else False

    return InMemoryCondition(test)


def _compute_not(values: Iterable[InMemoryTerm]) -> InMemoryTerm:
    (operand,) = values
    condition = _to_condition(operand)

    def test(session: InMemorySession, row: Row) -> Truth:
        truth = condition.test(session, row)
        return None if truth is None else not truth

    return InMemoryCondition(test)


def _merge_hops(a: tuple[InMemoryHop, ...], b: tuple[InMemoryHop, ...]) -> tuple[InMemoryHop, ...]:
    """Return the hops that reach both columns: one path must extend the other."""
    shorter, longer = sorted((a, b), key=len)
    if longer[: len(shorter)] != shorter:
        raise InMemoryQueryError("Cannot compare fields reached through different relationships")
    return longer


def _walk(
    session: InMemorySession, row: Row, hops: Sequence[InMemoryHop]
) -> Iterator[tuple[Row, ...]]:
    """Yield every chain of related records `hops` leads to, starting with `row` itself."""
    if not hops:
        yield (row,)
        return
    relationship = hops[0].relationship
    value = row[relationship.local]
    if value is None:
        return
    for related in session.tables[relationship.table].rows:
        if related[relationship.remote] == value:
            for chain in _walk(session, related, hops[1:]):
                yield (row, *chain)


def _make_comparison(
    compare: Callable[[object, object], Truth],
    compare_to_none: Callable[[object], bool] | None = None,
) -> Computation[InMemoryTerm]:
    """Build a computation that applies `compare` to a field and a field or a constant.

    As in SQL, a comparison involving `None` is unknown, but `compare_to_none` may handle
    comparing to a `None` constant, as `IS NULL` does. Across relationship hops, the
    comparison matches when any chain of related records does, as `EXISTS` does.
    """

    def compare_values(left: object, right: object) -> Truth:
        if left is None or right is None:
            return None
        try:
            return compare(left, right)
        except TypeError as error:
            raise InMemoryQueryError(f"Cannot compare {left!r} to {right!r}") from error

    def compute(values: Iterable[InMemoryTerm]) -> InMemoryTerm:
        left, right = values
        if not isinstance(left, InMemoryColumn):
            raise InMemoryQueryError("A comparison takes a field first")
        match right:
            case InMemoryColumn():
                hops = _merge_hops(left.hops, right.hops)
            case InMemoryValue():
                hops = left.hops
            case InMemoryCondition():
                raise InMemoryQueryError("Cannot compare a field to a condition")

        def test_chain(chain: tuple[Row, ...]) -> Truth:
            value = chain[len(left.hops)][left.name]
            match right:
                case InMemoryColumn():
                    return compare_values(value, chain[len(right.hops)][right.name])
                case InMemoryValue(value=None) if compare_to_none is not None:
                    return compare_to_none(value)
                case _:
                    return compare_values(value, right.value)

        def test(session: InMemorySession, row: Row) -> Truth:
            chains = _walk(session, row, hops)
            if not hops:
                return test_chain(next(chains))
            return any(test_chain(chain) is True for chain in chains)

        return InMemoryCondition(test)

    return compute


def _compare_in(value: object, values: object) -> Truth:
    if not isinstance(values, tuple):
        raise InMemoryQueryError(f"`in_` takes a tuple of values, got {type(values).__name__}")
    if value in values:
        return True
    # As in SQL, a value missing from values that include `None` is unknown.
    return None if None in values else False


def _contains(value: object, part: object) -> bool:
    if not isinstance(value, str) or not isinstance(part, str):
        raise InMemoryQueryError(f"`contains` takes strings, got {value!r} and {part!r}")
    return part in value


def _less_than(a: object, b: object) -> bool:
    return a < b  # ty: ignore[unsupported-operator]


def _less_or_equal(a: object, b: object) -> bool:
    return a <= b  # ty: ignore[unsupported-operator]


def _greater_than(a: object, b: object) -> bool:
    return a > b  # ty: ignore[unsupported-operator]


def _greater_or_equal(a: object, b: object) -> bool:
    return a >= b  # ty: ignore[unsupported-operator]


@dataclass(kw_only=True)
class InMemoryBackend(f.FilterBackend[InMemoryTerm]):
    """Computes a `Filter` into a predicate on the records of one table."""

    database: InMemoryDatabase
    """The database holding the tables relationships lead to."""

    table: InMemoryTable
    """The table the filter's field paths start from."""

    def _resolve_field(self, field: f.Field) -> InMemoryColumn:
        table = self.table
        *relationship_names, column_name = field.path
        hops: list[InMemoryHop] = []
        for name in relationship_names:
            relationship = table.get_relationship(name)
            hops.append(InMemoryHop(name=f"{table.name}.{name}", relationship=relationship))
            table = self.database.get_table(relationship.table)
        return InMemoryColumn(name=table.get_column(column_name), hops=tuple(hops))

    @override
    def _make_operations(self) -> Mapping[f.Operation, Computation[InMemoryTerm]]:
        return {
            f.Operation.EQ: _make_comparison(lambda a, b: a == b, lambda a: a is None),
            f.Operation.NE: _make_comparison(lambda a, b: a != b, lambda a: a is not None),
            f.Operation.LT: _make_comparison(_less_than),
            f.Operation.LE: _make_comparison(_less_or_equal),
            f.Operation.GT: _make_comparison(_greater_than),
            f.Operation.GE: _make_comparison(_greater_or_equal),
            f.Operation.IN: _make_comparison(_compare_in),
            f.Operation.CONTAINS: _make_comparison(_contains),
            f.Operation.AND: _compute_and,
            f.Operation.OR: _compute_or,
            f.Operation.NOT: _compute_not,
        }

    @override
    def cast(self, value: object) -> InMemoryTerm:
        if isinstance(value, f.Field):
            return self._resolve_field(value)
        return InMemoryValue(value)
