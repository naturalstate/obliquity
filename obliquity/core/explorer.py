"""Data layer for the Wordlist Explorer.

Pure, testable functions that build the browsable index of gameplans and
wordlists and render their detail views as plain text lines. The curses UI in
``cli.py`` is a thin renderer over these; a non-TTY fallback prints the same
lines. Nothing here imports curses.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from obliquity.core.crackplan import list_builtin_crackplans, load_crackplan
from obliquity.core.extensions import analyze_wordlist
from obliquity.core.fuzzplan import list_fuzz_plans, load_fuzz_plan
from obliquity.core.gameplan import list_builtin_gameplans, load_gameplan
from obliquity.core.loginplan import list_builtin_loginplans, load_loginplan
from obliquity.core.wordlists import WORDLIST_CATALOG


@dataclass
class GameplanRef:
    tool: str            # bust | fuzz | crack | brute
    name: str
    description: str
    stages: list[dict] = field(default_factory=list)   # [{name, wordlists: [..], detail: str}]


@dataclass
class WordlistRef:
    name: str                                   # basename, the identity key
    path: str                                   # representative path (prefers one that exists)
    referenced_by: list[str] = field(default_factory=list)  # "bust/generic-standard (stage)"
    description: str | None = None
    category: str | None = None


def _fuzz_op_use(category: str | None) -> str:
    return {
        "parameter-name": "fuzz -- discover hidden parameter names",
        "parameter-value": "fuzz -- test values of a known parameter",
        "request-input": "fuzz -- fuzz points inside a raw HTTP request",
    }.get(category or "", "fuzz")


def collect_gameplans() -> list[GameplanRef]:
    """All built-in gameplans across the four pillars, with the wordlists each
    stage uses (so the explorer can cross-link them to wordlists)."""
    out: list[GameplanRef] = []

    for path in list_builtin_gameplans():
        gp = load_gameplan(path)
        stages = [
            {"name": s.name, "wordlists": [s.wordlist],
             "detail": f"exts=[{', '.join(s.extensions) or '-'}] "
                       f"recursion={'yes' if s.recursion else 'no'}"}
            for s in gp.stages
        ]
        out.append(GameplanRef("bust", gp.name, gp.description, stages))

    for path in list_fuzz_plans():
        fp = load_fuzz_plan(path)
        out.append(GameplanRef(
            "fuzz", fp.name, fp.description,
            [{"name": fp.operation_category, "wordlists": [fp.wordlist], "detail": _fuzz_op_use(fp.operation_category)}],
        ))

    for path in list_builtin_crackplans():
        cp = load_crackplan(path)
        stages = []
        for s in cp.stages:
            wls = [w for w in (s.wordlist, s.wordlist2) if w]
            stages.append({"name": s.name, "wordlists": wls, "detail": f"attack={s.attack_mode}"})
        out.append(GameplanRef("crack", cp.name, cp.description, stages))

    for path in list_builtin_loginplans():
        lp = load_loginplan(path)
        stages = []
        for s in lp.stages:
            wls = [w for w in (s.userlist, s.passlist) if w]
            stages.append({"name": s.name, "wordlists": wls,
                           "detail": f"users={s.username or Path(s.userlist).name if s.userlist else s.username} "})
        out.append(GameplanRef("brute", lp.name, lp.description, stages))

    return out


def _derive_description(name: str) -> tuple[str, str | None]:
    """(description, category) guessed from a filename when no catalog entry
    matches. Category doubles as a similarity key."""
    n = name.lower()
    if "rockyou" in n or "password" in n or "-creds" in n:
        return "Password / credential list", "passwords"
    if "user" in n:
        return "Username list", "usernames"
    if "param" in n:
        return "Parameter-name list", "parameters"
    if "file" in n:
        return "File-name wordlist", "web-content-files"
    if "director" in n or n.startswith("dir"):
        return "Directory/path-name wordlist", "web-content-dirs"
    if "raft" in n:
        return "RAFT-derived web-content wordlist", "web-content"
    if "common" in n or "big" in n:
        return "Common web-content wordlist (dirs + files)", "web-content"
    return "Wordlist", None


def collect_wordlists(gameplans: list[GameplanRef]) -> list[WordlistRef]:
    """Every wordlist referenced by a built-in gameplan, plus the download
    catalog. Keyed by basename so the same list referenced from several
    gameplans (or present in the catalog) shows up once."""
    index: dict[str, WordlistRef] = {}

    for gp in gameplans:
        for stage in gp.stages:
            label = f"{gp.tool}/{gp.name}"
            if stage["name"] and stage["name"] != gp.name:
                label += f" ({stage['name']})"
            for wl in stage["wordlists"]:
                if not wl:
                    continue
                key = Path(wl).name
                ref = index.get(key)
                if ref is None:
                    desc, cat = _derive_description(key)
                    ref = WordlistRef(name=key, path=wl, description=desc, category=cat)
                    index[key] = ref
                elif Path(wl).exists() and not Path(ref.path).exists():
                    ref.path = wl  # prefer a path that actually exists on disk
                if label not in ref.referenced_by:
                    ref.referenced_by.append(label)

    # Fold in the download catalog: attach its curated description/category to a
    # matching entry, or add it as a standalone browsable wordlist.
    from obliquity.core.wordlists import installed_path, is_installed
    for entry in WORDLIST_CATALOG:
        key = Path(entry.match_suffix).name
        ref = index.get(key)
        installed = installed_path(entry)
        if ref is not None:
            ref.description = entry.description
            ref.category = entry.category
            if is_installed(entry) and not Path(ref.path).exists():
                ref.path = str(installed)
        else:
            index[key] = WordlistRef(
                name=key, path=str(installed) if is_installed(entry) else str(installed),
                description=entry.description, category=entry.category,
            )

    return sorted(index.values(), key=lambda r: r.name)


def find_similar(target: WordlistRef, allrefs: list[WordlistRef], limit: int = 6) -> list[WordlistRef]:
    """Similar = same category, or a shared leading name token
    (raft-medium-files ~ raft-large-files ~ raft-medium-directories)."""
    stem = target.name.split(".")[0].split("-")[0].lower()
    scored: list[tuple[int, WordlistRef]] = []
    for r in allrefs:
        if r.name == target.name:
            continue
        score = 0
        if target.category and r.category == target.category:
            score += 2
        if r.name.split(".")[0].split("-")[0].lower() == stem:
            score += 1
        if score:
            scored.append((score, r))
    scored.sort(key=lambda sr: (-sr[0], sr[1].name))
    return [r for _, r in scored[:limit]]


def _head_tail(path: Path, n: int = 8) -> tuple[list[str], list[str]]:
    """First n and last n content lines. Tail is read from the end so huge
    lists (raft-large) don't get fully loaded."""
    head: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            head.append(line.rstrip("\n"))
            if len(head) >= n:
                break
    tail = _tail_lines(path, n)
    return head, tail


def _tail_lines(path: Path, n: int) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
        lines = data.split(b"\n")
        text = [ln.decode("utf-8", "replace") for ln in lines if ln.strip()]
        return text[-n:]
    except OSError:
        return []


# --- detail renderers: return plain text lines for TUI or fallback -----------

def gameplan_detail_lines(gp: GameplanRef) -> list[str]:
    lines = [f"{gp.tool}  gameplan:  {gp.name}", ""]
    if gp.description:
        lines += _wrap(gp.description) + [""]
    lines.append(f"Stages ({len(gp.stages)}):")
    for i, stage in enumerate(gp.stages, 1):
        lines.append(f"  {i}. {stage['name']}   {stage['detail']}")
        for wl in stage["wordlists"]:
            lines.append(f"       wordlist: {Path(wl).name}")
    lines += ["", f"Run it:  obliquity {gp.tool} run <project> --gameplan {gp.name}"]
    return lines


def wordlist_detail_lines(ref: WordlistRef, allrefs: list[WordlistRef], sample: int = 8) -> list[str]:
    path = Path(ref.path)
    a = analyze_wordlist(path, preview_lines=0)
    lines = [f"wordlist:  {ref.name}", f"path:      {ref.path}", ""]
    if ref.description:
        lines += _wrap(f"Description: {ref.description}")
    if ref.category:
        lines.append(f"Category / typical use: {ref.category}")
    lines.append("")

    if not a.exists:
        lines.append("Status: NOT installed on this machine.")
        lines.append("Install via: obliquity wordlists install <name>  (if in the catalog)")
    else:
        lines.append(f"Length: {a.line_count:,} entries    Size: {_human(a.byte_size)}")
        verdict = "yes" if a.has_extensions else "no"
        lines.append(f"Contains extensions: {verdict} ({a.extension_ratio:.0%} of sample)")
        if a.top_extensions:
            lines.append("  most common: " + ", ".join(f".{e} ({c})" for e, c in a.top_extensions))
        head, tail = _head_tail(path, sample)
        lines += ["", "Head:"] + [f"    {h}" for h in head]
        if tail and a.line_count > sample:
            lines += ["", "Tail:"] + [f"    {t}" for t in tail]

    lines += ["", "Used by gameplans:"]
    if ref.referenced_by:
        lines += [f"  - {r}" for r in ref.referenced_by]
    else:
        lines.append("  (none -- standalone catalog wordlist)")

    similar = find_similar(ref, allrefs)
    lines += ["", "Similar wordlists:"]
    lines += [f"  - {s.name}" for s in similar] if similar else ["  (none)"]
    return lines


def _wrap(text: str, width: int = 72) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width) or [""]


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
