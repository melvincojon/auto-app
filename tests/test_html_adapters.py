from __future__ import annotations

import httpx
import pytest

from job_monitor.adapters.html_sources import AvatureAdapter, RadancyJsonLdAdapter
from job_monitor.config import CompanyConfig
from job_monitor.errors import SourceError


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
        return html(req, body or '<html><meta name="avature.portal.page" content="SearchJobs"></html>')

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


def test_bloomberg_retries_suspicious_first_page_without_accepting_empty(make_http, caplog):
    calls = 0

    def handler(req):
        nonlocal calls
        calls += 1
        body = "<html><title>Careers</title></html>" if calls == 1 else '<li class="sort__item--job"><a class="link" href="/careers/JobDetail/Engineer/1001">Engineer</a></li>'
        return html(req, body)

    adapter = AvatureAdapter(
        cfg("Bloomberg", "avature_html", endpoint="https://x/careers/SearchJobs/", content_retries=2, pagination={"default_limit": 12}),
        make_http(handler),
    )

    assert [job.job_id for job in adapter.list_jobs()] == ["1001"]
    assert calls == 2
    assert "status" in caplog.text and "response_length" in caplog.text


def test_bloomberg_fails_closed_after_bounded_empty_retries(make_http):
    adapter = AvatureAdapter(
        cfg("Bloomberg", "avature_html", endpoint="https://x/careers/SearchJobs/", content_retries=2, pagination={"default_limit": 12}),
        make_http(lambda req: html(req, "<html></html>")),
    )

    with pytest.raises(SourceError, match="zero jobs") as exc:
        adapter.list_jobs()
    assert exc.value.code == "suspicious_empty_response"


def test_intuit_retries_a_repeated_page_with_cache_buster(make_http):
    requested = []

    def handler(req):
        page = int(req.url.params["p"])
        requested.append((page, "_" in req.url.params))
        job_id = "A1" if page == 1 or "_" not in req.url.params else "A2"
        body = f'''<section id="search-results" data-current-page="{page}" data-total-pages="2"><section id="search-results-list"><a class="sr-item" href="/job/sde/{job_id}">SDE</a></section></section>'''
        return html(req, body)

    adapter = RadancyJsonLdAdapter(
        cfg("Intuit", "radancy_html_jsonld", endpoint="https://x/search-jobs", pagination_retries=2, pagination={"page_param": "p", "starts_at": 1, "page_size": 1}),
        make_http(handler),
    )

    assert [job.job_id for job in adapter.list_jobs()] == ["A1", "A2"]
    assert requested == [(1, False), (2, False), (2, True)]


def test_intuit_rejects_response_for_wrong_reported_page(make_http):
    body = '<section id="search-results" data-current-page="1" data-total-pages="3"><section id="search-results-list"><a class="sr-item" href="/job/sde/A1">SDE</a></section></section>'
    adapter = RadancyJsonLdAdapter(
        cfg("Intuit", "radancy_html_jsonld", endpoint="https://x/search-jobs", pagination={"page_param": "p", "starts_at": 2, "page_size": 1}),
        make_http(lambda req: html(req, body)),
    )

    with pytest.raises(SourceError, match="reported page 1") as exc:
        adapter.list_jobs()
    assert exc.value.code == "pagination_failure"
