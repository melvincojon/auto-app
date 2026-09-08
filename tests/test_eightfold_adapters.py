from __future__ import annotations

import httpx

from job_monitor.adapters.eightfold import EightfoldApplyV2Adapter, EightfoldPCSXAdapter
from job_monitor.config import CompanyConfig


def cfg(company, adapter, **values):
    return CompanyConfig(company, adapter, {"company": company, "adapter": adapter, **values})


def json_response(req, payload):
    return httpx.Response(200, json=payload, request=req, headers={"content-type": "application/json"})


def test_pcsx_bootstrap_pagination_and_detail(make_http):
    def handler(req):
        if req.url.path == "/careers":
            return httpx.Response(200, text='<meta name="_csrf" content="token">', request=req, headers={"content-type": "text/html"})
        assert req.headers["x-csrf-token"] == "token"
        if req.url.path.endswith("position_details"):
            return json_response(req, {"data": {"id": "1", "name": "Software Engineer", "jobDescription": "Graduate role", "locations": ["NYC"], "publicUrl": "https://job/1"}})
        start = int(req.url.params["start"])
        rows = [] if start >= 2 else [{"id": str(start + 1), "name": "Software Engineer", "positionUrl": f"https://job/{start + 1}"}]
        return json_response(req, {"data": {"positions": rows, "count": 2}})

    adapter = EightfoldPCSXAdapter(
        cfg(
            "Microsoft", "eightfold_pcsx_session", endpoint="https://x/api/pcsx/search",
            params={"domain": "microsoft.com", "num": 1},
            pagination={"offset_param": "start", "default_limit": 1},
            session_bootstrap={"url": "https://x/careers", "csrf_meta_name": "_csrf", "request_header": "x-csrf-token", "referer": "https://x/careers"},
            detail={"endpoint": "https://x/api/pcsx/position_details", "id_param": "position_id", "params": {"domain": "microsoft.com"}},
        ), make_http(handler)
    )
    jobs = adapter.list_jobs()
    assert [j.job_id for j in jobs] == ["1", "2"]
    assert adapter.hydrate(jobs[0]).description == "Graduate role"


def test_apply_v2_pagination_and_detail(make_http):
    def handler(req):
        if req.url.path.endswith("/1"):
            return json_response(req, {"id": "1", "name": "Backend Engineer", "job_description": "Entry level", "canonicalPositionUrl": "https://job/1"})
        start = int(req.url.params["start"])
        rows = [] if start >= 2 else [{"id": str(start + 1), "name": "Backend Engineer", "canonicalPositionUrl": f"https://job/{start + 1}"}]
        return json_response(req, {"positions": rows, "count": 2})

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            params={"domain": "netflix.com", "num": 1},
            pagination={"offset_param": "start", "limit_param": "num"},
            detail={"url_template": "https://x/api/jobs/{id}", "params": {"domain": "netflix.com"}},
        ), make_http(handler)
    )
    jobs = adapter.list_jobs()
    assert len(jobs) == 2
    assert adapter.hydrate(jobs[0]).description == "Entry level"
