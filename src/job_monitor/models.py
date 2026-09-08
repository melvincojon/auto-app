from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any


@dataclass(slots=True)
class Job:
    company: str
    source: str
    job_id: str
    title: str
    description: str | None
    location: str | None
    posted_at: str | None
    job_url: str
    apply_url: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def identity(self) -> str:
        """Stable, provider-backed identity without leaking arbitrary text into state."""
        value = f"{self.company.casefold()}\0{self.job_id}"
        return sha256(value.encode()).hexdigest()

    def as_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        result = asdict(self)
        if not include_raw:
            result.pop("raw", None)
        return result


class MatchCategory(StrEnum):
    NEW_GRAD_MATCH = "NEW_GRAD_MATCH"
    POSSIBLE_NEW_GRAD_MATCH = "POSSIBLE_NEW_GRAD_MATCH"


@dataclass(frozen=True, slots=True)
class Match:
    category: MatchCategory
    reason: str


@dataclass(frozen=True, slots=True)
class HealthWarning:
    company: str
    code: str
    message: str
