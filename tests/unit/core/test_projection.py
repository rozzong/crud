from dataclasses import dataclass

import pytest

from crud import Projection, RecordError


@dataclass(frozen=True)
class Birth(Projection):
    name: str
    """Person's name."""

    born_on: str
    """Date of birth."""


@dataclass(frozen=True)
class FullBirth(Birth):
    place: str
    """Place of birth."""


def test_fields_are_the_dataclass_fields_in_order() -> None:
    assert Birth.get_fields() == ("name", "born_on")


def test_fields_are_cached_per_class() -> None:
    assert Birth.get_fields() is Birth.get_fields()
    assert FullBirth.get_fields() == ("name", "born_on", "place")


@dataclass(frozen=True)
class Adult(Projection):
    age: int
    """Age in years, at least 18."""

    def __post_init__(self) -> None:
        if self.age < 18:
            raise ValueError("not an adult")


def test_build_makes_the_projection_from_its_fields() -> None:
    assert Birth.build({"name": "Ada", "born_on": "1815-12-10"}) == Birth("Ada", "1815-12-10")


def test_build_raises_record_error_when_the_values_do_not_fit() -> None:
    with pytest.raises(RecordError, match="Cannot build Adult") as raised:
        Adult.build({"age": 12})
    assert isinstance(raised.value.__cause__, ValueError)
