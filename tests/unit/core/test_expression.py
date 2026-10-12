from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import override

import pytest

from crud import Atom, Backend, Computation, Expression, Operator


@dataclass(frozen=True)
class Num(Atom[int, type]):
    value: int
    """The number."""

    @override
    def _get_value(self) -> int:
        return self.value


@dataclass(frozen=True)
class Var(Atom["Var", type]):
    name: str
    """The variable's name, looked up in the backend's environment."""

    @override
    def _get_value(self) -> "Var":
        return self


class Arithmetic(Operator[int | Var, type, Expression[int | Var, type]]):
    """Keyed by its own class, so the backend needs no enum."""

    @override
    def _get_key(self) -> type:
        return type(self)


class Neg(Arithmetic):
    arity = 1


class Sub(Arithmetic):
    arity = 2


class Sum(Arithmetic): ...


class Unknown(Arithmetic): ...


def _negate(values: Iterable[int]) -> int:
    (operand,) = values
    return -operand


def _subtract(values: Iterable[int]) -> int:
    left, right = values
    return left - right


@dataclass
class Calculator(Backend[int | Var, type, int]):
    env: dict[str, int]
    """Variable values."""

    @override
    def _make_operations(self) -> Mapping[type, Computation[int]]:
        return {Neg: _negate, Sub: _subtract, Sum: sum}

    @override
    def cast(self, value: int | Var) -> int:
        return self.env[value.name] if isinstance(value, Var) else value


# 10 - (-(1 + x + 3))
TREE = Sub(operands=(Num(10), Neg(operands=(Sum(operands=(Num(1), Var("x"), Num(3))),))))


def test_children_are_operands() -> None:
    assert Num(1).children == ()
    assert TREE.children == TREE.operands


def test_nodes_are_hashable_and_compare_by_value() -> None:
    copy = Sub(operands=(Num(10), Neg(operands=(Sum(operands=(Num(1), Var("x"), Num(3))),))))
    assert copy == TREE
    assert hash(copy) == hash(TREE)
    assert Sub(operands=(Num(1), Num(2))) != Sum(operands=(Num(1), Num(2)))


def test_evaluate_computes_bottom_up() -> None:
    assert TREE.evaluate(Calculator(env={"x": 2})) == 16


def test_arity_is_checked_on_construction() -> None:
    with pytest.raises(ValueError, match="Neg takes 1 operands, got 2"):
        Neg(operands=(Num(1), Num(2)))


def test_backend_rejects_unknown_operator() -> None:
    with pytest.raises(TypeError, match="Calculator cannot compute operation*"):
        Unknown(operands=()).evaluate(Calculator(env={}))
