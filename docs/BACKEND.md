# LabScope 后端工具（可选）

纯静态前端（`web/`）已能独立运行并实时查文献。本文档说明**可选的 Python 后端**——用于离线高精度索引、种子库策划、评估，以及作为 Claude Code 的 MCP 工具。

## 布局

```
labscope.py          CLI 入口
common.py            HTTP 客户端（代理容错 TLS）、查询日志、限流
llm.py               LLM 适配器：Anthropic SDK → `claude` CLI 回退
db/                  schema.sql + SQLite 访问层（模糊型号匹配）
pipelines/
  seed.py            载入策划种子库
  literature.py      Europe PMC（方法节域）+ OpenAlex → 证据句
                     → LLM 消歧 → 富化   ← 高精度离线索引
  datasheets.py      PDF → pymupdf → LLM 严格 schema 规格抽取
  marketplace.py     robots.txt 合规的快照抓取 + 手动 CSV 导入
agent/
  tools.py           6 个工具 + overview 网页端点
  mcp_server.py      MCP 服务器 —— 把工具接入 Claude Code（无需 API key）
  chat.py            SDK 聊天 agent（需 ANTHROPIC_API_KEY / `ant auth login`）
web/                 静态前端（生产部署）
  server.py          本地静态 dev 服务器（+ 可选 /api/ 后端端点）
  app.js             实时查询引擎 + 渲染
  data/instruments.json  策划种子库（前端载入）
scripts/
  export_seed.py     SQLite 种子 → web/data/instruments.json
  register_mcp.sh    注册 MCP 服务器到 Claude Code
eval/run_eval.py     链接精度（LLM 评审 + 人工抽样）、规格抽检、端到端
eval/test_fixes.py   代码审查发现的 bug 的回归测试
```

## 构建离线索引

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python labscope.py init-db
.venv/bin/python labscope.py seed                       # data/*.json → DB
.venv/bin/python labscope.py literature --limit 10      # 试点：LLM 消歧的文献索引
.venv/bin/python labscope.py literature                 # 全量
.venv/bin/python labscope.py datasheets                 # 可选：从 PDF 精修规格
.venv/bin/python labscope.py stats
.venv/bin/python scripts/export_seed.py                 # 导出给前端
```

全部幂等、可续跑；所有外部 API 查询记录到 `data/logs/queries.jsonl`；全文/PDF 缓存在 `data/cache/`。

## 六个 agent 工具

`spec_lookup`、`compare_models`、`paper_search`、`usage_profile`、`market_search`、`recommend`。
三种用法：

```bash
# 直接调用（无 LLM）
.venv/bin/python labscope.py tool recommend '{"category": "NOx analyzer"}'

# Claude Code 内作为 MCP 工具（推荐，无需 API key）
./scripts/register_mcp.sh

# 独立聊天 agent（需 API 凭据）
.venv/bin/python labscope.py chat
```

## 评估

```bash
.venv/bin/python eval/run_eval.py precision --n 50   # 目标 ≥90% 链接精度
.venv/bin/python eval/run_eval.py e2e                # 10 个真实工具查询
.venv/bin/python eval/test_fixes.py                  # 回归测试
```

试点结果（13 型号，LLM 消歧）：LLM 评审链接精度 **100%**（n=40），端到端 **10/10**。

## 代码审查

后端经过多智能体工作流审查（4 维度 × 对抗性核实），24 个确认发现全部修复——含 4 个高危（联网中断时误删链接、逐仪器失败无回滚、PDF 缓存污染、REPL 悬挂 tool_use）及若干论文去重/唯一索引/输入校验 bug。回归覆盖见 `eval/test_fixes.py`。

## 环境注意事项

- **TLS 拦截代理**：pip / Python HTTPS 可能报 `CERTIFICATE_VERIFY_FAILED`。修法在 `common.py`（优先 `truststore` 系统信任库）；pip 用 `--cert .certs/system.pem`（从 macOS keychain 导出）。
- **SOCKS 代理**：需 `httpx[socks]`（已在 requirements.txt）。
- **无 `ANTHROPIC_API_KEY`**：LLM 步骤自动回退到 `claude` CLI（Claude Code 订阅，无需 key）。

## 设计说明 / 与提案的差异

- **嵌入表 → 别名模糊匹配**：MVP 用别名表 + 分词/序列相似度替代嵌入，无嵌入 API 依赖。
- **实时 vs 离线**：前端实时查（启发式消歧，可部署、无 key）；后端离线 LLM 消歧（最高精度，供批量索引）。两者共享同一 SQLite/种子。
- **市场**：eBay/LabX 无 CORS 友好 API，前端降级为市场搜索深链；后端保留 robots.txt 合规的快照抓取 + 手动 CSV 导入。
