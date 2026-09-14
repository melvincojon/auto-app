from __future__ import annotations

import logging
from dataclasses import replace

from bs4 import BeautifulSoup

from ..errors import SourceError
from ..diagnostics import format_diagnostics, html_structure
from ..models import Job
from ..parsing import nested_find
from .base import SourceAdapter
from .simple import job_from_eightfold


logger = logging.getLogger(__name__)


def _position_rows(payload: object) -> tuple[list[dict], int | None]:
    if not isinstance(payload, dict):
        raise SourceError("schema_change", "Eightfold response is not an object")
    rows = nested_find(payload, "positions")
    if rows is None:
        rows = nested_find(payload, "jobs")
    if not isinstance(rows, list):
        raise SourceError("schema_change", "Eightfold response has no positions array")
    total = nested_find(payload, "count")
    if not isinstance(total, int):
        total = nested_find(payload, "totalCount")
    return [row for row in rows if isinstance(row, dict)], total if isinstance(total, int) else None


class EightfoldPCSXAdapter(SourceAdapter):
    def __init__(self, config, http):
        super().__init__(config, http)
        self._csrf: str | None = None

    def _bootstrap(self) -> None:
        bootstrap = self.config.require("session_bootstrap")
        response = self.http.request("GET", bootstrap["url"])
        try:
            html = self.http.html(response)
        except SourceError:
            logger.warning("Microsoft bootstrap invalid response %s", format_diagnostics(response))
            raise
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": bootstrap.get("csrf_meta_name", "_csrf")})
        token = meta.get("content") if meta else None
        logger.info(
            "Microsoft bootstrap %s",
            format_diagnostics(
                response,
                structure={**html_structure(html), "csrf_meta_present": bool(token)},
            ),
        )
        if not token:
            raise SourceError("bootstrap_failure", "Microsoft CSRF meta token is missing")
        self._csrf = str(token)

    def _headers(self) -> dict[str, str]:
        if not self._csrf:
            self._bootstrap()
        bootstrap = self.config.require("session_bootstrap")
        return {
            str(bootstrap.get("request_header", "x-csrf-token")): str(self._csrf),
            "Referer": str(bootstrap["referer"]),
            "Accept": "application/json",
        }

    def _scan_jobs(self, *, smoke: bool = False) -> list[Job]:
        # The shared client outlives adapters. Start each Microsoft polling scan
        # anonymously so an expired Eightfold session cannot poison pagination.
        self.http.clear_cookies()
        self._csrf = None
        self._bootstrap()
        pagination = self.config.require("pagination")
        limit = int(pagination.get("default_limit", self.config.get("params", {}).get("num", 10)))
        offset = 0
        pages = 0
        seen: set[str] = set()
        jobs: list[Job] = []
        while True:
            params = {**self.config.get("params", {}), pagination.get("offset_param", "start"): offset}
            response = self.http.request(
                "GET",
                self.config.require("endpoint"),
                params=params,
                headers={**self._headers(), "Cache-Control": "no-cache"},
            )
            payload = self.http.json(response)
            rows, total = _position_rows(payload)
            first_ids = [str(row.get("id") or row.get("positionId") or "") for row in rows[:5]]
            logger.info(
                "Microsoft page start=%s final_url=%s position_ids=%s",
                offset,
                response.url,
                first_ids,
            )
            page_new = 0
            for row in rows:
                job = job_from_eightfold(self, row)
                if job.job_id and job.job_id not in seen:
                    seen.add(job.job_id)
                    jobs.append(job)
                    page_new += 1
            pages += 1
            if smoke and pages >= 2:
                break
            if total is not None:
                if len(jobs) >= total:
                    break
                if len(rows) < limit:
                    raise SourceError(
                        "pagination_failure",
                        f"Microsoft pagination ended at {len(jobs)} of {total} positions; start={offset}",
                    )
            elif len(rows) < limit:
                break
            if page_new == 0:
                raise SourceError(
                    "pagination_failure",
                    f"Microsoft pagination repeated start={offset}; first position IDs: {first_ids}",
                )
            offset += limit
        return self._finish(jobs)

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        attempts = 1 if smoke else int(self.config.get("scan_retries", 1)) + 1
        for attempt in range(attempts):
            try:
                return self._scan_jobs(smoke=smoke)
            except SourceError as exc:
                if exc.code != "pagination_failure" or attempt + 1 == attempts:
                    raise
                logger.warning(
                    "Microsoft restarting full scan after pagination inconsistency attempt=%s: %s",
                    attempt + 1,
                    exc,
                )
                self.http.sleep_before_retry(attempt)
        raise SourceError("pagination_failure", "Microsoft scan retry exhausted")

    def hydrate(self, job: Job) -> Job:
        detail = self.config.require("detail")
        params = {**detail.get("params", {}), detail.get("id_param", "position_id"): job.job_id}
        response = self.http.request(
            "GET", detail["endpoint"], params=params, headers=self._headers()
        )
        payload = self.http.json(response)
        row = payload.get("data", payload) if isinstance(payload, dict) else None
        if isinstance(row, dict) and isinstance(row.get("position"), dict):
            row = row["position"]
        if not isinstance(row, dict):
            raise SourceError("schema_change", "Microsoft detail has no job object")
        full = job_from_eightfold(self, row, fallback_url=job.job_url)
        return replace(
            full,
            job_id=full.job_id or job.job_id,
            title=full.title or job.title,
            location=full.location or job.location,
            posted_at=full.posted_at or job.posted_at,
            job_url=full.job_url or job.job_url,
        )


class EightfoldApplyV2Adapter(SourceAdapter):
    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        pagination = self.config.require("pagination")
        base_params = self.config.get("params", {})
        limit = int(base_params.get(pagination.get("limit_param", "num"), 10))
        offset = 0
        pages = 0
        jobs: list[Job] = []
        seen: set[str] = set()
        while True:
            params = {**base_params, pagination.get("offset_param", "start"): offset}
            response = self.http.request("GET", self.config.require("endpoint"), params=params)
            payload = self.http.json(response)
            rows, total = _position_rows(payload)
            page_new = 0
            for row in rows:
                job = job_from_eightfold(self, row)
                if job.job_id and job.job_id not in seen:
                    seen.add(job.job_id)
                    jobs.append(job)
                    page_new += 1
            pages += 1
            if smoke and pages >= 2:
                break
            if total is not None:
                if len(jobs) >= total:
                    break
                if len(rows) < limit:
                    raise SourceError(
                        "pagination_failure",
                        f"Netflix pagination ended at {len(jobs)} of {total} positions; start={offset}",
                    )
            elif len(rows) < limit:
                break
            if page_new == 0:
                raise SourceError("pagination_failure", "Netflix pagination repeated a page")
            offset += limit
        return self._finish(jobs)

    def hydrate(self, job: Job) -> Job:
        detail = self.config.require("detail")
        endpoint = str(detail["url_template"]).format(id=job.job_id)
        response = self.http.request("GET", endpoint, params=detail.get("params", {}))
        payload = self.http.json(response)
        row = payload.get("position", payload) if isinstance(payload, dict) else None
        if isinstance(row, dict) and isinstance(row.get("data"), dict):
            row = row["data"]
        if not isinstance(row, dict):
            raise SourceError("schema_change", "Netflix detail has no job object")
        full = job_from_eightfold(self, row, fallback_url=job.job_url)
        return replace(
            full,
            job_id=full.job_id or job.job_id,
            title=full.title or job.title,
            location=full.location or job.location,
            posted_at=full.posted_at or job.posted_at,
            job_url=full.job_url or job.job_url,
        )
