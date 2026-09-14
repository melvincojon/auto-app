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
    source_health: dict[str, dict[str, Any]] = field(default_factory=dict)

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
        source_health = payload.get("source_health", {})
        if (
            not isinstance(seen, dict)
            or not isinstance(seeded, list)
            or not isinstance(job_failures, dict)
            or not isinstance(source_health, dict)
        ):
            raise ValueError("state file has an invalid shape")
        return cls(
            version=1,
            seeded_companies=set(map(str, seeded)),
            seen=seen,
            job_failures=job_failures,
            source_health=source_health,
        )

    @staticmethod
    def _source_key(company: str) -> str:
        return company.casefold()

    def record_source_success(
        self, company: str, jobs: list[Job], *, now: datetime | None = None
    ) -> bool:
        """Atomically replace source metadata only after a complete successful scan.

        Returns whether the source recovered from one or more scan failures.
        """
        key = self._source_key(company)
        previous = dict(self.source_health.get(key, {}))
        recovered = int(previous.get("consecutive_failures", 0)) > 0
        scanned_at = now or datetime.now(UTC)
        previous.update(
            {
                "last_successful_scan": scanned_at.isoformat(),
                "consecutive_failures": 0,
                "last_successful_job_count": len(jobs),
                "last_successful_job_ids": [job.job_id for job in jobs],
                "consecutive_reconciliation_failures": 0,
                "last_successful_reconciliation": scanned_at.isoformat(),
            }
        )
        self.source_health[key] = previous
        return recovered

    def record_discovery_success(self, company: str) -> bool:
        """Clear a real source outage once discovery is usable again."""
        key = self._source_key(company)
        previous = dict(self.source_health.get(key, {}))
        recovered = int(previous.get("consecutive_failures", 0)) > 0
        previous["consecutive_failures"] = 0
        self.source_health[key] = previous
        return recovered

    def record_reconciliation_failure(
        self,
        company: str,
        error_message: str,
        *,
        now: datetime | None = None,
    ) -> int:
        """Track incomplete reconciliation without changing source outage state."""
        key = self._source_key(company)
        previous = dict(self.source_health.get(key, {}))
        count = int(previous.get("consecutive_reconciliation_failures", 0)) + 1
        failed_at = now or datetime.now(UTC)
        previous.update(
            {
                "consecutive_reconciliation_failures": count,
                "last_reconciliation_failure_at": failed_at.isoformat(),
                "last_reconciliation_error": error_message,
            }
        )
        if count == 1:
            previous["reconciliation_failure_started_at"] = failed_at.isoformat()
        self.source_health[key] = previous
        return count

    def record_source_failure(
        self,
        company: str,
        error_code: str,
        error_message: str,
        *,
        now: datetime | None = None,
    ) -> int:
        """Record failure without changing the last-known-good snapshot."""
        key = self._source_key(company)
        previous = dict(self.source_health.get(key, {}))
        count = int(previous.get("consecutive_failures", 0)) + 1
        previous.update(
            {
                "consecutive_failures": count,
                "last_failure_at": (now or datetime.now(UTC)).isoformat(),
                "last_error_code": error_code,
                "last_error_message": error_message,
            }
        )
        self.source_health[key] = previous
        return count

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
            "source_health": self.source_health,
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
