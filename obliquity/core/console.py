from __future__ import annotations

import os
import sys
import colorsys
from typing import Iterable

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "gray": "\033[90m",
}


def supports_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, color: str | None = None, *, bold: bool = False, dim: bool = False) -> str:
    if not supports_color():
        return text
    parts: list[str] = []
    if bold:
        parts.append(BOLD)
    if dim:
        parts.append(DIM)
    if color:
        parts.append(COLORS.get(color, ""))
    parts.append(text)
    parts.append(RESET)
    return "".join(parts)


def rainbow_text(text: str) -> str:
    if not supports_color():
        return text

    visible_chars = [ch for ch in text if ch not in ("\n", " ")]
    total = max(len(visible_chars), 1)

    output: list[str] = []
    index = 0
    for ch in text:
        if ch in ("\n", " "):
            output.append(ch)
            continue

        hue = index / total
        r, g, b = colorsys.hsv_to_rgb(hue, 0.95, 1.0)
        output.append(
            f"\033[38;2;{int(r * 255)};{int(g * 255)};{int(b * 255)}m"
            f"{ch}"
            f"{RESET}"
        )
        index += 1

    return "".join(output)


def section(title: str, color: str = "cyan") -> None:
    print()
    print(c(title, color, bold=True))
    print(c("=" * len(title), color, bold=True))


def subsection(title: str, color: str = "magenta") -> None:
    print()
    print(c(title, color, bold=True))
    print(c("-" * len(title), color, bold=True))


def kv(label: str, value: object, *, color: str = "cyan") -> None:
    print(f"{c(label + ':', color, bold=True)} {value}")


def bullet(label: str, value: object, *, color: str = "cyan") -> None:
    print(f"  {c(label + ':', color, bold=True)} {value}")


def blank() -> None:
    print()


def command_block(command: str) -> None:
    print()
    print(c("Command:", "yellow", bold=True))
    print(command)
    print()


SPINNER = "|/-\\"


def elapsed_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def progress_bar(percent: int, width: int = 20) -> str:
    value = max(0, min(100, percent))
    filled = round(width * value / 100)
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def format_speed(hps: float) -> str:
    for unit, div in (("GH/s", 1e9), ("MH/s", 1e6), ("kH/s", 1e3)):
        if hps >= div:
            return f"{hps / div:.1f} {unit}"
    return f"{int(hps)} H/s"


def live_progress_line(event: dict) -> str:
    elapsed = float(event.get("elapsed") or 0)
    spinner = c(SPINNER[int(elapsed * 10) % len(SPINNER)], "yellow", bold=True)
    total = max(1, int(event.get("total_stages") or 1))
    current = max(1, int(event.get("stage_number") or 1))
    stage = event.get("stage") or "unknown"

    # When the tool gives a real percentage, show a live animated bar for THIS
    # stage. hashcat (--status-json) reports speed/recovered/ETA/temp; feroxbuster
    # (parsed from its PTY progress bar) reports requests done / found / errors.
    status = event.get("status")
    findings = int(event.get("findings") or 0)
    if status and status.get("percent") is not None:
        pct = int(round(status["percent"]))
        parts = [f"{spinner} Stage {current}/{total}: {stage}",
                 f"{c(progress_bar(pct), 'cyan', bold=True)} {pct:3d}%"]
        if status.get("kind") == "bust":
            done, tot = status.get("done"), status.get("total")
            if tot:
                parts.append(f"{done}/{tot} reqs")
            parts.append(f"found {findings}")
            if status.get("errors"):
                parts.append(f"err {status['errors']}")
            parts.append(f"Elapsed {elapsed_time(elapsed)}")
        else:
            if status.get("speed"):
                parts.append(format_speed(status["speed"]))
            parts.append(f"rec {status.get('recovered', 0)}/{status.get('recovered_total', 0)}")
            if status.get("eta") is not None:
                parts.append(f"ETA {elapsed_time(status['eta'])}")
            if status.get("temp") is not None:
                parts.append(f"{int(status['temp'])}°C")
        return "  ".join(parts)

    # No within-stage percentage yet (bar hasn't rendered, or no PTY). Report
    # honestly at stage granularity instead of a fixed, misleading "overall %".
    return (
        f"{spinner} Stage {current}/{total}: {stage}  "
        f"{current - 1}/{total} stages done  "
        f"Elapsed {elapsed_time(elapsed)}  Findings {findings}"
    )
