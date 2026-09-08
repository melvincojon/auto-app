from job_monitor.models import Job
from job_monitor.state import MonitorState


def make_job(job_id="42"):
    return Job("Acme", "test", job_id, "Software Engineer", None, None, None, "https://x")


def test_state_round_trip_and_company_seed(tmp_path):
    path = tmp_path / "state.json"
    state = MonitorState()
    state.seed("Acme", [make_job()])
    state.save(path)

    loaded = MonitorState.load(path)
    assert loaded.is_seeded("ACME")
    assert loaded.has_seen(make_job())


def test_identity_uses_company_and_provider_id():
    assert make_job().identity == make_job().identity
    assert make_job("43").identity != make_job().identity
    other = make_job()
    other.company = "Other"
    assert other.identity != make_job().identity
