from __future__ import annotations

import httpx

from job_monitor.adapters.html_sources import AvatureAdapter, RadancyJsonLdAdapter
from job_monitor.config import CompanyConfig


def cfg(company, adapter, **values):
    return CompanyConfig(company, adapter, {"company": company, "adapter": adapter, **values})


def html(req, body):
    return httpx.Response(200, text=body, request=req, headers={"content-type": "text/html; charset=utf-8"})


def test_avature_pagination_and_hydration(make_http):
    def handler(req):
        if "/JobDetail/" in req.url.path:
            return html(req, '<h1>Software Engineer</h1><div class="job-description">Graduate role</div><div class="location">NYC</div><a href="/careers/Login?jobId=1001">Apply</a>')
        offset = int(req.url.params["jobOffset"])
        body = "" if offset >= 2 else f'<a href="/en_US/careers/JobDetail/Software-Engineer/{1001 + offset}">Software Engineer</a>'
        return html(req, body or "<html></html>")

    adapter = AvatureAdapter(
        cfg("Bloomberg", "avature_html", endpoint="https://x/en_US/careers/SearchJobs/", pagination={"default_limit": 1, "offset_param": "jobOffset", "limit_param": "jobRecordsPerPage"}),
        make_http(handler),
    )
    jobs = adapter.list_jobs()
    assert len(jobs) == 2
    full = adapter.hydrate(jobs[0])
    assert full.description == "Graduate role" and "Login?jobId=1001" in full.apply_url


def test_radancy_pagination_jsonld_and_apply(make_http):
    def handler(req):
        if req.url.path.startswith("/job/"):
            return html(req, '''<script type="application/ld+json">{"@type":"JobPosting","identifier":{"value":"A1"},"title":"SDE I","description":"Build things","datePosted":"2026-01-01","jobLocation":{"address":{"addressLocality":"NYC","addressRegion":"NY","addressCountry":"US"}},"url":"https://x/job/sde/A1"}</script><a href="/JobApplication?pipelineId=A1">Apply</a>''')
        page = int(req.url.params["p"])
        return html(req, f'<a href="/job/sde/A{page}">SDE I</a>' if page <= 2 else "<html></html>")

    adapter = RadancyJsonLdAdapter(
        cfg("Intuit", "radancy_html_jsonld", endpoint="https://x/search-jobs", pagination={"page_param": "p", "starts_at": 1, "page_size": 1}),
        make_http(handler),
    )
    jobs = adapter.list_jobs()
    assert len(jobs) == 2
    full = adapter.hydrate(jobs[0])
    assert full.job_id == "A1" and full.location == "NYC, NY, US" and full.description == "Build things"
