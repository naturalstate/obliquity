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
    elapsed_time,
    kv,
    live_progress_line,
    progress_bar,
    rainbow_text,
    section,
    subsection,
    supports_color,
)
from obliquity.core.crack_runner import preview_plan as preview_crackplan, run_crackplan
from obliquity.core.crackplan import (
    find_builtin_crackplan,
    fingerprint_crack_stage,
    list_builtin_crackplans,
    load_crackplan,
)
from obliquity.core.database import (
    add_crack_job,
    add_host,
    connect,
    create_project,
    delete_crack_job,
    delete_host,
    delete_project,
    get_coverage,
    get_crack_job,
    get_crack_run_by_fingerprint,
    get_crack_runs,
    get_cracked_hashes,
    get_findings,
    get_history,
    get_host,
    get_project,
    get_run_by_fingerprint,
    get_runs,
    list_crack_jobs,
    list_hosts,
    sum_cracked_for_runs,
    sum_findings_for_runs,
    update_host,
)
from obliquity.core.gameplan import find_builtin_gameplan, fingerprint_stage, list_builtin_gameplans, load_gameplan
from obliquity.core.ffuf_runner import run_fuzz_plan
from obliquity.core.fuzzplan import find_fuzz_plan, list_fuzz_plans, load_fuzz_plan
from obliquity.core.reporting import generate_html
from obliquity.core.runner import preview_plan, run_gameplan
from obliquity.core.tools import inventory_tools
from obliquity.core.wordlists import (
    EXTERNAL_SOURCES,
    WORDLIST_CATALOG,
    catalog_by_name,
    download_entry,
    installed_path,
    is_installed,
)

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


def resolve_fuzz_plan(name_or_path: str):
    path = Path(name_or_path)
    if path.exists():
        return load_fuzz_plan(path)
    return load_fuzz_plan(find_fuzz_plan(name_or_path))


def resolve_crackplan(name_or_path: str):
    path = Path(name_or_path)
    if path.exists():
        return load_crackplan(path)
    return load_crackplan(find_builtin_crackplan(name_or_path))


def require_project(conn, name: str):
    project = get_project(conn, name)
    if project is None:
        die(f"project not found: {name}")
    return project


def require_host(conn, project: dict, url: str | None):
    if url:
        host = get_host(conn, project["id"], url)
        if host is None:
            die(f"host not found in project: {url}. Add it first with: obliquity host add {project['name']} {url}")
        return host

    hosts = list_hosts(conn, project["id"])
    if not hosts:
        die(f"project '{project['name']}' has no hosts yet. Add one with: obliquity host add {project['name']} <url>")
    if len(hosts) > 1:
        options = ", ".join(h["url"] for h in hosts)
        die(f"project '{project['name']}' has multiple hosts; specify one: {options}")
    return hosts[0]


def require_job(conn, project: dict, target: str | None):
    if target:
        job = get_crack_job(conn, project["id"], target)
        if job is None:
            die(f"crack job not found in project: {target}. Add it first with: obliquity crack job add {project['name']} <hashfile>")
        return job

    jobs = list_crack_jobs(conn, project["id"])
    if not jobs:
        die(f"project '{project['name']}' has no crack jobs yet. Add one with: obliquity crack job add {project['name']} <hashfile> --hash-type <mode>")
    if len(jobs) > 1:
        options = ", ".join(j["name"] or j["hash_file"] for j in jobs)
        die(f"project '{project['name']}' has multiple crack jobs; specify one: {options}")
    return jobs[0]


# A small, explicit escalation ladder between built-in gameplans/crackplans --
# not a general intensity/composition system (see CHANGES.md roadmap for
# that); just enough to suggest something reasonable when a plan has already
# been fully run against a target. Extend as more built-ins are added.
GAMEPLAN_ESCALATION = {
    "generic-quick": "generic-standard",
}
CRACKPLAN_ESCALATION = {
    "quick-dictionary": "standard",
}


def bust_completed_runs(conn, project, host, gameplan):
    """If every stage of `gameplan` already has a completed run against
    `host`, return those run rows (oldest fingerprint order). Otherwise None."""
    runs = []
    for stage in gameplan.stages:
        fingerprint = fingerprint_stage(host["url"], gameplan, stage, project_id=project["id"])
        run = get_run_by_fingerprint(conn, fingerprint)
        if run is None or run["status"] != "completed":
            return None
        runs.append(run)
    return runs


def crack_completed_runs(conn, project, job, crackplan):
    runs = []
    for stage in crackplan.stages:
        fingerprint = fingerprint_crack_stage(job["hash_file"], job["hash_type"], crackplan, stage, project_id=project["id"])
        run = get_crack_run_by_fingerprint(conn, fingerprint)
        if run is None or run["status"] != "completed":
            return None
        runs.append(run)
    return runs


def maybe_warn_and_escalate_bust(conn, project, host, gameplan, args):
    """Called by `bust run` (never `resume`, `--force`, or `--dry-run`) before
    execution. If this exact gameplan is already fully done against this
    host, stop, warn, and offer the next gameplan in the escalation ladder --
    accepted with 'y'. Falls back to an explicit rerun-anyway confirmation.
    Mutates args.force when the user chooses to rerun. Returns the gameplan
    to actually run."""
    if args.force or args.dry_run or getattr(args, "resume", False) or not sys.stdin.isatty():
        return gameplan

    completed = bust_completed_runs(conn, project, host, gameplan)
    if completed is None:
        return gameplan

    last_finished = max((r["finished_at"] for r in completed if r["finished_at"]), default=None)
    total_findings = sum_findings_for_runs(conn, [r["id"] for r in completed])

    section("Gameplan already completed", "yellow")
    kv("Target", host["url"], color="yellow")
    kv("Gameplan", gameplan.name, color="yellow")
    kv("Last finished", last_finished or "unknown", color="yellow")
    kv("Findings recorded", total_findings, color="yellow")

    suggested_name = GAMEPLAN_ESCALATION.get(gameplan.name)
    if suggested_name:
        suggested = resolve_gameplan(suggested_name)
        if bust_completed_runs(conn, project, host, suggested) is None:
            answer = input(f"Run '{suggested_name}' instead? [y/N] ").strip().lower()
            if answer in ("y", "yes"):
                return suggested

    answer = input(f"Rerun '{gameplan.name}' anyway? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        args.force = True
        return gameplan

    die("Nothing to do. Use --force to rerun, or pick a different --gameplan.")


def maybe_warn_and_escalate_crack(conn, project, job, crackplan, args):
    if args.force or args.dry_run or getattr(args, "resume", False) or not sys.stdin.isatty():
        return crackplan

    completed = crack_completed_runs(conn, project, job, crackplan)
    if completed is None:
        return crackplan

    last_finished = max((r["finished_at"] for r in completed if r["finished_at"]), default=None)
    total_cracked = sum_cracked_for_runs(conn, [r["id"] for r in completed])

    section("Crackplan already completed", "yellow")
    kv("Target", job["name"] or job["hash_file"], color="yellow")
    kv("Crackplan", crackplan.name, color="yellow")
    kv("Last finished", last_finished or "unknown", color="yellow")
    kv("Hashes cracked", total_cracked, color="yellow")

    suggested_name = CRACKPLAN_ESCALATION.get(crackplan.name)
    if suggested_name:
        suggested = resolve_crackplan(suggested_name)
        if crack_completed_runs(conn, project, job, suggested) is None:
            answer = input(f"Run '{suggested_name}' instead? [y/N] ").strip().lower()
            if answer in ("y", "yes"):
                return suggested

    answer = input(f"Rerun '{crackplan.name}' anyway? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        args.force = True
        return crackplan

    die("Nothing to do. Use --force to rerun, or pick a different --gameplan.")


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


def print_crack_stage_summary(row: dict) -> None:
    subsection(f"Stage {row['number']}: {row['name']}", "magenta")
    bullet("Attack mode", row["attack_mode"])
    if row["attack_mode"] == "dictionary":
        bullet("Wordlist", row["wordlist"])
        if row.get("rules"):
            bullet("Rules", row["rules"])
    elif row["attack_mode"] == "mask":
        bullet("Mask", row["mask"])
    bullet("Estimated time", fmt_estimate(row.get("estimated_minutes")))


def print_crackplan_summary(project: dict, job: dict, crackplan, *, mode: str, args) -> None:
    section(f"Obliquity Crack: {mode}", "cyan")
    kv("Project", project["name"])
    kv("Job", job["name"] or job["hash_file"])
    kv("Hash file", job["hash_file"])
    kv("Hash type (-m)", job["hash_type"])
    kv("Selected crackplan", crackplan.name)
    if crackplan.description:
        kv("Description", crackplan.description)
    kv("Stages", len(crackplan.stages))
    estimates = [stage.estimated_minutes for stage in crackplan.stages]
    kv("Estimated completion", "unknown in MVP" if any(v is None for v in estimates) else fmt_estimate(sum(estimates)))
    kv("Output root", Path(project["root_dir"]) / "runs" / "crack")

    option_bits = []
    if getattr(args, "force", False):
        option_bits.append("force-rerun=true")
    kv("Run options", ", ".join(option_bits) if option_bits else "default")

    section("Stages queued", "blue")
    for row in preview_crackplan(crackplan):
        print_crack_stage_summary(row)


def print_crack_event(event: dict) -> None:
    action = event.get("action")
    stage_label = f"Stage {event.get('stage_number')}/{event.get('total_stages')}: {event.get('stage')}"

    if action == "skipped":
        subsection(f"Skipped {stage_label}", "yellow")
        bullet("Reason", event.get("reason", "already completed"), color="yellow")
        return

    if action == "planned":
        subsection(f"Planned {stage_label}", "magenta")
        bullet("Attack mode", event.get("attack_mode"))
        bullet("Wordlist", event.get("wordlist") or "-")
        bullet("Rules", event.get("rules") or "-")
        bullet("Mask", event.get("mask") or "-")
        bullet("Cracked output", event.get("result_output"))
        command_block(event.get("command", ""))
        return

    if action == "starting":
        subsection(f"Running {stage_label}", "green")
        bullet("Attack mode", event.get("attack_mode"))
        bullet("Wordlist", event.get("wordlist") or "-")
        bullet("Rules", event.get("rules") or "-")
        bullet("Mask", event.get("mask") or "-")
        bullet("Raw output", event.get("raw_output"))
        bullet("Cracked output", event.get("result_output"))
        command_block(event.get("command", ""))
        print(c("This stage is running now. hashcat exiting with 'exhausted' (no hashes left to try) is normal, not a failure.", "gray"))
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
        bullet("Newly cracked", event.get("new_findings"), color=color)
        bullet("Raw output", event.get("raw_output"))
        bullet("Cracked output", event.get("result_output"))
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

    missing = default_profile_missing_entries()
    if missing:
        section("Wordlist setup", "yellow")
        print(c("Some wordlists used by Obliquity's built-in gameplans aren't installed yet:", "yellow"))
        for entry in missing:
            bullet(entry.name, entry.description, color="yellow")
        if sys.stdin.isatty():
            answer = input("\nDownload them now? [y/N] ").strip().lower()
            if answer in ("y", "yes"):
                for entry in missing:
                    install_wordlist_entry(entry)
                return
        print(c("Run 'obliquity wordlists setup' any time to install them.", "yellow"))


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


def cmd_crack_job_add(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    hash_file = str(Path(args.hashfile).expanduser().resolve())
    if not Path(hash_file).exists():
        die(f"hash file not found: {hash_file}")
    job = add_crack_job(conn, project["id"], hash_file, args.hash_type, args.name, args.notes)
    section("Crack job added", "green")
    kv("Project", project["name"])
    kv("Job", job["name"] or "-")
    kv("Hash file", job["hash_file"])
    kv("Hash type (-m)", job["hash_type"])


def cmd_crack_job_list(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    jobs = list_crack_jobs(conn, project["id"])
    section(f"Crack jobs: {project['name']}", "cyan")
    if not jobs:
        print("No crack jobs added yet.")
        return
    for job in jobs:
        subsection(job["name"] or job["hash_file"], "magenta")
        bullet("Hash file", job["hash_file"])
        bullet("Hash type (-m)", job["hash_type"])
        if job["notes"]:
            bullet("Notes", job["notes"])


def cmd_crack_job_remove(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    if not args.yes:
        section("Confirm crack job removal", "yellow")
        kv("Project", project["name"], color="yellow")
        kv("Target", args.target, color="yellow")
        print(c("This will remove the crack job and related run/cracked-hash records from the database.", "yellow"))
        print(c("Re-run with --yes to confirm.", "yellow", bold=True))
        return
    removed = delete_crack_job(conn, project["id"], args.target)
    if not removed:
        die(f"crack job not found in project: {args.target}")
    section("Crack job removed", "green")
    kv("Project", project["name"])
    kv("Target", args.target)


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

    section("FFUF fuzz gameplans", "cyan")
    for path in list_fuzz_plans():
        plan = load_fuzz_plan(path)
        subsection(plan.name, "magenta")
        bullet("Purpose", plan.description)
        bullet("Operation", plan.operation_category)
        bullet("Tool", "ffuf")
        if not args.brief:
            bullet("Wordlist", plan.wordlist)
            bullet("Autocalibration", "yes" if plan.autocalibrate else "no")

    section("Hashcat crack gameplans", "cyan")
    for path in list_builtin_crackplans():
        crackplan = resolve_crackplan(str(path))
        subsection(crackplan.name, "magenta")
        if crackplan.description:
            bullet("Description", crackplan.description)
        bullet("Stages", len(crackplan.stages))
        bullet("Tool", "hashcat")
        if not args.brief:
            for row in preview_crackplan(crackplan):
                print(f"  {c(str(row['number']) + '. ' + row['name'], 'yellow', bold=True)}")
                print(f"     {c('Attack mode:', 'cyan', bold=True)} {row['attack_mode']}")
                if row["attack_mode"] == "dictionary":
                    print(f"     {c('Wordlist:', 'cyan', bold=True)} {row['wordlist']}")
                    if row.get("rules"):
                        print(f"     {c('Rules:', 'cyan', bold=True)} {row['rules']}")
                elif row["attack_mode"] == "mask":
                    print(f"     {c('Mask:', 'cyan', bold=True)} {row['mask']}")
            blank()


def cmd_doctor(args) -> None:
    statuses = inventory_tools()
    section("Core tools", "cyan")
    for item in [status for status in statuses if status.required]:
        color = "green" if item.installed else "yellow"
        state = item.version or item.path or "missing - strongly recommended"
        bullet(item.name, state, color=color)
    section("Optional tools", "blue")
    for item in [status for status in statuses if not status.required]:
        state = item.version or item.path or "not installed"
        bullet(item.name, state, color="green" if item.installed else "gray")
    missing = [item.name for item in statuses if item.required and not item.installed]
    if missing:
        print(c(f"\nObliquity remains usable, but core capabilities are unavailable: {', '.join(missing)}", "yellow"))


def default_profile_missing_entries() -> list:
    """Catalog entries referenced by a built-in bust/fuzz/crack profile that
    aren't resolvable yet (not at their original path, not already downloaded)."""
    referenced_paths: set[str] = set()
    for path in list_builtin_gameplans():
        for stage in load_gameplan(path).stages:
            referenced_paths.add(stage.wordlist)
    for path in list_fuzz_plans():
        referenced_paths.add(load_fuzz_plan(path).wordlist)
    for path in list_builtin_crackplans():
        for stage in load_crackplan(path).stages:
            if stage.wordlist:
                referenced_paths.add(stage.wordlist)
            if stage.rules:
                referenced_paths.add(stage.rules)

    missing = []
    for entry in WORDLIST_CATALOG:
        if is_installed(entry):
            continue
        if any(p.endswith(entry.match_suffix) for p in referenced_paths):
            missing.append(entry)
    return missing


def print_download_progress(name: str, downloaded: int, total: int | None) -> None:
    if not supports_color():
        return
    kb = downloaded // 1024
    if total:
        percent = min(100, round(downloaded * 100 / total))
        print(f"\r{c(name, 'cyan', bold=True)} {progress_bar(percent)} {percent:3d}%  {kb} KB", end="", flush=True)
    else:
        print(f"\r{c(name, 'cyan', bold=True)} {kb} KB downloaded", end="", flush=True)


def install_wordlist_entry(entry) -> None:
    section(f"Downloading {entry.name}", "cyan")
    kv("Source", entry.url)
    kv("Destination", installed_path(entry))
    download_entry(entry, progress_callback=lambda d, t, n=entry.name: print_download_progress(n, d, t))
    if supports_color():
        print()
    kv("Installed", installed_path(entry), color="green")


def cmd_wordlists_list(args) -> None:
    section("Wordlist catalog", "cyan")
    for entry in WORDLIST_CATALOG:
        installed = is_installed(entry)
        subsection(entry.name, "magenta")
        bullet("Description", entry.description)
        bullet("Category", entry.category)
        bullet("Status", "installed" if installed else "not installed", color="green" if installed else "yellow")
        bullet("Path", installed_path(entry))
    section("Other wordlist sources (not auto-installed)", "blue")
    for label, url in EXTERNAL_SOURCES:
        bullet(label, url)


def cmd_wordlists_status(args) -> None:
    section("Wordlist status", "cyan")
    missing = default_profile_missing_entries()
    if not missing:
        print(c("All wordlists/rules referenced by built-in gameplans are available.", "green"))
        return
    print(c("Missing wordlists/rules used by built-in gameplans:", "yellow"))
    for entry in missing:
        bullet(entry.name, entry.description, color="yellow")
    print(c("\nInstall with: obliquity wordlists install <name>, or obliquity wordlists setup", "yellow"))


def cmd_wordlists_install(args) -> None:
    if args.all_missing:
        entries = default_profile_missing_entries()
        if not entries:
            section("Wordlist install", "green")
            print("Nothing missing -- all built-in gameplan wordlists are already available.")
            return
    else:
        if not args.name:
            die("specify one or more wordlist names, or use --all-missing. See: obliquity wordlists list")
        entries = []
        for name in args.name:
            entry = catalog_by_name(name)
            if entry is None:
                die(f"unknown wordlist '{name}'. See: obliquity wordlists list")
            entries.append(entry)

    for entry in entries:
        if is_installed(entry) and not args.force:
            section(f"Skipping {entry.name}", "yellow")
            kv("Reason", "already installed (use --force to redownload)", color="yellow")
            continue
        install_wordlist_entry(entry)


def cmd_wordlists_setup(args) -> None:
    section("Wordlist setup", "cyan")
    missing = default_profile_missing_entries()
    if not missing:
        print(c("All wordlists/rules referenced by built-in gameplans are already available.", "green"))
        return
    print("The following wordlists/rules are used by Obliquity's built-in gameplans but aren't installed yet:")
    for entry in missing:
        bullet(entry.name, entry.description)
    blank()
    for entry in missing:
        answer = input(f"Download {entry.name}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            continue
        install_wordlist_entry(entry)
    section("Other wordlist sources (not auto-installed)", "blue")
    for label, url in EXTERNAL_SOURCES:
        bullet(label, url)


def cmd_coverage(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = None
    if args.url:
        host = get_host(conn, project["id"], args.url)
        if host is None:
            die(f"host not found in project: {args.url}")
    rows = get_coverage(conn, project["id"], host["id"] if host else None)
    section(f"Coverage: {project['name']}", "cyan")
    if not rows:
        print("No operations recorded yet.")
        return
    current_host = None
    for row in rows:
        if row["host_url"] != current_host:
            current_host = row["host_url"]
            subsection(current_host, "magenta")
        print(
            f"  {c(row['operation_category'].ljust(18), 'cyan', bold=True)} "
            f"{c(row['tool'].ljust(13), 'yellow')} "
            f"{c(row['status'].ljust(12), 'green' if row['status'] == 'completed' else 'yellow')} "
            f"{row['gameplan_name']}"
        )
        if row["operation_scope"]:
            print(f"    scope: {row['operation_scope']}")


def _fuzz_url_template(host_url: str, plan, args) -> tuple[str | None, str | None]:
    if plan.operation_category == "parameter-name":
        if not args.endpoint:
            die("parameter-names-quick requires --endpoint, e.g. --endpoint /search")
        endpoint = f"{host_url.rstrip('/')}/{args.endpoint.lstrip('/')}"
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}FUZZ={args.test_value}", None
    if plan.operation_category == "parameter-value":
        if not args.template or "FUZZ" not in args.template:
            die("parameter-values-quick requires --template containing FUZZ")
        template = args.template
        if template.startswith("/"):
            template = f"{host_url.rstrip('/')}{template}"
        return template, None
    if plan.operation_category == "request-input":
        if not args.request:
            die("api-request-quick requires --request pointing to a raw HTTP request containing FUZZ")
        return None, args.request
    die(f"unsupported ffuf operation category: {plan.operation_category}")


def cmd_fuzz_run(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = require_host(conn, project, args.url)
    plan = resolve_fuzz_plan(args.gameplan)
    url_template, request_file = _fuzz_url_template(host["url"], plan, args)
    mode = "Plan" if args.dry_run else "Resume" if getattr(args, "resume", False) else "Run"
    section(f"Obliquity Fuzz: {mode}", "cyan")
    kv("Project", project["name"])
    kv("Target", host["url"])
    kv("Tool", "ffuf")
    kv("Gameplan", plan.name)
    kv("Purpose", plan.description)
    kv("Operation", plan.operation_category)
    kv("Scope", url_template or request_file)
    kv("Wordlist", args.wordlist or plan.wordlist)
    section("Execution", "cyan")
    results = run_fuzz_plan(
        conn,
        project,
        host,
        plan,
        url_template=url_template,
        request_file=request_file,
        wordlist=args.wordlist,
        request_proto=args.request_proto,
        method=args.method,
        data=args.data,
        headers=args.header or [],
        proxy=args.proxy,
        rate=args.rate,
        threads=args.threads,
        match_codes=args.match_codes,
        filter_codes=args.filter_codes,
        filter_size=args.filter_size,
        force=args.force,
        dry_run=args.dry_run,
        event_callback=print_run_event,
    )
    failed = sum(1 for item in results if item.get("status") == "failed")
    interrupted = sum(1 for item in results if item.get("status") == "interrupted")
    findings = sum(int(item.get("new_findings") or 0) for item in results)
    skipped = sum(1 for item in results if item.get("action") == "skipped")
    section("Fuzz summary", "red" if failed else "yellow" if interrupted else "green")
    kv("Skipped operations", skipped, color="yellow" if skipped else "green")
    kv("New findings", findings)
    kv("Coverage command", f"obliquity coverage {project['name']} {host['url']}")
    if not args.dry_run and not failed and not interrupted and (args.report or args.open_report):
        output = write_html_report(conn, project)
        if args.open_report:
            open_html_report(output)


def cmd_fuzz_resume(args) -> None:
    args.resume = True
    args.force = False
    cmd_fuzz_run(args)


def cmd_bust_plan(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = require_host(conn, project, args.url)
    gameplan = resolve_gameplan(args.gameplan)
    print_gameplan_summary(project, host, gameplan, mode="Plan Preview", args=args)


def cmd_bust_run(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    host = require_host(conn, project, args.url)
    gameplan = resolve_gameplan(args.gameplan)
    gameplan = maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)

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


def cmd_crack_plan(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    job = require_job(conn, project, args.job)
    crackplan = resolve_crackplan(args.gameplan)
    print_crackplan_summary(project, job, crackplan, mode="Plan Preview", args=args)


def cmd_crack_run(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    job = require_job(conn, project, args.job)
    crackplan = resolve_crackplan(args.gameplan)
    crackplan = maybe_warn_and_escalate_crack(conn, project, job, crackplan, args)

    mode = "Dry Run" if args.dry_run else "Resume" if getattr(args, "resume", False) else "Run"
    print_crackplan_summary(project, job, crackplan, mode=mode, args=args)

    section("Execution", "cyan")
    results = run_crackplan(
        conn,
        project,
        job,
        crackplan,
        force=args.force,
        dry_run=args.dry_run,
        event_callback=print_crack_event,
    )

    completed = sum(1 for item in results if item.get("status") == "completed")
    skipped = sum(1 for item in results if item.get("action") == "skipped")
    planned = sum(1 for item in results if item.get("action") == "planned")
    failed = sum(1 for item in results if item.get("status") == "failed")
    interrupted = sum(1 for item in results if item.get("status") == "interrupted")
    cracked = sum(int(item.get("new_findings") or 0) for item in results)

    summary_color = "red" if failed else "yellow" if interrupted else "green"
    section("Run summary", summary_color)
    kv("Completed stages", completed, color="green")
    kv("Skipped stages", skipped, color="yellow")
    kv("Planned stages", planned, color="magenta")
    kv("Failed stages", failed, color="red" if failed else "green")
    kv("Interrupted stages", interrupted, color="yellow" if interrupted else "green")
    kv("Newly cracked", cracked)
    kv("Report command", f"obliquity report html {project['name']}")

    if not args.dry_run and not failed and not interrupted and (
        getattr(args, "report", False) or getattr(args, "open_report", False)
    ):
        output = write_html_report(conn, project)
        if getattr(args, "open_report", False):
            open_html_report(output)


def cmd_crack_resume(args) -> None:
    args.resume = True
    cmd_crack_run(args)


def write_html_report(conn, project, output: Path | None = None) -> Path:
    runs = get_runs(conn, project["id"])
    findings = get_findings(conn, project["id"])
    crack_runs = get_crack_runs(conn, project["id"])
    cracked_hashes = get_cracked_hashes(conn, project["id"])
    output = output or Path(project["root_dir"]) / "report.html"
    generate_html(project, runs, findings, output, crack_runs=crack_runs, cracked_hashes=cracked_hashes)
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


def format_duration(started_at, finished_at) -> str:
    if not started_at or not finished_at:
        return "-"
    try:
        start = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(finished_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "-"
    return elapsed_time((end - start).total_seconds())


TOOL_LABELS = {"feroxbuster": "bust", "ffuf": "fuzz", "hashcat": "crack"}


def cmd_history(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.project)
    rows = get_history(conn, project["id"], tool=args.tool, status=args.status, limit=args.limit)
    section(f"History: {project['name']}", "cyan")
    if not rows:
        print("No scans recorded yet.")
        return
    for row in rows:
        status_color = "green" if row["status"] == "completed" else "red" if row["status"] == "failed" else "yellow"
        tool_label = TOOL_LABELS.get(row["tool"], row["tool"])
        when = row["finished_at"] or row["started_at"] or "pending"
        duration = format_duration(row["started_at"], row["finished_at"])
        target = str(row["target"])
        print(
            f"{c(when.ljust(19), 'gray')} "
            f"{c(tool_label.ljust(5), 'blue', bold=True)} "
            f"{c(row['status'].ljust(11), status_color, bold=True)} "
            f"{target[:32].ljust(32)} "
            f"{c(row['gameplan_name'], 'magenta')}/{row['stage_name']} "
            f"findings={row['finding_count']} took={duration}"
        )


def build_parser() -> argparse.ArgumentParser:
    formatter = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(
        prog="obliquity",
        formatter_class=formatter,
        description=(
            "Project-aware penetration testing orchestration for reusable gameplans,\n"
            "staged bust (feroxbuster), fuzz (ffuf), and crack (hashcat) execution,\n"
            "resume tracking, and organized results."
        ),
        epilog="""examples:
  obliquity gameplans list --brief
  obliquity doctor
  obliquity fuzz run acme https://app.acme.test --gameplan parameter-names-quick --endpoint /search
  obliquity coverage acme
  obliquity project create acme
  obliquity project archive acme --yes --if-exists
  obliquity host add acme https://app.acme.test --profile generic
  obliquity bust plan acme https://app.acme.test --gameplan generic-quick
  obliquity bust run acme https://app.acme.test --gameplan generic-quick
  obliquity bust run acme https://app.acme.test --gameplan smoke-test --open-report
  obliquity bust resume acme https://app.acme.test --gameplan generic-quick
  obliquity crack job add acme ./hashes.txt --hash-type 1000 --name ntlm-dump
  obliquity crack run acme --gameplan quick-dictionary --open-report
  obliquity crack resume acme --gameplan standard
  obliquity runs acme
  obliquity report html acme

Run 'obliquity COMMAND --help' or 'obliquity COMMAND SUBCOMMAND --help'
for detailed options and examples. Only test systems you are authorized to assess.""",
    )
    sub = p.add_subparsers(dest="cmd", required=False, title="commands", metavar="COMMAND")

    # Shared by every `bust`/`fuzz` run|resume|plan subcommand so `run` and `resume`
    # can never drift apart the way they did before (see git history).
    project_host_args = argparse.ArgumentParser(add_help=False)
    project_host_args.add_argument("project", help="project name")
    project_host_args.add_argument(
        "url", nargs="?",
        help="host URL or host name already added to the project (optional if the project has exactly one host)",
    )

    fuzz_scan_args = argparse.ArgumentParser(add_help=False)
    fuzz_scan_args.add_argument("--gameplan", default="parameter-names-quick", help="ffuf gameplan name")
    fuzz_scan_args.add_argument("--wordlist", help="override the gameplan wordlist")
    fuzz_scan_args.add_argument("--endpoint", help="path for parameter-name fuzzing")
    fuzz_scan_args.add_argument("--template", help="URL template containing FUZZ")
    fuzz_scan_args.add_argument("--test-value", default="test", help="fixed parameter value")
    fuzz_scan_args.add_argument("--request", help="raw HTTP request file")
    fuzz_scan_args.add_argument("--request-proto", default="https", help="protocol for raw requests")
    fuzz_scan_args.add_argument("--match-codes", help="ffuf match status codes")
    fuzz_scan_args.add_argument("--filter-codes", help="ffuf filter status codes")
    fuzz_scan_args.add_argument("--filter-size", help="ffuf filter response sizes")
    fuzz_scan_args.add_argument("--report", action="store_true", help="generate HTML report after success")
    fuzz_scan_args.add_argument("--open-report", action="store_true", help="generate and open HTML report after success")
    fuzz_scan_args.add_argument("--header", action="append", help="header; repeatable")
    fuzz_scan_args.add_argument("--method", help="HTTP method")
    fuzz_scan_args.add_argument("--data", help="request body, including FUZZ")
    fuzz_scan_args.add_argument("--proxy", help="HTTP/SOCKS proxy")
    fuzz_scan_args.add_argument("--threads", type=int, help="ffuf worker count")
    fuzz_scan_args.add_argument("--rate", type=int, help="requests per second")
    fuzz_scan_args.add_argument("--dry-run", action="store_true", help="show command without executing ffuf")

    doctor = sub.add_parser("doctor", help="check core and optional tool installations", formatter_class=formatter, epilog="example:\n  obliquity doctor")
    doctor.set_defaults(func=cmd_doctor)

    wordlists = sub.add_parser(
        "wordlists", help="manage downloadable wordlists and rules", formatter_class=formatter,
        epilog="""examples:
  obliquity wordlists list
  obliquity wordlists status
  obliquity wordlists install seclists-common rockyou
  obliquity wordlists install --all-missing
  obliquity wordlists setup""",
    )
    wordlists_sub = wordlists.add_subparsers(dest="wordlists_cmd", required=True)

    wl = wordlists_sub.add_parser("list", help="show the wordlist catalog and install status", formatter_class=formatter)
    wl.set_defaults(func=cmd_wordlists_list)

    ws = wordlists_sub.add_parser("status", help="show which built-in gameplan wordlists are missing", formatter_class=formatter)
    ws.set_defaults(func=cmd_wordlists_status)

    wi = wordlists_sub.add_parser(
        "install", help="download one or more catalog wordlists", formatter_class=formatter,
        epilog="examples:\n  obliquity wordlists install seclists-common rockyou\n  obliquity wordlists install --all-missing",
    )
    wi.add_argument("name", nargs="*", help="catalog entry name(s); see 'obliquity wordlists list'")
    wi.add_argument("--all-missing", action="store_true", help="install everything referenced by built-in gameplans that isn't already available")
    wi.add_argument("--force", action="store_true", help="redownload even if already installed")
    wi.set_defaults(func=cmd_wordlists_install)

    wsetup = wordlists_sub.add_parser("setup", help="interactively install missing default wordlists", formatter_class=formatter)
    wsetup.set_defaults(func=cmd_wordlists_setup)

    fuzz = sub.add_parser("fuzz", help="run ffuf parameter and request fuzzing", formatter_class=formatter, epilog="""examples:
  obliquity fuzz run acme https://app.test --gameplan parameter-names-quick --endpoint /search
  obliquity fuzz run acme https://app.test --gameplan parameter-values-quick --template '/search?q=FUZZ'
  obliquity fuzz run acme https://app.test --gameplan api-request-quick --request request.txt""")
    fuzz_sub = fuzz.add_subparsers(dest="fuzz_cmd", required=True)
    fl = fuzz_sub.add_parser("list", help="list ffuf gameplans", formatter_class=formatter)
    fl.add_argument("--brief", action="store_true")
    fl.set_defaults(func=cmd_gameplans_list)
    fr = fuzz_sub.add_parser(
        "run", help="execute an ffuf gameplan", formatter_class=formatter,
        parents=[project_host_args, fuzz_scan_args],
    )
    fr.add_argument("--force", action="store_true", help="rerun equivalent completed coverage")
    fr.set_defaults(func=cmd_fuzz_run)
    fres = fuzz_sub.add_parser(
        "resume", help="resume an ffuf gameplan", formatter_class=formatter,
        parents=[project_host_args, fuzz_scan_args],
    )
    fres.set_defaults(func=cmd_fuzz_resume)

    coverage = sub.add_parser("coverage", help="show operation coverage by host and tool")
    coverage.add_argument("project")
    coverage.add_argument("url", nargs="?")
    coverage.set_defaults(func=cmd_coverage)

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

    bust_scan_args = argparse.ArgumentParser(add_help=False)
    bust_scan_args.add_argument("--gameplan", default="generic-quick", help="built-in name or JSON path (default: generic-quick)")
    bust_scan_args.add_argument("--dry-run", action="store_true", help="print commands without running the underlying tool")
    bust_scan_args.add_argument("--rate-limit", type=int, help="maximum requests per second")
    bust_scan_args.add_argument("--threads", type=int, help="feroxbuster worker thread count")
    bust_scan_args.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    bust_scan_args.add_argument("--header", action="append", help="header passed to the underlying tool; repeatable")
    bust_scan_args.add_argument("--report", action="store_true", help="generate the HTML report after a successful run")
    bust_scan_args.add_argument("--open-report", action="store_true", help="generate and open the HTML report after a successful run")

    bust = sub.add_parser("bust", help="plan, run, or resume staged content discovery")
    bust_sub = bust.add_subparsers(dest="bust_cmd", required=True)

    bp = bust_sub.add_parser(
        "plan", help="preview stages without creating runs", formatter_class=formatter,
        parents=[project_host_args],
        epilog="example:\n  obliquity bust plan acme https://app.acme.test --gameplan generic-quick",
    )
    bp.add_argument("--gameplan", default="generic-quick", help="built-in name or JSON path (default: generic-quick)")
    bp.set_defaults(func=cmd_bust_plan)

    br = bust_sub.add_parser(
        "run", help="execute a staged feroxbuster gameplan", formatter_class=formatter,
        parents=[project_host_args, bust_scan_args],
        epilog="""examples:
  obliquity bust run acme https://app.acme.test --gameplan generic-quick
  obliquity bust run acme https://app.acme.test --gameplan php-standard --rate-limit 100
  obliquity bust run acme https://app.acme.test --proxy http://127.0.0.1:8080 --header 'Cookie: session=value'
  obliquity bust run acme https://app.acme.test --dry-run""",
    )
    br.add_argument("--force", action="store_true", help="rerun completed stages")
    br.set_defaults(func=cmd_bust_run)

    bres = bust_sub.add_parser(
        "resume", help="skip completed stages and retry interrupted or failed work",
        description="Resume a gameplan by using stored stage fingerprints. Completed stages are skipped.",
        formatter_class=formatter,
        parents=[project_host_args, bust_scan_args],
        epilog="example:\n  obliquity bust resume acme https://app.acme.test --gameplan generic-quick",
    )
    bres.set_defaults(force=False)
    bres.set_defaults(func=cmd_bust_resume)

    crack_target_args = argparse.ArgumentParser(add_help=False)
    crack_target_args.add_argument("project", help="project name")
    crack_target_args.add_argument(
        "job", nargs="?",
        help="crack job name or hash file already added to the project (optional if the project has exactly one job)",
    )

    crack_scan_args = argparse.ArgumentParser(add_help=False)
    crack_scan_args.add_argument("--gameplan", default="quick-dictionary", help="built-in name or JSON path (default: quick-dictionary)")
    crack_scan_args.add_argument("--dry-run", action="store_true", help="print commands without running hashcat")
    crack_scan_args.add_argument("--report", action="store_true", help="generate the HTML report after a successful run")
    crack_scan_args.add_argument("--open-report", action="store_true", help="generate and open the HTML report after a successful run")

    crack = sub.add_parser(
        "crack", help="plan, run, or resume staged hashcat cracking", formatter_class=formatter,
        epilog="""examples:
  obliquity crack job add acme ./hashes.txt --hash-type 1000 --name ntlm-dump
  obliquity crack plan acme --gameplan quick-dictionary
  obliquity crack run acme --gameplan quick-dictionary
  obliquity crack run acme ntlm-dump --gameplan standard --open-report
  obliquity crack resume acme --gameplan standard""",
    )
    crack_sub = crack.add_subparsers(dest="crack_cmd", required=True)

    crack_job = crack_sub.add_parser("job", help="add, list, or remove crack targets (hash files)")
    crack_job_sub = crack_job.add_subparsers(dest="crack_job_cmd", required=True)

    cja = crack_job_sub.add_parser(
        "add", help="add a hash file as a crack job", formatter_class=formatter,
        epilog="example:\n  obliquity crack job add acme ./hashes.txt --hash-type 1000 --name ntlm-dump",
    )
    cja.add_argument("project", help="project name")
    cja.add_argument("hashfile", help="path to a hashcat-compatible hash file")
    cja.add_argument("--hash-type", type=int, required=True, help="hashcat -m mode number, e.g. 0=MD5, 1000=NTLM")
    cja.add_argument("--name", help="friendly name to refer to this job later")
    cja.add_argument("--notes", help="free-form job notes")
    cja.set_defaults(func=cmd_crack_job_add)

    cjl = crack_job_sub.add_parser("list", help="list project crack jobs", epilog="example:\n  obliquity crack job list acme", formatter_class=formatter)
    cjl.add_argument("project", help="project name")
    cjl.set_defaults(func=cmd_crack_job_list)

    cjr = crack_job_sub.add_parser("remove", help="remove a crack job and its records", formatter_class=formatter, epilog="example:\n  obliquity crack job remove acme ntlm-dump")
    cjr.add_argument("project", help="project name")
    cjr.add_argument("target", help="job name or hash file path")
    cjr.add_argument("--yes", action="store_true", help="confirm removal without prompting")
    cjr.set_defaults(func=cmd_crack_job_remove)

    cp = crack_sub.add_parser(
        "plan", help="preview stages without creating runs", formatter_class=formatter,
        parents=[crack_target_args],
        epilog="example:\n  obliquity crack plan acme --gameplan quick-dictionary",
    )
    cp.add_argument("--gameplan", default="quick-dictionary", help="built-in name or JSON path (default: quick-dictionary)")
    cp.set_defaults(func=cmd_crack_plan)

    cr = crack_sub.add_parser(
        "run", help="execute a staged hashcat crackplan", formatter_class=formatter,
        parents=[crack_target_args, crack_scan_args],
        epilog="""examples:
  obliquity crack run acme --gameplan quick-dictionary
  obliquity crack run acme ntlm-dump --gameplan standard --open-report
  obliquity crack run acme --dry-run""",
    )
    cr.add_argument("--force", action="store_true", help="rerun completed stages")
    cr.set_defaults(func=cmd_crack_run)

    cres = crack_sub.add_parser(
        "resume", help="skip completed stages and retry interrupted or failed work",
        description="Resume a crackplan by using stored stage fingerprints. Completed stages are skipped.",
        formatter_class=formatter,
        parents=[crack_target_args, crack_scan_args],
        epilog="example:\n  obliquity crack resume acme --gameplan standard",
    )
    cres.set_defaults(force=False)
    cres.set_defaults(func=cmd_crack_resume)

    runs = sub.add_parser(
        "runs", help="show stored stage runs", formatter_class=formatter,
        epilog="examples:\n  obliquity runs acme\n  obliquity runs acme --status interrupted",
    )
    runs.add_argument("project", help="project name")
    runs.add_argument("--status", help="filter by pending, running, completed, failed, or interrupted")
    runs.set_defaults(func=cmd_runs)

    history = sub.add_parser(
        "history", help="show a unified, readable log of bust/fuzz/crack scans", formatter_class=formatter,
        epilog="""examples:
  obliquity history acme
  obliquity history acme --tool hashcat
  obliquity history acme --status failed --limit 20""",
    )
    history.add_argument("project", help="project name")
    history.add_argument("--tool", choices=["feroxbuster", "ffuf", "hashcat"], help="filter by underlying tool")
    history.add_argument("--status", help="filter by pending, running, completed, failed, or interrupted")
    history.add_argument("--limit", type=int, help="show only the N most recent entries")
    history.set_defaults(func=cmd_history)

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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
