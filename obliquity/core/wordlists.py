from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class WordlistEntry:
    name: str
    description: str
    category: str  # "bust", "crack-wordlist", "crack-rules"
    url: str
    # Suffix that appears at the end of the absolute paths our built-in
    # gameplan/crackplan JSON files use (e.g. "/usr/share/seclists/<suffix>").
    # Also doubles as this entry's storage path under wordlists_root().
    match_suffix: str
    archive: str | None = None  # None or "tar.gz"
    # For an archive, the member path to extract (relative to archive root).
    archive_member: str | None = None


# Assetnote's httparchive_* wordlists are regenerated monthly and their
# filenames carry the snapshot date. Bump this to pull a newer snapshot (the
# latest date is listed at https://wordlists.assetnote.io/).
ASSETNOTE_SNAPSHOT = "2026_08_27"


# A curated set of the wordlists Obliquity's own built-in profiles reference,
# plus a few other well-known ones. Not an attempt to mirror all of SecLists --
# see EXTERNAL_SOURCES below for pointers to the larger catalogs.
WORDLIST_CATALOG: list[WordlistEntry] = [
    WordlistEntry(
        name="seclists-common",
        description="SecLists Discovery/Web-Content/common.txt -- small, fast first pass",
        category="bust",
        url="https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/common.txt",
        match_suffix="Discovery/Web-Content/common.txt",
    ),
    WordlistEntry(
        name="seclists-big",
        description="SecLists Discovery/Web-Content/big.txt -- larger general-purpose list",
        category="bust",
        url="https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/big.txt",
        match_suffix="Discovery/Web-Content/big.txt",
    ),
    WordlistEntry(
        name="seclists-raft-medium-directories",
        description="SecLists raft-medium-directories.txt",
        category="bust",
        url="https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/raft-medium-directories.txt",
        match_suffix="Discovery/Web-Content/raft-medium-directories.txt",
    ),
    WordlistEntry(
        name="seclists-raft-large-directories",
        description="SecLists raft-large-directories.txt",
        category="bust",
        url="https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/raft-large-directories.txt",
        match_suffix="Discovery/Web-Content/raft-large-directories.txt",
    ),
    WordlistEntry(
        name="seclists-dirbuster-medium",
        description="SecLists DirBuster-2007 directory-list-2.3-medium.txt",
        category="bust",
        url="https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/DirBuster-2007_directory-list-2.3-medium.txt",
        match_suffix="Discovery/Web-Content/DirBuster-2007_directory-list-2.3-medium.txt",
    ),
    WordlistEntry(
        name="rockyou",
        description="rockyou.txt -- ~14M leaked passwords, the default crack wordlist (~50MB download, ~133MB extracted)",
        category="crack-wordlist",
        url="https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Leaked-Databases/rockyou.txt.tar.gz",
        match_suffix="Passwords/Leaked-Databases/rockyou.txt",
        archive="tar.gz",
        archive_member="rockyou.txt",
    ),
    WordlistEntry(
        name="hashcat-best64-rules",
        description="hashcat's best64.rule (ships with stable hashcat / Kali at /usr/share/hashcat/rules/)",
        category="crack-rules",
        url="https://raw.githubusercontent.com/hashcat/hashcat/v6.2.6/rules/best64.rule",
        match_suffix="hashcat/rules/best64.rule",
    ),
    WordlistEntry(
        name="onerule-all",
        description="OneRuleToRuleThemAll.rule -- popular high-coverage rule (stealthsploit)",
        category="crack-rules",
        url="https://raw.githubusercontent.com/stealthsploit/Optimised-hashcat-Rule/master/OneRuleToRuleThemAll.rule",
        match_suffix="hashcat/rules/OneRuleToRuleThemAll.rule",
    ),
    WordlistEntry(
        name="onerule-still",
        description="OneRuleToRuleThemStill.rule -- optimised successor to OneRuleToRuleThemAll (stealthsploit)",
        category="crack-rules",
        url="https://raw.githubusercontent.com/stealthsploit/OneRuleToRuleThemStill/main/OneRuleToRuleThemStill.rule",
        match_suffix="hashcat/rules/OneRuleToRuleThemStill.rule",
    ),
    # --- Assetnote wordlists (wordlists.assetnote.io) -----------------------
    # A first batch, ~3 per section; the rest can be added over time. The
    # httparchive_* files are regenerated monthly, so their filename carries a
    # date -- bump ASSETNOTE_SNAPSHOT below to refresh to a newer snapshot.
    # Section: manual (stable filenames)
    WordlistEntry(
        name="assetnote-raft-large-directories",
        description="Assetnote manual raft-large-directories (canonical raft source; ~62k dirs)",
        category="bust",
        url="https://wordlists-cdn.assetnote.io/data/manual/raft-large-directories.txt",
        match_suffix="assetnote/raft-large-directories.txt",
    ),
    WordlistEntry(
        name="assetnote-raft-large-files",
        description="Assetnote manual raft-large-files (file names for content discovery)",
        category="bust",
        url="https://wordlists-cdn.assetnote.io/data/manual/raft-large-files.txt",
        match_suffix="assetnote/raft-large-files.txt",
    ),
    WordlistEntry(
        name="assetnote-bak",
        description="Assetnote manual bak.txt -- backup/old file names",
        category="bust",
        url="https://wordlists-cdn.assetnote.io/data/manual/bak.txt",
        match_suffix="assetnote/bak.txt",
    ),
    # Section: automated (HTTP Archive, monthly-dated -- see ASSETNOTE_SNAPSHOT)
    WordlistEntry(
        name="assetnote-parameters",
        description=f"Assetnote httparchive top-1M parameter names ({ASSETNOTE_SNAPSHOT}) -- ideal for fuzz",
        category="fuzz",
        url=f"https://wordlists-cdn.assetnote.io/data/automated/httparchive_parameters_top_1m_{ASSETNOTE_SNAPSHOT}.txt",
        match_suffix="assetnote/httparchive_parameters_top_1m.txt",
    ),
    WordlistEntry(
        name="assetnote-api-routes",
        description=f"Assetnote httparchive API routes ({ASSETNOTE_SNAPSHOT}) -- API endpoint discovery",
        category="fuzz",
        url=f"https://wordlists-cdn.assetnote.io/data/automated/httparchive_apiroutes_{ASSETNOTE_SNAPSHOT}.txt",
        match_suffix="assetnote/httparchive_apiroutes.txt",
    ),
    WordlistEntry(
        name="assetnote-directories",
        description=f"Assetnote httparchive top-1M directories ({ASSETNOTE_SNAPSHOT}) -- large real-world dir list",
        category="bust",
        url=f"https://wordlists-cdn.assetnote.io/data/automated/httparchive_directories_1m_{ASSETNOTE_SNAPSHOT}.txt",
        match_suffix="assetnote/httparchive_directories_1m.txt",
    ),
    # Section: kiterunner (only the plain swagger list is usable without the
    # kiterunner tool; the .kite.tar.gz route DBs need kiterunner itself)
    WordlistEntry(
        name="assetnote-swagger",
        description="Assetnote kiterunner swagger-wordlist -- OpenAPI/Swagger endpoint names",
        category="bust",
        url="https://wordlists-cdn.assetnote.io/data/kiterunner/swagger-wordlist.txt",
        match_suffix="assetnote/swagger-wordlist.txt",
    ),
]

# Larger/technology-specific collections that don't fit a single well-known
# file well enough to auto-install. Surfaced as links, not downloaded.
EXTERNAL_SOURCES = [
    ("Full SecLists repository", "https://github.com/danielmiessler/SecLists"),
    ("Assetnote wordlists (catalog has a starter set; browse the rest)", "https://wordlists.assetnote.io/"),
    ("Assetnote technology-specific lists (per-framework paths; large)", "https://wordlists-cdn.assetnote.io/data/technologies/"),
    ("Grab every Assetnote list at once",
     "wget -r --no-parent -R 'index.html*' https://wordlists-cdn.assetnote.io/data/ -nH -e robots=off"),
]


def catalog_by_name(name: str) -> WordlistEntry | None:
    for entry in WORDLIST_CATALOG:
        if entry.name == name:
            return entry
    return None


def wordlists_root() -> Path:
    return Path(os.environ.get("OBLIQUITY_HOME", Path.home() / ".obliquity")) / "wordlists"


def installed_path(entry: WordlistEntry) -> Path:
    return wordlists_root() / entry.match_suffix


def is_installed(entry: WordlistEntry) -> bool:
    path = installed_path(entry)
    return path.exists() and path.stat().st_size > 0


def resolve_path(path_str: str) -> str:
    """If `path_str` doesn't exist but matches a catalog entry we've already
    downloaded, return our local copy instead. Otherwise return unchanged."""
    if Path(path_str).exists():
        return path_str
    for entry in WORDLIST_CATALOG:
        if path_str.endswith(entry.match_suffix) and is_installed(entry):
            return str(installed_path(entry))
    return path_str


def download_entry(entry: WordlistEntry, *, progress_callback: ProgressCallback | None = None) -> Path:
    destination = installed_path(entry)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        download_path = Path(tmp) / "download"
        with urllib.request.urlopen(entry.url) as response, download_path.open("wb") as handle:
            total = response.length
            downloaded = 0
            while chunk := response.read(1 << 16):
                handle.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)

        if entry.archive == "tar.gz":
            with tarfile.open(download_path, "r:gz") as tar:
                member = entry.archive_member or destination.name
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ValueError(f"'{member}' not found inside archive from {entry.url}")
                with destination.open("wb") as handle:
                    shutil.copyfileobj(extracted, handle)
        else:
            shutil.move(str(download_path), str(destination))

    return destination
