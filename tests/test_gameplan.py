from unittest import TestCase

from obliquity.core.gameplan import find_builtin_gameplan, list_builtin_gameplans, load_gameplan


class SmokeGameplanTests(TestCase):
    def test_smoke_wordlist_resolves_next_to_profile(self) -> None:
        gameplan = load_gameplan(find_builtin_gameplan("smoke-test"))

        self.assertEqual(len(gameplan.stages), 1)
        self.assertTrue(gameplan.stages[0].wordlist.endswith("smoke-test.txt"))


class AllBuiltinGameplansLoadTests(TestCase):
    def test_every_builtin_gameplan_loads_without_error(self) -> None:
        for path in list_builtin_gameplans():
            gameplan = load_gameplan(path)
            self.assertTrue(gameplan.stages, f"{path} has no stages")


class GenericDeepTests(TestCase):
    def test_generic_deep_does_not_repeat_generic_standard_wordlists(self) -> None:
        deep = load_gameplan(find_builtin_gameplan("generic-deep"))
        standard = load_gameplan(find_builtin_gameplan("generic-standard"))

        deep_wordlist_names = {w.rsplit("/", 1)[-1] for w in (s.wordlist for s in deep.stages)}
        standard_wordlist_names = {w.rsplit("/", 1)[-1] for w in (s.wordlist for s in standard.stages)}

        self.assertEqual(deep_wordlist_names & standard_wordlist_names, set())
