"""SQLite access layer: connection, init, upserts, and fuzzy model resolution."""
from __future__ import annotations

import difflib
import json
import re
import sqlite3
from pathlib import Path

from common import DB_PATH

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def connect() -> sqlite3.Connection:
    # 30 s busy timeout + WAL so the MCP server / web UI can read while a pipeline
    # writes, instead of hitting "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    conn.executescript(SCHEMA.read_text())
    conn.commit()
    if own:
        conn.close()


# ---------------------------------------------------------------- instruments

def upsert_instrument(conn: sqlite3.Connection, row: dict) -> int:
    specs = row.get("specs") or {}
    cur = conn.execute(
        """
        INSERT INTO instruments (manufacturer, model, model_aliases, category, principle,
                                 specs_json, datasheet_url, status, epa_designation, seed_confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (manufacturer, model) DO UPDATE SET
          model_aliases = excluded.model_aliases,
          category = excluded.category,
          principle = excluded.principle,
          specs_json = CASE WHEN instruments.specs_provenance = 'datasheet'
                            THEN instruments.specs_json ELSE excluded.specs_json END,
          datasheet_url = COALESCE(excluded.datasheet_url, instruments.datasheet_url),
          status = excluded.status,
          epa_designation = COALESCE(excluded.epa_designation, instruments.epa_designation),
          seed_confidence = excluded.seed_confidence
        """,
        (
            row["manufacturer"],
            row["model"],
            json.dumps(row.get("model_aliases") or [], ensure_ascii=False),
            row.get("category"),
            row.get("principle"),
            json.dumps(specs, ensure_ascii=False),
            row.get("datasheet_url"),
            row.get("status", "unknown"),
            row.get("epa_designation"),
            row.get("confidence", 1.0),
        ),
    )
    # On the ON CONFLICT DO UPDATE arm, SQLite leaves lastrowid at 0, so always
    # resolve the real row id by the unique key rather than trusting lastrowid.
    rid = conn.execute(
        "SELECT id FROM instruments WHERE manufacturer = ? AND model = ?",
        (row["manufacturer"], row["model"]),
    ).fetchone()
    return rid["id"]


def all_instruments(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM instruments ORDER BY manufacturer, model").fetchall()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def resolve_instrument(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    """Fuzzy model resolution over model + aliases + manufacturer (MVP substitute
    for the embeddings table in proposal §4). Returns scored candidates."""
    q = _norm(query)
    if not q:
        return []
    q_tokens = set(q.split())
    scored: list[tuple[float, sqlite3.Row, str]] = []
    for row in all_instruments(conn):
        names = [row["model"]] + json.loads(row["model_aliases"])
        combos = names + [f"{row['manufacturer']} {n}" for n in names]
        best, best_name = 0.0, row["model"]
        for name in combos:
            n = _norm(name)
            score = difflib.SequenceMatcher(None, q, n).ratio()
            n_tokens = set(n.split())
            if n_tokens and (q_tokens & n_tokens):
                overlap = len(q_tokens & n_tokens) / len(q_tokens | n_tokens)
                score = max(score, 0.35 + 0.65 * overlap)
            if _norm(row["model"]) and _norm(row["model"]) in q:
                score = max(score, 0.9)
            if score > best:
                best, best_name = score, name
        if best >= 0.35:
            scored.append((best, row, best_name))
    scored.sort(key=lambda t: -t[0])
    out = []
    for score, row, name in scored[:limit]:
        d = dict(row)
        d["match_score"] = round(score, 3)
        d["matched_name"] = name
        out.append(d)
    return out


# --------------------------------------------------------------------- papers

def _find_paper(conn: sqlite3.Connection, p: dict) -> int | None:
    """Locate an existing paper by any stable identifier, in priority order.
    Keying on all four ids (not just doi/pmcid) makes upsert idempotent for
    pmid-only Europe PMC records and doi-less OpenAlex works."""
    doi = (p.get("doi") or "").lower() or None
    for col, val in (("doi", doi), ("pmcid", p.get("pmcid")),
                     ("pmid", p.get("pmid")), ("openalex_id", p.get("openalex_id"))):
        if val:
            row = conn.execute(f"SELECT id FROM papers WHERE {col} = ?", (val,)).fetchone()
            if row:
                return row["id"]
    return None


def upsert_paper(conn: sqlite3.Connection, p: dict) -> int:
    """Idempotent paper insert/merge keyed on doi/pmcid/pmid/openalex_id.

    An identifier is only written onto the found row if no *other* row already
    owns it, so the doi UNIQUE constraint and the pmcid partial-unique index can
    never be violated when the same logical paper was first seen under two
    different ids (e.g. an EPMC pmcid-only row and an OpenAlex doi-only row).
    """
    doi = (p.get("doi") or "").lower() or None
    fields = json.dumps(p.get("fields") or [], ensure_ascii=False)
    affs = json.dumps(p.get("affiliations") or [], ensure_ascii=False)
    pid = _find_paper(conn, p)

    def _safe_id(col: str, val, self_id: int) -> object:
        """Return val only if setting it won't collide with a different row."""
        if not val:
            return None
        other = conn.execute(
            f"SELECT id FROM papers WHERE {col} = ? AND id != ?", (val, self_id)
        ).fetchone()
        return None if other else val

    if pid is not None:
        conn.execute(
            """
            UPDATE papers SET
              doi = COALESCE(?, doi), pmid = COALESCE(?, pmid), pmcid = COALESCE(?, pmcid),
              openalex_id = COALESCE(?, openalex_id), title = COALESCE(?, title),
              year = COALESCE(?, year), venue = COALESCE(?, venue),
              fields = CASE WHEN ? != '[]' THEN ? ELSE fields END,
              affiliations = CASE WHEN ? != '[]' THEN ? ELSE affiliations END,
              citation_count = COALESCE(?, citation_count),
              oa_fulltext_source = COALESCE(?, oa_fulltext_source)
            WHERE id = ?
            """,
            (
                _safe_id("doi", doi, pid), p.get("pmid"), _safe_id("pmcid", p.get("pmcid"), pid),
                p.get("openalex_id"), p.get("title"), p.get("year"), p.get("venue"),
                fields, fields, affs, affs,
                p.get("citation_count"), p.get("oa_fulltext_source"), pid,
            ),
        )
        return pid
    cur = conn.execute(
        """
        INSERT INTO papers (doi, pmid, pmcid, openalex_id, title, year, venue, fields,
                            affiliations, citation_count, oa_fulltext_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doi, p.get("pmid"), p.get("pmcid"),
            p.get("openalex_id"), p.get("title"), p.get("year"), p.get("venue"),
            fields, affs, p.get("citation_count"), p.get("oa_fulltext_source"),
        ),
    )
    return cur.lastrowid


def upsert_link(conn: sqlite3.Connection, instrument_id: int, paper_id: int, *,
                evidence: str | None, alias: str | None, section: str | None,
                source: str, confidence: float) -> None:
    conn.execute(
        """
        INSERT INTO instrument_paper (instrument_id, paper_id, evidence_snippet, matched_alias,
                                      section, source, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (instrument_id, paper_id) DO UPDATE SET
          evidence_snippet = COALESCE(excluded.evidence_snippet, instrument_paper.evidence_snippet),
          matched_alias = COALESCE(excluded.matched_alias, instrument_paper.matched_alias),
          section = COALESCE(excluded.section, instrument_paper.section),
          confidence = MAX(excluded.confidence, instrument_paper.confidence)
        """,
        (instrument_id, paper_id, evidence, alias, section, source, confidence),
    )
