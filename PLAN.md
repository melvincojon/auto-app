# Production new-grad monitor plan

This plan tracks the requirements in the pasted goal. `SOURCE_DISCOVERY.md` and
`companies.yaml` remain the authoritative source contracts.

## Implementation

- [x] Load all 16 production-verified companies from `companies.yaml`.
- [x] Implement a common `Job` model and a reusable adapter registry.
- [x] Implement Greenhouse, Ashby, Amazon Jobs, Avature, Eightfold PCS X,
  Radancy/JSON-LD, Meta Relay/JSON-LD, Eightfold Apply v2, and
  Rippling Algolia/Next Data adapters.
- [x] Normalize provider IDs, title, description, location, optional posting
  time, canonical job URL, and optional apply URL without synthesizing missing
  provider data.
- [x] Inspect title and hydrated description, classify explicit early-career
  roles as `NEW_GRAD_MATCH`, and classify ambiguous relevant roles as
  `POSSIBLE_NEW_GRAD_MATCH`.
- [x] Exclude explicit internships/co-ops and affirmative senior/experience
  signals, including provider title variants such as `Engineer - II`.
- [x] Persist company + provider-ID identities, deduplicate Rippling by
  `jobId`, seed each company independently, and alert later jobs once.
- [x] Implement a notifier abstraction with concise Discord job and source
  health messages; read the webhook only from `DISCORD_WEBHOOK_URL`.
- [x] Isolate company failures and detect non-200 responses, rate limits,
  malformed content, schema changes, suspicious empty inventories, pagination
  failures, bootstrap failures, and configuration drift.
- [x] Fail closed for Meta and Rippling deployment-versioned contracts.
- [x] Add exponential retry/backoff with jitter and bounded HTTP timeouts.
- [x] Add GitHub Actions scheduling every ten minutes at off-minutes from
  05:07 through 23:57 America/New_York, plus manual monitor and smoke modes.
- [x] Persist Actions state on a dedicated `monitor-state` branch and serialize
  runs with a concurrency group.
- [x] Document architecture, setup, extension, local operation, notifications,
  health behavior, state, deployment, security, and the unsupported Uber source.

## Verification

- [x] Automated tests cover every reusable adapter, normalization, pagination,
  classifier positives/ambiguity/exclusions, state and identity, first-run
  seeding, once-only subsequent notification, notification rendering, adapter
  configuration coverage, workflow requirements, and failure isolation.
- [x] Fresh-state full production poll: 16/16 companies seeded, 17,435 observed
  provider identities, zero backlog notifications, zero warnings.
- [x] Subsequent full production poll: 16/16 companies checked with zero source
  warnings; newly observed listings were evaluated against persisted state.
- [x] Bounded production smoke command: 16 passed, zero failed, with no
  notification path invoked.
- [x] Secret-pattern scan: no Discord webhook or GitHub credential committed.
- [x] Python package installation, CLI entry point, shell syntax, Python
  compilation, YAML parsing, and GitHub Actions validation with actionlint
  1.7.12 verified locally.
- [x] Publish the `main` branch to the public repository
  `https://github.com/melvincojon/auto-app`.
- [x] Run the GitHub-hosted manual smoke workflow. Run `34280948799` passed
  installation, all automated tests, and all 16 production source checks using
  `actions/checkout@v7` and `actions/setup-python@v7`.
- [ ] Add the `DISCORD_WEBHOOK_URL` repository secret and perform the first
  hosted monitor run. This final activation requires the user's Discord
  webhook value; no Actions secret is currently configured.

## Maintenance rule

Do not redo source discovery unless an existing production source fails. For a
Meta persisted-query or Rippling Algolia configuration failure, follow the
specific maintenance procedure in `SOURCE_DISCOVERY.md`, update the versioned
configuration only after direct verification, and rerun the production smoke
test. Keep Uber unsupported until a pagination-complete production-safe source
works in the deployment runtime.
