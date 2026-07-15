from __future__ import annotations

import shlex
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
            }
        )
    return rows


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
) -> list[dict]:
    if not dry_run:
        require_feroxbuster()
    results: list[dict] = []
    url = host["url"]

    for stage in gameplan.stages:
        fingerprint = fingerprint_stage(url, gameplan, stage)
        existing = get_run_by_fingerprint(conn, fingerprint)
        if existing and existing["status"] == "completed" and not force:
            results.append({"stage": stage.name, "action": "skipped", "reason": "already completed"})
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
        run = create_or_update_run(
            conn,
            project["id"],
            host["id"],
            gameplan.name,
            stage.name,
            fingerprint,
            " ".join(shlex.quote(part) for part in cmd),
            str(raw_output),
            str(json_output),
        )

        if dry_run:
            results.append({"stage": stage.name, "action": "planned", "command": run["command"]})
            continue

        mark_run_started(conn, run["id"])
        exit_code, error = run_command(cmd, raw_output)
        status = "completed" if exit_code == 0 else "failed"
        mark_run_finished(conn, run["id"], exit_code, status, error)

        findings = parse_json_output(
            json_output,
            run_id=run["id"],
            project_id=project["id"],
            host_id=host["id"],
            source=stage.name,
        )
        inserted = insert_findings(conn, findings)
        results.append(
            {
                "stage": stage.name,
                "action": "ran",
                "status": status,
                "exit_code": exit_code,
                "new_findings": inserted,
                "json_output": str(json_output),
                "raw_output": str(raw_output),
                "error": error,
            }
        )
        if exit_code != 0:
            break

    return results
