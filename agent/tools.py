"""The six agent tools (proposal §7), implemented as pure functions over the DB.

Every function returns JSON-serialisable dicts so the same implementations back
the SDK chat agent, the MCP server, and the direct CLI.
"""
from __future__ import annotations

import json
import re

import db as dbm


def _inst_card(conn, inst: dict, min_confidence: float = 0.7) -> dict:
    n_papers = conn.execute(
        "SELECT COUNT(*) c FROM instrument_paper WHERE instrument_id = ? AND confidence >= ?",
        (inst["id"], min_confidence),
    ).fetchone()["c"]
    return {
        "manufacturer": inst["manufacturer"],
        "model": inst["model"],
        "aliases": json.loads(inst["model_aliases"]),
        "category": inst["category"],
        "principle": inst["principle"],
        "specs": json.loads(inst["specs_json"]),
        "specs_provenance": inst["specs_provenance"],
        "datasheet_url": inst["datasheet_url"],
        "status": inst["status"],
        "epa_designation": inst["epa_designation"],
        "linked_papers": n_papers,
    }


def spec_lookup(model: str) -> dict:
    """Fuzzy model lookup -> spec card + datasheet link."""
    conn = dbm.connect()
    matches = dbm.resolve_instrument(conn, model, limit=4)
    if not matches:
        conn.close()
        return {"found": False, "query": model,
                "message": "No instrument matched. The index currently covers gas analyzers (NOx/SO2/O3/CO/NH3)."}
    best = matches[0]
    out = {
        "found": True,
        "query": model,
        "match_score": best["match_score"],
        "fuzzy": best["match_score"] < 0.85,
        "instrument": _inst_card(conn, best),
        "other_candidates": [
            {"manufacturer": m["manufacturer"], "model": m["model"], "score": m["match_score"]}
            for m in matches[1:]
        ],
    }
    conn.close()
    return out


def compare_models(models: list[str] | None = None, category: str | None = None) -> dict:
    """Aligned spec matrix for a list of models or a whole category."""
    conn = dbm.connect()
    rows: list[dict] = []
    unmatched: list[str] = []
    if models:
        for m in models:
            found = dbm.resolve_instrument(conn, m, limit=1)
            if found:
                rows.append(found[0])
            else:
                unmatched.append(m)
    elif category:
        cat = category.lower().replace("analyser", "analyzer")
        rows = [dict(r) for r in dbm.all_instruments(conn)
                if cat in (r["category"] or "").lower()]
    if not rows:
        conn.close()
        return {"matrix": [], "unmatched": unmatched,
                "message": "Nothing to compare — give model names or a category like 'NOx analyzer'."}
    matrix = [_inst_card(conn, r) for r in rows]
    conn.close()
    return {"matrix": matrix, "unmatched": unmatched, "n": len(matrix)}


def paper_search(model: str, limit: int = 15, min_confidence: float = 0.7) -> dict:
    """Papers that used a model: title, year, venue, fields, evidence snippet."""
    conn = dbm.connect()
    matches = dbm.resolve_instrument(conn, model, limit=1)
    if not matches:
        conn.close()
        return {"found": False, "query": model, "papers": []}
    inst = matches[0]
    rows = conn.execute(
        """
        SELECT p.doi, p.title, p.year, p.venue, p.fields, p.affiliations, p.citation_count,
               ip.evidence_snippet, ip.section, ip.source, ip.confidence, ip.matched_alias
        FROM instrument_paper ip JOIN papers p ON p.id = ip.paper_id
        WHERE ip.instrument_id = ? AND ip.confidence >= ?
        ORDER BY ip.confidence DESC, p.year DESC
        LIMIT ?
        """,
        (inst["id"], min_confidence, limit),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) c FROM instrument_paper WHERE instrument_id = ? AND confidence >= ?",
        (inst["id"], min_confidence),
    ).fetchone()["c"]
    conn.close()
    papers = []
    for r in rows:
        papers.append({
            "doi": r["doi"], "title": r["title"], "year": r["year"], "venue": r["venue"],
            "fields": json.loads(r["fields"]), "affiliations": json.loads(r["affiliations"])[:3],
            "citations": r["citation_count"], "evidence_snippet": r["evidence_snippet"],
            "evidence_section": r["section"], "link_source": r["source"],
            "link_confidence": r["confidence"],
        })
    return {
        "found": True,
        "instrument": f"{inst['manufacturer']} {inst['model']}",
        "match_score": inst["match_score"],
        "total_linked_papers": total,
        "shown": len(papers),
        "min_confidence": min_confidence,
        "coverage_note": "Open-access-only coverage: counts understate true usage (paywalled Methods sections are not indexed).",
        "papers": papers,
    }


def usage_profile(model: str, min_confidence: float = 0.7) -> dict:
    """Aggregated usage stats: papers/year, top fields, institutions, venues."""
    conn = dbm.connect()
    matches = dbm.resolve_instrument(conn, model, limit=1)
    if not matches:
        conn.close()
        return {"found": False, "query": model}
    inst = matches[0]
    rows = conn.execute(
        """
        SELECT p.year, p.venue, p.fields, p.affiliations
        FROM instrument_paper ip JOIN papers p ON p.id = ip.paper_id
        WHERE ip.instrument_id = ? AND ip.confidence >= ?
        """,
        (inst["id"], min_confidence),
    ).fetchall()
    conn.close()
    by_year: dict[str, int] = {}
    fields: dict[str, int] = {}
    insts: dict[str, int] = {}
    venues: dict[str, int] = {}
    for r in rows:
        if r["year"]:
            by_year[str(r["year"])] = by_year.get(str(r["year"]), 0) + 1
        for f in json.loads(r["fields"]):
            fields[f] = fields.get(f, 0) + 1
        for a in json.loads(r["affiliations"])[:5]:
            insts[a] = insts.get(a, 0) + 1
        if r["venue"]:
            venues[r["venue"]] = venues.get(r["venue"], 0) + 1

    def top(d: dict, n: int) -> list[dict]:
        return [{"name": k, "papers": v} for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]]

    return {
        "found": True,
        "instrument": f"{inst['manufacturer']} {inst['model']}",
        "total_linked_papers": len(rows),
        "papers_per_year": dict(sorted(by_year.items())),
        "top_fields": top(fields, 5),
        "top_institutions": top(insts, 8),
        "top_venues": top(venues, 8),
        "coverage_note": "Open-access-only coverage; treat as a lower bound on real usage.",
    }


def market_search(model: str) -> dict:
    """Current second-hand listing snapshots + price range."""
    conn = dbm.connect()
    matches = dbm.resolve_instrument(conn, model, limit=1)
    if not matches:
        conn.close()
        return {"found": False, "query": model, "listings": []}
    inst = matches[0]
    rows = conn.execute(
        """SELECT source, title, price, currency, condition, listing_url, scraped_at
           FROM listings WHERE instrument_id = ? ORDER BY scraped_at DESC, price ASC LIMIT 25""",
        (inst["id"],),
    ).fetchall()
    conn.close()
    listings = [dict(r) for r in rows]
    prices = [l["price"] for l in listings if l["price"]]
    return {
        "found": True,
        "instrument": f"{inst['manufacturer']} {inst['model']}",
        "n_listings": len(listings),
        "price_range_usd": {"min": min(prices), "max": max(prices)} if prices else None,
        "listings": listings,
        "note": ("Snapshot data (not real-time). Sources whose robots.txt disallows scraping are "
                 "not covered; listings can also be added via `labscope market-import`."),
    }


# require at least one digit; allow a trailing/leading dot only around digits
_LOD_RE = re.compile(r"(\d+(?:\.\d+)?|\.\d+)\s*(ppt|ppb|ppm)", re.IGNORECASE)


def _lod_ppb(specs: dict) -> float | None:
    lod = specs.get("lod")
    if not lod:
        return None
    m = _LOD_RE.search(str(lod))
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    return val * {"ppt": 0.001, "ppb": 1.0, "ppm": 1000.0}[unit]


def recommend(category: str, max_lod_ppb: float | None = None,
              require_current: bool = False, top_n: int = 5) -> dict:
    """Ranked model recommendations for a category, justified by specs + usage evidence."""
    conn = dbm.connect()
    cat = category.lower().replace("analyser", "analyzer")
    cands = [dict(r) for r in dbm.all_instruments(conn) if cat in (r["category"] or "").lower()]
    if not cands:
        conn.close()
        return {"category": category, "recommendations": [],
                "message": "No instruments in this category. Known categories: NOx/NO2/SO2/O3/CO/NH3 analyzer, calibrator."}
    scored = []
    for inst in cands:
        specs = json.loads(inst["specs_json"])
        lod = _lod_ppb(specs)
        usage = conn.execute(
            "SELECT COUNT(*) c FROM instrument_paper WHERE instrument_id = ? AND confidence >= 0.7",
            (inst["id"],),
        ).fetchone()["c"]
        methods_n = conn.execute(
            """SELECT COUNT(*) c FROM instrument_paper
               WHERE instrument_id = ? AND confidence >= 0.7 AND section = 'methods'""",
            (inst["id"],),
        ).fetchone()["c"]
        recent = conn.execute(
            """SELECT COUNT(*) c FROM instrument_paper ip JOIN papers p ON p.id = ip.paper_id
               WHERE ip.instrument_id = ? AND ip.confidence >= 0.7 AND p.year >= 2019""",
            (inst["id"],),
        ).fetchone()["c"]
        if require_current and inst["status"] != "current":
            continue
        if max_lod_ppb is not None and lod is not None and lod > max_lod_ppb:
            continue
        import math
        score = (math.log1p(usage) * 2.0 + math.log1p(recent) * 1.5
                 + (1.0 if inst["status"] == "current" else 0.0)
                 + (0.5 if inst["epa_designation"] else 0.0))
        example = conn.execute(
            """SELECT p.title, p.year, ip.evidence_snippet
               FROM instrument_paper ip JOIN papers p ON p.id = ip.paper_id
               WHERE ip.instrument_id = ? AND ip.confidence >= 0.7 AND ip.evidence_snippet IS NOT NULL
               ORDER BY ip.confidence DESC, p.year DESC LIMIT 1""",
            (inst["id"],),
        ).fetchone()
        scored.append({
            "manufacturer": inst["manufacturer"],
            "model": inst["model"],
            "status": inst["status"],
            "principle": inst["principle"],
            "lod": specs.get("lod"),
            "ranges": specs.get("ranges"),
            "epa_designation": inst["epa_designation"],
            "linked_papers": usage,
            "methods_confirmed_papers": methods_n,
            "papers_since_2019": recent,
            "example_evidence": dict(example) if example else None,
            "score": round(score, 2),
        })
    conn.close()
    scored.sort(key=lambda d: -d["score"])
    return {
        "category": category,
        "filters": {"max_lod_ppb": max_lod_ppb, "require_current": require_current},
        "ranking_basis": "literature usage volume (total + recent), current availability, compliance designation",
        "coverage_note": "Usage counts are OA-only lower bounds.",
        "recommendations": scored[:top_n],
    }


TOOL_FUNCS = {
    "spec_lookup": spec_lookup,
    "compare_models": compare_models,
    "paper_search": paper_search,
    "usage_profile": usage_profile,
    "market_search": market_search,
    "recommend": recommend,
}
