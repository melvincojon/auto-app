from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from ..config import CompanyConfig
from ..errors import SourceError
from ..http import HttpClient
from ..models import Job


class SourceAdapter(ABC):
    def __init__(self, config: CompanyConfig, http: HttpClient):
        self.config = config
        self.http = http

    @property
    def company(self) -> str:
        return self.config.company

    @property
    def source(self) -> str:
        return self.config.adapter

    @abstractmethod
    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        """Return normalized jobs. Descriptions may be absent until hydrate()."""

    def hydrate(self, job: Job) -> Job:
        return job

    def smoke_test(self) -> Job:
        jobs = self.list_jobs(smoke=True)
        self._validate_nonempty(jobs)
        job = self.hydrate(jobs[0])
        self._validate_job(job, require_description=True)
        return job

    def _validate_nonempty(self, jobs: list[Job]) -> None:
        if not jobs:
            raise SourceError("suspicious_empty_response", "source returned zero jobs")

    def _validate_job(self, job: Job, *, require_description: bool = False) -> None:
        missing = []
        for field in ("job_id", "title", "job_url"):
            if not getattr(job, field):
                missing.append(field)
        if require_description and not job.description:
            missing.append("description")
        if missing:
            raise SourceError("schema_change", f"normalized job missing: {', '.join(missing)}")

    def _finish(self, jobs: Iterable[Job]) -> list[Job]:
        result = list(jobs)
        self._validate_nonempty(result)
        for job in result:
            self._validate_job(job)
        return result
