"""LLM adapter for pipeline extraction/classification steps.

Backend priority:
  1. Anthropic SDK  — used when ANTHROPIC_API_KEY (or an `ant auth login` profile) is available.
  2. `claude` CLI   — Claude Code print mode; works on a subscription with no API key.

Default model: claude-opus-4-8 (override with LABSCOPE_LLM_MODEL).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

DEFAULT_MODEL = os.environ.get("LABSCOPE_LLM_MODEL", "claude-opus-4-8")
_CLI_ALIAS = {"claude-opus-4-8": "opus", "claude-sonnet-5": "sonnet", "claude-haiku-4-5": "haiku"}

_backend: str | None = None


def _pick_backend() -> str:
    global _backend
    if _backend:
        return _backend
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        _backend = "sdk"
    elif shutil.which("claude"):
        _backend = "cli"
    else:
        _backend = "sdk"  # may still resolve an `ant auth login` profile
    return _backend


def _extract_json(text: str) -> dict | list:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # fall back to outermost braces/brackets
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON found in LLM output: {text[:300]!r}")


def _sdk_json(prompt: str, schema: dict | None, model: str, max_tokens: int) -> dict | list:
    import anthropic

    client = anthropic.Anthropic()
    kwargs: dict = {}
    if schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model refused the request")
    text = next(b.text for b in resp.content if b.type == "text")
    return _extract_json(text)


def _cli_json(prompt: str, schema: dict | None, model: str, max_tokens: int) -> dict | list:
    if schema is not None:
        prompt = (
            prompt
            + "\n\nReturn ONLY a JSON value matching this JSON Schema — no prose, no markdown fences:\n"
            + json.dumps(schema)
        )
    else:
        prompt += "\n\nReturn ONLY valid JSON — no prose, no markdown fences."
    for candidate in (model, _CLI_ALIAS.get(model, "sonnet")):
        proc = subprocess.run(
            ["claude", "-p", "--model", candidate, "--output-format", "json",
             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'],
            input=prompt, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            if candidate != model or "model" not in err.lower():
                raise RuntimeError(f"claude CLI failed: {err[:400]}")
            continue  # model not available on this plan/CLI — retry with alias
        envelope = json.loads(proc.stdout)
        result_text = envelope.get("result", "")
        try:
            return _extract_json(result_text)
        except ValueError:
            # occasionally the CLI output is truncated mid-JSON; one fresh retry
            proc2 = subprocess.run(
                ["claude", "-p", "--model", candidate, "--output-format", "json",
                 "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'],
                input=prompt + "\nKeep the JSON as compact as possible.",
                capture_output=True, text=True, timeout=600,
            )
            if proc2.returncode != 0:
                raise RuntimeError(f"claude CLI retry failed: {(proc2.stderr or '')[:400]}")
            return _extract_json(json.loads(proc2.stdout).get("result", ""))
    raise RuntimeError("claude CLI failed for all model candidates")


def llm_json(prompt: str, schema: dict | None = None, model: str | None = None,
             max_tokens: int = 16000) -> dict | list:
    """One-shot prompt → parsed JSON, via whichever backend is available."""
    global _backend
    model = model or DEFAULT_MODEL
    backend = _pick_backend()
    if backend == "sdk":
        try:
            return _sdk_json(prompt, schema, model, max_tokens)
        except Exception as sdk_err:
            if not shutil.which("claude"):
                raise RuntimeError(
                    "No LLM backend available: set ANTHROPIC_API_KEY, run `ant auth login`, "
                    f"or install the claude CLI. Underlying error: {sdk_err}"
                ) from sdk_err
            # Fall back to the CLI for THIS call only — do NOT permanently flip the
            # backend on a transient SDK blip (that would slow every later call).
            try:
                return _cli_json(prompt, schema, model, max_tokens)
            except Exception as cli_err:
                # surface both root causes, not just the CLI one
                raise RuntimeError(
                    f"Both LLM backends failed. SDK error: {sdk_err}; CLI error: {cli_err}"
                ) from sdk_err
    return _cli_json(prompt, schema, model, max_tokens)
