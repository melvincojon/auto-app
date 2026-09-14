import json
from datetime import UTC, datetime, timedelta

from job_monitor.models import Job
from job_monitor.state import MonitorState


def make_job(job_id="42"):
    return Job("Acme", "test", job_id, "Software Engineer", None, None, None, "https://x")


def test_state_round_trip_and_company_seed(tmp_path):
    path = tmp_path / "state.json"
    state = MonitorState()
    state.seed("Acme", [make_job()])
    failed_job = make_job("43")
    state.record_job_failure(failed_job, "schema_change", "detail is invalid")
    state.record_source_success("Acme", [make_job()])
    state.save(path)

    loaded = MonitorState.load(path)
    assert loaded.is_seeded("ACME")
    assert loaded.has_seen(make_job())
    assert loaded.job_failures[failed_job.identity]["failure_count"] == 1
    assert loaded.job_failures[failed_job.identity]["error_code"] == "schema_change"
    assert loaded.source_health["acme"]["last_successful_job_count"] == 1


def test_source_failure_preserves_last_known_good_snapshot():
    state = MonitorState()
    successful_at = datetime(2026, 9, 13, tzinfo=UTC)
    state.record_source_success("Acme", [make_job("1"), make_job("2")], now=successful_at)

    count = state.record_source_failure(
        "Acme",
        "pagination_failure",
        "page repeated",
        now=successful_at + timedelta(minutes=5),
    )

    health = state.source_health["acme"]
    assert count == 1
    assert health["last_successful_scan"] == successful_at.isoformat()
    assert health["last_successful_job_count"] == 2
    assert health["last_successful_job_ids"] == ["1", "2"]
    assert health["consecutive_failures"] == 1


def test_source_recovery_resets_consecutive_failures():
    state = MonitorState()
    state.record_source_failure("Acme", "network_failure", "timeout")

    recovered = state.record_source_success("Acme", [make_job()])

    assert recovered is True
    assert state.source_health["acme"]["consecutive_failures"] == 0


def test_reconciliation_failure_preserves_authoritative_snapshot_and_health():
    state = MonitorState()
    jobs = [make_job("1"), make_job("2")]
    state.record_source_success("Acme", jobs)

    count = state.record_reconciliation_failure("Acme", "offset shifted")

    health = state.source_health["acme"]
    assert count == 1
    assert health["last_successful_job_ids"] == ["1", "2"]
    assert health["last_successful_job_count"] == 2
    assert health["consecutive_failures"] == 0
    assert health["consecutive_reconciliation_failures"] == 1


def test_identity_uses_company_and_provider_id():
    assert make_job().identity == make_job().identity
    assert make_job("43").identity != make_job().identity
    other = make_job()
    other.company = "Other"
    assert other.identity != make_job().identity


def test_version_one_state_without_job_failures_still_loads(tmp_path):
    path = tmp_path / "old-state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "seeded_companies": ["acme"],
                "seen": {make_job().identity: {"job_id": "42"}},
            }
        )
    )

    state = MonitorState.load(path)

    assert state.is_seeded("Acme")
    assert state.has_seen(make_job())
    assert state.job_failures == {}
