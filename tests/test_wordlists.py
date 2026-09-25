import tarfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from obliquity.core.wordlists import (
    WORDLIST_CATALOG,
    WordlistEntry,
    catalog_by_name,
    download_entry,
    installed_path,
    is_installed,
    resolve_path,
)


class CatalogSanityTests(TestCase):
    def test_entry_names_are_unique(self) -> None:
        names = [entry.name for entry in WORDLIST_CATALOG]
        self.assertEqual(len(names), len(set(names)))

    def test_catalog_by_name_finds_known_entry(self) -> None:
        self.assertIsNotNone(catalog_by_name("seclists-common"))

    def test_catalog_by_name_returns_none_for_unknown(self) -> None:
        self.assertIsNone(catalog_by_name("not-a-real-entry"))

    def test_all_urls_are_https(self) -> None:
        for entry in WORDLIST_CATALOG:
            self.assertTrue(entry.url.startswith("https://"), entry.name)

    def test_match_suffixes_are_unique(self) -> None:
        suffixes = [entry.match_suffix for entry in WORDLIST_CATALOG]
        self.assertEqual(len(suffixes), len(set(suffixes)))

    def test_assetnote_entries_present_and_dated_url_matches_snapshot(self) -> None:
        from obliquity.core.wordlists import ASSETNOTE_SNAPSHOT
        assetnote = [e for e in WORDLIST_CATALOG if e.name.startswith("assetnote-")]
        self.assertGreaterEqual(len(assetnote), 7)
        params = catalog_by_name("assetnote-parameters")
        self.assertIsNotNone(params)
        # the dated httparchive URL must use the single snapshot constant
        self.assertIn(ASSETNOTE_SNAPSHOT, params.url)
        self.assertIn("wordlists-cdn.assetnote.io", params.url)


class _FakeResponse:
    def __init__(self, data: bytes):
        self._buf = BytesIO(data)
        self.length = len(data)

    def read(self, n):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ResolvePathTests(TestCase):
    def test_existing_path_returned_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            real = Path(tmp) / "words.txt"
            real.write_text("a\nb\n")
            self.assertEqual(resolve_path(str(real)), str(real))

    def test_missing_path_falls_back_to_downloaded_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OBLIQUITY_HOME": tmp}):
                entry = catalog_by_name("seclists-common")
                cached = installed_path(entry)
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text("admin\nlogin\n")

                resolved = resolve_path("/usr/share/seclists/Discovery/Web-Content/common.txt")
                self.assertEqual(resolved, str(cached))

    def test_missing_path_without_cache_returned_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OBLIQUITY_HOME": tmp}):
                original = "/usr/share/seclists/Discovery/Web-Content/common.txt"
                self.assertEqual(resolve_path(original), original)


class DownloadEntryTests(TestCase):
    def test_plain_file_download_writes_destination(self) -> None:
        entry = WordlistEntry(
            name="test-plain",
            description="test",
            category="bust",
            url="https://example.invalid/words.txt",
            match_suffix="Discovery/Web-Content/words.txt",
        )
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OBLIQUITY_HOME": tmp}), patch(
                "obliquity.core.wordlists.urllib.request.urlopen",
                return_value=_FakeResponse(b"admin\nlogin\n"),
            ):
                destination = download_entry(entry)
                self.assertTrue(is_installed(entry))
                self.assertEqual(destination.read_text(), "admin\nlogin\n")

    def test_tar_gz_archive_extracts_named_member(self) -> None:
        entry = WordlistEntry(
            name="test-archive",
            description="test",
            category="crack-wordlist",
            url="https://example.invalid/words.tar.gz",
            match_suffix="Passwords/Leaked-Databases/words.txt",
            archive="tar.gz",
            archive_member="words.txt",
        )

        archive_bytes = BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
            payload = b"password123\nletmein\n"
            info = tarfile.TarInfo(name="words.txt")
            info.size = len(payload)
            tar.addfile(info, BytesIO(payload))
        archive_bytes.seek(0)

        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OBLIQUITY_HOME": tmp}), patch(
                "obliquity.core.wordlists.urllib.request.urlopen",
                return_value=_FakeResponse(archive_bytes.getvalue()),
            ):
                destination = download_entry(entry)

            self.assertEqual(destination.read_text(), "password123\nletmein\n")
