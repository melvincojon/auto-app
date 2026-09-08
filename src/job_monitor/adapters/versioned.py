from __future__ import annotations

import json
import re
from dataclasses import replace
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..errors import SourceError
from ..models import Job
from ..parsing import clean_text, join_location, json_ld_job, nested_find
from .base import SourceAdapter


class MetaRelayAdapter(SourceAdapter):
    def __init__(self, config, http):
        super().__init__(config, http)
        self._lsd: str | None = None

    def _bootstrap(self) -> None:
        bootstrap = self.config.require("session_bootstrap")
        response = self.http.request("GET", bootstrap["url"])
        html = self.http.html(response)
        patterns = [
            r'\["LSD",\[\],\{"token":"([^"]+)"',
            r'"LSD"\s*,\s*\[\]\s*,\s*\{\s*"token"\s*:\s*"([^"]+)"',
            r'name="lsd"\s+value="([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                self._lsd = match.group(1).replace("\\/", "/")
                return
        raise SourceError("bootstrap_failure", "Meta LSD token is missing")

    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        if not self._lsd:
            self._bootstrap()
        request = self.config.require("request")
        bootstrap = self.config.require("session_bootstrap")
        variables = request.get("variables")
        if not request.get("doc_id") or not isinstance(variables, dict):
            raise SourceError("configuration_drift", "Meta doc_id or variables are missing")
        form = {
            "lsd": self._lsd,
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": request["friendly_name"],
            "variables": json.dumps(variables, separators=(",", ":")),
            "doc_id": str(request["doc_id"]),
        }
        headers = {
            str(bootstrap.get("request_header", "x-fb-lsd")): str(self._lsd),
            "Referer": str(bootstrap["referer"]),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = self.http.request(
            "POST", self.config.require("endpoint"), data=form, headers=headers
        )
        payload = self.http.json(response, allow_html_content_type=True)
        if isinstance(payload, dict) and payload.get("errors"):
            raise SourceError(
                "versioned_contract_failure",
                "Meta Relay query failed; refresh the documented persisted query ID",
            )
        rows = nested_find(payload, "all_jobs")
        if not isinstance(rows, list):
            raise SourceError(
                "versioned_contract_failure",
                "Meta all_jobs is missing; persisted query contract may have changed",
            )
        jobs: list[Job] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("id") or "")
            jobs.append(
                Job(
                    company=self.company,
                    source=self.source,
                    job_id=job_id,
                    title=clean_text(row.get("title")),
                    description=None,
                    location=join_location(row.get("locations")),
                    posted_at=None,
                    job_url=f"https://www.metacareers.com/profile/job_details/{job_id}/",
                    apply_url=f"https://www.metacareers.com/profile/job_details/{job_id}/",
                    raw=row,
                )
            )
        return self._finish(jobs)

    def hydrate(self, job: Job) -> Job:
        response = self.http.request("GET", job.job_url)
        data = json_ld_job(self.http.html(response))
        return replace(
            job,
            title=clean_text(data.get("title")) or job.title,
            description=clean_text(data.get("description")) or None,
            location=join_location(data.get("jobLocation")) or job.location,
            posted_at=data.get("datePosted"),
            job_url=str(data.get("url") or job.job_url),
            apply_url=str(data.get("url") or job.apply_url or job.job_url),
            raw=data,
        )


class RipplingAdapter(SourceAdapter):
    def list_jobs(self, *, smoke: bool = False) -> list[Job]:
        request = self.config.require("request")
        headers = {str(key): str(value) for key, value in self.config.require("headers").items()}
        if not headers.get("x-algolia-application-id") or not headers.get("x-algolia-api-key"):
            raise SourceError("configuration_drift", "Rippling Algolia configuration is missing")
        page = int(self.config.require("pagination").get("starts_at", 0))
        per_page = int(request.get("default_hits_per_page", 100))
        jobs_by_id: dict[str, Job] = {}
        pages = 0
        while True:
            params = urlencode({"page": page, "hitsPerPage": per_page, "query": ""})
            body = {"requests": [{"indexName": request["index_name"], "params": params}]}
            try:
                response = self.http.request(
                    "POST", self.config.require("endpoint"), headers=headers, json=body
                )
            except SourceError as exc:
                if exc.code == "non_200_response" and any(
                    status in str(exc) for status in ("401", "403", "404")
                ):
                    raise SourceError(
                        "versioned_contract_failure",
                        "Rippling Algolia credentials/index failed; repeat bundle discovery and smoke testing",
                    ) from exc
                raise
            payload = self.http.json(response)
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list) or not results or not isinstance(results[0], dict):
                raise SourceError(
                    "versioned_contract_failure",
                    "Rippling Algolia result is missing; refresh the documented bundle configuration",
                )
            result = results[0]
            if result.get("error"):
                raise SourceError(
                    "versioned_contract_failure",
                    "Rippling Algolia returned an index/configuration error; repeat bundle discovery and smoke testing",
                )
            hits = result.get("hits")
            if not isinstance(hits, list):
                raise SourceError("schema_change", "Rippling result has no hits array")
            before = len(jobs_by_id)
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                job_id = str(hit.get("jobId") or "")
                if not job_id:
                    continue
                location = join_location(hit.get("locations") or hit.get("locationNames") or hit.get("location"))
                if job_id in jobs_by_id:
                    existing = jobs_by_id[job_id]
                    combined = join_location([existing.location, location])
                    jobs_by_id[job_id] = replace(existing, location=combined)
                    continue
                url = str(hit.get("url") or "")
                jobs_by_id[job_id] = Job(
                    company=self.company,
                    source=self.source,
                    job_id=job_id,
                    title=clean_text(hit.get("name") or hit.get("title")),
                    description=None,
                    location=location,
                    posted_at=None,
                    job_url=url,
                    apply_url=url or None,
                    raw=hit,
                )
            pages += 1
            nb_pages = result.get("nbPages")
            if smoke and pages >= 2:
                break
            if isinstance(nb_pages, int) and page + 1 >= nb_pages:
                break
            if len(hits) < per_page:
                break
            if len(jobs_by_id) == before:
                # A page may contain only duplicate job locations, so use objectID to
                # distinguish a valid location-only page from a repeated response.
                object_ids = {str(hit.get("objectID")) for hit in hits if isinstance(hit, dict)}
                if not object_ids:
                    raise SourceError("pagination_failure", "Rippling pagination made no progress")
            page += 1
        return self._finish(jobs_by_id.values())

    def hydrate(self, job: Job) -> Job:
        response = self.http.request("GET", job.job_url)
        html = self.http.html(response)
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            raise SourceError(
                "versioned_contract_failure",
                "Rippling detail has no __NEXT_DATA__; deployment contract changed",
            )
        try:
            payload = json.loads(script.string or script.get_text())
        except json.JSONDecodeError as exc:
            raise SourceError("unexpected_json", "Rippling __NEXT_DATA__ is invalid") from exc
        row = payload
        for key in self.config.require("detail").get("json_path", "").split("."):
            if not isinstance(row, dict) or key not in row:
                raise SourceError(
                    "versioned_contract_failure",
                    "Rippling jobPost path is missing; deployment contract changed",
                )
            row = row[key]
        if not isinstance(row, dict):
            raise SourceError("schema_change", "Rippling jobPost is not an object")
        description = " ".join(
            clean_text(row.get(key))
            for key in ("companyDescription", "jobDescription", "description")
            if row.get(key)
        )
        url = str(row.get("url") or row.get("canonicalUrl") or job.job_url)
        return replace(
            job,
            job_id=str(row.get("id") or row.get("uuid") or job.job_id),
            title=clean_text(row.get("name") or row.get("title")) or job.title,
            description=description or None,
            location=join_location(row.get("workLocations") or row.get("locations")) or job.location,
            posted_at=row.get("createdOn"),
            job_url=url,
            apply_url=url,
            raw=row,
        )
