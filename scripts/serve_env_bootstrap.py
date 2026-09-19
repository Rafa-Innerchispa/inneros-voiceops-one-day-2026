#!/usr/bin/env python3
"""Temporary bootstrap server: serves voiceops.env to .4 only (run on laptop)."""
from __future__ import annotations

import ipaddress
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ALLOW = {
    ipaddress.ip_address("192.168.1.4"),
    ipaddress.ip_address("100.94.99.12"),
    ipaddress.ip_address("127.0.0.1"),
}
ENV_PATHS = [
    Path.home() / ".config" / "inneros" / "voiceops.env",
    Path(".env"),
]
PORT = int(os.getenv("VOICEOPS_BOOTSTRAP_PORT", "8766"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/voiceops.env", "/voiceops.env.bootstrap"):
            self.send_error(404)
            return
        peer = self.client_address[0]
        try:
            if ipaddress.ip_address(peer) not in ALLOW:
                self.send_error(403, f"forbidden for {peer}")
                return
        except ValueError:
            self.send_error(403)
            return
        content = None
        for path in ENV_PATHS:
            if path.is_file():
                content = path.read_text(encoding="utf-8")
                break
        if not content:
            self.send_error(404, "voiceops.env not found on laptop")
            return
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[bootstrap] {self.client_address[0]} {fmt % args}")


def main() -> None:
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Bootstrap env server on 0.0.0.0:{PORT} (allowed: .4 only)")
    server.serve_forever()


if __name__ == "__main__":
    main()
