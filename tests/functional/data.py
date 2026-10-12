"""Backend-agnostic records every backend is seeded with, so all run the same test cases."""

from dataclasses import dataclass
from typing import Final

from crud import Blueprint, Projection


@dataclass(frozen=True)
class TeamData:
    name: str
    """Unique team name, also used by heroes to refer to their team."""

    founded: int
    """Year the team was founded."""


@dataclass(frozen=True)
class HeroData:
    name: str
    """Unique hero name."""

    age: int
    """Age in years."""

    strength: int
    """Strength score."""

    joined: int
    """Year the hero joined their team, or started out if they have none."""

    team: str | None = None
    """Name of the hero's team, if any."""


@dataclass(frozen=True)
class TeamBlueprint(Blueprint):
    name: str
    """Unique team name."""

    founded: int
    """Year the team was founded."""


@dataclass(frozen=True)
class HeroBlueprint(Blueprint):
    name: str
    """Unique hero name."""

    age: int
    """Age in years."""

    strength: int
    """Strength score."""

    joined: int
    """Year the hero joined their team, or started out if they have none."""

    team_id: object
    """Primary key of the hero's team, whatever its type on the backend, if any."""


@dataclass(frozen=True)
class SetAge(Blueprint):
    age: int
    """The new age."""


@dataclass(frozen=True)
class SetStrength(Blueprint):
    strength: int
    """The new strength score."""


@dataclass(frozen=True)
class SetPower(Blueprint):
    power: str
    """Not a hero field."""


@dataclass(frozen=True)
class TeamId(Projection):
    id: object
    """The team's primary key, whatever its type on the backend."""


@dataclass(frozen=True)
class HeroId(Projection):
    id: object
    """The hero's primary key, whatever its type on the backend."""


@dataclass(frozen=True)
class Named(Projection):
    """A hero or a team, read with only its name."""

    name: str
    """The record's name."""


@dataclass(frozen=True)
class HeroAge(Projection):
    """A hero read with only its name and age."""

    name: str
    """The hero's name."""

    age: int
    """The hero's age."""


@dataclass(frozen=True)
class HeroPower(Projection):
    power: str
    """Not a hero field."""


@dataclass(frozen=True)
class HeroTeam(Projection):
    team: object
    """A relationship, not a field."""


TEAMS: Final[tuple[TeamData, ...]] = (
    TeamData(name="Avengers", founded=1963),
    TeamData(name="X-Men", founded=1975),
)

HEROES: Final[tuple[HeroData, ...]] = (
    HeroData(name="Thor", age=1500, strength=100, joined=1963, team="Avengers"),
    HeroData(name="Natasha", age=35, strength=20, joined=1970, team="Avengers"),
    HeroData(name="Logan", age=190, strength=60, joined=1975, team="X-Men"),
    HeroData(name="Peter", age=17, strength=50, joined=2010),
)

HERO_NAMES: Final[frozenset[str]] = frozenset(hero.name for hero in HEROES)
