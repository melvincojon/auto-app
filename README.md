# New-grad job monitor

A production-oriented monitor for full-time new-grad and plausibly early-career software engineering and quantitative-development roles. It polls every production-verified company in [`companies.yaml`](companies.yaml), sends each new relevant posting to Discord exactly once, and makes source failures visible without letting one broken provider stop the others.

Internships and co-ops are intentionally excluded. A relevant technical role with unclear seniority is sent as `POSSIBLE_NEW_GRAD_MATCH`; the system favors a reviewable false positive over a silent false negative.

## How it works

```text
companies.yaml -> reusable provider adapter -> normalized Job
                                               |
                     durable seen state <------+
                                               |
                   hydrate new posting -> classifier -> Discord
                              |                         |
                              +---- health warning <----+
```

All adapters normalize to one `Job` model with company, source, provider job ID, title, description, location, optional posting date, canonical job URL, and optional apply URL. Fields a provider does not publish remain null; crawl time is never presented as posting time.

The adapter registry currently implements:

- Greenhouse: Datadog, Robinhood, Block, Coinbase, Databricks, Airbnb
- Ashby: Snowflake, Notion, Ramp
- Amazon Jobs JSON
- Avature HTML: Bloomberg
- Eightfold PCS X with anonymous CSRF bootstrap: Microsoft
- Radancy list HTML plus JobPosting JSON-LD: Intuit
- Meta Relay plus JobPosting JSON-LD
- Eightfold Apply v2: Netflix
- Rippling Algolia plus ATS `__NEXT_DATA__`

Provider discovery and the verified contracts are documented in [`SOURCE_DISCOVERY.md`](SOURCE_DISCOVERY.md). That file and `companies.yaml` are authoritative. Do not infer tenant names or replace versioned identifiers speculatively.

## Classification

The classifier inspects both title and description. Explicit signals such as new graduate, university graduate, early career, entry level, campus, associate, junior, Engineer I, a compatible 2027 graduation/start window, and 0–2 years produce `NEW_GRAD_MATCH`.

A software/quant-development role without an affirmative seniority exclusion produces `POSSIBLE_NEW_GRAD_MATCH`. Both categories notify. Titles such as senior, staff, principal, lead, manager/director, Engineer II/III, and requirements for several years of professional experience are excluded. “Member of Technical Staff” is treated as a role family, not automatically as a staff-level title.

## Local setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install '.[test]'
pytest -q
job-monitor smoke
```

The smoke command makes low-volume, read-only requests to every configured production source, checks response structure, exercises a second page for paginated adapters, and hydrates one detail. It does not send notifications and never asserts changing inventory counts.

For a local dry run that prints notifications instead of contacting Discord:

```bash
job-monitor run --state .state/jobs.json --dry-run
```

The first successful run for each company seeds every current provider job ID and sends no backlog. Later runs hydrate newly observed postings, classify them, and notify once. Delete the local state file only when you intentionally want to reseed.

## GitHub Actions deployment

1. Create a public GitHub repository and push this project to its default branch.
2. In **Settings → Secrets and variables → Actions**, add the repository secret `DISCORD_WEBHOOK_URL` containing a Discord webhook URL.
3. Ensure Actions can use the workflow’s `contents: write` permission. Under **Settings → Actions → General → Workflow permissions**, choose read/write if your organization policy does not honor the workflow declaration automatically.
4. Run **New-grad job monitor** manually with mode `smoke`. Confirm all configured sources pass.
5. Run it once with mode `monitor`. That run safely seeds existing jobs and creates the dedicated `monitor-state` branch.

The schedule runs at minutes 7, 17, 27, 37, 47, and 57 from 5:00 AM through midnight-adjacent 11:57 PM in `America/New_York`, every day. The off-minute schedule reduces exposure to GitHub’s top-of-hour congestion. `workflow_dispatch` supports a normal poll, a notification-free source smoke test, and an isolated Discord notification test.

State is stored as a single JSON tree on the dedicated `monitor-state` branch using Git plumbing; the workflow never checks that branch out or adds state commits to the main branch. A concurrency group serializes polls. State is saved even when a later source reports a failure, so successfully delivered alerts do not repeat. Do not branch-protect `monitor-state` in a way that prevents `github-actions[bot]` from updating it.

GitHub may delay scheduled jobs during high load, and scheduled workflows in inactive public repositories may be disabled by GitHub. The monitor reports source health but cannot compensate for a workflow that GitHub has not started.

## Notifications and source health

Job notifications contain the match category, company, title, location, match reason, provider date when available, and the best application/job URL. Discord mentions are disabled.

To verify the Discord webhook without polling any company or touching monitor
state, open **Actions → New-grad job monitor → Run workflow** and select
`test-notification`. It sends exactly one message:

> ✅ New-grad job monitor notification test successful.

The same test can be dispatched from the GitHub CLI:

```bash
gh workflow run "New-grad job monitor" \
  --repo melvincojon/auto-app \
  -f mode=test-notification
```

This mode still runs the automated test suite first, but skips production
source smoke tests, source polling, state restore, and state persistence.

HTTP requests use a descriptive user agent, bounded exponential backoff for rate limits and transient 5xx responses, and strict structure/content validation. Each company is isolated. Non-200 responses, rate limiting, malformed content, schema drift, suspicious empty inventories, pagination failures, bootstrap/session failures, and versioned-contract failures become Discord health warnings and a failed Actions run after all other companies are checked.

Meta’s Relay `doc_id` and Rippling’s public Algolia application/key/index are deployment-versioned. If either contract fails, the adapter stops and tells you to repeat the maintenance procedure in `SOURCE_DISCOVERY.md`; it does not guess a replacement.

## Adding or maintaining a company

1. Verify the production source using the same evidence standard as `SOURCE_DISCOVERY.md`.
2. Prefer an existing reusable adapter. Add the company’s exact identifiers and pagination/detail contract to `companies.yaml`.
3. If a new provider is required, implement one adapter, register it in `src/job_monitor/adapters/registry.py`, and add representative list, detail, normalization, pagination, empty/schema-failure, and smoke behavior tests.
4. Run `pytest -q` and `job-monitor smoke` before merging.

New companies seed independently on their first successful poll, preventing accidental backlog alerts. A temporarily broken new source remains unseeded and will seed—not notify old inventory—when it first recovers.

## Uber limitation

Uber remains deliberately unsupported. As documented in `SOURCE_DISCOVERY.md`, its complete JSON pagination route and details are protected by a browser challenge, while server-rendered initial data contains only the first page. No reliable curl/Python production retrieval contract has been verified. The incomplete page-one fallback and guessed Oracle endpoints are not used. Add Uber only after a pagination-complete, production-safe source succeeds in the deployment runtime.

## Security

No secret belongs in `companies.yaml`, state, logs, or the repository. The Rippling Algolia value in configuration is the public search-only key shipped to browsers, not a private credential. The Discord webhook is read only from the `DISCORD_WEBHOOK_URL` GitHub Actions secret.
