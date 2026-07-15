"""Literature pipeline (proposal §5.2 — the core).

Per instrument model:
  1. Query Europe PMC (METHODS-scoped, OA fulltext) + OpenAlex (fulltext.search)
     with the model string AND all aliases, always co-constrained by manufacturer
     or category keyword when the alias alone is ambiguous.
  2. Pull the matching Methods sentence as evidence_snippet (Europe PMC fullTextXML,
     cached on disk).
  3. LLM disambiguation pass: does the snippet describe *using* this instrument?
     Store confidence; links below MIN_STORE_CONFIDENCE are dropped.
  4. Enrich accepted papers via OpenAlex (fields, affiliations, venue, citations).

Idempotent and resumable: everything is upserted; fulltext is cached.
"""
from __future__ import annotations

import html
import json
import os
import re
import xml.etree.ElementTree as ET

from common import CACHE_DIR, RateLimiter, get_json, http_client, log_query
from llm import llm_json
import db as dbm

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENALEX_BASE = "https://api.openalex.org"

epmc_limiter = RateLimiter(0.35)
oa_limiter = RateLimiter(0.25)

FULLTEXT_CACHE = CACHE_DIR / "fulltext"
FULLTEXT_CACHE.mkdir(parents=True, exist_ok=True)

MIN_STORE_CONFIDENCE = 0.5     # links below this are not stored
# No-snippet confidence tiers: an EPMC hit already means the phrase matched inside
# the *Methods* section of the indexed fulltext, which is itself strong evidence.
CONF_EPMC_BRAND_PHRASE = 0.70  # e.g. METHODS:"Thermo 42i" matched, no snippet retrieved
CONF_EPMC_GENERIC = 0.65       # e.g. METHODS:"42i" AND (Thermo OR NOx) matched
CONF_OPENALEX_ONLY = 0.60      # fulltext.search matched somewhere in the paper

BRAND_TOKENS = {
    "thermo", "tei", "teledyne", "api", "ecotech", "acoem", "horiba", "envea",
    "environnement", "picarro", "aerodyne", "2b", "ecophysics", "eco physics",
    "los gatos", "lgr", "abb", "focused photonics", "fpi", "serinus",
}

CATEGORY_KEYWORD = {
    "NOx analyzer": "NOx", "NO2 analyzer": "NO2", "SO2 analyzer": "SO2",
    "O3 analyzer": "ozone", "CO analyzer": "carbon monoxide",
    "NH3 analyzer": "ammonia", "multi-gas analyzer": "analyzer",
    "calibrator": "calibrat",
}

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_TAG_RE = re.compile(r"<[^>]+>")


def clean_title(title: str | None) -> str | None:
    """Unescape HTML entities and strip inline markup (e.g. <sub>2</sub>) that
    Europe PMC / OpenAlex sometimes leave in title strings."""
    if not title:
        return None
    return _TAG_RE.sub("", html.unescape(title)).strip() or None


class SearchError(Exception):
    """A source API hard-failed (network/5xx after retries) — distinct from an
    empty-but-successful result, so the caller can avoid a destructive refresh."""


def _has_brand(alias: str) -> bool:
    a = alias.lower()
    return any(tok in a for tok in BRAND_TOKENS)


def _brand_word(manufacturer: str) -> str:
    first = manufacturer.split()[0].strip("(),")
    return first


def _alias_pattern(alias: str) -> re.Pattern:
    """Word-boundary regex for an alias, tolerant of space/hyphen variation."""
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", alias.strip()) if p]
    body = r"[\s\-]?".join(parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def build_queries(inst: dict) -> list[tuple[str, str]]:
    """Return [(alias, europepmc_query)] for one instrument."""
    aliases = [inst["model"]] + json.loads(inst["model_aliases"])
    brand = _brand_word(inst["manufacturer"])
    kw = CATEGORY_KEYWORD.get(inst["category"] or "", "analyzer")
    queries = []
    seen = set()
    for alias in aliases:
        alias = alias.strip()
        if not alias or alias.lower() in seen:
            continue
        seen.add(alias.lower())
        if _has_brand(alias):
            q = f'METHODS:"{alias}"'
        else:
            q = f'METHODS:"{alias}" AND (METHODS:"{brand}" OR METHODS:"{kw}")'
        queries.append((alias, q))
    return queries


# ------------------------------------------------------------------ Europe PMC

def epmc_search(query: str, max_results: int = 200) -> list[dict]:
    out, cursor = [], "*"
    while len(out) < max_results:
        params = {
            "query": query, "format": "json", "resultType": "core",
            "pageSize": min(100, max_results - len(out)), "cursorMark": cursor,
        }
        data = get_json(f"{EPMC_BASE}/search", params, "europepmc", epmc_limiter)
        if data is None:
            # hard failure after retries; if we have nothing yet it's a true outage
            if not out:
                raise SearchError(f"Europe PMC search failed for {query!r}")
            break
        results = (data.get("resultList") or {}).get("result") or []
        log_query("europepmc", f"{EPMC_BASE}/search", params, len(results))
        out.extend(results)
        nxt = data.get("nextCursorMark")
        if not results or not nxt or nxt == cursor:
            break
        cursor = nxt
    return out


def epmc_fulltext(pmcid: str) -> str | None:
    """Fetch (and cache) full-text XML for an OA article; return plain text with
    <SEC:title> markers so we can attribute snippets to the Methods section."""
    cache = FULLTEXT_CACHE / f"{pmcid}.txt"
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
        return text or None
    url = f"{EPMC_BASE}/{pmcid}/fullTextXML"
    try:
        epmc_limiter.wait()
        r = http_client().get(url)
        log_query("europepmc", url, None, 1 if r.status_code == 200 else 0)
        if r.status_code == 200 and r.text.strip():
            root = ET.fromstring(r.text)
        elif r.status_code in (404, 204) or (r.status_code == 200 and not r.text.strip()):
            # genuinely no OA fulltext for this article — safe to cache the negative
            cache.write_text("", encoding="utf-8")
            return None
        else:
            # transient (429/5xx) or unexpected status — do NOT poison the cache;
            # a later run will retry.
            log_query("europepmc", url, None, None, note=f"transient status {r.status_code}")
            return None
    except Exception as e:
        # network / XML-parse error — transient, do not cache
        log_query("europepmc", url, None, None, note=f"fulltext error: {e}")
        return None
    chunks: list[str] = []

    def walk(el, in_sec_title=False):
        tag = el.tag.lower()
        if tag == "sec":
            title_el = el.find("title")
            title = ("".join(title_el.itertext()).strip() if title_el is not None else "")
            chunks.append(f"\n<SEC:{title}>\n")
        for child in el:
            walk(child)
        if tag in ("p", "title"):
            txt = "".join(el.itertext()).strip()
            if txt:
                chunks.append(txt + "\n")

    body = root.find(".//body")
    if body is None:
        cache.write_text("", encoding="utf-8")
        return None
    walk(body)
    text = "".join(chunks)
    cache.write_text(text, encoding="utf-8")
    return text or None


def find_snippets(text: str, alias: str, max_snips: int = 2) -> list[tuple[str, str]]:
    """Return [(snippet, section)] for sentences matching alias in fulltext."""
    pat = _alias_pattern(alias)
    out = []
    section = "fulltext"
    for block in text.split("\n"):
        m = re.match(r"^<SEC:(.*)>$", block.strip())
        if m:
            title = m.group(1).lower()
            if any(k in title for k in ("method", "material", "experimental", "instrument", "measurement", "sampling", "site")):
                section = "methods"
            elif title:
                section = "fulltext"
            continue
        if not pat.search(block):
            continue
        for sent in _SENT_SPLIT.split(block):
            if pat.search(sent):
                out.append((sent.strip()[:600], section))
                if len(out) >= max_snips:
                    return out
    return out


# -------------------------------------------------------------------- OpenAlex

def _oa_params(extra: dict) -> dict:
    p = dict(extra)
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        p["mailto"] = mailto
    return p


def openalex_search(phrase: str, max_results: int = 100) -> list[dict]:
    params = _oa_params({
        "filter": f'fulltext.search:"{phrase}"',
        "per-page": min(100, max_results),
        "select": "id,doi,title,publication_year,primary_location,authorships,primary_topic,cited_by_count",
    })
    data = get_json(f"{OPENALEX_BASE}/works", params, "openalex", oa_limiter)
    if data is None:
        raise SearchError(f"OpenAlex search failed for {phrase!r}")
    results = data.get("results") or []
    log_query("openalex", f"{OPENALEX_BASE}/works", params, len(results))
    return results


_OA_SELECT = "id,doi,title,publication_year,primary_location,authorships,primary_topic,cited_by_count"


def _oa_fetch_dois(dois: list[str]) -> dict[str, dict]:
    if not dois:
        return {}
    params = _oa_params({"filter": "doi:" + "|".join(dois), "per-page": 50, "select": _OA_SELECT})
    data = get_json(f"{OPENALEX_BASE}/works", params, "openalex", oa_limiter)
    out = {}
    for w in (data or {}).get("results") or []:
        if w.get("doi"):
            out[w["doi"].lower().removeprefix("https://doi.org/")] = w
    return out


def openalex_enrich_by_doi(dois: list[str]) -> dict[str, dict]:
    """Batch-enrich papers by DOI (50 per request). Returns {doi_lower: work}.

    OpenAlex's OR-pipe filter uses ',' as the AND separator, so a DOI containing
    a comma (spec-legal) would corrupt the whole batch. Such DOIs are pulled out
    and fetched one-per-request instead."""
    out: dict[str, dict] = {}
    clean = [d.lower().removeprefix("https://doi.org/") for d in dois if d]
    batchable = [d for d in clean if "," not in d and "|" not in d]
    singletons = [d for d in clean if "," in d or "|" in d]
    for i in range(0, len(batchable), 50):
        out.update(_oa_fetch_dois(batchable[i : i + 50]))
    for d in singletons:
        # comma/pipe DOIs can't go through the OR-filter at all — use the entity path
        params = _oa_params({"select": _OA_SELECT})
        w = get_json(f"{OPENALEX_BASE}/works/doi:{d}", params, "openalex", oa_limiter)
        if isinstance(w, dict) and w.get("doi"):
            out[w["doi"].lower().removeprefix("https://doi.org/")] = w
    return out


def _work_to_paper(w: dict) -> dict:
    fields = []
    if w.get("primary_topic"):
        t = w["primary_topic"]
        fields = [x for x in [t.get("display_name"),
                              (t.get("subfield") or {}).get("display_name"),
                              (t.get("field") or {}).get("display_name")] if x]
    affs = []
    for a in (w.get("authorships") or [])[:25]:
        for inst in a.get("institutions") or []:
            name = inst.get("display_name")
            if name and name not in affs:
                affs.append(name)
    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
    return {
        "doi": (w.get("doi") or "").removeprefix("https://doi.org/") or None,
        "openalex_id": w.get("id"),
        "title": clean_title(w.get("title")),
        "year": w.get("publication_year"),
        "venue": venue,
        "fields": fields[:3],
        "affiliations": affs[:10],
        "citation_count": w.get("cited_by_count"),
    }


# -------------------------------------------------------------- Disambiguation

DISAMBIG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["judgements"],
    "properties": {
        "judgements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["idx", "used", "confidence"],
                "properties": {
                    "idx": {"type": "integer"},
                    "used": {"type": "boolean"},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}


def disambiguate(inst: dict, candidates: list[dict], batch_size: int = 10) -> None:
    """LLM pass: for each candidate with evidence text, decide whether the text
    shows this exact instrument being *used* in the study. Mutates candidates
    in place, setting 'confidence'."""
    desc = (f"{inst['manufacturer']} {inst['model']} — {inst['category'] or 'gas analyzer'}"
            f" ({inst['principle'] or 'unknown principle'})")
    with_text = [c for c in candidates if c.get("evidence")]
    for i in range(0, len(with_text), batch_size):
        batch = with_text[i : i + batch_size]
        listing = "\n".join(
            f'[{j}] (matched alias: "{c["alias"]}") "{c["evidence"]}"' for j, c in enumerate(batch)
        )
        prompt = f"""You are validating an instrument-to-paper index for lab equipment buyers.

Target instrument: {desc}

Below are text excerpts from different papers, each of which string-matched one of the instrument's aliases. For each excerpt, judge whether the paper actually USED this exact instrument in its experimental/monitoring work.

Count as used=true: the instrument appears in a description of the measurement setup, sampling, calibration, or data collection.
Count as used=false: false string matches (e.g. "42 in." or a different product sharing the token), mentions of a different model/variant from another manufacturer, papers that merely cite or compare against the instrument without using it, or excerpts too ambiguous to tell.

confidence: 0-1, your confidence in the used=true judgement (for used=false, confidence of the rejection).

Excerpts:
{listing}"""
        judgements: dict[int, dict] = {}
        try:
            result = llm_json(prompt, schema=DISAMBIG_SCHEMA)
            for j in result.get("judgements", []):
                if isinstance(j, dict) and "idx" in j:
                    judgements[j["idx"]] = j
        except Exception as e:
            print(f"    ! disambiguation batch failed ({e}); keeping snippets at 0.55")
        for j, c in enumerate(batch):
            v = judgements.get(j)
            # The CLI backend does not enforce the schema, so a judgement may be
            # missing 'used'/'confidence'; treat any malformed item as unjudged.
            if not isinstance(v, dict) or "used" not in v or "confidence" not in v:
                c["confidence"] = 0.6
                continue
            try:
                conf = max(0.0, min(1.0, float(v["confidence"])))
            except (TypeError, ValueError):
                c["confidence"] = 0.6
                continue
            c["confidence"] = conf if v["used"] else round((1.0 - conf) * 0.5, 3)


# ---------------------------------------------------------------------- runner

def _paper_key(p: dict) -> str:
    return (p.get("doi") or p.get("pmcid") or p.get("pmid") or p.get("openalex_id") or "").lower()


def run_for_instrument(conn, inst: dict, max_per_query: int = 100,
                       fulltext_budget: int = 60, skip_llm: bool = False) -> dict:
    """Full literature pass for one instrument. Returns summary stats."""
    print(f"\n=== {inst['manufacturer']} {inst['model']} ===")
    candidates: dict[str, dict] = {}
    search_errors = 0

    # -- Europe PMC (METHODS-scoped)
    for alias, query in build_queries(inst):
        try:
            hits = epmc_search(query, max_results=max_per_query)
        except SearchError as e:
            search_errors += 1
            print(f"  EPMC  {query!r}: ERROR ({e})")
            continue
        print(f"  EPMC  {query!r}: {len(hits)} hits")
        for h in hits:
            paper = {
                "doi": h.get("doi"), "pmid": h.get("pmid"), "pmcid": h.get("pmcid"),
                "title": clean_title(h.get("title")),
                "year": int(h["pubYear"]) if h.get("pubYear") else None,
                "venue": h.get("journalTitle"), "oa_fulltext_source": "europepmc",
            }
            key = _paper_key(paper)
            if not key:
                continue
            c = candidates.setdefault(key, {"paper": paper, "alias": alias, "source": "europepmc",
                                            "evidence": None, "section": None,
                                            "brand_phrase": _has_brand(alias)})
            c["brand_phrase"] = c.get("brand_phrase") or _has_brand(alias)
            # try to extract an evidence snippet from cached/downloaded fulltext
            if c["evidence"] is None and h.get("pmcid") and fulltext_budget > 0:
                text = epmc_fulltext(h["pmcid"])
                fulltext_budget -= 1
                if text:
                    snips = find_snippets(text, alias)
                    if not snips and alias != inst["model"]:
                        snips = find_snippets(text, inst["model"])
                    if snips:
                        # prefer a methods-section sentence
                        snips.sort(key=lambda s: 0 if s[1] == "methods" else 1)
                        c["evidence"], c["section"] = snips[0]
            # abstract fallback for evidence
            if c["evidence"] is None and h.get("abstractText"):
                pat = _alias_pattern(alias)
                if pat.search(h["abstractText"]):
                    for sent in _SENT_SPLIT.split(h["abstractText"]):
                        if pat.search(sent):
                            c["evidence"], c["section"] = sent.strip()[:600], "abstract"
                            break

    # -- OpenAlex (fulltext.search recall supplement)
    brand = _brand_word(inst["manufacturer"])
    oa_phrases = []
    for alias in [inst["model"]] + json.loads(inst["model_aliases"]):
        oa_phrases.append(alias if _has_brand(alias) else f"{brand} {alias}")
    seen_p = set()
    for phrase in oa_phrases:
        if phrase.lower() in seen_p:
            continue
        seen_p.add(phrase.lower())
        try:
            works = openalex_search(phrase, max_results=max_per_query)
        except SearchError as e:
            search_errors += 1
            print(f"  OA    {phrase!r}: ERROR ({e})")
            continue
        print(f"  OA    {phrase!r}: {len(works)} hits")
        for w in works:
            paper = _work_to_paper(w)
            key = _paper_key(paper)
            if not key:
                continue
            if key in candidates:
                # merge enrichment into the EPMC candidate
                candidates[key]["paper"].update({k: v for k, v in paper.items() if v})
            else:
                candidates[key] = {"paper": paper, "alias": phrase, "source": "openalex",
                                   "evidence": None, "section": "fulltext"}

    cands = list(candidates.values())
    print(f"  -> {len(cands)} unique candidate papers "
          f"({sum(1 for c in cands if c['evidence'])} with evidence text)")

    # Guard against destroying existing links on a transient outage: if we found
    # no candidates AND at least one source hard-failed, we cannot distinguish an
    # outage from a genuinely paper-less instrument — so skip the refresh entirely.
    if not cands and search_errors:
        print(f"  !! {search_errors} source error(s) and 0 candidates — "
              f"preserving existing links (no refresh)")
        return {"model": inst["model"], "candidates": 0, "kept": 0,
                "skipped": "search_error", "search_errors": search_errors}

    # -- Disambiguation
    def _no_snippet_conf(c: dict) -> float:
        if c["source"] == "europepmc":
            # methods-scoped phrase match confirmed by the EPMC index itself
            c["section"] = c["section"] or "methods"
            return CONF_EPMC_BRAND_PHRASE if c.get("brand_phrase") else CONF_EPMC_GENERIC
        return CONF_OPENALEX_ONLY

    if skip_llm:
        # Without the LLM judge we can't validate the snippet, but a retrieved
        # Methods sentence is still at least as strong as a bare index match — so
        # a snippet-bearing candidate must never rank *below* a snippet-less one.
        for c in cands:
            base = _no_snippet_conf(c)
            c["confidence"] = max(base, 0.6) if c["evidence"] else base
    else:
        disambiguate(inst, cands)
        for c in cands:
            if "confidence" not in c:
                c["confidence"] = _no_snippet_conf(c)

    kept = [c for c in cands if c["confidence"] >= MIN_STORE_CONFIDENCE]
    print(f"  -> {len(kept)} links kept (confidence >= {MIN_STORE_CONFIDENCE})")

    # -- Enrichment via OpenAlex for kept papers missing metadata
    need = [c["paper"]["doi"] for c in kept
            if c["paper"].get("doi") and not c["paper"].get("fields")]
    if need:
        enriched = openalex_enrich_by_doi(need)
        for c in kept:
            doi = (c["paper"].get("doi") or "").lower()
            if doi in enriched:
                extra = _work_to_paper(enriched[doi])
                c["paper"].update({k: v for k, v in extra.items() if v})

    # -- Persist (full refresh for this instrument so re-judged links don't linger).
    # The DELETE + inserts are one atomic unit: any failure here rolls back so a
    # partial refresh is never committed (and can't be committed by a later
    # instrument's commit).
    try:
        conn.execute("DELETE FROM instrument_paper WHERE instrument_id = ?", (inst["id"],))
        for c in kept:
            pid = dbm.upsert_paper(conn, c["paper"])
            dbm.upsert_link(conn, inst["id"], pid, evidence=c["evidence"], alias=c["alias"],
                            section=c["section"], source=c["source"], confidence=c["confidence"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"model": inst["model"], "candidates": len(cands), "kept": len(kept)}


def run(models: list[str] | None = None, limit: int | None = None,
        skip_llm: bool = False) -> list[dict]:
    conn = dbm.connect()
    instruments = [dict(r) for r in dbm.all_instruments(conn)]
    if models:
        wanted = {m.strip().lower() for m in models}
        instruments = [i for i in instruments if i["model"].lower() in wanted]
    if limit:
        instruments = instruments[:limit]
    stats = []
    for inst in instruments:
        try:
            stats.append(run_for_instrument(conn, inst, skip_llm=skip_llm))
        except Exception as e:
            # roll back any partial transaction so the failed instrument's DELETE
            # is not carried into the next instrument's commit
            conn.rollback()
            print(f"  !! pipeline failed for {inst['model']}: {e}")
            stats.append({"model": inst["model"], "error": str(e)})
    conn.close()
    return stats
