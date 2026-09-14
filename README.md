# New-grad job monitor

A small Python service that checks company career sites for new graduate and early-career software jobs and sends matching listings to Discord.

It currently monitors 16 companies through their public job-board APIs or career pages. Internships, senior roles, and unrelated positions are filtered out.

## How it works

On each run, the monitor:

1. Fetches the current jobs from every configured company.
2. Compares provider job IDs with durable seen state.
3. Loads and classifies unseen listings.
4. Sends relevant jobs to Discord.
5. Saves state so the same job is not announced twice.

Each company is checked independently, so one broken source does not stop the others. Incomplete scans never replace the last known complete inventory or make jobs appear to have been removed.

Microsoft and Netflix use a two-stage Eightfold scan. A small discovery window is processed immediately for fast notifications, followed by a complete reconciliation scan for safe inventory tracking.

## Run locally

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install '.[test]'
pytest -q
```

Run a source smoke test:

```bash
job-monitor smoke
```

Run the monitor without sending Discord messages:

```bash
job-monitor run --state .state/jobs.json --dry-run
```

The first successful run seeds the current inventory without announcing old jobs.

## Configuration and deployment

Companies and provider settings live in [`companies.yaml`](companies.yaml). Verified provider contracts and maintenance notes are documented in [`SOURCE_DISCOVERY.md`](SOURCE_DISCOVERY.md).

Production runs through the GitHub Actions workflow in [`.github/workflows/job-monitor.yml`](.github/workflows/job-monitor.yml), which expects a `DISCORD_WEBHOOK_URL` repository secret. Production scheduling is handled by QStash: it calls `workflow_dispatch` with `mode=monitor` every 10 minutes from 5:07 AM through 11:57 PM in `America/New_York`.

This is a personal monitoring tool, not an official integration with any listed company.
