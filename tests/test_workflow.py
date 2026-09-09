from pathlib import Path

import yaml


def test_workflow_is_dispatch_only_and_documents_qstash_schedule():
    workflow = Path(".github/workflows/job-monitor.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "\n  schedule:" not in workflow
    assert "cron:" not in workflow
    assert "timezone:" not in workflow
    for mode in ("monitor", "smoke", "test-notification"):
        assert f"          - {mode}" in workflow
    assert "secrets.DISCORD_WEBHOOK_URL" in workflow
    assert "contents: write" in workflow
    assert "cancel-in-progress: false" in workflow

    readme = Path("README.md").read_text()
    assert "Production scheduling is handled by QStash" in readme
    assert "`workflow_dispatch` with `mode=monitor`" in readme
    assert "every 10 minutes from 5:07 AM through 11:57 PM" in readme
    assert "`America/New_York`" in readme


def test_monitor_mode_restores_polls_and_persists_durable_state():
    workflow = Path(".github/workflows/job-monitor.yml").read_text()
    payload = yaml.safe_load(workflow)
    steps = {step.get("name"): step for step in payload["jobs"]["monitor"]["steps"]}

    assert steps["Restore durable state"]["if"] == "inputs.mode == 'monitor'"
    assert steps["Restore durable state"]["run"] == "bash scripts/load_state.sh .state/jobs.json"
    assert steps["Poll and notify"]["if"] == "inputs.mode == 'monitor'"
    assert steps["Poll and notify"]["run"] == "job-monitor run --state .state/jobs.json"
    assert steps["Persist durable state"]["if"] == "always() && steps.poll.outcome != 'skipped'"
    assert steps["Persist durable state"]["run"] == "bash scripts/save_state.sh .state/jobs.json"


def test_notification_mode_has_an_isolated_single_send_path():
    workflow = Path(".github/workflows/job-monitor.yml").read_text()
    assert "- test-notification" in workflow
    assert "inputs.mode == 'test-notification'" in workflow
    assert workflow.count("run: job-monitor test-notification") == 1
    assert "inputs.mode == 'monitor'" in workflow

    payload = yaml.safe_load(workflow)
    steps = {step.get("name"): step for step in payload["jobs"]["monitor"]["steps"]}
    assert steps["Test Discord notification"]["if"] == (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'test-notification'"
    )
    assert steps["Test Discord notification"]["run"] == "job-monitor test-notification"
    for name in ("Production source smoke tests", "Restore durable state", "Poll and notify", "Persist durable state"):
        assert "test-notification" not in steps[name]["if"]


def test_state_scripts_do_not_embed_credentials():
    text = Path("scripts/load_state.sh").read_text() + Path("scripts/save_state.sh").read_text()
    assert "DISCORD_WEBHOOK" not in text
    assert "https://" not in text
