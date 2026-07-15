#!/usr/bin/env python3
"""Export the curated instruments table to web/data/instruments.json for the
static front-end. Specs stay static (no public API serves them); literature is
queried live in the browser.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db as dbm  # noqa: E402

OUT = ROOT / "web" / "data" / "instruments.json"


def main() -> None:
    conn = dbm.connect()
    rows = []
    for r in dbm.all_instruments(conn):
        rows.append({
            "manufacturer": r["manufacturer"],
            "model": r["model"],
            "model_aliases": json.loads(r["model_aliases"]),
            "category": r["category"],
            "principle": r["principle"],
            "specs": json.loads(r["specs_json"]),
            "specs_provenance": r["specs_provenance"],
            "datasheet_url": r["datasheet_url"],
            "status": r["status"],
            "epa_designation": r["epa_designation"],
            "ccep_designation": r["ccep_designation"] if "ccep_designation" in r.keys() else None,
        })
    conn.close()
    rows.sort(key=lambda x: (x["manufacturer"], x["model"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    cats = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print(f"exported {len(rows)} instruments -> {OUT.relative_to(ROOT)}")
    for c, n in sorted(cats.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {c}")


if __name__ == "__main__":
    main()
