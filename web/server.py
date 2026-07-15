"""Minimal LabScope web UI — stdlib only, no extra dependencies.

  .venv/bin/python web/server.py [port]     (default 8321)

GET  /                     single-page UI
GET  /api/<tool>?args=<url-encoded JSON>    run one of the six agent tools
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.tools import TOOL_FUNCS, WEB_FUNCS  # noqa: E402

API_FUNCS = {**TOOL_FUNCS, **WEB_FUNCS}
INDEX_PATH = Path(__file__).resolve().parent / "index.html"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # dev server: always serve fresh
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            # re-read on each request so UI edits show up without a restart
            self._send(200, INDEX_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/api/"):
            name = parsed.path[5:]
            fn = API_FUNCS.get(name)
            if fn is None:
                self._send(404, b'{"error":"unknown tool"}', "application/json")
                return
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                args = json.loads(qs.get("args", ["{}"])[0])
                result = fn(**args)
                body = json.dumps(result, ensure_ascii=False, default=str).encode()
                self._send(200, body, "application/json; charset=utf-8")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return
        self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):  # quieter logs
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    print(f"LabScope UI -> http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
