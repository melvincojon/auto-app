from job_monitor.cli import main
from job_monitor.models import HealthWarning
from job_monitor.runner import RunReport
from job_monitor.state import MonitorState


class FakeHttp:
    def close(self):
        return None


def test_run_prints_warning_details_before_summary(monkeypatch, tmp_path, capsys):
    warning = HealthWarning(
        "Meta",
        "schema_change",
        "job 1064155186370895: no JobPosting JSON-LD found on detail page",
    )
    monkeypatch.setattr("job_monitor.cli.HttpClient", FakeHttp)
    monkeypatch.setattr("job_monitor.cli.load_companies", lambda path: [object()])
    monkeypatch.setattr("job_monitor.cli.MonitorState.load", lambda path: MonitorState())
    monkeypatch.setattr(
        "job_monitor.cli.run_monitor",
        lambda companies, state, notifier, http: RunReport(warnings=[warning]),
    )

    result = main(["run", "--dry-run", "--state", str(tmp_path / "state.json")])

    lines = capsys.readouterr().out.splitlines()
    assert result == 2
    assert lines[0] == (
        "WARNING | Meta | schema_change | job 1064155186370895: "
        "no JobPosting JSON-LD found on detail page"
    )
    assert lines[1].endswith("warnings=1")
