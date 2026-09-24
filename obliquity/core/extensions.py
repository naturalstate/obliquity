"""Extension Intelligence.

Two jobs, both about not wasting requests on the wrong extensions:

1. Reusable, intensity-tiered extension *sets* (low/medium/high) so a gameplan
   stage can say ``"extensions": "medium"`` instead of copy-pasting the same
   list into every profile.

2. Detecting whether a wordlist already carries extensions. Appending
   ``--extensions php`` to a wordlist whose entries are already
   ``index.php``/``admin.php`` makes feroxbuster request ``index.php.php`` --
   wasted requests that also miss nothing useful. We detect that case so we
   can warn (and so the wordlist analyzer / TUI can describe a list honestly).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Intensity-tiered extension sets, referenced by name from a gameplan stage's
# "extensions" field. Each tier is a superset of the one before it.
_LOW = ["html", "htm", "php", "asp", "aspx", "jsp", "txt"]
_MEDIUM = _LOW + ["js", "json", "xml", "bak", "old", "zip", "config", "conf", "inc", "sql", "log"]
_HIGH = _MEDIUM + [
    "tar", "tar.gz", "gz", "tgz", "7z", "rar", "swp", "save", "orig", "tmp",
    "cache", "yml", "yaml", "env", "ini", "pem", "key", "war", "jar",
    "do", "action", "cgi", "pl", "py", "rb", "sh", "cfm", "phtml", "php5", "phps",
]
EXTENSION_SETS: dict[str, list[str]] = {"low": _LOW, "medium": _MEDIUM, "high": _HIGH}

# Extensions we recognize when deciding whether a wordlist entry "has an
# extension". Deliberately broader than what we'd ever fuzz for (includes
# images/docs/styles) so detection doesn't misjudge a media-heavy list, while
# still ignoring things like "v1.0" or "2.3" that merely contain a dot.
KNOWN_EXTENSIONS: frozenset[str] = frozenset(
    _HIGH
    + [
        "css", "ico", "png", "jpg", "jpeg", "gif", "svg", "webp", "pdf", "doc",
        "docx", "xls", "xlsx", "ppt", "pptx", "csv", "md", "rtf", "woff", "woff2",
        "ttf", "eot", "map", "ts", "tsx", "jsx", "vue", "scss", "less", "wasm",
        "htaccess", "htpasswd", "dll", "exe", "bin", "class", "jspx", "asmx",
        "ashx", "axd", "svc", "wsdl", "properties", "toml", "lock", "gitignore",
        "dockerfile", "bat", "ps1", "vbs", "twig", "erb", "ejs", "hbs",
    ]
)


def expand_extensions(value) -> list[str]:
    """A stage's ``extensions`` may be a literal list, or the name of a tier
    ('low'/'medium'/'high'). Return the concrete list either way."""
    if value is None:
        return []
    if isinstance(value, str):
        key = value.strip().lower()
        if key in EXTENSION_SETS:
            return list(EXTENSION_SETS[key])
        raise ValueError(
            f"unknown extension set '{value}'. Use a list, or one of: "
            f"{', '.join(sorted(EXTENSION_SETS))}"
        )
    return [str(x).lstrip(".") for x in value]


def _entry_extension(entry: str) -> str | None:
    """Return the (lowercased) known extension of a wordlist entry, or None.
    Handles compound extensions like ``backup.tar.gz``."""
    name = entry.strip().strip("/")
    if not name or name.startswith("#"):
        return None
    base = name.rsplit("/", 1)[-1]  # only the last path segment carries the extension
    # try a two-part compound extension first (tar.gz), then a single one
    parts = base.split(".")
    if len(parts) >= 3:
        compound = ".".join(parts[-2:]).lower()
        if compound in KNOWN_EXTENSIONS:
            return compound
    if len(parts) >= 2:
        ext = parts[-1].lower()
        if ext in KNOWN_EXTENSIONS:
            return ext
    return None


@dataclass
class WordlistAnalysis:
    path: str
    exists: bool
    line_count: int = 0
    byte_size: int = 0
    sampled: int = 0
    extensioned: int = 0
    top_extensions: list[tuple[str, int]] = None  # type: ignore[assignment]
    preview: list[str] = None  # type: ignore[assignment]

    @property
    def extension_ratio(self) -> float:
        return (self.extensioned / self.sampled) if self.sampled else 0.0

    @property
    def has_extensions(self) -> bool:
        # A wordlist "has extensions baked in" when a meaningful share of its
        # entries already end in a known extension. 0.30 keeps a handful of
        # incidental robots.txt-style entries in a directory list from tripping
        # the flag, while catching genuine *-files.txt lists (near 1.0).
        return self.extension_ratio >= 0.30


def analyze_wordlist(path: str | os.PathLike, *, sample_limit: int = 2000, preview_lines: int = 10) -> WordlistAnalysis:
    """Sample a wordlist and report its size, whether it carries extensions,
    the most common ones, and a short preview. Sampling (not reading the whole
    file) keeps this instant even on raft-large-sized lists."""
    p = Path(path)
    if not p.exists():
        return WordlistAnalysis(path=str(p), exists=False, top_extensions=[], preview=[])

    byte_size = p.stat().st_size
    line_count = 0
    sampled = 0
    extensioned = 0
    ext_counts: dict[str, int] = {}
    preview: list[str] = []

    with p.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            stripped = line.strip()
            is_content = bool(stripped) and not stripped.startswith("#")
            if is_content:
                line_count += 1
                if len(preview) < preview_lines:
                    preview.append(stripped)
                if sampled < sample_limit:
                    sampled += 1
                    ext = _entry_extension(stripped)
                    if ext:
                        extensioned += 1
                        ext_counts[ext] = ext_counts.get(ext, 0) + 1
            # once we've sampled enough AND filled the preview, we still need
            # the true line count, so keep iterating but skip the per-line work
    top = sorted(ext_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return WordlistAnalysis(
        path=str(p),
        exists=True,
        line_count=line_count,
        byte_size=byte_size,
        sampled=sampled,
        extensioned=extensioned,
        top_extensions=top,
        preview=preview,
    )


def wordlist_has_extensions(path: str | os.PathLike) -> bool:
    return analyze_wordlist(path, preview_lines=0).has_extensions
