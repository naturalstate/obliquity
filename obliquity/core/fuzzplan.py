from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FuzzPlan:
    name: str
    description: str
    operation_category: str
    wordlist: str
    mode: str = "clusterbomb"
    autocalibrate: bool = True


def fuzz_profiles_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fuzz_profiles"


def find_fuzz_plan(name: str) -> Path:
    candidate = fuzz_profiles_dir() / f"{name}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Unknown fuzz gameplan '{name}'. Expected {candidate}")
    return candidate


def list_fuzz_plans() -> list[Path]:
    return sorted(fuzz_profiles_dir().glob("*.json"))


def load_fuzz_plan(path: Path) -> FuzzPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    wordlist = Path(data["wordlist"])
    if not wordlist.is_absolute():
        wordlist = (path.parent / wordlist).resolve()
    return FuzzPlan(
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        operation_category=data["operation_category"],
        wordlist=str(wordlist),
        mode=data.get("mode", "clusterbomb"),
        autocalibrate=bool(data.get("autocalibrate", True)),
    )
