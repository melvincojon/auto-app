# Careers Source Discovery

Validated on **2026-09-08** using direct HTTP requests (`curl`), not browser
rendering alone. A source is present in `companies.yaml` only when its exact
tenant/board identifier was confirmed, its list response and at least one job
could be parsed, and the fields required by the future monitor were available.

Classification:

- **A** — simple anonymous structured API
- **B** — structured HTTP source requiring custom session or response handling
- **C** — production-usable source discovered through network/bundle inspection
- **D** — no reliable production retrieval mechanism verified

## Inventory summary

| Company | ATS/platform | Production source | Class | Status |
|---|---|---|---|---|
| Amazon | Amazon Jobs custom | `GET https://www.amazon.jobs/en/search.json` | B | Configured |
| Bloomberg | Avature | Avature list/detail HTML | C | Configured |
| Microsoft | Eightfold PCS X | Session-backed `/api/pcsx/search` and `/api/pcsx/position_details` JSON | B | Configured |
| Datadog | Greenhouse | Greenhouse Job Board API, board `datadog` | A | Configured |
| Snowflake | Ashby (behind Phenom) | Ashby public posting API, board `snowflake` | A | Configured |
| Robinhood | Greenhouse | Greenhouse Job Board API, board `robinhood` | A | Configured |
| Block | Greenhouse | Greenhouse Job Board API, board `block` | A | Configured |
| Coinbase | Greenhouse | Greenhouse Job Board API, board `coinbase` | A | Configured |
| Intuit | Radancy/TalentBrew + Avature | Search HTML plus detail-page JobPosting JSON-LD | C | Configured |
| Meta | Meta Relay GraphQL | Relay list query plus detail-page JobPosting JSON-LD | C | Configured |
| Uber | Happydance/Next.js + Oracle HCM | Exact JSON route found, but non-browser HTTP is challenged | D | **Blocked; excluded** |
| Databricks | Greenhouse | Greenhouse Job Board API, board `databricks` | A | Configured |
| Airbnb | Greenhouse | Greenhouse Job Board API, board `airbnb` | A | Configured |
| Netflix | Eightfold legacy SmartApply | Anonymous `/api/apply/v2/jobs` list/detail JSON | B | Configured |
| Notion | Ashby | Ashby public posting API, board `notion` | A | Configured |
| Ramp | Ashby | Ashby public posting API, board `ramp` | A | Configured |
| Rippling | Rippling Recruiting + Algolia | Public Algolia list plus ATS detail `__NEXT_DATA__` | B | Configured |

## Newly resolved and extended investigations

### Microsoft — resolved

- Official site: [Microsoft Careers](https://apply.careers.microsoft.com/careers)
- Platform: Eightfold PCS X; the live page exposes group/domain
  `microsoft.com`.
- List: `GET https://apply.careers.microsoft.com/api/pcsx/search` with
  `domain=microsoft.com`, `start={offset}`, and `num=10`.
- Detail: `GET https://apply.careers.microsoft.com/api/pcsx/position_details`
  with `position_id={id}`, `domain=microsoft.com`, and `hl=en`.
- Session requirement: first GET the careers page, retain its anonymous
  cookies, parse `<meta name="_csrf" content="...">`, then send that value as
  `x-csrf-token` with the careers-page `Referer`. Calling the API without this
  bootstrap returned `429`; the same request with the anonymous session returned
  `200 application/json`.
- Pagination: offset `start=0` and `start=10` each returned 10 records and
  distinct first IDs. The live count was 2,142 during the final check.
- List fields: `id`, `displayJobId`, `atsJobId`, `name`, `locations`,
  `standardizedLocations`, `postedTs`, `creationTs`, `department`, and
  `positionUrl`.
- Detail fields: the same identifiers and locations plus full HTML
  `jobDescription`, `postedTs`, `publicUrl`, and application action state.
  `publicUrl` is the stable public job/application landing. The inspected
  anonymous apply action required login, so no separate direct-submit URL is
  asserted.

This is production-usable as a bounded, session-aware adapter. A fresh session
should be bootstrapped for each polling run (or safely reused only while valid).

### Meta — resolved with a versioned-query caveat

- Official site: [Meta job search](https://www.metacareers.com/jobsearch/)
- Platform: Meta custom React/Relay GraphQL.
- List: `POST https://www.metacareers.com/api/graphql/` using the current
  `CareersJobSearchResultsV2DataQuery` persisted query. The verified current
  `doc_id` is `27129360303422352`.
- Bootstrap: GET the job-search page, parse the `LSD` module's `token`, and send
  it in both the `lsd` form field and `x-fb-lsd` header. Also send
  `fb_api_caller_class=RelayModern`, the friendly query name, the configured
  variables, and the job-search `Referer`.
- Response quirk: the successful body is JSON, but Meta returns the media type
  `text/html; charset=utf-8`. The adapter must validate and decode the JSON body
  explicitly rather than requiring `application/json`.
- Pagination: the GraphQL response returned all 895 current jobs in one
  `all_jobs` array; the visible 10-job pages are client-side slices, so there is
  no server pagination step for this query.
- List fields: `id`, `title`, `locations`, `teams`, and `sub_teams`.
- Detail: `GET https://www.metacareers.com/profile/job_details/{id}/` returned
  `200 text/html` and a schema.org `JobPosting` JSON-LD object with title, full
  description, responsibilities, qualifications, `datePosted`, `validThrough`,
  employment type, and structured locations. The canonical detail page is the
  public direct-apply landing.

The persisted `doc_id` is versioned and may change with a Meta deployment. A
production adapter must treat a query-contract failure as a maintenance alert:
reload the current careers bundles, locate
`CareersJobSearchResultsV2DataQuery_candidate_portalRelayOperation`, update the
ID, and rerun the smoke test. It must not silently guess another query ID.

### Netflix — resolved

- Official site: [Netflix roles](https://explore.jobs.netflix.net/careers)
- Platform: Eightfold legacy SmartApply. The live page exposes domain
  `netflix.com`.
- The earlier PCS X lead was disproved: `/api/pcsx/search` returned
  `403 {"message":"PCSX is not enabled for this user."}`.
- The current SmartApply bundle identifies the real list route as
  `GET /api/apply/v2/jobs?domain=netflix.com&start={offset}&num=10` and the
  detail route as `GET /api/apply/v2/jobs/{id}?domain=netflix.com`.
- Both routes returned anonymous `200 application/json`; cookies and CSRF were
  not required.
- Pagination: `start=0` and `start=10` returned 10 records with distinct first
  IDs. The count was 496–497 while jobs were changing during the checks.
- List fields: `id`, `ats_job_id`, `display_job_id`, `name`, `locations`,
  `t_create`, `t_update`, department/business unit, and
  `canonicalPositionUrl`.
- Detail adds full HTML `job_description`, work/location fields, and the same
  canonical public job/application landing. No separate direct-submit URL is
  exposed anonymously.

### Ramp — added and verified

- Official site: [Ramp Careers](https://ramp.com/careers/)
- Platform: Ashby. The live careers payload contains Ashby URLs under the exact
  board slug `ramp`; the slug was not inferred from the company name.
- Source: `GET https://api.ashbyhq.com/posting-api/job-board/ramp`.
- Pagination: none; all published jobs are returned in one `jobs` array.
- The final response was `200 application/json` with 141 jobs. A parsed job had
  `id`, `title`, `descriptionHtml`, `location`, `publishedAt`, `jobUrl`,
  and `applyUrl` populated.

### Rippling — added and verified

- Official site: [Rippling open roles](https://www.rippling.com/careers/open-roles)
- Platform: Rippling Recruiting for details/applications; the official careers
  page uses Algolia for the searchable list.
- The current production bundle exposes Algolia app ID `6FNAX3TBEF`, public
  search-only key `416caa4690f002ff6fe4a2097623640b`, and index
  `careers_en-US_production`. These exact values were observed, not guessed.
- List: `POST https://6FNAX3TBEF-dsn.algolia.net/1/indexes/*/queries` with the
  standard public Algolia headers and a request for that exact index.
- Pagination: zero-based `page` plus `hitsPerPage`. Pages 0 and 1 returned
  `200 application/json`, correct page metadata, and distinct `objectID` values.
- Algolia creates one record per job/location. Records must be deduplicated by
  `jobId`, not `objectID`. List fields include `jobId`, name, department,
  remote flag, location names/objects, and the official ATS `url`.
- Detail: the returned `https://ats.rippling.com/rippling/jobs/{uuid}` page
  returned `200 text/html`. Its `__NEXT_DATA__` path
  `props.pageProps.apiData.jobPost` contains UUID, name, full company/role HTML
  descriptions, work locations, department, employment type, `createdOn`, and
  canonical URL. `createdOn` is an ATS record-creation timestamp; it is retained
  but not mislabeled as an independently verified publication date. The same ATS
  page hosts the application flow.

The Algolia key is intentionally public and search-only, but it and the index
name can rotate with a site deployment. A 401/403 or missing-index response must
trigger bundle re-discovery and a new smoke test, never credential guessing.

### Uber — still blocked and excluded

- Official site: [Uber Jobs](https://jobs.uber.com/en/jobs/)
- Platform: custom Happydance/Next.js front end; applications ultimately use
  the verified Oracle Fusion HCM tenant
  `iaziqy.fa.ocs.oraclecloud.com/.../sites/UberCareers`.
- Bundle inspection found the exact list route:
  `GET https://jobs.uber.com/api/jobs/search/`. Its response contract is
  `jobs`, `totalPages`, `totalJobs`, `page`, and `pageSize`; query keys
  include one-based `page` and `pagesize` plus filters.
- Direct curl to that exact route returned `403 text/html` with
  `cf-mitigated: challenge`. Bootstrapping cookies from the official careers
  page, sending a realistic user agent, `Accept: application/json`, and the
  correct `Referer` still returned the same challenge.
- The public jobs page itself returns `200 text/html` and embeds 10 structured
  `initialData` jobs (ID/reference, title, full description, locations,
  `DisplayDate`, teams, work type, and canonical URL). It is not a complete
  fallback: requesting `?page=2&pagesize=10` over curl still embedded
  `page: 1` data because the browser is expected to fetch page 2 from the
  challenged JSON route.
- A direct curl to a current job detail was also challenged. The Oracle tenant
  proves the apply platform but does not prove a public Oracle REST contract.

**Exact remaining blocker:** there is no pagination-complete list and detail
mechanism that succeeds under the required curl/Python runtime. Resolving Uber
requires either an approved production browser/challenge-capable retrieval
strategy or observation and successful direct testing of an official upstream
API used behind Uber's Next.js proxy. Do not guess an Oracle
`recruitingCEJobRequisitions` endpoint or enable the incomplete RSC fallback.

## Previously verified sources

### Greenhouse: Datadog, Robinhood, Block, Coinbase, Databricks, Airbnb

Each official site independently exposed its exact board token. The common
anonymous source is:

`GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true`

The board-wide response is not paginated. Every tested board returned a nonempty
`jobs` array whose first record had populated `id`, `title`, `location.name`,
full HTML `content`, `first_published`, `updated_at`, and `absolute_url`.

### Ashby: Snowflake and Notion

The official sites independently exposed the exact `snowflake` and `notion`
board slugs. Their anonymous Ashby endpoints return all current postings without
pagination. Both returned nonempty `jobs` arrays with populated `id`, `title`,
`descriptionHtml`, location, `publishedAt`, `jobUrl`, and `applyUrl`.

### Amazon

`GET https://www.amazon.jobs/en/search.json` supports `offset` and
`result_limit`. Offsets 0 and 1 with a one-record page returned distinct IDs.
After a full-production pagination run exposed Amazon's 10,000-result boundary,
`result_limit=100` was verified and is used to keep each poll bounded to roughly
100 requests. `sort=recent` was also verified in the endpoint's echoed request
contract as descending `CREATED_DATE`, ensuring the capped inventory contains
the newest postings rather than relevance-ordered results.
Parsed fields include the stable record `id`, title, description and
qualification content, location, `posted_date`, `job_path`, and the explicit
`url_next_step` application URL.

### Bloomberg

`GET https://bloomberg.avature.net/en_US/careers/SearchJobs/?jobRecordsPerPage=12&jobOffset={offset}`
returns ordinary HTML. Offsets 0 and 12 each produced 12 distinct job IDs and
detail links. A detail page provided the portal ID, title, location, full
description, ATS reference information, and an explicit Avature apply/login URL
such as `/careers/Login?jobId={id}`. No posting date was present in the inspected
list or detail, so the monitor must leave that optional field null.

### Intuit

`GET https://jobs.intuit.com/search-jobs?p={page}` returns 15 jobs per one-based
page. Pages 1 and 2 produced distinct job IDs. Returned detail pages contain
schema.org `JobPosting` JSON-LD with identifier, title, full description,
location, `datePosted`, and canonical URL, plus an explicit Avature
`JobApplication?pipelineId={ats_id}` apply URL.

## Runtime smoke-test results

All 16 entries now present in `companies.yaml` passed on 2026-09-08. No existing
configured source had to be removed. “Fields” below means at least one job had
the monitor identity, title, description, location, date/timestamp where the
provider supplies one, and a canonical job/apply URL.

| Company | HTTP/content check | Structure and parse check | Pagination check | Result |
|---|---|---|---|---|
| Amazon | 200, `application/json` | `jobs[]`; required fields populated | Offset 0/1 IDs differ | Pass |
| Bloomberg | 200, `text/html` list and detail | 12 job links; detail description/location/apply; date unavailable | Offsets 0/12 IDs differ | Pass |
| Microsoft | 200, `application/json` list and detail after bootstrap | `data.positions[]` plus populated detail `data` | Starts 0/10 IDs differ | Pass |
| Datadog | 200, `application/json` | 444 jobs; required fields populated | Complete board response | Pass |
| Snowflake | 200, `application/json` | 370 jobs; required fields populated | Complete board response | Pass |
| Robinhood | 200, `application/json` | 128 jobs; required fields populated | Complete board response | Pass |
| Block | 200, `application/json` | 204 jobs; required fields populated | Complete board response | Pass |
| Coinbase | 200, `application/json` | 192 jobs; required fields populated | Complete board response | Pass |
| Intuit | 200, `text/html` list and detail | 15 links; valid JobPosting JSON-LD and apply URL | Pages 1/2 IDs differ | Pass |
| Meta | 200; JSON body labeled `text/html`, detail `text/html` | 895 list jobs; detail JobPosting JSON-LD has description/date/location | Complete `all_jobs` array | Pass |
| Databricks | 200, `application/json` | 867 jobs; required fields populated | Complete board response | Pass |
| Airbnb | 200, `application/json` | 168 jobs; required fields populated | Complete board response | Pass |
| Netflix | 200, `application/json` list and detail | 10-job batch; full detail and canonical URL | Starts 0/10 IDs differ | Pass |
| Notion | 200, `application/json` | 132 jobs; required fields populated | Complete board response | Pass |
| Ramp | 200, `application/json` | 141 jobs; required fields populated | Complete board response | Pass |
| Rippling | 200, `application/json` list; 200 `text/html` detail | 682 location records; detail `jobPost` has required fields | Pages 0/1 objectIDs differ | Pass |

Counts are observations, not invariants; jobs changed during the test window.
Adapters should assert a nonempty correctly shaped response, not a fixed count.

## Production cautions

These were low-volume smoke tests, not load tests. Poll conservatively with a
descriptive user agent, bounded concurrency, jitter, and exponential backoff for
429/5xx. Microsoft must refresh its anonymous CSRF session. Meta's persisted
query ID and Rippling's public Algolia configuration are deployment-versioned
and need a fail-closed maintenance path. Optional dates must remain null when a
provider does not publish one; do not synthesize them from crawl time.
