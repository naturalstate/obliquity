import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from obliquity.core.database import add_host, connect, create_project, get_history
from obliquity.core.gameplan import Gameplan, Stage
from obliquity.core.runner import run_gameplan


class HistoryTests(TestCase):
    def test_history_includes_bust_runs_with_target_and_finding_count(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "history-test", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])

            def fake_run(command, raw_output, progress_callback, abort_check=None):
                output = Path(command[command.index("--output") + 1])
                output.write_text(json.dumps({"url": "https://example.com/admin", "status": 200}) + "\n")
                return 0, None

            with patch("obliquity.core.runner.require_feroxbuster"), patch(
                "obliquity.core.runner.run_command", side_effect=fake_run
            ):
                run_gameplan(conn, project, host, gameplan)

            rows = get_history(conn, project["id"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["tool"], "feroxbuster")
            self.assertEqual(rows[0]["target"], "https://example.com")
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(rows[0]["finding_count"], 1)

    def test_history_tool_filter(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "history-test", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(name="plan", description="", stages=[Stage(name="only", wordlist="words.txt")])

            with patch("obliquity.core.runner.require_feroxbuster"), patch(
                "obliquity.core.runner.run_command", return_value=(0, None)
            ):
                run_gameplan(conn, project, host, gameplan)

            self.assertEqual(len(get_history(conn, project["id"], tool="hashcat")), 0)
            self.assertEqual(len(get_history(conn, project["id"], tool="feroxbuster")), 1)

    def test_history_empty_project_returns_empty_list(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "empty", root / "project")
            self.assertEqual(get_history(conn, project["id"]), [])
