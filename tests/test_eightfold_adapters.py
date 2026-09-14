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
    # Each scan re-reads the first page as a final mutation anchor.
    assert starts == [0, 0, 0, 0]
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
    assert exc.value.code == "reconciliation_inconsistency"


def test_microsoft_does_not_restart_entire_inconsistent_scan(make_http):
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

    with pytest.raises(SourceError) as exc:
        adapter.list_jobs()
    assert exc.value.code == "reconciliation_inconsistency"
    assert bootstrap_count == 1


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


def test_microsoft_discovery_fetches_first_two_timestamp_sorted_pages(make_http):
    starts = []

    def handler(req):
        if req.url.path == "/careers":
            return httpx.Response(200, text='<meta name="_csrf" content="token">', request=req, headers={"content-type": "text/html"})
        starts.append(int(req.url.params["start"]))
        assert req.url.params["sort_by"] == "timestamp"
        start = starts[-1]
        rows = [{"id": str(value), "name": "Engineer", "positionUrl": f"https://job/{value}"} for value in range(start + 1, start + 11)]
        return json_response(req, {"data": {"positions": rows, "count": 100}})

    adapter = EightfoldPCSXAdapter(
        cfg(
            "Microsoft", "eightfold_pcsx_session", endpoint="https://x/api/pcsx/search",
            discovery_pages=2,
            params={"domain": "microsoft.com", "num": 10, "sort_by": "timestamp"},
            pagination={"offset_param": "start", "default_limit": 10, "overlap": 2},
            session_bootstrap={"url": "https://x/careers", "csrf_meta_name": "_csrf", "request_header": "x-csrf-token", "referer": "https://x/careers"},
            detail={"endpoint": "https://x/detail", "id_param": "position_id"},
        ), make_http(handler)
    )

    assert [job.job_id for job in adapter.discover_jobs()] == [str(value) for value in range(1, 21)]
    assert starts == [0, 10]


def test_netflix_discovery_fetches_first_five_pages(make_http):
    starts = []

    def handler(req):
        start = int(req.url.params["start"])
        starts.append(start)
        rows = [{"id": str(value), "name": "Engineer", "canonicalPositionUrl": f"https://job/{value}"} for value in range(start + 1, start + 11)]
        return json_response(req, {"positions": rows, "count": 100})

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            discovery_pages=5,
            params={"domain": "netflix.com", "num": 10},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 10, "overlap": 2},
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    assert [job.job_id for job in adapter.discover_jobs()] == [str(value) for value in range(1, 51)]
    assert starts == [0, 10, 20, 30, 40]


def test_discovery_deduplicates_ids_across_pages(make_http):
    def handler(req):
        start = int(req.url.params["start"])
        values = range(1, 11) if start == 0 else range(10, 20)
        rows = [{"id": str(value), "name": "Engineer", "canonicalPositionUrl": f"https://job/{value}"} for value in values]
        return json_response(req, {"positions": rows, "count": 100})

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            discovery_pages=2,
            params={"domain": "netflix.com", "num": 10},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 10, "overlap": 2},
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    assert [job.job_id for job in adapter.discover_jobs()] == [str(value) for value in range(1, 20)]


def test_reconciliation_reuses_matching_discovery_offset(make_http):
    starts = []
    all_ids = [str(value) for value in range(1, 51)]

    def handler(req):
        start = int(req.url.params["start"])
        starts.append(start)
        ids = all_ids[start:start + 10]
        rows = [{"id": value, "name": "Engineer", "canonicalPositionUrl": f"https://job/{value}"} for value in ids]
        return json_response(req, {"positions": rows, "count": len(all_ids)})

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            discovery_pages=5,
            params={"domain": "netflix.com", "num": 10},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 10, "overlap": 2},
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    adapter.discover_jobs()
    assert len(adapter.list_jobs()) == 50
    assert starts == [0, 10, 20, 30, 40, 8, 16, 24, 32, 0]
    assert starts.count(0) == 2  # Discovery plus the required final anchor check.
    assert starts.count(40) == 1  # Reused directly by the overlapping crawl.


def test_overlap_detects_shifted_offset_from_result_mutation(make_http):
    def handler(req):
        start = int(req.url.params["start"])
        rows = {
            0: ["1", "2", "3", "4"],
            3: ["3", "4", "5", "6"],
        }.get(start, ["7"])
        return json_response(
            req,
            {"positions": [{"id": value, "name": "Engineer", "canonicalPositionUrl": f"https://job/{value}"} for value in rows], "count": 7},
        )

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            params={"domain": "netflix.com", "num": 4},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 4, "overlap": 1},
            range_retries=0,
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    with pytest.raises(SourceError, match="boundary shifted") as exc:
        adapter.list_jobs()
    assert exc.value.code == "reconciliation_inconsistency"


@pytest.mark.parametrize(
    ("mutation", "later_rows", "later_total"),
    [
        ("insertion", ["3", "4", "5", "6"], 8),
        ("removal", ["5", "6", "7"], 6),
    ],
)
def test_mutation_during_pagination_fails_closed(
    make_http, mutation, later_rows, later_total
):
    calls = 0

    def handler(req):
        nonlocal calls
        calls += 1
        start = int(req.url.params["start"])
        rows = ["1", "2", "3", "4"] if start == 0 and calls == 1 else later_rows
        total = 7 if calls == 1 else later_total
        return json_response(
            req,
            {"positions": [{"id": value, "name": mutation, "canonicalPositionUrl": f"https://job/{value}"} for value in rows], "count": total},
        )

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            params={"domain": "netflix.com", "num": 4},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 4, "overlap": 1},
            range_retries=0,
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    with pytest.raises(SourceError) as exc:
        adapter.list_jobs()
    assert exc.value.code == "reconciliation_inconsistency"


def test_advertised_total_change_is_not_accepted(make_http):
    def handler(req):
        start = int(req.url.params["start"])
        ids = ["1", "2", "3", "4"] if start == 0 else ["4", "5", "6", "7"]
        total = 7 if start == 0 else 8
        return json_response(
            req,
            {"positions": [{"id": value, "name": "Engineer", "canonicalPositionUrl": f"https://job/{value}"} for value in ids], "count": total},
        )

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            params={"domain": "netflix.com", "num": 4},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 4, "overlap": 1},
            range_retries=0,
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    with pytest.raises(SourceError, match="advertised total changed"):
        adapter.list_jobs()


def test_shifted_late_range_is_repaired_without_full_restart(make_http):
    starts = []
    offset_six_calls = 0

    def handler(req):
        nonlocal offset_six_calls
        start = int(req.url.params["start"])
        starts.append(start)
        if start == 0:
            ids = ["1", "2", "3", "4"]
        elif start == 3:
            ids = ["4", "5", "6", "7"]
        else:
            offset_six_calls += 1
            ids = ["6", "7", "8", "9"] if offset_six_calls == 1 else ["7", "8", "9", "10"]
        return json_response(
            req,
            {"positions": [{"id": value, "name": "Engineer", "canonicalPositionUrl": f"https://job/{value}"} for value in ids], "count": 10},
        )

    adapter = EightfoldApplyV2Adapter(
        cfg(
            "Netflix", "eightfold_apply_v2", endpoint="https://x/api/jobs",
            params={"domain": "netflix.com", "num": 4},
            pagination={"offset_param": "start", "limit_param": "num", "default_limit": 4, "overlap": 1},
            range_retries=1,
            detail={"url_template": "https://x/api/jobs/{id}"},
        ), make_http(handler)
    )

    assert [job.job_id for job in adapter.list_jobs()] == [str(value) for value in range(1, 11)]
    assert starts == [0, 3, 6, 3, 6, 0]
