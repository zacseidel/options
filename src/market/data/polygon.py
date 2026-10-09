"""Async Massive (formerly Polygon.io) REST client: bounded concurrency, retries, pagination.

The paid plan has no call quota, so there is no throttle — only a concurrency cap and
retry-with-backoff for 429/5xx. Entitlement failures raise `NotEntitled` so callers
can tell "my plan doesn't include this" apart from transient errors.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from market.config import api_key as configured_api_key, config


class PolygonError(RuntimeError):
    def __init__(self, status: int, message: str, url: str):
        super().__init__(f"{status} {message} ({url})")
        self.status = status
        self.message = message


class NotEntitled(PolygonError):
    """The plan does not include this dataset or timeframe."""


_ENTITLEMENT_HINTS = ("not entitled", "not authorized", "doesn't include", "upgrade your plan")


def _entitlement_problem(status: int, body: Any) -> bool:
    flagged = isinstance(body, dict) and body.get("status") in ("NOT_AUTHORIZED", "NOT_ENTITLED")
    if status < 400 and not flagged:
        return False
    text = str(body.get("message", "") if isinstance(body, dict) else body).lower()
    return status in (401, 403) or flagged or any(hint in text for hint in _ENTITLEMENT_HINTS)


class Polygon:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        max_concurrency: int | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ):
        cfg = config()["polygon"]
        self.api_key = api_key or configured_api_key()
        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self.max_retries = max_retries if max_retries is not None else cfg["max_retries"]
        self._limit = asyncio.Semaphore(max_concurrency or cfg["max_concurrency"])
        self._client = httpx.AsyncClient(timeout=timeout or cfg["timeout_seconds"])
        self.calls = 0

    async def __aenter__(self) -> "Polygon":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict:
        base = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        # Merge, don't replace: next_url cursors carry their own query string, and httpx's
        # `params=` would silently drop it (page 2 then falls back to the default 10 rows).
        url = httpx.URL(base).copy_merge_params({**(params or {}), "apiKey": self.api_key})
        for attempt in range(self.max_retries + 1):
            async with self._limit:
                self.calls += 1
                try:
                    resp = await self._client.get(url)
                except httpx.TransportError as exc:
                    if attempt == self.max_retries:
                        raise PolygonError(0, f"transport error: {exc}", base) from exc
                    await self._backoff(attempt)
                    continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise PolygonError(resp.status_code, resp.text[:200], base)
                await self._backoff(attempt)
                continue
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            if resp.status_code >= 400 or _entitlement_problem(resp.status_code, body):
                error = NotEntitled if _entitlement_problem(resp.status_code, body) else PolygonError
                message = body.get("message") or body.get("error") if isinstance(body, dict) else body
                raise error(resp.status_code, str(message)[:300], base)
            return body
        raise AssertionError("unreachable")

    async def paginate(
        self, path: str, params: dict[str, Any] | None = None, max_pages: int | None = None
    ) -> list[dict]:
        """Follow `next_url` cursors and return every `results` row."""
        rows: list[dict] = []
        body = await self.get(path, params)
        pages = 1
        rows.extend(body.get("results") or [])
        seen: set[str] = set()
        while body.get("next_url") and (max_pages is None or pages < max_pages):
            if body["next_url"] in seen:   # defensive: never loop on a repeated cursor
                break
            seen.add(body["next_url"])
            body = await self.get(body["next_url"])
            rows.extend(body.get("results") or [])
            pages += 1
        return rows

    @staticmethod
    async def _backoff(attempt: int) -> None:
        await asyncio.sleep(min(30.0, 0.5 * 2**attempt) + random.random() * 0.25)
