import json

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
    state.save(path)

    loaded = MonitorState.load(path)
    assert loaded.is_seeded("ACME")
    assert loaded.has_seen(make_job())
    assert loaded.job_failures[failed_job.identity]["failure_count"] == 1
    assert loaded.job_failures[failed_job.identity]["error_code"] == "schema_change"


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
