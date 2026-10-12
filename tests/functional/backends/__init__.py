from abc import ABC, abstractmethod
from collections.abc import Sequence

from crud import CRUDClient, Field

from ..data import HeroBlueprint, HeroData, HeroId, TeamBlueprint, TeamData, TeamId


class StorageBackend(ABC):
    """Everything a functional test needs from a backend: its clients."""

    @property
    @abstractmethod
    def heroes(self) -> CRUDClient[HeroBlueprint, HeroId]: ...

    @property
    @abstractmethod
    def teams(self) -> CRUDClient[TeamBlueprint, TeamId]: ...

    def _find_team_id(self, name: str | None) -> object:
        if name is None:
            return None
        (team,) = self.teams.read(Field("name") == name, TeamId)
        return team.id

    def make_hero(self, data: HeroData) -> HeroBlueprint:
        """Build the blueprint of a hero, linked to its team if it has one."""
        return HeroBlueprint(
            name=data.name,
            age=data.age,
            strength=data.strength,
            joined=data.joined,
            team_id=self._find_team_id(data.team),
        )

    def seed(self, teams: Sequence[TeamData], heroes: Sequence[HeroData]) -> None:
        """Store the given records."""
        self.teams.create(TeamBlueprint(name=team.name, founded=team.founded) for team in teams)
        self.heroes.create(self.make_hero(hero) for hero in heroes)
