/* LabScope static front-end — real-time literature, OpenAlex-style UI, zh/en. */
'use strict';

const EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest";
const OPENALEX = "https://api.openalex.org";
const MAILTO = "labscope@users.noreply.github.com";
const $ = s => document.querySelector(s);
const app = () => document.getElementById("app");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------- i18n ---------------- */
let LANG = localStorage.getItem("labscope_lang") || (navigator.language.startsWith("zh") ? "zh" : "en");
const I18N = {
  zh: {
    tagline: "仪器采购情报", search_ph: "搜索型号（42i、T200、Serinus 40）或品类（NOx analyzer）…",
    hero_title: "从「哪台仪器」到「有据可依」",
    hero_desc: "把气体分析仪的规格与认证，和实时检索到的、真正用过它的已发表论文（含方法节证据句）汇到一处。",
    flow_1: "选型号", flow_2: "看文献证据", flow_3: "比同类", flow_4: "过采购论证",
    t_models: "已收录型号", t_cats: "仪器品类", t_epa: "EPA 认证型号", t_live: "实时", t_live_l: "文献联网查询",
    browse: "按品类浏览", featured: "常见型号（点开实时查文献）",
    c_model: "型号", c_category: "品类", c_status: "状态", c_cert: "认证",
    st_current: "在产", st_discontinued: "停产", st_unknown: "状态未知",
    notfound: "未找到匹配型号", notfound_sub: "当前索引覆盖气体分析仪（NOx / SO₂ / O₃ / CO / NH₃ / CO₂·CH₄ 等）。",
    specs: "规格", src_datasheet: "数据表抽取", src_curated: "人工整理", no_specs: "暂无规格数据",
    datasheet: "厂商数据表", aliases: "文献别名",
    market: "二手行情", market_desc: "实时行情无公共 API，直接在市场搜索：",
    usage: "使用画像", u_papers: "检索到论文", u_papers_sub: "方法节匹配", u_evidence: "含证据句", u_inst: "使用机构",
    ppy: "逐年论文数", fields: "主要领域", insts: "主要机构",
    evidence: "文献证据", found_showing: (a, b) => `检索到 ${a} 篇，展示 ${b}`, methods_tag: "方法节",
    no_snippet: "方法节域匹配（全文无可提取摘句）", no_papers: "未检索到方法节匹配的论文。",
    cov_note: "实时查询 Europe PMC（方法节域）+ OpenAlex；启发式匹配（品牌词共现），未经 LLM 语义复核。开放获取覆盖，计数为真实使用量的下限。",
    cov_note_llm: "已叠加 LLM（GPT-4o-mini）语义复核，过滤掉误报。实时查询 Europe PMC（方法节域）+ OpenAlex。开放获取覆盖，计数为真实使用量的下限。",
    compare: "比较同类", n_models: n => `${n} 个型号`,
    rank_basis: "按实时文献使用量（Europe PMC 方法节命中）、在产状态、合规认证排序",
    matrix: "规格对比矩阵", scroll_hint: "窄屏可左右滑动",
    m_range: "量程", m_lod: "检出限", m_resp: "响应", m_papers: "文献",
    f_mfr: "厂商", f_status: "状态", f_cert: "认证", f_principle: "原理", f_sort: "排序",
    f_all: "全部", f_epa: "有 EPA", f_ccep: "有 CCEP", sort_papers: "文献量↓", sort_name: "型号名",
    clear: "清除筛选", showing_n: (a, b) => `显示 ${a} / ${b} 个型号`,
    loading: "加载中…", p_epmc: "查 Europe PMC", p_snippet: "抽取方法节证据句", p_oa: "OpenAlex 富化…",
    p_rank: (i, n, m) => `实时排序：查文献量 ${i}/${n}（${m}）`, live: "实时", lit_vol: "文献量",
    principle: "原理", lod: "检出限",
  },
  en: {
    tagline: "instrument procurement intel", search_ph: "Search a model (42i, T200, Serinus 40) or category (NOx analyzer)…",
    hero_title: "From “which instrument” to “evidence-backed”",
    hero_desc: "Gas-analyzer specs and certifications, alongside the real published papers that actually used each model — with Methods-section evidence, fetched live.",
    flow_1: "pick a model", flow_2: "see the evidence", flow_3: "compare peers", flow_4: "justify the purchase",
    t_models: "models indexed", t_cats: "categories", t_epa: "EPA-certified", t_live: "live", t_live_l: "literature over the wire",
    browse: "Browse by category", featured: "Common models (click for live literature)",
    c_model: "Model", c_category: "Category", c_status: "Status", c_cert: "Cert",
    st_current: "Current", st_discontinued: "Discontinued", st_unknown: "Unknown",
    notfound: "No matching model found", notfound_sub: "The index currently covers gas analyzers (NOx / SO₂ / O₃ / CO / NH₃ / CO₂·CH₄ …).",
    specs: "Specifications", src_datasheet: "from datasheet", src_curated: "curated", no_specs: "No spec data yet",
    datasheet: "Manufacturer datasheet", aliases: "Aliases",
    market: "Secondhand market", market_desc: "No public API for live listings — search the marketplaces directly:",
    usage: "Usage profile", u_papers: "papers found", u_papers_sub: "Methods-scoped", u_evidence: "with evidence", u_inst: "institutions",
    ppy: "Papers per year", fields: "Top fields", insts: "Top institutions",
    evidence: "Literature evidence", found_showing: (a, b) => `${a} found, showing ${b}`, methods_tag: "Methods",
    no_snippet: "Methods-scoped match (no extractable sentence in full text)", no_papers: "No Methods-scoped matches found.",
    cov_note: "Live query of Europe PMC (Methods-scoped) + OpenAlex; heuristic matching (brand-token co-occurrence), not LLM-verified. Open-access coverage — counts are a lower bound on real usage.",
    cov_note_llm: "With LLM (GPT-4o-mini) semantic verification filtering out false positives. Live query of Europe PMC (Methods-scoped) + OpenAlex. Open-access coverage — counts are a lower bound.",
    compare: "Compare peers", n_models: n => `${n} models`,
    rank_basis: "Ranked by live literature volume (Europe PMC Methods hits), production status, and compliance certification",
    matrix: "Spec comparison matrix", scroll_hint: "scroll horizontally on narrow screens",
    m_range: "Range", m_lod: "LOD", m_resp: "Resp.", m_papers: "Papers",
    f_mfr: "Manufacturer", f_status: "Status", f_cert: "Cert", f_principle: "Principle", f_sort: "Sort",
    f_all: "All", f_epa: "Has EPA", f_ccep: "Has CCEP", sort_papers: "Literature↓", sort_name: "Name",
    clear: "Clear filters", showing_n: (a, b) => `Showing ${a} of ${b} models`,
    loading: "Loading…", p_epmc: "Querying Europe PMC", p_snippet: "Extracting Methods sentences", p_oa: "OpenAlex enrichment…",
    p_rank: (i, n, m) => `Live ranking: literature volume ${i}/${n} (${m})`, live: "Live", lit_vol: "papers",
    principle: "Principle", lod: "LOD",
  },
};
function t(key, ...args) { const v = I18N[LANG][key]; return typeof v === "function" ? v(...args) : (v ?? key); }

const CAT_ZH = {
  "NOx analyzer": "NOx 分析仪", "NO2 analyzer": "NO₂ 分析仪", "SO2 analyzer": "SO₂ 分析仪",
  "O3 analyzer": "O₃ 分析仪", "CO analyzer": "CO 分析仪", "NH3 analyzer": "NH₃ 分析仪",
  "CO2/CH4 analyzer": "CO₂/CH₄ 分析仪", "H2S analyzer": "H₂S 分析仪", "THC/VOC analyzer": "THC/VOC 分析仪",
  "multi-gas analyzer": "多组分分析仪", "calibrator": "校准仪",
};
const catLabel = c => LANG === "zh" ? (CAT_ZH[c] || c || "") : (c || "");
function statusLabel(s) { return t("st_" + (s || "unknown")) || t("st_unknown"); }

const CATEGORIES = ["NOx analyzer", "NO2 analyzer", "SO2 analyzer", "O3 analyzer", "CO analyzer",
  "NH3 analyzer", "CO2/CH4 analyzer", "H2S analyzer", "THC/VOC analyzer", "multi-gas analyzer", "calibrator"];
const CAT_KEYWORD = {
  "NOx analyzer": "NOx", "NO2 analyzer": "NO2", "SO2 analyzer": "SO2", "O3 analyzer": "ozone",
  "CO analyzer": "carbon monoxide", "NH3 analyzer": "ammonia", "CO2/CH4 analyzer": "methane",
  "H2S analyzer": "hydrogen sulfide", "THC/VOC analyzer": "hydrocarbon", "multi-gas analyzer": "analyzer", "calibrator": "calibrator",
};
const BRAND_TOKENS = ["thermo", "tei", "teco", "teledyne", "api", "tapi", "ecotech", "acoem", "horiba", "envea",
  "environnement", "picarro", "aerodyne", "2b", "ecophysics", "eco physics", "los gatos", "lgr", "abb",
  "focused photonics", "fpi", "serinus", "sailhero", "monitor labs", "dasibi", "sabio", "environics",
  "aeroqual", "vaisala", "li-cor", "licor", "fuji", "siemens", "雪迪龙", "先河", "聚光", "崂应"];

let SEED = [], seedReady = null;
async function loadSeed() { if (seedReady) return seedReady; seedReady = fetch("data/instruments.json").then(r => r.json()).then(d => { SEED = d; return d; }); return seedReady; }

/* ---------------- fuzzy resolution ---------------- */
const norm = s => String(s).toLowerCase().replace(/[^a-z0-9一-鿿]+/g, " ").trim();
function ratio(a, b) {
  if (a === b) return 1; if (a.length < 2 || b.length < 2) return 0;
  const bg = s => { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const g = s.slice(i, i + 2); m.set(g, (m.get(g) || 0) + 1); } return m; };
  const A = bg(a), B = bg(b); let inter = 0, total = 0;
  for (const [g, n] of A) { total += n; if (B.has(g)) inter += Math.min(n, B.get(g)); }
  for (const n of B.values()) total += n; return (2 * inter) / total;
}
function resolveInstrument(query, limit = 5) {
  const q = norm(query); if (!q) return [];
  const qTok = new Set(q.split(" ")); const scored = [];
  for (const inst of SEED) {
    const names = [inst.model, ...(inst.model_aliases || [])];
    const combos = names.concat(names.map(n => `${inst.manufacturer} ${n}`));
    let best = 0, bestName = inst.model; const modelN = norm(inst.model);
    for (const name of combos) {
      const n = norm(name); let score = ratio(q, n);
      const nTok = new Set(n.split(" ")); const shared = [...qTok].filter(x => nTok.has(x));
      if (shared.length) score = Math.max(score, 0.35 + 0.65 * shared.length / new Set([...qTok, ...nTok]).size);
      if (modelN && q.split(" ").includes(modelN)) score = Math.max(score, 0.9);
      if (score > best) { best = score; bestName = name; }
    }
    if (best >= 0.35) scored.push({ inst, score: +best.toFixed(3), matched: bestName });
  }
  scored.sort((a, b) => b.score - a.score); return scored.slice(0, limit);
}
function resolveCategory(query) {
  const x = query.toLowerCase().replace("analyser", "analyzer");
  for (const c of CATEGORIES) if (x === c.toLowerCase()) return c;
  const map = [["nox", "NOx analyzer"], ["no2", "NO2 analyzer"], ["so2", "SO2 analyzer"], ["ozone", "O3 analyzer"], ["o3", "O3 analyzer"],
    ["carbon monoxide", "CO analyzer"], ["co ", "CO analyzer"], ["nh3", "NH3 analyzer"], ["ammonia", "NH3 analyzer"],
    ["ch4", "CO2/CH4 analyzer"], ["methane", "CO2/CH4 analyzer"], ["co2", "CO2/CH4 analyzer"], ["h2s", "H2S analyzer"],
    ["voc", "THC/VOC analyzer"], ["hydrocarbon", "THC/VOC analyzer"], ["multi", "multi-gas analyzer"], ["calibrat", "calibrator"], ["校准", "calibrator"]];
  if (/analy[sz]er|分析仪|校准/.test(x)) for (const [k, c] of map) if (x.includes(k)) return c;
  return null;
}

/* ---------------- literature queries (unchanged core) ---------------- */
const hasBrand = a => { const s = a.toLowerCase(); return BRAND_TOKENS.some(x => s.includes(x)); };
const brandWord = m => m.split(/\s+/)[0].replace(/[(),]/g, "");
function epmcQueries(inst) {
  const aliases = [inst.model, ...(inst.model_aliases || [])]; const brand = brandWord(inst.manufacturer);
  const kw = CAT_KEYWORD[inst.category] || "analyzer"; const out = []; const seen = new Set();
  // an alias is "brand-qualified" if it carries a global brand token OR any
  // >=3-char word from this instrument's own manufacturer name — a specific
  // phrase query on it is low-noise; bare generic model names ("1600", "405 nm")
  // are not and get a co-occurrence constraint instead.
  const mfrTokens = inst.manufacturer.toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length >= 3 && !["ltd", "inc", "the", "and", "gmbh", "corp"].includes(w));
  const qualified = a => { const s = a.toLowerCase(); return hasBrand(a) || mfrTokens.some(tkn => s.includes(tkn)); };
  for (let a of aliases) {
    a = a.trim(); if (!a || seen.has(a.toLowerCase())) continue; seen.add(a.toLowerCase());
    const bq = qualified(a);
    const q = bq ? `METHODS:"${a}"` : `METHODS:"${a}" AND (METHODS:"${brand}" OR METHODS:"${kw}")`;
    out.push({ alias: a, q, brand: bq });
  }
  return out;
}
async function jget(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${r.status}`); return r.json(); }
/* Prefer brand-qualified phrase queries (e.g. "Thermo 42i", "2B Technologies
   Model 405 nm") — they are specific and low-noise. Bare generic model names
   ("405 nm", "2B") blow up on coincidental matches, so fall back to them only
   when no brand alias exists. */
function selectQueries(inst) { const qs = epmcQueries(inst); const b = qs.filter(x => x.brand); return b.length ? b : qs; }
async function epmcCount(inst) {
  let total = 0;
  for (const { q } of selectQueries(inst).slice(0, 4)) {
    try { const d = await jget(`${EPMC}/search?query=${encodeURIComponent(q)}&format=json&pageSize=1&resultType=lite`); total = Math.max(total, d.hitCount || 0); } catch (e) { }
  }
  return total;
}
const SENT_SPLIT = /(?<=[.!?])\s+(?=[A-Z(])/;
function aliasRegex(alias) { const parts = alias.trim().split(/[\s-]+/).filter(Boolean).map(p => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")); return new RegExp(`(?<![A-Za-z0-9])${parts.join("[\\s-]?")}(?![A-Za-z0-9])`, "i"); }
function cleanTitle(s) { if (!s) return ""; const un = s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#x?\d+;/g, ""); return un.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim(); }
const INST_RE = /(univ|institut|laborator|academ|college|centre|center|ministry|school|hochschule|politecnic|CNRS|CSIRO|CAS|CSIC|Max Planck|Helmholtz)/i;
function extractInstitution(aff) { if (!aff) return null; const parts = aff.split(/[,;]/).map(s => s.trim()).filter(Boolean); const org = parts.find(p => INST_RE.test(p) && p.length <= 60); return (org || parts[1] || parts[0] || "").replace(/\.$/, "").slice(0, 55) || null; }
function epmcAffiliations(h) { const affs = []; const add = a => { const i = extractInstitution(a); if (i && !affs.includes(i)) affs.push(i); }; for (const au of (h.authorList?.author || [])) { for (const d of (au.authorAffiliationDetailsList?.authorAffiliation || [])) add(d.affiliation); if (au.affiliation) add(au.affiliation); } if (h.affiliation) add(h.affiliation); return affs.slice(0, 10); }
async function fetchMethodsSnippet(pmcid, aliases) {
  try {
    const r = await fetch(`${EPMC}/${pmcid}/fullTextXML`); if (!r.ok) return null;
    const xml = new DOMParser().parseFromString(await r.text(), "text/xml"); const res = [...aliases].map(a => aliasRegex(a)); let fallback = null;
    for (const sec of xml.querySelectorAll("sec")) {
      const title = (sec.querySelector(":scope > title")?.textContent || "").toLowerCase();
      const isMethods = /method|material|experimental|instrument|measurement|sampling|site/.test(title);
      for (const p of sec.querySelectorAll("p")) {
        const txt = p.textContent || ""; const re = res.find(rx => rx.test(txt)); if (!re) continue;
        for (const sent of txt.split(SENT_SPLIT)) { if (!re.test(sent)) continue; const snip = sent.replace(/\s+/g, " ").trim().slice(0, 600); if (isMethods) return { snippet: snip, section: "methods" }; if (!fallback) fallback = { snippet: snip, section: "fulltext" }; }
      }
    }
    return fallback;
  } catch (e) { return null; }
}
async function pool(items, worker, concurrency = 4) { const out = new Array(items.length); let idx = 0; await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => { while (idx < items.length) { const i = idx++; out[i] = await worker(items[i], i); } })); return out; }
async function searchLiterature(inst, onProgress) {
  const byKey = new Map(); const queries = selectQueries(inst); let done = 0;
  for (const { alias, q, brand } of queries) {
    onProgress && onProgress(`${t("p_epmc")}: ${alias}`, done / (queries.length + 2)); done++;
    let hits = []; try { const d = await jget(`${EPMC}/search?query=${encodeURIComponent(q)}&format=json&pageSize=40&resultType=core`); hits = (d.resultList && d.resultList.result) || []; } catch (e) { continue; }
    const re = aliasRegex(alias);
    for (const h of hits) {
      const key = (h.doi || h.pmcid || h.pmid || h.id || "").toLowerCase(); if (!key) continue;
      let c = byKey.get(key);
      if (!c) { c = { doi: h.doi || null, pmid: h.pmid || null, pmcid: h.pmcid || null, title: cleanTitle(h.title), year: h.pubYear ? +h.pubYear : null, venue: h.journalTitle || null, evidence: null, section: null, brand, source: "europepmc", fields: (h.keywordList?.keyword || []).slice(0, 4), affiliations: epmcAffiliations(h), citations: h.citedByCount ?? null }; byKey.set(key, c); }
      c.brand = c.brand || brand;
      if (!c.evidence && h.abstractText && re.test(h.abstractText)) { for (const sent of h.abstractText.split(SENT_SPLIT)) { if (re.test(sent)) { c.evidence = sent.trim().slice(0, 600); c.section = "abstract"; break; } } }
    }
  }
  const cands = [...byKey.values()];
  const dois = cands.filter(c => c.doi).map(c => c.doi.toLowerCase().replace("https://doi.org/", ""));
  onProgress && onProgress(t("p_oa"), queries.length / (queries.length + 2));
  if (dois.length) {
    for (let i = 0; i < dois.length; i += 50) {
      const chunk = dois.slice(i, i + 50).filter(d => !d.includes(",") && !d.includes("|")); if (!chunk.length) continue;
      try {
        const d = await jget(`${OPENALEX}/works?filter=doi:${chunk.join("|")}&per-page=50&mailto=${MAILTO}&select=doi,primary_topic,authorships,primary_location,cited_by_count`);
        const byDoi = new Map(); for (const w of d.results || []) { if (w.doi) byDoi.set(w.doi.toLowerCase().replace("https://doi.org/", ""), w); }
        for (const c of cands) { const w = c.doi && byDoi.get(c.doi.toLowerCase().replace("https://doi.org/", "")); if (!w) continue; if (!c.fields.length && w.primary_topic) c.fields = [w.primary_topic.display_name, w.primary_topic.subfield?.display_name, w.primary_topic.field?.display_name].filter(Boolean); if (!c.affiliations.length) { const affs = []; for (const a of (w.authorships || []).slice(0, 25)) for (const ins of a.institutions || []) if (ins.display_name && !affs.includes(ins.display_name)) affs.push(ins.display_name); c.affiliations = affs.slice(0, 10); } if (c.citations == null) c.citations = w.cited_by_count; if (!c.venue && w.primary_location?.source?.display_name) c.venue = w.primary_location.source.display_name; }
      } catch (e) { }
    }
  }
  const aliases = [inst.model, ...(inst.model_aliases || [])];
  const needText = cands.filter(c => c.pmcid && !c.evidence).slice(0, 14); let ftDone = 0;
  await pool(needText, async (c) => { onProgress && onProgress(`${t("p_snippet")} ${++ftDone}/${needText.length}`, (queries.length + 1 + ftDone / Math.max(1, needText.length)) / (queries.length + 3)); const s = await fetchMethodsSnippet(c.pmcid, aliases); if (s) { c.evidence = s.snippet; c.section = s.section; } }, 4);
  for (const c of cands) { if (c.evidence && c.section === "methods") c.confidence = 0.95; else if (c.evidence) c.confidence = c.brand ? 0.9 : 0.82; else c.confidence = c.brand ? 0.75 : 0.65; if (!c.section) c.section = "methods"; }
  cands.sort((a, b) => (b.confidence - a.confidence) || ((b.year || 0) - (a.year || 0)));
  onProgress && onProgress("", 1); return cands;
}
/* Optional server-side LLM disambiguation. Calls /api/disambiguate (a Vercel
   function holding the OpenAI key server-side). If it's not deployed / not
   configured, this silently no-ops and the heuristic stands — so the static
   site works with or without it. */
async function llmDisambiguate(inst, cands) {
  const withEv = cands.filter(c => c.evidence);
  if (!withEv.length) return false;
  const items = withEv.map((c, i) => ({ idx: i, evidence: c.evidence }));
  try {
    const r = await fetch("/api/disambiguate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: `${inst.manufacturer} ${inst.model} (${inst.principle || "gas analyzer"})`, items }),
    });
    if (!r.ok) return false;                     // 503 not configured / 404 static-only → keep heuristic
    const { results } = await r.json();
    if (!Array.isArray(results)) return false;
    for (const v of results) {
      const c = withEv[v.idx]; if (!c) continue;
      if (v.used === false) { c.confidence = Math.min(c.confidence, 0.2); c.llm_rejected = true; }
      else { c.llm_verified = true; }
    }
    cands.sort((a, b) => (b.confidence - a.confidence) || ((b.year || 0) - (a.year || 0)));
    return true;
  } catch (e) { return false; }
}

function aggregateUsage(cands) {
  cands = cands.filter(c => !c.llm_rejected);

  const byYear = {}, fields = {}, insts = {}, venues = {};
  for (const c of cands) { if (c.year) byYear[c.year] = (byYear[c.year] || 0) + 1; for (const f of c.fields) fields[f] = (fields[f] || 0) + 1; for (const a of c.affiliations.slice(0, 5)) insts[a] = (insts[a] || 0) + 1; if (c.venue) venues[c.venue] = (venues[c.venue] || 0) + 1; }
  const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n).map(([name, papers]) => ({ name, papers }));
  return { byYear, topFields: top(fields, 5), topInstitutions: top(insts, 8) };
}
const cacheGet = k => { try { const v = sessionStorage.getItem(k); return v ? JSON.parse(v) : null; } catch { return null; } };
const cacheSet = (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch { } };

/* ---------------- shared UI bits ---------------- */
const progressBox = (label, frac) => app().innerHTML = `<div class="empty"><span class="spin"></span> ${esc(label)}<div style="max-width:320px;margin:1rem auto 0;height:4px;background:var(--line);border-radius:2px;overflow:hidden"><div style="height:100%;width:${Math.round(frac * 100)}%;background:var(--accent);transition:width .2s"></div></div></div>`;
const loading = () => app().innerHTML = `<div class="empty"><span class="spin"></span> ${esc(t("loading"))}</div>`;
function crumbs(parts) { return `<div class="crumbs">` + parts.map((p, i) => i < parts.length - 1 ? `<a onclick="${p.go}">${esc(p.label)}</a><span>›</span>` : `<span style="color:var(--ink-2)">${esc(p.label)}</span>`).join("") + `</div>`; }
function statusBadge(s) { if (s === "current") return `<span class="badge good"><span class="dot"></span>${esc(t("st_current"))}</span>`; if (s === "discontinued") return `<span class="badge mut"><span class="dot"></span>${esc(t("st_discontinued"))}</span>`; return `<span class="badge mut">${esc(t("st_unknown"))}</span>`; }
const INFO = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>`;
const coverage = txt => `<div class="note">${INFO}<span>${esc(txt)}</span></div>`;
const LIVE = `<span class="live"><span class="live-dot"></span>${esc(I18N[LANG].live)}</span>`;
function trendChart(byYear) {
  const years = Object.keys(byYear).sort(); if (!years.length) return "";
  const W = 520, H = 130, padB = 22, padL = 4, padT = 8; const max = Math.max(...years.map(y => byYear[y]));
  const bw = (W - padL * 2) / years.length, barW = Math.max(6, Math.min(38, bw - 8));
  const bars = years.map((y, i) => { const v = byYear[y], bh = Math.max(2, (H - padB - padT) * v / max); const x = padL + i * bw + (bw - barW) / 2, yy = H - padB - bh; const show = years.length <= 12 || i % 2 === 0; return `<rect class="bar" x="${x.toFixed(1)}" y="${yy.toFixed(1)}" width="${barW.toFixed(1)}" height="${bh.toFixed(1)}" rx="3" data-y="${y}" data-v="${v}"></rect>` + (show ? `<text x="${(x + barW / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle">${y.slice(2)}</text>` : ""); }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" onmousemove="barHover(event)" onmouseleave="hideTip()">${bars}</svg></div>`;
}
window.barHover = e => { const r = e.target.closest(".bar"); const tt = $("#tt"); if (!r) { tt.style.opacity = 0; return; } tt.textContent = `${r.dataset.y}: ${r.dataset.v}`; tt.style.left = (e.clientX + 12) + "px"; tt.style.top = (e.clientY - 12) + "px"; tt.style.opacity = 1; };
window.hideTip = () => $("#tt").style.opacity = 0;

/* ---------------- router ---------------- */
window.goHome = () => { location.hash = ""; };
window.go = (view, arg) => { location.hash = view + (arg ? "/" + encodeURIComponent(arg) : ""); };
async function route() {
  await loadSeed();
  const h = decodeURIComponent(location.hash.replace(/^#/, "")); const [view, ...rest] = h.split("/"); const arg = rest.join("/");
  if (view === "model") return renderModel(arg);
  if (view === "category") return renderCategory(arg);
  return renderHome();
}

/* ---------------- home ---------------- */
function renderHome() {
  const cats = {}; for (const i of SEED) cats[i.category] = (cats[i.category] || 0) + 1;
  const catList = Object.entries(cats).sort((a, b) => b[1] - a[1]);
  const featured = ["42i", "T200", "Serinus 40", "APNA-370", "G2401", "205"].map(m => SEED.find(i => i.model === m)).filter(Boolean);
  app().innerHTML = `
    <div class="hero">
      <h1>${esc(t("hero_title"))}</h1>
      <p>${esc(t("hero_desc"))}</p>
      <div class="flow"><b>${esc(t("flow_1"))}</b> → <span>${esc(t("flow_2"))}</span> → <span>${esc(t("flow_3"))}</span> → <b>${esc(t("flow_4"))}</b></div>
      <div class="bigsearch">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input id="bq" placeholder="${esc(t("search_ph"))}" autocomplete="off">
      </div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="n tnum">${SEED.length}</div><div class="l">${esc(t("t_models"))}</div></div>
      <div class="tile"><div class="n tnum">${catList.length}</div><div class="l">${esc(t("t_cats"))}</div></div>
      <div class="tile"><div class="n tnum">${SEED.filter(i => i.epa_designation).length}</div><div class="l">${esc(t("t_epa"))}</div></div>
      <div class="tile"><div class="n" style="color:var(--accent)">${esc(t("t_live"))}</div><div class="l">${esc(t("t_live_l"))}</div></div>
    </div>
    <div class="card">
      <h3>${esc(t("browse"))}</h3>
      <div class="chips">${catList.map(([c, n]) => `<span class="chip" onclick="go('category','${esc(c)}')">${esc(catLabel(c))}<span class="c tnum">${n}</span></span>`).join("")}</div>
    </div>
    <div class="card">
      <h3>${esc(t("featured"))}</h3>
      <div class="list">${featured.map(m => `<div class="item"><div class="item-head"><a class="item-title" onclick="go('model','${esc(m.model)}')">${esc(m.manufacturer)} ${esc(m.model)}</a></div><div class="item-meta">${esc(catLabel(m.category))}<span class="sep">·</span>${statusBadge(m.status)}${m.epa_designation ? `<span class="badge epa">EPA</span>` : ""}</div></div>`).join("")}</div>
    </div>`;
  const bq = document.getElementById("bq");
  if (bq) bq.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(e.target.value); });
}

/* ---------------- category (OpenAlex-style facets + list) ---------------- */
let CAT_STATE = { cat: null, ranked: null, facet: { mfr: "", status: "", cert: "", principle: "", sort: "papers" } };
window.setFacet = (k, v) => { CAT_STATE.facet[k] = v; drawCategory(); };
window.clearFacets = () => { CAT_STATE.facet = { mfr: "", status: "", cert: "", principle: "", sort: "papers" }; drawCategory(); };

async function renderCategory(cat) {
  await loadSeed();
  const models = SEED.filter(i => (i.category || "") === cat);
  if (!models.length) { app().innerHTML = crumbs([{ label: "LabScope", go: "goHome()" }, { label: catLabel(cat) }]) + `<div class="card empty">—</div>`; return; }
  CAT_STATE.cat = cat;
  if (CAT_STATE.rankedFor !== cat) CAT_STATE.ranked = null;
  let ranked = CAT_STATE.ranked || cacheGet("rank:" + cat);
  if (!ranked) {
    ranked = [];
    for (let i = 0; i < models.length; i++) { progressBox(t("p_rank", i + 1, models.length, models[i].model), i / models.length); const n = await epmcCount(models[i]); ranked.push({ model: models[i].model, count: n }); }
    cacheSet("rank:" + cat, ranked);
  }
  CAT_STATE.ranked = ranked; CAT_STATE.rankedFor = cat;
  CAT_STATE.facet = { mfr: "", status: "", cert: "", principle: "", sort: "papers" };
  drawCategory();
}

function drawCategory() {
  const cat = CAT_STATE.cat; const f = CAT_STATE.facet;
  const models = SEED.filter(i => (i.category || "") === cat);
  const countOf = m => (CAT_STATE.ranked.find(r => r.model === m.model) || {}).count || 0;

  const mfrs = [...new Set(models.map(m => m.manufacturer))].sort();
  const principles = [...new Set(models.map(m => m.principle).filter(Boolean))].sort();

  let rows = models.slice();
  if (f.mfr) rows = rows.filter(m => m.manufacturer === f.mfr);
  if (f.status) rows = rows.filter(m => (m.status || "unknown") === f.status);
  if (f.cert === "epa") rows = rows.filter(m => m.epa_designation);
  if (f.cert === "ccep") rows = rows.filter(m => m.ccep_designation);
  if (f.principle) rows = rows.filter(m => m.principle === f.principle);
  if (f.sort === "name") rows.sort((a, b) => (a.manufacturer + a.model).localeCompare(b.manufacturer + b.model));
  else rows.sort((a, b) => countOf(b) - countOf(a));

  const opt = (val, label, sel) => `<option value="${esc(val)}"${sel === val ? " selected" : ""}>${esc(label)}</option>`;
  const facetSel = (key, cur, allLabel, opts) => `<div class="facet${cur ? " on" : ""}"><select onchange="setFacet('${key}',this.value)">${opt("", allLabel, cur)}${opts.map(o => opt(o.v, o.l, cur)).join("")}</select></div>`;
  const active = f.mfr || f.status || f.cert || f.principle;

  const facetBar = `<div class="facets">
    ${facetSel("mfr", f.mfr, t("f_mfr"), mfrs.map(m => ({ v: m, l: m })))}
    ${facetSel("status", f.status, t("f_status"), [{ v: "current", l: t("st_current") }, { v: "discontinued", l: t("st_discontinued") }])}
    ${facetSel("cert", f.cert, t("f_cert"), [{ v: "epa", l: t("f_epa") }, { v: "ccep", l: t("f_ccep") }])}
    ${facetSel("principle", f.principle, t("f_principle"), principles.map(p => ({ v: p, l: p })))}
    <div class="facet"><select onchange="setFacet('sort',this.value)">${opt("papers", t("sort_papers"), f.sort)}${opt("name", t("sort_name"), f.sort)}</select></div>
    ${active ? `<button class="clearf" onclick="clearFacets()">✕ ${esc(t("clear"))}</button>` : ""}
  </div>`;

  const list = rows.map(m => {
    const n = countOf(m); const s = m.specs || {};
    const metaBits = [catLabel(m.category), m.principle, s.lod ? `${t("lod")} ${s.lod}` : null].filter(Boolean);
    return `<div class="item"><div class="item-head">
        <a class="item-title" onclick="go('model','${esc(m.model)}')">${esc(m.manufacturer)} ${esc(m.model)}</a>
        <span class="item-right">${LIVE} <span class="tnum">${n}</span> ${esc(t("lit_vol"))}</span>
      </div>
      <div class="item-meta">${statusBadge(m.status)}${m.epa_designation ? `<span class="badge epa">EPA</span>` : ""}${m.ccep_designation ? `<span class="badge epa">CCEP</span>` : ""}<span>${metaBits.map(esc).join(' <span class="sep">·</span> ')}</span></div>
    </div>`;
  }).join("");

  app().innerHTML =
    crumbs([{ label: "LabScope", go: "goHome()" }, { label: catLabel(cat) }])
    + `<div class="card">
        <h2>${esc(catLabel(cat))}</h2>
        <div class="sub" style="margin-bottom:.9rem">${esc(t("rank_basis"))}</div>
        ${facetBar}
        <div class="rescount">${esc(t("showing_n", rows.length, models.length))}</div>
        <div class="list">${list || `<div class="empty">—</div>`}</div>
        ${coverage(t("cov_note"))}
      </div>`;
}

/* ---------------- model detail ---------------- */
async function renderModel(q) {
  await loadSeed();
  const matches = resolveInstrument(q, 4);
  if (!matches.length) { app().innerHTML = crumbs([{ label: "LabScope", go: "goHome()" }, { label: q }]) + `<div class="card empty">${esc(t("notfound"))}「${esc(q)}」<br><span class="sub">${esc(t("notfound_sub"))}</span></div>`; return; }
  const m0 = matches[0], inst = m0.inst, fuzzy = m0.score < 0.85; const name = `${inst.manufacturer} ${inst.model}`;
  const cacheKey = "lit:" + name; let cands = cacheGet(cacheKey);
  if (!cands) {
    cands = await searchLiterature(inst, (label, frac) => progressBox(label, frac));
    cands._llm = await llmDisambiguate(inst, cands);   // no-op if endpoint absent
    cacheSet(cacheKey, cands);
  }
  const llmOn = !!cands._llm;
  const visible = cands.filter(c => !c.llm_rejected);
  const usage = aggregateUsage(cands); const shown = visible.slice(0, 25); const s = inst.specs || {};
  const specRows = Object.entries(s).filter(([, v]) => v != null && v !== "").map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  const methodsN = visible.filter(c => c.evidence).length;
  const covNote = llmOn ? t("cov_note_llm") : t("cov_note");
  const llmBadge = llmOn ? ` <span class="badge epa" title="LLM">✓ LLM</span>` : "";
  const q2 = encodeURIComponent(brandWord(inst.manufacturer) + " " + inst.model);
  const labxUrl = `https://www.labx.com/search?q=${q2}`, ebayUrl = `https://www.ebay.com/sch/i.html?_nkw=${q2}`;

  app().innerHTML =
    crumbs([{ label: "LabScope", go: "goHome()" }, { label: catLabel(inst.category), go: `go('category','${esc(inst.category)}')` }, { label: name }])
    + `<div class="card"><div class="detail-head">
        <div><h1 class="title">${esc(name)}</h1>
          <div class="meta">${statusBadge(inst.status)}<span class="pill">${esc(inst.category || "")}</span><span class="pill">${esc(inst.principle || "")}</span>${inst.epa_designation ? `<span class="badge epa">EPA ${esc(inst.epa_designation)}</span>` : ""}${inst.ccep_designation ? `<span class="badge epa">CCEP</span>` : ""}${fuzzy ? `<span class="badge mut">~ ${m0.score}</span>` : ""}</div>
        </div>
        <button class="btn primary" onclick="go('category','${esc(inst.category)}')">${esc(t("compare"))} →</button>
      </div></div>
      <div class="cols">
        <div>
          <div class="card">
            <h3>${esc(t("specs"))} · ${esc(inst.specs_provenance === "datasheet" ? t("src_datasheet") : t("src_curated"))}</h3>
            <div class="tablewrap"><table class="kv">${specRows || `<tr><td class="sub">${esc(t("no_specs"))}</td></tr>`}</table></div>
            ${inst.datasheet_url ? `<div style="margin-top:.7rem"><a href="${esc(inst.datasheet_url)}" target="_blank" rel="noopener">${esc(t("datasheet"))} →</a></div>` : ""}
            ${inst.model_aliases?.length ? `<div class="sub" style="margin-top:.7rem">${esc(t("aliases"))}: ${inst.model_aliases.map(esc).join(" · ")}</div>` : ""}
          </div>
          <div class="card"><h3>${esc(t("market"))}</h3><div class="sub">${esc(t("market_desc"))}</div>
            <div style="margin-top:.6rem;display:flex;gap:.5rem;flex-wrap:wrap"><a class="btn" href="${esc(labxUrl)}" target="_blank" rel="noopener">LabX →</a><a class="btn" href="${esc(ebayUrl)}" target="_blank" rel="noopener">eBay →</a></div>
          </div>
        </div>
        <div>
          <div class="card"><h3>${esc(t("usage"))} ${LIVE}</h3>
            <div class="stat-row">
              <div class="stat"><div class="n tnum">${visible.length}</div><div class="l">${esc(t("u_papers"))}<br>${esc(t("u_papers_sub"))}</div></div>
              <div class="stat"><div class="n tnum">${methodsN}</div><div class="l">${esc(t("u_evidence"))}</div></div>
              <div class="stat"><div class="n tnum">${usage.topInstitutions.length}</div><div class="l">${esc(t("u_inst"))}</div></div>
            </div>
            ${Object.keys(usage.byYear).length ? `<div style="margin-top:1rem"><div class="sub" style="margin-bottom:.3rem">${esc(t("ppy"))}</div>${trendChart(usage.byYear)}</div>` : ""}
            ${usage.topFields.length ? `<div style="margin-top:1rem"><div class="sub" style="margin-bottom:.4rem">${esc(t("fields"))}</div><div class="taglist">${usage.topFields.map(x => `<span class="pill">${esc(x.name)} · ${x.papers}</span>`).join("")}</div></div>` : ""}
            ${usage.topInstitutions.length ? `<div style="margin-top:.9rem"><div class="sub" style="margin-bottom:.4rem">${esc(t("insts"))}</div><div class="taglist">${usage.topInstitutions.map(x => `<span class="pill">${esc(x.name)} · ${x.papers}</span>`).join("")}</div></div>` : ""}
          </div>
          <div class="card"><h3>${esc(t("evidence"))} ${LIVE}${llmBadge} · ${esc(t("found_showing", visible.length, shown.length))}</h3>
            <div class="papers">${shown.map(p => `<div class="paper"><div class="paper-head"><span class="year tnum">${p.year ?? ""}</span>${p.doi ? `<a class="paper-title" href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : `<span class="paper-title" style="color:var(--ink)">${esc(p.title)}</span>`}<span class="conf-badge tnum">${p.confidence.toFixed(2)}</span></div>
              <div class="paper-meta">${esc(p.venue ?? "")}${(p.fields || []).length ? " · " + (p.fields || []).slice(0, 2).map(esc).join(" · ") : ""}</div>
              ${p.evidence ? `<div class="ev">“${esc(p.evidence)}”${p.section === "methods" ? ` <span class="ev-src">— ${esc(t("methods_tag"))}</span>` : ""}${p.llm_verified ? ` <span class="ev-src" style="color:var(--accent)">✓ LLM</span>` : ""}</div>` : `<div class="ev-src">${esc(t("no_snippet"))}</div>`}</div>`).join("") || `<div class="sub">${esc(t("no_papers"))}</div>`}</div>
            ${coverage(covNote)}
          </div>
        </div>
      </div>`;
}

/* ---------------- search + language + theme ---------------- */
function doSearch(raw) { const q = (raw || "").trim(); if (!q) return; const cat = resolveCategory(q); if (cat) go("category", cat); else go("model", q); }
function applyStaticText() {
  document.documentElement.lang = LANG;
  $("#q").placeholder = t("search_ph");
  document.querySelectorAll("[data-i18n]").forEach(el => el.textContent = t(el.getAttribute("data-i18n")));
  $("#langBtn").textContent = LANG === "zh" ? "EN" : "中文";
}
window.addEventListener("hashchange", route);
document.addEventListener("DOMContentLoaded", () => {
  applyStaticText();
  $("#q").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(e.target.value); });
  $("#langBtn").onclick = () => { LANG = LANG === "zh" ? "en" : "zh"; localStorage.setItem("labscope_lang", LANG); applyStaticText(); route(); };
  $("#themeBtn").onclick = () => { const cur = document.documentElement.getAttribute("data-theme"); const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; document.documentElement.setAttribute("data-theme", dark ? "light" : "dark"); };
  route();
});
