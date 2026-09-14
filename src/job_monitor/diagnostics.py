from __future__ import annotations

import json
from typing import Any

import httpx
from bs4 import BeautifulSoup


def response_facts(response: httpx.Response) -> dict[str, Any]:
    """Safe response metadata suitable for source-health logs."""
    return {
        "status": response.status_code,
        "final_url": str(response.url),
        "content_type": response.headers.get("content-type", ""),
        "response_length": len(response.content),
    }


def html_structure(html: str) -> dict[str, Any]:
    """Describe page shape without logging tokens, cookies, or page text."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True)[:120] if soup.title else None
    lower = html.casefold()
    return {
        "title": title,
        "tags": {
            tag: len(soup.find_all(tag))
            for tag in ("a", "form", "meta", "script", "iframe")
        },
        "markers": {
            "avature": "avature.portal" in lower,
            "challenge": any(
                marker in lower
                for marker in ("captcha", "challenge-platform", "access denied", "perimeterx")
            ),
        },
    }


def format_diagnostics(response: httpx.Response, *, structure: dict[str, Any] | None = None) -> str:
    facts = response_facts(response)
    if structure is not None:
        facts["structure"] = structure
    return json.dumps(facts, sort_keys=True, separators=(",", ":"))
