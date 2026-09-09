from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import NotificationError
from .http import HttpClient
from .models import HealthWarning, Job, Match


NOTIFICATION_TEST_MESSAGE = "✅ New-grad job monitor notification test successful."


def _format_posted_at(posted_at: str) -> str:
    raw_value = str(posted_at)

    try:
        posted_date = date.fromisoformat(raw_value)
    except (TypeError, ValueError):
        pass
    else:
        return f"{posted_date.strftime('%b')} {posted_date.day}, {posted_date.year}"

    try:
        posted_datetime = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if posted_datetime.tzinfo is not None:
            posted_datetime = posted_datetime.astimezone(ZoneInfo("America/New_York"))

        hour = posted_datetime.strftime("%I").lstrip("0")
        timezone_label = " ET" if posted_datetime.tzinfo is not None else ""
        return (
            f"{posted_datetime.strftime('%b')} {posted_datetime.day}, {posted_datetime.year} "
            f"at {hour}:{posted_datetime.strftime('%M %p')}{timezone_label}"
        )
    except (OSError, OverflowError, TypeError, ValueError, ZoneInfoNotFoundError):
        return raw_value[:100]


def discord_test_payload() -> dict:
    return {
        "content": NOTIFICATION_TEST_MESSAGE,
        "username": "New-grad job monitor",
        "allowed_mentions": {"parse": []},
    }


def discord_job_payload(job: Job, match: Match) -> dict:
    url = job.apply_url or job.job_url
    fields = [
        {"name": "Company", "value": job.company, "inline": True},
        {"name": "Location", "value": job.location or "Not provided", "inline": True},
        {"name": "Why", "value": match.reason[:1024], "inline": False},
    ]
    if job.posted_at:
        fields.insert(
            2,
            {
                "name": "Posted",
                "value": _format_posted_at(job.posted_at),
                "inline": True,
            },
        )
    return {
        "username": "New-grad job monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": job.title[:256],
                "url": url,
                "description": f"**{match.category.value}**",
                "color": 0x2ECC71 if match.category.value == "NEW_GRAD_MATCH" else 0xF1C40F,
                "fields": fields,
            }
        ],
    }


def discord_health_payload(warning: HealthWarning) -> dict:
    return {
        "username": "New-grad job monitor",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"Source health warning: {warning.company}"[:256],
                "description": warning.message[:4096],
                "color": 0xE74C3C,
                "fields": [{"name": "Code", "value": warning.code[:1024], "inline": True}],
            }
        ],
    }


class Notifier:
    def notify_test(self) -> None:
        raise NotImplementedError

    def notify_job(self, job: Job, match: Match) -> None:
        raise NotImplementedError

    def notify_health(self, warning: HealthWarning) -> None:
        raise NotImplementedError


@dataclass
class DiscordNotifier(Notifier):
    webhook_url: str
    http: HttpClient

    def _send(self, payload: dict) -> None:
        try:
            self.http.request("POST", self.webhook_url, json=payload)
        except Exception as exc:
            raise NotificationError(f"Discord webhook delivery failed: {exc}") from exc

    def notify_job(self, job: Job, match: Match) -> None:
        self._send(discord_job_payload(job, match))

    def notify_health(self, warning: HealthWarning) -> None:
        self._send(discord_health_payload(warning))

    def notify_test(self) -> None:
        self._send(discord_test_payload())


class ConsoleNotifier(Notifier):
    def notify_test(self) -> None:
        print(NOTIFICATION_TEST_MESSAGE)

    def notify_job(self, job: Job, match: Match) -> None:
        print(f"{match.category.value} | {job.company} | {job.title} | {job.location or '-'} | {job.apply_url or job.job_url}")

    def notify_health(self, warning: HealthWarning) -> None:
        print(f"HEALTH WARNING | {warning.company} | {warning.code} | {warning.message}")
