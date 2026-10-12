from dataclasses import dataclass


@dataclass(frozen=True)
class Squad:
    name: str


@dataclass(frozen=True)
class Hero:
    first_name: str
    last_name: str
    super_name: str
    squad: Squad
