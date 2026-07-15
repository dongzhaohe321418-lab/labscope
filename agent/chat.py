"""Conversational agent (proposal §7): Claude + the six LabScope tools, as a REPL.

Requires Anthropic API credentials (ANTHROPIC_API_KEY or an `ant auth login`
profile). Without credentials, use the MCP server inside Claude Code instead —
same tools, no key needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.tools import TOOL_FUNCS  # noqa: E402

MODEL = "claude-opus-4-8"

SYSTEM = """You are LabScope, an instrument-purchase advisor for researchers buying gas analyzers.

Hard rules:
- Answer ONLY from tool results. If the tools return nothing, say so — never invent specs, papers, or prices.
- When you claim a paper used an instrument, quote its evidence snippet and give the year/venue.
- When a model match was fuzzy (fuzzy=true or match_score < 0.85), say which instrument you matched to and ask if that was intended.
- Always mention that literature counts are open-access-only lower bounds when using them to justify a recommendation.
- For purchase recommendations, combine: spec fit, literature usage evidence, current/discontinued status, and (if relevant) compliance designation and second-hand price data."""

TOOLS = [
    {
        "name": "spec_lookup",
        "description": "Look up one instrument by (fuzzy) model name: specs, aliases, status, datasheet link, linked-paper count.",
        "input_schema": {
            "type": "object",
            "properties": {"model": {"type": "string", "description": "Model name, fuzzy OK, e.g. 'thermo 42i' or 'T200'"}},
            "required": ["model"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "compare_models",
        "description": "Aligned spec-comparison matrix for a list of models, or all models in a category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "models": {"type": ["array", "null"], "items": {"type": "string"}},
                "category": {"type": ["string", "null"], "description": "e.g. 'NOx analyzer'"},
            },
            "required": ["models", "category"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "paper_search",
        "description": "Papers that used this instrument, with evidence snippets from Methods sections.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "limit": {"type": "integer"},
                "min_confidence": {"type": "number"},
            },
            "required": ["model"],
            "additionalProperties": False,
        },
    },
    {
        "name": "usage_profile",
        "description": "Aggregate usage stats for a model: papers/year, top fields, institutions, venues.",
        "input_schema": {
            "type": "object",
            "properties": {"model": {"type": "string"}},
            "required": ["model"],
            "additionalProperties": False,
        },
    },
    {
        "name": "market_search",
        "description": "Second-hand listing snapshots and price range for a model.",
        "input_schema": {
            "type": "object",
            "properties": {"model": {"type": "string"}},
            "required": ["model"],
            "additionalProperties": False,
        },
    },
    {
        "name": "recommend",
        "description": "Ranked purchase recommendations for a category, justified by specs + usage evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "e.g. 'NOx analyzer'"},
                "max_lod_ppb": {"type": ["number", "null"]},
                "require_current": {"type": "boolean"},
                "top_n": {"type": "integer"},
            },
            "required": ["category"],
            "additionalProperties": False,
        },
    },
]


def _execute(name: str, args: dict) -> str:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return json.dumps(fn(**args), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def run_turn(client, messages: list, max_iterations: int = 12) -> str:
    """Agentic loop for one user turn; mutates messages in place.

    On any exception, the caller (main) truncates `messages` back to the pre-turn
    length, so a mid-turn failure never leaves a dangling tool_use in history.
    """
    for _ in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "refusal":
            return "(the model declined to answer this request)"
        if response.stop_reason == "pause_turn":
            continue
        # Answer any tool_use blocks regardless of stop_reason. If the model was
        # truncated (max_tokens) *after* emitting a complete tool_use block, we
        # must still return its tool_result or the next request 400s on a
        # dangling tool_use.
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            text = "".join(b.text for b in response.content if b.type == "text")
            if response.stop_reason == "max_tokens":
                text += "\n\n(response was truncated at the token limit)"
            return text
        results = []
        for block in tool_uses:
            print(f"  [tool] {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]})")
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _execute(block.name, block.input),
            })
        messages.append({"role": "user", "content": results})
    return "(stopped after too many tool-use rounds)"


def main() -> None:
    try:
        import anthropic

        client = anthropic.Anthropic()
    except Exception as e:
        print(f"Could not construct Anthropic client: {e}")
        sys.exit(1)
    print("LabScope agent — ask about buying gas analyzers. Ctrl-D / 'exit' to quit.\n")
    messages: list = []
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in {"exit", "quit"}:
            break
        base = len(messages)  # snapshot so we can roll the whole turn back on error
        messages.append({"role": "user", "content": user})
        try:
            reply = run_turn(client, messages)
        except Exception as e:
            hint = ""
            if "auth" in str(e).lower() or "401" in str(e):
                hint = ("\nNo API credentials found. Alternative: register the MCP server in "
                        "Claude Code —\n  claude mcp add labscope -- .venv/bin/python agent/mcp_server.py")
            print(f"error: {e}{hint}")
            # discard everything appended this turn (user msg + any tool rounds)
            # so history never ends on a dangling assistant tool_use block
            del messages[base:]
            continue
        print(f"\nlabscope> {reply}\n")


if __name__ == "__main__":
    main()
