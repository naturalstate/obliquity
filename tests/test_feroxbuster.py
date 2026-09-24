from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from obliquity.adapters.feroxbuster import build_command, run_command, terminate_process
from obliquity.core.gameplan import Stage


class BuildCommandTests(TestCase):
    def _stage(self, *, recursion: bool, depth: int | None = None) -> Stage:
        return Stage(
            name="test",
            wordlist="words.txt",
            extensions=[],
            recursion=recursion,
            depth=depth,
            status_codes=[],
            extra_args=[],
        )

    def test_recursion_uses_feroxbuster_default(self) -> None:
        command = build_command(
            "https://example.com", self._stage(recursion=True), Path("results.json")
        )

        self.assertNotIn("--recursive", command)
        self.assertNotIn("--no-recursion", command)
        self.assertNotIn("--depth", command)

    def test_recursive_stage_can_set_depth(self) -> None:
        command = build_command(
            "https://example.com",
            self._stage(recursion=True, depth=2),
            Path("results.json"),
        )

        self.assertNotIn("--recursive", command)
        self.assertNotIn("--no-recursion", command)
        self.assertEqual(command[command.index("--depth") + 1], "2")

    def test_non_recursive_stage_disables_recursion(self) -> None:
        command = build_command(
            "https://example.com", self._stage(recursion=False), Path("results.json")
        )

        self.assertIn("--no-recursion", command)
        self.assertNotIn("--recursive", command)

    def test_collect_extensions_flag_emitted(self) -> None:
        stage = Stage(name="t", wordlist="w.txt", collect_extensions=True)
        command = build_command("https://example.com", stage, Path("r.json"))
        self.assertIn("--collect-extensions", command)

    def test_response_filters_emitted(self) -> None:
        stage = Stage(
            name="t", wordlist="w.txt",
            filter_status=[404, 500], filter_size=[0, 1024],
            filter_words=[10], filter_lines=[3], filter_regex="Not Found",
        )
        command = build_command("https://example.com", stage, Path("r.json"))
        self.assertEqual(command[command.index("--filter-status") + 1], "404,500")
        self.assertEqual(command[command.index("--filter-size") + 1], "0,1024")
        self.assertEqual(command[command.index("--filter-words") + 1], "10")
        self.assertEqual(command[command.index("--filter-lines") + 1], "3")
        self.assertEqual(command[command.index("--filter-regex") + 1], "Not Found")

    def test_no_filters_by_default(self) -> None:
        command = build_command("https://example.com", Stage(name="t", wordlist="w.txt"), Path("r.json"))
        self.assertNotIn("--filter-status", command)
        self.assertNotIn("--filter-regex", command)

    def test_filters_change_fingerprint(self) -> None:
        from obliquity.core.gameplan import Gameplan, fingerprint_stage
        base = Stage(name="t", wordlist="w.txt")
        filtered = Stage(name="t", wordlist="w.txt", filter_status=[404])
        gp = Gameplan(name="g", description="", stages=[base])
        fp1 = fingerprint_stage("https://x", gp, base, project_id=1)
        fp2 = fingerprint_stage("https://x", gp, filtered, project_id=1)
        self.assertNotEqual(fp1, fp2)


class ProcessControlTests(TestCase):
    def test_terminate_process_stops_running_process(self) -> None:
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.return_value = 0

        terminate_process(proc)

        proc.terminate.assert_called_once_with()
        proc.wait.assert_called_once_with(timeout=3)
        proc.kill.assert_not_called()

    def test_terminate_process_kills_process_after_timeout(self) -> None:
        from subprocess import TimeoutExpired

        proc = Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [TimeoutExpired("feroxbuster", 3), 0]

        terminate_process(proc)

        proc.terminate.assert_called_once_with()
        proc.kill.assert_called_once_with()

    def test_keyboard_interrupt_returns_interrupted_exit_code(self) -> None:
        proc = Mock()
        proc.poll.side_effect = KeyboardInterrupt
        proc.returncode = None

        with TemporaryDirectory() as tmp, patch(
            "obliquity.adapters.feroxbuster.subprocess.Popen", return_value=proc
        ), patch("obliquity.adapters.feroxbuster.terminate_process") as terminate:
            code, error = run_command(["feroxbuster"], Path(tmp) / "raw.txt")

        terminate.assert_called_once_with(proc)
        self.assertEqual(code, 130)
        self.assertIn("interrupted", error or "")
