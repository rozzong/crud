"""CRUD behaviour every client must share, written once and inherited by each client's tests.

To test a client, subclass `CRUDClientContract` in a `Test*` class and implement its
`empty_backend` and `other_backend` fixtures: every test case below then runs on that client.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, override

import pytest
from pydantic import BaseModel

from crud import (
    Blueprint,
    CRUDClient,
    Field,
    FieldError,
    Filter,
    Order,
    Projection,
    RecordError,
    TransactionError,
)

from .backends import StorageBackend
from .data import (
    HERO_NAMES,
    HEROES,
    TEAMS,
    HeroAge,
    HeroData,
    HeroId,
    HeroPower,
    HeroTeam,
    Named,
    SetAge,
    SetPower,
    SetStrength,
)

WANDA = HeroData(name="Wanda", age=30, strength=70, joined=2015)


@dataclass(frozen=True)
class HeroStats(Projection):
    id: object
    """The hero's primary key, whatever its type on the backend."""

    age: int
    """The hero's age."""

    strength: int
    """The hero's strength."""


class HeroAgeModel(BaseModel, Projection):
    name: str
    age: int

    @classmethod
    @override
    def _get_fields(cls) -> Sequence[str]:
        return tuple(cls.model_fields)


class NotADataclass(Projection):
    """A projection that neither is a dataclass nor says what its fields are."""


def _read_names[B: Blueprint, K: Projection](
    client: CRUDClient[B, K], filter: Filter | None = None
) -> set[str]:
    return {item.name for item in client.read(filter, Named)}


class CRUDClientContract(ABC):
    """The test cases every client must pass, run on the backend of the subclass."""

    @pytest.fixture
    @abstractmethod
    def empty_backend(
        self, request: pytest.FixtureRequest, tmp_path: Path
    ) -> Iterator[StorageBackend]:
        """Fixture opening a backend with no records, and cleaning it up afterwards.

        Implement it as a pytest fixture, parametrized to run on several storages if need be.
        `tmp_path` is a temporary directory the backend may use.
        """

    @pytest.fixture
    @abstractmethod
    def other_backend(self, tmp_path: Path) -> Iterator[StorageBackend]:
        """Fixture opening a backend on another storage than `empty_backend`'s."""

    @pytest.fixture
    def backend(self, empty_backend: StorageBackend) -> StorageBackend:
        """The backend of the subclass, seeded with the records every test case expects."""
        empty_backend.seed(TEAMS, HEROES)
        return empty_backend

    def test_create_stores_items(self, backend: StorageBackend) -> None:
        (key,) = backend.heroes.create([backend.make_hero(WANDA)])
        (wanda,) = backend.heroes.read(Field("name") == "Wanda", HeroStats)
        assert key == HeroId(id=wanda.id)
        assert (wanda.age, wanda.strength) == (WANDA.age, WANDA.strength)

    def test_create_returns_keys_in_the_order_of_items(self, backend: StorageBackend) -> None:
        names = [f"Hero {index}" for index in range(10)]
        keys = backend.heroes.create(
            backend.make_hero(HeroData(name=name, age=20, strength=10, joined=2000))
            for name in reversed(names)
        )
        for key, name in zip(keys, reversed(names), strict=True):
            (named,) = backend.heroes.read(Field("id") == key.id, Named)
            assert named.name == name

    def test_create_nothing_returns_no_keys(self, backend: StorageBackend) -> None:
        assert backend.heroes.create([]) == []

    def test_read_without_filter_returns_everything(self, backend: StorageBackend) -> None:
        assert _read_names(backend.heroes) == HERO_NAMES

    @pytest.mark.parametrize("shape", [HeroAge, HeroAgeModel])
    def test_read_returns_the_shape(self, backend: StorageBackend, shape: type[Any]) -> None:
        assert backend.heroes.read(Field("name") == "Natasha", shape) == [
            shape(name="Natasha", age=35)
        ]

    def test_read_rejects_projection_without_fields(self, backend: StorageBackend) -> None:
        with pytest.raises(RecordError, match="NotADataclass is not a dataclass"):
            backend.heroes.read(None, NotADataclass)

    @pytest.mark.parametrize("shape", [HeroPower, HeroTeam])
    def test_read_rejects_non_column_fields(
        self, backend: StorageBackend, shape: type[Any]
    ) -> None:
        with pytest.raises(FieldError):
            backend.heroes.read(None, shape)

    @pytest.mark.parametrize(
        ("filter", "expected"),
        [
            (Field("age") == 35, {"Natasha"}),
            (Field("age") != 35, {"Thor", "Logan", "Peter"}),
            (Field("age") < 35, {"Peter"}),
            (Field("age") <= 35, {"Peter", "Natasha"}),
            (Field("age") > 190, {"Thor"}),
            (Field("age") >= 190, {"Thor", "Logan"}),
            (Field("name").in_(["Thor", "Peter", "Nobody"]), {"Thor", "Peter"}),
            (Field("name").contains("ta"), {"Natasha"}),
            ((Field("age") > 20) & (Field("age") < 200), {"Natasha", "Logan"}),
            ((Field("age") < 20) | (Field("age") > 1000), {"Peter", "Thor"}),
            (~(Field("name") == "Thor"), {"Natasha", "Logan", "Peter"}),
            (~((Field("age") < 20) | (Field("name") == "Thor")) & (Field("age") > 40), {"Logan"}),
        ],
    )
    def test_filters(self, backend: StorageBackend, filter: Filter, expected: set[str]) -> None:
        assert _read_names(backend.heroes, filter) == expected

    @pytest.mark.parametrize(
        ("filter", "expected"),
        [
            (Field("strength") > Field("age"), {"Peter"}),
            (Field("joined") == Field("team", "founded"), {"Thor", "Logan"}),
            (Field("team", "founded") < Field("joined"), {"Natasha"}),
        ],
    )
    def test_field_to_field(
        self, backend: StorageBackend, filter: Filter, expected: set[str]
    ) -> None:
        assert _read_names(backend.heroes, filter) == expected

    def test_dotted_path_to_one(self, backend: StorageBackend) -> None:
        assert _read_names(backend.heroes, Field("team", "name") == "Avengers") == {
            "Thor",
            "Natasha",
        }

    def test_dotted_path_to_many(self, backend: StorageBackend) -> None:
        assert _read_names(backend.teams, Field("heroes", "age") > 1000) == {"Avengers"}

    def test_field_to_field_across_to_many(self, backend: StorageBackend) -> None:
        teams = _read_names(backend.teams, Field("heroes", "joined") > Field("founded"))
        assert teams == {"Avengers"}

    @pytest.mark.parametrize(
        "filter",
        [
            Field("power") == 1,
            Field("team", "power") == 1,
            Field("name", "length") == 1,
            Field("team") == 1,
        ],
    )
    def test_bad_field_path_raises(self, backend: StorageBackend, filter: Filter) -> None:
        with pytest.raises(FieldError):
            backend.heroes.read(filter, Named)

    @pytest.mark.parametrize("field", [Field("power"), Field("team")])
    def test_order_by_unknown_field_raises(self, backend: StorageBackend, field: Field) -> None:
        with pytest.raises(FieldError):
            backend.heroes.read(None, Named, order_by=[Order(field=field)])

    def test_order_and_limit(self, backend: StorageBackend) -> None:
        by_age = backend.heroes.read(
            None, HeroAge, order_by=[Order(field=Field("age"), is_descending=True)], limit=2
        )
        assert by_age == [HeroAge(name="Thor", age=1500), HeroAge(name="Logan", age=190)]
        by_name = backend.heroes.read(None, Named, order_by=[Order(field=Field("name"))])
        assert [hero.name for hero in by_name] == sorted(HERO_NAMES)

    @pytest.mark.parametrize(
        ("filter", "count"),
        [(Field("name") == "Nobody", 0), (Field("name") == "Thor", 1), (Field("age") > 100, 2)],
    )
    def test_update_returns_count(
        self, backend: StorageBackend, filter: Filter, count: int
    ) -> None:
        assert backend.heroes.update(filter, SetStrength(strength=1)) == count
        assert len(backend.heroes.read(Field("strength") == 1, Named)) == count

    def test_update_can_change_the_filtered_field(self, backend: StorageBackend) -> None:
        assert backend.heroes.update(Field("age") > 100, SetAge(age=99)) == 2
        assert _read_names(backend.heroes, Field("age") == 99) == {"Thor", "Logan"}

    def test_update_rejects_unknown_field(self, backend: StorageBackend) -> None:
        with pytest.raises(FieldError):
            backend.heroes.update(Field("name") == "Thor", SetPower(power="thunder"))

    @pytest.mark.parametrize(
        ("filter", "count"),
        [(Field("name") == "Nobody", 0), (Field("name") == "Thor", 1), (Field("age") > 30, 3)],
    )
    def test_destroy_returns_count(
        self, backend: StorageBackend, filter: Filter, count: int
    ) -> None:
        assert backend.heroes.destroy(filter) == count
        assert len(backend.heroes.read(None, Named)) == len(HEROES) - count

    def test_transaction_rolls_back_on_error(self, backend: StorageBackend) -> None:
        heroes = backend.heroes
        with pytest.raises(RuntimeError), heroes.transaction() as transaction:
            heroes.destroy(Field("name") == "Thor", transaction=transaction)
            heroes.create([backend.make_hero(WANDA)], transaction=transaction)
            raise RuntimeError
        assert _read_names(heroes) == HERO_NAMES

    def test_transaction_commits_on_success(self, backend: StorageBackend) -> None:
        heroes = backend.heroes
        with heroes.transaction() as transaction:
            heroes.destroy(Field("name") == "Thor", transaction=transaction)
            heroes.update(Field("name") == "Peter", SetAge(age=18), transaction=transaction)
        assert _read_names(heroes) == HERO_NAMES - {"Thor"}
        assert heroes.read(Field("name") == "Peter", HeroAge) == [HeroAge(name="Peter", age=18)]

    def test_transaction_spans_clients_on_the_same_storage(self, backend: StorageBackend) -> None:
        with pytest.raises(RuntimeError), backend.teams.transaction() as transaction:
            backend.heroes.destroy(Field("name") == "Thor", transaction=transaction)
            raise RuntimeError
        assert _read_names(backend.heroes) == HERO_NAMES

    def test_transaction_rejects_a_client_on_another_storage(
        self, backend: StorageBackend, other_backend: StorageBackend
    ) -> None:
        with pytest.raises(TransactionError), other_backend.heroes.transaction() as transaction:
            backend.heroes.destroy(Field("name") == "Thor", transaction=transaction)
        assert _read_names(backend.heroes) == HERO_NAMES
