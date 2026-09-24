from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obliquity.core.extensions import expand_extensions, wordlist_has_extensions
from obliquity.core.wordlists import resolve_path


@dataclass
class Stage:
    name: str
    wordlist: str
    extensions: list[str] = field(default_factory=list)
    recursion: bool = False
    depth: int | None = None
    status_codes: list[int] = field(default_factory=lambda: [200, 204, 301, 302, 307, 308, 401, 403])
    collect_extensions: bool = False
    # Response filters (feroxbuster -C/-S/-W/-N/-X): drop noisy responses by
    # status code, byte size, word count, line count, or a regex on the body.
    filter_status: list[int] = field(default_factory=list)
    filter_size: list[int] = field(default_factory=list)
    filter_words: list[int] = field(default_factory=list)
    filter_lines: list[int] = field(default_factory=list)
    filter_regex: str | None = None
    extra_args: list[str] = field(default_factory=list)


@dataclass
class Gameplan:
    name: str
    description: str
    stages: list[Stage]


def load_gameplan(path: Path) -> Gameplan:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_stages = data.get("stages", [])
    # Extension Intelligence: a stage's "extensions" may be a named tier
    # ("low"/"medium"/"high") instead of a literal list -- expand it before
    # building the Stage so everything downstream (command, fingerprint) sees
    # the concrete list.
    for stage in raw_stages:
        if "extensions" in stage:
            stage["extensions"] = expand_extensions(stage["extensions"])
    stages = [Stage(**stage) for stage in raw_stages]
    for stage in stages:
        wordlist = Path(stage.wordlist)
        if not wordlist.is_absolute():
            stage.wordlist = str((path.parent / wordlist).resolve())
        stage.wordlist = resolve_path(stage.wordlist)
    if not stages:
        raise ValueError(f"Gameplan has no stages: {path}")
    return Gameplan(
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        stages=stages,
    )


def fingerprint_stage(url: str, gameplan: Gameplan, stage: Stage, *, project_id: int) -> str:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "url": url.rstrip("/"),
        "gameplan": gameplan.name,
        "stage": stage.name,
        "wordlist": stage.wordlist,
        "extensions": sorted(stage.extensions),
        "recursion": stage.recursion,
        "depth": stage.depth,
        "collect_extensions": stage.collect_extensions,
        "status_codes": sorted(stage.status_codes),
        "filter_status": sorted(stage.filter_status),
        "filter_size": sorted(stage.filter_size),
        "filter_words": sorted(stage.filter_words),
        "filter_lines": sorted(stage.filter_lines),
        "filter_regex": stage.filter_regex,
        "extra_args": stage.extra_args,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def profiles_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "profiles"


def find_builtin_gameplan(name: str) -> Path:
    candidate = profiles_dir() / f"{name}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Unknown gameplan '{name}'. Expected {candidate}")
    return candidate


def list_builtin_gameplans() -> list[Path]:
    return sorted(profiles_dir().glob("*.json"))


def extension_conflicts(gameplan: Gameplan) -> list[tuple[str, str, list[str]]]:
    """Extension Intelligence: find stages that append extensions to a wordlist
    that *already* carries extensions -- the double-extension waste case
    (``index.php`` + ``.php`` -> ``index.php.php``). Returns
    ``(stage_name, wordlist, appended_extensions)`` per offending stage.

    Only inspects wordlists that exist on disk, so a missing wordlist never
    turns this into an error; it's advisory."""
    conflicts: list[tuple[str, str, list[str]]] = []
    checked: dict[str, bool] = {}
    for stage in gameplan.stages:
        if not stage.extensions:
            continue
        wl = stage.wordlist
        if wl not in checked:
            try:
                checked[wl] = wordlist_has_extensions(wl)
            except OSError:
                checked[wl] = False
        if checked[wl]:
            conflicts.append((stage.name, wl, list(stage.extensions)))
    return conflicts
