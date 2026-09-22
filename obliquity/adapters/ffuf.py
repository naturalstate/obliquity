from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path
from typing import Any

from obliquity.adapters.feroxbuster import run_command


class FfufMissing(RuntimeError):
    pass


def require_ffuf() -> None:
    if shutil.which("ffuf") is None:
        raise FfufMissing("ffuf was not found in PATH. Install ffuf, then rerun Obliquity.")


def build_command(
    template: str = "",
    wordlist: str = "",
    *,
    output: Path | None = None,
    url_template: str | None = None,
    request_file: str | None = None,
    request_proto: str = "https",
    mode: str = "clusterbomb",
    match_codes: str | None = None,
    filter_codes: str | None = None,
    filter_size: str | None = None,
    method: str | None = None,
    data: str | None = None,
    headers: list[str] | None = None,
    cookie: str | None = None,
    request: Path | None = None,
    proxy: str | None = None,
    threads: int | None = None,
    rate: int | None = None,
    autocalibrate: bool = True,
) -> list[str]:
    template = url_template if url_template is not None else template
    request = Path(request_file) if request_file else request
    if "FUZZ" not in template and request is None:
        raise ValueError("ffuf operation requires FUZZ in the template or a raw request file")
    cmd = ["ffuf", "-w", wordlist, "-json", "-s", "-noninteractive"]
    if request:
        cmd += ["-request", str(request)]
        if request_proto:
            cmd += ["-request-proto", request_proto]
    else:
        cmd += ["-u", template]
    if mode:
        cmd += ["-mode", mode]
    if method:
        cmd += ["-X", method]
    if data:
        cmd += ["-d", data]
    for header in headers or []:
        cmd += ["-H", header]
    if cookie:
        cmd += ["-b", cookie]
    if proxy:
        cmd += ["-x", proxy]
    if threads:
        cmd += ["-t", str(threads)]
    if rate:
        cmd += ["-rate", str(rate)]
    if match_codes:
        cmd += ["-mc", match_codes]
    if filter_codes:
        cmd += ["-fc", filter_codes]
    if filter_size:
        cmd += ["-fs", filter_size]
    if autocalibrate:
        cmd += ["-ac"]
    return cmd


def fingerprint(project_id: int, operation: str, command: list[str]) -> str:
    payload = {"project_id": project_id, "operation": operation, "command": command}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def parse_jsonl(path: Path, *, run_id: int, project_id: int, host_id: int, source: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not path.exists():
        return findings
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or not item.get("url") or item.get("status") is None:
            continue
        findings.append(
            {
                "run_id": run_id,
                "project_id": project_id,
                "host_id": host_id,
                "url": item["url"],
                "path": item["url"].split("?", 1)[0],
                "status_code": item.get("status"),
                "content_length": item.get("length"),
                "words": item.get("words"),
                "lines": item.get("lines"),
                "redirect": item.get("redirectlocation"),
                "source": source,
            }
        )
    return findings


parse_json_output = parse_jsonl
