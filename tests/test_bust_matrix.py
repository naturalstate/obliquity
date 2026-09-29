import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from obliquity.core.database import add_host, connect, create_project
from obliquity.core.gameplan import Gameplan, Stage
from obliquity.core.runner import run_gameplan, stage_paths


def _fake_run(command, raw_output, progress_callback=None, abort_check=None):
    # write one finding to the --output JSON so parse_json_output records it
    out = Path(command[command.index("--output") + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"url": "http://x/hit", "status": 200}) + "\n", encoding="utf-8")
    return 0, None


class MatrixTargetTests(TestCase):
    def _setup(self, tmp):
        root = Path(tmp)
        conn = connect(root / "o.db")
        project = create_project(conn, "acme", root / "proj")
        host = add_host(conn, project["id"], "http://ex.com")
        gameplan = Gameplan(name="gp", description="", stages=[
            Stage(name="s1", wordlist="w.txt"),
            Stage(name="s2", wordlist="w.txt"),
        ])
        return conn, project, host, gameplan

    def test_base_url_overrides_scan_url_in_command(self) -> None:
        seen = []

        def capture(command, raw_output, progress_callback=None, abort_check=None):
            seen.append(command[command.index("--url") + 1])
            return _fake_run(command, raw_output)

        with TemporaryDirectory() as tmp:
            conn, project, host, gameplan = self._setup(tmp)
            with patch("obliquity.core.runner.require_feroxbuster"), \
                 patch("obliquity.core.runner.run_command", side_effect=capture):
                run_gameplan(conn, project, host, gameplan, base_url="http://ex.com/admin/")
        self.assertTrue(seen and all(u == "http://ex.com/admin/" for u in seen))

    def test_two_dirs_same_host_are_distinct_runs_and_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            conn, project, host, gameplan = self._setup(tmp)
            with patch("obliquity.core.runner.require_feroxbuster"), \
                 patch("obliquity.core.runner.run_command", side_effect=_fake_run):
                r1 = run_gameplan(conn, project, host, gameplan, base_url="http://ex.com/a/")
                r2 = run_gameplan(conn, project, host, gameplan, base_url="http://ex.com/b/")

            # 2 stages x 2 targets = 4 completed runs
            ran = [x for x in (r1 + r2) if x.get("action") == "ran"]
            self.assertEqual(len(ran), 4)
            self.assertTrue(all(x["status"] == "completed" for x in ran))

            # distinct output directories per base URL
            raw_a, _ = stage_paths(project, host, gameplan, "s1", url_override="http://ex.com/a/")
            raw_b, _ = stage_paths(project, host, gameplan, "s1", url_override="http://ex.com/b/")
            self.assertNotEqual(raw_a.parent, raw_b.parent)

    def test_resume_skips_completed_cells(self) -> None:
        with TemporaryDirectory() as tmp:
            conn, project, host, gameplan = self._setup(tmp)
            with patch("obliquity.core.runner.require_feroxbuster"), \
                 patch("obliquity.core.runner.run_command", side_effect=_fake_run):
                run_gameplan(conn, project, host, gameplan, base_url="http://ex.com/a/")
                # second run of the same target: every cell already completed
                again = run_gameplan(conn, project, host, gameplan, base_url="http://ex.com/a/")
        self.assertTrue(again and all(x.get("action") == "skipped" for x in again))
