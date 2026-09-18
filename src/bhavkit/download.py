from __future__ import annotations

import asyncio
import hashlib
import random
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from .config import Config
from .sources.base import Source
from .sources.nse import NSE_ALTERNATE_BASES
from .utils import get_logger

log = get_logger()

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
STATUS_DOWNLOADED = "downloaded"
STATUS_CACHED = "cached"
STATUS_NON_TRADING = "not_a_trading_day"
STATUS_ERROR = "error"


@dataclass
class DownloadOutcome:
    day: date
    status: str
    path: Path | None = None
    url: str | None = None
    sha256: str | None = None
    error: str | None = None
    duration_sec: float = 0.0


class RateLimiter:
    """Minimum-interval sleeper shared across concurrent downloads."""

    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            wait = self._last + self._min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = loop.time()


class Fetcher:
    def __init__(self, config: Config, source: Source):
        self.cfg = config
        self.source = source
        self.cache_root = config.data_dir / "cache"
        self._limiter = RateLimiter(config.rate_limit_sleep)

    def cache_path(self, product: str, file_name: str, day: date) -> Path:
        return (
            self.cache_root
            / product
            / str(day.year)
            / day.strftime("%m-%b").upper()
            / file_name
        )

    async def fetch_many(self, product: str, days: list[date]) -> dict[date, DownloadOutcome]:
        sem = asyncio.Semaphore(self.cfg.concurrency)

        async def _one(day: date) -> DownloadOutcome:
            async with sem:
                return await self.fetch_one(product, day, self.source)

        outcomes = await asyncio.gather(*[_one(d) for d in days])
        return dict(zip(days, outcomes, strict=False))

    async def fetch_one(self, product: str, day: date, source: Source) -> DownloadOutcome:
        started = time.monotonic()

        try:
            resolved = source.resolve(product, day)
        except ValueError as exc:
            return _error(day, f"source: {exc}", started)

        if resolved is None:
            return DownloadOutcome(day, STATUS_NON_TRADING, duration_sec=time.monotonic() - started)

        file_name = resolved.url.rsplit("/", 1)[-1]
        target = self.cache_path(product, file_name, day)

        if target.is_file() and target.stat().st_size > 0:
            return DownloadOutcome(
                day, STATUS_CACHED, path=target, url=resolved.url,
                sha256=_sha256(target), duration_sec=time.monotonic() - started,
            )

        if resolved.is_local:
            path = Path(resolved.url)
            if not path.is_file():
                return DownloadOutcome(day, STATUS_NON_TRADING, url=resolved.url,
                                       duration_sec=time.monotonic() - started)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path != target:
                try:
                    target.symlink_to(path.absolute())
                except OSError:
                    _copyfile(path, target)
            return DownloadOutcome(
                day, STATUS_CACHED, path=target, url=resolved.url,
                sha256=_sha256(target), duration_sec=time.monotonic() - started,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        last_error: str | None = None

        for attempt in range(self.cfg.retries + 1):
            await self._limiter.wait()
            try:
                async with httpx.AsyncClient(
                    timeout=self.cfg.timeout,
                    headers={"User-Agent": self.cfg.user_agent},
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(resolved.url)
                if resp.status_code == 404:
                    partial.unlink(missing_ok=True)
                    return DownloadOutcome(
                        day, STATUS_NON_TRADING, url=resolved.url,
                        duration_sec=time.monotonic() - started,
                    )
                if resp.status_code == 200:
                    if not resp.content:
                        raise httpx.TransportError("empty response body")
                    partial.write_bytes(resp.content)
                    partial.replace(target)
                    return DownloadOutcome(
                        day, STATUS_DOWNLOADED, path=target, url=resolved.url,
                        sha256=_sha256(target), duration_sec=time.monotonic() - started,
                    )
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRYABLE_STATUS:
                    partial.unlink(missing_ok=True)
                    return _error(day, last_error, started, url=resolved.url)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(self.cfg.backoff_base * (2**attempt) + random.uniform(0, 0.5))

        partial.unlink(missing_ok=True)
        return _error(day, last_error or "download failed", started, url=resolved.url)


def _error(day: date, message: str, started: float, url: str | None = None) -> DownloadOutcome:
    return DownloadOutcome(day, STATUS_ERROR, error=message, url=url,
                           duration_sec=time.monotonic() - started)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copyfile(src: Path, dst: Path) -> None:
    dst.write_bytes(src.read_bytes())


def base_urls_to_probe(cfg: Config) -> list[str]:
    """Candidate NSE base URLs to test with `bhavkit probe`."""
    return list(dict.fromkeys([cfg.nse_base_url, *NSE_ALTERNATE_BASES]))


async def probe(base_url: str, day: date = date(2024, 1, 3), timeout: float = 15.0) -> str:
    """Probe a base URL by requesting a known-good CM bhavcopy."""
    from .sources.nse import NSESource

    url = NSESource(base_url).resolve("cm", day).url  # type: ignore[union-attr]
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 bhavkit-probe"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
        return f"{resp.status_code}"
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: {exc}"