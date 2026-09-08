from __future__ import annotations

from typing import Any

from ..errors import SourceError
from ..models import Job
from ..parsing import clean_text, join_location
from .base import SourceAdapter


class GreenhouseAdapter(SourceAdapter):
    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        response = self.http.request(
            "GET", self.config.require("endpoint"), params=self.config.get("params", {})
        )
        payload = self.http.json(response)
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise SourceError("schema_change", "Greenhouse response has no jobs array")
        jobs = [
            Job(
                company=self.company,
                source=self.source,
                job_id=str(row.get("id", "")),
                title=clean_text(row.get("title")),
                description=clean_text(row.get("content")) or None,
                location=join_location(row.get("location")),
                posted_at=row.get("first_published") or row.get("updated_at"),
                job_url=str(row.get("absolute_url") or ""),
                apply_url=str(row.get("absolute_url") or "") or None,
                raw=row,
            )
            for row in rows
            if isinstance(row, dict)
        ]
        return self._finish(jobs)


class AshbyAdapter(SourceAdapter):
    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        response = self.http.request("GET", self.config.require("endpoint"))
        payload = self.http.json(response)
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise SourceError("schema_change", "Ashby response has no jobs array")
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_url = str(row.get("jobUrl") or row.get("applyUrl") or "")
            jobs.append(
                Job(
                    company=self.company,
                    source=self.source,
                    job_id=str(row.get("id", "")),
                    title=clean_text(row.get("title")),
                    description=clean_text(row.get("descriptionHtml") or row.get("descriptionPlain"))
                    or None,
                    location=join_location(row.get("location")),
                    posted_at=row.get("publishedAt"),
                    job_url=job_url,
                    apply_url=str(row.get("applyUrl") or "") or None,
                    raw=row,
                )
            )
        return self._finish(jobs)


class AmazonAdapter(SourceAdapter):
    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        endpoint = self.config.require("endpoint")
        pagination = self.config.require("pagination")
        limit = int(pagination.get("default_limit", 10))
        offset_name = pagination.get("offset_param", "offset")
        limit_name = pagination.get("limit_param", "result_limit")
        base_params = self.config.get("params", {})
        jobs: list[Job] = []
        seen: set[str] = set()
        offset = 0
        scanned = 0
        pages = 0
        while True:
            response = self.http.request(
                "GET",
                endpoint,
                params={**base_params, offset_name: offset, limit_name: limit},
            )
            payload = self.http.json(response)
            rows = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise SourceError("schema_change", "Amazon response has no jobs array")
            page_ids: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                job_id = str(row.get("id") or row.get("job_id") or "")
                if job_id in seen:
                    continue
                page_ids.append(job_id)
                seen.add(job_id)
                job_path = str(row.get("job_path") or "")
                job_url = job_path if job_path.startswith("http") else f"https://www.amazon.jobs{job_path}"
                description = " ".join(
                    clean_text(row.get(key))
                    for key in ("description", "basic_qualifications", "preferred_qualifications")
                    if row.get(key)
                )
                jobs.append(
                    Job(
                        company=self.company,
                        source=self.source,
                        job_id=job_id,
                        title=clean_text(row.get("title")),
                        description=description or None,
                        location=join_location(
                            row.get("location") or row.get("normalized_location")
                        ),
                        posted_at=row.get("posted_date"),
                        job_url=job_url,
                        apply_url=str(row.get("url_next_step") or "") or None,
                        raw=row,
                    )
                )
            pages += 1
            scanned += len(rows)
            total = payload.get("hits") or payload.get("total_hits") or payload.get("total")
            if smoke and pages >= 2:
                break
            if not rows or len(rows) < limit or (isinstance(total, int) and scanned >= total):
                break
            if not page_ids:
                raise SourceError("pagination_failure", "Amazon pagination repeated a page")
            offset += limit
        return self._finish(jobs)


def job_from_eightfold(
    adapter: SourceAdapter,
    row: dict[str, Any],
    *,
    fallback_url: str = "",
) -> Job:
    job_id = str(row.get("id") or row.get("position_id") or row.get("ats_job_id") or "")
    title = clean_text(row.get("name") or row.get("title"))
    description = clean_text(row.get("jobDescription") or row.get("job_description")) or None
    location = join_location(
        row.get("locations") or row.get("standardizedLocations") or row.get("location")
    )
    job_url = str(
        row.get("publicUrl")
        or row.get("canonicalPositionUrl")
        or row.get("positionUrl")
        or fallback_url
    )
    return Job(
        company=adapter.company,
        source=adapter.source,
        job_id=job_id,
        title=title,
        description=description,
        location=location,
        posted_at=row.get("postedTs") or row.get("t_create") or row.get("creationTs"),
        job_url=job_url,
        apply_url=job_url or None,
        raw=row,
    )
