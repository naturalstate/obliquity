import json
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from obliquity.cli import bust_completed_runs, maybe_warn_and_escalate_bust
from obliquity.core.database import add_host, connect, create_project
from obliquity.core.gameplan import Gameplan, Stage
from obliquity.core.runner import run_gameplan


def _run_to_completion(conn, project, host, gameplan) -> None:
    def fake_run(command, raw_output, progress_callback):
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"url": host["url"] + "/x", "status": 200}) + "\n")
        return 0, None

    with patch("obliquity.core.runner.require_feroxbuster"), patch(
        "obliquity.core.runner.run_command", side_effect=fake_run
    ):
        run_gameplan(conn, project, host, gameplan)


class BustCompletedRunsTests(TestCase):
    def test_returns_none_when_not_yet_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])

            self.assertIsNone(bust_completed_runs(conn, project, host, gameplan))

    def test_returns_runs_once_every_stage_completed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])

            _run_to_completion(conn, project, host, gameplan)

            completed = bust_completed_runs(conn, project, host, gameplan)
            self.assertIsNotNone(completed)
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0]["status"], "completed")


class MaybeWarnAndEscalateTests(TestCase):
    def test_noninteractive_bypasses_prompt_entirely(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])
            _run_to_completion(conn, project, host, gameplan)

            args = Namespace(force=False, dry_run=False)
            with patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as fake_input:
                result = maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)

            fake_input.assert_not_called()
            self.assertIs(result, gameplan)

    def test_force_bypasses_prompt_entirely(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])
            _run_to_completion(conn, project, host, gameplan)

            args = Namespace(force=True, dry_run=False)
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input") as fake_input:
                result = maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)

            fake_input.assert_not_called()
            self.assertIs(result, gameplan)

    def test_not_yet_completed_bypasses_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])

            args = Namespace(force=False, dry_run=False)
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input") as fake_input:
                result = maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)

            fake_input.assert_not_called()
            self.assertIs(result, gameplan)

    def test_declining_everything_dies(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="not-escalatable", description="", stages=[Stage(name="only", wordlist="words.txt")])
            _run_to_completion(conn, project, host, gameplan)

            args = Namespace(force=False, dry_run=False)
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"):
                with self.assertRaises(SystemExit):
                    maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)

    def test_accepting_rerun_sets_force_true(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "acme", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="not-escalatable", description="", stages=[Stage(name="only", wordlist="words.txt")])
            _run_to_completion(conn, project, host, gameplan)

            args = Namespace(force=False, dry_run=False)
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="y"):
                result = maybe_warn_and_escalate_bust(conn, project, host, gameplan, args)

            self.assertIs(result, gameplan)
            self.assertTrue(args.force)
