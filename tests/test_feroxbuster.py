from pathlib import Path
from unittest import TestCase

from obliquity.adapters.feroxbuster import build_command
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
