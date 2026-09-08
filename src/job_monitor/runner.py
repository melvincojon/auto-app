from __future__ import annotations

from dataclasses import dataclass, field

from .adapters import build_adapter
from .classifier import classify
from .config import CompanyConfig
from .errors import NotificationError, SourceError
from .http import HttpClient
from .models import HealthWarning
from .notifier import Notifier
from .state import MonitorState


@dataclass
class RunReport:
    checked_companies: int = 0
    seeded_companies: list[str] = field(default_factory=list)
    new_jobs: int = 0
    notifications: int = 0
    warnings: list[HealthWarning] = field(default_factory=list)


def _warn(report: RunReport, warning: HealthWarning) -> None:
    """Avoid flooding a phone with the same source-level failure for many jobs."""
    if any(
        existing.company == warning.company and existing.code == warning.code
        for existing in report.warnings
    ):
        return
    report.warnings.append(warning)


def run_monitor(
    companies: list[CompanyConfig],
    state: MonitorState,
    notifier: Notifier,
    http: HttpClient,
) -> RunReport:
    report = RunReport()
    for company in companies:
        try:
            adapter = build_adapter(company, http)
            jobs = adapter.list_jobs()
            report.checked_companies += 1
            if not state.is_seeded(company.company):
                state.seed(company.company, jobs)
                report.seeded_companies.append(company.company)
                continue

            for listing in jobs:
                if state.has_seen(listing):
                    continue
                report.new_jobs += 1
                identity_job = listing
                try:
                    job = adapter.hydrate(listing)
                    adapter._validate_job(job, require_description=False)
                    match = classify(job)
                    if match is not None:
                        notifier.notify_job(job, match)
                        report.notifications += 1
                    state.mark_seen(identity_job)
                except NotificationError as exc:
                    _warn(report,
                        HealthWarning(company.company, "notification_failure", str(exc))
                    )
                except SourceError as exc:
                    _warn(report,
                        HealthWarning(company.company, exc.code, f"job {listing.job_id}: {exc}")
                    )
                except Exception as exc:
                    _warn(report,
                        HealthWarning(company.company, "unexpected_failure", f"job {listing.job_id}: {exc}")
                    )
        except SourceError as exc:
            _warn(report, HealthWarning(company.company, exc.code, str(exc)))
        except Exception as exc:
            _warn(report,
                HealthWarning(company.company, "unexpected_failure", str(exc))
            )

    for warning in report.warnings:
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
