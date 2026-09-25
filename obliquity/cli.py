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
from obliquity.core.config import active_project, clear_active_project, set_active_project
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
    add_login_job,
    connect,
    create_project,
    list_projects,
    set_project_default_gameplan,
    delete_crack_job,
    delete_host,
    delete_login_job,
    delete_project,
    get_coverage,
    get_crack_job,
    get_crack_run_by_fingerprint,
    get_crack_runs,
    get_cracked_hashes,
    get_findings,
    get_found_credentials,
    get_history,
    get_host,
    get_login_job,
    get_login_run_by_fingerprint,
    get_login_runs,
    get_project,
    get_run_by_fingerprint,
    get_runs,
    list_crack_jobs,
    list_hosts,
    list_login_jobs,
    get_project_options,
    set_project_option,
    unset_project_option,
    sum_cracked_for_runs,
    sum_findings_for_runs,
    update_host,
)
from obliquity.core.extensions import analyze_wordlist
from obliquity.core.login_runner import preview_plan as preview_loginplan, run_loginplan
from obliquity.core.loginplan import (
    find_builtin_loginplan,
    list_builtin_loginplans,
    load_loginplan,
)
from obliquity.adapters.hydra import FORM_SERVICES, KNOWN_SERVICES
from obliquity.core.gameplan import extension_conflicts, find_builtin_gameplan, fingerprint_stage, list_builtin_gameplans, load_gameplan
from obliquity.core.ffuf_runner import run_fuzz_plan
from obliquity.core.fuzzplan import find_fuzz_plan, list_fuzz_plans, load_fuzz_plan
from obliquity.core.reporting import generate_csv, generate_html, generate_json, generate_markdown
from obliquity.core.runner import preview_plan, run_gameplan
from obliquity.core.tools import inventory_tools
from obliquity.core.wordlists import (
    EXTERNAL_SOURCES,
    WORDLIST_CATALOG,
    catalog_by_name,
    download_entry,
    installed_path,
    is_installed,
    resolve_path,
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


def resolve_loginplan(name_or_path: str):
    path = Path(name_or_path)
    if path.exists():
        return load_loginplan(path)
    return load_loginplan(find_builtin_loginplan(name_or_path))


# --- Metasploit-style stateful per-tool options ------------------------------
# Each tool ("module") has a set of options a user can `set` on the active
# project and reuse, so `run` needs no flags. `gameplan` is stored in its own
# dedicated column (default_*_gameplan) via set-gameplan; everything else lives
# in project_options. An explicit CLI flag always overrides a stored option.
#
# Each option: (key, args_attr, type, required, help). `required` is advisory
# for `show options`; the run handlers still do the real validation with their
# existing friendly errors.
class _Opt:
    __slots__ = ("key", "attr", "typ", "required", "help")

    def __init__(self, key, attr, typ="str", required=False, help=""):
        self.key = key
        self.attr = attr
        self.typ = typ
        self.required = required
        self.help = help


OPTION_SCHEMA: dict[str, list[_Opt]] = {
    "bust": [
        _Opt("host", "url", help="target URL (optional if the project has exactly one host)"),
        _Opt("gameplan", "gameplan", help="built-in gameplan name or JSON path"),
        _Opt("threads", "threads", "int", help="feroxbuster worker threads"),
        _Opt("rate", "rate_limit", "int", help="max requests/sec"),
        _Opt("proxy", "proxy", help="proxy URL, e.g. http://127.0.0.1:8080"),
    ],
    "fuzz": [
        _Opt("host", "url", help="target URL (optional if the project has exactly one host)"),
        _Opt("gameplan", "gameplan", help="built-in fuzz gameplan name or JSON path"),
        _Opt("endpoint", "endpoint", required=True, help="path for parameter-name fuzzing (e.g. /search)"),
        _Opt("template", "template", help="URL template containing FUZZ"),
        _Opt("request", "request", help="raw HTTP request file containing FUZZ"),
    ],
    "crack": [
        _Opt("job", "job", help="crack job name or hash file"),
        _Opt("gameplan", "gameplan", help="built-in crackplan name or JSON path"),
    ],
    "brute": [
        _Opt("job", "job", required=True, help="login job name or target"),
        _Opt("gameplan", "gameplan", help="built-in loginplan name or JSON path"),
    ],
}

# tool -> the projects column holding that tool's default gameplan (matches
# database.PROJECT_DEFAULT_COLUMNS).
_GAMEPLAN_COLUMN = {
    "bust": "default_bust_gameplan",
    "fuzz": "default_fuzz_gameplan",
    "crack": "default_crackplan",
    "brute": "default_bruteplan",
}


def apply_stored_options(conn, project, tool: str, args) -> None:
    """Fill in any run/plan args the user didn't pass on the CLI from the
    project's stored options. Explicit flags (already non-empty on args) win."""
    stored = get_project_options(conn, project["id"], tool)
    for opt in OPTION_SCHEMA.get(tool, []):
        if opt.key == "gameplan":
            continue  # gameplan comes from the dedicated default column, handled by resolvers
        if getattr(args, opt.attr, None):
            continue  # explicit flag wins
        if opt.key in stored and stored[opt.key] is not None:
            val = stored[opt.key]
            if opt.typ == "int":
                try:
                    val = int(val)
                except ValueError:
                    continue
            setattr(args, opt.attr, val)


def require_project(conn, name: str):
    project = get_project(conn, name)
    if project is None:
        die(f"project not found: {name}")
    return project


def resolve_project(conn, args):
    """Resolve which project a command targets. Precedence: explicit positional
    > OBLIQUITY_PROJECT env var > the active project set with `project use`.
    Prints a note when it wasn't given explicitly, so it's never a surprise
    which project a command acted on."""
    explicit = getattr(args, "project", None)
    env_project = os.environ.get("OBLIQUITY_PROJECT")
    name = explicit or env_project or active_project()
    if not name:
        die("no project given, and no active project is set. Pass a project name, "
            "or select one with: obliquity project use <name>")
    if not explicit:
        source = "OBLIQUITY_PROJECT env" if env_project else "active project"
        print(c(f"Using {source}: {name}", "gray"))
    project = get_project(conn, name)
    if project is None:
        die(f"project not found: {name}")
    return project


def normalize_host_target(args) -> None:
    """bust/fuzz take an optional `project` then an optional `url`. If the user
    gives a single positional that's a URL (contains '://') while there's an
    active project, they meant it as the host -- shuffle it into `url` so the
    project resolves from the active/env setting. Project names never contain
    '://', so this is unambiguous."""
    proj = getattr(args, "project", None)
    if proj and "://" in proj and not getattr(args, "url", None):
        args.url = proj
        args.project = None


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


def require_login_job(conn, project: dict, target: str | None):
    if target:
        job = get_login_job(conn, project["id"], target)
        if job is None:
            die(f"login job not found in project: {target}. Add it first with: obliquity brute job add {project['name']} <target> --service <svc>")
        return job

    jobs = list_login_jobs(conn, project["id"])
    if not jobs:
        die(f"project '{project['name']}' has no login jobs yet. Add one with: obliquity brute job add {project['name']} <target> --service <svc>")
    if len(jobs) > 1:
        options = ", ".join(j["name"] or j["target"] for j in jobs)
        die(f"project '{project['name']}' has multiple login jobs; specify one: {options}")
    return jobs[0]


# A small, explicit escalation ladder between built-in gameplans/crackplans --
# not a general intensity/composition system (see CHANGES.md roadmap for
# that); just enough to suggest something reasonable when a plan has already
# been fully run against a target. Extend as more built-ins are added.
GAMEPLAN_ESCALATION = {
    "generic-quick": "generic-standard",
    "generic-standard": "generic-deep",
}
CRACKPLAN_ESCALATION = {
    "quick-dictionary": "standard",
}


# Host/Application Awareness: when `--gameplan` isn't given, recommend a
# built-in gameplan from the host metadata `host add` already collects,
# instead of always defaulting to generic-quick. The three fields have
# distinct, non-overlapping roles so there's exactly one right place for a
# given value:
#   --tech    = backend language/framework (aspnet, php, java, node, python)
#   --profile = application TYPE            (api, wordpress, admin-panel, ...)
#   --server  = web server software        (iis, apache, nginx, tomcat)
# Checked most-to-least specific: tech -> profile -> server -> default.
TECH_GAMEPLAN = {
    "aspnet": "aspnet-standard",
    "php": "php-standard",
}
PROFILE_GAMEPLAN = {
    "api": "api-quick",
}
SERVER_GAMEPLAN = {
    "iis": "aspnet-standard",
}
DEFAULT_GAMEPLAN = "generic-quick"


def recommend_gameplan(host) -> tuple[str, str | None]:
    """Returns (gameplan_name, reason). reason is None for the plain default."""
    tech = (host["tech"] or "").strip().lower()
    profile = (host["profile"] or "").strip().lower()
    server = (host["server"] or "").strip().lower()

    if tech in TECH_GAMEPLAN:
        return TECH_GAMEPLAN[tech], f"tech={tech}"
    if profile in PROFILE_GAMEPLAN:
        return PROFILE_GAMEPLAN[profile], f"profile={profile}"
    if server in SERVER_GAMEPLAN:
        return SERVER_GAMEPLAN[server], f"server={server}"
    return DEFAULT_GAMEPLAN, None


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


def print_stage_summary(row: dict) -> None:
    subsection(f"Stage {row['number']}: {row['name']}", "magenta")
    bullet("Wordlist", row["wordlist"])
    bullet("Extensions", fmt_list(row["extensions"]))
    bullet("Recursion", fmt_recursion(row["recursion"], row["depth"]))
    bullet("Status codes", fmt_list(row["status_codes"]))
    filters = []
    if row.get("filter_status"):
        filters.append(f"status={fmt_list(row['filter_status'])}")
    if row.get("filter_size"):
        filters.append(f"size={fmt_list(row['filter_size'])}")
    if row.get("filter_words"):
        filters.append(f"words={fmt_list(row['filter_words'])}")
    if row.get("filter_lines"):
        filters.append(f"lines={fmt_list(row['filter_lines'])}")
    if row.get("filter_regex"):
        filters.append(f"regex={row['filter_regex']}")
    if filters:
        bullet("Filters", ", ".join(filters))
    if row.get("extra_args"):
        bullet("Extra args", fmt_list(row["extra_args"]))


def print_gameplan_summary(project: dict, host: dict, gameplan, *, mode: str, args, recommended_reason: str | None = None) -> None:
    section(f"Obliquity Bust: {mode}", "cyan")
    kv("Project", project["name"])
    kv("Target", host["url"])
    if recommended_reason:
        kv("Selected gameplan", f"{gameplan.name}  (recommended: {recommended_reason})", color="green")
    else:
        kv("Selected gameplan", gameplan.name)
    if gameplan.description:
        kv("Description", gameplan.description)
    kv("Stages", len(gameplan.stages))
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

    # Extension Intelligence: warn when a stage appends extensions to a wordlist
    # that already carries them (index.php + .php -> index.php.php waste).
    conflicts = extension_conflicts(gameplan)
    if conflicts:
        section("Extension Intelligence", "yellow")
        print(c("These stages append extensions to a wordlist that already contains "
                "extensions, which produces double-extension requests (e.g. "
                "index.php.php) that waste time and find nothing:", "yellow"))
        for stage_name, wordlist, exts in conflicts:
            bullet(stage_name, f"{Path(wordlist).name} + [{', '.join(exts)}]", color="yellow")
        print(c("Consider a directory-only wordlist for these stages, or drop the "
                "appended extensions. Inspect any list with: obliquity wordlists inspect <name>", "gray"))

    # Only expand the per-stage detail for a plan preview; on a real run/resume
    # the compact per-stage execution output covers it, so don't print it twice.
    if mode == "Plan Preview":
        section("Stages queued", "blue")
        for row in preview_plan(host["url"], gameplan):
            print_stage_summary(row)


def _stage_n(event: dict) -> str:
    return f"{event.get('stage_number')}/{event.get('total_stages')} {event.get('stage')}"


def _clear_progress_line() -> None:
    if supports_color():
        print("\r" + " " * 120 + "\r", end="", flush=True)


# Per-stage execution output is deliberately terse (2 lines/stage): one header
# line that stays, the animated spinner in place, then a result line that
# overwrites the spinner. Exact output-file paths live in the run summary's
# "Output root" and in `runs`/`report`/`history` -- not repeated per stage.
def print_run_event(event: dict) -> None:
    action = event.get("action")
    n = _stage_n(event)

    if action == "skipped":
        print(c(f"  - {n}  skipped ({event.get('reason', 'already completed')})", "yellow"))
        return

    if action == "planned":  # dry-run: the command is the whole point, keep it
        subsection(f"Planned {n}", "magenta")
        bullet("Wordlist", event.get("wordlist"))
        bullet("Extensions", fmt_list(event.get("extensions")))
        bullet("Recursion", fmt_recursion(bool(event.get("recursion")), event.get("depth")))
        command_block(event.get("command", ""))
        return

    if action == "starting":
        wl = Path(event.get("wordlist") or "").name
        exts = event.get("extensions") or []
        extbit = c(f"  +{fmt_list(exts)}", "gray") if exts else ""
        print(c(f"  > {n}", "green", bold=True) + c(f"   {wl}", "cyan") + extbit)
        return

    if action == "progress":
        if supports_color():
            print(f"\r{live_progress_line(event)}", end="", flush=True)
        return

    if action == "ran":
        _clear_progress_line()
        status = event.get("status", "unknown")
        mark = {"completed": "OK", "interrupted": "INT"}.get(status, "FAIL")
        color = {"completed": "green", "interrupted": "yellow"}.get(status, "red")
        line = c(f"  {mark} {n}", color, bold=True) + c(f"   {event.get('new_findings')} new", color)
        if event.get("error"):
            line += c(f"   {event['error']}", color)
        print(line)
        return


def print_crack_stage_summary(row: dict) -> None:
    subsection(f"Stage {row['number']}: {row['name']}", "magenta")
    bullet("Attack mode", row["attack_mode"])
    if row.get("wordlist"):
        bullet("Wordlist", row["wordlist"])
    if row.get("wordlist2"):
        bullet("Wordlist 2", row["wordlist2"])
    if row.get("rules"):
        bullet("Rules", fmt_list(row["rules"]))
    if row.get("mask"):
        bullet("Mask", row["mask"])


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
    kv("Output root", Path(project["root_dir"]) / "runs" / "crack")

    option_bits = []
    if getattr(args, "force", False):
        option_bits.append("force-rerun=true")
    kv("Run options", ", ".join(option_bits) if option_bits else "default")

    if mode == "Plan Preview":
        section("Stages queued", "blue")
        for row in preview_crackplan(crackplan):
            print_crack_stage_summary(row)


def print_crack_event(event: dict) -> None:
    action = event.get("action")
    n = _stage_n(event)

    if action == "skipped":
        print(c(f"  - {n}  skipped ({event.get('reason', 'already completed')})", "yellow"))
        return

    if action == "planned":  # dry-run: keep the full command + fields
        subsection(f"Planned {n}", "magenta")
        bullet("Attack mode", event.get("attack_mode"))
        if event.get("wordlist"):
            bullet("Wordlist", event["wordlist"])
        if event.get("wordlist2"):
            bullet("Wordlist 2", event["wordlist2"])
        if event.get("rules"):
            bullet("Rules", fmt_list(event["rules"]))
        if event.get("mask"):
            bullet("Mask", event["mask"])
        command_block(event.get("command", ""))
        return

    if action == "starting":
        detail = Path(event["wordlist"]).name if event.get("wordlist") else (event.get("mask") or "")
        line = c(f"  > {n}", "green", bold=True) + c(f"   {event.get('attack_mode')}", "cyan")
        if detail:
            line += c(f"  {detail}", "cyan")
        if event.get("resuming"):
            line += c("  (resuming --restore)", "green")
        print(line)
        return

    if action == "progress":
        if supports_color():
            print(f"\r{live_progress_line(event)}", end="", flush=True)
        return

    if action == "ran":
        _clear_progress_line()
        status = event.get("status", "unknown")
        mark = {"completed": "OK", "interrupted": "INT"}.get(status, "FAIL")
        color = {"completed": "green", "interrupted": "yellow"}.get(status, "red")
        line = c(f"  {mark} {n}", color, bold=True) + c(f"   {event.get('new_findings')} cracked", color)
        if event.get("error"):
            line += c(f"   {event['error']}", color)
        print(line)
        return


def cmd_project_list(args) -> None:
    conn = connect(DB_PATH)
    projects = list_projects(conn)
    active = os.environ.get("OBLIQUITY_PROJECT") or active_project()
    section("Projects", "cyan")
    if not projects:
        print("No projects yet. Create one with: obliquity project create <name>")
        return
    for p in projects:
        marker = c("  * active", "green", bold=True) if p["name"] == active else ""
        subsection(p["name"] + marker, "magenta")
        bullet("Hosts", p["host_count"])
        bullet("Crack jobs", p["job_count"])
        bullet("Runs", p["run_count"])
        bullet("Created", p["created_at"])
        bullet("Root", p["root_dir"])


def cmd_project_use(args) -> None:
    conn = connect(DB_PATH)
    project = require_project(conn, args.name)  # validate it exists (explicit name)
    set_active_project(project["name"])
    section("Active project set", "green")
    kv("Active project", project["name"])
    print(c("Commands now default to this project; pass a name or --project, or set OBLIQUITY_PROJECT, to override.", "gray"))


# The built-in gameplan each tool falls back to when a project has no default
# set. bust is special: with no project default it recommends a plan from the
# target host's metadata (recommend_gameplan), so there's no single fixed name.
CRACK_DEFAULT_FALLBACK = "quick-dictionary"
FUZZ_DEFAULT_FALLBACK = "parameter-names-quick"
BRUTE_DEFAULT_FALLBACK = "quick"


def _default_gameplan_display(project) -> list[tuple[str, str]]:
    """(tool, description) pairs describing each tool's effective default plan
    for a project, marking built-in fallbacks with '(default)'."""
    rows = []
    bust = project["default_bust_gameplan"]
    if bust:
        rows.append(("bust", bust))
    else:
        rows.append(("bust", "(default) auto from host metadata, else generic-quick"))
    fuzz = project["default_fuzz_gameplan"]
    rows.append(("fuzz", fuzz if fuzz else f"{FUZZ_DEFAULT_FALLBACK} (default)"))
    crack = project["default_crackplan"]
    rows.append(("crack", crack if crack else f"{CRACK_DEFAULT_FALLBACK} (default)"))
    brute = project["default_bruteplan"]
    rows.append(("brute", brute if brute else f"{BRUTE_DEFAULT_FALLBACK} (default)"))
    return rows


def cmd_project_current(args) -> None:
    env_project = os.environ.get("OBLIQUITY_PROJECT")
    name = env_project or active_project()
    section("Active project", "cyan")
    if not name:
        print("No active project set. Set one with: obliquity project use <name>")
        return
    kv("Active project", name)
    kv("Source", "OBLIQUITY_PROJECT env" if env_project else "config")
    conn = connect(DB_PATH)
    project = get_project(conn, name)
    if project is None:
        print(c("warning: this project no longer exists (was it archived?)", "yellow"))
        return

    hosts = list_hosts(conn, project["id"])
    jobs = list_crack_jobs(conn, project["id"])
    login_jobs = list_login_jobs(conn, project["id"])
    kv("Root", project["root_dir"])
    kv("Created", project["created_at"])

    # Targets block: hosts comma-separated, then the distinct metadata across
    # them (usually one host, so this reads as that host's tech/profile/server).
    kv("Host[s]", ", ".join(h["url"] for h in hosts) if hosts else "(none yet)")
    kv("Tech", _distinct_meta(hosts, "tech"))
    kv("Profile", _distinct_meta(hosts, "profile"))
    kv("Server", _distinct_meta(hosts, "server"))
    if jobs:
        kv("Crack jobs", ", ".join(j["name"] or j["hash_file"] for j in jobs))
    if login_jobs:
        kv("Login jobs", ", ".join(j["name"] or j["target"] for j in login_jobs))

    subsection("Gameplan per tool", "magenta")
    labels = {"bust": "Bust ", "crack": "Crack", "fuzz": "Fuzz ", "brute": "Brute"}
    for tool, desc in _default_gameplan_display(project):
        line = desc
        opts = get_project_options(conn, project["id"], tool)
        if opts:
            line += "   [" + ", ".join(f"{k}={v}" for k, v in sorted(opts.items())) + "]"
        kv(labels.get(tool, tool), line)
    print(c("Change with: obliquity project set-gameplan <tool> <name>, or "
            "obliquity set <tool> <option> <value>.", "gray"))


def _distinct_meta(hosts, field: str) -> str:
    vals = []
    for h in hosts:
        v = h[field]
        if v and v not in vals:
            vals.append(v)
    return ", ".join(vals) if vals else "-"


def _host_meta_summary(host) -> str:
    parts = []
    for field in ("profile", "tech", "server"):
        val = host[field]
        if val:
            parts.append(f"{field}={val}")
    return ", ".join(parts) if parts else "no metadata"


def _opt_for(tool: str, key: str):
    for opt in OPTION_SCHEMA.get(tool, []):
        if opt.key == key:
            return opt
    return None


def cmd_set(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    tool, key, value = args.tool, args.key.lower(), args.value
    opt = _opt_for(tool, key)
    if opt is None:
        valid = ", ".join(o.key for o in OPTION_SCHEMA[tool])
        die(f"unknown option '{key}' for {tool}. Valid: {valid}")
    if opt.typ == "int":
        try:
            int(value)
        except ValueError:
            die(f"{tool} {key} expects an integer, got: {value}")

    if key == "gameplan":
        # Validate and store in the dedicated default-gameplan column.
        resolver = {"bust": resolve_gameplan, "fuzz": resolve_fuzz_plan,
                    "crack": resolve_crackplan, "brute": resolve_loginplan}[tool]
        try:
            resolver(value)
        except Exception as exc:  # noqa: BLE001
            die(f"not a valid {tool} gameplan: {value} ({exc})")
        set_project_default_gameplan(conn, project["id"], tool, value)
    else:
        set_project_option(conn, project["id"], tool, key, value)

    section("Option set", "green")
    kv("Project", project["name"])
    print(c(f"{tool} {key} => {value}", "cyan", bold=True))
    print(c(f"'obliquity {tool} run' will use it (an explicit --{key.replace('_','-')} still overrides).", "gray"))


def cmd_unset(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    tool, key = args.tool, args.key.lower()
    if _opt_for(tool, key) is None:
        valid = ", ".join(o.key for o in OPTION_SCHEMA[tool])
        die(f"unknown option '{key}' for {tool}. Valid: {valid}")
    if key == "gameplan":
        set_project_default_gameplan(conn, project["id"], tool, None)
        removed = True
    else:
        removed = unset_project_option(conn, project["id"], tool, key)
    section("Option unset" if removed else "Nothing to unset", "green" if removed else "yellow")
    kv("Project", project["name"])
    kv(f"{tool} {key}", "reverted to default" if removed else "was not set")


def cmd_options(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    tool = args.tool
    stored = get_project_options(conn, project["id"], tool)
    gameplan_default = project[_GAMEPLAN_COLUMN[tool]]
    section(f"Options: {tool}  (project {project['name']})", "cyan")
    header = f"  {'OPTION'.ljust(10)} {'VALUE'.ljust(30)} {'REQUIRED'.ljust(9)} SOURCE"
    print(c(header, "gray", bold=True))
    for opt in OPTION_SCHEMA[tool]:
        if opt.key == "gameplan":
            value = gameplan_default or "(built-in default)"
            source = "set" if gameplan_default else "default"
        elif opt.key in stored:
            value = stored[opt.key]
            source = "set"
        else:
            value = "-"
            source = "-"
        req = "yes" if opt.required else "no"
        color = "green" if source == "set" else "yellow" if opt.required and source == "-" else "cyan"
        print(f"  {c(opt.key.ljust(10), color, bold=True)} {str(value).ljust(30)} {req.ljust(9)} {source}")
    print(c(f"\nSet with:  obliquity set {tool} <option> <value>", "gray"))
    print(c(f"Then run:  obliquity {tool} run", "gray"))
    print(c("(You can still pass flags directly on 'run' -- they override stored options.)", "gray"))


def cmd_project_set_gameplan(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    tool = args.tool
    if args.clear:
        set_project_default_gameplan(conn, project["id"], tool, None)
        section("Project default cleared", "green")
        kv("Project", project["name"])
        kv(f"{tool} default", "(reverted to built-in default)")
        return

    name = args.name
    if not name:
        die(f"provide a gameplan name, or use --clear to revert {tool} to the built-in default")
    # Validate the plan exists (built-in name or JSON path) before saving, so a
    # typo fails now instead of at the next run.
    resolver = {
        "bust": resolve_gameplan,
        "fuzz": resolve_fuzz_plan,
        "crack": resolve_crackplan,
        "brute": resolve_loginplan,
    }[tool]
    try:
        resolver(name)
    except Exception as exc:  # noqa: BLE001 -- surface any resolution failure as a friendly error
        die(f"not a valid {tool} gameplan: {name} ({exc})")

    set_project_default_gameplan(conn, project["id"], tool, name)
    section("Project default set", "green")
    kv("Project", project["name"])
    kv(f"{tool} default", name)
    print(c(f"{tool} commands for this project now use this gameplan unless you pass --gameplan.", "gray"))


def cmd_project_unset(args) -> None:
    clear_active_project()
    section("Active project cleared", "green")
    print(c("Commands will now require an explicit project name again "
            "(unless OBLIQUITY_PROJECT is set).", "gray"))


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


def cmd_project_delete(args) -> None:
    conn = connect(DB_PATH)
    project = get_project(conn, args.name)
    if project is None:
        die(f"project not found: {args.name}")
    root = Path(project["root_dir"])
    if not args.yes:
        section("Confirm project deletion", "red")
        kv("Project", project["name"], color="red")
        kv("Files to delete", root, color="red")
        print(c("This PERMANENTLY deletes the project's database records (hosts, runs, "
                "findings, crack jobs, cracked hashes) and its files on disk.", "red"))
        print(c("This cannot be undone. To keep a copy instead, use: obliquity project archive", "yellow"))
        print(c("Re-run with --yes to delete.", "red", bold=True))
        return

    if root.exists():
        shutil.rmtree(root)
    delete_project(conn, project["id"])
    if (os.environ.get("OBLIQUITY_PROJECT") or active_project()) == project["name"]:
        clear_active_project()
    section("Project deleted", "green")
    kv("Project", project["name"])


def cmd_host_add(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    host = add_host(conn, project["id"], args.url, args.profile, args.server, args.tech, args.notes)
    section("Host added", "green")
    kv("Project", project["name"])
    kv("URL", host["url"])
    kv("Profile", host["profile"])
    kv("Server", host["server"] or "-")
    kv("Tech", host["tech"] or "-")


def cmd_host_list(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
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
    project = resolve_project(conn, args)
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
    project = resolve_project(conn, args)
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
    project = resolve_project(conn, args)
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
    project = resolve_project(conn, args)
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
    project = resolve_project(conn, args)
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
    # Optional tool filter: `gameplans list bust|fuzz|crack` shows just that
    # pillar. None = show all three. (fuzz's own `list` subcommand doesn't set
    # this attribute, so getattr defaults to None -> all.)
    tool = getattr(args, "tool", None)

    if tool in (None, "bust"):
        section("Feroxbuster bust gameplans", "cyan")
        for path in list_builtin_gameplans():
            gameplan = load_gameplan(path)
            subsection(gameplan.name, "magenta")
            if gameplan.description:
                bullet("Description", gameplan.description)
            bullet("Stages", len(gameplan.stages))
            if not args.brief:
                for row in preview_plan("https://example.local", gameplan):
                    print(f"  {c(str(row['number']) + '. ' + row['name'], 'yellow', bold=True)}")
                    print(f"     {c('Wordlist:', 'cyan', bold=True)} {row['wordlist']}")
                    print(f"     {c('Extensions:', 'cyan', bold=True)} {fmt_list(row['extensions'])}")
                    print(f"     {c('Recursion:', 'cyan', bold=True)} {fmt_recursion(row['recursion'], row['depth'])}")
                blank()

    if tool in (None, "fuzz"):
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

    if tool in (None, "crack"):
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
                    if row.get("wordlist"):
                        print(f"     {c('Wordlist:', 'cyan', bold=True)} {row['wordlist']}")
                    if row.get("wordlist2"):
                        print(f"     {c('Wordlist 2:', 'cyan', bold=True)} {row['wordlist2']}")
                    if row.get("rules"):
                        print(f"     {c('Rules:', 'cyan', bold=True)} {fmt_list(row['rules'])}")
                    if row.get("mask"):
                        print(f"     {c('Mask:', 'cyan', bold=True)} {row['mask']}")
                blank()

    if tool in (None, "brute"):
        section("Brute login gameplans (backend: hydra)", "cyan")
        for path in list_builtin_loginplans():
            plan = load_loginplan(path)
            subsection(plan.name, "magenta")
            if plan.description:
                bullet("Description", plan.description)
            bullet("Stages", len(plan.stages))
            bullet("Tool", "hydra")
            if not args.brief:
                for row in preview_loginplan(plan):
                    print(f"  {c(str(row['number']) + '. ' + row['name'], 'yellow', bold=True)}")
                    print(f"     {c('Usernames:', 'cyan', bold=True)} {row.get('username') or row.get('userlist')}")
                    print(f"     {c('Passwords:', 'cyan', bold=True)} {row.get('password') or row.get('passlist')}")
                blank()


_TOOL_RUN_HINT = {
    "bust": "obliquity bust run <project> [url] --gameplan <name>   (also: plan, resume)",
    "fuzz": "obliquity fuzz run <project> [url] --gameplan <name> --endpoint /path   (also: plan, resume)",
    "crack": "obliquity crack run <project> [job] --gameplan <name>   (also: job add/list, plan, resume)",
    "brute": "obliquity brute run <project> [job] --gameplan <name>   (also: job add/list, plan, resume, creds)",
}


def cmd_tool_gameplans(args) -> None:
    """Bare `obliquity <tool>` (no subcommand) lists that pillar's gameplans."""
    tool = args._tool
    args.tool = tool
    if not hasattr(args, "brief"):
        args.brief = False
    cmd_gameplans_list(args)
    print(c(f"\nRun one: {_TOOL_RUN_HINT.get(tool, '')}", "gray"))
    print(c(f"Full help: obliquity {tool} -h", "gray"))


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
            if stage.wordlist2:
                referenced_paths.add(stage.wordlist2)
            for rule in stage.rules or []:
                referenced_paths.add(rule)

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


def _resolve_wordlist_target(target: str) -> str:
    """Resolve an `inspect` argument that may be a catalog name, a bare
    filename Obliquity has downloaded, or a filesystem path."""
    entry = catalog_by_name(target)
    if entry is not None:
        return str(installed_path(entry))
    return resolve_path(target)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def cmd_wordlists_inspect(args) -> None:
    path = _resolve_wordlist_target(args.target)
    analysis = analyze_wordlist(path)
    section("Wordlist inspection", "cyan")
    kv("Requested", args.target)
    kv("Resolved path", analysis.path)
    if not analysis.exists:
        print(c("File not found. If it's a catalog entry, install it with: "
                f"obliquity wordlists install {args.target}", "yellow"))
        return
    kv("Entries", f"{analysis.line_count:,}")
    kv("Size", _human_size(analysis.byte_size))
    verdict = "yes" if analysis.has_extensions else "no"
    color = "yellow" if analysis.has_extensions else "green"
    kv("Contains extensions", f"{verdict} ({analysis.extension_ratio:.0%} of a {analysis.sampled}-entry sample)", color=color)
    if analysis.top_extensions:
        bullet("Most common", ", ".join(f".{ext} ({count})" for ext, count in analysis.top_extensions), color=color)
    if analysis.has_extensions:
        print(c("Heads up: appending extensions to this list in a gameplan stage would "
                "create double-extension requests (e.g. foo.php.php). Use it as-is, without "
                "appended extensions.", "yellow"))
    if analysis.preview:
        subsection("Preview (first entries)", "magenta")
        for line in analysis.preview:
            print(f"  {line}")


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
    project = resolve_project(conn, args)
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
    # "operation" is the kind of work a run did; spell it out once so the
    # column values (content-path, parameter-name, ...) aren't cryptic.
    print(c("operation = kind of work: content-path (directory/file discovery), "
            "parameter-name/parameter-value/request-input (fuzzing), "
            "dictionary/mask/... (cracking), login (credential attack).", "gray"))
    header = (
        f"  {'OPERATION'.ljust(18)} "
        f"{'TOOL'.ljust(20)} "
        f"{'STATUS'.ljust(12)} "
        f"GAMEPLAN"
    )
    current_host = None
    for row in rows:
        if row["host_url"] != current_host:
            current_host = row["host_url"]
            subsection(f"Host: {current_host}", "magenta")
            print(c(header, "gray", bold=True))
        pillar = TOOL_LABELS.get(row["tool"], row["tool"])
        tool_label = f"[{pillar}] {row['tool']}"
        print(
            f"  {c(row['operation_category'].ljust(18), 'cyan', bold=True)} "
            f"{c(tool_label.ljust(20), 'yellow')} "
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
    normalize_host_target(args)
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "fuzz", args)
    host = require_host(conn, project, args.url)
    fuzz_name = args.gameplan or project["default_fuzz_gameplan"] or "parameter-names-quick"
    plan = resolve_fuzz_plan(fuzz_name)
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


def resolve_bust_gameplan_choice(project, host, args) -> tuple:
    # explicit --gameplan > project default > host-metadata recommendation > generic-quick
    if args.gameplan:
        return resolve_gameplan(args.gameplan), None
    if project["default_bust_gameplan"]:
        return resolve_gameplan(project["default_bust_gameplan"]), "project default"
    name, reason = recommend_gameplan(host)
    return resolve_gameplan(name), reason


def apply_bust_recursion_overrides(gameplan, args) -> None:
    """Let --depth / --no-recurse override the gameplan's per-stage recursion
    settings for every stage. Mutating the stage fields is enough: recursion
    and depth are both part of the stage fingerprint, so an overridden scan is
    correctly treated as a distinct run rather than colliding with a cached one."""
    if getattr(args, "no_recurse", False):
        for stage in gameplan.stages:
            stage.recursion = False
            stage.depth = None
    elif getattr(args, "depth", None) is not None:
        for stage in gameplan.stages:
            stage.recursion = True
            stage.depth = args.depth

    # Response filters given on the CLI apply to every stage, overriding the
    # gameplan's own filter fields for those axes.
    def _int_csv(flag, value):
        try:
            return [int(x) for x in value.split(",") if x.strip()]
        except ValueError:
            die(f"{flag} expects comma-separated integers, got: {value}")

    for attr, flag in (
        ("filter_status", "--filter-status"),
        ("filter_size", "--filter-size"),
        ("filter_words", "--filter-words"),
        ("filter_lines", "--filter-lines"),
    ):
        raw = getattr(args, attr, None)
        if raw:
            value = _int_csv(flag, raw)
            for stage in gameplan.stages:
                setattr(stage, attr, value)
    if getattr(args, "filter_regex", None):
        for stage in gameplan.stages:
            stage.filter_regex = args.filter_regex


def cmd_bust_plan(args) -> None:
    conn = connect(DB_PATH)
    normalize_host_target(args)
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "bust", args)
    host = require_host(conn, project, args.url)
    gameplan, reason = resolve_bust_gameplan_choice(project, host, args)
    apply_bust_recursion_overrides(gameplan, args)
    print_gameplan_summary(project, host, gameplan, mode="Plan Preview", args=args, recommended_reason=reason)


def cmd_bust_run(args) -> None:
    conn = connect(DB_PATH)
    normalize_host_target(args)
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "bust", args)
    host = require_host(conn, project, args.url)
    gameplan, reason = resolve_bust_gameplan_choice(project, host, args)
    apply_bust_recursion_overrides(gameplan, args)
    original_name = gameplan.name
    gameplan = maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)
    if gameplan.name != original_name:
        reason = None

    mode = "Dry Run" if args.dry_run else "Resume" if getattr(args, "resume", False) else "Run"
    print_gameplan_summary(project, host, gameplan, mode=mode, args=args, recommended_reason=reason)

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
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "crack", args)
    job = require_job(conn, project, args.job)
    crack_name = args.gameplan or project["default_crackplan"] or "quick-dictionary"
    crackplan = resolve_crackplan(crack_name)
    print_crackplan_summary(project, job, crackplan, mode="Plan Preview", args=args)


def cmd_crack_run(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "crack", args)
    job = require_job(conn, project, args.job)
    crack_name = args.gameplan or project["default_crackplan"] or "quick-dictionary"
    crackplan = resolve_crackplan(crack_name)
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


# --- thc-hydra pillar: online login attacks ---------------------------------

def _default_port_for_url(url: str) -> str:
    # crude host extraction from a stored host URL, for seeding a login job
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.hostname or url


def normalize_login_job_target(conn, args) -> None:
    """`hydra job add` takes an optional `project` then an optional `target`.
    If the user gives a single positional that isn't the name of an existing
    project (while an active project is set), they meant it as the target --
    shuffle it so the project resolves from the active/env setting."""
    proj = getattr(args, "project", None)
    if proj and not getattr(args, "target", None) and get_project(conn, proj) is None:
        args.target = proj
        args.project = None


def cmd_brute_job_add(args) -> None:
    conn = connect(DB_PATH)
    normalize_login_job_target(conn, args)
    project = resolve_project(conn, args)
    if args.service not in KNOWN_SERVICES:
        die(f"unknown service '{args.service}'. Known services: {', '.join(sorted(KNOWN_SERVICES))}")
    if args.service in FORM_SERVICES and not args.form_spec:
        die(f"service '{args.service}' requires --form-spec, e.g. "
            "--form-spec \"/login:user=^USER^&pass=^PASS^:F=invalid\"")

    # Optionally link to an existing host (for reporting) and seed the target
    # from it when the user gave a host instead of a raw target.
    host_id = None
    target = args.target
    if args.host:
        host = get_host(conn, project["id"], args.host)
        if host is None:
            die(f"host not found in project: {args.host}. Add it with: obliquity host add {project['name']} {args.host}")
        host_id = host["id"]
        if not target:
            target = _default_port_for_url(host["url"])
    if not target:
        die("provide a target (hostname/IP), or --host <url> to seed it from a project host")

    job = add_login_job(
        conn, project["id"], service=args.service, target=target, name=args.name,
        host_id=host_id, port=args.port, form_spec=args.form_spec,
        module_args=args.module_args, notes=args.notes,
    )
    section("Login job added", "green")
    kv("Project", project["name"])
    kv("Job", job["name"] or "-")
    kv("Service", job["service"])
    kv("Target", job["target"])
    if job["port"]:
        kv("Port", job["port"])
    if job["form_spec"]:
        kv("Form spec", job["form_spec"])


def cmd_brute_job_list(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    jobs = list_login_jobs(conn, project["id"])
    section(f"Login jobs: {project['name']}", "cyan")
    if not jobs:
        print("No login jobs added yet.")
        return
    for job in jobs:
        subsection(job["name"] or job["target"], "magenta")
        bullet("Service", job["service"])
        bullet("Target", job["target"] + (f":{job['port']}" if job["port"] else ""))
        if job["form_spec"]:
            bullet("Form spec", job["form_spec"])
        if job["module_args"]:
            bullet("Module args", job["module_args"])
        if job["notes"]:
            bullet("Notes", job["notes"])


def cmd_brute_job_remove(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    if not args.yes:
        section("Confirm login job removal", "yellow")
        kv("Project", project["name"], color="yellow")
        kv("Target", args.target, color="yellow")
        print(c("This will remove the login job and related run/credential records from the database.", "yellow"))
        print(c("Re-run with --yes to confirm.", "yellow", bold=True))
        return
    removed = delete_login_job(conn, project["id"], args.target)
    if not removed:
        die(f"login job not found in project: {args.target}")
    section("Login job removed", "green")
    kv("Project", project["name"])
    kv("Target", args.target)


def _login_stage_detail(row: dict) -> str:
    user = row.get("username") or (Path(row["userlist"]).name if row.get("userlist") else "?")
    pw = row.get("password") or (Path(row["passlist"]).name if row.get("passlist") else "?")
    return f"{user} x {pw}"


def print_login_stage_summary(row: dict) -> None:
    subsection(f"Stage {row['number']}: {row['name']}", "magenta")
    bullet("Usernames", row.get("username") or row.get("userlist") or "?")
    bullet("Passwords", row.get("password") or row.get("passlist") or "?")
    if row.get("tasks"):
        bullet("Tasks (-t)", row["tasks"])
    bullet("Stop on first valid", "yes" if row.get("stop_on_first_valid") else "no")


def print_loginplan_summary(project: dict, job: dict, plan, *, mode: str, args) -> None:
    section(f"Obliquity Brute: {mode}", "cyan")
    kv("Project", project["name"])
    kv("Job", job["name"] or job["target"])
    kv("Service", job["service"])
    kv("Target", job["target"] + (f":{job['port']}" if job["port"] else ""))
    if job["form_spec"]:
        kv("Form spec", job["form_spec"])
    kv("Selected loginplan", plan.name)
    if plan.description:
        kv("Description", plan.description)
    kv("Stages", len(plan.stages))
    kv("Output root", Path(project["root_dir"]) / "runs" / "hydra")

    option_bits = []
    if getattr(args, "force", False):
        option_bits.append("force-rerun=true")
    kv("Run options", ", ".join(option_bits) if option_bits else "default")

    # Online password attacks are noisy and can lock accounts -- say so plainly.
    section("Authorization & safety", "yellow")
    print(c("hydra performs LIVE online login attempts against the target. Only run this "
            "against systems you are explicitly authorized to test. Online guessing can "
            "trigger account lockouts, rate limits, and alerts -- keep -t (tasks) low and "
            "prefer small, targeted credential lists.", "yellow"))

    if mode == "Plan Preview":
        section("Stages queued", "blue")
        for row in preview_loginplan(plan):
            print_login_stage_summary(row)


def print_login_event(event: dict) -> None:
    action = event.get("action")
    n = _stage_n(event)

    if action == "skipped":
        print(c(f"  - {n}  skipped ({event.get('reason', 'already completed')})", "yellow"))
        return

    if action == "planned":
        subsection(f"Planned {n}", "magenta")
        bullet("Usernames", event.get("username") or event.get("userlist"))
        bullet("Passwords", event.get("password") or event.get("passlist"))
        command_block(event.get("command", ""))
        return

    if action == "starting":
        line = c(f"  > {n}", "green", bold=True) + c(f"   {_login_stage_detail(event)}", "cyan")
        print(line)
        return

    if action == "progress":
        if supports_color():
            print(f"\r{live_progress_line(event)}", end="", flush=True)
        return

    if action == "ran":
        _clear_progress_line()
        status = event.get("status", "unknown")
        mark = {"completed": "OK", "interrupted": "INT"}.get(status, "FAIL")
        color = {"completed": "green", "interrupted": "yellow"}.get(status, "red")
        line = c(f"  {mark} {n}", color, bold=True) + c(f"   {event.get('new_findings')} creds found", color)
        if event.get("error"):
            line += c(f"   {event['error']}", color)
        print(line)
        return


def normalize_login_run_target(conn, args) -> None:
    """`hydra plan/run` take an optional `project` then an optional `job`. If the
    single positional given isn't an existing project (with an active project
    set), treat it as the job name against the active project."""
    proj = getattr(args, "project", None)
    if proj and not getattr(args, "job", None) and get_project(conn, proj) is None:
        args.job = proj
        args.project = None


def cmd_brute_plan(args) -> None:
    conn = connect(DB_PATH)
    normalize_login_run_target(conn, args)
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "brute", args)
    job = require_login_job(conn, project, args.job)
    plan = resolve_loginplan(args.gameplan or project["default_bruteplan"] or "quick")
    print_loginplan_summary(project, job, plan, mode="Plan Preview", args=args)


def cmd_brute_run(args) -> None:
    conn = connect(DB_PATH)
    normalize_login_run_target(conn, args)
    project = resolve_project(conn, args)
    apply_stored_options(conn, project, "brute", args)
    job = require_login_job(conn, project, args.job)
    plan = resolve_loginplan(args.gameplan or project["default_bruteplan"] or "quick")

    mode = "Dry Run" if args.dry_run else "Resume" if getattr(args, "resume", False) else "Run"
    print_loginplan_summary(project, job, plan, mode=mode, args=args)

    section("Execution", "cyan")
    results = run_loginplan(
        conn, project, job, plan,
        force=args.force, dry_run=args.dry_run, event_callback=print_login_event,
    )

    completed = sum(1 for item in results if item.get("status") == "completed")
    skipped = sum(1 for item in results if item.get("action") == "skipped")
    planned = sum(1 for item in results if item.get("action") == "planned")
    failed = sum(1 for item in results if item.get("status") == "failed")
    interrupted = sum(1 for item in results if item.get("status") == "interrupted")
    found = sum(int(item.get("new_findings") or 0) for item in results)

    summary_color = "red" if failed else "yellow" if interrupted else "green"
    section("Run summary", summary_color)
    kv("Completed stages", completed, color="green")
    kv("Skipped stages", skipped, color="yellow")
    kv("Planned stages", planned, color="magenta")
    kv("Failed stages", failed, color="red" if failed else "green")
    kv("Interrupted stages", interrupted, color="yellow" if interrupted else "green")
    kv("Credentials found", found)
    kv("Report command", f"obliquity report html {project['name']}")
    if found:
        kv("View", f"obliquity brute creds {project['name']}")


def cmd_brute_resume(args) -> None:
    args.resume = True
    cmd_brute_run(args)


def cmd_brute_creds(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    creds = get_found_credentials(conn, project["id"])
    section(f"Found credentials: {project['name']}", "cyan")
    if not creds:
        print("No credentials found yet.")
        return
    for row in creds:
        subsection(f"{row['username']} : {row['password']}", "green")
        bullet("Service", row["service"])
        bullet("Target", row["target"])
        bullet("Found via", f"{row['loginplan_name']} / {row['stage_name']}")


def gather_report_data(conn, project):
    return (
        get_runs(conn, project["id"]),
        get_findings(conn, project["id"]),
        get_crack_runs(conn, project["id"]),
        get_cracked_hashes(conn, project["id"]),
        get_login_runs(conn, project["id"]),
        get_found_credentials(conn, project["id"]),
    )


def write_html_report(conn, project, output: Path | None = None) -> Path:
    runs, findings, crack_runs, cracked_hashes, login_runs, found_credentials = gather_report_data(conn, project)
    output = output or Path(project["root_dir"]) / "report.html"
    generate_html(project, runs, findings, output, crack_runs=crack_runs, cracked_hashes=cracked_hashes,
                  login_runs=login_runs, found_credentials=found_credentials)
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
    project = resolve_project(conn, args)
    output = write_html_report(conn, project, Path(args.output) if args.output else None)
    if args.open:
        open_html_report(output)


def cmd_report_json(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    runs, findings, crack_runs, cracked_hashes, login_runs, found_credentials = gather_report_data(conn, project)
    output = Path(args.output) if args.output else Path(project["root_dir"]) / "report.json"
    generate_json(project, runs, findings, output, crack_runs=crack_runs, cracked_hashes=cracked_hashes,
                  login_runs=login_runs, found_credentials=found_credentials)
    section("JSON report", "green")
    kv("Report written", output)


CSV_DATASETS = {
    "findings": lambda data: data[1],
    "cracked-hashes": lambda data: data[3],
    "runs": lambda data: data[0],
    "crack-runs": lambda data: data[2],
    "login-runs": lambda data: data[4],
    "found-credentials": lambda data: data[5],
}


def cmd_report_csv(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    data = gather_report_data(conn, project)
    rows = CSV_DATASETS[args.kind](data)
    output = Path(args.output) if args.output else Path(project["root_dir"]) / f"report-{args.kind}.csv"
    generate_csv(rows, output)
    section("CSV report", "green")
    kv("Dataset", args.kind)
    kv("Rows", len(rows))
    kv("Report written", output)


def cmd_report_markdown(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
    runs, findings, crack_runs, cracked_hashes, login_runs, found_credentials = gather_report_data(conn, project)
    output = Path(args.output) if args.output else Path(project["root_dir"]) / "report.md"
    generate_markdown(project, runs, findings, output, crack_runs=crack_runs, cracked_hashes=cracked_hashes,
                      login_runs=login_runs, found_credentials=found_credentials)
    section("Markdown report", "green")
    kv("Report written", output)


def cmd_manual(args) -> None:
    from obliquity.manual import print_manual
    print_manual()


def cmd_explore(args) -> None:
    # Lazy import so a TUI backend is only pulled in when the explorer runs.
    from obliquity.explorer_tui import run_explorer

    prefer = getattr(args, "backend", "auto")
    if getattr(args, "no_tui", False) or os.environ.get("OBLIQUITY_NO_TUI"):
        prefer = "text"

    conn = connect(DB_PATH)
    # Soft-resolve the active project (no error if none) so Enter can "load" a
    # gameplan as that project's default for its tool.
    name = os.environ.get("OBLIQUITY_PROJECT") or active_project()
    project = get_project(conn, name) if name else None

    def on_load(tool: str, gameplan_name: str) -> str:
        if project is None:
            return "No active project -- run 'obliquity project use <name>' first, then reopen."
        set_project_default_gameplan(conn, project["id"], tool, gameplan_name)
        return f"Loaded: {project['name']} {tool} default -> {gameplan_name}"

    run_explorer(
        prefer=prefer,
        on_load=on_load,
        project_label=(project["name"] if project else None),
    )


def cmd_runs(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
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


TOOL_LABELS = {"feroxbuster": "bust", "ffuf": "fuzz", "hashcat": "crack", "hydra": "brute"}


def cmd_history(args) -> None:
    conn = connect(DB_PATH)
    project = resolve_project(conn, args)
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
    project_host_args.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    project_host_args.add_argument(
        "url", nargs="?",
        help="host URL or host name already added to the project (optional if the project has exactly one host)",
    )

    fuzz_scan_args = argparse.ArgumentParser(add_help=False)
    fuzz_scan_args.add_argument("--gameplan", default=None, help="ffuf gameplan name (default: the project default, else parameter-names-quick)")
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

    manual = sub.add_parser(
        "manual", help="show the full Obliquity manual (all commands, reformatted)",
        description="Print the complete Obliquity manual in the terminal -- every command with an "
        "example. Works on all platforms; pipe to a pager for scrolling (e.g. 'obliquity manual | less -R'). "
        "On Linux/macOS you can also install the man page for 'man obliquity' (see the README).",
        formatter_class=formatter, epilog="example:\n  obliquity manual",
    )
    manual.set_defaults(func=cmd_manual)

    # --- Metasploit-style stateful options (set / unset / options) ---
    _tool_choices = ["bust", "fuzz", "crack", "brute"]
    setp = sub.add_parser(
        "set", help="set a per-tool option on the active project (Metasploit-style)",
        description="Store an option for a tool so 'run' can use it without flags. "
        "An explicit flag on 'run' always overrides a stored option.",
        formatter_class=formatter,
        epilog="examples:\n"
        "  obliquity set fuzz host https://app.acme.test\n"
        "  obliquity set fuzz endpoint /search\n"
        "  obliquity set bust gameplan generic-deep\n"
        "  obliquity options fuzz     # then:  obliquity fuzz run",
    )
    setp.add_argument("tool", choices=_tool_choices)
    setp.add_argument("key", help="option name (see 'obliquity options <tool>')")
    setp.add_argument("value", help="value to store")
    setp.add_argument("--project", help="project name (optional if an active project is set)")
    setp.set_defaults(func=cmd_set)

    unsetp = sub.add_parser(
        "unset", help="clear a per-tool option on the active project", formatter_class=formatter,
        epilog="example:\n  obliquity unset fuzz endpoint",
    )
    unsetp.add_argument("tool", choices=_tool_choices)
    unsetp.add_argument("key", help="option name to clear")
    unsetp.add_argument("--project", help="project name (optional if an active project is set)")
    unsetp.set_defaults(func=cmd_unset)

    optp = sub.add_parser(
        "options", help="show settable options for a tool (Metasploit 'show options')",
        formatter_class=formatter, epilog="example:\n  obliquity options fuzz",
    )
    optp.add_argument("tool", choices=_tool_choices)
    optp.add_argument("--project", help="project name (optional if an active project is set)")
    optp.set_defaults(func=cmd_options)

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

    wins = wordlists_sub.add_parser(
        "inspect", help="analyze a wordlist: size, whether it carries extensions, preview",
        formatter_class=formatter,
        epilog="examples:\n  obliquity wordlists inspect seclists-common\n  obliquity wordlists inspect /usr/share/seclists/Discovery/Web-Content/raft-medium-files.txt",
    )
    wins.add_argument("target", help="catalog entry name or a path to a wordlist file")
    wins.set_defaults(func=cmd_wordlists_inspect)

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
    fuzz.set_defaults(func=cmd_tool_gameplans, _tool="fuzz")
    fuzz_sub = fuzz.add_subparsers(dest="fuzz_cmd", required=False)
    fl = fuzz_sub.add_parser("list", help="list ffuf gameplans", formatter_class=formatter)
    fl.add_argument("--brief", action="store_true")
    fl.set_defaults(func=cmd_gameplans_list, tool="fuzz")
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
    coverage.add_argument("project", nargs="?")
    coverage.add_argument("url", nargs="?")
    coverage.set_defaults(func=cmd_coverage)

    explore = sub.add_parser(
        "explore",
        help="wordlist explorer -- interactive TUI to browse gameplans and wordlists",
        description="Interactive Wordlist Explorer. Scroll through every built-in gameplan "
        "and every referenced/catalog wordlist; the detail pane shows length, size, whether "
        "it carries extensions, a head/tail sample, description and typical use, which "
        "gameplan(s) reference it, and similar wordlists. Falls back to a plain listing when "
        "there is no interactive terminal.",
        epilog="example:\n  obliquity explore\n  obliquity explore --backend textual",
        formatter_class=formatter,
    )
    explore.add_argument(
        "--backend", choices=["auto", "curses", "textual", "text"], default="auto",
        help="TUI backend (default: auto -- curses on macOS/Linux, Textual on Windows, text otherwise)",
    )
    explore.add_argument(
        "--no-tui", action="store_true",
        help="skip the interactive TUI and print a plain text listing instead "
        "(same as --backend text; can also set OBLIQUITY_NO_TUI)",
    )
    explore.set_defaults(func=cmd_explore)

    gameplans = sub.add_parser("gameplans", help="inspect built-in scan gameplans")
    gameplans_sub = gameplans.add_subparsers(dest="gameplans_cmd", required=True)
    gl = gameplans_sub.add_parser(
        "list",
        help="list available gameplans",
        description="List built-in gameplans, their stages, wordlists, and extensions. "
        "Pass a tool (bust/fuzz/crack) to show only that pillar's gameplans.",
        epilog="examples:\n  obliquity gameplans list\n  obliquity gameplans list crack\n  obliquity gameplans list bust --brief",
        formatter_class=formatter,
    )
    gl.add_argument("tool", nargs="?", choices=["bust", "fuzz", "crack", "brute"], help="show only this tool's gameplans (default: all)")
    gl.add_argument("--brief", action="store_true", help="show only names and summary fields")
    gl.set_defaults(func=cmd_gameplans_list)

    project = sub.add_parser("project", help="create and manage Obliquity projects")
    project_sub = project.add_subparsers(dest="project_cmd", required=True)
    ple = project_sub.add_parser(
        "list",
        help="list all projects with host/job/run counts",
        epilog="example:\n  obliquity project list",
        formatter_class=formatter,
    )
    ple.set_defaults(func=cmd_project_list)

    puse = project_sub.add_parser(
        "use",
        help="set the active project (defaults future commands to it)",
        description="Select the active project. Later commands default to it, so you "
        "don't have to name it every time. Explicit names, --project, and "
        "OBLIQUITY_PROJECT all override it.",
        epilog="example:\n  obliquity project use acme",
        formatter_class=formatter,
    )
    puse.add_argument("name", help="project to make active")
    puse.set_defaults(func=cmd_project_use)

    pcur = project_sub.add_parser("current", help="show the active project", formatter_class=formatter)
    pcur.set_defaults(func=cmd_project_current)

    puns = project_sub.add_parser("unset", help="clear the active project", formatter_class=formatter)
    puns.set_defaults(func=cmd_project_unset)

    psg = project_sub.add_parser(
        "set-gameplan",
        help="set (or clear) a project's default gameplan for a tool",
        description="Set the default gameplan a tool uses for this project, so you "
        "don't have to pass --gameplan every time. Explicit --gameplan on a run "
        "always overrides it. Use --clear to revert to Obliquity's built-in default.",
        epilog="examples:\n"
        "  obliquity project set-gameplan bust generic-deep\n"
        "  obliquity project set-gameplan crack rules-basic --project acme\n"
        "  obliquity project set-gameplan fuzz --clear",
        formatter_class=formatter,
    )
    psg.add_argument("tool", choices=["bust", "fuzz", "crack", "brute"], help="which tool's default to change")
    psg.add_argument("name", nargs="?", help="built-in gameplan name or JSON path (omit with --clear)")
    psg.add_argument("--project", help="project name (optional if an active project is set via 'project use')")
    psg.add_argument("--clear", action="store_true", help="revert to the built-in default for this tool")
    psg.set_defaults(func=cmd_project_set_gameplan)

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

    pd = project_sub.add_parser(
        "delete",
        help="permanently delete a project (DB records + files on disk)",
        description="Permanently delete a project: its database records and its files "
        "on disk. Cannot be undone -- use 'project archive' to keep a backup instead.",
        formatter_class=formatter,
        epilog="example:\n  obliquity project delete acme --yes",
    )
    pd.add_argument("name", help="project name")
    pd.add_argument("--yes", action="store_true", help="delete without prompting")
    pd.set_defaults(func=cmd_project_delete)

    host = sub.add_parser("host", help="add, inspect, update, or remove project hosts")
    host_sub = host.add_subparsers(dest="host_cmd", required=True)
    ha = host_sub.add_parser(
        "add", help="add a host", formatter_class=formatter,
        epilog="example:\n  obliquity host add acme https://app.acme.test --profile php --server apache --tech php",
    )
    ha.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    ha.add_argument("url", help="target base URL, including scheme")
    ha.add_argument("--tech", help="backend language/framework: aspnet, php, java, node, python")
    ha.add_argument("--server", help="web server software: iis, apache, nginx, tomcat")
    ha.add_argument("--profile", default="generic", help="application type: api, wordpress, admin-panel (default: generic)")
    ha.add_argument("--notes", help="free-form host notes")
    ha.set_defaults(func=cmd_host_add)

    hl = host_sub.add_parser("list", help="list project hosts", epilog="example:\n  obliquity host list acme", formatter_class=formatter)
    hl.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hl.set_defaults(func=cmd_host_list)

    hu = host_sub.add_parser(
        "update", help="update host metadata", formatter_class=formatter,
        epilog='example:\n  obliquity host update acme https://app.acme.test --tech php --notes "Public app"',
    )
    hu.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hu.add_argument("url", help="current host URL")
    hu.add_argument("--url-new", help="new URL for this host")
    hu.add_argument("--profile")
    hu.add_argument("--server")
    hu.add_argument("--tech")
    hu.add_argument("--notes")
    hu.set_defaults(func=cmd_host_update)

    hr = host_sub.add_parser("remove", help="remove a host and its database records", formatter_class=formatter, epilog="example:\n  obliquity host remove acme https://app.acme.test")
    hr.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hr.add_argument("url", help="host URL")
    hr.add_argument("--yes", action="store_true", help="confirm removal without prompting")
    hr.set_defaults(func=cmd_host_remove)

    bust_scan_args = argparse.ArgumentParser(add_help=False)
    bust_scan_args.add_argument("--gameplan", default=None, help="built-in name or JSON path (default: recommended from the host's --tech/--server/--profile, else generic-quick)")
    bust_scan_args.add_argument("--dry-run", action="store_true", help="print commands without running the underlying tool")
    bust_scan_args.add_argument("--rate-limit", type=int, help="maximum requests per second")
    bust_scan_args.add_argument("--threads", type=int, help="feroxbuster worker thread count")
    bust_scan_args.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080")
    bust_scan_args.add_argument("--header", action="append", help="header passed to the underlying tool; repeatable")
    bust_recursion = bust_scan_args.add_mutually_exclusive_group()
    bust_recursion.add_argument("--depth", type=int, metavar="N", help="override recursion depth for every stage (enables feroxbuster recursion, --depth N)")
    bust_recursion.add_argument("--no-recurse", action="store_true", help="disable feroxbuster recursion for every stage, overriding the gameplan")
    bust_scan_args.add_argument("--filter-status", help="drop responses with these status codes (feroxbuster -C), e.g. 404,500")
    bust_scan_args.add_argument("--filter-size", help="drop responses of these byte sizes (feroxbuster -S), e.g. 0,1024")
    bust_scan_args.add_argument("--filter-words", help="drop responses with these word counts (feroxbuster -W)")
    bust_scan_args.add_argument("--filter-lines", help="drop responses with these line counts (feroxbuster -N)")
    bust_scan_args.add_argument("--filter-regex", help="drop responses whose body matches this regex (feroxbuster -X)")
    bust_scan_args.add_argument("--report", action="store_true", help="generate the HTML report after a successful run")
    bust_scan_args.add_argument("--open-report", action="store_true", help="generate and open the HTML report after a successful run")

    bust = sub.add_parser("bust", help="plan, run, or resume staged content discovery")
    bust.set_defaults(func=cmd_tool_gameplans, _tool="bust")
    bust_sub = bust.add_subparsers(dest="bust_cmd", required=False)

    bp = bust_sub.add_parser(
        "plan", help="preview stages without creating runs", formatter_class=formatter,
        parents=[project_host_args],
        epilog="example:\n  obliquity bust plan acme https://app.acme.test --gameplan generic-quick",
    )
    bp.add_argument("--gameplan", default=None, help="built-in name or JSON path (default: recommended from the host's --tech/--server/--profile, else generic-quick)")
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
    crack_target_args.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    crack_target_args.add_argument(
        "job", nargs="?",
        help="crack job name or hash file already added to the project (optional if the project has exactly one job)",
    )

    crack_scan_args = argparse.ArgumentParser(add_help=False)
    crack_scan_args.add_argument("--gameplan", default=None, help="built-in name or JSON path (default: the project default, else quick-dictionary)")
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
    crack.set_defaults(func=cmd_tool_gameplans, _tool="crack")
    crack_sub = crack.add_subparsers(dest="crack_cmd", required=False)

    crack_job = crack_sub.add_parser("job", help="add, list, or remove crack targets (hash files)")
    crack_job_sub = crack_job.add_subparsers(dest="crack_job_cmd", required=True)

    cja = crack_job_sub.add_parser(
        "add", help="add a hash file as a crack job", formatter_class=formatter,
        epilog="example:\n  obliquity crack job add acme ./hashes.txt --hash-type 1000 --name ntlm-dump",
    )
    cja.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    cja.add_argument("hashfile", help="path to a hashcat-compatible hash file")
    cja.add_argument("--hash-type", type=int, required=True, help="hashcat -m mode number, e.g. 0=MD5, 1000=NTLM")
    cja.add_argument("--name", help="friendly name to refer to this job later")
    cja.add_argument("--notes", help="free-form job notes")
    cja.set_defaults(func=cmd_crack_job_add)

    cjl = crack_job_sub.add_parser("list", help="list project crack jobs", epilog="example:\n  obliquity crack job list acme", formatter_class=formatter)
    cjl.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    cjl.set_defaults(func=cmd_crack_job_list)

    cjr = crack_job_sub.add_parser("remove", help="remove a crack job and its records", formatter_class=formatter, epilog="example:\n  obliquity crack job remove acme ntlm-dump")
    cjr.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    cjr.add_argument("target", help="job name or hash file path")
    cjr.add_argument("--yes", action="store_true", help="confirm removal without prompting")
    cjr.set_defaults(func=cmd_crack_job_remove)

    cp = crack_sub.add_parser(
        "plan", help="preview stages without creating runs", formatter_class=formatter,
        parents=[crack_target_args],
        epilog="example:\n  obliquity crack plan acme --gameplan quick-dictionary",
    )
    cp.add_argument("--gameplan", default=None, help="built-in name or JSON path (default: the project default, else quick-dictionary)")
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

    # --- brute (online login attacks; backend: thc-hydra) ---
    login_target_args = argparse.ArgumentParser(add_help=False)
    login_target_args.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    login_target_args.add_argument(
        "job", nargs="?",
        help="login job name or target already added to the project (optional if the project has exactly one job)",
    )

    login_scan_args = argparse.ArgumentParser(add_help=False)
    login_scan_args.add_argument("--gameplan", default=None, help="built-in loginplan name or JSON path (default: quick)")
    login_scan_args.add_argument("--dry-run", action="store_true", help="print the hydra command without running it")

    brute = sub.add_parser(
        "brute", help="plan, run, or resume online login/credential attacks (backend: thc-hydra)", formatter_class=formatter,
        epilog="""examples:
  obliquity brute job add acme 10.0.0.5 --service ssh --name ssh-box
  obliquity brute job add acme app.acme.test --service http-post-form --form-spec "/login:user=^USER^&pass=^PASS^:F=invalid"
  obliquity brute plan acme --gameplan quick
  obliquity brute run acme ssh-box --gameplan common-creds
  obliquity brute creds acme""",
    )
    brute.set_defaults(func=cmd_tool_gameplans, _tool="brute")
    brute_sub = brute.add_subparsers(dest="brute_cmd", required=False)

    brute_job = brute_sub.add_parser("job", help="add, list, or remove login targets (service + host)")
    brute_job_sub = brute_job.add_subparsers(dest="brute_job_cmd", required=True)

    hja = brute_job_sub.add_parser(
        "add", help="add a login target as a job", formatter_class=formatter,
        epilog="examples:\n"
        "  obliquity brute job add acme 10.0.0.5 --service ssh\n"
        "  obliquity brute job add acme app.acme.test --service http-post-form --form-spec \"/login:user=^USER^&pass=^PASS^:F=invalid\"",
    )
    hja.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hja.add_argument("target", nargs="?", help="hostname or IP to attack (optional if --host is given)")
    hja.add_argument("--service", required=True, help=f"service to attack; one of: {', '.join(sorted(KNOWN_SERVICES))}")
    hja.add_argument("--host", help="link to an existing project host URL (seeds the target if omitted)")
    hja.add_argument("--port", type=int, help="custom port (hydra -s)")
    hja.add_argument("--form-spec", dest="form_spec", help="http-*-form module string: \"path:body-with-^USER^-^PASS^:F=failure-text\"")
    hja.add_argument("--module-args", dest="module_args", help="extra hydra module argument for non-form services")
    hja.add_argument("--name", help="friendly name to refer to this job later")
    hja.add_argument("--notes", help="free-form job notes")
    hja.set_defaults(func=cmd_brute_job_add)

    hjl = brute_job_sub.add_parser("list", help="list project login jobs", epilog="example:\n  obliquity brute job list acme", formatter_class=formatter)
    hjl.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hjl.set_defaults(func=cmd_brute_job_list)

    hjr = brute_job_sub.add_parser("remove", help="remove a login job and its records", formatter_class=formatter, epilog="example:\n  obliquity brute job remove acme ssh-box")
    hjr.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hjr.add_argument("target", help="job name or target")
    hjr.add_argument("--yes", action="store_true", help="confirm removal without prompting")
    hjr.set_defaults(func=cmd_brute_job_remove)

    hp = brute_sub.add_parser(
        "plan", help="preview stages without creating runs", formatter_class=formatter,
        parents=[login_target_args],
        epilog="example:\n  obliquity brute plan acme --gameplan quick",
    )
    hp.add_argument("--gameplan", default=None, help="built-in loginplan name or JSON path (default: quick)")
    hp.set_defaults(func=cmd_brute_plan)

    hr = brute_sub.add_parser(
        "run", help="execute a staged hydra login attack", formatter_class=formatter,
        parents=[login_target_args, login_scan_args],
        epilog="""examples:
  obliquity brute run acme --gameplan quick
  obliquity brute run acme ssh-box --gameplan common-creds
  obliquity brute run acme --dry-run""",
    )
    hr.add_argument("--force", action="store_true", help="rerun completed stages")
    hr.set_defaults(func=cmd_brute_run)

    hres = brute_sub.add_parser(
        "resume", help="skip completed stages and retry interrupted or failed work",
        description="Resume a loginplan using stored stage fingerprints. Completed stages are skipped. "
        "Note: this is stage-level resume, not mid-attack resume within a single hydra pass.",
        formatter_class=formatter,
        parents=[login_target_args, login_scan_args],
        epilog="example:\n  obliquity brute resume acme --gameplan common-creds",
    )
    hres.set_defaults(force=False)
    hres.set_defaults(func=cmd_brute_resume)

    hcreds = brute_sub.add_parser("creds", help="list credentials found for a project", formatter_class=formatter, epilog="example:\n  obliquity brute creds acme")
    hcreds.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    hcreds.set_defaults(func=cmd_brute_creds)

    runs = sub.add_parser(
        "runs", help="show stored stage runs", formatter_class=formatter,
        epilog="examples:\n  obliquity runs acme\n  obliquity runs acme --status interrupted",
    )
    runs.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    runs.add_argument("--status", help="filter by pending, running, completed, failed, or interrupted")
    runs.set_defaults(func=cmd_runs)

    history = sub.add_parser(
        "history", help="show a unified, readable log of bust/fuzz/crack scans", formatter_class=formatter,
        epilog="""examples:
  obliquity history acme
  obliquity history acme --tool hashcat
  obliquity history acme --status failed --limit 20""",
    )
    history.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    history.add_argument("--tool", choices=["feroxbuster", "ffuf", "hashcat", "hydra"], help="filter by underlying tool")
    history.add_argument("--status", help="filter by pending, running, completed, failed, or interrupted")
    history.add_argument("--limit", type=int, help="show only the N most recent entries")
    history.set_defaults(func=cmd_history)

    report = sub.add_parser("report", help="generate project reports")
    report_sub = report.add_subparsers(dest="report_cmd", required=True)
    rh = report_sub.add_parser(
        "html", help="generate an HTML report", formatter_class=formatter,
        epilog="examples:\n  obliquity report html acme\n  obliquity report html acme --output ./acme-report.html",
    )
    rh.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    rh.add_argument("--output", help="custom report path")
    rh.add_argument("--open", action="store_true", help="open the report in the default browser")
    rh.set_defaults(func=cmd_report_html)

    rj = report_sub.add_parser(
        "json", help="generate a JSON report (runs, findings, crack runs, cracked hashes)", formatter_class=formatter,
        epilog="examples:\n  obliquity report json acme\n  obliquity report json acme --output ./acme-report.json",
    )
    rj.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    rj.add_argument("--output", help="custom report path")
    rj.set_defaults(func=cmd_report_json)

    rc = report_sub.add_parser(
        "csv", help="generate a CSV report for one dataset", formatter_class=formatter,
        epilog="examples:\n  obliquity report csv acme\n  obliquity report csv acme --kind cracked-hashes",
    )
    rc.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    rc.add_argument("--kind", choices=sorted(CSV_DATASETS), default="findings", help="which dataset to export (default: findings)")
    rc.add_argument("--output", help="custom report path")
    rc.set_defaults(func=cmd_report_csv)

    rm = report_sub.add_parser(
        "markdown", help="generate a Markdown report", formatter_class=formatter,
        epilog="examples:\n  obliquity report markdown acme\n  obliquity report markdown acme --output ./acme-report.md",
    )
    rm.add_argument("project", nargs="?", help="project name (optional if an active project is set via 'project use')")
    rm.add_argument("--output", help="custom report path")
    rm.set_defaults(func=cmd_report_markdown)

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
