from __future__ import annotations

import httpx

from job_monitor.adapters.simple import AmazonAdapter, AshbyAdapter, GreenhouseAdapter
from job_monitor.config import CompanyConfig


def cfg(company, adapter, **values):
    return CompanyConfig(company, adapter, {"company": company, "adapter": adapter, **values})


def response(request, payload):
    return httpx.Response(200, json=payload, request=request, headers={"content-type": "application/json"})


def test_greenhouse_normalizes(make_http):
    http = make_http(lambda req: response(req, {"jobs": [{"id": 1, "title": "Software Engineer", "content": "<p>Graduate</p>", "location": {"name": "NYC"}, "first_published": "2026-01-01", "absolute_url": "https://x/1"}]}))
    adapter = GreenhouseAdapter(cfg("Acme", "greenhouse", endpoint="https://api/jobs", params={"content": True}), http)
    jobs = adapter.list_jobs()
    assert jobs[0].description == "Graduate"
    assert jobs[0].location == "NYC"


def test_ashby_normalizes(make_http):
    http = make_http(lambda req: response(req, {"jobs": [{"id": "a", "title": "SDE I", "descriptionHtml": "<b>Build</b>", "location": "Remote", "publishedAt": "now", "jobUrl": "https://job", "applyUrl": "https://apply"}]}))
    adapter = AshbyAdapter(cfg("Acme", "ashby", endpoint="https://api/jobs"), http)
    job = adapter.list_jobs()[0]
    assert job.job_id == "a" and job.apply_url == "https://apply" and job.description == "Build"


def test_amazon_paginates_without_duplicate(make_http):
    def handler(req):
        offset = int(req.url.params["offset"])
        rows = [] if offset >= 2 else [{"id": str(offset + 1), "title": "Software Engineer", "description": "desc", "location": "US", "job_path": f"/en/jobs/{offset + 1}"}]
        return response(req, {"jobs": rows, "hits": 2})

    adapter = AmazonAdapter(
        cfg("Amazon", "amazon_jobs_json", endpoint="https://api/search", pagination={"default_limit": 1, "offset_param": "offset", "limit_param": "result_limit"}),
        make_http(handler),
    )
    jobs = adapter.list_jobs()
    assert [job.job_id for job in jobs] == ["1", "2"]
    assert jobs[0].job_url == "https://www.amazon.jobs/en/jobs/1"


def test_amazon_stops_at_reported_total_even_with_duplicate_ids(make_http):
    calls = []

    def handler(req):
        calls.append(int(req.url.params["offset"]))
        return response(req, {"jobs": [{"id": "same", "title": "Software Engineer", "description": "desc", "job_path": "/en/jobs/same"}], "hits": 2})

    adapter = AmazonAdapter(
        cfg("Amazon", "amazon_jobs_json", endpoint="https://api/search", params={"sort": "recent"}, pagination={"default_limit": 1, "offset_param": "offset", "limit_param": "result_limit"}),
        make_http(handler),
    )
    jobs = adapter.list_jobs()
    assert len(jobs) == 1
    assert calls == [0, 1]
