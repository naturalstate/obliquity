from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from sqlite3 import Connection, Row

from obliquity.adapters import hashcat
from obliquity.adapters.feroxbuster import run_command
from obliquity.core.crackplan import CrackPlan, fingerprint_crack_stage
from obliquity.core.database import (
    create_or_update_crack_run,
    get_crack_run_by_fingerprint,
    insert_cracked_hashes,
    mark_crack_run_finished,
    mark_crack_run_started,
)
from obliquity.core.runner import EventCallback, quoted_command, safe_name

# hashcat exit codes: 0 = all hashes cracked, 1 = exhausted the candidate
# space without cracking everything (a normal outcome, not a failure),
# 2 = aborted (checkpoint/user), anything else = a real error.
EXHAUSTED_EXIT_CODE = 1
ABORTED_EXIT_CODE = 2


def live_crack_counter(output: Path) -> Callable[[], int]:
    position = 0
    count = 0

    def update() -> int:
        nonlocal position, count
        if not output.exists():
            return count
        with output.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(position)
            for line in handle:
                if line.strip():
                    count += 1
            position = handle.tell()
        return count

    return update


def stage_paths(project: Row, job: Row, plan: CrackPlan, stage_name: str) -> tuple[Path, Path]:
    base = Path(project["root_dir"]) / "runs" / "crack" / safe_name(job["hash_file"]) / safe_name(plan.name)
    base.mkdir(parents=True, exist_ok=True)
    raw = base / f"{safe_name(stage_name)}.raw.txt"
    result = base / f"{safe_name(stage_name)}.cracked.txt"
    return raw, result


def preview_plan(plan: CrackPlan) -> list[dict]:
    rows: list[dict] = []
    for idx, stage in enumerate(plan.stages, start=1):
        rows.append(
            {
                "number": idx,
                "name": stage.name,
                "attack_mode": stage.attack_mode,
                "wordlist": stage.wordlist,
                "wordlist2": stage.wordlist2,
                "rules": stage.rules,
                "mask": stage.mask,
                "estimated_minutes": stage.estimated_minutes,
            }
        )
    return rows


def run_crackplan(
    conn: Connection,
    project: Row,
    job: Row,
    plan: CrackPlan,
    *,
    force: bool = False,
    dry_run: bool = False,
    extra_args: list[str] | None = None,
    event_callback: EventCallback | None = None,
) -> list[dict]:
    if not dry_run:
        hashcat.require_hashcat()
    results: list[dict] = []
    hash_file = job["hash_file"]
    hash_type = job["hash_type"]
    total_stages = len(plan.stages)

    for idx, stage in enumerate(plan.stages, start=1):
        fingerprint = fingerprint_crack_stage(hash_file, hash_type, plan, stage, project_id=project["id"])
        existing = get_crack_run_by_fingerprint(conn, fingerprint)
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
        session = safe_name(f"{project['name']}-{job['id']}-{plan.name}-{stage.name}")
        restore_file = raw_output.parent / f"{safe_name(stage.name)}.restore"

        # hashcat leaves a .restore checkpoint behind only when a run was
        # interrupted (it deletes it on clean completion). If one exists and
        # we're not force-rerunning, resume from it instead of starting over.
        # With --force, wipe any stale checkpoint so the rerun really is fresh
        # (but never on a dry-run -- previewing shouldn't delete anything).
        if force and restore_file.exists() and not dry_run:
            restore_file.unlink()
        resuming = restore_file.exists() and not force

        cmd = hashcat.build_command(
            hash_file,
            hash_type,
            stage,
            result_output,
            session=session,
            restore_file=restore_file,
            restore=resuming,
            extra_args=extra_args,
        )
        command = quoted_command(cmd)
        run = create_or_update_crack_run(
            conn,
            project["id"],
            job["id"],
            plan.name,
            stage.name,
            fingerprint,
            command,
            str(raw_output),
            str(result_output),
        )

        common = {
            "stage": stage.name,
            "stage_number": idx,
            "total_stages": total_stages,
            "attack_mode": stage.attack_mode,
            "wordlist": stage.wordlist,
            "wordlist2": stage.wordlist2,
            "rules": stage.rules,
            "mask": stage.mask,
            "estimated_minutes": stage.estimated_minutes,
            "resuming": resuming,
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

        mark_crack_run_started(conn, run["id"])
        count_cracked = live_crack_counter(result_output)

        def report_progress(elapsed: float) -> None:
            if event_callback:
                event_callback(
                    {
                        **common,
                        "action": "progress",
                        "elapsed": elapsed,
                        "findings": count_cracked(),
                    }
                )

        exit_code, error = run_command(cmd, raw_output, report_progress)
        if exit_code in (0, EXHAUSTED_EXIT_CODE):
            status = "completed"
            error = None
        elif exit_code in (130, ABORTED_EXIT_CODE):
            status = "interrupted"
        else:
            status = "failed"
        mark_crack_run_finished(conn, run["id"], exit_code, status, error)

        cracked = hashcat.parse_output(
            result_output,
            run_id=run["id"],
            project_id=project["id"],
            job_id=job["id"],
            source=stage.name,
        )
        inserted = insert_cracked_hashes(conn, cracked)
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
        # Stop the plan on a real problem, or once hashcat reports every hash
        # in the file is cracked (exit 0) -- nothing left for later stages to
        # find. Exit 1 ("exhausted this wordlist/mask, hashes remain") is the
        # normal signal to fall through to the next stage.
        if status != "completed" or exit_code == 0:
            break

    return results
