/* LabScope static front-end — real-time literature queries, no backend.
 *
 *  Instruments (specs/aliases/certs) load from a curated static JSON.
 *  Literature is queried LIVE in the browser against Europe PMC (Methods-scoped)
 *  and OpenAlex (both send `access-control-allow-origin: *`).
 *  Disambiguation is a transparent heuristic — Methods-scoped queries plus
 *  brand-token co-occurrence — no server, no API key.
 */
'use strict';

const EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest";
const OPENALEX = "https://api.openalex.org";
const MAILTO = "labscope@users.noreply.github.com";   // OpenAlex polite pool
const $ = s => document.querySelector(s);
const app = () => document.getElementById("app");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const CATEGORIES = ["NOx analyzer", "NO2 analyzer", "SO2 analyzer", "O3 analyzer", "CO analyzer",
  "NH3 analyzer", "CO2/CH4 analyzer", "H2S analyzer", "THC/VOC analyzer", "multi-gas analyzer", "calibrator"];
const CAT_ZH = {
  "NOx analyzer": "NOx 分析仪", "NO2 analyzer": "NO₂ 分析仪", "SO2 analyzer": "SO₂ 分析仪",
  "O3 analyzer": "O₃ 分析仪", "CO analyzer": "CO 分析仪", "NH3 analyzer": "NH₃ 分析仪",
  "CO2/CH4 analyzer": "CO₂/CH₄ 分析仪", "H2S analyzer": "H₂S 分析仪", "THC/VOC analyzer": "THC/VOC 分析仪",
  "multi-gas analyzer": "多组分分析仪", "calibrator": "校准仪"
};
const catLabel = c => CAT_ZH[c] || c || "";
const CAT_KEYWORD = {
  "NOx analyzer": "NOx", "NO2 analyzer": "NO2", "SO2 analyzer": "SO2", "O3 analyzer": "ozone",
  "CO analyzer": "carbon monoxide", "NH3 analyzer": "ammonia", "CO2/CH4 analyzer": "methane",
  "H2S analyzer": "hydrogen sulfide", "THC/VOC analyzer": "hydrocarbon",
  "multi-gas analyzer": "analyzer", "calibrator": "calibrator"
};
const BRAND_TOKENS = ["thermo", "tei", "teco", "teledyne", "api", "tapi", "ecotech", "acoem", "horiba",
  "envea", "environnement", "picarro", "aerodyne", "2b", "ecophysics", "eco physics", "los gatos", "lgr",
  "abb", "focused photonics", "fpi", "serinus", "sailhero", "monitor labs", "dasibi", "sabio", "environics",
  "aeroqual", "vaisala", "li-cor", "licor", "fuji", "siemens", "雪迪龙", "先河", "聚光", "崂应"];

let SEED = [];
let seedReady = null;

/* ---------------- data load ---------------- */
async function loadSeed() {
  if (seedReady) return seedReady;
  seedReady = fetch("data/instruments.json").then(r => r.json()).then(d => { SEED = d; return d; });
  return seedReady;
}

/* ---------------- fuzzy model resolution (ported from db.resolve_instrument) --- */
const norm = s => String(s).toLowerCase().replace(/[^a-z0-9一-鿿]+/g, " ").trim();
function ratio(a, b) {                     // Dice bigram similarity (fast, dependency-free)
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return 0;
  const bg = s => { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const g = s.slice(i, i + 2); m.set(g, (m.get(g) || 0) + 1); } return m; };
  const A = bg(a), B = bg(b); let inter = 0, total = 0;
  for (const [g, n] of A) { total += n; if (B.has(g)) inter += Math.min(n, B.get(g)); }
  for (const n of B.values()) total += n;
  return (2 * inter) / total;
}
function resolveInstrument(query, limit = 5) {
  const q = norm(query);
  if (!q) return [];
  const qTok = new Set(q.split(" "));
  const scored = [];
  for (const inst of SEED) {
    const names = [inst.model, ...(inst.model_aliases || [])];
    const combos = names.concat(names.map(n => `${inst.manufacturer} ${n}`));
    let best = 0, bestName = inst.model;
    const modelN = norm(inst.model);
    for (const name of combos) {
      const n = norm(name);
      let score = ratio(q, n);
      const nTok = new Set(n.split(" "));
      const shared = [...qTok].filter(t => nTok.has(t));
      if (shared.length) score = Math.max(score, 0.35 + 0.65 * shared.length / new Set([...qTok, ...nTok]).size);
      if (modelN && q.split(" ").includes(modelN)) score = Math.max(score, 0.9);
      if (score > best) { best = score; bestName = name; }
    }
    if (best >= 0.35) scored.push({ inst, score: +best.toFixed(3), matched: bestName });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit);
}
function resolveCategory(query) {
  const t = query.toLowerCase().replace("analyser", "analyzer");
  for (const c of CATEGORIES) if (t === c.toLowerCase()) return c;
  const map = [["nox", "NOx analyzer"], ["no2", "NO2 analyzer"], ["so2", "SO2 analyzer"],
    ["ozone", "O3 analyzer"], ["o3", "O3 analyzer"], ["carbon monoxide", "CO analyzer"], ["co ", "CO analyzer"],
    ["nh3", "NH3 analyzer"], ["ammonia", "NH3 analyzer"], ["ch4", "CO2/CH4 analyzer"], ["methane", "CO2/CH4 analyzer"],
    ["co2", "CO2/CH4 analyzer"], ["h2s", "H2S analyzer"], ["voc", "THC/VOC analyzer"], ["hydrocarbon", "THC/VOC analyzer"],
    ["multi", "multi-gas analyzer"], ["calibrat", "calibrator"], ["校准", "calibrator"]];
  if (/analy[sz]er|分析仪|校准/.test(t)) for (const [k, c] of map) if (t.includes(k)) return c;
  return null;
}

/* ---------------- literature query helpers ---------------- */
const hasBrand = a => { const s = a.toLowerCase(); return BRAND_TOKENS.some(t => s.includes(t)); };
const brandWord = m => m.split(/\s+/)[0].replace(/[(),]/g, "");

function epmcQueries(inst) {
  const aliases = [inst.model, ...(inst.model_aliases || [])];
  const brand = brandWord(inst.manufacturer);
  const kw = CAT_KEYWORD[inst.category] || "analyzer";
  const out = []; const seen = new Set();
  for (let a of aliases) {
    a = a.trim(); if (!a || seen.has(a.toLowerCase())) continue; seen.add(a.toLowerCase());
    const q = hasBrand(a) ? `METHODS:"${a}"` : `METHODS:"${a}" AND (METHODS:"${brand}" OR METHODS:"${kw}")`;
    out.push({ alias: a, q, brand: hasBrand(a) });
  }
  return out;
}

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

/* count-only query for fast ranking (uses hitCount, pageSize=1) */
async function epmcCount(inst) {
  let total = 0;
  for (const { q } of epmcQueries(inst).slice(0, 3)) {
    try {
      const d = await jget(`${EPMC}/search?query=${encodeURIComponent(q)}&format=json&pageSize=1&resultType=lite`);
      total = Math.max(total, d.hitCount || 0);   // max across aliases ~ dedup proxy
    } catch (e) { /* skip */ }
  }
  return total;
}

const SENT_SPLIT = /(?<=[.!?])\s+(?=[A-Z(])/;
function aliasRegex(alias) {
  const parts = alias.trim().split(/[\s-]+/).filter(Boolean).map(p => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`(?<![A-Za-z0-9])${parts.join("[\\s-]?")}(?![A-Za-z0-9])`, "i");
}
function cleanTitle(t) {
  if (!t) return "";
  // unescape entities FIRST, then strip the revealed markup (e.g. NO<sub>x</sub>)
  const un = t.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#x?\d+;/g, "");
  return un.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

/* pull an organisation name out of a full Europe PMC affiliation string */
const INST_RE = /(univ|institut|laborator|academ|college|centre|center|ministry|school|hochschule|politecnic|CNRS|CSIRO|NOAA|CAS|CSIC|Max Planck|Helmholtz)/i;
function extractInstitution(aff) {
  if (!aff) return null;
  const parts = aff.split(/[,;]/).map(s => s.trim()).filter(Boolean);
  const org = parts.find(p => INST_RE.test(p) && p.length <= 60);
  return (org || parts[1] || parts[0] || "").replace(/\.$/, "").slice(0, 55) || null;
}
function epmcAffiliations(h) {
  const affs = [];
  const add = a => { const i = extractInstitution(a); if (i && !affs.includes(i)) affs.push(i); };
  for (const au of (h.authorList?.author || [])) {
    for (const d of (au.authorAffiliationDetailsList?.authorAffiliation || [])) add(d.affiliation);
    if (au.affiliation) add(au.affiliation);
  }
  if (h.affiliation) add(h.affiliation);
  return affs.slice(0, 10);
}

/* pull a real Methods-section evidence sentence from an OA full text */
async function fetchMethodsSnippet(pmcid, aliases) {
  try {
    const r = await fetch(`${EPMC}/${pmcid}/fullTextXML`);
    if (!r.ok) return null;
    const xml = new DOMParser().parseFromString(await r.text(), "text/xml");
    const res = [...aliases].map(a => aliasRegex(a));
    let fallback = null;
    for (const sec of xml.querySelectorAll("sec")) {
      const title = (sec.querySelector(":scope > title")?.textContent || "").toLowerCase();
      const isMethods = /method|material|experimental|instrument|measurement|sampling|site/.test(title);
      for (const p of sec.querySelectorAll("p")) {
        const txt = p.textContent || "";
        const re = res.find(rx => rx.test(txt));
        if (!re) continue;
        for (const sent of txt.split(SENT_SPLIT)) {
          if (!re.test(sent)) continue;
          const snip = sent.replace(/\s+/g, " ").trim().slice(0, 600);
          if (isMethods) return { snippet: snip, section: "methods" };
          if (!fallback) fallback = { snippet: snip, section: "fulltext" };
        }
      }
    }
    return fallback;
  } catch (e) { return null; }
}

/* small concurrency pool */
async function pool(items, worker, concurrency = 4) {
  const out = new Array(items.length);
  let idx = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (idx < items.length) { const i = idx++; out[i] = await worker(items[i], i); }
  }));
  return out;
}

/* full literature pull for the detail view */
async function searchLiterature(inst, onProgress) {
  const byKey = new Map();
  const queries = epmcQueries(inst);
  let done = 0;
  for (const { alias, q, brand } of queries) {
    onProgress && onProgress(`查 Europe PMC：${alias}`, done / (queries.length + 2));
    done++;
    let hits = [];
    try {
      const d = await jget(`${EPMC}/search?query=${encodeURIComponent(q)}&format=json&pageSize=40&resultType=core`);
      hits = (d.resultList && d.resultList.result) || [];
    } catch (e) { continue; }
    const re = aliasRegex(alias);
    for (const h of hits) {
      const key = (h.doi || h.pmcid || h.pmid || h.id || "").toLowerCase();
      if (!key) continue;
      let c = byKey.get(key);
      if (!c) {
        c = {
          doi: h.doi || null, pmid: h.pmid || null, pmcid: h.pmcid || null,
          title: cleanTitle(h.title), year: h.pubYear ? +h.pubYear : null,
          venue: h.journalTitle || null, evidence: null, section: null,
          brand, source: "europepmc",
          fields: (h.keywordList?.keyword || []).slice(0, 4),
          affiliations: epmcAffiliations(h),
          citations: h.citedByCount ?? null,
        };
        byKey.set(key, c);
      }
      c.brand = c.brand || brand;
      if (!c.evidence && h.abstractText && re.test(h.abstractText)) {
        for (const sent of h.abstractText.split(SENT_SPLIT)) {
          if (re.test(sent)) { c.evidence = sent.trim().slice(0, 600); c.section = "abstract"; break; }
        }
      }
    }
  }
  // OpenAlex enrichment (fields / venue / affiliations) by DOI
  const cands = [...byKey.values()];
  const dois = cands.filter(c => c.doi).map(c => c.doi.toLowerCase().replace("https://doi.org/", ""));
  onProgress && onProgress("OpenAlex 富化…", (queries.length) / (queries.length + 2));
  if (dois.length) {
    for (let i = 0; i < dois.length; i += 50) {
      const chunk = dois.slice(i, i + 50).filter(d => !d.includes(",") && !d.includes("|"));
      if (!chunk.length) continue;
      try {
        const d = await jget(`${OPENALEX}/works?filter=doi:${chunk.join("|")}&per-page=50&mailto=${MAILTO}&select=doi,primary_topic,authorships,primary_location,cited_by_count`);
        const byDoi = new Map();
        for (const w of d.results || []) { if (w.doi) byDoi.set(w.doi.toLowerCase().replace("https://doi.org/", ""), w); }
        for (const c of cands) {
          const w = c.doi && byDoi.get(c.doi.toLowerCase().replace("https://doi.org/", ""));
          if (!w) continue;
          // OpenAlex only fills gaps — EPMC affiliations/keywords already populated above
          if (!c.fields.length && w.primary_topic) c.fields = [w.primary_topic.display_name, w.primary_topic.subfield?.display_name, w.primary_topic.field?.display_name].filter(Boolean);
          if (!c.affiliations.length) {
            const affs = [];
            for (const a of (w.authorships || []).slice(0, 25)) for (const ins of a.institutions || []) if (ins.display_name && !affs.includes(ins.display_name)) affs.push(ins.display_name);
            c.affiliations = affs.slice(0, 10);
          }
          if (c.citations == null) c.citations = w.cited_by_count;
          if (!c.venue && w.primary_location?.source?.display_name) c.venue = w.primary_location.source.display_name;
        }
      } catch (e) { /* skip */ }
    }
  }
  // pull real Methods-section evidence sentences from OA full texts for the
  // most relevant hits that don't already have an abstract snippet
  const aliases = [inst.model, ...(inst.model_aliases || [])];
  const needText = cands.filter(c => c.pmcid && !c.evidence).slice(0, 14);
  let ftDone = 0;
  await pool(needText, async (c) => {
    onProgress && onProgress(`抽取方法节证据句 ${++ftDone}/${needText.length}`, (queries.length + 1 + ftDone / Math.max(1, needText.length)) / (queries.length + 3));
    const s = await fetchMethodsSnippet(c.pmcid, aliases);
    if (s) { c.evidence = s.snippet; c.section = s.section; }
  }, 4);

  // heuristic confidence: a retrieved Methods sentence is the strongest signal
  for (const c of cands) {
    if (c.evidence && c.section === "methods") c.confidence = 0.95;
    else if (c.evidence) c.confidence = c.brand ? 0.9 : 0.82;
    else c.confidence = c.brand ? 0.75 : 0.65;
    if (!c.section) c.section = "methods";  // Europe PMC METHODS-scoped hit
  }
  cands.sort((a, b) => (b.confidence - a.confidence) || ((b.year || 0) - (a.year || 0)));
  onProgress && onProgress("完成", 1);
  return cands;
}

function aggregateUsage(cands) {
  const byYear = {}, fields = {}, insts = {}, venues = {};
  for (const c of cands) {
    if (c.year) byYear[c.year] = (byYear[c.year] || 0) + 1;
    for (const f of c.fields) fields[f] = (fields[f] || 0) + 1;
    for (const a of c.affiliations.slice(0, 5)) insts[a] = (insts[a] || 0) + 1;
    if (c.venue) venues[c.venue] = (venues[c.venue] || 0) + 1;
  }
  const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n).map(([name, papers]) => ({ name, papers }));
  return { byYear, topFields: top(fields, 5), topInstitutions: top(insts, 8), topVenues: top(venues, 8) };
}

/* sessionStorage cache so re-visiting a model doesn't re-query */
const cacheGet = k => { try { const v = sessionStorage.getItem(k); return v ? JSON.parse(v) : null; } catch { return null; } };
const cacheSet = (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch { } };

/* ================= UI (renders in index.html's #app) ================= */
const loading = (msg = "加载中…") => app().innerHTML = `<div class="empty"><span class="spin"></span> ${esc(msg)}</div>`;
function progressBox(label, frac) {
  app().innerHTML = `<div class="empty"><span class="spin"></span> ${esc(label)}
    <div style="max-width:320px;margin:1rem auto 0;height:4px;background:var(--grid);border-radius:2px;overflow:hidden">
      <div style="height:100%;width:${Math.round(frac * 100)}%;background:var(--accent);transition:width .2s"></div></div></div>`;
}
function crumbs(parts) {
  return `<div class="crumbs">` + parts.map((p, i) => i < parts.length - 1
    ? `<a onclick="${p.go}">${esc(p.label)}</a><span>›</span>` : `<span style="color:var(--ink-2)">${esc(p.label)}</span>`).join("") + `</div>`;
}
function statusBadge(s) {
  if (s === "current") return `<span class="badge good"><span class="dot"></span>在产</span>`;
  if (s === "discontinued") return `<span class="badge mut"><span class="dot"></span>停产</span>`;
  return `<span class="badge mut">状态未知</span>`;
}
const INFO = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>`;
const coverage = t => `<div class="note">${INFO}<span>${esc(t)}</span></div>`;
const LIVE = `<span class="live"><span class="live-dot"></span>实时</span>`;

function trendChart(byYear) {
  const years = Object.keys(byYear).sort();
  if (!years.length) return "";
  const W = 520, H = 130, padB = 22, padL = 4, padT = 8;
  const max = Math.max(...years.map(y => byYear[y]));
  const bw = (W - padL * 2) / years.length, barW = Math.max(6, Math.min(38, bw - 8));
  const bars = years.map((y, i) => {
    const v = byYear[y], bh = Math.max(2, (H - padB - padT) * v / max);
    const x = padL + i * bw + (bw - barW) / 2, yy = H - padB - bh;
    const show = years.length <= 12 || i % 2 === 0;
    return `<rect class="bar" x="${x.toFixed(1)}" y="${yy.toFixed(1)}" width="${barW.toFixed(1)}" height="${bh.toFixed(1)}" rx="3" data-y="${y}" data-v="${v}"></rect>`
      + (show ? `<text x="${(x + barW / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle">${y.slice(2)}</text>` : "");
  }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" onmousemove="barHover(event)" onmouseleave="hideTip()">${bars}</svg></div>`;
}
window.barHover = e => { const r = e.target.closest(".bar"); const tt = $("#tt"); if (!r) { tt.style.opacity = 0; return; } tt.textContent = `${r.dataset.y}：${r.dataset.v} 篇`; tt.style.left = (e.clientX + 12) + "px"; tt.style.top = (e.clientY - 12) + "px"; tt.style.opacity = 1; };
window.hideTip = () => $("#tt").style.opacity = 0;

/* ---- router ---- */
window.goHome = () => { location.hash = ""; };
window.go = (view, arg) => { location.hash = view + (arg ? "/" + encodeURIComponent(arg) : ""); };
async function route() {
  await loadSeed();
  const h = decodeURIComponent(location.hash.replace(/^#/, ""));
  const [view, ...rest] = h.split("/");
  const arg = rest.join("/");
  if (view === "model") return renderModel(arg);
  if (view === "category") return renderCategory(arg);
  return renderHome();
}

/* ---- home ---- */
function renderHome() {
  const cats = {};
  for (const i of SEED) cats[i.category] = (cats[i.category] || 0) + 1;
  const catList = Object.entries(cats).sort((a, b) => b[1] - a[1]);
  const featured = ["42i", "T200", "Serinus 40", "APNA-370", "G2401", "205"]
    .map(m => SEED.find(i => i.model === m)).filter(Boolean);
  app().innerHTML = `
    <div class="hero">
      <h1>从「哪台仪器」到「有据可依」</h1>
      <p>把气体分析仪的规格与认证，和 ${LIVE} <b>真正用过它的已发表论文</b>（含方法节证据句）汇到一处，支撑可辩护的采购决策。</p>
      <div class="flow"><b>选型号</b> → <span>看文献证据</span> → <span>比同类</span> → <b>过采购论证</b></div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="n tnum">${SEED.length}</div><div class="l">已收录型号</div></div>
      <div class="tile"><div class="n tnum">${catList.length}</div><div class="l">仪器品类</div></div>
      <div class="tile"><div class="n tnum">${SEED.filter(i => i.epa_designation).length}</div><div class="l">EPA 认证型号</div></div>
      <div class="tile"><div class="n tnum" style="color:var(--accent)">实时</div><div class="l">文献联网查询</div></div>
    </div>
    <div class="card">
      <h3>按品类浏览</h3>
      <div class="chips">${catList.map(([c, n]) => `<span class="chip" onclick="go('category','${esc(c)}')">${esc(catLabel(c))}<span class="c tnum">${n}</span></span>`).join("")}</div>
    </div>
    <div class="card">
      <h3>常见型号（点开实时查文献）</h3>
      <div class="tablewrap"><table>
        <tr><th>型号</th><th>品类</th><th>状态</th><th>认证</th></tr>
        ${featured.map(m => `<tr>
          <td><a onclick="go('model','${esc(m.model)}')"><b>${esc(m.manufacturer)} ${esc(m.model)}</b></a></td>
          <td class="cat-tag">${esc(catLabel(m.category))}</td><td>${statusBadge(m.status)}</td>
          <td>${m.epa_designation ? `<span class="pill">EPA</span>` : ""}</td></tr>`).join("")}
      </table></div>
    </div>`;
}

/* ---- model detail ---- */
async function renderModel(q) {
  await loadSeed();
  const matches = resolveInstrument(q, 4);
  if (!matches.length) {
    app().innerHTML = crumbs([{ label: "首页", go: "goHome()" }, { label: q }])
      + `<div class="card empty">未找到匹配型号「${esc(q)}」。<br><span class="sub">当前索引覆盖气体分析仪（NOx / SO₂ / O₃ / CO / NH₃ / CO₂·CH₄ 等）。</span></div>`;
    return;
  }
  const m0 = matches[0], inst = m0.inst, fuzzy = m0.score < 0.85;
  const name = `${inst.manufacturer} ${inst.model}`;
  const cacheKey = "lit:" + name;
  let cands = cacheGet(cacheKey);
  if (!cands) {
    cands = await searchLiterature(inst, (label, frac) => progressBox(`${label}`, frac));
    cacheSet(cacheKey, cands);
  }
  const usage = aggregateUsage(cands);
  const shown = cands.slice(0, 25);
  const s = inst.specs || {};
  const specRows = Object.entries(s).filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  const methodsN = cands.filter(c => c.evidence).length;

  const labxUrl = `https://www.labx.com/search?q=${encodeURIComponent(brandWord(inst.manufacturer) + " " + inst.model)}`;
  const ebayUrl = `https://www.ebay.com/sch/i.html?_nkw=${encodeURIComponent(brandWord(inst.manufacturer) + " " + inst.model)}`;

  app().innerHTML =
    crumbs([{ label: "首页", go: "goHome()" }, { label: catLabel(inst.category), go: `go('category','${esc(inst.category)}')` }, { label: name }])
    + `<div class="card">
        <div class="detail-head">
          <div>
            <h1 class="title">${esc(name)}</h1>
            <div class="meta">
              ${statusBadge(inst.status)}
              <span class="pill">${esc(inst.category || "")}</span>
              <span class="pill">${esc(inst.principle || "")}</span>
              ${inst.epa_designation ? `<span class="badge epa">EPA ${esc(inst.epa_designation)}</span>` : ""}
              ${fuzzy ? `<span class="badge mut">模糊匹配 ${m0.score}</span>` : ""}
            </div>
          </div>
          <button class="btn primary" onclick="go('category','${esc(inst.category)}')">比较同类 →</button>
        </div>
      </div>
      <div class="cols">
        <div>
          <div class="card">
            <h3>规格 <span class="sub" style="text-transform:none;letter-spacing:0">· 来源：${inst.specs_provenance === 'datasheet' ? '数据表抽取' : '人工整理'}</span></h3>
            <div class="tablewrap"><table class="kv">${specRows || '<tr><td class="sub">暂无规格数据</td></tr>'}</table></div>
            ${inst.datasheet_url ? `<div style="margin-top:.7rem"><a href="${esc(inst.datasheet_url)}" target="_blank" rel="noopener">厂商数据表 →</a></div>` : ""}
            ${inst.model_aliases?.length ? `<div class="sub" style="margin-top:.7rem">文献别名：${inst.model_aliases.map(esc).join("、")}</div>` : ""}
          </div>
          <div class="card">
            <h3>二手行情</h3>
            <div class="sub">实时行情无公共 API，直接在市场搜索：</div>
            <div style="margin-top:.6rem;display:flex;gap:.5rem;flex-wrap:wrap">
              <a class="btn" href="${esc(labxUrl)}" target="_blank" rel="noopener">LabX 搜索 →</a>
              <a class="btn" href="${esc(ebayUrl)}" target="_blank" rel="noopener">eBay 搜索 →</a>
            </div>
          </div>
        </div>
        <div>
          <div class="card">
            <h3>使用画像 ${LIVE}</h3>
            <div class="stat-row">
              <div class="stat"><div class="n tnum">${cands.length}</div><div class="l">检索到论文<br>（方法节匹配）</div></div>
              <div class="stat"><div class="n tnum">${methodsN}</div><div class="l">含证据句</div></div>
              <div class="stat"><div class="n tnum">${usage.topInstitutions.length}</div><div class="l">使用机构</div></div>
            </div>
            ${Object.keys(usage.byYear).length ? `<div style="margin-top:1rem"><div class="sub" style="margin-bottom:.3rem">逐年论文数</div>${trendChart(usage.byYear)}</div>` : ""}
            ${usage.topFields.length ? `<div style="margin-top:1rem"><div class="sub" style="margin-bottom:.4rem">主要领域</div><div class="taglist">${usage.topFields.map(f => `<span class="pill">${esc(f.name)} · ${f.papers}</span>`).join("")}</div></div>` : ""}
            ${usage.topInstitutions.length ? `<div style="margin-top:.9rem"><div class="sub" style="margin-bottom:.4rem">主要机构</div><div class="taglist">${usage.topInstitutions.map(f => `<span class="pill">${esc(f.name)} · ${f.papers}</span>`).join("")}</div></div>` : ""}
          </div>
          <div class="card">
            <h3>文献证据 ${LIVE} <span class="sub" style="text-transform:none;letter-spacing:0">· 检索到 ${cands.length} 篇，展示 ${shown.length}</span></h3>
            <div class="papers">
              ${shown.map(p => `<div class="paper">
                <div class="paper-head">
                  <span class="year tnum">${p.year ?? ""}</span>
                  ${p.doi ? `<a class="paper-title" href="https://doi.org/${esc(p.doi)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : `<span class="paper-title">${esc(p.title)}</span>`}
                  <span class="conf-badge tnum" title="启发式置信度">${p.confidence.toFixed(2)}</span>
                </div>
                <div class="paper-meta">${esc(p.venue ?? "")}${(p.fields || []).length ? " · " + (p.fields || []).slice(0, 2).map(esc).join("、") : ""}</div>
                ${p.evidence ? `<div class="ev">“${esc(p.evidence)}”${p.section === "methods" ? ` <span class="ev-src">— 方法节</span>` : ""}</div>` : `<div class="ev-src">方法节域匹配（全文无可提取摘句）</div>`}
              </div>`).join("") || `<div class="sub">未检索到方法节匹配的论文。</div>`}
            </div>
            ${coverage("实时查询 Europe PMC（方法节域）+ OpenAlex；启发式匹配（品牌词共现），未经 LLM 语义复核。开放获取覆盖，计数为真实使用量的下限。")}
          </div>
        </div>
      </div>`;
}

/* ---- category view ---- */
async function renderCategory(cat) {
  await loadSeed();
  const models = SEED.filter(i => (i.category || "") === cat);
  if (!models.length) { app().innerHTML = crumbs([{ label: "首页", go: "goHome()" }, { label: catLabel(cat) }]) + `<div class="card empty">该品类暂无型号。</div>`; return; }

  // real-time literature-volume ranking via Europe PMC hitCount (one light count per model)
  const cacheKey = "rank:" + cat;
  let ranked = cacheGet(cacheKey);
  if (!ranked) {
    ranked = [];
    for (let i = 0; i < models.length; i++) {
      progressBox(`实时排序：查文献量 ${i + 1}/${models.length}（${models[i].model}）`, i / models.length);
      const n = await epmcCount(models[i]);
      ranked.push({ inst: models[i], count: n });
    }
    ranked.sort((a, b) => b.count - a.count);
    cacheSet(cacheKey, ranked);
  }

  const scoreOf = r => Math.log1p(r.count) * 2 + (r.inst.status === "current" ? 1 : 0) + (r.inst.epa_designation ? .5 : 0);
  const recs = [...ranked].sort((a, b) => scoreOf(b) - scoreOf(a)).slice(0, 5);

  const recCards = recs.map((r, i) => {
    const m = r.inst;
    return `<div class="rec">
      <div><span class="rank">${i + 1}</span><span class="name"><a onclick="go('model','${esc(m.model)}')">${esc(m.manufacturer)} ${esc(m.model)}</a></span>
        ${statusBadge(m.status)} ${m.epa_designation ? `<span class="badge epa">EPA ${esc(m.epa_designation)}</span>` : ""}</div>
      <div class="metrics">
        <span>原理 <b>${esc(m.principle || "—")}</b></span>
        <span>检出限 <b>${esc(m.specs?.lod || "—")}</b></span>
        <span>${LIVE} 文献量 <b class="tnum">${r.count}</b></span>
      </div></div>`;
  }).join("");

  app().innerHTML =
    crumbs([{ label: "首页", go: "goHome()" }, { label: catLabel(cat) }])
    + `<div class="card"><div class="detail-head"><div><h1 class="title">${esc(catLabel(cat))}</h1>
        <div class="sub">${models.length} 个型号 · 排序依据：${LIVE} 文献使用量（Europe PMC 方法节命中）、在产状态、合规认证</div></div></div></div>
      <div class="card">
        <h3>采购推荐（有据可依）</h3>
        ${recCards || `<div class="empty">暂无数据。</div>`}
        ${coverage("文献量为 Europe PMC 方法节命中的实时计数（开放获取下限）。")}
      </div>
      <div class="card">
        <h3>规格对比矩阵 <span class="sub" style="text-transform:none;letter-spacing:0">· 窄屏可左右滑动</span></h3>
        <div class="tablewrap"><table class="matrix">
          <tr><th>型号</th><th>状态</th><th>原理</th><th>量程</th><th>检出限</th><th>响应</th><th>EPA</th><th style="text-align:right">${LIVE}文献</th></tr>
          ${ranked.map(r => { const m = r.inst, s = m.specs || {}; return `<tr>
            <td><a onclick="go('model','${esc(m.model)}')"><b>${esc(m.manufacturer)} ${esc(m.model)}</b></a></td>
            <td>${statusBadge(m.status)}</td><td>${esc(m.principle || "—")}</td>
            <td>${esc(s.ranges || "—")}</td><td>${esc(s.lod || "—")}</td>
            <td class="tnum">${s.response_time_s != null ? s.response_time_s + " s" : "—"}</td>
            <td>${m.epa_designation ? `<span class="pill" title="${esc(m.epa_designation)}">EPA</span>` : "—"}</td>
            <td style="text-align:right" class="tnum">${r.count}</td></tr>`; }).join("")}
        </table></div>
      </div>`;
}

/* ---- wire up ---- */
window.addEventListener("hashchange", route);
document.addEventListener("DOMContentLoaded", () => {
  $("#q").addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    const q = e.target.value.trim(); if (!q) return;
    const cat = resolveCategory(q);
    if (cat) go("category", cat); else go("model", q);
  });
  $("#themeBtn").onclick = () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
  };
  route();
});
