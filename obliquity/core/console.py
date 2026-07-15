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


def live_progress_line(event: dict) -> str:
    total = max(1, int(event.get("total_stages") or 1))
    current = max(1, int(event.get("stage_number") or 1))
    percent = round((current - 1) * 100 / total)
    elapsed = float(event.get("elapsed") or 0)
    spinner = SPINNER[int(elapsed * 10) % len(SPINNER)]
    bar = c(progress_bar(percent), "cyan", bold=True)
    stage = event.get("stage") or "unknown"
    findings = int(event.get("findings") or 0)
    return (
        f"{c(spinner, 'yellow', bold=True)} Stage {current}/{total}: {stage}  "
        f"Overall {bar} {percent:3d}%  "
        f"Elapsed {elapsed_time(elapsed)}  Findings {findings}"
    )
