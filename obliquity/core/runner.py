from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from sqlite3 import Connection, Row

from obliquity.adapters.feroxbuster import (
    FLOOD_ABORT_EXIT,
    build_command,
    parse_json_output,
    require_feroxbuster,
    run_command,
)
from obliquity.core.database import (
    create_or_update_run,
    get_run_by_fingerprint,
    insert_findings,
    mark_run_finished,
    mark_run_started,
)
from obliquity.core.gameplan import Gameplan, fingerprint_stage

EventCallback = Callable[[dict], None]


def live_finding_counter(json_output: Path) -> Callable[[], int]:
    position = 0
    count = 0

    def update() -> int:
        nonlocal position, count
        if not json_output.exists():
            return count
        with json_output.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(position)
            while line := handle.readline():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (item.get("url") or item.get("target")) and (
                    item.get("status") is not None or item.get("status_code") is not None
                ):
                    count += 1
            position = handle.tell()
        return count

    return update


def live_status_tally(json_output: Path) -> Callable[[], dict[int, int]]:
    """Incremental {status_code: count} over feroxbuster's JSONL output."""
    position = 0
    counts: dict[int, int] = {}

    def update() -> dict[int, int]:
        nonlocal position
        if not json_output.exists():
            return counts
        with json_output.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(position)
            while line := handle.readline():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                url = item.get("url") or item.get("target")
                status = item.get("status")
                if status is None:
                    status = item.get("status_code")
                if url and status is not None:
                    try:
                        code = int(status)
                    except (TypeError, ValueError):
                        continue
                    counts[code] = counts.get(code, 0) + 1
            position = handle.tell()
        return counts

    return update


def make_flood_detector(
    tally: Callable[[], dict[int, int]],
    threshold: int,
    *,
    min_total: int = 40,
    ratio: float = 0.85,
) -> Callable[[float], str | None]:
    """Return an abort_check that fires when one status code dominates the
    results (>= `threshold` hits and >= `ratio` of everything seen so far) --
    the signature of a wildcard / soft-404 host answering everything alike."""
    def check(_elapsed: float) -> str | None:
        counts = tally()
        total = sum(counts.values())
        if total < max(min_total, 1) or not counts:
            return None
        code, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= threshold and (n / total) >= ratio:
            return f"status {code} flood: {n}/{total} matches ({n / total:.0%}) -- likely a wildcard/soft-404"
        return None

    return check


def safe_name(value: str) -> str:
    keep = []
    for ch in value:
        keep.append(ch if ch.isalnum() or ch in "._-" else "_")
    return "".join(keep).strip("_") or "item"


def stage_paths(project: Row, host: Row, gameplan: Gameplan, stage_name: str) -> tuple[Path, Path]:
    base = Path(project["root_dir"]) / "runs" / safe_name(host["url"]) / safe_name(gameplan.name)
    base.mkdir(parents=True, exist_ok=True)
    raw = base / f"{safe_name(stage_name)}.raw.txt"
    js = base / f"{safe_name(stage_name)}.jsonl"
    return raw, js


def preview_plan(url: str, gameplan: Gameplan) -> list[dict]:
    rows: list[dict] = []
    for idx, stage in enumerate(gameplan.stages, start=1):
        rows.append(
            {
                "number": idx,
                "name": stage.name,
                "wordlist": stage.wordlist,
                "extensions": stage.extensions,
                "recursion": stage.recursion,
                "depth": stage.depth,
                "status_codes": stage.status_codes,
                "filter_status": stage.filter_status,
                "filter_size": stage.filter_size,
                "filter_words": stage.filter_words,
                "filter_lines": stage.filter_lines,
                "filter_regex": stage.filter_regex,
                "extra_args": stage.extra_args,
            }
        )
    return rows


def quoted_command(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_gameplan(
    conn: Connection,
    project: Row,
    host: Row,
    gameplan: Gameplan,
    *,
    force: bool = False,
    dry_run: bool = False,
    rate_limit: int | None = None,
    threads: int | None = None,
    proxy: str | None = None,
    headers: list[str] | None = None,
    event_callback: EventCallback | None = None,
    flood_threshold: int = 0,
    flood_prompt: Callable[[dict], bool] | None = None,
) -> list[dict]:
    if not dry_run:
        require_feroxbuster()
    results: list[dict] = []
    url = host["url"]
    total_stages = len(gameplan.stages)

    for idx, stage in enumerate(gameplan.stages, start=1):
        fingerprint = fingerprint_stage(url, gameplan, stage, project_id=project["id"])
        existing = get_run_by_fingerprint(conn, fingerprint)
        if existing and existing["status"] == "completed" and not force:
            item = {
                "stage": stage.name,
                "stage_number": idx,
                "total_stages": total_stages,
                "action": "skipped",
                "reason": "already completed",
            }
            if event_callback:
                event_callback(item)
            results.append(item)
            continue

        # Dry-run: preview the command once, without executing.
        if dry_run:
            raw_output, json_output = stage_paths(project, host, gameplan, stage.name)
            cmd = build_command(url, stage, json_output, rate_limit=rate_limit, threads=threads, proxy=proxy, headers=headers)
            item = {
                "stage": stage.name, "stage_number": idx, "total_stages": total_stages,
                "wordlist": stage.wordlist, "extensions": stage.extensions,
                "recursion": stage.recursion, "depth": stage.depth,
                "status_codes": stage.status_codes, "filter_status": stage.filter_status,
                "command": quoted_command(cmd), "action": "planned",
            }
            if event_callback:
                event_callback(item)
            results.append(item)
            continue

        # Execute, with optional mid-run flood detection. On a detected flood we
        # can re-run the stage once with the offending status code filtered out
        # (which changes the fingerprint, so it's tracked as its own run).
        item = None
        for attempt in range(1, 3):  # original + at most one filtered re-run
            fingerprint = fingerprint_stage(url, gameplan, stage, project_id=project["id"])
            raw_output, json_output = stage_paths(project, host, gameplan, stage.name)
            cmd = build_command(url, stage, json_output, rate_limit=rate_limit, threads=threads, proxy=proxy, headers=headers)
            command = quoted_command(cmd)
            run = create_or_update_run(
                conn, project["id"], host["id"], gameplan.name, stage.name,
                fingerprint, command, str(raw_output), str(json_output),
            )
            common = {
                "stage": stage.name, "stage_number": idx, "total_stages": total_stages,
                "wordlist": stage.wordlist, "extensions": stage.extensions,
                "recursion": stage.recursion, "depth": stage.depth,
                "status_codes": stage.status_codes, "filter_status": stage.filter_status,
                "command": command, "json_output": str(json_output), "raw_output": str(raw_output),
                "retry": attempt > 1,
            }
            if event_callback:
                event_callback({**common, "action": "starting"})
            mark_run_started(conn, run["id"])
            count_findings = live_finding_counter(json_output)
            tally = live_status_tally(json_output)

            def report_progress(elapsed: float, _common=common, _count=count_findings) -> None:
                if event_callback:
                    event_callback({**_common, "action": "progress", "elapsed": elapsed, "findings": _count()})

            # Only guard on the first attempt (a filtered re-run shouldn't flood again).
            abort_check = None
            if flood_threshold and attempt == 1:
                abort_check = make_flood_detector(tally, flood_threshold)

            exit_code, error = run_command(cmd, raw_output, report_progress, abort_check=abort_check)

            if exit_code == FLOOD_ABORT_EXIT:
                counts = tally()
                total = sum(counts.values())
                code = max(counts, key=counts.get) if counts else None
                mark_run_finished(conn, run["id"], exit_code, "interrupted", error)
                # partial findings so far are still recorded
                insert_findings(conn, parse_json_output(json_output, run_id=run["id"], project_id=project["id"], host_id=host["id"], source=stage.name))
                proceed = True
                if flood_prompt is not None:
                    proceed = flood_prompt({"stage": stage.name, "status": code, "count": counts.get(code, 0), "total": total, "reason": error})
                if proceed and code is not None and code not in stage.filter_status:
                    stage.filter_status = sorted(set(stage.filter_status) | {code})
                    if event_callback:
                        event_callback({**common, "action": "reflood", "status": code, "count": counts.get(code, 0), "total": total})
                    continue  # re-run with the flood status filtered out
                item = {**common, "action": "ran", "status": "interrupted", "exit_code": exit_code,
                        "new_findings": 0, "error": error or "aborted: response flood"}
                break

            status = "completed" if exit_code == 0 else "interrupted" if exit_code == 130 else "failed"
            mark_run_finished(conn, run["id"], exit_code, status, error)
            inserted = insert_findings(conn, parse_json_output(
                json_output, run_id=run["id"], project_id=project["id"], host_id=host["id"], source=stage.name))
            item = {**common, "action": "ran", "status": status, "exit_code": exit_code,
                    "new_findings": inserted, "error": error}
            break

        if event_callback:
            event_callback(item)
        results.append(item)
        if item.get("status") != "completed":
            break

    return results
