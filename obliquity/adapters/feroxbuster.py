from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from obliquity.core.gameplan import Stage


class FeroxbusterMissing(RuntimeError):
    pass


def require_feroxbuster() -> None:
    if shutil.which("feroxbuster") is None:
        raise FeroxbusterMissing(
            "feroxbuster was not found in PATH. Install feroxbuster first, then rerun Obliquity."
        )


def build_command(
    url: str,
    stage: Stage,
    json_output: Path,
    rate_limit: int | None = None,
    threads: int | None = None,
    proxy: str | None = None,
    headers: list[str] | None = None,
) -> list[str]:
    cmd = [
        "feroxbuster",
        "--url", url,
        "--wordlist", stage.wordlist,
        "--json",
        "--output", str(json_output),
        "--silent",
        "--no-state",
    ]

    if stage.extensions:
        cmd += ["--extensions", ",".join(stage.extensions)]

    # Extension Intelligence: let feroxbuster discover extensions from responses
    # and fold them into the scan (its -E flag). Previously this Stage field was
    # defined but never emitted.
    if stage.collect_extensions:
        cmd += ["--collect-extensions"]

    if stage.recursion:
        if stage.depth is not None:
            cmd += ["--depth", str(stage.depth)]
    else:
        cmd += ["--no-recursion"]

    if stage.status_codes:
        cmd += ["--status-codes", ",".join(str(x) for x in stage.status_codes)]

    if rate_limit:
        cmd += ["--rate-limit", str(rate_limit)]

    if threads:
        cmd += ["--threads", str(threads)]

    if proxy:
        cmd += ["--proxy", proxy]

    for header in headers or []:
        cmd += ["--headers", header]

    cmd += stage.extra_args
    return cmd


ProgressCallback = Callable[[float], None]


def terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_command(
    cmd: list[str],
    raw_output: Path,
    progress_callback: ProgressCallback | None = None,
) -> tuple[int, str | None]:
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    with raw_output.open("w", encoding="utf-8", errors="replace") as handle:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT, text=True)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if progress_callback:
                    progress_callback(time.monotonic() - started)
                time.sleep(0.1)
        except KeyboardInterrupt:
            terminate_process(proc)
            return 130, "feroxbuster was interrupted by the user"

        if progress_callback:
            progress_callback(time.monotonic() - started)
    if proc.returncode != 0:
        return proc.returncode, f"feroxbuster exited with code {proc.returncode}"
    return proc.returncode, None


def _extract_field(obj: dict, *names: str):
    for name in names:
        if name in obj:
            return obj.get(name)
    return None


def parse_json_output(json_output: Path, *, run_id: int, project_id: int, host_id: int, source: str) -> list[dict]:
    findings: list[dict] = []
    if not json_output.exists():
        return findings

    for line in json_output.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # feroxbuster JSON lines can include config/progress objects. Keep only result-looking objects.
        url = _extract_field(obj, "url", "target")
        status = _extract_field(obj, "status", "status_code")
        if not url or status is None:
            continue

        parsed = urlparse(str(url))
        findings.append(
            {
                "run_id": run_id,
                "project_id": project_id,
                "host_id": host_id,
                "url": str(url),
                "path": parsed.path,
                "status_code": int(status) if str(status).isdigit() else None,
                "content_length": _extract_field(obj, "content_length", "length", "size"),
                "words": _extract_field(obj, "words", "word_count"),
                "lines": _extract_field(obj, "lines", "line_count"),
                "redirect": _extract_field(obj, "redirect", "location"),
                "source": source,
            }
        )
    return findings
