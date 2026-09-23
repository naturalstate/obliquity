from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obliquity.core.wordlists import resolve_path


@dataclass
class CrackStage:
    name: str
    attack_mode: str  # "dictionary" or "mask"
    wordlist: str | None = None
    rules: str | None = None
    mask: str | None = None
    extra_args: list[str] = field(default_factory=list)
    estimated_minutes: int | None = None

    def __post_init__(self) -> None:
        if self.attack_mode == "dictionary" and not self.wordlist:
            raise ValueError(f"crack stage '{self.name}' uses attack_mode=dictionary but has no wordlist")
        if self.attack_mode == "mask" and not self.mask:
            raise ValueError(f"crack stage '{self.name}' uses attack_mode=mask but has no mask")


@dataclass
class CrackPlan:
    name: str
    description: str
    stages: list[CrackStage]


def load_crackplan(path: Path) -> CrackPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    stages = [CrackStage(**stage) for stage in data.get("stages", [])]
    for stage in stages:
        if stage.wordlist:
            wordlist = Path(stage.wordlist)
            if not wordlist.is_absolute():
                stage.wordlist = str((path.parent / wordlist).resolve())
            stage.wordlist = resolve_path(stage.wordlist)
        if stage.rules:
            rules = Path(stage.rules)
            if not rules.is_absolute():
                stage.rules = str((path.parent / rules).resolve())
            stage.rules = resolve_path(stage.rules)
    if not stages:
        raise ValueError(f"Crack plan has no stages: {path}")
    return CrackPlan(
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        stages=stages,
    )


def fingerprint_crack_stage(hash_file: str, hash_type: int, plan: CrackPlan, stage: CrackStage, *, project_id: int) -> str:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "hash_file": hash_file,
        "hash_type": hash_type,
        "crackplan": plan.name,
        "stage": stage.name,
        "attack_mode": stage.attack_mode,
        "wordlist": stage.wordlist,
        "rules": stage.rules,
        "mask": stage.mask,
        "extra_args": stage.extra_args,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def crack_profiles_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "crack_profiles"


def find_builtin_crackplan(name: str) -> Path:
    candidate = crack_profiles_dir() / f"{name}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Unknown crack gameplan '{name}'. Expected {candidate}")
    return candidate


def list_builtin_crackplans() -> list[Path]:
    return sorted(crack_profiles_dir().glob("*.json"))
