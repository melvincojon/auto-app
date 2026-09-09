from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Job


@dataclass
class MonitorState:
    version: int = 1
    seeded_companies: set[str] = field(default_factory=set)
    seen: dict[str, dict[str, Any]] = field(default_factory=dict)
    job_failures: dict[str, dict[str, Any]] = field(default_factory=dict)

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
        job_failures = payload.get("job_failures", {})
        if (
            not isinstance(seen, dict)
            or not isinstance(seeded, list)
            or not isinstance(job_failures, dict)
        ):
            raise ValueError("state file has an invalid shape")
        return cls(
            version=1,
            seeded_companies=set(map(str, seeded)),
            seen=seen,
            job_failures=job_failures,
        )

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
        self.clear_job_failure(job)

    def is_job_quarantined(self, job: Job, *, now: datetime | None = None) -> bool:
        failure = self.job_failures.get(job.identity)
        if not failure:
            return False
        quarantined_until = failure.get("quarantined_until")
        if not isinstance(quarantined_until, str):
            return False
        try:
            deadline = datetime.fromisoformat(quarantined_until)
        except ValueError:
            return False
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return (now or datetime.now(UTC)) < deadline

    def record_job_failure(
        self,
        job: Job,
        error_code: str,
        error_message: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Persist a per-job source failure and return whether it is new enough to warn."""
        failed_at = now or datetime.now(UTC)
        previous = self.job_failures.get(job.identity)
        identical = bool(
            previous
            and previous.get("error_code") == error_code
            and previous.get("error_message") == error_message
        )
        failure_count = int(previous.get("failure_count", 0)) + 1 if identical else 1
        failure: dict[str, Any] = {
            "failure_count": failure_count,
            "error_code": error_code,
            "error_message": error_message,
            "last_failure_at": failed_at.isoformat(),
        }
        if identical and failure_count >= 3:
            failure["quarantined_until"] = (failed_at + timedelta(hours=24)).isoformat()
        self.job_failures[job.identity] = failure
        return not identical

    def clear_job_failure(self, job: Job) -> None:
        self.job_failures.pop(job.identity, None)

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
            "job_failures": self.job_failures,
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
