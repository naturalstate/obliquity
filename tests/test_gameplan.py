from unittest import TestCase

from obliquity.core.gameplan import find_builtin_gameplan, load_gameplan


class SmokeGameplanTests(TestCase):
    def test_smoke_wordlist_resolves_next_to_profile(self) -> None:
        gameplan = load_gameplan(find_builtin_gameplan("smoke-test"))

        self.assertEqual(len(gameplan.stages), 1)
        self.assertTrue(gameplan.stages[0].wordlist.endswith("smoke-test.txt"))
