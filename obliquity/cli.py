from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from obliquity.core.database import (
    add_host,
    connect,
    create_project,
    get_findings,
    get_host,
    get_project,
    get_runs,
    list_hosts,
)
from obliquity.core.gameplan import find_builtin_gameplan, load_gameplan
from obliquity.core.reporting import generate_html
from obliquity.core.runner import preview_plan, run_gameplan

APP_DIR = Path(os.environ.get("OBLIQUITY_HOME", Path.home() / ".obliquity"))
DB_PATH = APP_DIR / "obliquity.db"
PROJECTS_DIR = APP_DIR / "projects"


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def resolve_gameplan(name_or_path: str):
    path = Path(name_or_path)
    if path.exists():
        return load_gameplan(path)
    return load_gameplan(find_builtin_gameplan(name_or_path))


def require_project(conn, name: str):
    project = get_project(conn, name)
    if project is None:
        die(f"project not found: {name}")
    return project


def cmd_project_create(args) -> None:
    conn = connect(DB_PATH)
    root = PROJECTS_DIR / args.name
    project = create_project(conn, args.name, root)
    print(f"Created project: {project['name']}")
    print(f"Root: {project['root_dir']}")


def cmd_host_add(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = add_host(conn, project["id"], args.url, args.profile, args.server, args.tech, args.notes)
    print(f"Added host: {host['url']} ({host['profile']})")


def cmd_host_list(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    hosts = list_hosts(conn, project["id"])
    if not hosts:
        print("No hosts added yet.")
        return
    for host in hosts:
        print(f"{host['url']}  profile={host['profile']}  server={host['server'] or '-'}  tech={host['tech'] or '-'}")


def cmd_bust_plan(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = get_host(conn, project["id"], args.url)
    if host is None:
        die(f"host not found in project: {args.url}")
    gameplan = resolve_gameplan(args.gameplan)
    print(f"Gameplan: {gameplan.name}")
    if gameplan.description:
        print(f"Description: {gameplan.description}")
    print(f"Target: {host['url']}")
    print()
    for row in preview_plan(host["url"], gameplan):
        ext = ",".join(row["extensions"]) if row["extensions"] else "none"
        recurse = f"yes depth={row['depth']}" if row["recursion"] else "no"
        print(f"{row['number']}. {row['name']}")
        print(f"   wordlist: {row['wordlist']}")
        print(f"   extensions: {ext}")
        print(f"   recursion: {recurse}")
        print(f"   status codes: {','.join(str(x) for x in row['status_codes'])}")


def cmd_bust_run(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = get_host(conn, project["id"], args.url)
    if host is None:
        die(f"host not found in project: {args.url}. Add it first with: obliquity host add")
    gameplan = resolve_gameplan(args.gameplan)
    results = run_gameplan(
        conn,
        project,
        host,
        gameplan,
        force=args.force,
        dry_run=args.dry_run,
        rate_limit=args.rate_limit,
        threads=args.threads,
        proxy=args.proxy,
        headers=args.header or [],
    )
    for item in results:
        if item["action"] == "skipped":
            print(f"SKIP {item['stage']}: {item['reason']}")
        elif item["action"] == "planned":
            print(f"PLAN {item['stage']}: {item['command']}")
        else:
            print(f"{item['status'].upper()} {item['stage']}: new findings={item['new_findings']} exit={item['exit_code']}")
            if item.get("error"):
                print(f"  {item['error']}")


def cmd_bust_resume(args) -> None:
    # Resume is implemented by re-running the selected gameplan. Completed stage fingerprints are skipped.
    cmd_bust_run(args)


def cmd_report_html(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    runs = get_runs(conn, project["id"])
    findings = get_findings(conn, project["id"])
    output = Path(args.output) if args.output else Path(project["root_dir"]) / "report.html"
    generate_html(project, runs, findings, output)
    print(f"Report written: {output}")


def cmd_runs(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    runs = get_runs(conn, project["id"], args.status)
    for run in runs:
        print(f"{run['id']:>4} {run['status']:<10} {run['stage_name']:<24} {run['gameplan_name']} exit={run['exit_code']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="obliquity", description="Obliquity Bust MVP: staged feroxbuster orchestration")
    sub = p.add_subparsers(dest="cmd", required=True)

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="project_cmd", required=True)
    pc = project_sub.add_parser("create")
    pc.add_argument("name")
    pc.set_defaults(func=cmd_project_create)

    host = sub.add_parser("host")
    host_sub = host.add_subparsers(dest="host_cmd", required=True)
    ha = host_sub.add_parser("add")
    ha.add_argument("project")
    ha.add_argument("url")
    ha.add_argument("--profile", default="generic")
    ha.add_argument("--server")
    ha.add_argument("--tech")
    ha.add_argument("--notes")
    ha.set_defaults(func=cmd_host_add)

    hl = host_sub.add_parser("list")
    hl.add_argument("project")
    hl.set_defaults(func=cmd_host_list)

    bust = sub.add_parser("bust")
    bust_sub = bust.add_subparsers(dest="bust_cmd", required=True)

    bp = bust_sub.add_parser("plan")
    bp.add_argument("project")
    bp.add_argument("url")
    bp.add_argument("--gameplan", default="generic-quick")
    bp.set_defaults(func=cmd_bust_plan)

    br = bust_sub.add_parser("run")
    br.add_argument("project")
    br.add_argument("url")
    br.add_argument("--gameplan", default="generic-quick")
    br.add_argument("--force", action="store_true", help="rerun completed stages")
    br.add_argument("--dry-run", action="store_true", help="print commands without running feroxbuster")
    br.add_argument("--rate-limit", type=int)
    br.add_argument("--threads", type=int)
    br.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    br.add_argument("--header", action="append", help="header passed to feroxbuster; repeatable")
    br.set_defaults(func=cmd_bust_run)

    bres = bust_sub.add_parser("resume")
    bres.add_argument("project")
    bres.add_argument("url")
    bres.add_argument("--gameplan", default="generic-quick")
    bres.add_argument("--force", action="store_true")
    bres.add_argument("--dry-run", action="store_true")
    bres.add_argument("--rate-limit", type=int)
    bres.add_argument("--threads", type=int)
    bres.add_argument("--proxy")
    bres.add_argument("--header", action="append")
    bres.set_defaults(func=cmd_bust_resume)

    runs = sub.add_parser("runs")
    runs.add_argument("project")
    runs.add_argument("--status")
    runs.set_defaults(func=cmd_runs)

    report = sub.add_parser("report")
    report_sub = report.add_subparsers(dest="report_cmd", required=True)
    rh = report_sub.add_parser("html")
    rh.add_argument("project")
    rh.add_argument("--output")
    rh.set_defaults(func=cmd_report_html)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
