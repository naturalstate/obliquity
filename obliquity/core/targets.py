"""Target expansion for `bust` -- turning `-iL`/`--targets`/a positional URL into
a normalized, de-duplicated list of scan targets.

A *target* is a base URL: ``scheme://host[:port][/path/]``. The path (if any) is
the directory feroxbuster scans from, so the same host may appear many times with
different paths (the multi-directory case). Splitting a target yields:

- ``host_key`` = ``scheme://netloc`` -- the key a project host is registered under
  (findings/reporting group by host), path stripped.
- ``base_url`` = the full normalized URL incl. path -- the actual scan base and
  part of the run fingerprint, so two directories on one host are distinct runs.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_target(raw: str) -> tuple[str, str]:
    """Return ``(host_key, base_url)`` for a raw target string.

    A scheme-less value defaults to ``https://`` (matching the rest of Obliquity).
    The path is preserved exactly -- ``/dir`` and ``/dir/`` are not the same to
    feroxbuster, so we never add or strip a trailing slash.
    """
    s = raw.strip()
    if not s:
        raise ValueError("empty target")
    if "://" not in s:
        s = "https://" + s
    parts = urlsplit(s)
    if not parts.netloc:
        raise ValueError(f"invalid target: {raw!r}")
    scheme = parts.scheme or "https"
    host_key = urlunsplit((scheme, parts.netloc, "", "", ""))
    base_url = urlunsplit((scheme, parts.netloc, parts.path, "", ""))
    return host_key, base_url


def read_target_file(text: str) -> list[str]:
    """Extract raw target lines from an ``-iL`` file: one per line, blank lines
    and ``#`` comments ignored, surrounding whitespace trimmed."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def split_inline_targets(value: str) -> list[str]:
    """Split a ``--targets "a,b,c"`` value into non-empty, trimmed items."""
    return [item for item in (part.strip() for part in value.split(",")) if item]


def parse_targets(raw_items: list[str]) -> list[tuple[str, str]]:
    """Normalize and de-duplicate raw targets, preserving first-seen order.

    Returns ``[(host_key, base_url), ...]``. Duplicates are compared on the
    normalized ``base_url`` (so ``ex.com`` given twice collapses, but ``ex.com``
    and ``ex.com/dir/`` stay separate)."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for raw in raw_items:
        host_key, base_url = normalize_target(raw)
        if base_url in seen:
            continue
        seen.add(base_url)
        result.append((host_key, base_url))
    return result
