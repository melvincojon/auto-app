from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import load_companies
from .http import HttpClient
from .notifier import ConsoleNotifier, DiscordNotifier
from .runner import run_monitor, run_smoke
from .state import MonitorState


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="job-monitor")
    result.add_argument("--config", default="companies.yaml")
    subparsers = result.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="poll sources and notify about new matches")
    run.add_argument("--state", default=".state/jobs.json")
    run.add_argument("--dry-run", action="store_true", help="print instead of using Discord")
    subparsers.add_parser("smoke", help="verify every configured production source")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    companies = load_companies(args.config)
    http = HttpClient()
    try:
        if args.command == "smoke":
            report = run_smoke(companies, http)
            print(f"Smoke: {report.checked_companies} passed, {len(report.warnings)} failed")
            return 2 if report.warnings else 0

        state_path = Path(args.state)
        state = MonitorState.load(state_path)
        webhook = os.environ.get("DISCORD_WEBHOOK_URL")
        if args.dry_run:
            notifier = ConsoleNotifier()
        elif webhook:
            notifier = DiscordNotifier(webhook, http)
        else:
            raise SystemExit("DISCORD_WEBHOOK_URL is required unless --dry-run is used")
        report = run_monitor(companies, state, notifier, http)
        state.save(state_path)
        print(
            f"Run: {report.checked_companies}/{len(companies)} sources, "
            f"seeded={len(report.seeded_companies)}, new={report.new_jobs}, "
            f"notified={report.notifications}, warnings={len(report.warnings)}"
        )
        return 2 if report.warnings else 0
    finally:
        http.close()


if __name__ == "__main__":
    raise SystemExit(main())
