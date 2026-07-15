# LabScope — Instrument Intelligence Agent

Reverse index from **instrument model → papers that actually used it**, plus specs and
second-hand listing snapshots, for gas analyzers (NOx / NO₂ / SO₂ / O₃ / CO / NH₃).
Implements the MVP in `instrument-agent-proposal.md` v0.1.

## Layout

```
labscope.py          CLI entry point
common.py            HTTP client (proxy-tolerant TLS), query logging, rate limiting
llm.py               LLM adapter: Anthropic SDK -> `claude` CLI fallback
db/                  schema.sql + SQLite access layer (fuzzy model resolution)
pipelines/
  seed.py            load curated seed models into the DB
  literature.py      Europe PMC (METHODS-scoped) + OpenAlex -> evidence snippets
                     -> LLM disambiguation -> enrichment   ← the core
  datasheets.py      PDF -> pymupdf -> LLM strict-schema spec extraction
  marketplace.py     robots.txt-aware snapshot scraping + manual CSV import
agent/
  tools.py           the 6 tools (spec_lookup, compare_models, paper_search,
                     usage_profile, market_search, recommend)
  mcp_server.py      MCP server — plug the tools into Claude Code (no API key needed)
  chat.py            SDK chat agent (needs ANTHROPIC_API_KEY / `ant auth login`)
web/
  server.py          stdlib HTTP server exposing the tools as a JSON API
  index.html         single-page decision UI (search → dossier → compare)
eval/run_eval.py     linkage precision (LLM-judged + human sample), spec spot-check, e2e
data/                seed_models.json / .csv, caches, query logs
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# behind a TLS-intercepting proxy: pip install --cert .certs/system.pem ...
# (.certs/system.pem is exported from the macOS keychain; regenerate with
#  security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain)
```

Optional environment:

- `ANTHROPIC_API_KEY` — enables the SDK backend and `labscope chat`; without it, the
  LLM steps run through the `claude` CLI (Claude Code subscription).
- `LABSCOPE_LLM_MODEL` — pipeline model (default `claude-opus-4-8`).
- `OPENALEX_MAILTO` — your email for OpenAlex's polite pool (faster rate limits).
- `CORE_API_KEY` — reserved; the CORE recall source is wired but disabled without a key.

## Build the index

```bash
.venv/bin/python labscope.py init-db
.venv/bin/python labscope.py seed                      # data/seed_models.json -> DB
.venv/bin/python labscope.py literature --limit 10     # pilot run (proposal week-2 checkpoint)
.venv/bin/python labscope.py literature                # full run
.venv/bin/python labscope.py datasheets                # optional: refine specs from PDFs
.venv/bin/python labscope.py market                    # optional: listing snapshots
.venv/bin/python labscope.py stats
```

Everything is idempotent and resumable; all external API queries are logged to
`data/logs/queries.jsonl`; fulltext and PDFs are cached under `data/cache/`.

## Use it

**Web UI** (recommended — a single decision flow: search → evidence dossier → compare → decide):

```bash
.venv/bin/python web/server.py 8321      # then open http://127.0.0.1:8321
```

One search box routes by intent — a **model** (`42i`, `T200`, `Serinus 40`) opens an
evidence dossier (specs, per-year usage trend, the papers that used it with Methods
snippets, second-hand listings); a **category** (`NOx 分析仪`, `ozone analyzer`) opens
ranked recommendations plus an aligned spec-comparison matrix. Stdlib-only backend,
light/dark themed, responsive. Landing page shows index coverage and the most-cited
models.

Direct tool calls (no LLM):

```bash
.venv/bin/python labscope.py tool spec_lookup '{"model": "thermo 42i"}'
.venv/bin/python labscope.py tool paper_search '{"model": "T200", "limit": 5}'
.venv/bin/python labscope.py tool recommend '{"category": "NOx analyzer"}'
```

As an agent inside Claude Code (recommended, no API key):

```bash
claude mcp add labscope -- "$PWD/.venv/bin/python" "$PWD/agent/mcp_server.py"
# then in any Claude Code session: "我想买一台NOx分析仪，帮我推荐并给出文献依据"
```

Standalone chat agent (needs API credentials):

```bash
.venv/bin/python labscope.py chat
```

## Evaluate (proposal §9)

```bash
.venv/bin/python eval/run_eval.py precision --n 50   # target >=90% linkage precision
.venv/bin/python eval/run_eval.py specs              # 10% sample for manual datasheet check
.venv/bin/python eval/run_eval.py e2e                # 10 realistic tool queries
.venv/bin/python eval/test_fixes.py                  # regression tests for reviewed bugs
```

Pilot results (13-model run — Thermo 42i/43i/48i/49i/42C, Teledyne T100/T200/T400,
Serinus 40, APNA-370, AC32M, 2B 205, CAPS NO2):

| Metric | Target | Result |
|---|---|---|
| Linkage precision (LLM-judged, n=40) | ≥ 90% | **100%** |
| End-to-end tool queries | 10/10 substantive | **10/10** |
| Week-2 checkpoint: linked papers across pilot models | ≥ 20 | **354** (conf ≥ 0.7) |

## Code review

The codebase was reviewed by a multi-agent workflow (4 dimensions × adversarial
verification). All 24 distinct confirmed findings were fixed — 4 high-severity
(destructive DELETE on API outage, missing rollback on per-instrument failure,
PDF-cache poisoning, dangling-tool_use REPL corruption), plus paper-dedup /
unique-index, cache-poisoning-on-transient-error, and input-validation bugs.
Regression coverage is in `eval/test_fixes.py`.

## Design notes / deviations from the proposal

- **Embeddings table → alias-based fuzzy matching.** MVP fuzzy model resolution uses the
  alias table + token/sequence similarity (`db.resolve_instrument`) instead of embeddings —
  no embedding API dependency; swap in later without schema changes.
- **Link storage threshold.** Links are stored from confidence ≥ 0.5 and the agent tools
  filter at ≥ 0.7 by default, so borderline links remain inspectable (`min_confidence` knob).
- **OpenAlex-only hits** (fulltext match, no retrievable snippet) get confidence 0.6:
  above storage threshold, below the default display threshold.
- **CORE / Semantic Scholar**: CORE needs an API key (skipped without one); Semantic Scholar
  added no Methods-scoped value over EPMC+OpenAlex in the pilot and is left out of the MVP loop.
- **eBay**: robots.txt disallows search-page scraping, so the scraper skips it by design.
  **LabX** allows the path in robots.txt but currently serves 403 to non-browser clients,
  so snapshots come back empty; the supported route is manual import
  (`labscope market-import`, template in `data/example_listings.template.csv`).
  A production version should use official APIs (e.g. eBay Browse API) instead.
- **Compliance head start**: `epa_designation` is already captured in the seed (roadmap 12.6).
