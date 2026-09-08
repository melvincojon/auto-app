from __future__ import annotations

import json

import httpx

from job_monitor.adapters.versioned import MetaRelayAdapter, RipplingAdapter
from job_monitor.config import CompanyConfig


def cfg(company, adapter, **values):
    return CompanyConfig(company, adapter, {"company": company, "adapter": adapter, **values})


def test_meta_bootstrap_html_typed_json_and_detail(make_http):
    def handler(req):
        if req.url.path == "/jobsearch/":
            return httpx.Response(200, text='<script>["LSD",[],{"token":"abc"}]</script>', request=req, headers={"content-type": "text/html"})
        if req.url.path == "/api/graphql/":
            assert req.headers["x-fb-lsd"] == "abc"
            return httpx.Response(200, text=json.dumps({"data": {"job_search": {"all_jobs": [{"id": "1", "title": "Software Engineer", "locations": ["NYC"]}]}}}), request=req, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(200, text='<script type="application/ld+json">{"@type":"JobPosting","title":"Software Engineer","description":"New graduate","datePosted":"2026-01-01","jobLocation":{"address":{"addressLocality":"NYC"}}}</script>', request=req, headers={"content-type": "text/html"})

    adapter = MetaRelayAdapter(
        cfg(
            "Meta", "meta_relay_jsonld", endpoint="https://x/api/graphql/",
            session_bootstrap={"url": "https://x/jobsearch/", "request_header": "x-fb-lsd", "referer": "https://x/jobsearch/"},
            request={"friendly_name": "Query", "doc_id": "123", "variables": {"search_input": {}}},
        ), make_http(handler)
    )
    jobs = adapter.list_jobs()
    assert jobs[0].location == "NYC"
    assert adapter.hydrate(jobs[0]).description == "New graduate"


def test_rippling_pagination_deduplicates_by_job_id_and_hydrates(make_http):
    def handler(req):
        if req.url.path.startswith("/job/"):
            data = {"props": {"pageProps": {"apiData": {"jobPost": {"id": "j1", "name": "Software Engineer", "jobDescription": "Entry level", "workLocations": ["NYC", "Remote"], "createdOn": "2026-01-01", "url": "https://x/job/j1"}}}}}
            return httpx.Response(200, text=f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>', request=req, headers={"content-type": "text/html"})
        posted = json.loads(req.content)
        params = posted["requests"][0]["params"]
        page = 1 if "page=1" in params else 0
        hit = {"objectID": f"o{page}", "jobId": "j1" if page == 0 else "j2", "name": "Software Engineer", "locationNames": ["NYC"], "url": f"https://x/job/j{page + 1}"}
        return httpx.Response(200, json={"results": [{"hits": [hit], "nbPages": 2}]}, request=req, headers={"content-type": "application/json"})

    adapter = RipplingAdapter(
        cfg(
            "Rippling", "rippling_algolia_next_data", endpoint="https://x/queries",
            headers={"content-type": "application/json", "x-algolia-application-id": "app", "x-algolia-api-key": "key"},
            request={"index_name": "index", "default_hits_per_page": 1},
            pagination={"starts_at": 0},
            detail={"json_path": "props.pageProps.apiData.jobPost"},
        ), make_http(handler)
    )
    jobs = adapter.list_jobs()
    assert [job.job_id for job in jobs] == ["j1", "j2"]
    assert adapter.hydrate(jobs[0]).description == "Entry level"
