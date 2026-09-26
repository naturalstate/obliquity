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
    set_project_default_gameplan,
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


class DefaultGameplanTests(TestCase):
    def test_new_project_has_no_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            self.assertIsNone(p["default_bust_gameplan"])
            self.assertIsNone(p["default_fuzz_gameplan"])
            self.assertIsNone(p["default_crackplan"])

    def test_set_and_clear_each_tool_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")

            set_project_default_gameplan(conn, p["id"], "bust", "generic-deep")
            set_project_default_gameplan(conn, p["id"], "fuzz", "api-request-quick")
            set_project_default_gameplan(conn, p["id"], "crack", "rules-basic")
            set_project_default_gameplan(conn, p["id"], "brute", "common-creds")
            refreshed = get_project(conn, "acme")
            self.assertEqual(refreshed["default_bust_gameplan"], "generic-deep")
            self.assertEqual(refreshed["default_fuzz_gameplan"], "api-request-quick")
            self.assertEqual(refreshed["default_crackplan"], "rules-basic")
            self.assertEqual(refreshed["default_bruteplan"], "common-creds")

            set_project_default_gameplan(conn, p["id"], "crack", None)
            self.assertIsNone(get_project(conn, "acme")["default_crackplan"])
            # clearing one tool leaves the others untouched
            self.assertEqual(get_project(conn, "acme")["default_bust_gameplan"], "generic-deep")


class RequireHostTests(TestCase):
    def test_single_host_used_automatically(self) -> None:
        from obliquity.cli import require_host
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            add_host(conn, p["id"], "https://only.test")
            self.assertEqual(require_host(conn, p, None)["url"], "https://only.test")

    def test_multiple_hosts_default_to_first(self) -> None:
        from obliquity.cli import require_host
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            add_host(conn, p["id"], "https://first.test")
            add_host(conn, p["id"], "https://second.test")
            # picks the first rather than erroring
            self.assertEqual(require_host(conn, p, None)["url"], "https://first.test")

    def test_scheme_less_target_resolves_to_existing_https_host(self) -> None:
        from obliquity.cli import require_host
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            add_host(conn, p["id"], "https://scanme.test")
            # a stale bare value should match the https host, not create a dup
            self.assertEqual(require_host(conn, p, "scanme.test")["url"], "https://scanme.test")
            self.assertEqual(len(list_hosts(conn, p["id"])), 1)

    def test_unknown_target_is_auto_added(self) -> None:
        from obliquity.cli import require_host
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            host = require_host(conn, p, "newhost.test")  # not present -> added, https-normalized
            self.assertEqual(host["url"], "https://newhost.test")
            self.assertEqual(len(list_hosts(conn, p["id"])), 1)


class NormalizeCrackTargetTests(TestCase):
    def test_lone_positional_becomes_job_when_not_a_project(self) -> None:
        from argparse import Namespace
        from obliquity.cli import normalize_crack_target
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "obliquity.db")
            create_project(conn, "lab", Path(tmp) / "lab")
            args = Namespace(project="md5", job=None)  # 'md5' is a job, not a project
            normalize_crack_target(conn, args)
            self.assertEqual(args.job, "md5")
            self.assertIsNone(args.project)

    def test_real_project_positional_is_left_alone(self) -> None:
        from argparse import Namespace
        from obliquity.cli import normalize_crack_target
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "obliquity.db")
            create_project(conn, "lab", Path(tmp) / "lab")
            args = Namespace(project="lab", job=None)
            normalize_crack_target(conn, args)
            self.assertEqual(args.project, "lab")
            self.assertIsNone(args.job)


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
