"""A tiny localhost report browser: `obliquity report serve`.

Lists every project and serves each one's HTML report on click, so you can flip
between projects in the browser without regenerating files by hand. Stdlib only,
binds to 127.0.0.1. Reports are generated fresh on each view.
"""

from __future__ import annotations

import html
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from obliquity.core.database import (
    connect,
    get_cracked_hashes,
    get_crack_runs,
    get_findings,
    get_found_credentials,
    get_login_runs,
    get_project,
    get_runs,
    list_projects,
)
from obliquity.core.reporting import generate_html

_DB_PATH: Path | None = None

INDEX_CSS = """
body{margin:0;background:#0d1117;color:#c9d1d9;font-family:ui-sans-serif,-apple-system,Segoe UI,sans-serif;}
.wrap{max-width:820px;margin:0 auto;padding:36px 20px;}
h1{font-size:26px;} .muted{color:#8b949e;}
a{color:#58a6ff;text-decoration:none;} a:hover{text-decoration:underline;}
.row{display:flex;justify-content:space-between;align-items:center;background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px 18px;margin:12px 0;}
.name{font-size:17px;font-weight:600;} .meta{color:#8b949e;font-size:13px;font-family:monospace;}
.btn{background:#2dd4bf;color:#04231f;border-radius:9px;padding:8px 16px;font-weight:700;}
"""


def _report_html(conn, project) -> str:
    pid = project["id"]
    tmp = Path(tempfile.gettempdir()) / f"obliquity-report-{pid}.html"
    generate_html(
        project,
        get_runs(conn, pid),
        get_findings(conn, pid),
        tmp,
        crack_runs=get_crack_runs(conn, pid),
        cracked_hashes=get_cracked_hashes(conn, pid),
        login_runs=get_login_runs(conn, pid),
        found_credentials=get_found_credentials(conn, pid),
    )
    return tmp.read_text(encoding="utf-8")


def _index_html(projects) -> str:
    rows = "".join(
        f"<div class=row><div><div class=name>{html.escape(p['name'])}</div>"
        f"<div class=meta>{p['host_count']} hosts &middot; {p['run_count']} runs &middot; {p['job_count']} crack jobs &middot; {html.escape(str(p['created_at']))}</div></div>"
        f"<a class=btn href='/r/{html.escape(p['name'])}'>Open report &rarr;</a></div>"
        for p in projects
    ) or "<p class=muted>No projects yet. Create one with <code>obliquity project create &lt;name&gt;</code>.</p>"
    return f"""<!doctype html><html><head><meta charset=utf-8><title>Obliquity Reports</title>
<style>{INDEX_CSS}</style></head><body><div class=wrap>
<h1>Obliquity Reports</h1><p class=muted>Pick a project to view its report (generated fresh each time).</p>
{rows}</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: str, ctype: str = "text/html") -> None:
        data = body.encode("utf-8", "replace")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        conn = connect(_DB_PATH)
        if path == "/":
            self._send(200, _index_html(list_projects(conn)))
            return
        if path.startswith("/r/"):
            name = unquote(path[3:])
            project = get_project(conn, name)
            if project is None:
                self._send(404, f"<p>Unknown project: {html.escape(name)}. <a href='/'>&larr; back</a></p>")
                return
            self._send(200, _report_html(conn, project))
            return
        self._send(404, "<p>Not found. <a href='/'>&larr; back</a></p>")


def serve_reports(db_path: Path, *, host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True) -> None:
    global _DB_PATH
    _DB_PATH = db_path
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Obliquity report browser -> {url}   (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
