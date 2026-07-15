"""LabScope MCP server — plugs the six tools into Claude Code / Claude Desktop.

Register with:
  claude mcp add labscope -- <repo>/.venv/bin/python <repo>/agent/mcp_server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from agent import tools  # noqa: E402

mcp = FastMCP(
    "labscope",
    instructions=(
        "LabScope indexes gas analyzers (NOx/NO2/SO2/O3/CO/NH3) with specs, the published "
        "papers that actually used each model (with Methods-section evidence snippets), and "
        "second-hand listing snapshots. Answer purchase questions only from tool results; "
        "cite evidence snippets when claiming a paper used an instrument; state when a model "
        "match was fuzzy. Usage counts are open-access-only lower bounds."
    ),
)


@mcp.tool()
def spec_lookup(model: str) -> dict:
    """Look up one instrument by (fuzzy) model name: specs, aliases, status, datasheet link, linked-paper count."""
    return tools.spec_lookup(model)


@mcp.tool()
def compare_models(models: list[str] | None = None, category: str | None = None) -> dict:
    """Aligned spec-comparison matrix for a list of model names, or for every model in a category (e.g. 'NOx analyzer')."""
    return tools.compare_models(models, category)


@mcp.tool()
def paper_search(model: str, limit: int = 15, min_confidence: float = 0.7) -> dict:
    """List published papers that used this instrument model, with year, venue, fields, affiliations and the Methods evidence snippet."""
    return tools.paper_search(model, limit, min_confidence)


@mcp.tool()
def usage_profile(model: str, min_confidence: float = 0.7) -> dict:
    """Aggregate usage statistics for a model: papers per year, top research fields, institutions, venues."""
    return tools.usage_profile(model, min_confidence)


@mcp.tool()
def market_search(model: str) -> dict:
    """Second-hand listing snapshots and price range for a model."""
    return tools.market_search(model)


@mcp.tool()
def recommend(category: str, max_lod_ppb: float | None = None,
              require_current: bool = False, top_n: int = 5) -> dict:
    """Ranked purchase recommendations for a category, justified by specs and literature-usage evidence."""
    return tools.recommend(category, max_lod_ppb, require_current, top_n)


if __name__ == "__main__":
    mcp.run()
