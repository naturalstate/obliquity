from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolStatus:
    name: str
    required: bool
    path: str | None
    version: str | None

    @property
    def installed(self) -> bool:
        return self.path is not None


CORE_TOOLS = ("feroxbuster", "ffuf", "hashcat", "hydra")
OPTIONAL_TOOLS = ("gobuster", "wfuzz", "john")

VERSION_ARGS = {
    "feroxbuster": ["--version"],
    "ffuf": ["-V"],
    "hashcat": ["--version"],
    # hydra has no --version flag; a bare invocation prints "Hydra v9.x ..."
    # as its first usage line.
    "hydra": [],
    "gobuster": ["version"],
    "wfuzz": ["--version"],
    "john": ["--list=build-info"],
}


def detect_tool(name: str, *, required: bool) -> ToolStatus:
    path = shutil.which(name)
    if path is None:
        return ToolStatus(name, required, None, None)
    version = None
    try:
        proc = subprocess.run(
            [path, *VERSION_ARGS.get(name, ["--version"])],
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = (proc.stdout or proc.stderr).strip().splitlines()
        if output:
            version = re.sub(r"\s+", " ", output[0])[:100]
    except (OSError, subprocess.SubprocessError):
        pass
    return ToolStatus(name, required, path, version)


def inventory_tools() -> list[ToolStatus]:
    return [detect_tool(name, required=True) for name in CORE_TOOLS] + [
        detect_tool(name, required=False) for name in OPTIONAL_TOOLS
    ]
