"""Seed pipeline: load the curated model list into the instruments table.

Input: data/seed_models.json (list of instrument rows, produced by the
multi-agent curation workflow) or data/seed_models.csv (same columns, flat).
"""
from __future__ import annotations

import csv
import json

from common import DATA_DIR
import db as dbm

SEED_JSON = DATA_DIR / "seed_models.json"
SEED_CSV = DATA_DIR / "seed_models.csv"


def load_rows() -> list[dict]:
    if SEED_JSON.exists():
        return json.loads(SEED_JSON.read_text(encoding="utf-8"))
    if SEED_CSV.exists():
        rows = []
        with SEED_CSV.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                # csv.DictReader yields '' for empty cells; convert to None so the
                # DB stores NULL and COALESCE in upsert doesn't clobber real values
                r = {k: (v if (v is not None and v != "") else None) for k, v in r.items()}
                r["model_aliases"] = json.loads(r.get("model_aliases") or "[]")
                r["specs"] = json.loads(r.get("specs") or "{}")
                r["confidence"] = float(r["confidence"]) if r.get("confidence") else 1.0
                rows.append(r)
        return rows
    raise FileNotFoundError("no data/seed_models.json or data/seed_models.csv found")


def export_csv(rows: list[dict]) -> None:
    """Keep the proposal's data/seed_models.csv in sync as the flat artifact."""
    cols = ["manufacturer", "model", "model_aliases", "category", "principle",
            "specs", "datasheet_url", "status", "epa_designation", "confidence"]
    with SEED_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            out = {c: r.get(c) for c in cols}
            out["model_aliases"] = json.dumps(r.get("model_aliases") or [], ensure_ascii=False)
            out["specs"] = json.dumps(r.get("specs") or {}, ensure_ascii=False)
            w.writerow(out)


def run() -> int:
    rows = load_rows()
    conn = dbm.connect()
    dbm.init_db(conn)
    n = 0
    for row in rows:
        dbm.upsert_instrument(conn, row)
        n += 1
    conn.commit()
    conn.close()
    export_csv(rows)
    print(f"seeded {n} instruments -> {dbm.DB_PATH if hasattr(dbm, 'DB_PATH') else 'db'}")
    return n
