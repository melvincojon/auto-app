import json

import httpx

from job_monitor.cli import main
from job_monitor.models import HealthWarning, Job, Match, MatchCategory
from job_monitor.notifier import (
    NOTIFICATION_TEST_MESSAGE,
    DiscordNotifier,
    discord_health_payload,
    discord_job_payload,
    discord_test_payload,
)


def test_job_notification_is_concise_and_complete():
    job = Job(
        "Acme", "test", "1", "Software Engineer", "desc", "New York", "2026-09-08", "https://job", "https://apply"
    )
    payload = discord_job_payload(
        job, Match(MatchCategory.NEW_GRAD_MATCH, "new-graduate language")
    )
    embed = payload["embeds"][0]
    assert embed["url"] == "https://apply"
    assert "NEW_GRAD_MATCH" in embed["description"]
    rendered = str(payload)
    for text in ("Acme", "Software Engineer", "New York", "2026-09-08", "new-graduate"):
        assert text in rendered
    assert payload["allowed_mentions"] == {"parse": []}


def test_health_notification_contains_failure():
    payload = discord_health_payload(HealthWarning("Meta", "schema_change", "all_jobs missing"))
    assert "Meta" in payload["embeds"][0]["title"]
    assert "all_jobs missing" in payload["embeds"][0]["description"]


def test_notification_test_payload_and_delivery_path(make_http):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    notifier = DiscordNotifier("https://discord.example/webhook", make_http(handler))
    notifier.notify_test()

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "https://discord.example/webhook"
    payload = json.loads(requests[0].content)
    assert payload == discord_test_payload()
    assert payload["content"] == NOTIFICATION_TEST_MESSAGE


def test_notification_cli_sends_once_without_loading_sources_or_state(
    make_http, monkeypatch
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    http = make_http(handler)
    monkeypatch.setattr("job_monitor.cli.HttpClient", lambda: http)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    result = main(["--config", "does-not-exist.yaml", "test-notification"])

    assert result == 0
    assert len(requests) == 1
    assert json.loads(requests[0].content)["content"] == NOTIFICATION_TEST_MESSAGE
