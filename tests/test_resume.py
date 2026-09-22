from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import json

from obliquity.core.database import add_host, connect, create_project, get_findings, get_runs
from obliquity.core.gameplan import Gameplan, Stage
from obliquity.core.runner import run_gameplan


class ResumeTests(TestCase):
    def test_resume_skips_completed_stage_and_retries_interrupted_stage(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            project = create_project(conn, "resume-test", root / "project")
            host = add_host(conn, project["id"], "https://example.com")
            gameplan = Gameplan(
                name="resume-plan",
                description="",
                stages=[
                    Stage(name="first", wordlist="words.txt"),
                    Stage(name="second", wordlist="words.txt"),
                ],
            )

            calls = 0

            def interrupt_second_stage(command, raw_output, progress_callback):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return 0, None
                output = Path(command[command.index("--output") + 1])
                output.write_text(
                    json.dumps({"url": "https://example.com/partial", "status": 200}) + "\n",
                    encoding="utf-8",
                )
                return 130, "interrupted"

            with patch("obliquity.core.runner.require_feroxbuster"), patch(
                "obliquity.core.runner.run_command", side_effect=interrupt_second_stage
            ):
                first_run = run_gameplan(conn, project, host, gameplan)

            self.assertEqual(first_run[0]["status"], "completed")
            self.assertEqual(first_run[1]["status"], "interrupted")
            self.assertEqual([item["url"] for item in get_findings(conn, project["id"])], ["https://example.com/partial"])

            with patch("obliquity.core.runner.require_feroxbuster"), patch(
                "obliquity.core.runner.run_command", return_value=(0, None)
            ) as rerun:
                resumed = run_gameplan(conn, project, host, gameplan)

            self.assertEqual(resumed[0]["action"], "skipped")
            self.assertEqual(resumed[1]["status"], "completed")
            rerun.assert_called_once()
            statuses = [run["status"] for run in get_runs(conn, project["id"])]
            self.assertEqual(statuses, ["completed", "completed"])
            conn.close()

    def test_completed_stage_is_scoped_to_its_project(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = connect(root / "obliquity.db")
            first_project = create_project(conn, "first", root / "first")
            second_project = create_project(conn, "second", root / "second")
            first_host = add_host(conn, first_project["id"], "https://example.com")
            second_host = add_host(conn, second_project["id"], "https://example.com")
            gameplan = Gameplan(
                name="shared-plan",
                description="",
                stages=[Stage(name="only", wordlist="words.txt")],
            )

            with patch("obliquity.core.runner.require_feroxbuster"), patch(
                "obliquity.core.runner.run_command", return_value=(0, None)
            ) as execute:
                first = run_gameplan(conn, first_project, first_host, gameplan)
                second = run_gameplan(conn, second_project, second_host, gameplan)

            self.assertEqual(first[0]["status"], "completed")
            self.assertEqual(second[0]["status"], "completed")
            self.assertEqual(execute.call_count, 2)
            conn.close()
