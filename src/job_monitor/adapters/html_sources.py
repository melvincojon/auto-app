from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..errors import SourceError
from ..diagnostics import format_diagnostics, html_structure
from ..models import Job
from ..parsing import absolute, clean_text, join_location, json_ld_job
from .base import SourceAdapter


logger = logging.getLogger(__name__)


def _id_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("jobId", "job", "id", "pipelineId"):
        if query.get(key):
            return query[key][0]
    parts = [part for part in parsed.path.split("/") if part]
    for part in reversed(parts):
        match = re.search(r"(?:^|[-_])(\d{4,}|[0-9a-f]{8}-[0-9a-f-]{27,})(?:$|[-_])", part, re.I)
        if match:
            return match.group(1)
    return parts[-1] if parts else ""


class AvatureAdapter(SourceAdapter):
    def _page(self, offset: int, limit: int) -> list[Job]:
        params = {
            self.config.require("pagination").get("offset_param", "jobOffset"): offset,
            self.config.require("pagination").get("limit_param", "jobRecordsPerPage"): limit,
        }
        response = self.http.request("GET", self.config.require("endpoint"), params=params)
        try:
            page_html = self.http.html(response)
        except SourceError:
            logger.warning("Bloomberg invalid response offset=%s %s", offset, format_diagnostics(response))
            raise
        soup = BeautifulSoup(page_html, "html.parser")
        result_legend = soup.select_one(".list-controls__text__legend[aria-label]")
        if result_legend:
            total_match = re.search(r"\d+", str(result_legend.get("aria-label")))
            if total_match:
                self._expected_total = int(total_match.group())
        # Current Avature markup has one title link per li.sort__item--job.
        links = soup.select("li.sort__item--job a.link[href*='/JobDetail/']")
        if not links:
            links = [
                anchor
                for anchor in soup.select("a[href]")
                if re.search(r"/JobDetail(?:\.avature)?/", str(anchor.get("href")), re.I)
            ]
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in links:
            url = absolute(self.config.require("endpoint"), str(anchor.get("href")))
            job_id = _id_from_url(url)
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            container = anchor.find_parent("li") or anchor.find_parent(["article", "div"])
            location = None
            if container:
                location_node = container.select_one(
                    "[class*='location'], [data-field='location'], .jobLocation"
                )
                location = clean_text(location_node) if location_node else None
            jobs.append(
                Job(
                    company=self.company,
                    source=self.source,
                    job_id=job_id,
                    title=clean_text(anchor),
                    description=None,
                    location=location,
                    posted_at=None,
                    job_url=url,
                    raw={"detail_url": url},
                )
            )
        logger.info(
            "Bloomberg page offset=%s final_url=%s job_ids=%s",
            offset,
            response.url,
            [job.job_id for job in jobs[:5]],
        )
        if not jobs:
            structure = html_structure(page_html)
            logger.warning(
                "Bloomberg zero-job page offset=%s %s",
                offset,
                format_diagnostics(response, structure=structure),
            )
            if structure["markers"]["challenge"] or not structure["markers"]["avature"]:
                raise SourceError("unexpected_html", "Bloomberg returned a non-Avature page")
        return jobs

    def _page_with_retries(self, offset: int, limit: int) -> list[Job]:
        attempts = int(self.config.get("content_retries", 2)) + 1
        last_error: SourceError | None = None
        for attempt in range(attempts):
            try:
                page = self._page(offset, limit)
                if page or offset > 0:
                    return page
                last_error = SourceError("suspicious_empty_response", "source returned zero jobs")
            except SourceError as exc:
                last_error = exc
            if attempt + 1 < attempts:
                self.http.sleep_before_retry(attempt)
        if offset == 0:
            raise SourceError(
                "suspicious_empty_response",
                f"source returned zero jobs after {attempts} attempts ({last_error})",
            )
        raise last_error or SourceError("suspicious_empty_response", "source returned zero jobs")

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        pagination = self.config.require("pagination")
        limit = int(pagination.get("default_limit", 12))
        offset = 0
        self._expected_total: int | None = None
        pages = 0
        jobs: list[Job] = []
        seen: set[str] = set()
        while True:
            page = self._page_with_retries(offset, limit)
            page_new = [job for job in page if job.job_id not in seen]
            jobs.extend(page_new)
            seen.update(job.job_id for job in page_new)
            pages += 1
            if smoke and pages >= 2:
                break
            if len(page) < limit:
                break
            if not page_new:
                raise SourceError("pagination_failure", "Bloomberg pagination repeated a page")
            offset += limit
        if not smoke and self._expected_total is not None and len(jobs) < self._expected_total:
            raise SourceError(
                "pagination_failure",
                f"Bloomberg scan ended at {len(jobs)} of {self._expected_total} advertised jobs",
            )
        return self._finish(jobs)

    def hydrate(self, job: Job) -> Job:
        response = self.http.request("GET", job.job_url)
        html = self.http.html(response)
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one("h1, [class*='job-title'], [data-field='title']")
        description_node = soup.select_one(
            "[class*='job-description'], [class*='jobDescription'], [data-field='description'], main"
        )
        location_node = soup.select_one(
            "[class*='location'], [data-field='location'], .jobLocation"
        )
        apply = None
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href"))
            if "Login?jobId=" in href or "JobApplication" in href:
                apply = absolute(job.job_url, href)
                break
        return replace(
            job,
            title=clean_text(title_node) or job.title,
            description=clean_text(description_node) or None,
            location=clean_text(location_node) or job.location,
            apply_url=apply,
        )


class RadancyJsonLdAdapter(SourceAdapter):
    def _page(
        self, page: int, *, cache_buster: int | None = None
    ) -> tuple[list[Job], int | None, int | None]:
        pagination = self.config.require("pagination")
        params = {pagination.get("page_param", "p"): page}
        if cache_buster is not None:
            params["_"] = cache_buster
        response = self.http.request(
            "GET",
            self.config.require("endpoint"),
            params=params,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        page_html = self.http.html(response)
        soup = BeautifulSoup(page_html, "html.parser")
        results = soup.select_one("#search-results")
        current_page = None
        total_pages = None
        if results:
            try:
                current_page = int(str(results.get("data-current-page")))
                total_pages = int(str(results.get("data-total-pages")))
                self._expected_total = int(str(results.get("data-total-job-results")))
            except (TypeError, ValueError):
                pass
        jobs: list[Job] = []
        seen: set[str] = set()
        anchors = soup.select("#search-results-list a.sr-item[href]")
        if not anchors:
            anchors = soup.select("#search-results-list a[href]")
        if not anchors and results is None:
            anchors = soup.select("a[href]")
        for anchor in anchors:
            href = str(anchor.get("href"))
            if not re.search(r"/job/|/jobs/", href, re.I):
                continue
            url = absolute(self.config.require("endpoint"), href)
            job_id = _id_from_url(url)
            title = clean_text(anchor)
            if not job_id or not title or job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                Job(self.company, self.source, job_id, title, None, None, None, url, raw={"detail_url": url})
            )
        logger.info(
            "Intuit page requested=%s reported=%s final_url=%s job_ids=%s",
            page,
            current_page,
            response.url,
            [job.job_id for job in jobs[:5]],
        )
        if current_page is not None and current_page != page:
            raise SourceError(
                "pagination_failure",
                f"Intuit requested page {page} but response reported page {current_page}; final URL {response.url}",
            )
        if not jobs:
            logger.warning(
                "Intuit zero-job page requested=%s %s",
                page,
                format_diagnostics(response, structure=html_structure(page_html)),
            )
        return jobs, current_page, total_pages

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        pagination = self.config.require("pagination")
        page = int(pagination.get("starts_at", 1))
        self._expected_total: int | None = None
        size = int(pagination.get("page_size", 15))
        pages = 0
        jobs: list[Job] = []
        seen: set[str] = set()
        while True:
            rows: list[Job] = []
            total_pages: int | None = None
            for attempt in range(int(self.config.get("pagination_retries", 2)) + 1):
                rows, _reported_page, total_pages = self._page(
                    page, cache_buster=time.time_ns() if attempt else None
                )
                new = [job for job in rows if job.job_id not in seen]
                if new or not rows:
                    break
                logger.warning(
                    "Intuit repeated page requested=%s attempt=%s job_ids=%s",
                    page,
                    attempt + 1,
                    [job.job_id for job in rows[:5]],
                )
                if attempt < int(self.config.get("pagination_retries", 2)):
                    self.http.sleep_before_retry(attempt)
            jobs.extend(new)
            seen.update(job.job_id for job in new)
            pages += 1
            if smoke and pages >= 2:
                break
            if total_pages is not None and page >= total_pages:
                break
            if total_pages is None and len(rows) < size:
                break
            if not new:
                raise SourceError(
                    "pagination_failure",
                    f"Intuit pagination repeated page {page}; first job IDs: "
                    f"{[job.job_id for job in rows[:5]]}",
                )
            page += 1
        if not smoke and self._expected_total is not None and len(jobs) < self._expected_total:
            raise SourceError(
                "pagination_failure",
                f"Intuit scan ended at {len(jobs)} of {self._expected_total} advertised jobs",
            )
        return self._finish(jobs)

    def hydrate(self, job: Job) -> Job:
        response = self.http.request("GET", job.job_url)
        html = self.http.html(response)
        data = json_ld_job(html)
        identifier = data.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value") or identifier.get("name")
        location = data.get("jobLocation") or data.get("applicantLocationRequirements")
        soup = BeautifulSoup(html, "html.parser")
        apply = None
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href"))
            if "JobApplication" in href or "pipelineId=" in href:
                apply = absolute(job.job_url, href)
                break
        return replace(
            job,
            job_id=str(identifier or job.job_id),
            title=clean_text(data.get("title")) or job.title,
            description=clean_text(data.get("description")) or None,
            location=join_location(location) or job.location,
            posted_at=data.get("datePosted"),
            job_url=str(data.get("url") or job.job_url),
            apply_url=apply,
            raw=data,
        )
