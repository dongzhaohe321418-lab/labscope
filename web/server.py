"""Local dev server for the LabScope static front-end.

The production build is fully static (Vercel serves web/ directly; the browser
queries Europe PMC / OpenAlex live). This server just serves web/ over HTTP so
`fetch('data/instruments.json')` works locally, and additionally keeps the
optional `/api/<tool>` JSON endpoints for anyone wiring the Python tools into a
custom backend.

  python web/server.py [port]        # default 8321
"""
from __future__ import annotations

import json
import mimetypes
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent

# /api/ is optional — only import the tools if the Python package is importable
try:
    sys.path.insert(0, str(WEB_DIR.parent))
    from agent.tools import TOOL_FUNCS, WEB_FUNCS
    API_FUNCS = {**TOOL_FUNCS, **WEB_FUNCS}
except Exception:
    API_FUNCS = {}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            fn = API_FUNCS.get(path[5:])
            if fn is None:
                self._send(404, b'{"error":"unknown tool"}', "application/json")
                return
            try:
                args = json.loads(urllib.parse.parse_qs(parsed.query).get("args", ["{}"])[0])
                body = json.dumps(fn(**args), ensure_ascii=False, default=str).encode()
                self._send(200, body, "application/json; charset=utf-8")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return

        # static file serving out of WEB_DIR, with a path-traversal guard
        rel = urllib.parse.unquote(path.lstrip("/")) or "index.html"
        fp = (WEB_DIR / rel).resolve()
        if fp != WEB_DIR and WEB_DIR not in fp.parents:
            self._send(403, b"forbidden", "text/plain")
            return
        if not fp.is_file():
            fp = WEB_DIR / "index.html"          # SPA fallback (hash routing)
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, fp.read_bytes(), ctype)

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    print(f"LabScope static UI -> http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
