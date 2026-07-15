from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Stage:
    name: str
    wordlist: str
    extensions: list[str] = field(default_factory=list)
    recursion: bool = False
    depth: int | None = None
    status_codes: list[int] = field(default_factory=lambda: [200, 204, 301, 302, 307, 308, 401, 403])
    collect_extensions: bool = False
    extra_args: list[str] = field(default_factory=list)
    estimated_minutes: int | None = None


@dataclass
class Gameplan:
    name: str
    description: str
    stages: list[Stage]


def load_gameplan(path: Path) -> Gameplan:
    data = json.loads(path.read_text(encoding="utf-8"))
    stages = [Stage(**stage) for stage in data.get("stages", [])]
    if not stages:
        raise ValueError(f"Gameplan has no stages: {path}")
    return Gameplan(
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        stages=stages,
    )


def fingerprint_stage(url: str, gameplan: Gameplan, stage: Stage) -> str:
    payload: dict[str, Any] = {
        "url": url.rstrip("/"),
        "gameplan": gameplan.name,
        "stage": stage.name,
        "wordlist": stage.wordlist,
        "extensions": sorted(stage.extensions),
        "recursion": stage.recursion,
        "depth": stage.depth,
        "status_codes": sorted(stage.status_codes),
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
