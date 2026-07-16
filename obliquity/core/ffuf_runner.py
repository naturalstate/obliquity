from __future__ import annotations

import hashlib
import json
from pathlib import Path
from sqlite3 import Connection, Row

from obliquity.adapters import ffuf
from obliquity.core.database import (
    create_or_update_run,
    get_run_by_fingerprint,
    insert_findings,
    mark_run_finished,
    mark_run_started,
)
from obliquity.core.fuzzplan import FuzzPlan
from obliquity.core.runner import EventCallback, live_finding_counter, quoted_command, safe_name


def operation_fingerprint(project_id: int, host_id: int, plan: FuzzPlan, scope: str, options: dict) -> str:
    wordlist = Path(options["wordlist"])
    wordlist_hash = hashlib.sha256(wordlist.read_bytes()).hexdigest()
    payload = {
        "project_id": project_id,
        "host_id": host_id,
        "category": plan.operation_category,
        "scope": scope,
        "wordlist_hash": wordlist_hash,
        "method": options.get("method"),
        "data": options.get("data"),
        "headers": sorted(options.get("headers") or []),
        "mode": options.get("mode"),
        "match_codes": options.get("match_codes"),
        "filter_codes": options.get("filter_codes"),
        "filter_size": options.get("filter_size"),
        "autocalibrate": options.get("autocalibrate"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def output_path(project: Row, host: Row, plan: FuzzPlan) -> Path:
    base = Path(project["root_dir"]) / "runs" / safe_name(host["url"]) / "ffuf" / safe_name(plan.name)
    base.mkdir(parents=True, exist_ok=True)
    return base / "results.jsonl"


def run_fuzz_plan(
    conn: Connection,
    project: Row,
    host: Row,
    plan: FuzzPlan,
    *,
    url_template: str | None,
    request_file: str | None,
    wordlist: str | None = None,
    request_proto: str = "https",
    method: str | None = None,
    data: str | None = None,
    headers: list[str] | None = None,
    proxy: str | None = None,
    rate: int | None = None,
    threads: int | None = None,
    match_codes: str | None = None,
    filter_codes: str | None = None,
    filter_size: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    event_callback: EventCallback | None = None,
) -> list[dict]:
    if not dry_run:
        ffuf.require_ffuf()
    selected_wordlist = str(Path(wordlist or plan.wordlist).expanduser().resolve())
    scope = url_template or f"request:{Path(request_file or '').resolve()}"
    options = {
        "wordlist": selected_wordlist,
        "method": method,
        "data": data,
        "headers": headers or [],
        "mode": plan.mode,
        "match_codes": match_codes,
        "filter_codes": filter_codes,
        "filter_size": filter_size,
        "autocalibrate": plan.autocalibrate,
    }
    fingerprint = operation_fingerprint(project["id"], host["id"], plan, scope, options)
    existing = get_run_by_fingerprint(conn, fingerprint)
    if existing and existing["status"] == "completed" and not force:
        item = {
            "stage": plan.name,
            "stage_number": 1,
            "total_stages": 1,
            "action": "skipped",
            "reason": f"equivalent {plan.operation_category} coverage already completed with {existing['tool']}",
        }
        if event_callback:
            event_callback(item)
        return [item]

    output = output_path(project, host, plan)
    command_parts = ffuf.build_command(
        wordlist=selected_wordlist,
        url_template=url_template,
        request_file=request_file,
        request_proto=request_proto,
        mode=plan.mode,
        autocalibrate=plan.autocalibrate,
        method=method,
        data=data,
        headers=headers,
        proxy=proxy,
        rate=rate,
        threads=threads,
        match_codes=match_codes,
        filter_codes=filter_codes,
        filter_size=filter_size,
    )
    command = quoted_command(command_parts)
    run = create_or_update_run(
        conn,
        project["id"],
        host["id"],
        plan.name,
        plan.name,
        fingerprint,
        command,
        str(output),
        str(output),
        tool="ffuf",
        operation_category=plan.operation_category,
        operation_scope=scope,
    )
    common = {
        "stage": plan.name,
        "stage_number": 1,
        "total_stages": 1,
        "wordlist": selected_wordlist,
        "extensions": [],
        "recursion": False,
        "depth": None,
        "command": command,
        "json_output": str(output),
        "raw_output": str(output),
        "operation_category": plan.operation_category,
        "scope": scope,
    }
    if dry_run:
        item = {**common, "action": "planned"}
        if event_callback:
            event_callback(item)
        return [item]

    if event_callback:
        event_callback({**common, "action": "starting"})
    mark_run_started(conn, run["id"])
    count_findings = live_finding_counter(output)

    def report_progress(elapsed: float) -> None:
        if event_callback:
            event_callback({**common, "action": "progress", "elapsed": elapsed, "findings": count_findings()})

    exit_code, error = ffuf.run_command(command_parts, output, report_progress)
    status = "completed" if exit_code == 0 else "interrupted" if exit_code == 130 else "failed"
    mark_run_finished(conn, run["id"], exit_code, status, error)
    findings = ffuf.parse_json_output(
        output, run_id=run["id"], project_id=project["id"], host_id=host["id"], source=plan.name
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
    return [item]
