from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection, Row

from obliquity.adapters import hydra
from obliquity.adapters.feroxbuster import run_command
from obliquity.core.database import (
    create_or_update_login_run,
    get_login_run_by_fingerprint,
    insert_found_credentials,
    mark_login_run_finished,
    mark_login_run_started,
)
from obliquity.core.loginplan import LoginPlan, fingerprint_login_stage
from obliquity.core.runner import EventCallback, quoted_command, safe_name


def _job_key(job: Row) -> str:
    return job["name"] or f"{job['target']}:{job['service']}"


def stage_paths(project: Row, job: Row, plan: LoginPlan, stage_name: str) -> tuple[Path, Path]:
    base = Path(project["root_dir"]) / "runs" / "hydra" / safe_name(_job_key(job)) / safe_name(plan.name)
    base.mkdir(parents=True, exist_ok=True)
    raw = base / f"{safe_name(stage_name)}.raw.txt"
    result = base / f"{safe_name(stage_name)}.creds.json"
    return raw, result


def preview_plan(plan: LoginPlan) -> list[dict]:
    rows: list[dict] = []
    for idx, stage in enumerate(plan.stages, start=1):
        rows.append({
            "number": idx,
            "name": stage.name,
            "username": stage.username,
            "userlist": stage.userlist,
            "password": stage.password,
            "passlist": stage.passlist,
            "tasks": stage.tasks,
            "stop_on_first_valid": stage.stop_on_first_valid,
        })
    return rows


def run_loginplan(
    conn: Connection,
    project: Row,
    job: Row,
    plan: LoginPlan,
    *,
    force: bool = False,
    dry_run: bool = False,
    extra_args: list[str] | None = None,
    event_callback: EventCallback | None = None,
) -> list[dict]:
    if not dry_run:
        hydra.require_hydra()
    results: list[dict] = []
    total_stages = len(plan.stages)
    job_key = _job_key(job)

    for idx, stage in enumerate(plan.stages, start=1):
        fingerprint = fingerprint_login_stage(job_key, job["service"], plan, stage, project_id=project["id"])
        existing = get_login_run_by_fingerprint(conn, fingerprint)
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

        raw_output, result_output = stage_paths(project, job, plan, stage.name)
        # hydra appends to -o; start each attempt from a clean result file so a
        # rerun's parsed credentials reflect only this run.
        if result_output.exists() and not dry_run:
            result_output.unlink()

        cmd = hydra.build_command(dict(job), stage, result_output, extra_args=extra_args)
        command = quoted_command(cmd)
        run = create_or_update_login_run(
            conn, project["id"], job["id"], plan.name, stage.name, fingerprint,
            command, str(raw_output), str(result_output),
        )

        common = {
            "stage": stage.name,
            "stage_number": idx,
            "total_stages": total_stages,
            "username": stage.username,
            "userlist": stage.userlist,
            "password": stage.password,
            "passlist": stage.passlist,
            "command": command,
            "result_output": str(result_output),
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
        mark_login_run_started(conn, run["id"])

        def report_progress(elapsed: float) -> None:
            if event_callback:
                event_callback({**common, "action": "progress", "elapsed": elapsed})

        exit_code, error = run_command(cmd, raw_output, report_progress)
        # hydra returns 0 on a normal finish (found or not); 130 = interrupted.
        if exit_code == 0:
            status = "completed"
            error = None
        elif exit_code == 130:
            status = "interrupted"
        else:
            status = "failed"
        mark_login_run_finished(conn, run["id"], exit_code, status, error)

        found = hydra.parse_output(
            result_output,
            run_id=run["id"],
            project_id=project["id"],
            job_id=job["id"],
            service=job["service"],
            target=job["target"],
            source=stage.name,
        )
        inserted = insert_found_credentials(conn, found)
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
        # Stop on a real problem, or once we've recovered valid credentials --
        # later escalation stages exist only for the not-yet-cracked case.
        if status != "completed" or inserted > 0:
            break

    return results
