from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.cli import apply_stored_options, build_parser
from obliquity.core.database import (
    connect,
    create_project,
    get_project,
    get_project_options,
    set_project_option,
    unset_project_option,
)


class ProjectOptionDbTests(TestCase):
    def _project(self, tmp):
        root = Path(tmp)
        conn = connect(root / "obliquity.db")
        p = create_project(conn, "acme", root / "acme")
        return conn, p

    def test_set_get_unset(self):
        with TemporaryDirectory() as tmp:
            conn, p = self._project(tmp)
            self.assertEqual(get_project_options(conn, p["id"], "fuzz"), {})
            set_project_option(conn, p["id"], "fuzz", "endpoint", "/search")
            set_project_option(conn, p["id"], "fuzz", "endpoint", "/login")  # upsert
            self.assertEqual(get_project_options(conn, p["id"], "fuzz"), {"endpoint": "/login"})
            self.assertTrue(unset_project_option(conn, p["id"], "fuzz", "endpoint"))
            self.assertFalse(unset_project_option(conn, p["id"], "fuzz", "endpoint"))
            self.assertEqual(get_project_options(conn, p["id"], "fuzz"), {})

    def test_options_are_per_tool(self):
        with TemporaryDirectory() as tmp:
            conn, p = self._project(tmp)
            set_project_option(conn, p["id"], "fuzz", "endpoint", "/x")
            set_project_option(conn, p["id"], "bust", "threads", "40")
            self.assertEqual(get_project_options(conn, p["id"], "fuzz"), {"endpoint": "/x"})
            self.assertEqual(get_project_options(conn, p["id"], "bust"), {"threads": "40"})


class ApplyStoredOptionsTests(TestCase):
    def test_fills_unset_args_and_respects_explicit(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            set_project_option(conn, p["id"], "fuzz", "endpoint", "/search")
            set_project_option(conn, p["id"], "fuzz", "host", "https://app.acme.test")
            project = get_project(conn, "acme")

            # nothing on the CLI -> filled from stored
            args = Namespace(url=None, endpoint=None, template=None, request=None, gameplan=None)
            apply_stored_options(conn, project, "fuzz", args)
            self.assertEqual(args.endpoint, "/search")
            self.assertEqual(args.url, "https://app.acme.test")

            # explicit flag wins
            args2 = Namespace(url=None, endpoint="/admin", template=None, request=None, gameplan=None)
            apply_stored_options(conn, project, "fuzz", args2)
            self.assertEqual(args2.endpoint, "/admin")

    def test_int_option_coerced(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            p = create_project(conn, "acme", root / "acme")
            set_project_option(conn, p["id"], "bust", "threads", "40")
            project = get_project(conn, "acme")
            args = Namespace(url=None, gameplan=None, threads=None, rate_limit=None, proxy=None)
            apply_stored_options(conn, project, "bust", args)
            self.assertEqual(args.threads, 40)
            self.assertIsInstance(args.threads, int)


class OptionsCliParseTests(TestCase):
    def test_set_unset_options_parse(self):
        from obliquity.cli import cmd_set, cmd_unset, cmd_options
        a = build_parser().parse_args(["set", "fuzz", "endpoint", "/search"])
        self.assertIs(a.func, cmd_set)
        self.assertEqual((a.tool, a.key, a.value), ("fuzz", "endpoint", "/search"))
        self.assertIs(build_parser().parse_args(["unset", "fuzz", "endpoint"]).func, cmd_unset)
        self.assertIs(build_parser().parse_args(["options", "fuzz"]).func, cmd_options)
