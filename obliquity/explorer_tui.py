"""Curses TUI for the Wordlist Explorer.

Kept out of cli.py so the curses import only happens when the command runs.
The data all comes from obliquity.core.explorer; this module is just a
renderer plus a keyboard loop, with a plain-text fallback for non-TTY /
no-curses environments (e.g. Windows without windows-curses).
"""

from __future__ import annotations

import sys

from obliquity.core.explorer import (
    GameplanRef,
    WordlistRef,
    collect_gameplans,
    collect_wordlists,
    gameplan_detail_lines,
    wordlist_detail_lines,
)

TITLE = "Obliquity Wordlist Explorer"
HELP = "↑/↓ move  ·  PgUp/PgDn scroll details  ·  Home/End  ·  q quit"


def run_explorer() -> None:
    gameplans = collect_gameplans()
    wordlists = collect_wordlists(gameplans)

    try:
        import curses  # noqa: F401
    except ImportError:
        _print_fallback(gameplans, wordlists, reason="curses is not available (on Windows: pip install windows-curses)")
        return
    if not sys.stdout.isatty():
        _print_fallback(gameplans, wordlists, reason="not attached to an interactive terminal")
        return

    import curses
    curses.wrapper(_main_loop, gameplans, wordlists)


def _build_rows(gameplans: list[GameplanRef], wordlists: list[WordlistRef]) -> list[tuple[str, object, str]]:
    rows: list[tuple[str, object, str]] = [("header", None, f"GAMEPLANS ({len(gameplans)})")]
    for gp in gameplans:
        rows.append(("gameplan", gp, f"[{gp.tool}] {gp.name}"))
    rows.append(("header", None, f"WORDLISTS ({len(wordlists)})"))
    for wl in wordlists:
        rows.append(("wordlist", wl, wl.name))
    return rows


def _detail_lines(kind: str, obj: object, wordlists: list[WordlistRef]) -> list[str]:
    if kind == "gameplan":
        return gameplan_detail_lines(obj)  # type: ignore[arg-type]
    return wordlist_detail_lines(obj, wordlists)  # type: ignore[arg-type]


def _main_loop(stdscr, gameplans, wordlists) -> None:
    import curses

    curses.curs_set(0)
    stdscr.keypad(True)
    use_color = curses.has_colors()
    if use_color:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # headers / title
        curses.init_pair(2, curses.COLOR_YELLOW, -1)   # accents

    rows = _build_rows(gameplans, wordlists)
    nav = [i for i, r in enumerate(rows) if r[0] != "header"]
    cur = 0                      # index into nav
    detail_scroll = 0
    detail_cache: dict[int, list[str]] = {}

    def detail_for(row_idx: int) -> list[str]:
        kind, obj, _ = rows[row_idx]
        oid = id(obj)
        if oid not in detail_cache:
            detail_cache[oid] = _detail_lines(kind, obj, wordlists)
        return detail_cache[oid]

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 6 or w < 40:
            _safe_add(stdscr, 0, 0, "Terminal too small -- enlarge the window (q to quit).", w)
            stdscr.refresh()
            if stdscr.getch() in (ord("q"), 27):
                return
            continue

        left_w = min(42, max(24, w // 3))
        list_h = h - 3
        cattr = curses.color_pair(1) if use_color else 0

        # title + help
        _safe_add(stdscr, 0, 0, TITLE.ljust(w), w, curses.A_BOLD | cattr)
        _safe_add(stdscr, 1, 0, HELP, w, curses.A_DIM if hasattr(curses, "A_DIM") else 0)

        selected_row = rows[nav[cur]]

        # keep selection visible: compute a window over rows
        sel_row_idx = nav[cur]
        top = 0
        if sel_row_idx >= list_h:
            top = sel_row_idx - list_h + 1

        # left list
        for screen_line in range(list_h):
            ri = top + screen_line
            if ri >= len(rows):
                break
            kind, _obj, label = rows[ri]
            y = 2 + screen_line
            if kind == "header":
                _safe_add(stdscr, y, 0, label[: left_w - 1], left_w - 1, curses.A_BOLD | cattr)
            else:
                attr = curses.A_REVERSE if ri == sel_row_idx else 0
                text = ("  " + label)[: left_w - 1].ljust(left_w - 1)
                _safe_add(stdscr, y, 0, text, left_w - 1, attr)

        # divider
        for y in range(2, 2 + list_h):
            _safe_add(stdscr, y, left_w - 1, "│", 1)

        # right detail pane
        detail = detail_for(sel_row_idx)
        pane_w = w - left_w - 1
        pane_h = list_h
        max_scroll = max(0, len(detail) - pane_h)
        ds = min(detail_scroll, max_scroll)
        for screen_line in range(pane_h):
            di = ds + screen_line
            if di >= len(detail):
                break
            line = detail[di]
            attr = (curses.A_BOLD | cattr) if di == 0 else 0
            _safe_add(stdscr, 2 + screen_line, left_w + 1, line[:pane_w], pane_w, attr)

        # footer: position + scroll hint
        pos = f"{cur + 1}/{len(nav)}"
        if max_scroll:
            pos += f"   details {ds + 1}-{min(ds + pane_h, len(detail))}/{len(detail)}"
        _safe_add(stdscr, h - 1, 0, pos.ljust(w), w, curses.A_DIM if hasattr(curses, "A_DIM") else 0)

        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return
        elif ch in (curses.KEY_DOWN, ord("j")):
            cur = min(cur + 1, len(nav) - 1)
            detail_scroll = 0
        elif ch in (curses.KEY_UP, ord("k")):
            cur = max(cur - 1, 0)
            detail_scroll = 0
        elif ch in (curses.KEY_NPAGE, ord(" ")):
            detail_scroll = min(detail_scroll + pane_h - 1, max_scroll)
        elif ch in (curses.KEY_PPAGE, ord("b")):
            detail_scroll = max(detail_scroll - (pane_h - 1), 0)
        elif ch in (curses.KEY_HOME, ord("g")):
            cur = 0
            detail_scroll = 0
        elif ch in (curses.KEY_END, ord("G")):
            cur = len(nav) - 1
            detail_scroll = 0


def _safe_add(stdscr, y, x, text, maxlen, attr=0) -> None:
    try:
        stdscr.addnstr(y, x, text, maxlen, attr)
    except Exception:
        pass  # curses raises at the bottom-right corner and on odd resizes; ignore


def _print_fallback(gameplans, wordlists, *, reason: str) -> None:
    print(f"{TITLE} (text mode -- {reason})\n")
    print(f"GAMEPLANS ({len(gameplans)}):")
    for gp in gameplans:
        print(f"  [{gp.tool}] {gp.name} -- {gp.description[:70]}")
    print(f"\nWORDLISTS ({len(wordlists)}):")
    for wl in wordlists:
        used = f"  (used by {len(wl.referenced_by)} gameplan(s))" if wl.referenced_by else ""
        print(f"  {wl.name} -- {wl.description or 'wordlist'}{used}")
    print("\nRun this in an interactive terminal for the full scrollable explorer.")
    print("Inspect a single wordlist any time with: obliquity wordlists inspect <name|path>")
