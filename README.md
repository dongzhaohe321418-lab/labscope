# LabScope · 仪器采购情报

> **从「哪台仪器」到「有据可依」** —— 把气体分析仪的规格、**实时联网检索到的、真正用过它的已发表论文**（含方法节证据句），以及市场入口汇到一处，支撑可辩护的采购决策。

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/dongzhaohe321418-lab/labscope)
&nbsp;![static](https://img.shields.io/badge/frontend-static-blue)
&nbsp;![realtime](https://img.shields.io/badge/literature-realtime-2a78d6)
&nbsp;![license](https://img.shields.io/badge/license-MIT-green)

覆盖 **269 个气体分析仪型号**（NOx / NO₂ / SO₂ / O₃ / CO / NH₃ / CO₂·CH₄ / H₂S / THC·VOC / 多组分 / 校准仪），跨 Thermo、Teledyne API、Ecotech、Horiba、Envea、2B、Eco Physics、Picarro、LGR/ABB、Aerodyne、聚光科技 FPI、先河、雪迪龙等主流厂商。

---

## 为什么

买一台实验室/监测仪器，最强的信任信号是**「哪些论文真的用过这个型号、用在什么场景」**——但这需要几天的文献翻找。LabScope 把它变成一次搜索：

**选型号 → 看文献证据 → 比同类 → 过采购论证**

## 核心特性

- **🔎 实时文献证据** — 搜一个型号，浏览器**当场**查 [Europe PMC](https://europepmc.org/)（方法节域检索）+ [OpenAlex](https://openalex.org/)，抽取**方法节原文证据句**（"...measured using a Thermo Scientific Model 42i..."）。不预爬、不背数据。
- **📊 有据可依的推荐** — 品类推荐用 Europe PMC 的 `hitCount` **实时**给型号按文献使用量排序，叠加在产状态、EPA/CCEP 合规认证。
- **📋 规格 + 合规** — 策划的静态种子库：量程、检出限、响应时间、测量原理、US EPA 参考方法号、中国 CCEP 认证。
- **⚡ 纯静态、零后端** — 前端直连公共 API（都支持 CORS），可一键部署到 Vercel/任意静态托管，无数据库、无服务器、无 API key。
- **🎨 干净好用** — 一个智能搜索框按意图路由（型号→证据档案，品类→推荐+对比），深浅主题，响应式。

## 一键部署到 Vercel

1. 把本仓库推到你的 GitHub（见下方「本地开发」，或直接 fork）。
2. 到 [vercel.com/new](https://vercel.com/new) → **Import Git Repository** → 选本仓库 → **Deploy**。
   `vercel.json` 已把静态根设为 `web/`，**零配置**。
3. 完成。站点纯静态，浏览器实时查文献。

> 或点上方 **Deploy with Vercel** 按钮，按提示 clone + 部署。

## 本地开发

```bash
git clone https://github.com/dongzhaohe321418-lab/labscope.git
cd labscope
python3 web/server.py 8321        # 本地静态服务器（仅为让 fetch 生效；生产是纯静态）
# 打开 http://127.0.0.1:8321
```

前端只依赖 `web/index.html`、`web/app.js`、`web/data/instruments.json`——没有构建步骤。

## 架构

```
浏览器 (web/)                         公共 API（实时，CORS）
┌───────────────────────────┐        ┌──────────────────────┐
│ index.html · app.js       │──查──▶ │ Europe PMC  方法节检索 │
│ · 智能搜索/路由            │        │             全文证据句 │
│ · 前端模糊型号匹配         │──查──▶ │ OpenAlex    字段/引用   │
│ · 实时文献查询 + 启发式消歧 │        └──────────────────────┘
│ · 证据句提取 · 使用画像图表 │
└───────────┬───────────────┘
            │ 载入（静态）
   web/data/instruments.json          ← 策划种子库（规格/别名/认证）
```

- **仪器种子库是策划的静态数据**——没有公共 API 能实时给出型号规格/别名/认证，这是产品的护城河，靠人工+多智能体策划（见下）。
- **文献链接全部实时**——每次搜索当场查，永远最新。
- **消歧是透明的启发式**：Europe PMC 的方法节域检索本身是强信号，叠加品牌词共现约束 + 证据句提取。诚实标注「未经 LLM 语义复核」。若需最高精度，用可选的 Python 后端（下）做 LLM 消歧的批量索引。

## 扩展仪器库

种子库由多智能体工作流策划（每个厂商一个 agent 起草 + 一个对抗性 agent 核实删幻觉），当前 269 个型号。要增补：

```bash
# 编辑 data/expanded_seed.json 或用后端工具重新策划，然后：
python3 scripts/export_seed.py       # 重新生成 web/data/instruments.json
```

`web/data/instruments.json` 是前端唯一的数据依赖——直接编辑它也能加型号。

## 可选：Python 后端（LLM 增强 / 批量索引）

纯静态前端已能独立运行。仓库还带一套 Python 工具，用于**离线高精度索引**（LLM 语义消歧、数据表规格抽取、评估）：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python labscope.py init-db
.venv/bin/python labscope.py seed                 # 载入种子
.venv/bin/python labscope.py literature --limit 10 # LLM 消歧的文献索引
.venv/bin/python labscope.py stats
```

它还能作为 [Claude Code](https://claude.com/claude-code) 的 MCP 工具（无需 API key）：

```bash
./scripts/register_mcp.sh
```

后端细节见 [`docs/BACKEND.md`](docs/BACKEND.md)。

## 数据来源

- **[Europe PMC](https://europepmc.org/)** — 开放获取全文与方法节检索（REST API，CORS）。
- **[OpenAlex](https://openalex.org/)** — 学术元数据（字段、机构、引用；polite pool）。
- 仪器规格与认证：厂商数据表 + 人工/多智能体策划。

请遵守各 API 的使用条款与速率限制。文献覆盖仅限开放获取，计数为真实使用量的**下限**。

## License

[MIT](LICENSE)
