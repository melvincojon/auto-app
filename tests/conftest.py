from __future__ import annotations

import httpx
import pytest

from job_monitor.http import HttpClient


@pytest.fixture
def make_http():
    clients: list[HttpClient] = []

    def factory(handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        wrapped = HttpClient(client=client, retries=0, backoff_seconds=0)
        clients.append(wrapped)
        return wrapped

    yield factory
    for client in clients:
        client.client.close()
