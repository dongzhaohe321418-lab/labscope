#!/usr/bin/env python3
"""One-off data cleaning: merge duplicate models that were seeded under
inconsistent manufacturer spellings (e.g. Serinus 40 under "Ecotech (Acoem)"
vs "Ecotech / Acoem"). Uses an LLM only to pick the canonical manufacturer name
for each duplicate group; falls back to a rule (shortest clean name) if no
OPENAI_API_KEY is set. The result is written back to the static seed — there is
no runtime LLM dependency.

  OPENAI_API_KEY=... python scripts/dedupe_seed.py          # LLM-normalised
  python scripts/dedupe_seed.py                             # rule-based
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "web" / "data" / "instruments.json"


def nm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def canonical_by_rule(mfrs: list[str]) -> str:
    # shortest name without parenthetical / "distributed"/"/" clutter wins
    clean = [re.sub(r"\s*\(.*?\)\s*", " ", m).split(";")[0].strip() for m in mfrs]
    clean = [c for c in clean if c] or mfrs
    return min(clean, key=len)


def llm_canonical(groups: list[dict]) -> dict[str, str]:
    """Ask the LLM for the canonical manufacturer per duplicate model. Returns
    {model_key: manufacturer}. Empty dict on any failure (caller falls back)."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return {}
    import urllib.request

    payload = {
        "model": "gpt-4o-mini",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "For each gas-analyzer model you are given several manufacturer-name variants that refer to the SAME instrument. Return JSON {\"models\":[{\"key\":..., \"manufacturer\":<the single most standard/canonical manufacturer name>}]}. Prefer the current/standard corporate name, drop distribution notes and parentheticals."},
            {"role": "user", "content": json.dumps({"models": groups}, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
        content = json.loads(body["choices"][0]["message"]["content"])
        return {m["key"]: m["manufacturer"] for m in content.get("models", []) if m.get("manufacturer")}
    except Exception as e:
        print(f"  ! LLM normalisation failed ({e}); using rule fallback", file=sys.stderr)
        return {}


def merge_group(rows: list[dict], canonical_mfr: str) -> dict:
    # pick the row with the most non-null spec fields as the base
    def richness(r):
        s = r.get("specs") or {}
        return sum(1 for v in s.values() if v not in (None, ""))
    base = dict(max(rows, key=richness))
    base["manufacturer"] = canonical_mfr
    # union aliases, and fold every manufacturer variant + model into aliases so
    # searching by any spelling still resolves
    aliases = set()
    for r in rows:
        for a in r.get("model_aliases") or []:
            aliases.add(a)
        aliases.add(f"{r['manufacturer']} {r['model']}")
    aliases.discard(base["model"])
    base["model_aliases"] = sorted(aliases)[:12]
    # first non-null wins for these fields
    for field in ("epa_designation", "ccep_designation", "datasheet_url", "principle", "category"):
        if not base.get(field):
            for r in rows:
                if r.get(field):
                    base[field] = r[field]
                    break
    # prefer a "current" status if any variant is current
    if any((r.get("status") == "current") for r in rows):
        base["status"] = "current"
    return base


def main() -> None:
    rows = json.loads(SEED.read_text(encoding="utf-8"))
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(nm(r["model"]), []).append(r)

    dup_keys = [k for k, v in groups.items() if len(v) > 1]
    print(f"{len(rows)} rows, {len(groups)} distinct models, {len(dup_keys)} duplicated")

    llm_groups = [{"key": k, "model": groups[k][0]["model"], "manufacturers": [r["manufacturer"] for r in groups[k]]} for k in dup_keys]
    canon = llm_canonical(llm_groups) if dup_keys else {}
    print(f"LLM normalised {len(canon)}/{len(dup_keys)} manufacturers" if canon else "rule-based normalisation")

    out = []
    for k, v in groups.items():
        if len(v) == 1:
            out.append(v[0])
        else:
            mfr = canon.get(k) or canonical_by_rule([r["manufacturer"] for r in v])
            out.append(merge_group(v, mfr))

    out.sort(key=lambda x: (x["manufacturer"], x["model"]))
    SEED.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} deduplicated rows -> {SEED.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
