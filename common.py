"""Shared utilities: paths, HTTP client with robust TLS, query logging, rate limiting."""
from __future__ import annotations

import json
import ssl
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = ROOT / "db" / "labscope.sqlite3"
SYSTEM_CERTS = ROOT / ".certs" / "system.pem"

for d in (DATA_DIR, CACHE_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

USER_AGENT = "LabScope/0.1 (research-instrument index; non-commercial)"


def _ssl_context() -> ssl.SSLContext | str | bool:
    """Prefer the OS trust store (handles TLS-intercepting proxies), then the
    exported keychain bundle, then certifi defaults."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    if SYSTEM_CERTS.exists():
        return ssl.create_default_context(cafile=str(SYSTEM_CERTS))
    return True  # httpx default (certifi)


_client: httpx.Client | None = None
_client_lock = threading.Lock()


def http_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                verify=_ssl_context(),
                timeout=httpx.Timeout(30.0, connect=15.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        return _client


_QUERY_LOG = LOG_DIR / "queries.jsonl"
_log_lock = threading.Lock()


def log_query(source: str, url: str, params: dict | None, n_results: int | None, note: str = "") -> None:
    """Every external API query is logged for recall debugging (proposal §11)."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "url": url,
        "params": params,
        "n_results": n_results,
        "note": note,
    }
    with _log_lock:
        with _QUERY_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class RateLimiter:
    """Minimal interval-based limiter, one per API source."""

    def __init__(self, min_interval_s: float):
        self.min_interval = min_interval_s
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = self.min_interval - (now - self._last)
            if delta > 0:
                time.sleep(delta)
            self._last = time.monotonic()


def get_json(url: str, params: dict | None, source: str, limiter: RateLimiter | None = None,
             retries: int = 3) -> dict | None:
    """GET returning parsed JSON with logging + retry. Returns None on hard failure."""
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        try:
            r = http_client().get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            return data
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            log_query(source, url, params, None, note=f"error attempt {attempt + 1}: {e}")
            time.sleep(1.5 * (attempt + 1))
    return None
