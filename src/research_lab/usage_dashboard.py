"""Loopback-only, read-only research dashboard; legacy usage endpoint preserved."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .dashboard_data import DashboardStore
from .token_ledger import TokenLedger

ASSETS = Path(__file__).with_name("dashboard_assets")


def make_server(config, port=8767, root=None):
    ledger = TokenLedger(config)
    store = DashboardStore(root or Path(__file__).resolve().parents[2], ledger, background_integrity=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            actual_port = self.server.server_port
            if self.headers.get("Host") not in (f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"):
                self.send_error(403)
                return
            parsed = urlsplit(self.path)
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/assets/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
                      "/assets/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8")}
            try:
                if parsed.path in static:
                    name, kind = static[parsed.path]
                    body = (ASSETS / name).read_bytes()
                elif parsed.path == "/api/usage":
                    body, kind = json.dumps(ledger.snapshot(), ensure_ascii=False).encode("utf-8"), "application/json"
                elif parsed.path == "/api/research":
                    body, kind = json.dumps(store.snapshot(), ensure_ascii=False).encode("utf-8"), "application/json"
                elif parsed.path == "/api/artifact":
                    query = parse_qs(parsed.query)
                    if set(query) != {"path"} or len(query["path"]) != 1:
                        raise ValueError("Expected one allowlisted artifact path")
                    body, kind = json.dumps(store.artifact(query["path"][0]), ensure_ascii=False).encode("utf-8"), "application/json"
                else:
                    self.send_error(404)
                    return
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                self.send_error(400 if parsed.path == "/api/artifact" else 503, "Data unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.dashboard_store = store
    return server


def serve_usage(config, port=8767):
    server = make_server(config, port)
    print(f"Research dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
