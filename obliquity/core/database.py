from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    root_dir TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    profile TEXT DEFAULT 'generic',
    server TEXT,
    tech TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, url),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    host_id INTEGER NOT NULL,
    gameplan_name TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    command TEXT NOT NULL,
    raw_output_path TEXT,
    json_output_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    exit_code INTEGER,
    error TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    host_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    path TEXT,
    status_code INTEGER,
    content_length INTEGER,
    words INTEGER,
    lines INTEGER,
    redirect TEXT,
    source TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, host_id, url, status_code, content_length),
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_project(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()


def create_project(conn: sqlite3.Connection, name: str, root_dir: Path) -> sqlite3.Row:
    root_dir.mkdir(parents=True, exist_ok=True)
    conn.execute("INSERT INTO projects(name, root_dir) VALUES(?, ?)", (name, str(root_dir)))
    conn.commit()
    project = get_project(conn, name)
    if project is None:
        raise RuntimeError("Project creation failed")
    return project


def add_host(
    conn: sqlite3.Connection,
    project_id: int,
    url: str,
    profile: str = "generic",
    server: str | None = None,
    tech: str | None = None,
    notes: str | None = None,
) -> sqlite3.Row:
    conn.execute(
        """
        INSERT OR IGNORE INTO hosts(project_id, url, profile, server, tech, notes)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (project_id, url, profile, server, tech, notes),
    )
    conn.commit()
    host = conn.execute(
        "SELECT * FROM hosts WHERE project_id = ? AND url = ?", (project_id, url)
    ).fetchone()
    if host is None:
        raise RuntimeError("Host creation failed")
    return host


def list_hosts(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM hosts WHERE project_id = ? ORDER BY url", (project_id,)))


def update_host(
    conn: sqlite3.Connection,
    project_id: int,
    url: str,
    *,
    new_url: str | None = None,
    profile: str | None = None,
    server: str | None = None,
    tech: str | None = None,
    notes: str | None = None,
) -> Optional[sqlite3.Row]:
    host = get_host(conn, project_id, url)
    if host is None:
        return None

    final_url = new_url if new_url is not None else host["url"]
    final_profile = profile if profile is not None else host["profile"]
    final_server = server if server is not None else host["server"]
    final_tech = tech if tech is not None else host["tech"]
    final_notes = notes if notes is not None else host["notes"]

    conn.execute(
        """
        UPDATE hosts
        SET url = ?, profile = ?, server = ?, tech = ?, notes = ?
        WHERE project_id = ? AND url = ?
        """,
        (final_url, final_profile, final_server, final_tech, final_notes, project_id, url),
    )
    conn.commit()
    return get_host(conn, project_id, final_url)


def delete_host(conn: sqlite3.Connection, project_id: int, url: str) -> bool:
    cur = conn.execute("DELETE FROM hosts WHERE project_id = ? AND url = ?", (project_id, url))
    conn.commit()
    return cur.rowcount > 0


def get_host(conn: sqlite3.Connection, project_id: int, url: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM hosts WHERE project_id = ? AND url = ?", (project_id, url)
    ).fetchone()


def get_run_by_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs WHERE fingerprint = ?", (fingerprint,)).fetchone()


def create_or_update_run(
    conn: sqlite3.Connection,
    project_id: int,
    host_id: int,
    gameplan_name: str,
    stage_name: str,
    fingerprint: str,
    command: str,
    raw_output_path: str,
    json_output_path: str,
    status: str = "pending",
) -> sqlite3.Row:
    conn.execute(
        """
        INSERT INTO runs(project_id, host_id, gameplan_name, stage_name, fingerprint, command,
                         raw_output_path, json_output_path, status)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            command=excluded.command,
            raw_output_path=excluded.raw_output_path,
            json_output_path=excluded.json_output_path
        """,
        (project_id, host_id, gameplan_name, stage_name, fingerprint, command, raw_output_path, json_output_path, status),
    )
    conn.commit()
    run = get_run_by_fingerprint(conn, fingerprint)
    if run is None:
        raise RuntimeError("Run creation failed")
    return run


def mark_run_started(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute(
        "UPDATE runs SET status = 'running', started_at = CURRENT_TIMESTAMP, error = NULL WHERE id = ?",
        (run_id,),
    )
    conn.commit()


def mark_run_finished(conn: sqlite3.Connection, run_id: int, exit_code: int, status: str, error: str | None = None) -> None:
    conn.execute(
        """
        UPDATE runs
        SET status = ?, finished_at = CURRENT_TIMESTAMP, exit_code = ?, error = ?
        WHERE id = ?
        """,
        (status, exit_code, error, run_id),
    )
    conn.commit()


def insert_findings(conn: sqlite3.Connection, findings: Iterable[dict]) -> int:
    count = 0
    for item in findings:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO findings(
                run_id, project_id, host_id, url, path, status_code, content_length,
                words, lines, redirect, source
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("run_id"),
                item.get("project_id"),
                item.get("host_id"),
                item.get("url"),
                item.get("path"),
                item.get("status_code"),
                item.get("content_length"),
                item.get("words"),
                item.get("lines"),
                item.get("redirect"),
                item.get("source"),
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


def get_findings(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT f.*, h.url AS host_url, r.stage_name, r.gameplan_name
            FROM findings f
            JOIN hosts h ON h.id = f.host_id
            JOIN runs r ON r.id = f.run_id
            WHERE f.project_id = ?
            ORDER BY h.url, f.status_code, f.url
            """,
            (project_id,),
        )
    )


def get_runs(conn: sqlite3.Connection, project_id: int, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return list(conn.execute("SELECT * FROM runs WHERE project_id = ? AND status = ? ORDER BY id", (project_id, status)))
    return list(conn.execute("SELECT * FROM runs WHERE project_id = ? ORDER BY id", (project_id,)))
