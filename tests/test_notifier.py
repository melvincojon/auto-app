import json

import httpx
import pytest

from job_monitor.cli import main
from job_monitor.models import HealthWarning, Job, Match, MatchCategory
from job_monitor.notifier import (
    NOTIFICATION_TEST_MESSAGE,
    ConsoleNotifier,
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
    assert embed["url"] == "https://job"
    assert "NEW_GRAD_MATCH" in embed["description"]
    rendered = str(payload)
    for text in ("Acme", "Software Engineer", "New York", "Sep 8, 2026", "new-graduate"):
        assert text in rendered
    assert payload["allowed_mentions"] == {"parse": []}


@pytest.mark.parametrize(
    ("job_url", "apply_url", "expected"),
    [
        ("https://job", "https://apply", "https://job"),
        ("https://job", None, "https://job"),
        ("", "https://apply", "https://apply"),
    ],
)
def test_job_notification_prefers_description_url_with_apply_fallback(
    job_url, apply_url, expected
):
    job = Job(
        "Acme", "test", "1", "Engineer", None, None, None, job_url, apply_url
    )

    payload = discord_job_payload(
        job, Match(MatchCategory.NEW_GRAD_MATCH, "new-graduate language")
    )

    assert payload["embeds"][0]["url"] == expected


@pytest.mark.parametrize(
    ("job_url", "apply_url", "expected"),
    [
        ("https://job", "https://apply", "https://job"),
        ("https://job", None, "https://job"),
        ("", "https://apply", "https://apply"),
    ],
)
def test_console_notification_uses_same_url_priority(
    job_url, apply_url, expected, capsys
):
    job = Job(
        "Acme", "test", "1", "Engineer", None, "New York", None, job_url, apply_url
    )
    notifier = ConsoleNotifier()

    notifier.notify_job(
        job, Match(MatchCategory.NEW_GRAD_MATCH, "new-graduate language")
    )

    assert capsys.readouterr().out.rstrip().endswith(f" | {expected}")


@pytest.mark.parametrize(
    ("posted_at", "expected"),
    [
        ("2026-09-09T20:32:00Z", "Sep 9, 2026 at 4:32 PM ET"),
        ("2026-01-09T20:32:00+00:00", "Jan 9, 2026 at 3:32 PM ET"),
        ("2026-09-09T17:30:00-07:00", "Sep 9, 2026 at 8:30 PM ET"),
        ("2026-09-09", "Sep 9, 2026"),
        ("2026-09-09T20:32:00", "Sep 9, 2026 at 8:32 PM"),
    ],
)
def test_job_notification_formats_posted_at(posted_at, expected):
    job = Job(
        "Acme", "test", "1", "Engineer", None, None, posted_at, "https://job"
    )

    payload = discord_job_payload(
        job, Match(MatchCategory.NEW_GRAD_MATCH, "new-graduate language")
    )

    posted_field = next(
        field for field in payload["embeds"][0]["fields"] if field["name"] == "Posted"
    )
    assert posted_field == {"name": "Posted", "value": expected, "inline": True}
    assert job.posted_at == posted_at


def test_job_notification_uses_capped_raw_posted_at_when_unrecognized():
    posted_at = "not-a-timestamp" * 20
    job = Job(
        "Acme", "test", "1", "Engineer", None, None, posted_at, "https://job"
    )

    payload = discord_job_payload(
        job, Match(MatchCategory.NEW_GRAD_MATCH, "new-graduate language")
    )

    posted_field = next(
        field for field in payload["embeds"][0]["fields"] if field["name"] == "Posted"
    )
    assert posted_field["value"] == posted_at[:100]


def test_job_notification_omits_posted_field_when_missing():
    job = Job("Acme", "test", "1", "Engineer", None, None, None, "https://job")

    payload = discord_job_payload(
        job, Match(MatchCategory.NEW_GRAD_MATCH, "new-graduate language")
    )

    assert all(
        field["name"] != "Posted" for field in payload["embeds"][0]["fields"]
    )


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
