from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.core.database import (
    add_host,
    connect,
    create_project,
    delete_project,
    get_project,
    list_hosts,
    list_projects,
)


class ListProjectsTests(TestCase):
    def test_empty_when_no_projects(self) -> None:
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "obliquity.db")
            self.assertEqual(list_projects(conn), [])

    def test_lists_projects_sorted_with_host_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            b = create_project(conn, "bravo", root / "bravo")
            create_project(conn, "alpha", root / "alpha")
            add_host(conn, b["id"], "https://one.test")
            add_host(conn, b["id"], "https://two.test")

            rows = list_projects(conn)
            names = [r["name"] for r in rows]
            self.assertEqual(names, ["alpha", "bravo"])  # sorted by name
            by_name = {r["name"]: r for r in rows}
            self.assertEqual(by_name["bravo"]["host_count"], 2)
            self.assertEqual(by_name["alpha"]["host_count"], 0)
            self.assertEqual(by_name["bravo"]["run_count"], 0)
            self.assertEqual(by_name["bravo"]["job_count"], 0)


class DeleteProjectTests(TestCase):
    def test_delete_removes_project_and_cascades_to_hosts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "victim", root / "victim")
            add_host(conn, p["id"], "https://a.test")
            add_host(conn, p["id"], "https://b.test")
            self.assertEqual(len(list_hosts(conn, p["id"])), 2)

            self.assertTrue(delete_project(conn, p["id"]))
            self.assertIsNone(get_project(conn, "victim"))
            # FK ON DELETE CASCADE should have removed the hosts too
            self.assertEqual(list_hosts(conn, p["id"]), [])

    def test_delete_missing_project_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "obliquity.db")
            self.assertFalse(delete_project(conn, 999))
