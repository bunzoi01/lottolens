"""A polite HTTP client: robots.txt, descriptive User-Agent, rate limit and a disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .. import paths

log = logging.getLogger("lottolens.fetch")

USER_AGENT = "LottoLens/0.1 (personal local statistical analysis tool; max 1 request per 2s)"
MIN_INTERVAL_S = 2.0


class FetchError(RuntimeError):
    pass


class FetchDisallowed(FetchError):
    pass


class PoliteClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        min_interval: float = MIN_INTERVAL_S,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.cache_dir = cache_dir or paths.cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request = 0.0
        self._lock = threading.Lock()
        self.network_requests = 0

    # ------------------------------------------------------------ internals
    def _throttled_get(self, url: str) -> httpx.Response:
        with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as exc:
                raise FetchError(f"network error fetching {url}: {exc}") from exc
            finally:
                self._last_request = time.monotonic()
                self.network_requests += 1
        log.info("GET %s -> %s", url, resp.status_code)
        return resp

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / f"{h}.html", self.cache_dir / f"{h}.json"

    def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = origin + "/robots.txt"
            text = self._cached(robots_url, ttl=24 * 3600)
            rp = RobotFileParser()
            rp.parse(text.splitlines() if text is not None else [])
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def _cached(self, url: str, ttl: float | None) -> str | None:
        """Fetch with cache; returns None for 404 (robots.txt absence is fine)."""
        body_path, meta_path = self._cache_paths(url)
        if body_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if ttl is None or time.time() - meta["fetched_at"] < ttl:
                return body_path.read_text(encoding="utf-8") if meta["status"] == 200 else None
        resp = self._throttled_get(url)
        if resp.status_code not in (200, 404):
            raise FetchError(f"{url} returned HTTP {resp.status_code}")
        body_path.write_text(resp.text if resp.status_code == 200 else "", encoding="utf-8")
        meta_path.write_text(json.dumps({"url": url, "status": resp.status_code, "fetched_at": time.time()}))
        return resp.text if resp.status_code == 200 else None

    # ------------------------------------------------------------ public
    def get_text(self, url: str, ttl: float | None = 3600) -> str:
        """GET a page, honouring robots.txt. ttl=None caches forever (immutable pages)."""
        if not self.robots_allows(url):
            raise FetchDisallowed(f"robots.txt disallows {url}; stopping")
        text = self._cached(url, ttl)
        if text is None:
            raise FetchError(f"{url} returned HTTP 404")
        return text

    def close(self) -> None:
        self._client.close()
