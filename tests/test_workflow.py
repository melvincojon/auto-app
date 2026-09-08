from pathlib import Path


def test_workflow_has_schedule_manual_dispatch_and_secret():
    workflow = Path(".github/workflows/job-monitor.yml").read_text()
    assert 'cron: "7-57/10 5-23 * * *"' in workflow
    assert 'timezone: "America/New_York"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "secrets.DISCORD_WEBHOOK_URL" in workflow
    assert "contents: write" in workflow
    assert "cancel-in-progress: false" in workflow


def test_state_scripts_do_not_embed_credentials():
    text = Path("scripts/load_state.sh").read_text() + Path("scripts/save_state.sh").read_text()
    assert "DISCORD_WEBHOOK" not in text
    assert "https://" not in text
