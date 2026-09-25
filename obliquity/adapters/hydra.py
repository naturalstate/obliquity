from __future__ import annotations

import json
import shutil
from pathlib import Path

from obliquity.core.loginplan import LoginStage

# hydra services Obliquity knows about. http-*-form services also need a
# form_spec on the job (the "path:body-with-^USER^-^PASS^:failure-condition"
# string hydra requires); the others are plain host/service attacks.
FORM_SERVICES = {"http-get-form", "http-post-form", "https-get-form", "https-post-form"}
KNOWN_SERVICES = FORM_SERVICES | {
    "ssh", "ftp", "ftps", "smb", "rdp", "telnet", "http-get", "http-post",
    "https-get", "https-post", "mysql", "postgres", "vnc", "smtp", "pop3",
    "imap", "ldap2", "ldap3", "mssql", "redis", "rlogin", "snmp",
}


# Per-service defaults: standard port + a recommended built-in loginplan (which
# in turn points at service-appropriate user/pass lists). Applied when a user
# adds a login job / runs without specifying a port or gameplan. Non-form
# services get an auto-filled port; form services carry the port in the URL.
SERVICE_PROFILES = {
    "ssh": {"port": 22, "loginplan": "ssh-default"},
    "ftp": {"port": 21, "loginplan": "ftp-default"},
    "ftps": {"port": 990, "loginplan": "ftp-default"},
    "smb": {"port": 445, "loginplan": "smb-default"},
    "rdp": {"port": 3389, "loginplan": "common-creds"},
    "telnet": {"port": 23, "loginplan": "common-creds"},
    "mysql": {"port": 3306, "loginplan": "common-creds"},
    "postgres": {"port": 5432, "loginplan": "common-creds"},
    "mssql": {"port": 1433, "loginplan": "common-creds"},
    "vnc": {"port": 5900, "loginplan": "common-creds"},
    "smtp": {"port": 25, "loginplan": "common-creds"},
    "pop3": {"port": 110, "loginplan": "common-creds"},
    "imap": {"port": 143, "loginplan": "common-creds"},
    "ldap2": {"port": 389, "loginplan": "common-creds"},
    "ldap3": {"port": 389, "loginplan": "common-creds"},
    "redis": {"port": 6379, "loginplan": "common-creds"},
    "rlogin": {"port": 513, "loginplan": "common-creds"},
    "snmp": {"port": 161, "loginplan": "common-creds"},
    "http-get": {"port": 80, "loginplan": "common-creds"},
    "http-post": {"port": 80, "loginplan": "common-creds"},
    "http-get-form": {"port": 80, "loginplan": "common-creds"},
    "http-post-form": {"port": 80, "loginplan": "common-creds"},
    "https-get-form": {"port": 443, "loginplan": "common-creds"},
    "https-post-form": {"port": 443, "loginplan": "common-creds"},
}


def service_default_port(service: str) -> int | None:
    prof = SERVICE_PROFILES.get(service)
    return prof["port"] if prof else None


def service_default_loginplan(service: str) -> str | None:
    prof = SERVICE_PROFILES.get(service)
    return prof["loginplan"] if prof else None


class HydraMissing(RuntimeError):
    pass


def require_hydra() -> None:
    if shutil.which("hydra") is None:
        raise HydraMissing("hydra (thc-hydra) was not found in PATH. Install thc-hydra first, then rerun Obliquity.")


def build_command(
    job: dict,
    stage: LoginStage,
    output: Path,
    *,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Assemble a hydra invocation for one stage against one login job.

    hydra shape:  hydra [creds] [opts] -o out -b json <target> <service> [module-args]
    """
    service = job["service"]
    if service not in KNOWN_SERVICES:
        raise ValueError(f"unsupported hydra service: {service} (known: {', '.join(sorted(KNOWN_SERVICES))})")

    cmd = ["hydra"]

    # credentials: single value (-l/-p) or list (-L/-P)
    if stage.username:
        cmd += ["-l", stage.username]
    else:
        cmd += ["-L", stage.userlist]
    if stage.password:
        cmd += ["-p", stage.password]
    else:
        cmd += ["-P", stage.passlist]

    if job.get("port"):
        cmd += ["-s", str(job["port"])]
    if stage.tasks:
        cmd += ["-t", str(stage.tasks)]
    if stage.stop_on_first_valid:
        cmd += ["-f"]

    # machine-readable output for parsing, alongside the raw text log.
    cmd += ["-o", str(output), "-b", "json"]

    cmd += stage.extra_args
    cmd += extra_args or []

    # target then service, then any module argument (the form spec for
    # http-*-form services, or free-form module_args on the job).
    cmd += [job["target"], service]
    module = job.get("form_spec") if service in FORM_SERVICES else job.get("module_args")
    if service in FORM_SERVICES and not job.get("form_spec"):
        raise ValueError(
            f"service '{service}' requires a form_spec on the job, e.g. "
            f"\"/login:user=^USER^&pass=^PASS^:F=invalid\""
        )
    if module:
        cmd.append(module)
    elif job.get("module_args") and service not in FORM_SERVICES:
        cmd.append(job["module_args"])
    return cmd


def _parse_json(text: str) -> list[dict]:
    """hydra -b json writes a JSON document with a 'results' array of
    {host, port, service, login, password}. Tolerate minor format drift."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    results = data.get("results") if isinstance(data, dict) else None
    creds: list[dict] = []
    for row in results or []:
        if not isinstance(row, dict):
            continue
        login = row.get("login")
        password = row.get("password")
        if login is None and password is None:
            continue
        creds.append({
            "username": login,
            "password": password,
            "target": row.get("host"),
            "service": row.get("service"),
        })
    return creds


def _parse_text(text: str) -> list[dict]:
    """Fallback for hydra's plain text output lines, e.g.
    ``[22][ssh] host: 10.0.0.5   login: root   password: toor``."""
    creds: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if "login:" not in line or "password:" not in line:
            continue
        try:
            host = None
            if "host:" in line:
                host = line.split("host:", 1)[1].split("login:", 1)[0].strip()
            login = line.split("login:", 1)[1].split("password:", 1)[0].strip()
            password = line.split("password:", 1)[1].strip()
        except IndexError:
            continue
        creds.append({"username": login, "password": password, "target": host, "service": None})
    return creds


def parse_output(output: Path, *, run_id: int, project_id: int, job_id: int, service: str, target: str, source: str) -> list[dict]:
    if not output.exists():
        return []
    text = output.read_text(encoding="utf-8", errors="replace")
    creds = _parse_json(text) or _parse_text(text)
    results: list[dict] = []
    for c in creds:
        results.append({
            "run_id": run_id,
            "project_id": project_id,
            "job_id": job_id,
            "service": c.get("service") or service,
            "target": c.get("target") or target,
            "username": c.get("username"),
            "password": c.get("password"),
            "source": source,
        })
    return results
