"""Evaluation harness (proposal §9).

  python eval/run_eval.py precision [--n 50]   LLM-judged review of random links
  python eval/run_eval.py specs [--frac 0.1]   sample rows for manual spec check
  python eval/run_eval.py e2e                  run the 6 tools on realistic queries

Precision uses an independent LLM judge over stored evidence snippets — a
proxy for the manual review the proposal calls for; the sampled links are also
written to eval/precision_sample.json so a human can re-score them.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db as dbm  # noqa: E402
from llm import llm_json  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["idx", "correct", "reason"],
                "properties": {
                    "idx": {"type": "integer"},
                    "correct": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


def eval_precision(n: int = 50) -> None:
    conn = dbm.connect()
    rows = conn.execute(
        """
        SELECT i.manufacturer, i.model, i.category, p.title, p.year, p.venue,
               ip.evidence_snippet, ip.confidence, ip.section
        FROM instrument_paper ip
        JOIN instruments i ON i.id = ip.instrument_id
        JOIN papers p ON p.id = ip.paper_id
        WHERE ip.confidence >= 0.7 AND ip.evidence_snippet IS NOT NULL
        """
    ).fetchall()
    conn.close()
    if not rows:
        print("no links with evidence to evaluate — run the literature pipeline first")
        return
    sample = random.sample(rows, min(n, len(rows)))
    records = [dict(r) for r in sample]
    (OUT_DIR / "precision_sample.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    correct = judged = 0
    details = []
    for i in range(0, len(records), 10):
        batch = records[i : i + 10]
        listing = "\n".join(
            f'[{j}] instrument: {r["manufacturer"]} {r["model"]} ({r["category"]}) | '
            f'paper: "{r["title"]}" ({r["year"]}, {r["venue"]}) | '
            f'evidence: "{r["evidence_snippet"]}"'
            for j, r in enumerate(batch)
        )
        prompt = f"""Independently audit an instrument-to-paper index. For each entry below, judge whether
the evidence text genuinely shows the named paper USED that exact instrument model in its
experimental/monitoring work (correct=true), or whether the link is wrong (false string match,
different model, incidental mention/comparison only).

{listing}"""
        try:
            result = llm_json(prompt, schema=JUDGE_SCHEMA)
        except Exception as e:
            print(f"judge batch failed: {e}")
            continue
        for v in result.get("verdicts", []):
            # CLI backend does not enforce the schema — skip malformed verdicts
            if not isinstance(v, dict) or "idx" not in v or "correct" not in v:
                continue
            idx = v["idx"]
            if isinstance(idx, int) and 0 <= idx < len(batch):
                judged += 1
                correct += bool(v["correct"])
                details.append({**batch[idx], "judge_correct": v["correct"],
                                "judge_reason": v.get("reason", "")})
    (OUT_DIR / "precision_judged.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if judged:
        print(f"linkage precision (LLM-judged, n={judged}): {correct / judged:.1%}  (target >=90%)")
        print(f"details -> eval/precision_judged.json, raw sample -> eval/precision_sample.json")


def eval_specs(frac: float = 0.1) -> None:
    conn = dbm.connect()
    rows = [dict(r) for r in dbm.all_instruments(conn)]
    conn.close()
    if not rows:
        print("no instruments to sample — run `labscope seed` first")
        return
    sample = random.sample(rows, max(1, min(len(rows), int(len(rows) * frac))))
    out = [
        {"manufacturer": r["manufacturer"], "model": r["model"],
         "specs": json.loads(r["specs_json"]), "provenance": r["specs_provenance"],
         "datasheet_url": r["datasheet_url"]}
        for r in sample
    ]
    path = OUT_DIR / "spec_spotcheck.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} rows sampled for manual datasheet comparison -> {path}")


E2E_QUERIES = [
    ("spec_lookup", {"model": "thermo 42i"}),
    ("spec_lookup", {"model": "teledyne t200"}),
    ("compare_models", {"category": "NOx analyzer"}),
    ("paper_search", {"model": "42i", "limit": 5}),
    ("paper_search", {"model": "APNA-370", "limit": 5}),
    ("usage_profile", {"model": "serinus 40"}),
    ("usage_profile", {"model": "49i"}),
    ("market_search", {"model": "42i"}),
    ("recommend", {"category": "NOx analyzer"}),
    ("recommend", {"category": "O3 analyzer", "require_current": True}),
]


def eval_e2e() -> None:
    from agent.tools import TOOL_FUNCS

    ok = 0
    for name, args in E2E_QUERIES:
        try:
            result = TOOL_FUNCS[name](**args)
            found = result.get("found", True) and (
                result.get("recommendations") or result.get("matrix") or
                result.get("papers") or result.get("instrument") or result.get("listings") is not None
            )
            status = "OK " if found else "EMPTY"
            ok += status == "OK "
            print(f"[{status}] {name}({json.dumps(args, ensure_ascii=False)})")
        except Exception as e:
            print(f"[ERR] {name}({args}): {e}")
    print(f"\n{ok}/{len(E2E_QUERIES)} end-to-end tool queries returned substantive results")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("precision")
    sp.add_argument("--n", type=int, default=50)
    sp = sub.add_parser("specs")
    sp.add_argument("--frac", type=float, default=0.1)
    sub.add_parser("e2e")
    args = p.parse_args()
    if args.cmd == "precision":
        eval_precision(args.n)
    elif args.cmd == "specs":
        eval_specs(args.frac)
    else:
        eval_e2e()
