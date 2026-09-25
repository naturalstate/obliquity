from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.core.explorer import (
    WordlistRef,
    collect_gameplans,
    collect_wordlists,
    find_similar,
    gameplan_detail_lines,
    wordlist_detail_lines,
)


class CollectTests(TestCase):
    def setUp(self):
        self.gameplans = collect_gameplans()
        self.wordlists = collect_wordlists(self.gameplans)

    def test_all_four_pillars_present(self):
        tools = {g.tool for g in self.gameplans}
        self.assertEqual(tools, {"bust", "fuzz", "crack", "brute"})

    def test_wordlists_nonempty_and_deduped_by_name(self):
        names = [w.name for w in self.wordlists]
        self.assertTrue(names)
        self.assertEqual(len(names), len(set(names)))  # no dupes

    def test_wordlist_cross_links_to_gameplans(self):
        # the password top-100 list is referenced by the brute plans
        ref = next((w for w in self.wordlists if w.name == "10-million-password-list-top-100.txt"), None)
        self.assertIsNotNone(ref)
        self.assertTrue(any(r.startswith("brute/") for r in ref.referenced_by))

    def test_gameplan_detail_has_stages_and_run_line(self):
        gp = next(g for g in self.gameplans if g.tool == "bust")
        lines = gameplan_detail_lines(gp)
        self.assertTrue(any("Stages" in ln for ln in lines))
        self.assertTrue(any("obliquity bust run" in ln for ln in lines))


class DetailTests(TestCase):
    def test_missing_wordlist_detail_is_graceful(self):
        ref = WordlistRef(name="nope.txt", path="/no/such/nope.txt", description="x", category="web-content")
        lines = wordlist_detail_lines(ref, [ref])
        self.assertTrue(any("NOT installed" in ln for ln in lines))

    def test_present_wordlist_shows_length_head_tail(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "files.txt"
            p.write_text("\n".join(f"file{i}.php" for i in range(50)) + "\n", encoding="utf-8")
            ref = WordlistRef(name="files.txt", path=str(p))
            lines = wordlist_detail_lines(ref, [ref], sample=5)
            text = "\n".join(lines)
            self.assertIn("Length: 50", text)
            self.assertIn("Head:", text)
            self.assertIn("Tail:", text)
            self.assertIn("Contains extensions: yes", text)

    def test_find_similar_matches_stem_and_category(self):
        a = WordlistRef(name="raft-medium-files.txt", path="x", category="web-content-files")
        b = WordlistRef(name="raft-large-files.txt", path="y", category="web-content-files")
        c = WordlistRef(name="rockyou.txt", path="z", category="passwords")
        sim = find_similar(a, [a, b, c])
        names = [s.name for s in sim]
        self.assertIn("raft-large-files.txt", names)
        self.assertNotIn("rockyou.txt", names)
