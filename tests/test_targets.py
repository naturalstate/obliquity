from unittest import TestCase

from obliquity.core.targets import (
    normalize_target,
    parse_targets,
    read_target_file,
    split_inline_targets,
)


class NormalizeTargetTests(TestCase):
    def test_bare_host_defaults_to_https(self) -> None:
        self.assertEqual(normalize_target("example.com"),
                         ("https://example.com", "https://example.com"))

    def test_keeps_scheme_and_port(self) -> None:
        self.assertEqual(normalize_target("http://10.0.0.5:8080"),
                         ("http://10.0.0.5:8080", "http://10.0.0.5:8080"))

    def test_path_is_preserved_and_not_slash_normalized(self) -> None:
        host_key, base_url = normalize_target("https://ex.com/dir1/dir2/")
        self.assertEqual(host_key, "https://ex.com")
        self.assertEqual(base_url, "https://ex.com/dir1/dir2/")

    def test_dir_without_trailing_slash_stays_as_given(self) -> None:
        _, base_url = normalize_target("ex.com/dir")
        self.assertEqual(base_url, "https://ex.com/dir")

    def test_same_host_different_paths_share_host_key(self) -> None:
        a = normalize_target("ex.com/a/")
        b = normalize_target("ex.com/b/")
        self.assertEqual(a[0], b[0])            # same host_key
        self.assertNotEqual(a[1], b[1])         # distinct base_url

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_target("   ")


class ReadTargetFileTests(TestCase):
    def test_ignores_blanks_and_comments_and_trims(self) -> None:
        text = "# a comment\n\n  https://a.com/  \nb.com\n#trailing\n"
        self.assertEqual(read_target_file(text), ["https://a.com/", "b.com"])


class SplitInlineTests(TestCase):
    def test_splits_and_trims_dropping_empties(self) -> None:
        self.assertEqual(split_inline_targets(" a , b ,, c "), ["a", "b", "c"])


class ParseTargetsTests(TestCase):
    def test_dedups_on_base_url_preserving_order(self) -> None:
        specs = parse_targets(["ex.com", "https://ex.com", "b.com", "ex.com"])
        base_urls = [b for _, b in specs]
        self.assertEqual(base_urls, ["https://ex.com", "https://b.com"])

    def test_same_host_different_dirs_are_separate_units(self) -> None:
        specs = parse_targets(["ex.com/", "ex.com/admin/", "ex.com/"])
        self.assertEqual([b for _, b in specs],
                         ["https://ex.com/", "https://ex.com/admin/"])
        # both register under one host
        self.assertEqual({h for h, _ in specs}, {"https://ex.com"})
