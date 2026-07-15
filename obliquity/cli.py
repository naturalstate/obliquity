from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from obliquity.core.console import blank, bullet, c, command_block, kv, rainbow_text, section, subsection
from obliquity.core.database import (
    add_host,
    connect,
    create_project,
    delete_host,
    get_findings,
    get_host,
    get_project,
    get_runs,
    list_hosts,
    update_host,
)
from obliquity.core.gameplan import find_builtin_gameplan, list_builtin_gameplans, load_gameplan
from obliquity.core.reporting import generate_html
from obliquity.core.runner import preview_plan, run_gameplan

APP_DIR = Path(os.environ.get("OBLIQUITY_HOME", Path.home() / ".obliquity"))
DB_PATH = APP_DIR / "obliquity.db"
PROJECTS_DIR = APP_DIR / "projects"

BANNER = r"""
      ___.   .__  .__             .__  __
  ____\_ |__ |  | |__| ________ __|__|/  |_ ___.__.
 /  _ \| __ \|  | |  |/ ____/  |  \  \   __<   |  |
(  <_> ) \_\ \  |_|  < <_|  |  |  /  ||  |  \___  |
 \____/|___  /____/__/\__   |____/|__||__|  / ____|
           \/            |__|               \/
"""


def print_banner() -> None:
    print(rainbow_text(BANNER))


def die(msg: str, code: int = 1) -> None:
    print(c(f"error: {msg}", "red", bold=True), file=sys.stderr)
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


def fmt_list(values: list[str] | list[int] | tuple | None, empty: str = "none") -> str:
    if not values:
        return empty
    return ", ".join(str(x) for x in values)


def fmt_recursion(enabled: bool, depth: int | None) -> str:
    if not enabled:
        return "no"
    return f"yes, depth={depth}" if depth is not None else "yes"


def fmt_estimate(minutes: int | None) -> str:
    if minutes is None:
        return "unknown"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    return f"{hours:.1f} hr"


def total_estimate(gameplan) -> str:
    estimates = [stage.estimated_minutes for stage in gameplan.stages]
    if not estimates or any(value is None for value in estimates):
        return "unknown in MVP; stage estimates can be added to the gameplan JSON later"
    return fmt_estimate(sum(value or 0 for value in estimates))


def print_stage_summary(row: dict) -> None:
    subsection(f"Stage {row['number']}: {row['name']}", "magenta")
    bullet("Wordlist", row["wordlist"])
    bullet("Extensions", fmt_list(row["extensions"]))
    bullet("Recursion", fmt_recursion(row["recursion"], row["depth"]))
    bullet("Status codes", fmt_list(row["status_codes"]))
    bullet("Estimated time", fmt_estimate(row.get("estimated_minutes")))
    if row.get("extra_args"):
        bullet("Extra args", fmt_list(row["extra_args"]))


def print_gameplan_summary(project: dict, host: dict, gameplan, *, mode: str, args) -> None:
    section(f"Obliquity Bust: {mode}", "cyan")
    kv("Project", project["name"])
    kv("Target", host["url"])
    kv("Selected gameplan", gameplan.name)
    if gameplan.description:
        kv("Description", gameplan.description)
    kv("Stages", len(gameplan.stages))
    kv("Estimated completion", total_estimate(gameplan))
    kv("Output root", Path(project["root_dir"]) / "runs")

    option_bits = []
    if getattr(args, "proxy", None):
        option_bits.append(f"proxy={args.proxy}")
    if getattr(args, "threads", None):
        option_bits.append(f"threads={args.threads}")
    if getattr(args, "rate_limit", None):
        option_bits.append(f"rate-limit={args.rate_limit}")
    if getattr(args, "header", None):
        option_bits.append(f"headers={len(args.header)}")
    if getattr(args, "force", False):
        option_bits.append("force-rerun=true")
    kv("Run options", ", ".join(option_bits) if option_bits else "default")

    section("Stages queued", "blue")
    for row in preview_plan(host["url"], gameplan):
        print_stage_summary(row)


def print_run_event(event: dict) -> None:
    action = event.get("action")
    stage_label = f"Stage {event.get('stage_number')}/{event.get('total_stages')}: {event.get('stage')}"

    if action == "skipped":
        subsection(f"Skipped {stage_label}", "yellow")
        bullet("Reason", event.get("reason", "already completed"), color="yellow")
        return

    if action == "planned":
        subsection(f"Planned {stage_label}", "magenta")
        bullet("Wordlist", event.get("wordlist"))
        bullet("Extensions", fmt_list(event.get("extensions")))
        bullet("Recursion", fmt_recursion(bool(event.get("recursion")), event.get("depth")))
        bullet("JSON output", event.get("json_output"))
        command_block(event.get("command", ""))
        return

    if action == "starting":
        subsection(f"Running {stage_label}", "green")
        bullet("Wordlist", event.get("wordlist"))
        bullet("Extensions", fmt_list(event.get("extensions")))
        bullet("Recursion", fmt_recursion(bool(event.get("recursion")), event.get("depth")))
        bullet("Raw output", event.get("raw_output"))
        bullet("JSON output", event.get("json_output"))
        command_block(event.get("command", ""))
        print(c("This stage is running now. Output is being written to the files above.", "gray"))
        return

    if action == "ran":
        status = event.get("status", "unknown")
        color = "green" if status == "completed" else "red"
        subsection(f"Finished {stage_label}", color)
        bullet("Status", status, color=color)
        bullet("Exit code", event.get("exit_code"), color=color)
        bullet("New findings", event.get("new_findings"), color=color)
        bullet("Raw output", event.get("raw_output"))
        bullet("JSON output", event.get("json_output"))
        if event.get("error"):
            bullet("Error", event["error"], color="red")
        return


def cmd_project_create(args) -> None:
    conn = connect(DB_PATH)
    root = PROJECTS_DIR / args.name
    project = create_project(conn, args.name, root)
    section("Project created", "green")
    kv("Name", project["name"])
    kv("Root", project["root_dir"])


def cmd_host_add(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = add_host(conn, project["id"], args.url, args.profile, args.server, args.tech, args.notes)
    section("Host added", "green")
    kv("Project", project["name"])
    kv("URL", host["url"])
    kv("Profile", host["profile"])
    kv("Server", host["server"] or "-")
    kv("Tech", host["tech"] or "-")


def cmd_host_list(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    hosts = list_hosts(conn, project["id"])
    section(f"Hosts: {project['name']}", "cyan")
    if not hosts:
        print("No hosts added yet.")
        return
    for host in hosts:
        subsection(host["url"], "magenta")
        bullet("Profile", host["profile"])
        bullet("Server", host["server"] or "-")
        bullet("Tech", host["tech"] or "-")
        if host["notes"]:
            bullet("Notes", host["notes"])


def cmd_host_update(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    if not any([args.url_new, args.profile, args.server is not None, args.tech is not None, args.notes is not None]):
        die("nothing to update. Use --url-new, --profile, --server, --tech, or --notes")
    host = update_host(
        conn,
        project["id"],
        args.url,
        new_url=args.url_new,
        profile=args.profile,
        server=args.server,
        tech=args.tech,
        notes=args.notes,
    )
    if host is None:
        die(f"host not found in project: {args.url}")
    section("Host updated", "green")
    kv("Project", project["name"])
    kv("URL", host["url"])
    kv("Profile", host["profile"])
    kv("Server", host["server"] or "-")
    kv("Tech", host["tech"] or "-")
    kv("Notes", host["notes"] or "-")


def cmd_host_remove(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    if not args.yes:
        section("Confirm host removal", "yellow")
        kv("Project", project["name"], color="yellow")
        kv("URL", args.url, color="yellow")
        print(c("This will remove the host and related run/finding records from the database.", "yellow"))
        print(c("Re-run with --yes to confirm.", "yellow", bold=True))
        return
    removed = delete_host(conn, project["id"], args.url)
    if not removed:
        die(f"host not found in project: {args.url}")
    section("Host removed", "green")
    kv("Project", project["name"])
    kv("URL", args.url)


def cmd_gameplans_list(args) -> None:
    section("Available gameplans", "cyan")
    for path in list_builtin_gameplans():
        gameplan = load_gameplan(path)
        subsection(gameplan.name, "magenta")
        if gameplan.description:
            bullet("Description", gameplan.description)
        bullet("Stages", len(gameplan.stages))
        bullet("Estimated completion", total_estimate(gameplan))
        if not args.brief:
            for row in preview_plan("https://example.local", gameplan):
                print(f"  {c(str(row['number']) + '. ' + row['name'], 'yellow', bold=True)}")
                print(f"     {c('Wordlist:', 'cyan', bold=True)} {row['wordlist']}")
                print(f"     {c('Extensions:', 'cyan', bold=True)} {fmt_list(row['extensions'])}")
                print(f"     {c('Recursion:', 'cyan', bold=True)} {fmt_recursion(row['recursion'], row['depth'])}")
            blank()


def cmd_bust_plan(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = get_host(conn, project["id"], args.url)
    if host is None:
        die(f"host not found in project: {args.url}")
    gameplan = resolve_gameplan(args.gameplan)
    print_gameplan_summary(project, host, gameplan, mode="Plan Preview", args=args)


def cmd_bust_run(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = get_host(conn, project["id"], args.url)
    if host is None:
        die(f"host not found in project: {args.url}. Add it first with: obliquity host add")
    gameplan = resolve_gameplan(args.gameplan)

    mode = "Dry Run" if args.dry_run else "Run"
    print_gameplan_summary(project, host, gameplan, mode=mode, args=args)

    section("Execution", "cyan")
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
        event_callback=print_run_event,
    )

    completed = sum(1 for item in results if item.get("status") == "completed")
    skipped = sum(1 for item in results if item.get("action") == "skipped")
    planned = sum(1 for item in results if item.get("action") == "planned")
    failed = sum(1 for item in results if item.get("status") == "failed")
    findings = sum(int(item.get("new_findings") or 0) for item in results)

    section("Run summary", "green" if failed == 0 else "red")
    kv("Completed stages", completed, color="green")
    kv("Skipped stages", skipped, color="yellow")
    kv("Planned stages", planned, color="magenta")
    kv("Failed stages", failed, color="red" if failed else "green")
    kv("New findings", findings)
    kv("Report command", f"obliquity report html {project['name']}")


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
    section("HTML report", "green")
    kv("Report written", output)


def cmd_runs(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    runs = get_runs(conn, project["id"], args.status)
    section(f"Runs: {project['name']}", "cyan")
    if not runs:
        print("No runs found.")
        return
    for run in runs:
        status_color = "green" if run["status"] == "completed" else "red" if run["status"] == "failed" else "yellow"
        print(
            f"{c(str(run['id']).rjust(4), 'gray')} "
            f"{c(run['status'].ljust(10), status_color, bold=True)} "
            f"{c(run['stage_name'].ljust(24), 'magenta')} "
            f"{run['gameplan_name']} exit={run['exit_code']}"
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="obliquity", description="Obliquity: staged pentest workflow orchestration")
    sub = p.add_subparsers(dest="cmd", required=True)

    gameplans = sub.add_parser("gameplans")
    gameplans_sub = gameplans.add_subparsers(dest="gameplans_cmd", required=True)
    gl = gameplans_sub.add_parser("list")
    gl.add_argument("--brief", action="store_true", help="show only names and summary fields")
    gl.set_defaults(func=cmd_gameplans_list)

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

    hu = host_sub.add_parser("update")
    hu.add_argument("project")
    hu.add_argument("url")
    hu.add_argument("--url-new", help="new URL for this host")
    hu.add_argument("--profile")
    hu.add_argument("--server")
    hu.add_argument("--tech")
    hu.add_argument("--notes")
    hu.set_defaults(func=cmd_host_update)

    hr = host_sub.add_parser("remove")
    hr.add_argument("project")
    hr.add_argument("url")
    hr.add_argument("--yes", action="store_true", help="confirm removal without prompting")
    hr.set_defaults(func=cmd_host_remove)

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
    br.add_argument("--dry-run", action="store_true", help="print commands without running the underlying tool")
    br.add_argument("--rate-limit", type=int)
    br.add_argument("--threads", type=int)
    br.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    br.add_argument("--header", action="append", help="header passed to the underlying tool; repeatable")
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
    print_banner()
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
