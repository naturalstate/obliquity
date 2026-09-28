from __future__ import annotations

import json
import os
import re
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
        "--no-state",
    ]

    if stage.extensions:
        cmd += ["--extensions", ",".join(stage.extensions)]

    # Extension Intelligence: let feroxbuster discover extensions from responses
    # and fold them into the scan (its -E flag). Previously this Stage field was
    # defined but never emitted.
    if stage.collect_extensions:
        cmd += ["--collect-extensions"]

    # Link extraction (parse response bodies for URLs and request them) is ON by
    # default in feroxbuster -- only emit a flag to turn it OFF.
    if not stage.extract_links:
        cmd += ["--dont-extract-links"]

    if stage.recursion:
        if stage.depth is not None:
            cmd += ["--depth", str(stage.depth)]
    else:
        cmd += ["--no-recursion"]

    if stage.status_codes:
        cmd += ["--status-codes", ",".join(str(x) for x in stage.status_codes)]

    # Response filters: drop noise by status/size/words/lines/regex.
    if stage.filter_status:
        cmd += ["--filter-status", ",".join(str(x) for x in stage.filter_status)]
    if stage.filter_size:
        cmd += ["--filter-size", ",".join(str(x) for x in stage.filter_size)]
    if stage.filter_words:
        cmd += ["--filter-words", ",".join(str(x) for x in stage.filter_words)]
    if stage.filter_lines:
        cmd += ["--filter-lines", ",".join(str(x) for x in stage.filter_lines)]
    if stage.filter_regex:
        cmd += ["--filter-regex", stage.filter_regex]

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


# Returned when abort_check stops the process mid-run (e.g. a status-code flood
# / wildcard). Distinct from feroxbuster's own exit codes so callers can tell.
FLOOD_ABORT_EXIT = 141


def run_command(
    cmd: list[str],
    raw_output: Path,
    progress_callback: ProgressCallback | None = None,
    abort_check: Callable[[float], str | None] | None = None,
) -> tuple[int, str | None]:
    """Run feroxbuster. If `abort_check(elapsed)` returns a reason string mid-run,
    the process is terminated and (FLOOD_ABORT_EXIT, reason) is returned."""
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    with raw_output.open("w", encoding="utf-8", errors="replace") as handle:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT, text=True)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                elapsed = time.monotonic() - started
                if progress_callback:
                    progress_callback(elapsed)
                if abort_check is not None:
                    reason = abort_check(elapsed)
                    if reason:
                        terminate_process(proc)
                        return FLOOD_ABORT_EXIT, reason
                time.sleep(0.1)
        except KeyboardInterrupt:
            terminate_process(proc)
            return 130, "feroxbuster was interrupted by the user"

        if progress_callback:
            progress_callback(time.monotonic() - started)
    if proc.returncode != 0:
        return proc.returncode, f"feroxbuster exited with code {proc.returncode}"
    return proc.returncode, None


# --- live progress -----------------------------------------------------------
# feroxbuster only renders its progress bar to a TTY, so the bust runner drives
# it through a PTY (run_with_progress below) and parses the bar. A rendered line
# looks like:  [####>---------------] - 3s   142/438   0s   found:7   errors:0
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BAR_RE = re.compile(r"\[[#>\s\-]{3,}\].*?(\d+)\s*/\s*(\d+)")
# A result row feroxbuster prints, e.g. "200      GET   1l   2w   11c http://..."
_RESULT_RE = re.compile(r"^\s*\d{3}\s+[A-Z]{3,7}\b")

# Two-arg progress callback: (elapsed_seconds, parsed_progress_or_None).
LiveProgressCallback = Callable[[float, "dict | None"], None]


def parse_progress(text: str) -> dict | None:
    """Extract the latest feroxbuster progress from captured (PTY) output.

    Returns ``{percent, done, total, found, errors}`` for the aggregate bar
    (the one with the largest total -- feroxbuster's overall counter), or None
    if no bar has rendered yet."""
    text = _ANSI_RE.sub("", text)
    best: tuple[int, int] | None = None
    found = errors = None
    for seg in re.split(r"[\r\n]", text):
        m = _BAR_RE.search(seg)
        if not m:
            continue
        done, total = int(m.group(1)), int(m.group(2))
        if total <= 0:
            continue
        # Prefer the aggregate bar (largest total); on a tie, the later segment
        # wins because we iterate the buffer in render order (most recent last).
        if best is None or total >= best[1]:
            best = (done, total)
            fm = re.search(r"found:\s*(\d+)", seg)
            em = re.search(r"errors:\s*(\d+)", seg)
            found = int(fm.group(1)) if fm else found
            errors = int(em.group(1)) if em else errors
    if best is None:
        return None
    done, total = best
    return {
        "percent": min(100.0, done / total * 100.0),
        "done": done,
        "total": total,
        "found": found,
        "errors": errors,
    }


def _terminate_pid(pid: int) -> None:
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(30):  # up to ~3s for a graceful exit
        try:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return
        except ChildProcessError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass


def run_with_progress(
    cmd: list[str],
    raw_output: Path,
    progress_callback: LiveProgressCallback | None = None,
    abort_check: Callable[[float], str | None] | None = None,
) -> tuple[int, str | None]:
    """Run feroxbuster under a PTY so its real progress bar renders, parsing it
    into a live percentage / found / errors for the caller. Same contract as
    run_command otherwise (FLOOD_ABORT_EXIT on abort, 130 on Ctrl-C). Falls back
    to the plain runner where a PTY isn't available."""
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pty
        import select
    except ImportError:  # no PTY on this platform -- degrade gracefully.
        wrapped = (lambda e: progress_callback(e, None)) if progress_callback else None
        return run_command(cmd, raw_output, wrapped, abort_check=abort_check)

    try:
        pid, fd = pty.fork()
    except OSError:
        wrapped = (lambda e: progress_callback(e, None)) if progress_callback else None
        return run_command(cmd, raw_output, wrapped, abort_check=abort_check)

    if pid == 0:  # child
        try:
            os.execvp(cmd[0], cmd)
        except OSError:
            os._exit(127)

    started = time.monotonic()
    tail = ""
    handle = raw_output.open("w", encoding="utf-8", errors="replace")
    try:
        while True:
            elapsed = time.monotonic() - started
            try:
                readable, _, _ = select.select([fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if readable:
                try:
                    chunk = os.read(fd, 8192)
                except OSError:  # EIO: child closed the PTY (it exited)
                    chunk = b""
                if not chunk:
                    break
                text = chunk.decode("utf-8", "replace")
                handle.write(_ANSI_RE.sub("", text))
                tail = (tail + text)[-16384:]
            if progress_callback:
                progress_callback(elapsed, parse_progress(tail) if tail else None)
            if abort_check is not None:
                reason = abort_check(elapsed)
                if reason:
                    _terminate_pid(pid)
                    return FLOOD_ABORT_EXIT, reason
    except KeyboardInterrupt:
        _terminate_pid(pid)
        return 130, "feroxbuster was interrupted by the user"
    finally:
        handle.close()

    try:
        _, wstatus = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(wstatus)
    except ChildProcessError:
        code = 0
    if progress_callback:
        progress_callback(time.monotonic() - started, parse_progress(tail) if tail else None)
    if code != 0:
        return code, f"feroxbuster exited with code {code}"
    return code, None


def _banner_end_offset(buf: bytes) -> int | None:
    """Byte offset of the first results/progress-bar line in `buf`, i.e. where
    feroxbuster's startup banner ends. None while only banner has arrived."""
    pos = 0
    for line in buf.split(b"\n"):
        stripped = _ANSI_RE.sub("", line.decode("utf-8", "replace"))
        if _BAR_RE.search(stripped) or _RESULT_RE.search(stripped):
            return pos
        pos += len(line) + 1  # + the newline we split on
    return None


def run_passthrough(cmd: list[str], raw_output: Path) -> tuple[int, str | None]:
    """Run feroxbuster attached to the real terminal so its native pinned UI --
    scrolling results, progress bars, clickable URLs, and the Scan Management
    Menu -- is shown live, with only the startup banner suppressed. Keystrokes
    are forwarded so the menu works; findings are still written to the --output
    JSON. Requires a TTY on stdin+stdout (callers gate on that); returns the same
    (exit_code, error) contract as run_command."""
    import fcntl
    import pty
    import select
    import signal
    import termios
    import tty

    raw_output.parent.mkdir(parents=True, exist_ok=True)
    stdin_fd, stdout_fd = 0, 1

    pid, master = pty.fork()
    if pid == 0:  # child
        try:
            os.execvp(cmd[0], cmd)
        except OSError:
            os._exit(127)

    def _sync_winsize(*_) -> None:
        try:
            sz = fcntl.ioctl(stdout_fd, termios.TIOCGWINSZ, b"\0" * 8)
            fcntl.ioctl(master, termios.TIOCSWINSZ, sz)
        except OSError:
            pass

    _sync_winsize()
    try:
        old_attr = termios.tcgetattr(stdin_fd)
        tty.setcbreak(stdin_fd)  # cbreak (not raw) keeps Ctrl-C -> SIGINT for us
    except (termios.error, ValueError, OSError):
        old_attr = None
    try:
        signal.signal(signal.SIGWINCH, _sync_winsize)
    except (ValueError, OSError):
        pass

    forwarding = False
    pending = b""
    handle = raw_output.open("wb")
    try:
        while True:
            try:
                readable, _, _ = select.select([master, stdin_fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if master in readable:
                try:
                    data = os.read(master, 65536)
                except OSError:  # EIO -- child exited
                    data = b""
                if not data:
                    break
                handle.write(data)
                if forwarding:
                    os.write(stdout_fd, data)
                else:
                    pending += data
                    offset = _banner_end_offset(pending)
                    if offset is not None:
                        os.write(stdout_fd, pending[offset:])
                        pending = b""
                        forwarding = True
            if stdin_fd in readable:
                try:
                    keys = os.read(stdin_fd, 4096)
                except OSError:
                    keys = b""
                if keys:
                    os.write(master, keys)
    except KeyboardInterrupt:
        _terminate_pid(pid)
    finally:
        handle.close()
        if old_attr is not None:
            try:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attr)
            except (termios.error, OSError):
                pass
        try:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        except (ValueError, OSError):
            pass
        os.write(stdout_fd, b"\n")  # leave the cursor on a fresh line

    try:
        _, wstatus = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(wstatus)
    except ChildProcessError:
        code = 0
    if code not in (0, 130):
        return code, f"feroxbuster exited with code {code}"
    return code, None


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
