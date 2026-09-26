"""Local test web target for Obliquity -- exercises bust, fuzz, and brute(http).

Zero dependencies (stdlib only). Binds to 127.0.0.1 (localhost) so it's never
exposed off your machine. Run:

    python -m testlab.web                # http://127.0.0.1:8000
    python -m testlab.web --port 8080
    OBLIQUITY_LAB_WILDCARD=1 python -m testlab.web   # soft-404: every path 200

See testlab/README.md for the exact obliquity commands + expected results.
"""

from __future__ import annotations

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# --- what bust should discover (path -> body) -------------------------------
# feroxbuster with common.txt/generic-* will find the ones whose names are in
# those wordlists (admin, backup, api, uploads, config, robots.txt, login, ...).
PAGES = {
    "/": "<h1>Test Lab</h1><a href='/login'>login</a>",
    "/admin": "<h1>Admin</h1>",
    "/admin/": "<h1>Admin index</h1>",
    "/backup": "backup area",
    "/backup/": "backup index",
    "/api": '{"api":"v1"}',
    "/api/": '{"routes":["/api/users","/api/login"]}',
    "/uploads/": "uploads dir",
    "/config.php": "<?php $db='secret'; ?>",
    "/config.bak": "old config backup",
    "/backup.zip": "PK\x03\x04 (fake zip)",
    "/.env": "DB_PASSWORD=hunter2",
    "/.git/HEAD": "ref: refs/heads/main",
    "/robots.txt": "User-agent: *\nDisallow: /admin\nDisallow: /backup",
    "/old/": "old site",
    "/dev/": "dev area",
    "/test/": "test area",
    "/phpinfo.php": "phpinfo()",
}

# --- what fuzz should discover: parameter NAMES /search recognizes ----------
# fuzz parameter-names-quick hits /search?FUZZ=test; recognized names return a
# distinctly-sized body so ffuf's autocalibration flags them as matches.
KNOWN_PARAMS = {"q", "id", "page", "debug", "search", "admin", "api_key", "redirect"}

# --- what brute(http-post-form) should crack --------------------------------
VALID_CREDS = {("admin", "password123"), ("user", "letmein"), ("root", "toor")}
LOGIN_FAIL_MARKER = "Login failed"  # use with hydra:  F=Login failed


class Handler(BaseHTTPRequestHandler):
    server_version = "obliquity-testlab/1.0"

    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code: int, body: str, ctype: str = "text/html") -> None:
        data = body.encode("utf-8", "replace")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # Wildcard / soft-404 mode: everything returns 200 (test the flood guard)
        if os.environ.get("OBLIQUITY_LAB_WILDCARD"):
            self._send(200, f"wildcard 200 for {path}")
            return

        if path == "/search":
            params = parse_qs(parsed.query)
            hit = KNOWN_PARAMS.intersection(params.keys())
            if hit:
                self._send(200, "<h1>Search results</h1>" + "".join(
                    f"<div>result for {p}={params[p][0]}</div>" for p in sorted(hit)) +
                    "<p>extra content so the body size differs from the baseline.</p>")
            else:
                self._send(200, "<h1>Search</h1>")  # baseline (no recognized param)
            return

        if path == "/login":
            self._send(200, "<form method=post action=/login>"
                            "user:<input name=user> pass:<input name=pass>"
                            "<button>go</button></form>")
            return

        if path in PAGES:
            self._send(200, PAGES[path])
            return
        self._send(404, "<h1>404 Not Found</h1>")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/login":
            self._send(404, "not found")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", "replace")
        form = parse_qs(body)
        user = (form.get("user") or [""])[0]
        pw = (form.get("pass") or [""])[0]
        if (user, pw) in VALID_CREDS:
            self._send(200, f"<h1>Welcome {user}</h1> authenticated.")
        else:
            self._send(200, f"<h1>{LOGIN_FAIL_MARKER}</h1>")


def main() -> None:
    ap = argparse.ArgumentParser(description="Obliquity test web target (localhost only)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep it localhost)")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    wild = " [WILDCARD/soft-404 mode]" if os.environ.get("OBLIQUITY_LAB_WILDCARD") else ""
    print(f"Obliquity test web target on http://{args.host}:{args.port}{wild}")
    print("bust/fuzz/brute-http target. Ctrl-C to stop. See testlab/README.md.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
