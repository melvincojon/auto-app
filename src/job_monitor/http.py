from __future__ import annotations

import random
import time
from typing import Any

import httpx

from .errors import SourceError


class HttpClient:
    """Small HTTP wrapper with bounded retries and explicit content validation."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        retries: int = 3,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=15.0),
            follow_redirects=True,
            headers={
                "User-Agent": "new-grad-job-monitor/1.0 (+https://github.com/)",
                "Accept-Language": "en-US,en;q=0.8",
            },
        )
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == self.retries:
                    raise SourceError("network_failure", str(exc)) from exc
            else:
                if response.status_code == 429:
                    if attempt == self.retries:
                        raise SourceError("rate_limited", f"429 from {url}")
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else None
                elif 500 <= response.status_code < 600:
                    if attempt == self.retries:
                        raise SourceError(
                            "upstream_failure", f"HTTP {response.status_code} from {url}"
                        )
                    delay = None
                elif response.status_code < 200 or response.status_code >= 300:
                    raise SourceError(
                        "non_200_response", f"HTTP {response.status_code} from {url}"
                    )
                else:
                    return response
            delay = delay if "delay" in locals() and delay is not None else self.backoff_seconds * (2**attempt)
            time.sleep(delay + random.uniform(0, min(0.5, delay / 4)))
        raise SourceError("network_failure", str(last_error or "request failed"))

    @staticmethod
    def json(response: httpx.Response, *, allow_html_content_type: bool = False) -> Any:
        content_type = response.headers.get("content-type", "").casefold()
        if "json" not in content_type and not allow_html_content_type:
            raise SourceError(
                "unexpected_content_type",
                f"expected JSON, received {content_type or 'no content type'}",
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError("unexpected_json", "response body is not valid JSON") from exc

    @staticmethod
    def html(response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "").casefold()
        if "html" not in content_type:
            raise SourceError(
                "unexpected_content_type",
                f"expected HTML, received {content_type or 'no content type'}",
            )
        if "<" not in response.text:
            raise SourceError("unexpected_html", "response does not look like HTML")
        return response.text
