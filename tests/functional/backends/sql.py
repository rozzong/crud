import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Final, override

import pytest
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel, create_engine

from crud import SQLClient

from ..data import HeroBlueprint, HeroId, TeamBlueprint, TeamId
from . import StorageBackend

POSTGRESQL_URL_VARIABLE: Final[str] = "CRUD_TEST_POSTGRESQL_URL"
"""Environment variable holding a SQLAlchemy URL to a disposable PostgreSQL database."""


class Team(SQLModel, table=True):
    id: int | None = SQLField(default=None, primary_key=True)
    name: str
    founded: int
    heroes: list["Hero"] = Relationship(back_populates="team")


class Hero(SQLModel, table=True):
    id: int | None = SQLField(default=None, primary_key=True)
    name: str
    age: int
    strength: int
    joined: int
    team_id: int | None = SQLField(default=None, foreign_key="team.id")
    team: Team | None = Relationship(back_populates="heroes")


@dataclass
class SQLStorageBackend(StorageBackend):
    engine: Engine
    """Engine shared by both clients, on a database holding the model tables."""

    @cached_property
    def _heroes(self) -> SQLClient[HeroBlueprint, HeroId, Hero]:
        return SQLClient(
            blueprint_cls=HeroBlueprint, key_cls=HeroId, model_cls=Hero, engine=self.engine
        )

    @cached_property
    def _teams(self) -> SQLClient[TeamBlueprint, TeamId, Team]:
        return SQLClient(
            blueprint_cls=TeamBlueprint, key_cls=TeamId, model_cls=Team, engine=self.engine
        )

    @property
    @override
    def heroes(self) -> SQLClient[HeroBlueprint, HeroId, Hero]:
        return self._heroes

    @property
    @override
    def teams(self) -> SQLClient[TeamBlueprint, TeamId, Team]:
        return self._teams


@contextmanager
def _create_tables(engine: Engine) -> Iterator[Engine]:
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def open_sqlite_memory(tmp_path: Path) -> AbstractContextManager[Engine]:
    """Open an in-memory SQLite database holding the model tables."""
    # A single shared connection, or each session would get its own empty database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return _create_tables(engine)


def open_sqlite_file(tmp_path: Path) -> AbstractContextManager[Engine]:
    """Open a SQLite database file in `tmp_path`, holding the model tables."""
    return _create_tables(create_engine(f"sqlite:///{tmp_path / 'crud.db'}"))


def open_postgresql(tmp_path: Path) -> AbstractContextManager[Engine]:
    """Open the PostgreSQL database set in the environment, holding the model tables."""
    url = os.environ.get(POSTGRESQL_URL_VARIABLE)
    if not url:
        pytest.skip(f"set {POSTGRESQL_URL_VARIABLE} to run against PostgreSQL")
    return _create_tables(create_engine(url))
