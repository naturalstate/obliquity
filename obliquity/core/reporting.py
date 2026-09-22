from __future__ import annotations

import html
from collections import Counter, defaultdict
from pathlib import Path
from sqlite3 import Row


REPORT_BANNER = r"""
      ___.   .__  .__             .__  __
  ____\_ |__ |  | |__| ________ __|__|/  |_ ___.__.
 /  _ \| __ \|  | |  |/ ____/  |  \  \   __<   |  |
(  <_> ) \_\ \  |_|  < <_|  |  |  /  ||  |  \___  |
 \____/|___  /____/__/\__   |____/|__||__|  / ____|
           \/            |__|               \/
"""


def _esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def generate_html(project: Row, runs: list[Row], findings: list[Row], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    status_counts = Counter(f["status_code"] for f in findings)
    host_counts = Counter(f["host_url"] for f in findings)
    stage_counts = Counter(f["stage_name"] for f in findings)

    summary_cards = "".join(
        f"<div class='card'><div class='num'>{_esc(v)}</div><div class='label'>{_esc(k)}</div></div>"
        for k, v in [
            ("findings", len(findings)),
            ("runs", len(runs)),
            ("completed", sum(1 for r in runs if r["status"] == "completed")),
            ("failed", sum(1 for r in runs if r["status"] == "failed")),
        ]
    )

    status_rows = "".join(
        f"<tr><td>{_esc(status)}</td><td>{count}</td></tr>"
        for status, count in sorted(status_counts.items(), key=lambda x: (x[0] is None, x[0]))
    )
    host_rows = "".join(
        f"<tr><td>{_esc(host)}</td><td>{count}</td></tr>"
        for host, count in sorted(host_counts.items())
    )
    stage_rows = "".join(
        f"<tr><td>{_esc(stage)}</td><td>{count}</td></tr>"
        for stage, count in sorted(stage_counts.items())
    )

    run_rows = "".join(
        f"""
        <tr>
          <td>{_esc(r['stage_name'])}</td>
          <td>{_esc(r['gameplan_name'])}</td>
          <td>{_esc(r['status'])}</td>
          <td>{_esc(r['exit_code'])}</td>
          <td><code>{_esc(r['command'])}</code></td>
        </tr>
        """
        for r in runs
    )

    finding_rows = "".join(
        f"""
        <tr>
          <td>{_esc(f['status_code'])}</td>
          <td><a href="{_esc(f['url'])}" target="_blank" rel="noreferrer">{_esc(f['url'])}</a></td>
          <td>{_esc(f['content_length'])}</td>
          <td>{_esc(f['words'])}</td>
          <td>{_esc(f['lines'])}</td>
          <td>{_esc(f['redirect'])}</td>
          <td>{_esc(f['stage_name'])}</td>
          <td>{_esc(f['source'])}</td>
        </tr>
        """
        for f in findings
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Obliquity Report - {_esc(project['name'])}</title>
  <style>
    :root {{ --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#c9d1d9; --muted:#8b949e; --accent:#2dd4bf; --link:#58a6ff; }}
    body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--text); }}
    header {{ padding:28px 36px; border-bottom:1px solid var(--border); }}
    .banner {{
      display:inline-block;
      margin:0 0 18px 0;
      font-family:"SFMono-Regular", Consolas, "Liberation Mono", monospace;
      font-size:13px;
      line-height:1.05;
      white-space:pre;
      letter-spacing:0;
      background:linear-gradient(90deg,#ff004c,#ff7a00,#ffe600,#00e676,#00c2ff,#7c4dff,#ff00d4);
      -webkit-background-clip:text;
      background-clip:text;
      color:transparent;
      font-weight:700;
    }}
    h1 {{ margin:0 0 6px 0; font-size:28px; }}
    h2 {{ margin-top:32px; }}
    .muted {{ color:var(--muted); }}
    main {{ padding:24px 36px 60px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px; margin:20px 0; }}
    .card {{ background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:18px; }}
    .num {{ color:var(--accent); font-size:30px; font-weight:700; }}
    .label {{ color:var(--muted); text-transform:uppercase; font-size:12px; letter-spacing:.08em; }}
    table {{ width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--border); border-radius:12px; overflow:hidden; margin:14px 0 28px; }}
    th, td {{ border-bottom:1px solid var(--border); padding:10px 12px; text-align:left; vertical-align:top; font-size:14px; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
    tr:hover td {{ background:#1f2630; }}
    a {{ color:var(--link); text-decoration:none; }}
    code {{ white-space:pre-wrap; color:#f0883e; font-size:12px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:18px; }}
  </style>
</head>
<body>
<header>
  <pre class="banner">{_esc(REPORT_BANNER)}</pre>
  <h1>Obliquity Bust Report</h1>
  <div class="muted">Project: {_esc(project['name'])}</div>
</header>
<main>
  <section class="cards">{summary_cards}</section>

  <section class="grid">
    <div>
      <h2>Status codes</h2>
      <table><thead><tr><th>Status</th><th>Count</th></tr></thead><tbody>{status_rows}</tbody></table>
    </div>
    <div>
      <h2>Hosts</h2>
      <table><thead><tr><th>Host</th><th>Findings</th></tr></thead><tbody>{host_rows}</tbody></table>
    </div>
    <div>
      <h2>Stages</h2>
      <table><thead><tr><th>Stage</th><th>Findings</th></tr></thead><tbody>{stage_rows}</tbody></table>
    </div>
  </section>

  <h2>Findings</h2>
  <table>
    <thead><tr><th>Status</th><th>URL</th><th>Length</th><th>Words</th><th>Lines</th><th>Redirect</th><th>Stage</th><th>Source</th></tr></thead>
    <tbody>{finding_rows}</tbody>
  </table>

  <h2>Runs</h2>
  <table>
    <thead><tr><th>Stage</th><th>Gameplan</th><th>Status</th><th>Exit</th><th>Command</th></tr></thead>
    <tbody>{run_rows}</tbody>
  </table>
</main>
</body>
</html>
"""
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path
