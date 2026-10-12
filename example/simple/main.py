"""Play around with the CRUD clients: seed heroes and squads, then read, update and destroy.

Run it with `uv run python example/simple/main.py`. Set `ECHO_SQL` to see the SQL each call
sends, such as `read` selecting only the columns of its projection.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from entities import Hero, Squad
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel, create_engine

from crud import Blueprint, CRUDClient, Field, Order, Projection, SQLClient

ECHO_SQL: Final[bool] = False
"""Whether to print every SQL statement sent to the database."""

DATABASE_PATH: Final[Path] = Path(__file__).with_name("database.db")
"""SQLite file the example writes to, recreated on every run."""


@dataclass(frozen=True)
class NewSquad(Blueprint):
    id: UUID
    """The squad's primary key, chosen by the caller."""

    name: str
    """The squad's name."""


@dataclass(frozen=True)
class NewHero(Blueprint):
    id: UUID
    """The hero's primary key, chosen by the caller."""

    first_name: str
    """The hero's first name."""

    last_name: str
    """The hero's last name."""

    super_name: str
    """The name the hero goes by."""

    squad_id: UUID
    """Primary key of the hero's squad."""


@dataclass(frozen=True)
class Rename(Blueprint):
    super_name: str
    """The new name the hero goes by."""


@dataclass(frozen=True)
class SquadId(Projection):
    id: UUID
    """The squad's primary key."""


@dataclass(frozen=True)
class HeroId(Projection):
    id: UUID
    """The hero's primary key."""


@dataclass(frozen=True)
class SquadRef(Projection):
    id: UUID
    """The squad's primary key."""

    name: str
    """The squad's name."""


@dataclass(frozen=True)
class HeroName(Projection):
    super_name: str
    """The name the hero goes by."""


@dataclass(frozen=True)
class HeroCard(Projection):
    first_name: str
    """The hero's first name."""

    last_name: str
    """The hero's last name."""

    super_name: str
    """The name the hero goes by."""


@dataclass(frozen=True)
class Entries:
    squads: Sequence[Squad]
    """Squads to store first."""

    heroes: Sequence[Hero]
    """Heroes to store, each in one of `squads`."""


@dataclass(frozen=True)
class Clients:
    heroes: CRUDClient[NewHero, HeroId]
    """Client for the heroes."""

    squads: CRUDClient[NewSquad, SquadId]
    """Client for the squads."""


# No defaults: every column must be written, so a blueprint missing one fails.
class SquadModel(SQLModel, table=True):
    id: UUID = SQLField(primary_key=True)
    name: str
    heroes: list["HeroModel"] = Relationship(back_populates="squad")


class HeroModel(SQLModel, table=True):
    id: UUID = SQLField(primary_key=True)
    first_name: str
    last_name: str
    super_name: str
    squad_id: UUID = SQLField(foreign_key="squadmodel.id")
    squad: SquadModel = Relationship(back_populates="heroes")


def _make_sql_clients() -> Clients:
    engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=ECHO_SQL)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    return Clients(
        heroes=SQLClient(blueprint_cls=NewHero, key_cls=HeroId, model_cls=HeroModel, engine=engine),
        squads=SQLClient(
            blueprint_cls=NewSquad, key_cls=SquadId, model_cls=SquadModel, engine=engine
        ),
    )


def make_all_clients() -> Iterable[Clients]:
    return (_make_sql_clients(),)


def create_entries() -> Entries:
    justice_league = Squad("Justice League")
    avengers = Squad("Avengers")
    return Entries(
        squads=(justice_league, avengers),
        heroes=(
            Hero(first_name="Bruce", last_name="Wayne", super_name="Batman", squad=justice_league),
            Hero(first_name="Clark", last_name="Kent", super_name="Superman", squad=justice_league),
            Hero(
                first_name="Diana",
                last_name="Prince",
                super_name="Wonder Woman",
                squad=justice_league,
            ),
            Hero(first_name="Tony", last_name="Stark", super_name="Iron Man", squad=avengers),
            Hero(
                first_name="Steve", last_name="Rogers", super_name="Captain America", squad=avengers
            ),
            Hero(
                first_name="Natasha", last_name="Romanoff", super_name="Black Widow", squad=avengers
            ),
        ),
    )


def populate(clients: Clients, entries: Entries) -> None:
    squad_ids = {squad: uuid4() for squad in entries.squads}
    clients.squads.create(NewSquad(id=id, name=squad.name) for squad, id in squad_ids.items())
    clients.heroes.create(
        NewHero(
            id=uuid4(),
            first_name=hero.first_name,
            last_name=hero.last_name,
            super_name=hero.super_name,
            squad_id=squad_ids[hero.squad],
        )
        for hero in entries.heroes
    )


def show(title: str, rows: Iterable[object]) -> None:
    print(f"\n{title}")
    for row in rows:
        print(f"  {row}")


def play(clients: Clients) -> None:
    heroes, squads = clients.heroes, clients.squads
    by_super_name = [Order(field=Field("super_name"))]

    show("Every hero, by super name", heroes.read(None, HeroName, order_by=by_super_name))
    show(
        "Justice League members (a filter across a relationship)",
        heroes.read(Field("squad", "name") == "Justice League", HeroCard),
    )
    show(
        "Super names containing 'man'",
        heroes.read(Field("super_name").contains("man"), HeroName, order_by=by_super_name),
    )
    show(
        "Squads with a member called Natasha (across a to-many relationship)",
        squads.read(Field("heroes", "first_name") == "Natasha", SquadRef),
    )
    show(
        "The first two heroes by last name, descending",
        heroes.read(
            None, HeroCard, order_by=[Order(field=Field("last_name"), is_descending=True)], limit=2
        ),
    )

    count = heroes.update(Field("first_name") == "Bruce", Rename(super_name="The Dark Knight"))
    show(f"Renamed {count} hero", heroes.read(Field("first_name") == "Bruce", HeroCard))

    try:
        with heroes.transaction() as transaction:
            count = heroes.destroy(Field("squad", "name") == "Avengers", transaction=transaction)
            print(f"\nDestroyed {count} Avengers, then failed before the transaction ended")
            raise RuntimeError("Something went wrong")
    except RuntimeError:
        pass
    show(
        "Rolled back, so the Avengers are still there",
        heroes.read(None, HeroName, order_by=by_super_name),
    )

    count = heroes.destroy(Field("squad", "name") == "Avengers")
    show(
        f"Destroyed {count} Avengers for real", heroes.read(None, HeroName, order_by=by_super_name)
    )


if __name__ == "__main__":
    entries = create_entries()
    for clients in make_all_clients():
        populate(clients, entries)
        play(clients)
