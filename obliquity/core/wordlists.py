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
        name="hashcat-best66-rules",
        description="hashcat's best66.rule (current upstream successor to best64.rule)",
        category="crack-rules",
        url="https://raw.githubusercontent.com/hashcat/hashcat/master/rules/best66.rule",
        match_suffix="hashcat/rules/best66.rule",
    ),
    WordlistEntry(
        name="hashcat-best64-rules",
        description="hashcat's classic best64.rule (from the v6.2.6 release; the widely-referenced ruleset)",
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
]

# Larger/technology-specific collections that don't fit a single well-known
# file well enough to auto-install. Surfaced as links, not downloaded.
EXTERNAL_SOURCES = [
    ("Full SecLists repository", "https://github.com/danielmiessler/SecLists"),
    ("Assetnote technology-specific wordlists", "https://wordlists.assetnote.io/"),
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
