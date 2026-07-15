"""Marketplace pipeline (proposal §5.3) — snapshot scraping, robots-aware.

Design constraints from the proposal's risk table: weekly snapshots, strict
robots.txt compliance, and the whole feature is optional. Many marketplaces
(notably eBay) disallow scraping their search pages via robots.txt — in that
case the source is skipped automatically and the manual CSV import path
(`labscope market-import`) is the supported way to add listings.
"""
from __future__ import annotations

import csv
import re
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

from common import RateLimiter, http_client, log_query
import db as dbm

scrape_limiter = RateLimiter(3.0)
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def robots_allows(url: str) -> bool:
    origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    rp = _robots_cache.get(origin)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = http_client().get(origin + "/robots.txt")
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse(["User-agent: *", "Disallow: /"])  # unreachable -> be conservative
        _robots_cache[origin] = rp
    return rp.can_fetch("*", url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PRICE_RE = re.compile(r"(?:US\s?)?\$\s?([\d,]+(?:\.\d{2})?)")


def scrape_labx(inst: dict) -> list[dict]:
    """Best-effort LabX search snapshot. Skips cleanly if robots.txt disallows
    or the page structure has drifted (risk table: 'treat as optional')."""
    q = f"{inst['manufacturer'].split()[0]} {inst['model']}"
    url = f"https://www.labx.com/search?q={quote_plus(q)}"
    if not robots_allows(url):
        log_query("labx", url, None, None, note="robots.txt disallows; skipped")
        return []
    try:
        scrape_limiter.wait()
        r = http_client().get(url)
        log_query("labx", url, None, 1 if r.status_code == 200 else 0)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        log_query("labx", url, None, None, note=f"error: {e}")
        return []
    listings = []
    # tolerant extraction: anchor blocks that mention the model and carry a price
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.{0,400}?)</a>', html, re.S | re.I):
        href, body = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        if inst["model"].lower() not in body.lower():
            continue
        pm = PRICE_RE.search(body)
        listings.append({
            "source": "labx",
            "title": re.sub(r"\s+", " ", body).strip()[:200],
            "price": float(pm.group(1).replace(",", "")) if pm else None,
            "currency": "USD" if pm else None,
            "condition": None,
            "listing_url": href if href.startswith("http") else f"https://www.labx.com{href}",
        })
    return listings[:20]


def run(models: list[str] | None = None) -> dict:
    conn = dbm.connect()
    instruments = [dict(r) for r in dbm.all_instruments(conn)]
    if models:
        wanted = {m.strip().lower() for m in models}
        instruments = [i for i in instruments if i["model"].lower() in wanted]
    ts, n = _now(), 0
    for inst in instruments:
        # scrape (slow, network) OUTSIDE any open write transaction, then commit
        # per instrument so we never hold the write lock across rate-limited HTTP
        rows = scrape_labx(inst)
        for listing in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO listings
                   (instrument_id, source, title, price, currency, condition, listing_url, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (inst["id"], listing["source"], listing["title"], listing["price"],
                 listing["currency"], listing["condition"], listing["listing_url"], ts),
            )
            n += cur.rowcount  # count only rows actually inserted, not IGNOREd
        conn.commit()
    conn.close()
    return {"snapshots": n, "scraped_at": ts}


_PRICE_CLEAN = re.compile(r"[^\d.]")


def _parse_price(raw: str | None) -> float | None:
    """Tolerant price parse: '$1,200', ' 950 ', '1200.00' -> float; junk -> None."""
    if not raw:
        return None
    cleaned = _PRICE_CLEAN.sub("", str(raw))
    if not cleaned or cleaned == ".":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def import_csv(path: str) -> int:
    """Manual listing import: CSV with columns
    model,source,title,price,currency,condition,listing_url"""
    conn = dbm.connect()
    ts, n = _now(), 0
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "model" not in reader.fieldnames:
                print("  ! CSV must have a 'model' column")
                return 0
            for i, row in enumerate(reader, 2):  # header is line 1
                model = (row.get("model") or "").strip()
                if not model or model.startswith("#"):
                    continue
                matches = dbm.resolve_instrument(conn, model, limit=1)
                if not matches:
                    print(f"  ! line {i}: no instrument match for {model!r}; skipped")
                    continue
                cur = conn.execute(
                    """INSERT OR IGNORE INTO listings
                       (instrument_id, source, title, price, currency, condition, listing_url, scraped_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (matches[0]["id"], row.get("source") or "manual", row.get("title"),
                     _parse_price(row.get("price")),
                     row.get("currency") or "USD", row.get("condition"),
                     row.get("listing_url"), ts),
                )
                n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    print(f"imported {n} listings")
    return n
