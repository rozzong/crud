import operator
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, override

import pytest

from crud import (
    And,
    Computation,
    Constant,
    Contains,
    Eq,
    Field,
    Filter,
    FilterBackend,
    Gt,
    In,
    Le,
    Not,
    Operation,
    Or,
)

A = Field("a") == 1
B = Field("b") > 2
C = Field("c").contains("x")


def _binary(compute: Callable[[Any, Any], bool]) -> Computation[Any]:
    def apply(values: Iterable[Any]) -> bool:
        left, right = values
        return compute(left, right)

    return apply


def _not(values: Iterable[Any]) -> bool:
    (operand,) = values
    return not operand


# Record values are arbitrary Python objects, so this backend is typed with `Any`.
@dataclass(kw_only=True)
class DictBackend(FilterBackend[Any]):
    """Evaluates a filter against one in-memory record."""

    record: Mapping[str, Any]
    """The record; dotted paths index into nested mappings."""

    @override
    def _make_operations(self) -> Mapping[Operation, Computation[Any]]:
        return {
            Operation.EQ: _binary(operator.eq),
            Operation.NE: _binary(operator.ne),
            Operation.LT: _binary(operator.lt),
            Operation.LE: _binary(operator.le),
            Operation.GT: _binary(operator.gt),
            Operation.GE: _binary(operator.ge),
            Operation.IN: _binary(lambda value, values: value in values),
            Operation.CONTAINS: _binary(operator.contains),
            Operation.AND: all,
            Operation.OR: any,
            Operation.NOT: _not,
        }

    @override
    def cast(self, value: object) -> Any:
        if not isinstance(value, Field):
            return value
        found: Any = self.record
        for key in value.path:
            found = found[key]
        return found


def test_operators_build_filters() -> None:
    assert (Field("a") <= 3) == Le(operands=(Field("a"), Constant(3)))
    assert Field("a").contains("x") == Contains(operands=(Field("a"), Constant("x")))
    assert Field("a").in_([1, 2]) == In(operands=(Field("a"), Constant((1, 2))))


def test_field_to_field_comparison() -> None:
    assert (Field("a") > Field("b")) == Gt(operands=(Field("a"), Field("b")))


def test_reflected_comparison_keeps_field_first() -> None:
    assert (5 < Field("a")) == Gt(operands=(Field("a"), Constant(5)))


def test_in_accepts_any_iterable() -> None:
    assert Field("a").in_(i for i in range(3)).operands[1] == Constant((0, 1, 2))


def test_fields_still_work_in_containers() -> None:
    assert Field("a") == Field("a")
    assert Field("a") != Field("b")
    assert Field("a") in {Field("a")}
    assert Field("a") not in [Field("b")]
    assert Eq(operands=(Field("a"), Constant(1))) != Eq(operands=(Field("a"), Field("a")))


def test_filters_have_no_truth_value() -> None:
    with pytest.raises(TypeError, match="no truth value"):
        bool(Field("a") > 1)
    with pytest.raises(TypeError, match="no truth value"):
        _ = (Field("a") > 1) and (Field("b") > 2)


def test_and_or_flatten() -> None:
    assert A & B & C == And(operands=(A, B, C))
    assert A | B | C == Or(operands=(A, B, C))
    assert (A & B) | C == Or(operands=(And(operands=(A, B)), C))


def test_invert_wraps_in_not() -> None:
    assert ~A == Not(operands=(A,))


def test_comparisons_check_arity() -> None:
    with pytest.raises(ValueError, match="Eq takes 2 operands"):
        Eq(operands=(Field("a"),))


def test_filters_are_hashable() -> None:
    assert hash(A & B) == hash((Field("a") == 1) & (Field("b") > 2))
    assert len({A & B, (Field("a") == 1) & (Field("b") > 2)}) == 1


RECORD = {"a": 1, "b": 5, "c": "xyz", "d": 5, "team": {"name": "Avengers"}}


@pytest.mark.parametrize(
    ("filter", "expected"),
    [
        (A & B & C, True),
        (A & ~B, False),
        (~A | B, True),
        (Field("a").in_([2, 3]), False),
        (Field("team", "name") == "Avengers", True),
        ((Field("b") <= 4) | Field("c").contains("q"), False),
        (Field("b") == Field("d"), True),
        (Field("a") >= Field("b"), False),
    ],
)
def test_dict_backend(filter: Filter, expected: bool) -> None:
    assert filter.evaluate(DictBackend(record=RECORD)) is expected


def test_operands_are_computed_lazily() -> None:
    # `all` stops at the first false operand, so the missing field is never read.
    lazy = (Field("a") == 0) & (Field("missing") == 1)
    assert lazy.evaluate(DictBackend(record=RECORD)) is False
    with pytest.raises(KeyError):
        (~lazy.operands[0] & lazy.operands[1]).evaluate(DictBackend(record=RECORD))


def test_backend_must_cover_every_operation() -> None:
    @dataclass(kw_only=True)
    class Partial(DictBackend):
        @override
        def _make_operations(self) -> Mapping[Operation, Computation[Any]]:
            return {Operation.EQ: _binary(operator.eq)}

    with pytest.raises(TypeError, match="Partial does not implement \\['AND', "):
        Partial(record=RECORD)
