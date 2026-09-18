"""Edge-case tests for the fetcher, using a local HTTP server to avoid the network."""

from __future__ import annotations

import asyncio
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from bhavkit.config import Config
from bhavkit.download import (
    STATUS_CACHED,
    STATUS_DOWNLOADED,
    STATUS_ERROR,
    STATUS_NON_TRADING,
    Fetcher,
)
from bhavkit.sources.base import BhavFile, Source

DAY = date(2024, 1, 3)
FILE_NAME = "cm03JAN2024bhav.csv.zip"
CONTENT = b"SYMBOL,CLOSE\nSBIN,632\n"


class ScriptSource(Source):
    name = "script"

    def __init__(self, base_url: str, routes: dict[date, str]):
        self.base_url = base_url
        self.routes = routes

    def resolve(self, product: str, day: date) -> BhavFile | None:
        assert product == "cm"
        return BhavFile(f"{self.base_url}/{self.routes[day]}")


class ScriptHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, bytes]] = {}
    hits = 0
    flaky_first_status: int | None = None

    def do_GET(self) -> None:  # noqa: N802
        ScriptHandler.hits += 1
        name = self.path.lstrip("/")
        if name in ScriptHandler.routes:
            code, body = ScriptHandler.routes[name]
        else:
            code, body = 404, b""
        if ScriptHandler.flaky_first_status is not None and ScriptHandler.hits == 1:
            code, body = ScriptHandler.flaky_first_status, b"retry"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args):  # noqa: ANN002 - silence request logging
        pass


@pytest.fixture
def server():
    ScriptHandler.routes = {FILE_NAME: (200, CONTENT)}
    ScriptHandler.hits = 0
    ScriptHandler.flaky_first_status = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ScriptHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def fetcher(server, tmp_path: Path) -> Fetcher:
    cfg = Config(
        db_path=tmp_path / "t.duckdb",
        data_dir=tmp_path / "data",
        retries=1,
        backoff_base=0.1,
        rate_limit_sleep=0.0,
        concurrency=1,
    )
    return Fetcher(cfg, ScriptSource(server, {DAY: FILE_NAME}))


def _cache(f: Fetcher) -> Path:
    return f.cache_path("cm", FILE_NAME, DAY)


def test_download_ok_and_caches(fetcher: Fetcher) -> None:
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out.status == STATUS_DOWNLOADED
    assert out.sha256 is not None
    assert _cache(fetcher).read_bytes() == CONTENT
    assert ScriptHandler.hits == 1

    out2 = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out2.status == STATUS_CACHED
    assert ScriptHandler.hits == 1


def test_zero_byte_stale_cache_redownloaded(fetcher: Fetcher) -> None:
    _cache(fetcher).parent.mkdir(parents=True, exist_ok=True)
    _cache(fetcher).write_bytes(b"")
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out.status == STATUS_DOWNLOADED
    assert _cache(fetcher).read_bytes() == CONTENT


def test_two_hundred_empty_body_errors(fetcher: Fetcher) -> None:
    ScriptHandler.routes[FILE_NAME] = (200, b"")
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out.status == STATUS_ERROR
    assert "empty" in (out.error or "")
    assert not _cache(fetcher).exists()
    assert not _cache(fetcher).with_suffix(".zip.partial").exists()


def test_404_is_non_trading_and_leaves_no_partials(fetcher: Fetcher) -> None:
    ScriptHandler.routes[FILE_NAME] = (404, b"")
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out.status == STATUS_NON_TRADING
    assert not _cache(fetcher).with_suffix(".zip.partial").exists()


def test_500_then_200_recovers(fetcher: Fetcher) -> None:
    fetcher.cfg.retries = 3
    ScriptHandler.routes[FILE_NAME] = (200, CONTENT)
    ScriptHandler.flaky_first_status = 500
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    ScriptHandler.flaky_first_status = None
    assert out.status == STATUS_DOWNLOADED
    assert _cache(fetcher).read_bytes() == CONTENT


def test_retryable_storm_errors_and_cleans_partial(fetcher: Fetcher) -> None:
    ScriptHandler.routes[FILE_NAME] = (503, b"")
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out.status == STATUS_ERROR
    assert not _cache(fetcher).with_suffix(".zip.partial").exists()


def test_non_retryable_status_errors_immediately(fetcher: Fetcher) -> None:
    ScriptHandler.routes[FILE_NAME] = (403, b"forbidden")
    out = asyncio.run(fetcher.fetch_one("cm", DAY, fetcher.source))
    assert out.status == STATUS_ERROR
    assert "403" in (out.error or "")
    assert ScriptHandler.hits == 1


def test_fetch_many_maps_days(fetcher: Fetcher) -> None:
    day_b = date(2024, 1, 4)
    fetcher.source.routes[day_b] = "missing.zip"
    ScriptHandler.routes["missing.zip"] = (404, b"")
    outcomes = asyncio.run(fetcher.fetch_many("cm", [DAY, day_b]))
    assert outcomes[DAY].status == STATUS_DOWNLOADED
    assert outcomes[day_b].status == STATUS_NON_TRADING