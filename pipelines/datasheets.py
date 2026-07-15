"""Datasheet pipeline (proposal §5.1).

For instruments with a datasheet_url: fetch the PDF, extract text (pymupdf),
LLM-extract a strict spec JSON, normalise units, and update specs_json with
provenance 'datasheet'. Instruments without a datasheet URL keep their curated
specs (provenance 'curated').
"""
from __future__ import annotations

import json

from common import CACHE_DIR, http_client, log_query
from llm import llm_json
import db as dbm

PDF_CACHE = CACHE_DIR / "datasheets"
PDF_CACHE.mkdir(parents=True, exist_ok=True)

SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_relevant", "specs"],
    "properties": {
        "is_relevant": {"type": "boolean",
                        "description": "true only if this document is a datasheet/manual for the target instrument"},
        "specs": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ranges", "lod", "response_time_s", "precision", "flow_rate", "notes"],
            "properties": {
                "ranges": {"type": ["string", "null"]},
                "lod": {"type": ["string", "null"]},
                "response_time_s": {"type": ["number", "null"]},
                "precision": {"type": ["string", "null"]},
                "flow_rate": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]},
            },
        },
    },
}


def _looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def fetch_pdf(inst_id: int, url: str) -> bytes | None:
    cache = PDF_CACHE / f"{inst_id}.pdf"
    if cache.exists():
        data = cache.read_bytes()
        # validate cached bytes so a previously-poisoned cache (e.g. an HTML
        # soft-404 saved as .pdf) can't crash every future run
        if _looks_like_pdf(data):
            return data
        cache.unlink(missing_ok=True)
    try:
        r = http_client().get(url)
        log_query("datasheet", url, None, 1 if r.status_code == 200 else 0)
        if r.status_code != 200 or not _looks_like_pdf(r.content):
            log_query("datasheet", url, None, None,
                      note=f"not a PDF (status {r.status_code}, magic {r.content[:5]!r})")
            return None
        cache.write_bytes(r.content)
        return r.content
    except Exception as e:
        log_query("datasheet", url, None, None, note=f"fetch error: {e}")
        return None


def extract_text(pdf_bytes: bytes, max_chars: int = 20000) -> str:
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
    return text[:max_chars]


def run(models: list[str] | None = None) -> dict:
    conn = dbm.connect()
    instruments = [dict(r) for r in dbm.all_instruments(conn)]
    if models:
        wanted = {m.strip().lower() for m in models}
        instruments = [i for i in instruments if i["model"].lower() in wanted]
    done = skipped = failed = 0
    for inst in instruments:
        if not inst["datasheet_url"]:
            skipped += 1
            continue
        if inst["specs_provenance"] == "datasheet":
            done += 1
            continue
        pdf = fetch_pdf(inst["id"], inst["datasheet_url"])
        if not pdf:
            failed += 1
            continue
        try:
            text = extract_text(pdf)
        except Exception as e:  # corrupt/truncated PDF — never abort the whole run
            print(f"  ! could not parse PDF for {inst['model']}: {e}")
            failed += 1
            continue
        prompt = f"""Extract performance specifications for this instrument from its datasheet text.

Target instrument: {inst['manufacturer']} {inst['model']} ({inst['category']}).

Normalise units to ppb/ppm for concentrations and seconds for response time.
Use null for anything not stated — do NOT guess.

Datasheet text:
{text}"""
        try:
            result = llm_json(prompt, schema=SPEC_SCHEMA)
        except Exception as e:
            print(f"  ! extraction failed for {inst['model']}: {e}")
            failed += 1
            continue
        # the CLI backend does not enforce the schema — validate the shape
        if not isinstance(result, dict) or not isinstance(result.get("specs"), dict):
            print(f"  ! malformed extraction output for {inst['model']}")
            failed += 1
            continue
        if not result.get("is_relevant"):
            print(f"  ! fetched document not relevant for {inst['model']}")
            failed += 1
            continue
        conn.execute(
            "UPDATE instruments SET specs_json = ?, specs_provenance = 'datasheet' WHERE id = ?",
            (json.dumps(result["specs"], ensure_ascii=False), inst["id"]),
        )
        conn.commit()
        print(f"  extracted datasheet specs for {inst['manufacturer']} {inst['model']}")
        done += 1
    conn.close()
    return {"datasheet": done, "no_url": skipped, "failed": failed}
