from __future__ import annotations

import shutil
from pathlib import Path

from obliquity.core.crackplan import CrackStage

# hashcat attack-mode names Obliquity understands, mapped to hashcat's -a values.
ATTACK_MODES = {
    "dictionary": "0",
    "mask": "3",
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
    extra_args: list[str] | None = None,
) -> list[str]:
    if stage.attack_mode not in ATTACK_MODES:
        raise ValueError(f"unsupported hashcat attack mode: {stage.attack_mode}")

    cmd = [
        "hashcat",
        "-m", str(hash_type),
        "-a", ATTACK_MODES[stage.attack_mode],
        "-o", str(output),
        # 1=hash[:salt], 2=plain -- comma-separated codes, NOT a bitmask sum
        # (confirmed against real hashcat 7.1.2; parse_output() needs "hash:plain").
        "--outfile-format", "1,2",
        "--potfile-disable",
    ]

    if session:
        cmd += ["--session", session]

    if stage.rules:
        cmd += ["-r", stage.rules]

    cmd += stage.extra_args
    cmd += extra_args or []

    cmd.append(hash_file)

    if stage.attack_mode == "dictionary":
        cmd.append(stage.wordlist)
    elif stage.attack_mode == "mask":
        cmd.append(stage.mask)

    return cmd


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
