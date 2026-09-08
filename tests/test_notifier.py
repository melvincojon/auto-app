from job_monitor.models import HealthWarning, Job, Match, MatchCategory
from job_monitor.notifier import discord_health_payload, discord_job_payload


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
