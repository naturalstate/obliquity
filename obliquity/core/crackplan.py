from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obliquity.core.wordlists import resolve_path


# attack_mode -> the fields it requires. Also the set of modes Obliquity knows.
CRACK_MODE_REQUIREMENTS = {
    "dictionary": ("wordlist",),
    "mask": ("mask",),
    "combinator": ("wordlist", "wordlist2"),
    "hybrid-wordlist-mask": ("wordlist", "mask"),
    "hybrid-mask-wordlist": ("wordlist", "mask"),
}


@dataclass
class CrackStage:
    name: str
    attack_mode: str  # see CRACK_MODE_REQUIREMENTS
    wordlist: str | None = None
    wordlist2: str | None = None  # second wordlist for combinator attacks
    # one rule file, or a list of them to stack (each becomes its own -r);
    # normalized to a list in __post_init__.
    rules: str | list[str] | None = None
    mask: str | None = None
    extra_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.rules, str):
            self.rules = [self.rules]

        if self.attack_mode not in CRACK_MODE_REQUIREMENTS:
            raise ValueError(
                f"crack stage '{self.name}' has unknown attack_mode '{self.attack_mode}' "
                f"(expected one of: {', '.join(sorted(CRACK_MODE_REQUIREMENTS))})"
            )
        for attr in CRACK_MODE_REQUIREMENTS[self.attack_mode]:
            if not getattr(self, attr):
                raise ValueError(
                    f"crack stage '{self.name}' uses attack_mode={self.attack_mode} but has no {attr}"
                )
        # `-r` rules files only apply to straight/dictionary attacks in hashcat;
        # hybrid/combinator use -j/-k (via extra_args) instead.
        if self.rules and self.attack_mode != "dictionary":
            raise ValueError(
                f"crack stage '{self.name}' sets rules, which hashcat only supports with "
                f"attack_mode=dictionary (got {self.attack_mode})"
            )


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
        if stage.wordlist2:
            wordlist2 = Path(stage.wordlist2)
            if not wordlist2.is_absolute():
                stage.wordlist2 = str((path.parent / wordlist2).resolve())
            stage.wordlist2 = resolve_path(stage.wordlist2)
        if stage.rules:
            resolved_rules = []
            for rule in stage.rules:
                rule_path = Path(rule)
                if not rule_path.is_absolute():
                    rule = str((path.parent / rule_path).resolve())
                resolved_rules.append(resolve_path(rule))
            stage.rules = resolved_rules
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
        "wordlist2": stage.wordlist2,
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
