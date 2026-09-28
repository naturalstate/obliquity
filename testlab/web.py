"""Local test target for Obliquity -- bust, fuzz, and brute(http).

Two servers, one process, so the control plane never pollutes the attack surface:

  * CONTENT server  (--port, default 8000): the site you scan -- dirs/files
    (bust), /search params (fuzz), a login form (brute). Every request here is
    logged. It serves NO /admin, so a scan never "finds" the control panel.
  * ADMIN server    (--admin-port, default 8001): your operator console -- live
    request log of the content server, edit paths/params, import config
    profiles, links to reports. Its own requests are never logged.

Stdlib only; both bind to 127.0.0.1. Situation toggles (content paths only):
  OBLIQUITY_LAB_WILDCARD=1        every path -> 200 (soft-404; tests the flood guard)
  OBLIQUITY_LAB_RATELIMIT=<n>     over n req/s -> 429
  OBLIQUITY_LAB_FLAKY=<pct>       pct% -> random 500
  OBLIQUITY_LAB_SLOW=<seconds>    delay every response

    python -m testlab.web
    python -m testlab.web --port 8000 --admin-port 8001 --config testlab/profiles/wordpress.json

See the lab guide (testlab/README.md).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border);white-space:nowrap;} th{color:var(--muted);}
.s2{color:#00e676}.s3{color:#58a6ff}.s4{color:#ffb84d}.s5{color:#ff5f5f}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;} @media(max-width:680px){.cols{grid-template-columns:1fr}}
"""


class LabState:
    def __init__(self) -> None:
        self.server = {"name": "Obliquity Test Lab", "header": "Obliquity-Lab"}
        self.login_path = "/login"
        self.fail_marker = "Login failed"
        self.creds = [["admin", "password123"], ["user", "letmein"], ["root", "toor"]]
        self.params = {"q", "id", "page", "debug", "search", "admin", "api_key", "redirect"}
        self.paths: dict[str, dict] = {
            "/config.php": {"status": 200, "body": "<?php $db_password='hunter2'; ?>", "ctype": "text/plain"},
            "/config.bak": {"status": 200, "body": "db_password=hunter2\napi_key=sk-test-999", "ctype": "text/plain"},
            "/backup": {"status": 200, "body": "backup area", "ctype": "text/plain"},
            "/backup/": {"status": 200, "body": "index of /backup:\n db.sql\n config.bak", "ctype": "text/plain"},
            "/backup.zip": {"status": 200, "body": "PK\x03\x04 (fake zip)", "ctype": "application/zip"},
            "/.env": {"status": 200, "body": "DB_PASSWORD=hunter2\nSECRET_KEY=obliquity-lab", "ctype": "text/plain"},
            "/.git/HEAD": {"status": 200, "body": "ref: refs/heads/main", "ctype": "text/plain"},
            "/robots.txt": {"status": 200, "body": "User-agent: *\nDisallow: /backup", "ctype": "text/plain"},
            "/api": {"status": 200, "body": '{"name":"lab-api","version":"v1"}', "ctype": "application/json"},
            "/api/": {"status": 200, "body": '{"routes":["/api/users","/api/login"]}', "ctype": "application/json"},
            "/uploads/": {"status": 200, "body": "index of /uploads", "ctype": "text/plain"},
            "/old/": {"status": 200, "body": "old site", "ctype": "text/plain"},
            "/phpinfo.php": {"status": 200, "body": "phpinfo() OBLIQUITY-LAB", "ctype": "text/plain"},
            # --- link-extraction demo -------------------------------------
            # These paths have deliberately obscure names that appear in NO
            # common wordlist, so a plain `bust` never guesses them. They are
            # only reachable by parsing links out of response bodies -- exactly
            # what feroxbuster's link extraction (on by default) does. The home
            # page and /assets/app.js below point at them, so a default scan
            # discovers them and `--no-extract-links` does not.
            "/assets/app.js": {"status": 200, "ctype": "application/javascript",
                "body": "// lab bootstrap\nfetch('/api/v7-legacy/tokens.json');\n"
                        "const dash='/dev-x9f2-console/';\nimport('/static/z3-widgets/loader.mjs');\n"},
            "/api/v7-legacy/tokens.json": {"status": 200, "ctype": "application/json",
                "body": '{"token":"lab-legacy-9f2","note":"found via link extraction"}'},
            "/dev-x9f2-console/": {"status": 200, "body": "internal dev console (link-extraction only)"},
            "/static/z3-widgets/loader.mjs": {"status": 200, "ctype": "application/javascript",
                "body": "export const build='z3';  // reached via JS import link"},
            "/reports/q4-internal-8kd.html": {"status": 200, "ctype": "text/html",
                "body": "<h1>Q4 internal (link-extraction only)</h1>"},
        }
        self.log: deque = deque(maxlen=50000)
        self.verbose = False
        self.access_log_path: str | None = None
        self.reports_url = "http://127.0.0.1:8787/"
        self.admin_url = "http://127.0.0.1:8001/"
        self._lock = threading.Lock()
        self._rl_sec = 0
        self._rl_count = 0

    def rate_hit(self, limit: int) -> bool:
        now = int(time.time())
        with self._lock:
            if now != self._rl_sec:
                self._rl_sec = now
                self._rl_count = 0
            self._rl_count += 1
            return self._rl_count > limit

    def write_access_log(self, line: str) -> None:
        if not self.access_log_path:
            return
        try:
            with self._lock, open(self.access_log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def load_config(self, path: str) -> None:
        self.apply_config(json.loads(open(path, encoding="utf-8").read()))

    def apply_config(self, data: dict) -> None:
        if "server" in data:
            self.server.update(data["server"])
        if "login_path" in data:
            self.login_path = data["login_path"]
        if "fail_marker" in data:
            self.fail_marker = data["fail_marker"]
        if "reports_url" in data:
            self.reports_url = data["reports_url"]
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


def _profiles_dir() -> Path:
    return Path(__file__).resolve().parent / "profiles"


def _profile_names() -> list[str]:
    d = _profiles_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []


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


class QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class _Base(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _write(self, code: int, body: str, ctype: str, cookie: str | None = None):
        data = body.encode("utf-8", "replace")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Server", STATE.server.get("header", "Obliquity-Lab"))
            if STATE.server.get("powered_by"):
                self.send_header("X-Powered-By", STATE.server["powered_by"])
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        return len(data)


# ---------------------------------------------------------------------------
# CONTENT server -- the thing you scan. Every request is logged. No /admin.
# ---------------------------------------------------------------------------
class ContentHandler(_Base):
    server_version = "obliquity-testlab/3.0"

    def _record(self, status: int, size: int) -> None:
        if self.path == "/favicon.ico":
            return
        ip = self.client_address[0] if self.client_address else "-"
        ua = self.headers.get("User-Agent") or "-"
        STATE.log.append({"t": time.strftime("%H:%M:%S"), "m": self.command,
                          "p": self.path[:200], "s": status, "ip": ip, "ua": ua[:160], "sz": size})
        if STATE.verbose:
            print(f"{time.strftime('%H:%M:%S')} {ip} {self.command} {self.path} -> {status} {size}b")
        STATE.write_access_log(
            f'{ip} - - [{time.strftime("%d/%b/%Y:%H:%M:%S %z")}] '
            f'"{self.command} {self.path} {self.request_version}" {status} {size} '
            f'"{self.headers.get("Referer","-")}" "{ua}"')

    def _send(self, code, body, ctype="text/html", cookie=None):
        size = self._write(code, body, ctype, cookie)
        self._record(code, size)

    def _degrade(self, path: str):
        slow = os.environ.get("OBLIQUITY_LAB_SLOW")
        if slow:
            try:
                time.sleep(float(slow))
            except ValueError:
                pass
        rl = os.environ.get("OBLIQUITY_LAB_RATELIMIT")
        if rl:
            try:
                if STATE.rate_hit(int(rl)):
                    return (429, "429 Too Many Requests -- rate limited (OBLIQUITY_LAB_RATELIMIT)")
            except ValueError:
                pass
        flaky = os.environ.get("OBLIQUITY_LAB_FLAKY")
        if flaky:
            try:
                if random.random() * 100 < float(flaky):
                    return (500, "500 Internal Server Error (OBLIQUITY_LAB_FLAKY)")
            except ValueError:
                pass
        return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        degraded = self._degrade(path)
        if degraded is not None:
            self._send(degraded[0], degraded[1], "text/plain")
            return
        if os.environ.get("OBLIQUITY_LAB_WILDCARD"):
            self._send(200, f"wildcard 200 for {path}")
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

    def do_POST(self) -> None:
        if urlparse(self.path).path != STATE.login_path:
            self._send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        user = (form.get("user") or [""])[0]
        pw = (form.get("pass") or [""])[0]
        if [user, pw] in STATE.creds:
            self._send(200, page("Welcome",
                f"<h1 class=ok>&#10003; Authenticated as {html.escape(user)}</h1>"
                "<div class=card>"
                f"<p>You signed in with valid credentials (<code>{html.escape(user)}</code> / "
                f"<code>{html.escape(pw)}</code>). In a real engagement, a weak login like this is "
                "exactly what Obliquity's <code>brute</code> pillar recovers.</p>"
                "<div class=grid>"
                f"<a class=pill href='{html.escape(STATE.admin_url)}' target=_blank>&rarr; Admin console</a> "
                f"<a class=pill href='{html.escape(STATE.reports_url)}' target=_blank>&rarr; Obliquity reports</a></div>"
                f"<p class=muted style='margin-top:12px'>The admin console runs on a separate port "
                f"(<a href='{html.escape(STATE.admin_url)}' target=_blank>{html.escape(STATE.admin_url)}</a>) so it "
                "never shows up in your scan of this site.</p></div>"))
        else:
            self._send(200, page("Sign in", f"<h1 class=fail>{html.escape(STATE.fail_marker)}</h1>" + self._login_form_inner()))

    def _home(self) -> str:
        return page("Home",
            f"<h1>Welcome to {html.escape(STATE.server['name'])}</h1>"
            "<p class=muted>A deliberately-vulnerable localhost target for practicing every pillar.</p>"
            "<div class=card><div class=grid>"
            "<span class=pill>bust &rarr; hidden dirs/files</span>"
            "<span class=pill>fuzz &rarr; /search params</span>"
            "<span class=pill>brute &rarr; login form</span>"
            "<span class=pill>crack &rarr; hash fixtures</span></div></div>"
            f"<p><a href='{html.escape(STATE.login_path)}'>&rarr; Sign in</a></p>"
            # Link-extraction demo: these obscure paths are in no wordlist, so a
            # plain bust misses them -- feroxbuster only reaches them by parsing
            # links out of this page's body (and the JS it loads). Run a default
            # scan vs. `--no-extract-links` to see the difference.
            "<script src='/assets/app.js'></script>"
            "<p style='display:none'>"
            "<a href='/reports/q4-internal-8kd.html'>q4</a> "
            "<a href='/dev-x9f2-console/'>console</a></p>")

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


# ---------------------------------------------------------------------------
# ADMIN server -- operator console on a separate port. Not logged, not scannable.
# ---------------------------------------------------------------------------
_LOG_JS = """
const cls={2:'s2',3:'s3',4:'s4',5:'s5'};
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function rows(j){return j.length?j.map(e=>`<tr><td>${e.t}</td><td>${esc(e.ip)}</td><td>${e.m}</td><td>${esc(e.p)}</td><td class="${cls[Math.floor(e.s/100)]||''}">${e.s}</td></tr>`).join(''):'<tr><td colspan=5 class=muted>waiting for requests...</td></tr>';}
async function poll(url,el,cnt){try{const r=await fetch(url);const j=await r.json();if(cnt)document.getElementById(cnt).textContent='('+j.length.toLocaleString()+' shown)';document.getElementById(el).innerHTML=rows(j);}catch(e){}}
"""


class AdminHandler(_Base):
    server_version = "obliquity-testlab-admin/3.0"

    def _send(self, code, body, ctype="text/html"):
        self._write(code, body, ctype)  # admin requests are NOT logged

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return parse_qs(self.rfile.read(length).decode("utf-8", "replace"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/logs.json":
            self._send(200, json.dumps(list(STATE.log)[-40:][::-1]), "application/json")
        elif path == "/log.json":
            self._send(200, json.dumps(list(STATE.log)[-5000:][::-1]), "application/json")
        elif path == "/log":
            self._send(200, self._detailed())
        elif path in ("/", "/admin", "/admin/"):
            self._send(200, self._dashboard())
        else:
            self._send(404, page("Not found", "<h1>404</h1><div class=card><p class=muted>Admin console: try <a href=/>/</a>.</p></div>"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        form = self._form()
        msg = "done."
        if path == "/add-path":
            p = (form.get("path") or [""])[0].strip()
            body = (form.get("body") or [""])[0]
            status = int((form.get("status") or ["200"])[0] or 200)
            if p:
                if not p.startswith("/"):
                    p = "/" + p
                STATE.paths[p] = {"status": status, "body": body or f"added {p}", "ctype": "text/plain"}
                msg = f"added path {p} ({status})"
        elif path == "/add-param":
            name = (form.get("name") or [""])[0].strip()
            if name:
                STATE.params.add(name)
                msg = f"added param '{name}'"
        elif path == "/import":
            try:
                STATE.apply_config(json.loads((form.get("config") or ["{}"])[0]))
                msg = "config imported."
            except Exception as exc:  # noqa: BLE001
                msg = f"import failed: {exc}"
        elif path == "/load-profile":
            name = (form.get("name") or [""])[0].strip()
            f = _profiles_dir() / (name + ".json")
            if name and f.exists():
                try:
                    STATE.load_config(str(f))
                    msg = f"loaded profile '{name}' ({STATE.server['name']})"
                except Exception as exc:  # noqa: BLE001
                    msg = f"load failed: {exc}"
            else:
                msg = f"unknown profile: {name}"
        elif path == "/clear-logs":
            STATE.log.clear()
            msg = "logs cleared."
        else:
            self._send(404, "not found", "text/plain")
            return
        self._send(200, self._dashboard(banner=msg))

    def _detailed(self) -> str:
        loc = ("Also written to <code>" + html.escape(STATE.access_log_path) + "</code>"
               if STATE.access_log_path else
               "In-memory (up to 50,000). Add <code>--access-log &lt;path&gt;</code> to also write a real logfile.")
        return page("Full log",
            "<h1>Request log <span id=count class=muted style='font-size:15px'></span></h1>"
            f"<p class=muted>Newest first, live. {loc} <a href='/'>&larr; back to console</a></p>"
            "<div class=card style='max-height:80vh;overflow:auto'>"
            "<table><thead><tr><th>time</th><th>client</th><th>method</th><th>path</th><th>status</th></tr></thead>"
            "<tbody id=full><tr><td colspan=5 class=muted>loading...</td></tr></tbody></table></div>"
            "<script>" + _LOG_JS + "setInterval(()=>poll('/log.json','full','count'),1500);poll('/log.json','full','count');</script>")

    def _dashboard(self, banner: str = "") -> str:
        note = f"<div class=card><p class=ok>{html.escape(banner)}</p></div>" if banner else ""
        paths = "".join(f"<span class=pill>{html.escape(p)}</span>" for p in sorted(STATE.paths)[:60])
        params = "".join(f"<span class=pill>{html.escape(p)}</span>" for p in sorted(STATE.params))
        profile_options = "<option value=''>-- pick --</option>" + "".join(
            f"<option value='{html.escape(n)}'>{html.escape(n)}</option>" for n in _profile_names())
        body = f"""<h1>Admin console</h1>
<p class=muted>Operator console (separate port; never scanned or logged). Content server request log below.</p>
<div class=grid style="margin:6px 0 4px">
<a class=pill href="{html.escape(STATE.reports_url)}" target=_blank>&rarr; Obliquity reports</a>
<a class=pill href="/log">&rarr; full detailed log</a></div>{note}
<h2>Live request log <span class=muted style="font-size:13px">(latest 40 &middot; <a href="/log">see all</a>)</span></h2>
<div class=card><table><thead><tr><th>time</th><th>client</th><th>method</th><th>path</th><th>status</th></tr></thead>
<tbody id=log><tr><td colspan=5 class=muted>waiting for requests...</td></tr></tbody></table>
<button onclick="fetch('/clear-logs',{{method:'POST'}}).then(()=>0)">clear logs</button></div>
<div class=cols>
<div class=card><h2>Add a path (dir / file)</h2>
<form method=post action=/add-path>
<label>Path</label><input name=path placeholder="/secret/ or /db.sql">
<label>Status</label><input name=status value=200>
<label>Body (optional)</label><input name=body placeholder="file contents">
<button>Add path</button></form></div>
<div class=card><h2>Add a parameter</h2>
<form method=post action=/add-param>
<label>Name (fuzz finds it at /search?NAME=...)</label><input name=name placeholder="token">
<button>Add param</button></form>
<h2 style="margin-top:22px">Config profile</h2>
<form method=post action=/load-profile style="margin-bottom:10px">
<label>Load a shipped profile</label><select name=name>{profile_options}</select>
<button>Load profile</button></form>
<form method=post action=/import>
<label>...or choose a .json file from your computer</label>
<input type=file accept=".json,application/json" id=cfgfile>
<label style="margin-top:8px">...or paste JSON</label>
<textarea name=config id=config rows=5 placeholder='{{"paths":{{"/wp-admin/":{{"status":302}}}},"params":["s","p"]}}'></textarea>
<button>Import config</button></form></div>
</div>
<h2>Current paths ({len(STATE.paths)})</h2><div class=card><div class=grid>{paths}</div></div>
<h2>Current params ({len(STATE.params)})</h2><div class=card><div class=grid>{params}</div></div>
<script>{_LOG_JS}
setInterval(()=>poll('/logs.json','log'),1000);poll('/logs.json','log');
const _cf=document.getElementById('cfgfile');
if(_cf)_cf.onchange=e=>{{const f=e.target.files[0];if(!f)return;const r=new FileReader();r.onload=()=>{{document.getElementById('config').value=r.result;}};r.readAsText(f);}};
</script>"""
        return page("Admin", body)


def main() -> None:
    ap = argparse.ArgumentParser(description="Obliquity test target (localhost only): content + admin servers")
    ap.add_argument("--port", type=int, default=8000, help="content server port (the site you scan)")
    ap.add_argument("--admin-port", dest="admin_port", type=int, default=8001, help="admin console port")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep it localhost)")
    ap.add_argument("--config", help="load a server profile JSON (see testlab/profiles/)")
    ap.add_argument("--verbose", action="store_true", help="also print each request to stdout")
    ap.add_argument("--access-log", dest="access_log", help="also write an Apache-style access log to this file")
    ap.add_argument("--reports-url", dest="reports_url", help="URL the 'reports' links point to (default http://127.0.0.1:8787/)")
    args = ap.parse_args()
    STATE.verbose = args.verbose
    STATE.access_log_path = args.access_log
    STATE.admin_url = f"http://{args.host}:{args.admin_port}/"
    if args.reports_url:
        STATE.reports_url = args.reports_url
    if args.config:
        STATE.load_config(args.config)

    content = QuietHTTPServer((args.host, args.port), ContentHandler)
    admin = QuietHTTPServer((args.host, args.admin_port), AdminHandler)
    print("\n".join(BANNER.splitlines()))
    wild = "  [WILDCARD/soft-404]" if os.environ.get("OBLIQUITY_LAB_WILDCARD") else ""
    print(f"\n{STATE.server['name']}")
    print(f"  content (scan this) -> http://{args.host}:{args.port}{wild}")
    print(f"  admin console       -> http://{args.host}:{args.admin_port}/   (separate port; not scanned/logged)")
    print(f"  login: {STATE.creds[0][0]}/{STATE.creds[0][1]}   (Ctrl-C to stop)\n")
    threading.Thread(target=admin.serve_forever, daemon=True).start()
    try:
        content.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
