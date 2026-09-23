from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from sqlite3 import Connection, Row

from obliquity.adapters.feroxbuster import build_command, parse_json_output, require_feroxbuster, run_command
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

        raw_output, json_output = stage_paths(project, host, gameplan, stage.name)
        cmd = build_command(
            url,
            stage,
            json_output,
            rate_limit=rate_limit,
            threads=threads,
            proxy=proxy,
            headers=headers,
        )
        command = quoted_command(cmd)
        run = create_or_update_run(
            conn,
            project["id"],
            host["id"],
            gameplan.name,
            stage.name,
            fingerprint,
            command,
            str(raw_output),
            str(json_output),
        )

        common = {
            "stage": stage.name,
            "stage_number": idx,
            "total_stages": total_stages,
            "wordlist": stage.wordlist,
            "extensions": stage.extensions,
            "recursion": stage.recursion,
            "depth": stage.depth,
            "status_codes": stage.status_codes,
            "command": command,
            "json_output": str(json_output),
            "raw_output": str(raw_output),
        }

        if dry_run:
            item = {**common, "action": "planned"}
            if event_callback:
                event_callback(item)
            results.append(item)
            continue

        if event_callback:
            event_callback({**common, "action": "starting"})

        mark_run_started(conn, run["id"])
        count_findings = live_finding_counter(json_output)

        def report_progress(elapsed: float) -> None:
            if event_callback:
                event_callback(
                    {
                        **common,
                        "action": "progress",
                        "elapsed": elapsed,
                        "findings": count_findings(),
                    }
                )

        exit_code, error = run_command(cmd, raw_output, report_progress)
        status = "completed" if exit_code == 0 else "interrupted" if exit_code == 130 else "failed"
        mark_run_finished(conn, run["id"], exit_code, status, error)

        findings = parse_json_output(
            json_output,
            run_id=run["id"],
            project_id=project["id"],
            host_id=host["id"],
            source=stage.name,
        )
        inserted = insert_findings(conn, findings)
        item = {
            **common,
            "action": "ran",
            "status": status,
            "exit_code": exit_code,
            "new_findings": inserted,
            "error": error,
        }
        if event_callback:
            event_callback(item)
        results.append(item)
        if exit_code != 0:
            break

    return results
