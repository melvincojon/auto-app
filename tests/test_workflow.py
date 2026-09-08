from pathlib import Path

import yaml


def test_workflow_has_schedule_manual_dispatch_and_secret():
    workflow = Path(".github/workflows/job-monitor.yml").read_text()
    assert 'cron: "7-57/10 5-23 * * *"' in workflow
    assert 'timezone: "America/New_York"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "secrets.DISCORD_WEBHOOK_URL" in workflow
    assert "contents: write" in workflow
    assert "cancel-in-progress: false" in workflow


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
