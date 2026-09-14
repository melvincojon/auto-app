from __future__ import annotations

import httpx
import pytest

from job_monitor.adapters.eightfold import EightfoldApplyV2Adapter, EightfoldPCSXAdapter
from job_monitor.config import CompanyConfig
from job_monitor.errors import SourceError


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


def test_microsoft_uses_fresh_anonymous_bootstrap_for_every_scan(make_http, caplog):
    caplog.set_level("INFO")
    bootstrap_cookies = []
    starts = []

    def handler(req):
        if req.url.path == "/careers":
            bootstrap_cookies.append(req.headers.get("cookie"))
            return httpx.Response(
                200,
                text='<meta name="_csrf" content="fresh-token">',
                request=req,
                headers={"content-type": "text/html", "set-cookie": "session=fresh; Path=/"},
            )
        assert req.headers["x-csrf-token"] == "fresh-token"
        starts.append(int(req.url.params["start"]))
        return json_response(req, {"data": {"positions": [{"id": "1", "name": "Engineer", "positionUrl": "https://job/1"}], "count": 1}})

    http = make_http(handler)
    http.client.cookies.set("session", "stale")
    adapter = EightfoldPCSXAdapter(
        cfg(
            "Microsoft", "eightfold_pcsx_session", endpoint="https://x/api/pcsx/search",
            params={"domain": "microsoft.com", "num": 10}, pagination={"offset_param": "start", "default_limit": 10},
            session_bootstrap={"url": "https://x/careers", "csrf_meta_name": "_csrf", "request_header": "x-csrf-token", "referer": "https://x/careers"},
            detail={"endpoint": "https://x/api/pcsx/position_details", "id_param": "position_id"},
        ), http
    )

    adapter.list_jobs()
    adapter.list_jobs()

    assert bootstrap_cookies == [None, None]
    assert starts == [0, 0]
    assert "Microsoft page start=0" in caplog.text


def test_microsoft_repeated_offset_logs_ids_and_fails_closed(make_http):
    def handler(req):
        if req.url.path == "/careers":
            return httpx.Response(200, text='<meta name="_csrf" content="token">', request=req, headers={"content-type": "text/html"})
        return json_response(req, {"data": {"positions": [{"id": "same", "name": "Engineer", "positionUrl": "https://job/same"}], "count": 2}})

    adapter = EightfoldPCSXAdapter(
        cfg(
            "Microsoft", "eightfold_pcsx_session", endpoint="https://x/api/pcsx/search",
            params={"domain": "microsoft.com", "num": 1}, pagination={"offset_param": "start", "default_limit": 1},
            session_bootstrap={"url": "https://x/careers", "csrf_meta_name": "_csrf", "request_header": "x-csrf-token", "referer": "https://x/careers"},
            detail={"endpoint": "https://x/detail", "id_param": "position_id"},
        ), make_http(handler)
    )

    with pytest.raises(SourceError, match="start=1.*same") as exc:
        adapter.list_jobs()
    assert exc.value.code == "pagination_failure"


def test_microsoft_restarts_inconsistent_full_scan_with_fresh_session(make_http):
    bootstrap_count = 0

    def handler(req):
        nonlocal bootstrap_count
        if req.url.path == "/careers":
            bootstrap_count += 1
            return httpx.Response(200, text=f'<meta name="_csrf" content="token-{bootstrap_count}">', request=req, headers={"content-type": "text/html"})
        start = int(req.url.params["start"])
        assert req.headers["x-csrf-token"] == f"token-{bootstrap_count}"
        if bootstrap_count == 1 and start == 1:
            rows = []
        else:
            rows = [{"id": str(start + 1), "name": "Engineer", "positionUrl": f"https://job/{start + 1}"}]
        return json_response(req, {"data": {"positions": rows, "count": 2}})

    adapter = EightfoldPCSXAdapter(
        cfg(
            "Microsoft", "eightfold_pcsx_session", endpoint="https://x/api/pcsx/search", scan_retries=1,
            params={"domain": "microsoft.com", "num": 1}, pagination={"offset_param": "start", "default_limit": 1},
            session_bootstrap={"url": "https://x/careers", "csrf_meta_name": "_csrf", "request_header": "x-csrf-token", "referer": "https://x/careers"},
            detail={"endpoint": "https://x/detail", "id_param": "position_id"},
        ), make_http(handler)
    )

    assert [job.job_id for job in adapter.list_jobs()] == ["1", "2"]
    assert bootstrap_count == 2


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
