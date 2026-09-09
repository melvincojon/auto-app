from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_monitor.config import CompanyConfig
from job_monitor.errors import NotificationError, SourceError
from job_monitor.models import Job
from job_monitor.runner import run_monitor
from job_monitor.state import MonitorState


class RecordingNotifier:
    def __init__(self, job_failure=None):
        self.jobs = []
        self.health = []
        self.job_failure = job_failure

    def notify_job(self, job, match):
        if self.job_failure:
            raise self.job_failure
        self.jobs.append((job, match))

    def notify_health(self, warning):
        self.health.append(warning)


class FakeAdapter:
    def __init__(self, jobs=None, failure=None, hydrate_failure=None):
        self.jobs = jobs or []
        self.failure = failure
        self.hydrate_failure = hydrate_failure
        self.hydrate_calls = 0

    def list_jobs(self):
        if self.failure:
            raise self.failure
        return self.jobs

    def hydrate(self, job):
        self.hydrate_calls += 1
        if self.hydrate_failure:
            raise self.hydrate_failure
        return job

    def _validate_job(self, job, require_description=False):
        return None


def cfg(name):
    return CompanyConfig(name, "fake", {"company": name, "adapter": "fake"})


def job(company, job_id, title="Software Engineer", description="New graduate role"):
    return Job(company, "fake", job_id, title, description, "NYC", None, f"https://x/{job_id}")


def seeded_state(company="Acme"):
    return MonitorState(seeded_companies={company.casefold()})


def failing_job_adapter(error=None):
    return FakeAdapter(
        [job("Acme", "1064155186370895")],
        hydrate_failure=error
        or SourceError("schema_change", "no JobPosting JSON-LD found on detail page"),
    )


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


def test_foreign_only_new_job_is_seen_without_notification(monkeypatch):
    jobs = [job("Acme", "1")]
    adapter = FakeAdapter(jobs)
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = MonitorState()
    notifier = RecordingNotifier()
    run_monitor([cfg("Acme")], state, notifier, object())

    foreign = Job(
        "Acme",
        "fake",
        "2",
        "Software Engineer",
        "New graduate role",
        "Remote - Canada",
        None,
        "https://x/2",
    )
    jobs.append(foreign)
    report = run_monitor([cfg("Acme")], state, notifier, object())

    assert report.new_jobs == 1
    assert report.notifications == 0
    assert notifier.jobs == []
    assert state.has_seen(foreign)


def test_first_per_job_source_failure_warns_and_persists(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    listing = adapter.jobs[0]

    report = run_monitor([cfg("Acme")], state, RecordingNotifier(), object())

    assert len(report.warnings) == 1
    assert report.warnings[0].message.startswith(f"job {listing.job_id}:")
    assert state.job_failures[listing.identity]["failure_count"] == 1
    assert state.job_failures[listing.identity]["error_code"] == "schema_change"
    assert "last_failure_at" in state.job_failures[listing.identity]
    assert not state.has_seen(listing)


def test_second_identical_job_failure_suppresses_duplicate_warning(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    notifier = RecordingNotifier()

    run_monitor([cfg("Acme")], state, notifier, object())
    report = run_monitor([cfg("Acme")], state, notifier, object())

    assert report.warnings == []
    assert len(notifier.health) == 1
    assert state.job_failures[adapter.jobs[0].identity]["failure_count"] == 2


def test_third_identical_job_failure_starts_quarantine(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()

    for _ in range(3):
        report = run_monitor([cfg("Acme")], state, RecordingNotifier(), object())

    failure = state.job_failures[adapter.jobs[0].identity]
    assert failure["failure_count"] == 3
    assert datetime.fromisoformat(failure["quarantined_until"]) > datetime.now(UTC)
    assert report.warnings == []


def test_quarantined_job_skips_hydration_without_warning_or_seen(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    notifier = RecordingNotifier()
    for _ in range(3):
        run_monitor([cfg("Acme")], state, notifier, object())

    report = run_monitor([cfg("Acme")], state, notifier, object())

    assert adapter.hydrate_calls == 3
    assert report.warnings == []
    assert notifier.jobs == []
    assert not state.has_seen(adapter.jobs[0])


def test_retry_after_quarantine_expiry_attempts_hydration_again(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    for _ in range(3):
        run_monitor([cfg("Acme")], state, RecordingNotifier(), object())
    failure = state.job_failures[adapter.jobs[0].identity]
    failure["quarantined_until"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    report = run_monitor([cfg("Acme")], state, RecordingNotifier(), object())

    assert adapter.hydrate_calls == 4
    assert report.warnings == []
    assert state.job_failures[adapter.jobs[0].identity]["failure_count"] == 4


def test_successful_retry_clears_failure_and_resumes_normal_flow(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    notifier = RecordingNotifier()
    for _ in range(3):
        run_monitor([cfg("Acme")], state, notifier, object())
    state.job_failures[adapter.jobs[0].identity]["quarantined_until"] = (
        datetime.now(UTC) - timedelta(seconds=1)
    ).isoformat()
    adapter.hydrate_failure = None

    report = run_monitor([cfg("Acme")], state, notifier, object())

    assert report.notifications == 1
    assert len(notifier.jobs) == 1
    assert state.has_seen(adapter.jobs[0])
    assert adapter.jobs[0].identity not in state.job_failures


def test_changed_job_source_error_resets_count_and_warns(monkeypatch):
    adapter = failing_job_adapter()
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    run_monitor([cfg("Acme")], state, RecordingNotifier(), object())
    original_message = "no JobPosting JSON-LD found on detail page"
    adapter.hydrate_failure = SourceError("unexpected_json", original_message)

    changed_code = run_monitor([cfg("Acme")], state, RecordingNotifier(), object())

    failure = state.job_failures[adapter.jobs[0].identity]
    assert failure["failure_count"] == 1
    assert failure["error_code"] == "unexpected_json"
    assert failure["error_message"] == original_message
    assert len(changed_code.warnings) == 1

    adapter.hydrate_failure = SourceError("unexpected_json", "detail JSON is invalid")
    changed_message = run_monitor([cfg("Acme")], state, RecordingNotifier(), object())

    failure = state.job_failures[adapter.jobs[0].identity]
    assert failure["failure_count"] == 1
    assert failure["error_code"] == "unexpected_json"
    assert failure["error_message"] == "detail JSON is invalid"
    assert len(changed_message.warnings) == 1


def test_notification_failure_is_not_quarantined_and_remains_retryable(monkeypatch):
    adapter = FakeAdapter([job("Acme", "2")])
    monkeypatch.setattr("job_monitor.runner.build_adapter", lambda config, http: adapter)
    state = seeded_state()
    notifier = RecordingNotifier(NotificationError("Discord unavailable"))

    first = run_monitor([cfg("Acme")], state, notifier, object())
    second = run_monitor([cfg("Acme")], state, notifier, object())

    assert first.warnings[0].code == "notification_failure"
    assert second.warnings[0].code == "notification_failure"
    assert adapter.hydrate_calls == 2
    assert state.job_failures == {}
    assert not state.has_seen(adapter.jobs[0])
