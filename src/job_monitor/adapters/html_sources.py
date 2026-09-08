from __future__ import annotations

import json
import re
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..errors import SourceError
from ..models import Job
from ..parsing import absolute, clean_text, join_location, json_ld_job
from .base import SourceAdapter


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
        soup = BeautifulSoup(self.http.html(response), "html.parser")
        links = []
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href"))
            if re.search(r"(?:JobDetail|jobdetail|JobDetail\.avature|/careers/Job)/", href) or "jobId=" in href:
                links.append(anchor)
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in links:
            url = absolute(self.config.require("endpoint"), str(anchor.get("href")))
            job_id = _id_from_url(url)
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            container = anchor.find_parent(["li", "article", "div"])
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
        return jobs

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        pagination = self.config.require("pagination")
        limit = int(pagination.get("default_limit", 12))
        offset = 0
        pages = 0
        jobs: list[Job] = []
        seen: set[str] = set()
        while True:
            page = self._page(offset, limit)
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
    def _page(self, page: int) -> list[Job]:
        pagination = self.config.require("pagination")
        response = self.http.request(
            "GET", self.config.require("endpoint"), params={pagination.get("page_param", "p"): page}
        )
        soup = BeautifulSoup(self.http.html(response), "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
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
        return jobs

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        pagination = self.config.require("pagination")
        page = int(pagination.get("starts_at", 1))
        size = int(pagination.get("page_size", 15))
        pages = 0
        jobs: list[Job] = []
        seen: set[str] = set()
        while True:
            rows = self._page(page)
            new = [job for job in rows if job.job_id not in seen]
            jobs.extend(new)
            seen.update(job.job_id for job in new)
            pages += 1
            if smoke and pages >= 2:
                break
            if len(rows) < size:
                break
            if not new:
                raise SourceError("pagination_failure", "Intuit pagination repeated a page")
            page += 1
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
