"""Local test web target for Obliquity -- exercises bust, fuzz, and brute(http).

Stdlib only, binds to 127.0.0.1 (localhost). Branded to match the app, with a
live request log + an authenticated admin center where you can add paths, files,
directories and parameters at runtime, and import a config profile to mimic a
real server / CMS (e.g. WordPress).

    python -m testlab.web                                  # http://127.0.0.1:8000
    python -m testlab.web --config testlab/profiles/wordpress.json
    python -m testlab.web --verbose                        # also print requests
    OBLIQUITY_LAB_WILDCARD=1 python -m testlab.web          # soft-404: every path 200

Log in (default admin/password123) then open /admin to watch scans live.
See the lab guide (testlab/README.md).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
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
.wrap{max-width:900px;margin:0 auto;padding:28px 20px 60px;}
pre.banner{font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace;font-size:12px;line-height:1.05;white-space:pre;font-weight:700;
  background:linear-gradient(90deg,#ff004c,#ff7a00,#ffe600,#00e676,#00c2ff,#7c4dff,#ff00d4);
  -webkit-background-clip:text;background-clip:text;color:transparent;margin:0 0 6px;}
.tag{color:var(--muted);letter-spacing:.28em;text-transform:uppercase;font-size:12px;font-family:monospace;}
h1{font-size:24px;margin:22px 0 4px;} h2{margin:26px 0 10px;font-size:16px;color:var(--accent);}
.muted{color:var(--muted);} a{color:var(--link);text-decoration:none;} a:hover{text-decoration:underline;}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:20px;margin:16px 0;}
.grid{display:flex;gap:10px;flex-wrap:wrap;} .pill{border:1px solid var(--border);border-radius:999px;padding:6px 12px;font-size:13px;color:var(--muted);}
label{display:block;color:var(--muted);font-size:13px;margin:10px 0 6px;}
input,textarea,select{width:100%;background:#0d1117;border:1px solid var(--border);border-radius:10px;color:var(--text);padding:10px 12px;font-size:14px;font-family:inherit;}
input:focus,textarea:focus{outline:none;border-color:var(--accent);}
button{margin-top:14px;background:var(--accent);color:#04231f;border:0;border-radius:10px;padding:11px 16px;font-size:14px;font-weight:700;cursor:pointer;}
.ok{color:#00e676;font-weight:700;} .fail{color:#ff5f5f;font-weight:700;}
code{color:#f0883e;font-family:monospace;} footer{margin-top:40px;color:var(--muted);font-size:12px;font-family:monospace;}
table{width:100%;border-collapse:collapse;font-family:monospace;font-size:13px;}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border);} th{color:var(--muted);}
.s2{color:#00e676}.s3{color:#58a6ff}.s4{color:#ffb84d}.s5{color:#ff5f5f}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;} @media(max-width:680px){.cols{grid-template-columns:1fr}}
"""

# ---------------------------------------------------------------------------
# Mutable lab state (a config profile can override all of this at startup or
# from the admin center at runtime).
# ---------------------------------------------------------------------------
class LabState:
    def __init__(self) -> None:
        self.server = {"name": "Obliquity Test Lab", "header": "Obliquity-Lab"}
        self.login_path = "/login"
        self.fail_marker = "Login failed"
        self.creds = [["admin", "password123"], ["user", "letmein"], ["root", "toor"]]
        self.params = {"q", "id", "page", "debug", "search", "admin", "api_key", "redirect"}
        # path -> {"status": int, "body": str, "ctype": str}
        self.paths: dict[str, dict] = {
            "/config.php": {"status": 200, "body": "<?php $db_password='hunter2'; ?>", "ctype": "text/plain"},
            "/config.bak": {"status": 200, "body": "db_password=hunter2\napi_key=sk-test-999", "ctype": "text/plain"},
            "/backup": {"status": 200, "body": "backup area", "ctype": "text/plain"},
            "/backup/": {"status": 200, "body": "index of /backup:\n db.sql\n config.bak", "ctype": "text/plain"},
            "/backup.zip": {"status": 200, "body": "PK\x03\x04 (fake zip)", "ctype": "application/zip"},
            "/.env": {"status": 200, "body": "DB_PASSWORD=hunter2\nSECRET_KEY=obliquity-lab", "ctype": "text/plain"},
            "/.git/HEAD": {"status": 200, "body": "ref: refs/heads/main", "ctype": "text/plain"},
            "/robots.txt": {"status": 200, "body": "User-agent: *\nDisallow: /admin\nDisallow: /backup", "ctype": "text/plain"},
            "/api": {"status": 200, "body": '{"name":"lab-api","version":"v1"}', "ctype": "application/json"},
            "/api/": {"status": 200, "body": '{"routes":["/api/users","/api/login"]}', "ctype": "application/json"},
            "/uploads/": {"status": 200, "body": "index of /uploads", "ctype": "text/plain"},
            "/old/": {"status": 200, "body": "old site", "ctype": "text/plain"},
            "/phpinfo.php": {"status": 200, "body": "phpinfo() OBLIQUITY-LAB", "ctype": "text/plain"},
        }
        self.log: deque = deque(maxlen=50000)  # keep tens of thousands for a big scan
        self.sessions: set[str] = set()
        self.verbose = False
        self.access_log_path: str | None = None
        self._lock = threading.Lock()

    def write_access_log(self, line: str) -> None:
        if not self.access_log_path:
            return
        try:
            with self._lock, open(self.access_log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def load_config(self, path: str) -> None:
        data = json.loads(open(path, encoding="utf-8").read())
        self.apply_config(data)

    def apply_config(self, data: dict) -> None:
        if "server" in data:
            self.server.update(data["server"])
        if "login_path" in data:
            self.login_path = data["login_path"]
        if "fail_marker" in data:
            self.fail_marker = data["fail_marker"]
        if "creds" in data:
            self.creds = [list(c) for c in data["creds"]]
        if data.get("params"):
            self.params |= set(data["params"])
        for p, spec in (data.get("paths") or {}).items():
            if isinstance(spec, str):
                spec = {"status": 200, "body": spec, "ctype": "text/plain"}
            spec.setdefault("status", 200)
            spec.setdefault("ctype", "text/html" if "<" in str(spec.get("body", "")) else "text/plain")
            self.paths[p] = spec


STATE = LabState()


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - {html.escape(STATE.server['name'])}</title><style>{CSS}</style></head>
<body><div class=wrap>
<pre class=banner>{BANNER}</pre>
<div class=tag>{html.escape(STATE.server['name'])}</div>
{body}
<footer>{html.escape(STATE.server['name'])} -- localhost target for bust / fuzz / crack / brute. Authorized testing only.</footer>
</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "obliquity-testlab/2.0"

    def log_message(self, *a):
        pass  # we do our own logging

    # --- helpers ----------------------------------------------------------
    def _record(self, status: int, size: int) -> None:
        # don't log the admin log-pollers or favicon -- keep the view to real traffic
        if self.path.startswith("/admin/logs.json") or self.path.startswith("/admin/log.json") or self.path == "/favicon.ico":
            return
        ip = self.client_address[0] if self.client_address else "-"
        ua = (self.headers.get("User-Agent") or "-")
        STATE.log.append({"t": time.strftime("%H:%M:%S"), "m": self.command,
                          "p": self.path[:200], "s": status, "ip": ip,
                          "ua": ua[:120], "sz": size})
        if STATE.verbose:
            print(f"{time.strftime('%H:%M:%S')} {ip} {self.command} {self.path} -> {status} {size}b")
        # Apache "combined"-style line to the real logfile, if configured.
        STATE.write_access_log(
            f'{ip} - - [{time.strftime("%d/%b/%Y:%H:%M:%S %z")}] '
            f'"{self.command} {self.path} {self.request_version}" {status} {size} '
            f'"{self.headers.get("Referer","-")}" "{ua}"')

    def _send(self, code: int, body: str, ctype: str = "text/html", cookie: str | None = None) -> None:
        data = body.encode("utf-8", "replace")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Server", STATE.server.get("header", "Obliquity-Lab"))
        if STATE.server.get("powered_by"):
            self.send_header("X-Powered-By", STATE.server["powered_by"])
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self._record(code, len(data))
        if self.command != "HEAD":
            self.wfile.write(data)

    def _authed(self) -> bool:
        raw = self.headers.get("Cookie")
        if not raw:
            return False
        ck = SimpleCookie(raw)
        return "labsession" in ck and ck["labsession"].value in STATE.sessions

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return parse_qs(self.rfile.read(length).decode("utf-8", "replace"))

    # --- GET --------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if os.environ.get("OBLIQUITY_LAB_WILDCARD"):
            self._send(200, f"wildcard 200 for {path}")
            return

        if path == "/admin/logs.json":
            if not self._authed():
                self._send(403, "[]", "application/json")
            else:
                self._send(200, json.dumps(list(STATE.log)[-150:][::-1]), "application/json")
            return

        if path == "/admin/log.json":  # full log for the detailed page (newest first)
            if not self._authed():
                self._send(403, "[]", "application/json")
            else:
                self._send(200, json.dumps(list(STATE.log)[-5000:][::-1]), "application/json")
            return

        if path == "/admin/log":
            self._send(200, self._full_log_page())
            return

        if path == "/admin" or path == "/admin/":
            self._send(200, self._admin_page())
            return

        if path == "/":
            self._send(200, self._home())
            return

        if path == "/search":
            self._send(200, self._search(parse_qs(parsed.query)))
            return

        if path == STATE.login_path:
            self._send(200, self._login_form())
            return

        if path in STATE.paths:
            spec = STATE.paths[path]
            self._send(int(spec.get("status", 200)), str(spec.get("body", "")), spec.get("ctype", "text/plain"))
            return

        self._send(404, page("Not found", "<h1>404</h1><div class=card><p class=muted>No such path.</p></div>"))

    def do_HEAD(self) -> None:
        self.do_GET()

    # --- POST -------------------------------------------------------------
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == STATE.login_path:
            self._do_login()
            return
        if path.startswith("/admin/"):
            self._do_admin_action(path)
            return
        self._send(404, "not found", "text/plain")

    def _do_login(self) -> None:
        form = self._form()
        user = (form.get("user") or [""])[0]
        pw = (form.get("pass") or [""])[0]
        if [user, pw] in STATE.creds:
            token = secrets.token_hex(16)
            STATE.sessions.add(token)
            self._send(200, page("Welcome",
                f"<h1 class=ok>&#10003; Authenticated</h1>"
                f"<div class=card><p>Welcome back, <code>{html.escape(user)}</code>. "
                "<code>brute</code> just recovered these credentials.</p>"
                "<p><a href=/admin>&rarr; Open the admin center</a> (live logs + edit the site)</p></div>"
                "<p><a href='" + html.escape(STATE.login_path) + "'>Sign out</a></p>",
            ), cookie=f"labsession={token}; Path=/")
        else:
            self._send(200, page("Sign in",
                f"<h1 class=fail>{html.escape(STATE.fail_marker)}</h1>" + self._login_form_inner()))

    def _do_admin_action(self, path: str) -> None:
        if not self._authed():
            self._send(403, page("Forbidden", "<h1>403</h1><div class=card><p class=muted>Log in first.</p></div>"))
            return
        form = self._form()
        msg = "done."
        if path == "/admin/add-path":
            p = (form.get("path") or [""])[0].strip()
            body = (form.get("body") or [""])[0]
            status = int((form.get("status") or ["200"])[0] or 200)
            if p:
                if not p.startswith("/"):
                    p = "/" + p
                STATE.paths[p] = {"status": status, "body": body or f"added {p}", "ctype": "text/plain"}
                msg = f"added path {p} ({status})"
        elif path == "/admin/add-param":
            name = (form.get("name") or [""])[0].strip()
            if name:
                STATE.params.add(name)
                msg = f"added param '{name}' (fuzz /search?{name}=...)"
        elif path == "/admin/import":
            try:
                STATE.apply_config(json.loads((form.get("config") or ["{}"])[0]))
                msg = "config imported."
            except Exception as exc:  # noqa: BLE001
                msg = f"import failed: {exc}"
        elif path == "/admin/clear-logs":
            STATE.log.clear()
            msg = "logs cleared."
        self._send(200, self._admin_page(banner=msg))

    # --- pages ------------------------------------------------------------
    def _home(self) -> str:
        return page("Home",
            f"<h1>Welcome to {html.escape(STATE.server['name'])}</h1>"
            "<p class=muted>A deliberately-vulnerable localhost target for practicing every pillar.</p>"
            "<div class=card><div class=grid>"
            "<span class=pill>bust &rarr; hidden dirs/files</span>"
            "<span class=pill>fuzz &rarr; /search params</span>"
            "<span class=pill>brute &rarr; login form</span>"
            "<span class=pill>crack &rarr; hash fixtures</span></div></div>"
            f"<p><a href='{html.escape(STATE.login_path)}'>&rarr; Sign in</a> "
            "(then open <code>/admin</code> for live logs + editing)</p>")

    def _search(self, params: dict) -> str:
        hit = sorted(STATE.params.intersection(params.keys()))
        if hit:
            rows = "".join(f"<div class=pill>{html.escape(p)} = {html.escape(params[p][0])}</div>" for p in hit)
            return page("Search", f"<h1>Search</h1><div class=card><p class=ok>Recognized {len(hit)} parameter(s):</p>"
                        f"<div class=grid>{rows}</div><p class=muted>Extra content makes the body larger than the "
                        "baseline, so ffuf flags it as a hit.</p></div>")
        return page("Search", "<h1>Search</h1><div class=card><p class=muted>No recognized parameter.</p></div>")

    def _login_form_inner(self) -> str:
        return (f"<form method=post action='{html.escape(STATE.login_path)}' class=card>"
                "<label>Username</label><input name=user autocomplete=off autofocus>"
                "<label>Password</label><input name=pass type=password autocomplete=off>"
                "<button>Sign in</button>"
                "<p class=muted style='margin-top:12px'>Weak creds live here (brute target).</p></form>")

    def _login_form(self) -> str:
        return page("Sign in", "<h1>Sign in</h1>" + self._login_form_inner())

    def _admin_page(self, banner: str = "") -> str:
        if not self._authed():
            return page("Admin", "<h1>Admin</h1><div class=card><p class=muted>Please "
                        f"<a href='{html.escape(STATE.login_path)}'>sign in</a> to view the admin center.</p></div>")
        note = f"<div class=card><p class=ok>{html.escape(banner)}</p></div>" if banner else ""
        paths = "".join(f"<span class=pill>{html.escape(p)}</span>" for p in sorted(STATE.paths)[:40])
        params = "".join(f"<span class=pill>{html.escape(p)}</span>" for p in sorted(STATE.params))
        body = f"""<h1>Admin center</h1><p class=muted>Live request log + edit the site while a scan runs.</p>{note}
<h2>Live request log &nbsp;<a href="/admin/log" style="font-size:13px">view full detailed log &rarr;</a></h2>
<div class=card><table><thead><tr><th>time</th><th>client</th><th>method</th><th>path</th><th>status</th></tr></thead>
<tbody id=log><tr><td colspan=5 class=muted>waiting for requests...</td></tr></tbody></table>
<button onclick="fetch('/admin/clear-logs',{{method:'POST'}}).then(()=>0)">clear logs</button>
<span class=muted style="margin-left:12px;font-family:monospace;font-size:12px">{html.escape('access log file: ' + STATE.access_log_path if STATE.access_log_path else 'access log file: off (start with --access-log PATH)')}</span></div>
<div class=cols>
<div class=card><h2>Add a path (dir / file)</h2>
<form method=post action=/admin/add-path>
<label>Path</label><input name=path placeholder="/secret/ or /db.sql">
<label>Status</label><input name=status value=200>
<label>Body (optional)</label><input name=body placeholder="file contents">
<button>Add path</button></form></div>
<div class=card><h2>Add a parameter</h2>
<form method=post action=/admin/add-param>
<label>Name (fuzz finds it at /search?NAME=...)</label><input name=name placeholder="token">
<button>Add param</button></form>
<h2 style="margin-top:22px">Import a config profile</h2>
<form method=post action=/admin/import>
<label>Paste JSON (see testlab/profiles/)</label><textarea name=config rows=5 placeholder='{{"paths":{{"/wp-admin/":{{"status":302}}}},"params":["s","p"]}}'></textarea>
<button>Import config</button></form></div>
</div>
<h2>Current paths ({len(STATE.paths)})</h2><div class=card><div class=grid>{paths}</div></div>
<h2>Current params ({len(STATE.params)})</h2><div class=card><div class=grid>{params}</div></div>
<script>
const cls={{2:'s2',3:'s3',4:'s4',5:'s5'}};
async function tick(){{try{{const r=await fetch('/admin/logs.json');const j=await r.json();
document.getElementById('log').innerHTML=j.length?j.map(e=>`<tr><td>${{e.t}}</td><td>${{e.ip}}</td><td>${{e.m}}</td><td>${{e.p}}</td><td class="${{cls[Math.floor(e.s/100)]||''}}">${{e.s}}</td></tr>`).join(''):'<tr><td colspan=5 class=muted>waiting for requests...</td></tr>';}}catch(e){{}}}}
setInterval(tick,1000);tick();
</script>"""
        return page("Admin", body)


    def _full_log_page(self) -> str:
        if not self._authed():
            return page("Log", "<h1>Log</h1><div class=card><p class=muted>Please "
                        f"<a href='{html.escape(STATE.login_path)}'>sign in</a>.</p></div>")
        loc = ("Also written to <code>" + html.escape(STATE.access_log_path) + "</code>"
               if STATE.access_log_path else
               "In-memory (up to 50,000). Add <code>--access-log &lt;path&gt;</code> to also write a real logfile.")
        # Live: JS polls /admin/log.json and re-renders, so it stays current while
        # a scan runs (up to 5000 newest). Auto-scroll only when already at top.
        return page("Full log",
            "<h1>Request log <span id=count class=muted style='font-size:15px'></span></h1>"
            f"<p class=muted>Newest first, live (auto-updates). {loc} "
            "<a href='/admin'>&larr; back to admin</a></p>"
            "<div class=card style='max-height:80vh;overflow:auto'>"
            "<table><thead><tr><th>time</th><th>client</th><th>method</th><th>path</th>"
            "<th>status</th><th>bytes</th><th>user-agent</th></tr></thead>"
            "<tbody id=full><tr><td colspan=7 class=muted>loading...</td></tr></tbody></table></div>"
            """<script>
const cls={2:'s2',3:'s3',4:'s4',5:'s5'};
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
async function tick(){try{const r=await fetch('/admin/log.json');const j=await r.json();
document.getElementById('count').textContent='('+j.length.toLocaleString()+' shown)';
document.getElementById('full').innerHTML=j.length?j.map(e=>`<tr><td>${e.t}</td><td>${esc(e.ip)}</td><td>${e.m}</td><td>${esc(e.p)}</td><td class="${cls[Math.floor(e.s/100)]||''}">${e.s}</td><td>${e.sz}</td><td class=muted>${esc(e.ua)}</td></tr>`).join(''):'<tr><td colspan=7 class=muted>no requests yet</td></tr>';}catch(e){}}
setInterval(tick,1500);tick();
</script>""")


def main() -> None:
    ap = argparse.ArgumentParser(description="Obliquity test web target (localhost only)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep it localhost)")
    ap.add_argument("--config", help="load a server profile JSON (see testlab/profiles/)")
    ap.add_argument("--verbose", action="store_true", help="also print each request to stdout")
    ap.add_argument("--access-log", dest="access_log", help="also write an Apache-style access log to this file")
    args = ap.parse_args()
    STATE.verbose = args.verbose
    STATE.access_log_path = args.access_log
    if args.config:
        STATE.load_config(args.config)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    wild = "  [WILDCARD/soft-404 mode]" if os.environ.get("OBLIQUITY_LAB_WILDCARD") else ""
    print("\n".join(BANNER.splitlines()))
    print(f"\n{STATE.server['name']} -> http://{args.host}:{args.port}{wild}")
    print(f"login: {STATE.creds[0][0]}/{STATE.creds[0][1]}   admin center: /admin   (Ctrl-C to stop)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
