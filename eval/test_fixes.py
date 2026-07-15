"""Regression tests for the bugs found in code review. Run: python eval/test_fixes.py

Uses a throwaway in-memory-style temp DB so it never touches the real index.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402

# redirect the DB to a temp file BEFORE importing db
_tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
common.DB_PATH = Path(_tmp.name)

import db as dbm  # noqa: E402
from agent import tools  # noqa: E402
from pipelines import marketplace, literature  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond):
    results.append((name, cond))
    print(f"  [{PASS if cond else FAIL}] {name}")


def main():
    dbm.DB_PATH = common.DB_PATH
    conn = dbm.connect()
    dbm.init_db(conn)

    # --- upsert_instrument returns a valid id on the UPDATE path (lastrowid bug)
    row = {"manufacturer": "Test", "model": "X1", "model_aliases": ["Test X1"],
           "category": "NOx analyzer", "principle": "chemiluminescence",
           "specs": {"lod": "0.4 ppb"}, "status": "current", "confidence": 0.9}
    id1 = dbm.upsert_instrument(conn, row)
    id2 = dbm.upsert_instrument(conn, row)  # UPDATE path
    conn.commit()
    check("upsert_instrument returns real id on update path", id1 == id2 and id1 > 0)

    # --- upsert_paper dedupes doi-less/openalex-only papers across runs
    p = {"openalex_id": "https://openalex.org/W999", "title": "Doi-less work", "year": 2024}
    pa = dbm.upsert_paper(conn, p)
    pb = dbm.upsert_paper(conn, p)  # same paper, second run
    conn.commit()
    n_papers = conn.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
    check("openalex-only paper not duplicated on re-run", pa == pb and n_papers == 1)

    # --- upsert_paper merge across two ids never violates the unique index
    conn.execute("DELETE FROM papers")
    a = dbm.upsert_paper(conn, {"pmcid": "PMC77", "title": "A"})       # pmcid-only
    b = dbm.upsert_paper(conn, {"doi": "10.1/z", "title": "A"})        # doi-only, same work
    merged_ok = True
    try:
        dbm.upsert_paper(conn, {"doi": "10.1/z", "pmcid": "PMC77", "title": "A"})  # both
        conn.commit()
    except Exception as e:
        merged_ok = False
        print(f"      raised: {e}")
    check("upsert_paper both-ids merge doesn't violate unique index", merged_ok)

    # --- _lod_ppb doesn't crash on a bare-dot lod string
    crash = False
    try:
        r = tools._lod_ppb({"lod": "approx. ppb sensitivity"})
    except Exception as e:
        crash = True
        print(f"      raised: {e}")
    check("_lod_ppb tolerates 'approx. ppb' without crashing", not crash)

    # --- _lod_ppb still parses a real value
    check("_lod_ppb('0.40 ppb') == 0.40", tools._lod_ppb({"lod": "0.40 ppb"}) == 0.40)
    check("_lod_ppb('50 ppt') == 0.05", abs(tools._lod_ppb({"lod": "LDL 50 ppt"}) - 0.05) < 1e-9)

    # --- marketplace price parsing is tolerant
    check("price '$1,200' -> 1200.0", marketplace._parse_price("$1,200") == 1200.0)
    check("price ' 950 ' -> 950.0", marketplace._parse_price(" 950 ") == 950.0)
    check("price 'call for quote' -> None", marketplace._parse_price("call for quote") is None)

    # --- outage guard: no candidates + a search error must NOT delete existing links
    iid = dbm.upsert_instrument(conn, row)
    pid = dbm.upsert_paper(conn, {"doi": "10.9/keep", "title": "keeper"})
    dbm.upsert_link(conn, iid, pid, evidence="uses the Test X1", alias="X1",
                    section="methods", source="europepmc", confidence=0.9)
    conn.commit()
    links_before = conn.execute("SELECT COUNT(*) c FROM instrument_paper WHERE instrument_id=?", (iid,)).fetchone()["c"]

    orig_epmc, orig_oa = literature.epmc_search, literature.openalex_search

    def boom_epmc(*a, **k):
        raise literature.SearchError("simulated EPMC outage")

    def boom_oa(*a, **k):
        raise literature.SearchError("simulated OpenAlex outage")

    literature.epmc_search, literature.openalex_search = boom_epmc, boom_oa
    try:
        inst = dict(conn.execute("SELECT * FROM instruments WHERE id=?", (iid,)).fetchone())
        stat = literature.run_for_instrument(conn, inst, skip_llm=True)
    finally:
        literature.epmc_search, literature.openalex_search = orig_epmc, orig_oa
    links_after = conn.execute("SELECT COUNT(*) c FROM instrument_paper WHERE instrument_id=?", (iid,)).fetchone()["c"]
    check("outage does not wipe existing links",
          links_before == 1 and links_after == 1 and stat.get("skipped") == "search_error")

    conn.close()
    print()
    ok = sum(1 for _, c in results if c)
    print(f"{ok}/{len(results)} checks passed")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
