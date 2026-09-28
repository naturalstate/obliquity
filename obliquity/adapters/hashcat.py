from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from obliquity.core.crackplan import CrackStage

# hashcat attack-mode names Obliquity understands, mapped to hashcat's -a values.
ATTACK_MODES = {
    "dictionary": "0",
    "combinator": "1",
    "mask": "3",
    "hybrid-wordlist-mask": "6",
    "hybrid-mask-wordlist": "7",
}


class HashcatMissing(RuntimeError):
    pass


def require_hashcat() -> None:
    if shutil.which("hashcat") is None:
        raise HashcatMissing("hashcat was not found in PATH. Install hashcat first, then rerun Obliquity.")


def build_command(
    hash_file: str,
    hash_type: int,
    stage: CrackStage,
    output: Path,
    *,
    session: str | None = None,
    restore_file: Path | None = None,
    restore: bool = False,
    extra_args: list[str] | None = None,
) -> list[str]:
    if stage.attack_mode not in ATTACK_MODES:
        raise ValueError(f"unsupported hashcat attack mode: {stage.attack_mode}")

    # Resuming: hashcat reads every other parameter from the restore file, so
    # the command must be minimal -- reissuing the full arg list alongside
    # --restore makes hashcat error or ignore it.
    if restore:
        if restore_file is None:
            raise ValueError("restore=True requires a restore_file")
        cmd = ["hashcat", "--restore", "--restore-file-path", str(restore_file)]
        if session:
            cmd += ["--session", session]
        return cmd

    cmd = [
        "hashcat",
        "-m", str(hash_type),
        "-a", ATTACK_MODES[stage.attack_mode],
        "-o", str(output),
        # 1=hash[:salt], 2=plain -- comma-separated codes, NOT a bitmask sum
        # (confirmed against real hashcat 7.1.2; parse_output() needs "hash:plain").
        "--outfile-format", "1,2",
        "--potfile-disable",
        # Emit machine-readable status to stdout every second so Obliquity can
        # surface live progress %, hash-rate, recovered count, ETA, and temp.
        "--status", "--status-json", "--status-timer", "1",
    ]

    if session:
        cmd += ["--session", session]

    # Write the checkpoint to a path Obliquity controls, so `crack resume`
    # can find it later regardless of hashcat's build-specific default location.
    if restore_file is not None:
        cmd += ["--restore-file-path", str(restore_file)]

    for rule in stage.rules or []:
        cmd += ["-r", rule]

    cmd += stage.extra_args
    cmd += extra_args or []

    cmd.append(hash_file)

    # Positional arguments after the hash file are mode-specific, and order
    # matters (hashcat mode 6 is wordlist-then-mask, mode 7 is mask-then-wordlist).
    if stage.attack_mode == "dictionary":
        cmd.append(stage.wordlist)
    elif stage.attack_mode == "mask":
        cmd.append(stage.mask)
    elif stage.attack_mode == "combinator":
        cmd += [stage.wordlist, stage.wordlist2]
    elif stage.attack_mode == "hybrid-wordlist-mask":
        cmd += [stage.wordlist, stage.mask]
    elif stage.attack_mode == "hybrid-mask-wordlist":
        cmd += [stage.mask, stage.wordlist]

    return cmd


def parse_status(text: str) -> dict | None:
    """Extract a friendly live-status dict from hashcat's `--status-json` output
    (which prints one JSON status object per second to stdout). Returns the most
    recent one as {percent, speed, recovered, total, eta, temp}, or None."""
    latest = None
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        # hashcat prefixes each status object with its interactive prompt
        # ("[s]tatus [p]ause ... =>  { ... }"), so parse from the first "{".
        idx = line.find("{")
        if idx < 0 or '"progress"' not in line:
            continue
        try:
            obj, _ = decoder.raw_decode(line[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "progress" in obj:
            latest = obj
    if latest is None:
        return None

    prog = latest.get("progress") or [0, 0]
    done, total = (prog + [0, 0])[:2]
    percent = (done / total * 100.0) if total else 0.0
    rec = latest.get("recovered_hashes") or [0, 0]
    recovered, rec_total = (rec + [0, 0])[:2]
    devices = latest.get("devices") or []
    speed = sum(d.get("speed", 0) for d in devices if isinstance(d, dict))
    temps = [d.get("temp") for d in devices if isinstance(d, dict) and isinstance(d.get("temp"), (int, float)) and d.get("temp", -1) >= 0]
    temp = max(temps) if temps else None
    est = latest.get("estimated_stop")
    eta = None
    if isinstance(est, (int, float)) and est > 0:
        eta = max(0, int(est - time.time()))
    return {
        "percent": percent,
        "speed": speed,
        "recovered": recovered,
        "recovered_total": rec_total,
        "eta": eta,
        "temp": temp,
    }


def read_status(raw_output: Path) -> dict | None:
    """Read the latest status from hashcat's captured stdout file."""
    if not raw_output.exists():
        return None
    try:
        # only need the tail; status objects are the last lines written
        return parse_status(raw_output.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def parse_output(output: Path, *, run_id: int, project_id: int, job_id: int, source: str) -> list[dict]:
    """Parse a hashcat `--outfile-format 2` file: one `hash:plaintext` pair per line."""
    results: list[dict] = []
    if not output.exists():
        return results

    for line in output.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        hash_value, sep, plaintext = line.rpartition(":")
        if not sep:
            continue
        results.append(
            {
                "run_id": run_id,
                "project_id": project_id,
                "job_id": job_id,
                "hash": hash_value,
                "plaintext": plaintext,
                "source": source,
            }
        )
    return results
