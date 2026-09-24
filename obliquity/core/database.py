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

CREATE TABLE IF NOT EXISTS crack_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT,
    hash_file TEXT NOT NULL,
    hash_type INTEGER NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, hash_file),
    UNIQUE(project_id, name),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crack_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    crackplan_name TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    command TEXT NOT NULL,
    raw_output_path TEXT,
    result_output_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    exit_code INTEGER,
    error TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES crack_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cracked_hashes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    hash TEXT NOT NULL,
    plaintext TEXT NOT NULL,
    source TEXT,
    cracked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, job_id, hash),
    FOREIGN KEY(run_id) REFERENCES crack_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES crack_jobs(id) ON DELETE CASCADE
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_column(conn, "runs", "tool", "TEXT NOT NULL DEFAULT 'feroxbuster'")
    _ensure_column(conn, "runs", "operation_category", "TEXT NOT NULL DEFAULT 'content-path'")
    _ensure_column(conn, "runs", "operation_scope", "TEXT")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()


def get_project(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()


def list_projects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT p.*,
                (SELECT COUNT(*) FROM hosts h WHERE h.project_id = p.id) AS host_count,
                (SELECT COUNT(*) FROM crack_jobs j WHERE j.project_id = p.id) AS job_count,
                (SELECT COUNT(*) FROM runs r WHERE r.project_id = p.id) AS run_count
            FROM projects p
            ORDER BY p.name
            """
        )
    )


def create_project(conn: sqlite3.Connection, name: str, root_dir: Path) -> sqlite3.Row:
    root_dir.mkdir(parents=True, exist_ok=True)
    conn.execute("INSERT INTO projects(name, root_dir) VALUES(?, ?)", (name, str(root_dir)))
    conn.commit()
    project = get_project(conn, name)
    if project is None:
        raise RuntimeError("Project creation failed")
    return project


def delete_project(conn: sqlite3.Connection, project_id: int) -> bool:
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return cur.rowcount > 0


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
    tool: str = "feroxbuster",
    operation_category: str = "content-path",
    operation_scope: str | None = None,
) -> sqlite3.Row:
    conn.execute(
        """
        INSERT INTO runs(project_id, host_id, gameplan_name, stage_name, fingerprint, command,
                         raw_output_path, json_output_path, status, tool, operation_category, operation_scope)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            command=excluded.command,
            raw_output_path=excluded.raw_output_path,
            json_output_path=excluded.json_output_path,
            tool=excluded.tool,
            operation_category=excluded.operation_category,
            operation_scope=excluded.operation_scope
        """,
        (
            project_id, host_id, gameplan_name, stage_name, fingerprint, command,
            raw_output_path, json_output_path, status, tool, operation_category, operation_scope,
        ),
    )
    conn.commit()
    run = get_run_by_fingerprint(conn, fingerprint)
    if run is None:
        raise RuntimeError("Run creation failed")
    return run


def mark_run_started(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute(
        """
        UPDATE runs
        SET status = 'running', started_at = CURRENT_TIMESTAMP,
            finished_at = NULL, exit_code = NULL, error = NULL
        WHERE id = ?
        """,
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


def get_coverage(conn: sqlite3.Connection, project_id: int, host_id: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT r.*, h.url AS host_url
        FROM runs r
        JOIN hosts h ON h.id = r.host_id
        WHERE r.project_id = ?
    """
    params: list[object] = [project_id]
    if host_id is not None:
        sql += " AND r.host_id = ?"
        params.append(host_id)
    sql += " ORDER BY h.url, r.operation_category, r.id"
    return list(conn.execute(sql, params))


def add_crack_job(
    conn: sqlite3.Connection,
    project_id: int,
    hash_file: str,
    hash_type: int,
    name: str | None = None,
    notes: str | None = None,
) -> sqlite3.Row:
    conn.execute(
        """
        INSERT OR IGNORE INTO crack_jobs(project_id, hash_file, hash_type, name, notes)
        VALUES(?, ?, ?, ?, ?)
        """,
        (project_id, hash_file, hash_type, name, notes),
    )
    conn.commit()
    job = conn.execute(
        "SELECT * FROM crack_jobs WHERE project_id = ? AND hash_file = ?", (project_id, hash_file)
    ).fetchone()
    if job is None:
        raise RuntimeError("Crack job creation failed")
    return job


def list_crack_jobs(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM crack_jobs WHERE project_id = ? ORDER BY id", (project_id,)))


def get_crack_job(conn: sqlite3.Connection, project_id: int, target: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crack_jobs WHERE project_id = ? AND (name = ? OR hash_file = ?)",
        (project_id, target, target),
    ).fetchone()


def delete_crack_job(conn: sqlite3.Connection, project_id: int, target: str) -> bool:
    cur = conn.execute(
        "DELETE FROM crack_jobs WHERE project_id = ? AND (name = ? OR hash_file = ?)",
        (project_id, target, target),
    )
    conn.commit()
    return cur.rowcount > 0


def get_crack_run_by_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM crack_runs WHERE fingerprint = ?", (fingerprint,)).fetchone()


def create_or_update_crack_run(
    conn: sqlite3.Connection,
    project_id: int,
    job_id: int,
    crackplan_name: str,
    stage_name: str,
    fingerprint: str,
    command: str,
    raw_output_path: str,
    result_output_path: str,
    status: str = "pending",
) -> sqlite3.Row:
    conn.execute(
        """
        INSERT INTO crack_runs(project_id, job_id, crackplan_name, stage_name, fingerprint, command,
                               raw_output_path, result_output_path, status)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            command=excluded.command,
            raw_output_path=excluded.raw_output_path,
            result_output_path=excluded.result_output_path
        """,
        (
            project_id, job_id, crackplan_name, stage_name, fingerprint, command,
            raw_output_path, result_output_path, status,
        ),
    )
    conn.commit()
    run = get_crack_run_by_fingerprint(conn, fingerprint)
    if run is None:
        raise RuntimeError("Crack run creation failed")
    return run


def mark_crack_run_started(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute(
        """
        UPDATE crack_runs
        SET status = 'running', started_at = CURRENT_TIMESTAMP,
            finished_at = NULL, exit_code = NULL, error = NULL
        WHERE id = ?
        """,
        (run_id,),
    )
    conn.commit()


def mark_crack_run_finished(conn: sqlite3.Connection, run_id: int, exit_code: int, status: str, error: str | None = None) -> None:
    conn.execute(
        """
        UPDATE crack_runs
        SET status = ?, finished_at = CURRENT_TIMESTAMP, exit_code = ?, error = ?
        WHERE id = ?
        """,
        (status, exit_code, error, run_id),
    )
    conn.commit()


def insert_cracked_hashes(conn: sqlite3.Connection, results: Iterable[dict]) -> int:
    count = 0
    for item in results:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO cracked_hashes(run_id, project_id, job_id, hash, plaintext, source)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("run_id"),
                item.get("project_id"),
                item.get("job_id"),
                item.get("hash"),
                item.get("plaintext"),
                item.get("source"),
            ),
        )
        count += cur.rowcount
    conn.commit()
    return count


def get_cracked_hashes(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT c.*, j.name AS job_name, j.hash_file, r.stage_name, r.crackplan_name
            FROM cracked_hashes c
            JOIN crack_jobs j ON j.id = c.job_id
            JOIN crack_runs r ON r.id = c.run_id
            WHERE c.project_id = ?
            ORDER BY j.hash_file, c.plaintext
            """,
            (project_id,),
        )
    )


def get_crack_runs(conn: sqlite3.Connection, project_id: int, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return list(conn.execute("SELECT * FROM crack_runs WHERE project_id = ? AND status = ? ORDER BY id", (project_id, status)))
    return list(conn.execute("SELECT * FROM crack_runs WHERE project_id = ? ORDER BY id", (project_id,)))


def sum_findings_for_runs(conn: sqlite3.Connection, run_ids: list[int]) -> int:
    if not run_ids:
        return 0
    placeholders = ",".join("?" for _ in run_ids)
    return conn.execute(f"SELECT COUNT(*) FROM findings WHERE run_id IN ({placeholders})", run_ids).fetchone()[0]


def sum_cracked_for_runs(conn: sqlite3.Connection, run_ids: list[int]) -> int:
    if not run_ids:
        return 0
    placeholders = ",".join("?" for _ in run_ids)
    return conn.execute(f"SELECT COUNT(*) FROM cracked_hashes WHERE run_id IN ({placeholders})", run_ids).fetchone()[0]


def get_history(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    tool: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    # Note: r.id/cr.id are explicitly aliased to run_id. With the JOINs present,
    # SQLite's compound-SELECT ORDER BY resolution collides an unqualified
    # "id" output column with hosts.id/crack_jobs.id from the FROM clause
    # (even though they aren't selected) and refuses to order by it.
    sql = """
        SELECT r.id AS run_id, r.tool, r.gameplan_name, r.stage_name, r.status, r.exit_code,
               r.started_at, r.finished_at, h.url AS target,
               (SELECT COUNT(*) FROM findings f WHERE f.run_id = r.id) AS finding_count
        FROM runs r
        JOIN hosts h ON h.id = r.host_id
        WHERE r.project_id = ?
        UNION ALL
        SELECT cr.id AS run_id, 'hashcat' AS tool, cr.crackplan_name AS gameplan_name, cr.stage_name, cr.status, cr.exit_code,
               cr.started_at, cr.finished_at, COALESCE(j.name, j.hash_file) AS target,
               (SELECT COUNT(*) FROM cracked_hashes ch WHERE ch.run_id = cr.id) AS finding_count
        FROM crack_runs cr
        JOIN crack_jobs j ON j.id = cr.job_id
        WHERE cr.project_id = ?
    """
    params: list[object] = [project_id, project_id]
    if tool:
        sql = f"SELECT * FROM ({sql}) WHERE tool = ?"
        params.append(tool)
    if status:
        sql = f"SELECT * FROM ({sql}) WHERE status = ?"
        params.append(status)
    sql += " ORDER BY started_at DESC, run_id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))
