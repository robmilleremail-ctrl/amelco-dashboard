#!/usr/bin/env python3
"""
Local dashboard server.
Serves the latest report and handles refresh requests.

Usage:
    python src/server.py          # serves on http://localhost:8765
    python src/server.py --port 9000
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

PORT = 8765

# Resolve project root (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = PROJECT_ROOT / "output"


class DashboardHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default request logging

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_latest()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/refresh":
            self._run_refresh()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self._cors_headers(200)
        self.end_headers()

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _serve_latest(self):
        html_files = sorted(OUTPUT_DIR.glob("amelco-dashboard-*.html"))
        if not html_files:
            self._text(404, "No dashboard report found. Run: python src/main.py")
            return
        latest = html_files[-1]
        content = latest.read_bytes()
        self._cors_headers(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _run_refresh(self):
        print("\n[server] Refresh triggered — running main.py...")
        try:
            env = os.environ.copy()
            # Load ANTHROPIC_API_KEY from ~/.zshrc if not already in env
            if not env.get("ANTHROPIC_API_KEY"):
                zshrc = Path.home() / ".zshrc"
                if zshrc.exists():
                    for line in zshrc.read_text().splitlines():
                        if line.startswith("export ANTHROPIC_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if key:
                                env["ANTHROPIC_API_KEY"] = key
                                print(f"[server] Loaded API key from ~/.zshrc")
                            break
            result = subprocess.run(
                [sys.executable, str(SRC_DIR / "main.py")],
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=False,   # show output in terminal
                timeout=300,
            )
            success = result.returncode == 0
            status = {
                "ok": success,
                "message": "Refresh complete." if success else "Refresh failed — check terminal."
            }
            self._cors_headers(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
            if success:
                print("[server] Done. Serving updated report.")
        except subprocess.TimeoutExpired:
            self._json_error("Refresh timed out after 5 minutes.")
        except Exception as e:
            self._json_error(str(e))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cors_headers(self, code: int):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _text(self, code: int, msg: str):
        body = msg.encode()
        self._cors_headers(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, msg: str):
        self._cors_headers(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": False, "message": msg}).encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    server = http.server.HTTPServer(("localhost", args.port), DashboardHandler)
    url = f"http://localhost:{args.port}"

    print(f"\n{'='*50}")
    print(f"  Amelco Dashboard Server")
    print(f"  {url}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*50}\n")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] Stopped.")


if __name__ == "__main__":
    main()
