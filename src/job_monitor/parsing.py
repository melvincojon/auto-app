from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .errors import SourceError


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    soup = BeautifulSoup(html.unescape(str(value)), "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def join_location(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return clean_text(value) or None
    if isinstance(value, dict):
        if value.get("name") or value.get("label"):
            return clean_text(value.get("name") or value.get("label")) or None
        address = value.get("address", value)
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            text = ", ".join(str(part) for part in parts if part)
            return clean_text(text) or None
        return None
    if isinstance(value, Iterable):
        parts = [join_location(item) for item in value]
        return "; ".join(dict.fromkeys(item for item in parts if item)) or None
    return clean_text(value) or None


def absolute(base: str, url: str | None) -> str:
    return urljoin(base, url or "")


def json_ld_job(html_text: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
            if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                for node in candidate["@graph"]:
                    if isinstance(node, dict) and node.get("@type") == "JobPosting":
                        return node
    raise SourceError("schema_change", "no JobPosting JSON-LD found on detail page")


def nested_find(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = nested_find(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = nested_find(child, key)
            if found is not None:
                return found
    return None
