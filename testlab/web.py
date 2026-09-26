"""Local test web target for Obliquity -- exercises bust, fuzz, and brute(http).

Zero dependencies (stdlib only). Binds to 127.0.0.1 (localhost) so it's never
exposed off your machine. Branded to match the Obliquity app. Run:

    python -m testlab.web                # http://127.0.0.1:8000
    python -m testlab.web --port 8080
    OBLIQUITY_LAB_WILDCARD=1 python -m testlab.web   # soft-404: every path 200

See the lab guide (testlab/README.md) for commands + expected results.
"""

from __future__ import annotations

import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BANNER = r"""      ___.   .__  .__             .__  __
  ____\_ |__ |  | |__| ________ __|__|/  |_ ___.__.
 /  _ \| __ \|  | |  |/ ____/  |  \  \   __<   |  |
(  <_> ) \_\ \  |_|  < <_|  |  |  /  ||  |  \___  |
 \____/|___  /____/__/\__   |____/|__||__|  / ____|
           \/            |__|               \/"""

CSS = """
:root{--bg:#0b0e14;--panel:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#2dd4bf;--link:#58a6ff;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif;}
.wrap{max-width:760px;margin:0 auto;padding:28px 20px 60px;}
pre.banner{font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;font-size:12px;line-height:1.05;white-space:pre;font-weight:700;
  background:linear-gradient(90deg,#ff004c,#ff7a00,#ffe600,#00e676,#00c2ff,#7c4dff,#ff00d4);
  -webkit-background-clip:text;background-clip:text;color:transparent;margin:0 0 6px;}
.tag{color:var(--muted);letter-spacing:.28em;text-transform:uppercase;font-size:12px;font-family:monospace;}
h1{font-size:24px;margin:22px 0 4px;} h2{margin:26px 0 10px;font-size:17px;}
.muted{color:var(--muted);} a{color:var(--link);text-decoration:none;} a:hover{text-decoration:underline;}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:22px;margin:18px 0;}
.grid{display:flex;gap:10px;flex-wrap:wrap;} .pill{border:1px solid var(--border);border-radius:999px;padding:6px 12px;font-size:13px;color:var(--muted);}
label{display:block;color:var(--muted);font-size:13px;margin:12px 0 6px;}
input{width:100%;background:#0d1117;border:1px solid var(--border);border-radius:10px;color:var(--text);padding:11px 12px;font-size:15px;}
input:focus{outline:none;border-color:var(--accent);}
button{margin-top:18px;width:100%;background:var(--accent);color:#04231f;border:0;border-radius:10px;padding:12px;font-size:15px;font-weight:700;cursor:pointer;}
.ok{color:#00e676;font-weight:700;} .fail{color:#ff5f5f;font-weight:700;}
code{color:#f0883e;font-family:monospace;} footer{margin-top:40px;color:var(--muted);font-size:12px;font-family:monospace;}
"""

# --- what bust should discover: raw "found" files/dirs (status 200) ---------
RAW = {
    "/config.php": "<?php $db_password = 'hunter2'; // TODO: move to env ?>",
    "/config.bak": "db_password=hunter2\napi_key=sk-test-999",
    "/backup": "backup area",
    "/backup/": "index of /backup:\n  db.sql\n  config.bak",
    "/backup.zip": "PK\x03\x04 (fake zip archive)",
    "/.env": "DB_PASSWORD=hunter2\nSECRET_KEY=obliquity-lab",
    "/.git/HEAD": "ref: refs/heads/main",
    "/robots.txt": "User-agent: *\nDisallow: /admin\nDisallow: /backup\nDisallow: /api",
    "/api": '{"name":"obliquity-lab-api","version":"v1"}',
    "/api/": '{"routes":["/api/users","/api/login","/api/debug"]}',
    "/uploads/": "index of /uploads:\n  avatar.png\n  notes.txt",
    "/old/": "old site",
    "/dev/": "dev area",
    "/test/": "test area",
    "/phpinfo.php": "phpinfo()  PHP 8.1  OBLIQUITY-LAB",
}

# --- fuzz: parameter NAMES /search recognizes -------------------------------
KNOWN_PARAMS = {"q", "id", "page", "debug", "search", "admin", "api_key", "redirect"}

# --- brute(http-post-form) valid creds --------------------------------------
VALID_CREDS = {("admin", "password123"), ("user", "letmein"), ("root", "toor")}
LOGIN_FAIL_MARKER = "Login failed"  # hydra form spec:  F=Login failed


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title} - Obliquity Test Lab</title><style>{CSS}</style></head>
<body><div class=wrap>
<pre class=banner>{BANNER}</pre>
<div class=tag>obliquity &middot; test lab</div>
{body}
<footer>Obliquity Test Lab -- localhost target for bust / fuzz / crack / brute. Authorized testing only.</footer>
</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "obliquity-testlab/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: str, ctype: str = "text/html") -> None:
        data = body.encode("utf-8", "replace")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Server", "Obliquity-Lab")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if os.environ.get("OBLIQUITY_LAB_WILDCARD"):
            self._send(200, f"wildcard 200 for {path}")
            return

        if path == "/":
            self._send(200, page("Home",
                "<h1>Welcome to the Obliquity Test Lab</h1>"
                "<p class=muted>A deliberately-vulnerable localhost target for practicing every pillar.</p>"
                "<div class=card><div class=grid>"
                "<span class=pill>bust &rarr; hidden dirs/files</span>"
                "<span class=pill>fuzz &rarr; /search params</span>"
                "<span class=pill>brute &rarr; /login form</span>"
                "<span class=pill>crack &rarr; hash fixtures</span>"
                "</div></div>"
                "<p><a href=/login>&rarr; Sign in</a></p>"))
            return

        if path == "/admin" or path == "/admin/":
            self._send(200, page("Admin",
                "<h1>Admin Console</h1><div class=card><p class=fail>403-ish: you found the admin area.</p>"
                "<p class=muted>Restricted. (bust found this via <code>/admin</code>.)</p></div>"))
            return

        if path == "/search":
            params = parse_qs(parsed.query)
            hit = sorted(KNOWN_PARAMS.intersection(params.keys()))
            if hit:
                rows = "".join(f"<div class=pill>{p} = {params[p][0]}</div>" for p in hit)
                self._send(200, page("Search",
                    f"<h1>Search</h1><div class=card><p class=ok>Recognized {len(hit)} parameter(s):</p>"
                    f"<div class=grid>{rows}</div>"
                    "<p class=muted>Extra content here makes the body larger than the baseline, "
                    "so ffuf's autocalibration flags this as a hit.</p></div>"))
            else:
                self._send(200, page("Search",
                    "<h1>Search</h1><div class=card><p class=muted>No recognized parameter.</p></div>"))
            return

        if path == "/login":
            self._send(200, page("Sign in",
                "<h1>Sign in</h1>"
                "<form method=post action=/login class=card>"
                "<label>Username</label><input name=user autocomplete=off autofocus>"
                "<label>Password</label><input name=pass type=password autocomplete=off>"
                "<button>Sign in</button>"
                "<p class=muted style='margin-top:14px'>Hint for brute testing: weak creds live here.</p>"
                "</form>"))
            return

        if path in RAW:
            self._send(200, RAW[path], "text/plain")
            return

        self._send(404, page("Not found", "<h1>404</h1><div class=card><p class=muted>No such path.</p></div>"))

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/login":
            self._send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        user = (form.get("user") or [""])[0]
        pw = (form.get("pass") or [""])[0]
        if (user, pw) in VALID_CREDS:
            self._send(200, page("Welcome",
                f"<h1 class=ok>&#10003; Authenticated</h1>"
                f"<div class=card><p>Welcome back, <code>{user}</code>.</p>"
                "<p class=muted>You are signed in to the Obliquity Test Lab. "
                "<code>brute</code> just recovered these credentials.</p>"
                "<div class=grid><span class=pill>role: operator</span>"
                "<span class=pill>session: lab</span></div></div>"
                "<p><a href=/login>Sign out</a></p>"))
        else:
            self._send(200, page("Sign in",
                f"<h1 class=fail>{LOGIN_FAIL_MARKER}</h1>"
                "<form method=post action=/login class=card>"
                "<label>Username</label><input name=user autocomplete=off autofocus>"
                "<label>Password</label><input name=pass type=password autocomplete=off>"
                "<button>Sign in</button></form>"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Obliquity test web target (localhost only)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep it localhost)")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    wild = "  [WILDCARD/soft-404 mode]" if os.environ.get("OBLIQUITY_LAB_WILDCARD") else ""
    print("\n".join(BANNER.splitlines()))
    print(f"\nObliquity Test Lab web target -> http://{args.host}:{args.port}{wild}")
    print("bust / fuzz / brute-http target. Ctrl-C to stop. See testlab/README.md.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
