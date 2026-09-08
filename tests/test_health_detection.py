from __future__ import annotations

import httpx
import pytest

from job_monitor.adapters import build_adapter
from job_monitor.adapters.simple import GreenhouseAdapter
from job_monitor.config import CompanyConfig
from job_monitor.errors import SourceError


def cfg(adapter="greenhouse", **values):
    return CompanyConfig("Acme", adapter, {"company": "Acme", "adapter": adapter, **values})


def test_non_200_is_classified(make_http):
    http = make_http(lambda req: httpx.Response(404, request=req))
    with pytest.raises(SourceError, match="HTTP 404") as caught:
        http.request("GET", "https://x/jobs")
    assert caught.value.code == "non_200_response"


def test_rate_limit_is_classified(make_http):
    http = make_http(lambda req: httpx.Response(429, request=req))
    with pytest.raises(SourceError) as caught:
        http.request("GET", "https://x/jobs")
    assert caught.value.code == "rate_limited"


def test_unexpected_json_content_type_is_classified(make_http):
    response = httpx.Response(200, text="<html>blocked</html>", headers={"content-type": "text/html"})
    with pytest.raises(SourceError) as caught:
        make_http(lambda req: response).json(response)
    assert caught.value.code == "unexpected_content_type"


def test_invalid_json_is_classified(make_http):
    response = httpx.Response(200, text="not-json", headers={"content-type": "application/json"})
    with pytest.raises(SourceError) as caught:
        make_http(lambda req: response).json(response)
    assert caught.value.code == "unexpected_json"


def test_unexpected_html_is_classified(make_http):
    response = httpx.Response(200, text="plain text", headers={"content-type": "text/html"})
    with pytest.raises(SourceError) as caught:
        make_http(lambda req: response).html(response)
    assert caught.value.code == "unexpected_html"


def test_empty_inventory_is_suspicious(make_http):
    def handler(req):
        return httpx.Response(
            200, json={"jobs": []}, request=req, headers={"content-type": "application/json"}
        )

    adapter = GreenhouseAdapter(cfg(endpoint="https://x/jobs"), make_http(handler))
    with pytest.raises(SourceError) as caught:
        adapter.list_jobs()
    assert caught.value.code == "suspicious_empty_response"


def test_unknown_adapter_is_configuration_drift(make_http):
    with pytest.raises(SourceError) as caught:
        build_adapter(cfg(adapter="made_up"), make_http(lambda req: None))
    assert caught.value.code == "configuration_drift"
