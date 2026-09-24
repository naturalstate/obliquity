from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obliquity.core.wordlists import resolve_path


@dataclass
class LoginStage:
    """One hydra pass. Provide either a single username/password or a
    userlist/passlist (or a mix, e.g. one known user against a passlist)."""
    name: str
    username: str | None = None
    userlist: str | None = None
    password: str | None = None
    passlist: str | None = None
    tasks: int | None = None            # hydra -t (parallel connections)
    stop_on_first_valid: bool = False   # hydra -f (stop after first valid pair)
    extra_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (self.username or self.userlist):
            raise ValueError(f"login stage '{self.name}' needs a username or a userlist")
        if not (self.password or self.passlist):
            raise ValueError(f"login stage '{self.name}' needs a password or a passlist")


@dataclass
class LoginPlan:
    name: str
    description: str
    stages: list[LoginStage]


def _resolve(base: Path, value: str) -> str:
    p = Path(value)
    if not p.is_absolute():
        value = str((base / p).resolve())
    return resolve_path(value)


def load_loginplan(path: Path) -> LoginPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    stages = [LoginStage(**stage) for stage in data.get("stages", [])]
    for stage in stages:
        if stage.userlist:
            stage.userlist = _resolve(path.parent, stage.userlist)
        if stage.passlist:
            stage.passlist = _resolve(path.parent, stage.passlist)
    if not stages:
        raise ValueError(f"Login plan has no stages: {path}")
    return LoginPlan(
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        stages=stages,
    )


def fingerprint_login_stage(job_key: str, service: str, plan: LoginPlan, stage: LoginStage, *, project_id: int) -> str:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "job": job_key,
        "service": service,
        "loginplan": plan.name,
        "stage": stage.name,
        "username": stage.username,
        "userlist": stage.userlist,
        "password": stage.password,
        "passlist": stage.passlist,
        "tasks": stage.tasks,
        "stop_on_first_valid": stage.stop_on_first_valid,
        "extra_args": stage.extra_args,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def login_profiles_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "login_profiles"


def find_builtin_loginplan(name: str) -> Path:
    candidate = login_profiles_dir() / f"{name}.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Unknown login gameplan '{name}'. Expected {candidate}")
    return candidate


def list_builtin_loginplans() -> list[Path]:
    return sorted(login_profiles_dir().glob("*.json"))
