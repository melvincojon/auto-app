from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Job


@dataclass
class MonitorState:
    version: int = 1
    seeded_companies: set[str] = field(default_factory=set)
    seen: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "MonitorState":
        state_path = Path(path)
        if not state_path.exists():
            return cls()
        payload = json.loads(state_path.read_text())
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("state file must be a version 1 object")
        seen = payload.get("seen", {})
        seeded = payload.get("seeded_companies", [])
        if not isinstance(seen, dict) or not isinstance(seeded, list):
            raise ValueError("state file has an invalid shape")
        return cls(version=1, seeded_companies=set(map(str, seeded)), seen=seen)

    def is_seeded(self, company: str) -> bool:
        return company.casefold() in self.seeded_companies

    def has_seen(self, job: Job) -> bool:
        return job.identity in self.seen

    def mark_seen(self, job: Job) -> None:
        self.seen[job.identity] = {
            "company": job.company,
            "job_id": job.job_id,
            "first_seen_at": datetime.now(UTC).isoformat(),
        }

    def seed(self, company: str, jobs: list[Job]) -> None:
        for job in jobs:
            self.mark_seen(job)
        self.seeded_companies.add(company.casefold())

    def save(self, path: str | Path) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "seeded_companies": sorted(self.seeded_companies),
            "seen": self.seen,
        }
        fd, temp_name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=state_path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_name, state_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
