from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from bs4 import BeautifulSoup

from ..diagnostics import format_diagnostics, html_structure
from ..errors import SourceError
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


@dataclass(frozen=True)
class _Page:
    offset: int
    jobs: list[Job]
    total: int | None

    @property
    def ids(self) -> list[str]:
        return [job.job_id for job in self.jobs]


class _EightfoldOffsetAdapter(SourceAdapter):
    provider_name = "Eightfold"

    def __init__(self, config, http):
        super().__init__(config, http)
        self._discovery_pages: dict[int, _Page] = {}
        self._poll_started = False

    def _start_poll(self) -> None:
        self._poll_started = True
        self._discovery_pages = {}

    def _page_headers(self) -> dict[str, str]:
        return {}

    def _limit(self) -> int:
        pagination = self.config.require("pagination")
        limit_param = pagination.get("limit_param", "num")
        return int(
            pagination.get(
                "default_limit",
                self.config.get("params", {}).get(limit_param, 10),
            )
        )

    def _fetch_page(self, offset: int) -> _Page:
        pagination = self.config.require("pagination")
        params = {
            **self.config.get("params", {}),
            pagination.get("offset_param", "start"): offset,
        }
        response = self.http.request(
            "GET",
            self.config.require("endpoint"),
            params=params,
            headers=self._page_headers() or None,
        )
        rows, total = _position_rows(self.http.json(response))
        jobs = [job_from_eightfold(self, row) for row in rows]
        ids = [job.job_id for job in jobs]
        if any(not job_id for job_id in ids):
            raise SourceError("schema_change", f"{self.provider_name} page contains a missing job ID")
        if len(ids) != len(set(ids)):
            raise SourceError(
                "reconciliation_inconsistency",
                f"{self.provider_name} returned duplicate IDs within start={offset}",
            )
        logger.info(
            "%s page start=%s returned=%s total=%s position_ids=%s",
            self.provider_name,
            offset,
            len(jobs),
            total,
            ids[:5],
        )
        return _Page(offset, jobs, total)

    def discover_jobs(self) -> list[Job]:
        self._start_poll()
        limit = self._limit()
        page_count = max(1, int(self.config.get("discovery_pages", 2)))
        discovered: list[Job] = []
        seen: set[str] = set()
        for page_number in range(page_count):
            offset = page_number * limit
            page = self._fetch_page(offset)
            self._discovery_pages[offset] = page
            for job in page.jobs:
                if job.job_id in seen:
                    logger.info(
                        "%s discovery deduplicated job %s at start=%s",
                        self.provider_name,
                        job.job_id,
                        offset,
                    )
                    continue
                seen.add(job.job_id)
                discovered.append(job)
            if len(page.jobs) < limit:
                break
        return self._finish(discovered)

    def _retry_page_with_total(self, offset: int, expected_total: int | None) -> _Page:
        attempts = int(self.config.get("range_retries", 2)) + 1
        page: _Page | None = None
        for attempt in range(attempts):
            page = self._fetch_page(offset)
            if page.total == expected_total:
                return page
            if attempt + 1 < attempts:
                self.http.sleep_before_retry(attempt)
        assert page is not None
        raise SourceError(
            "reconciliation_inconsistency",
            f"{self.provider_name} advertised total changed from "
            f"{expected_total} to {page.total} at start={offset}",
        )

    def _repair_boundary(
        self,
        previous: _Page,
        current: _Page,
        *,
        overlap: int,
        expected_total: int | None,
    ) -> tuple[_Page, _Page]:
        attempts = int(self.config.get("range_retries", 2))
        for attempt in range(attempts):
            logger.warning(
                "%s retrying shifted range starts=%s,%s attempt=%s",
                self.provider_name,
                previous.offset,
                current.offset,
                attempt + 1,
            )
            retried_previous = self._fetch_page(previous.offset)
            retried_current = self._fetch_page(current.offset)
            if (
                retried_previous.total == expected_total
                and retried_current.total == expected_total
                and (
                    overlap == 0
                    or retried_previous.ids[-overlap:] == retried_current.ids[:overlap]
                )
            ):
                return retried_previous, retried_current
            if attempt + 1 < attempts:
                self.http.sleep_before_retry(attempt)
        raise SourceError(
            "reconciliation_inconsistency",
            f"{self.provider_name} offset boundary shifted between "
            f"start={previous.offset} and start={current.offset}",
        )

    def _validate_pages(
        self, pages: list[_Page], *, overlap: int, expected_total: int | None
    ) -> list[Job]:
        jobs: list[Job] = []
        seen: set[str] = set()
        for index, page in enumerate(pages):
            expected_overlap: set[str] = set()
            if index and overlap:
                previous = pages[index - 1]
                expected = previous.ids[-overlap:]
                if page.ids[:overlap] != expected:
                    raise SourceError(
                        "reconciliation_inconsistency",
                        f"{self.provider_name} overlap validation failed at start={page.offset}",
                    )
                expected_overlap = set(expected)
            repeated = (set(page.ids) & seen) - expected_overlap
            if repeated:
                raise SourceError(
                    "reconciliation_inconsistency",
                    f"{self.provider_name} repeated IDs outside the expected overlap "
                    f"at start={page.offset}: {sorted(repeated)[:5]}",
                )
            for job in page.jobs:
                if job.job_id not in seen:
                    seen.add(job.job_id)
                    jobs.append(job)
        if expected_total is not None and len(jobs) != expected_total:
            raise SourceError(
                "reconciliation_inconsistency",
                f"{self.provider_name} reconciliation produced {len(jobs)} unique "
                f"positions for advertised total {expected_total}",
            )
        return self._finish(jobs)

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        if smoke:
            return self.discover_jobs()
        if not self._poll_started:
            self._start_poll()

        pagination = self.config.require("pagination")
        limit = self._limit()
        overlap = int(pagination.get("overlap", min(2, max(0, limit - 1))))
        if overlap < 0 or overlap >= limit:
            raise SourceError("configuration_drift", "Eightfold overlap must be between 0 and limit-1")
        stride = limit - overlap

        first = self._discovery_pages.get(0) or self._fetch_page(0)
        expected_total = first.total
        if expected_total is None:
            raise SourceError(
                "schema_change",
                f"{self.provider_name} response has no advertised total",
            )
        pages = [first]
        offset = stride
        while offset < expected_total:
            page = self._discovery_pages.get(offset)
            if page is None or page.total != expected_total:
                page = self._retry_page_with_total(offset, expected_total)
            previous = pages[-1]
            if overlap and previous.ids[-overlap:] != page.ids[:overlap]:
                previous, page = self._repair_boundary(
                    previous,
                    page,
                    overlap=overlap,
                    expected_total=expected_total,
                )
                pages[-1] = previous
            pages.append(page)
            if offset + len(page.jobs) >= expected_total:
                break
            if len(page.jobs) < limit:
                raise SourceError(
                    "reconciliation_inconsistency",
                    f"{self.provider_name} pagination ended early at start={offset}; "
                    f"returned={len(page.jobs)} total={expected_total}",
                )
            offset += stride

        final_anchor = self._retry_page_with_total(0, expected_total)
        if final_anchor.ids != first.ids:
            raise SourceError(
                "reconciliation_inconsistency",
                f"{self.provider_name} first page changed during reconciliation",
            )
        result = self._validate_pages(pages, overlap=overlap, expected_total=expected_total)
        self._poll_started = False
        self._discovery_pages = {}
        return result


class EightfoldPCSXAdapter(_EightfoldOffsetAdapter):
    provider_name = "Microsoft"

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

    def _start_poll(self) -> None:
        self.http.clear_cookies()
        self._csrf = None
        self._bootstrap()
        super()._start_poll()

    def _page_headers(self) -> dict[str, str]:
        if not self._csrf:
            self._bootstrap()
        bootstrap = self.config.require("session_bootstrap")
        return {
            str(bootstrap.get("request_header", "x-csrf-token")): str(self._csrf),
            "Referer": str(bootstrap["referer"]),
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        }

    def hydrate(self, job: Job) -> Job:
        detail = self.config.require("detail")
        params = {**detail.get("params", {}), detail.get("id_param", "position_id"): job.job_id}
        response = self.http.request(
            "GET", detail["endpoint"], params=params, headers=self._page_headers()
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


class EightfoldApplyV2Adapter(_EightfoldOffsetAdapter):
    provider_name = "Netflix"

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
