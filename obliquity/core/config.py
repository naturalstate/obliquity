from __future__ import annotations

import json
import os
from pathlib import Path


def config_path() -> Path:
    return Path(os.environ.get("OBLIQUITY_HOME", Path.home() / ".obliquity")) / "config.json"


def _read() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def active_project() -> str | None:
    return _read().get("active_project")


def set_active_project(name: str) -> None:
    data = _read()
    data["active_project"] = name
    _write(data)


def clear_active_project() -> None:
    data = _read()
    data.pop("active_project", None)
    _write(data)
