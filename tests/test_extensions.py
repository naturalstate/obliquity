import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.core.extensions import (
    EXTENSION_SETS,
    analyze_wordlist,
    expand_extensions,
    wordlist_has_extensions,
)
from obliquity.core.gameplan import extension_conflicts, load_gameplan


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ExpandExtensionsTests(TestCase):
    def test_named_sets_expand(self) -> None:
        self.assertEqual(expand_extensions("low"), EXTENSION_SETS["low"])
        self.assertEqual(expand_extensions("MEDIUM"), EXTENSION_SETS["medium"])
        self.assertIn("war", expand_extensions("high"))

    def test_literal_list_passes_through_and_strips_dots(self) -> None:
        self.assertEqual(expand_extensions(["php", ".bak"]), ["php", "bak"])

    def test_none_is_empty(self) -> None:
        self.assertEqual(expand_extensions(None), [])

    def test_unknown_set_raises(self) -> None:
        with self.assertRaises(ValueError):
            expand_extensions("gigantic")


class AnalyzeWordlistTests(TestCase):
    def test_directory_list_has_no_extensions(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "dirs.txt"
            _write(p, ["admin", "login", "backup", "config", "api"])
            a = analyze_wordlist(p)
            self.assertTrue(a.exists)
            self.assertEqual(a.line_count, 5)
            self.assertFalse(a.has_extensions)
            self.assertEqual(a.extension_ratio, 0.0)

    def test_files_list_detected_including_compound(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "files.txt"
            _write(p, ["index.php", "admin.php", "backup.tar.gz", ".htaccess", "robots.txt"])
            a = analyze_wordlist(p)
            self.assertTrue(a.has_extensions)
            self.assertEqual(a.extension_ratio, 1.0)
            exts = {ext for ext, _ in a.top_extensions}
            self.assertIn("php", exts)
            self.assertIn("tar.gz", exts)

    def test_comments_and_blanks_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "mixed.txt"
            _write(p, ["# a comment", "", "admin", "index.php"])
            a = analyze_wordlist(p)
            self.assertEqual(a.line_count, 2)  # comment + blank excluded

    def test_version_numbers_are_not_extensions(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "versions.txt"
            _write(p, ["v1.0", "v2.3", "release1.5", "api"])
            a = analyze_wordlist(p)
            self.assertFalse(a.has_extensions)  # ".0"/".3" are not known extensions

    def test_missing_file(self) -> None:
        a = analyze_wordlist("/no/such/wordlist.txt")
        self.assertFalse(a.exists)
        self.assertFalse(wordlist_has_extensions("/no/such/wordlist.txt"))


class ExtensionConflictTests(TestCase):
    def test_conflict_flagged_only_for_extensioned_wordlist(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = root / "files.txt"
            dirs = root / "dirs.txt"
            _write(files, ["index.php", "admin.php", "config.bak"])
            _write(dirs, ["admin", "login", "api"])
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "name": "t",
                "description": "",
                "stages": [
                    {"name": "bad", "wordlist": str(files), "extensions": ["php"]},
                    {"name": "ok-dirs", "wordlist": str(dirs), "extensions": ["php"]},
                    {"name": "ok-no-ext", "wordlist": str(files), "extensions": []},
                ],
            }), encoding="utf-8")
            gp = load_gameplan(plan)
            conflicts = extension_conflicts(gp)
            names = [name for name, _, _ in conflicts]
            self.assertEqual(names, ["bad"])  # only the extensioned wordlist + appended exts

    def test_named_set_expands_on_load(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = root / "dirs.txt"
            _write(dirs, ["admin", "login"])
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "name": "t",
                "description": "",
                "stages": [{"name": "s", "wordlist": str(dirs), "extensions": "low"}],
            }), encoding="utf-8")
            gp = load_gameplan(plan)
            self.assertEqual(gp.stages[0].extensions, EXTENSION_SETS["low"])
