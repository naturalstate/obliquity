from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from obliquity.core.console import (
    blank,
    bullet,
    c,
    command_block,
    kv,
    live_progress_line,
    rainbow_text,
    section,
    subsection,
    supports_color,
)
from obliquity.core.database import (
    add_host,
    connect,
    create_project,
    delete_host,
    delete_project,
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
ARCHIVE_DIR = APP_DIR / "archive"

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

    if action == "progress":
        if supports_color():
            print(f"\r{live_progress_line(event)}", end="", flush=True)
        return

    if action == "ran":
        if supports_color():
            print("\r" + " " * 120 + "\r", end="", flush=True)
        status = event.get("status", "unknown")
        color = "green" if status == "completed" else "yellow" if status == "interrupted" else "red"
        subsection(f"Finished {stage_label}", color)
        bullet("Status", status, color=color)
        bullet("Exit code", event.get("exit_code"), color=color)
        bullet("New findings", event.get("new_findings"), color=color)
        bullet("Raw output", event.get("raw_output"))
        bullet("JSON output", event.get("json_output"))
        if event.get("error"):
            bullet("Error", event["error"], color=color)
        return


def cmd_project_create(args) -> None:
    conn = connect(DB_PATH)
    root = PROJECTS_DIR / args.name
    project = create_project(conn, args.name, root)
    section("Project created", "green")
    kv("Name", project["name"])
    kv("Root", project["root_dir"])


def cmd_project_archive(args) -> None:
    conn = connect(DB_PATH)
    project = get_project(conn, args.name)
    if project is None:
        if args.if_exists:
            section("Project archive", "yellow")
            kv("Skipped", f"project not found: {args.name}", color="yellow")
            return
        die(f"project not found: {args.name}")
    root = Path(project["root_dir"])
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = ARCHIVE_DIR / f"{project['name']}-{timestamp}"
    if not args.yes:
        section("Confirm project archive", "yellow")
        kv("Project", project["name"], color="yellow")
        kv("From", root, color="yellow")
        kv("To", destination, color="yellow")
        print(c("Re-run with --yes to archive files and remove the project from the active database.", "yellow"))
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    if root.exists():
        shutil.move(str(root), str(destination))
    delete_project(conn, project["id"])
    section("Project archived", "green")
    kv("Project", project["name"])
    kv("Backup", destination if destination.exists() else "No project files existed")


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

    mode = "Dry Run" if args.dry_run else "Resume" if getattr(args, "resume", False) else "Run"
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
    interrupted = sum(1 for item in results if item.get("status") == "interrupted")
    findings = sum(int(item.get("new_findings") or 0) for item in results)

    summary_color = "red" if failed else "yellow" if interrupted else "green"
    section("Run summary", summary_color)
    kv("Completed stages", completed, color="green")
    kv("Skipped stages", skipped, color="yellow")
    kv("Planned stages", planned, color="magenta")
    kv("Failed stages", failed, color="red" if failed else "green")
    kv("Interrupted stages", interrupted, color="yellow" if interrupted else "green")
    kv("New findings", findings)
    kv("Report command", f"obliquity report html {project['name']}")

    if not args.dry_run and not failed and not interrupted and (
        getattr(args, "report", False) or getattr(args, "open_report", False)
    ):
        output = write_html_report(conn, project)
        if getattr(args, "open_report", False):
            open_html_report(output)


def cmd_bust_resume(args) -> None:
    args.resume = True
    cmd_bust_run(args)


def write_html_report(conn, project, output: Path | None = None) -> Path:
    runs = get_runs(conn, project["id"])
    findings = get_findings(conn, project["id"])
    output = output or Path(project["root_dir"]) / "report.html"
    generate_html(project, runs, findings, output)
    section("HTML report", "green")
    kv("Report written", output)
    return output


def open_html_report(output: Path) -> None:
    opened = webbrowser.open(output.resolve().as_uri())
    if opened:
        kv("Opened", output)
    else:
        print(c(f"Could not open a browser automatically. Open this file manually: {output}", "yellow"))


def cmd_report_html(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    output = write_html_report(conn, project, Path(args.output) if args.output else None)
    if args.open:
        open_html_report(output)


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
    formatter = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(
        prog="obliquity",
        formatter_class=formatter,
        description=(
            "Project-aware penetration testing orchestration for reusable gameplans,\n"
            "staged feroxbuster execution, resume tracking, and organized results."
        ),
        epilog="""examples:
  obliquity gameplans list --brief
  obliquity project create acme
  obliquity project archive acme --yes --if-exists
  obliquity host add acme https://app.acme.test --profile generic
  obliquity bust plan acme https://app.acme.test --gameplan generic-quick
  obliquity bust run acme https://app.acme.test --gameplan generic-quick
  obliquity bust run acme https://app.acme.test --gameplan smoke-test --open-report
  obliquity bust resume acme https://app.acme.test --gameplan generic-quick
  obliquity runs acme
  obliquity report html acme

Run 'obliquity COMMAND --help' or 'obliquity COMMAND SUBCOMMAND --help'
for detailed options and examples. Only test systems you are authorized to assess.""",
    )
    sub = p.add_subparsers(dest="cmd", required=True, title="commands", metavar="COMMAND")

    gameplans = sub.add_parser("gameplans", help="inspect built-in scan gameplans")
    gameplans_sub = gameplans.add_subparsers(dest="gameplans_cmd", required=True)
    gl = gameplans_sub.add_parser(
        "list",
        help="list available gameplans",
        description="List built-in gameplans, their stages, wordlists, extensions, and estimates.",
        epilog="examples:\n  obliquity gameplans list\n  obliquity gameplans list --brief",
        formatter_class=formatter,
    )
    gl.add_argument("--brief", action="store_true", help="show only names and summary fields")
    gl.set_defaults(func=cmd_gameplans_list)

    project = sub.add_parser("project", help="create and manage Obliquity projects")
    project_sub = project.add_subparsers(dest="project_cmd", required=True)
    pc = project_sub.add_parser(
        "create",
        help="create a project",
        description="Create a project and its result directory under OBLIQUITY_HOME.",
        epilog="example:\n  obliquity project create acme",
        formatter_class=formatter,
    )
    pc.add_argument("name", help="unique project name")
    pc.set_defaults(func=cmd_project_create)

    pa = project_sub.add_parser(
        "archive",
        help="back up project files and remove the active database record",
        formatter_class=formatter,
        epilog="example:\n  obliquity project archive acme --yes",
    )
    pa.add_argument("name", help="project name")
    pa.add_argument("--yes", action="store_true", help="archive without prompting")
    pa.add_argument("--if-exists", action="store_true", help="succeed when the project does not exist")
    pa.set_defaults(func=cmd_project_archive)

    host = sub.add_parser("host", help="add, inspect, update, or remove project hosts")
    host_sub = host.add_subparsers(dest="host_cmd", required=True)
    ha = host_sub.add_parser(
        "add", help="add a host", formatter_class=formatter,
        epilog="example:\n  obliquity host add acme https://app.acme.test --profile php --server apache --tech php",
    )
    ha.add_argument("project", help="project name")
    ha.add_argument("url", help="target base URL, including scheme")
    ha.add_argument("--profile", default="generic", help="host profile (default: generic)")
    ha.add_argument("--server", help="known web server, such as apache or iis")
    ha.add_argument("--tech", help="known technology, such as php or aspnet")
    ha.add_argument("--notes", help="free-form host notes")
    ha.set_defaults(func=cmd_host_add)

    hl = host_sub.add_parser("list", help="list project hosts", epilog="example:\n  obliquity host list acme", formatter_class=formatter)
    hl.add_argument("project", help="project name")
    hl.set_defaults(func=cmd_host_list)

    hu = host_sub.add_parser(
        "update", help="update host metadata", formatter_class=formatter,
        epilog='example:\n  obliquity host update acme https://app.acme.test --tech php --notes "Public app"',
    )
    hu.add_argument("project", help="project name")
    hu.add_argument("url", help="current host URL")
    hu.add_argument("--url-new", help="new URL for this host")
    hu.add_argument("--profile")
    hu.add_argument("--server")
    hu.add_argument("--tech")
    hu.add_argument("--notes")
    hu.set_defaults(func=cmd_host_update)

    hr = host_sub.add_parser("remove", help="remove a host and its database records", formatter_class=formatter, epilog="example:\n  obliquity host remove acme https://app.acme.test")
    hr.add_argument("project", help="project name")
    hr.add_argument("url", help="host URL")
    hr.add_argument("--yes", action="store_true", help="confirm removal without prompting")
    hr.set_defaults(func=cmd_host_remove)

    bust = sub.add_parser("bust", help="plan, run, or resume staged content discovery")
    bust_sub = bust.add_subparsers(dest="bust_cmd", required=True)

    bp = bust_sub.add_parser(
        "plan", help="preview stages without creating runs", formatter_class=formatter,
        epilog="example:\n  obliquity bust plan acme https://app.acme.test --gameplan generic-quick",
    )
    bp.add_argument("project", help="project name")
    bp.add_argument("url", help="host URL already added to the project")
    bp.add_argument("--gameplan", default="generic-quick", help="built-in name or JSON path (default: generic-quick)")
    bp.set_defaults(func=cmd_bust_plan)

    br = bust_sub.add_parser(
        "run", help="execute a staged feroxbuster gameplan", formatter_class=formatter,
        epilog="""examples:
  obliquity bust run acme https://app.acme.test --gameplan generic-quick
  obliquity bust run acme https://app.acme.test --gameplan php-standard --rate-limit 100
  obliquity bust run acme https://app.acme.test --proxy http://127.0.0.1:8080 --header 'Cookie: session=value'
  obliquity bust run acme https://app.acme.test --dry-run""",
    )
    br.add_argument("project", help="project name")
    br.add_argument("url", help="host URL already added to the project")
    br.add_argument("--gameplan", default="generic-quick", help="built-in name or JSON path (default: generic-quick)")
    br.add_argument("--force", action="store_true", help="rerun completed stages")
    br.add_argument("--dry-run", action="store_true", help="print commands without running the underlying tool")
    br.add_argument("--rate-limit", type=int, help="maximum requests per second")
    br.add_argument("--threads", type=int, help="feroxbuster worker thread count")
    br.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    br.add_argument("--header", action="append", help="header passed to the underlying tool; repeatable")
    br.add_argument("--report", action="store_true", help="generate the HTML report after a successful run")
    br.add_argument("--open-report", action="store_true", help="generate and open the HTML report after a successful run")
    br.set_defaults(func=cmd_bust_run)

    bres = bust_sub.add_parser(
        "resume", help="skip completed stages and retry interrupted or failed work",
        description="Resume a gameplan by using stored stage fingerprints. Completed stages are skipped.",
        formatter_class=formatter,
        epilog="example:\n  obliquity bust resume acme https://app.acme.test --gameplan generic-quick",
    )
    bres.add_argument("project", help="project name")
    bres.add_argument("url", help="host URL already added to the project")
    bres.add_argument("--gameplan", default="generic-quick", help="built-in name or JSON path (default: generic-quick)")
    bres.set_defaults(force=False)
    bres.add_argument("--dry-run", action="store_true", help="show pending commands without executing them")
    bres.add_argument("--rate-limit", type=int, help="maximum requests per second")
    bres.add_argument("--threads", type=int, help="feroxbuster worker thread count")
    bres.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    bres.add_argument("--header", action="append", help="request header; repeatable")
    bres.set_defaults(func=cmd_bust_resume)

    runs = sub.add_parser(
        "runs", help="show stored stage runs", formatter_class=formatter,
        epilog="examples:\n  obliquity runs acme\n  obliquity runs acme --status interrupted",
    )
    runs.add_argument("project", help="project name")
    runs.add_argument("--status", help="filter by pending, running, completed, failed, or interrupted")
    runs.set_defaults(func=cmd_runs)

    report = sub.add_parser("report", help="generate project reports")
    report_sub = report.add_subparsers(dest="report_cmd", required=True)
    rh = report_sub.add_parser(
        "html", help="generate an HTML report", formatter_class=formatter,
        epilog="examples:\n  obliquity report html acme\n  obliquity report html acme --output ./acme-report.html",
    )
    rh.add_argument("project", help="project name")
    rh.add_argument("--output", help="custom report path")
    rh.add_argument("--open", action="store_true", help="open the report in the default browser")
    rh.set_defaults(func=cmd_report_html)

    return p


def main(argv: list[str] | None = None) -> None:
    print_banner()
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
