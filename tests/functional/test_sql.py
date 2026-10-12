"""`SQLClient` tests: the shared contract and SQL-specific behaviour, on every SQL database."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, override

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from crud import (
    Blueprint,
    Field,
    Filter,
    Order,
    SQLClient,
    SQLConstraintError,
    SQLFieldError,
    SQLQueryError,
    SQLStorageError,
)

from .backends.sql import (
    Hero,
    SQLStorageBackend,
    open_postgresql,
    open_sqlite_file,
    open_sqlite_memory,
)
from .contract import CRUDClientContract
from .data import HeroId, HeroPower, HeroTeam, Named, SetPower


@dataclass(frozen=True)
class AgelessHero(Blueprint):
    name: str
    """The hero's name, but no age, which the table requires."""


@dataclass(frozen=True)
class PowerfulHero(Blueprint):
    power: str
    """Not a hero field."""


class TestSQLClient(CRUDClientContract):
    @pytest.fixture(
        params=[open_sqlite_memory, open_sqlite_file, open_postgresql],
        ids=["sqlite-memory", "sqlite-file", "postgresql"],
    )
    @override
    def empty_backend(
        self, request: pytest.FixtureRequest, tmp_path: Path
    ) -> Iterator[SQLStorageBackend]:
        with request.param(tmp_path) as engine:
            yield SQLStorageBackend(engine=engine)

    @pytest.fixture
    @override
    def other_backend(self, tmp_path: Path) -> Iterator[SQLStorageBackend]:
        with open_sqlite_memory(tmp_path) as engine:
            yield SQLStorageBackend(engine=engine)

    @pytest.mark.parametrize(
        ("filter", "message"),
        [
            (Field("power") == 1, "Hero has no field 'power'"),
            (Field("team", "power") == 1, "Team has no field 'power'"),
            (Field("name", "length") == 1, "Hero.name is not a relationship"),
            (Field("team") == 1, "Hero.team is not a column"),
        ],
    )
    def test_bad_field_path_names_the_culprit(
        self, backend: SQLStorageBackend, filter: Filter, message: str
    ) -> None:
        with pytest.raises(SQLFieldError, match=message):
            backend.heroes.read(filter, Named)

    def test_update_names_unknown_fields(self, backend: SQLStorageBackend) -> None:
        with pytest.raises(SQLFieldError, match="Hero has no field 'power'"):
            backend.heroes.update(Field("name") == "Thor", SetPower(power="thunder"))

    def test_order_by_related_field_raises(self, backend: SQLStorageBackend) -> None:
        with pytest.raises(SQLQueryError, match="Cannot order by related field 'team.name'"):
            backend.heroes.read(None, Named, order_by=[Order(field=Field("team", "name"))])

    @pytest.mark.parametrize(
        ("shape", "message"),
        [(HeroPower, "Hero has no field 'power'"), (HeroTeam, "Hero.team is not a column")],
    )
    def test_read_names_the_culprit(
        self, backend: SQLStorageBackend, shape: type[Any], message: str
    ) -> None:
        with pytest.raises(SQLFieldError, match=message):
            backend.heroes.read(None, shape)

    def test_create_without_a_required_field_fails(self, backend: SQLStorageBackend) -> None:
        client = SQLClient(
            blueprint_cls=AgelessHero, key_cls=HeroId, model_cls=Hero, engine=backend.engine
        )
        with pytest.raises(SQLConstraintError) as raised:
            client.create([AgelessHero(name="Wanda")])
        assert isinstance(raised.value.__cause__, IntegrityError)

    def test_constraint_error_in_a_transaction_rolls_it_back(
        self, backend: SQLStorageBackend
    ) -> None:
        heroes = backend.heroes
        client = SQLClient(
            blueprint_cls=AgelessHero, key_cls=HeroId, model_cls=Hero, engine=backend.engine
        )
        with pytest.raises(SQLConstraintError), heroes.transaction() as transaction:
            heroes.destroy(Field("name") == "Thor", transaction=transaction)
            client.create([AgelessHero(name="Wanda")], transaction=transaction)
        assert len(heroes.read(Field("name") == "Thor", Named)) == 1

    def test_database_failure_raises_storage_error(self, backend: SQLStorageBackend) -> None:
        Hero.__table__.drop(backend.engine)  # ty: ignore[unresolved-attribute]
        with pytest.raises(SQLStorageError) as raised:
            backend.heroes.read(None, Named)
        assert isinstance(raised.value.__cause__, SQLAlchemyError)

    def test_create_names_unknown_fields(self, backend: SQLStorageBackend) -> None:
        client = SQLClient(
            blueprint_cls=PowerfulHero, key_cls=HeroId, model_cls=Hero, engine=backend.engine
        )
        with pytest.raises(SQLFieldError, match="Hero has no field 'power'"):
            client.create([PowerfulHero(power="thunder")])
