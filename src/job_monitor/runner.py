from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .adapters import build_adapter
from .classifier import classify
from .config import CompanyConfig
from .errors import NotificationError, SourceError
from .http import HttpClient
from .models import HealthWarning
from .notifier import Notifier
from .state import MonitorState


logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    checked_companies: int = 0
    seeded_companies: list[str] = field(default_factory=list)
    new_jobs: int = 0
    notifications: int = 0
    warnings: list[HealthWarning] = field(default_factory=list)
    health_notifications: list[HealthWarning] = field(default_factory=list)


def _warn(report: RunReport, warning: HealthWarning, *, notify: bool = True) -> None:
    """Avoid flooding a phone with the same source-level failure for many jobs."""
    if any(
        existing.company == warning.company and existing.code == warning.code
        for existing in report.warnings
    ):
        return
    report.warnings.append(warning)
    if notify:
        report.health_notifications.append(warning)


def _source_failed(
    report: RunReport, state: MonitorState, company: str, code: str, message: str
) -> None:
    warning = HealthWarning(company, code, message)
    _warn(report, warning, notify=False)
    count = state.record_source_failure(company, code, message)
    # Alert on transition to unhealthy, then at deliberately sparse escalation points.
    if count == 1 or count == 3 or count % 10 == 0:
        suffix = "" if count == 1 else f" (consecutive failures: {count})"
        report.health_notifications.append(
            HealthWarning(company, code, f"{message}{suffix}")
        )


def _process_unseen_jobs(
    report: RunReport,
    state: MonitorState,
    notifier: Notifier,
    company: CompanyConfig,
    adapter,
    jobs,
    attempted: set[str],
) -> None:
    for listing in jobs:
        if state.has_seen(listing) or listing.identity in attempted:
            continue
        if state.is_job_quarantined(listing):
            continue
        attempted.add(listing.identity)
        report.new_jobs += 1
        identity_job = listing
        try:
            job = adapter.hydrate(listing)
            adapter._validate_job(job, require_description=False)
            match = classify(job)
            state.clear_job_failure(identity_job)
            if match is not None:
                notifier.notify_job(job, match)
                report.notifications += 1
            state.mark_seen(identity_job)
        except NotificationError as exc:
            _warn(report, HealthWarning(company.company, "notification_failure", str(exc)))
        except SourceError as exc:
            if state.record_job_failure(identity_job, exc.code, str(exc)):
                _warn(
                    report,
                    HealthWarning(company.company, exc.code, f"job {listing.job_id}: {exc}"),
                )
        except Exception as exc:
            _warn(
                report,
                HealthWarning(
                    company.company,
                    "unexpected_failure",
                    f"job {listing.job_id}: {exc}",
                ),
            )


def run_monitor(
    companies: list[CompanyConfig],
    state: MonitorState,
    notifier: Notifier,
    http: HttpClient,
) -> RunReport:
    report = RunReport()
    for company in companies:
        attempted: set[str] = set()
        split_scan = False
        try:
            adapter = build_adapter(company, http)
            discover = getattr(adapter, "discover_jobs", None)
            discovery = discover() if discover is not None else None
            split_scan = discovery is not None
            if split_scan and state.is_seeded(company.company):
                _process_unseen_jobs(
                    report, state, notifier, company, adapter, discovery, attempted
                )

            jobs = adapter.list_jobs()
            report.checked_companies += 1
            if state.record_source_success(company.company, jobs):
                report.health_notifications.append(
                    HealthWarning(
                        company.company,
                        "source_recovered",
                        f"Source recovered; successful scan returned {len(jobs)} jobs.",
                    )
                )
            if not state.is_seeded(company.company):
                state.seed(company.company, jobs)
                report.seeded_companies.append(company.company)
                continue
            _process_unseen_jobs(report, state, notifier, company, adapter, jobs, attempted)
        except SourceError as exc:
            if exc.code == "reconciliation_inconsistency" and split_scan:
                report.checked_companies += 1
                count = state.record_reconciliation_failure(company.company, str(exc))
                logger.warning(
                    "%s reconciliation incomplete (consecutive=%s): %s",
                    company.company,
                    count,
                    exc,
                )
                if state.record_discovery_success(company.company):
                    report.health_notifications.append(
                        HealthWarning(
                            company.company,
                            "source_recovered",
                            "Source discovery recovered; reconciliation is still protected.",
                        )
                    )
                # Reconciliation drift becomes actionable only after it persists.
                if count == 3 or count % 12 == 0:
                    warning = HealthWarning(
                        company.company,
                        "reconciliation_inconsistency",
                        f"Full reconciliation remains incomplete: {exc} "
                        f"(consecutive scans: {count}). Discovery remains operational; "
                        "the authoritative snapshot was preserved.",
                    )
                    _warn(report, warning)
            else:
                _source_failed(report, state, company.company, exc.code, str(exc))
        except Exception as exc:
            _source_failed(report, state, company.company, "unexpected_failure", str(exc))

    for warning in report.health_notifications:
        try:
            notifier.notify_health(warning)
        except NotificationError as exc:
            print(f"HEALTH DELIVERY FAILURE | {warning.company} | {exc}")
    return report


def run_smoke(companies: list[CompanyConfig], http: HttpClient) -> RunReport:
    report = RunReport()
    for company in companies:
        try:
            build_adapter(company, http).smoke_test()
            report.checked_companies += 1
            print(f"PASS | {company.company} | {company.adapter}")
        except SourceError as exc:
            warning = HealthWarning(company.company, exc.code, str(exc))
            report.warnings.append(warning)
            print(f"FAIL | {company.company} | {exc.code} | {exc}")
        except Exception as exc:
            warning = HealthWarning(company.company, "unexpected_failure", str(exc))
            report.warnings.append(warning)
            print(f"FAIL | {company.company} | unexpected_failure | {exc}")
    return report
