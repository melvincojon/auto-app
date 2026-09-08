from __future__ import annotations

from job_monitor.config import CompanyConfig
from job_monitor.errors import SourceError
from job_monitor.models import Job
from job_monitor.runner import run_monitor
from job_monitor.state import MonitorState


class RecordingNotifier:
    def __init__(self):
        self.jobs = []
        self.health = []

    def notify_job(self, job, match):
        self.jobs.append((job, match))

    def notify_health(self, warning):
        self.health.append(warning)


class FakeAdapter:
    def __init__(self, jobs=None, failure=None):
        self.jobs = jobs or []
        self.failure = failure

    def list_jobs(self):
        if self.failure:
            raise self.failure
        return self.jobs

    def hydrate(self, job):
        return job

    def _validate_job(self, job, require_description=False):
        return None


def cfg(name):
    return CompanyConfig(name, "fake", {"company": name, "adapter": "fake"})


def job(company, job_id, title="Software Engineer", description="New graduate role"):
    return Job(company, "fake", job_id, title, description, "NYC", None, f"https://x/{job_id}")


def test_first_run_seeds_without_backlog_then_notifies_once(monkeypatch):
    jobs = [job("Acme", "1")]
    adapter = FakeAdapter(jobs)
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = MonitorState()
    notifier = RecordingNotifier()

    first = run_monitor([cfg("Acme")], state, notifier, object())
    assert first.seeded_companies == ["Acme"]
    assert notifier.jobs == []

    jobs.append(job("Acme", "2"))
    second = run_monitor([cfg("Acme")], state, notifier, object())
    third = run_monitor([cfg("Acme")], state, notifier, object())
    assert second.notifications == 1
    assert third.notifications == 0
    assert len(notifier.jobs) == 1


def test_source_failure_does_not_stop_other_companies(monkeypatch):
    adapters = {
        "Broken": FakeAdapter(failure=SourceError("rate_limited", "429")),
        "Healthy": FakeAdapter([job("Healthy", "1")]),
    }
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapters[config.company])
    state = MonitorState()
    notifier = RecordingNotifier()
    report = run_monitor([cfg("Broken"), cfg("Healthy")], state, notifier, object())
    assert report.checked_companies == 1
    assert state.is_seeded("Healthy")
    assert report.warnings[0].code == "rate_limited"
    assert notifier.health == report.warnings
