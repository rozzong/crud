from dataclasses import dataclass, field
from functools import cached_property
from typing import Final, override

from crud import InMemoryClient, InMemoryDatabase, InMemoryRelationship, InMemoryTable

from ..data import HeroBlueprint, HeroId, TeamBlueprint, TeamId
from . import StorageBackend

TEAM: Final[InMemoryTable] = InMemoryTable(
    name="team",
    columns=("id", "name", "founded"),
    required=("name", "founded"),
    relationships={"heroes": InMemoryRelationship(table="hero", local="id", remote="team_id")},
)

HERO: Final[InMemoryTable] = InMemoryTable(
    name="hero",
    columns=("id", "name", "age", "strength", "joined", "team_id"),
    required=("name", "age", "strength", "joined"),
    relationships={"team": InMemoryRelationship(table="team", local="team_id", remote="id")},
)


def make_database() -> InMemoryDatabase:
    """Make an empty database with the same tables as the SQL models."""
    return InMemoryDatabase(tables=(TEAM, HERO))


@dataclass
class InMemoryStorageBackend(StorageBackend):
    database: InMemoryDatabase = field(default_factory=make_database)
    """Database shared by both clients."""

    @cached_property
    def _heroes(self) -> InMemoryClient[HeroBlueprint, HeroId]:
        return InMemoryClient(
            blueprint_cls=HeroBlueprint, key_cls=HeroId, database=self.database, table_name="hero"
        )

    @cached_property
    def _teams(self) -> InMemoryClient[TeamBlueprint, TeamId]:
        return InMemoryClient(
            blueprint_cls=TeamBlueprint, key_cls=TeamId, database=self.database, table_name="team"
        )

    @property
    @override
    def heroes(self) -> InMemoryClient[HeroBlueprint, HeroId]:
        return self._heroes

    @property
    @override
    def teams(self) -> InMemoryClient[TeamBlueprint, TeamId]:
        return self._teams
