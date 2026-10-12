"""Behaviour specific to `InMemoryClient`, on top of the contract every client shares."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import override

import pytest

from crud import (
    Blueprint,
    Field,
    Filter,
    InMemoryClient,
    InMemoryConflictError,
    InMemoryConstraintError,
    InMemoryDatabase,
    InMemoryFieldError,
    InMemoryQueryError,
    InMemoryRelationship,
    InMemoryTable,
    Order,
)

from .backends.memory import InMemoryStorageBackend
from .contract import CRUDClientContract
from .data import HEROES, TEAMS, HeroAge, HeroId, Named, SetAge


class TestInMemoryClient(CRUDClientContract):
    @pytest.fixture
    @override
    def empty_backend(
        self, request: pytest.FixtureRequest, tmp_path: Path
    ) -> Iterator[InMemoryStorageBackend]:
        yield InMemoryStorageBackend()

    @pytest.fixture
    @override
    def other_backend(self, tmp_path: Path) -> Iterator[InMemoryStorageBackend]:
        yield InMemoryStorageBackend()


@pytest.fixture
def memory_backend() -> InMemoryStorageBackend:
    backend = InMemoryStorageBackend()
    backend.seed(TEAMS, HEROES)
    return backend


@dataclass(frozen=True)
class AgelessHero(Blueprint):
    name: str
    """The hero's name, but no age, which the table requires."""


@dataclass(frozen=True)
class NumberedHero(Blueprint):
    id: int
    """A primary key chosen by the caller."""

    name: str
    """Unique hero name."""

    age: int
    """Age in years."""

    strength: int
    """Strength score."""

    joined: int
    """Year the hero joined their team, or started out if they have none."""


@dataclass(frozen=True)
class HeroTeamId(Named):
    team_id: object
    """The hero's team key, `None` when the hero has none."""


def _make_client[B: Blueprint](
    backend: InMemoryStorageBackend, blueprint_cls: type[B]
) -> InMemoryClient[B, HeroId]:
    return InMemoryClient(
        blueprint_cls=blueprint_cls, key_cls=HeroId, database=backend.database, table_name="hero"
    )


def _numbered(id: int, name: str) -> NumberedHero:
    return NumberedHero(id=id, name=name, age=20, strength=10, joined=2000)


@pytest.mark.parametrize(
    ("filter", "message"),
    [
        (Field("power") == 1, "hero has no field 'power'"),
        (Field("team", "power") == 1, "team has no field 'power'"),
        (Field("name", "length") == 1, "hero.name is not a relationship"),
        (Field("team") == 1, "hero.team is not a column"),
    ],
)
def test_bad_field_path_names_the_culprit(
    memory_backend: InMemoryStorageBackend, filter: Filter, message: str
) -> None:
    with pytest.raises(InMemoryFieldError, match=message):
        memory_backend.heroes.read(filter, Named)


def test_order_by_related_field_raises(memory_backend: InMemoryStorageBackend) -> None:
    with pytest.raises(InMemoryQueryError, match="Cannot order by related field 'team.name'"):
        memory_backend.heroes.read(None, Named, order_by=[Order(field=Field("team", "name"))])


@pytest.mark.parametrize(
    ("filter", "expected"),
    [
        (Field("team_id") == None, {"Peter"}),  # noqa: E711
        (Field("team_id") != None, {"Thor", "Natasha", "Logan"}),  # noqa: E711
        # As in SQL, comparing to a missing value is unknown, and so is its negation.
        (Field("team_id") != 1, {"Logan"}),
        (~(Field("team_id") == 1), {"Logan"}),
        (Field("team_id").in_([2, None]), {"Logan"}),
        (~Field("team_id").in_([2, None]), set()),
        (~(Field("team", "founded") > 1970), {"Thor", "Natasha", "Peter"}),
    ],
)
def test_missing_values_follow_sql(
    memory_backend: InMemoryStorageBackend, filter: Filter, expected: set[str]
) -> None:
    assert {hero.name for hero in memory_backend.heroes.read(filter, Named)} == expected


def test_missing_values_sort_first(memory_backend: InMemoryStorageBackend) -> None:
    heroes = memory_backend.heroes.read(
        None, HeroTeamId, order_by=[Order(field=Field("team_id")), Order(field=Field("name"))]
    )
    assert [hero.name for hero in heroes] == ["Peter", "Natasha", "Thor", "Logan"]


def test_comparing_incomparable_values_raises(memory_backend: InMemoryStorageBackend) -> None:
    with pytest.raises(InMemoryQueryError, match="Cannot compare"):
        memory_backend.heroes.read(Field("name") > 3, Named)


def test_create_without_a_required_field_fails(memory_backend: InMemoryStorageBackend) -> None:
    client = _make_client(memory_backend, AgelessHero)
    with pytest.raises(InMemoryConstraintError, match="hero.age is required"):
        client.create([AgelessHero(name="Wanda")])


def test_create_keeps_given_keys_and_rejects_repeated_ones(
    memory_backend: InMemoryStorageBackend,
) -> None:
    client = _make_client(memory_backend, NumberedHero)
    assert client.create([_numbered(10, "Wanda")]) == [HeroId(id=10)]
    with pytest.raises(InMemoryConstraintError, match="hero.id 10 is repeated"):
        client.create([_numbered(10, "Vision")])
    # Generated keys carry on after the largest given one.
    (key,) = memory_backend.heroes.create([memory_backend.make_hero(HEROES[0])])
    assert key == HeroId(id=11)


def test_failed_write_in_a_transaction_changes_nothing(
    memory_backend: InMemoryStorageBackend,
) -> None:
    client = _make_client(memory_backend, NumberedHero)
    with client.transaction() as transaction:
        with pytest.raises(InMemoryConstraintError):
            client.create(
                [_numbered(20, "Wanda"), _numbered(20, "Vision")], transaction=transaction
            )
        client.create([_numbered(21, "Vision")], transaction=transaction)
    names = {hero.name for hero in memory_backend.heroes.read(None, Named)}
    assert names == {hero.name for hero in HEROES} | {"Vision"}


def test_transactions_see_their_own_writes_only(memory_backend: InMemoryStorageBackend) -> None:
    heroes = memory_backend.heroes
    with heroes.transaction() as transaction:
        heroes.update(Field("name") == "Peter", SetAge(age=18), transaction=transaction)
        assert heroes.read(Field("name") == "Peter", HeroAge, transaction=transaction)[0].age == 18
        assert heroes.read(Field("name") == "Peter", HeroAge)[0].age == 17


def test_concurrent_write_raises_conflict(memory_backend: InMemoryStorageBackend) -> None:
    heroes = memory_backend.heroes
    with pytest.raises(InMemoryConflictError), heroes.transaction() as transaction:
        heroes.update(Field("name") == "Peter", SetAge(age=18), transaction=transaction)
        heroes.update(Field("name") == "Thor", SetAge(age=1501))
    assert heroes.read(Field("name") == "Peter", HeroAge) == [HeroAge(name="Peter", age=17)]
    assert heroes.read(Field("name") == "Thor", HeroAge) == [HeroAge(name="Thor", age=1501)]


def test_read_only_transaction_never_conflicts(memory_backend: InMemoryStorageBackend) -> None:
    heroes = memory_backend.heroes
    with heroes.transaction() as transaction:
        heroes.read(None, Named, transaction=transaction)
        heroes.update(Field("name") == "Thor", SetAge(age=1501))


@pytest.mark.parametrize(
    ("table", "message"),
    [
        (InMemoryTable(name="hero", columns=("name",)), "the key 'id' is not a column"),
        (
            InMemoryTable(name="hero", columns=("id",), required=("name",)),
            "the required 'name' is not a column",
        ),
        (
            InMemoryTable(
                name="hero",
                columns=("id",),
                relationships={"team": InMemoryRelationship(table="team", local="id", remote="id")},
            ),
            "No table named 'team'",
        ),
        (
            InMemoryTable(
                name="hero",
                columns=("id",),
                relationships={"self": InMemoryRelationship(table="hero", local="x", remote="id")},
            ),
            "hero.self: 'x' is not a column",
        ),
    ],
)
def test_bad_schema_raises(table: InMemoryTable, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        InMemoryDatabase(tables=(table,))


def test_tables_are_independent_across_databases() -> None:
    first, second = InMemoryStorageBackend(), InMemoryStorageBackend()
    first.seed(TEAMS, HEROES)
    assert second.heroes.read(None, Named) == []
