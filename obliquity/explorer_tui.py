"""TUI backends for the Wordlist Explorer.

Two interactive renderers over the same data (obliquity.core.explorer):

* **curses** -- stdlib, zero-dependency; the default on macOS/Linux.
* **textual** -- cross-platform, works natively on Windows; used when curses
  isn't available (Windows without windows-curses) or when explicitly asked.

Both are imported lazily so neither is pulled in unless it's actually used, and
there's a plain-text fallback for non-TTY / neither-available environments.
"""

from __future__ import annotations

import importlib.util
import platform
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
HELP = "↑/↓ move  ·  Enter load gameplan  ·  PgUp/PgDn details  ·  Home/End  ·  q quit"


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def choose_backend(prefer: str = "auto") -> str:
    """Pick a TUI backend. Returns 'curses', 'textual', or 'text'.

    Order per platform (auto):
      * macOS/Linux: curses (stdlib) -> textual -> text
      * Windows:     curses (only if windows-curses is installed) -> textual -> text
    An explicit preference is honored when that backend is actually usable,
    otherwise it degrades with the same order.
    """
    if not sys.stdout.isatty():
        return "text"

    curses_ok = _has_module("curses")
    textual_ok = _has_module("textual")

    if prefer == "curses" and curses_ok:
        return "curses"
    if prefer == "textual" and textual_ok:
        return "textual"
    if prefer == "text":
        return "text"

    # auto (or an unavailable explicit choice): prefer the zero-dependency
    # curses on POSIX; on Windows curses usually isn't present, so Textual wins.
    if platform.system() == "Windows":
        if curses_ok:
            return "curses"
        if textual_ok:
            return "textual"
        return "text"
    if curses_ok:
        return "curses"
    if textual_ok:
        return "textual"
    return "text"


def run_explorer(prefer: str = "auto", *, on_load=None, project_label: str | None = None) -> None:
    gameplans = collect_gameplans()
    wordlists = collect_wordlists(gameplans)

    backend = choose_backend(prefer)
    if backend == "curses":
        import curses
        curses.wrapper(_main_loop, gameplans, wordlists, on_load, project_label)
    elif backend == "textual":
        _run_textual(gameplans, wordlists, on_load, project_label)
    else:
        if not sys.stdout.isatty():
            reason = "not attached to an interactive terminal"
        elif platform.system() == "Windows":
            reason = "no TUI backend available -- install one with: pip install textual  (or: pip install windows-curses)"
        else:
            reason = "no TUI backend available -- install one with: pip install textual"
        _print_fallback(gameplans, wordlists, reason=reason)


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


def _main_loop(stdscr, gameplans, wordlists, on_load=None, project_label=None) -> None:
    import curses

    curses.curs_set(0)
    stdscr.keypad(True)
    use_color = curses.has_colors()
    if use_color:
        curses.start_color()
        curses.use_default_colors()
        # Prefer true-ish orange/blue/purple on 256-color terminals; fall back
        # to the base 8 elsewhere. Keeps the CLI's cyan/orange/blue feel.
        if curses.COLORS >= 256:
            C_CYAN, C_ORANGE, C_BLUE, C_PURPLE, C_GREEN, C_RED = 44, 208, 39, 141, 42, 203
        else:
            C_CYAN, C_ORANGE, C_BLUE, C_PURPLE, C_GREEN, C_RED = (
                curses.COLOR_CYAN, curses.COLOR_YELLOW, curses.COLOR_BLUE,
                curses.COLOR_MAGENTA, curses.COLOR_GREEN, curses.COLOR_RED,
            )
        curses.init_pair(1, C_CYAN, -1)               # top title
        curses.init_pair(2, curses.COLOR_MAGENTA, -1) # left section headers + divider
        curses.init_pair(3, C_ORANGE, -1)             # detail title / info status / accents
        curses.init_pair(4, C_GREEN, -1)              # success status
        curses.init_pair(5, C_RED, -1)                # error status
        curses.init_pair(6, C_BLUE, -1)               # detail section labels (subtle)
        curses.init_pair(7, C_ORANGE, -1)             # [bust] tag
        curses.init_pair(8, C_PURPLE, -1)             # [fuzz] tag
        curses.init_pair(9, C_GREEN, -1)              # [crack] tag
        curses.init_pair(10, C_RED, -1)               # [brute] tag

    TOOL_PAIR = {"bust": 7, "fuzz": 8, "crack": 9, "brute": 10}

    def cp(n):
        return curses.color_pair(n) if use_color else 0

    dim = curses.A_DIM if hasattr(curses, "A_DIM") else 0

    rows = _build_rows(gameplans, wordlists)
    nav = [i for i, r in enumerate(rows) if r[0] != "header"]
    cur = 0                      # index into nav
    detail_scroll = 0
    detail_cache: dict[int, list[str]] = {}
    status = ""
    status_kind = "info"         # info | ok | err

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

        # title (+ active project) and help
        title = TITLE + (f"   [project: {project_label}]" if project_label else "   [no active project]")
        _safe_add(stdscr, 0, 0, title.ljust(w), w, curses.A_BOLD | cp(1))
        _safe_add(stdscr, 1, 0, HELP, w, dim)

        sel_row_idx = nav[cur]
        top = 0
        if sel_row_idx >= list_h:
            top = sel_row_idx - list_h + 1

        # left list
        for screen_line in range(list_h):
            ri = top + screen_line
            if ri >= len(rows):
                break
            kind, obj, label = rows[ri]
            y = 2 + screen_line
            avail = left_w - 1
            if kind == "header":
                _safe_add(stdscr, y, 0, label[:avail], avail, curses.A_BOLD | cp(2))
            elif ri == sel_row_idx:
                # selected: a clean full-width reverse bar (readable over any tag color)
                text = ("  " + label)[:avail].ljust(avail)
                _safe_add(stdscr, y, 0, text, avail, curses.A_REVERSE | curses.A_BOLD)
            elif kind == "gameplan":
                # "[tool]" in the tool's color, name in default white
                tag = f"[{obj.tool}]"
                _safe_add(stdscr, y, 0, "  ", avail)
                _safe_add(stdscr, y, 2, tag, max(0, avail - 2), curses.A_BOLD | cp(TOOL_PAIR.get(obj.tool, 3)))
                name = " " + obj.name
                nx = 2 + len(tag)
                _safe_add(stdscr, y, nx, name[: max(0, avail - nx)], max(0, avail - nx))
            else:
                text = ("  " + label)[:avail].ljust(avail)
                _safe_add(stdscr, y, 0, text, avail)

        # divider
        for y in range(2, 2 + list_h):
            _safe_add(stdscr, y, left_w - 1, "│", 1, cp(2))

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
            if di == 0:
                attr = curses.A_BOLD | cp(3)                 # title in orange
            elif line.rstrip().endswith(":") and line[:1].strip():
                attr = curses.A_BOLD | cp(6)                 # section labels in blue (subtle)
            else:
                attr = 0
            _safe_add(stdscr, 2 + screen_line, left_w + 1, line[:pane_w], pane_w, attr)

        # footer: status message (if any) else position + scroll hint
        if status:
            scolor = {"ok": cp(4), "err": cp(5)}.get(status_kind, cp(3))
            _safe_add(stdscr, h - 1, 0, status.ljust(w), w, curses.A_BOLD | scolor)
        else:
            pos = f"{cur + 1}/{len(nav)}"
            if max_scroll:
                pos += f"   details {ds + 1}-{min(ds + pane_h, len(detail))}/{len(detail)}"
            _safe_add(stdscr, h - 1, 0, pos.ljust(w), w, dim)

        stdscr.refresh()

        ch = stdscr.getch()
        # any navigation clears a transient status
        if ch in (ord("q"), 27):
            return
        elif ch in (curses.KEY_DOWN, ord("j")):
            cur = (cur + 1) % len(nav); detail_scroll = 0; status = ""   # wrap to top past bottom
        elif ch in (curses.KEY_UP, ord("k")):
            cur = (cur - 1) % len(nav); detail_scroll = 0; status = ""   # wrap to bottom past top
        elif ch in (curses.KEY_NPAGE, ord(" ")):
            detail_scroll = min(detail_scroll + pane_h - 1, max_scroll)
        elif ch in (curses.KEY_PPAGE, ord("b")):
            detail_scroll = max(detail_scroll - (pane_h - 1), 0)
        elif ch in (curses.KEY_HOME, ord("g")):
            cur = 0; detail_scroll = 0; status = ""
        elif ch in (curses.KEY_END, ord("G")):
            cur = len(nav) - 1; detail_scroll = 0; status = ""
        elif ch in (curses.KEY_ENTER, 10, 13):
            kind, obj, _label = rows[sel_row_idx]
            if kind == "gameplan":
                if on_load is None:
                    status, status_kind = "Loading isn't available in this context.", "info"
                else:
                    status = on_load(obj.tool, obj.name)
                    status_kind = "err" if status.startswith("No active project") else "ok"
            elif kind == "wordlist":
                if obj.referenced_by:
                    status = f"'{obj.name}' loads via a gameplan -- Enter a gameplan that uses it (e.g. {obj.referenced_by[0]})."
                else:
                    status = f"'{obj.name}' is a standalone wordlist -- not part of a gameplan to load."
                status_kind = "info"


def _safe_add(stdscr, y, x, text, maxlen, attr=0) -> None:
    try:
        stdscr.addnstr(y, x, text, maxlen, attr)
    except Exception:
        pass  # curses raises at the bottom-right corner and on odd resizes; ignore


# --- Textual backend (cross-platform; the Windows-friendly option) ----------

def _run_textual(gameplans, wordlists, on_load=None, project_label=None) -> None:
    """Textual renderer -- same data as the curses one. Imported lazily so
    Textual is only required when this backend is actually chosen."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

    class Row(ListItem):
        def __init__(self, label: str, kind: str, obj) -> None:
            super().__init__(Label(label))
            self.kind = kind
            self.payload = obj

    class ExplorerApp(App):
        # Minimal palette to match the CLI: cyan accents, magenta headers.
        CSS = """
        Horizontal { height: 1fr; }
        #list { width: 40%; border-right: solid $primary; }
        #detailwrap { width: 60%; padding: 0 1; }
        Row.header { color: magenta; text-style: bold; }
        #status { dock: bottom; height: 1; color: cyan; }
        """
        BINDINGS = [("q", "quit", "Quit"), ("enter", "load", "Load gameplan")]
        TITLE = TITLE
        SUB_TITLE = f"project: {project_label}" if project_label else "no active project"

        def compose(self) -> ComposeResult:
            yield Header()
            items: list[ListItem] = []
            tool_hex = {"bust": "#ff8700", "fuzz": "#9d7cff", "crack": "#00b894", "brute": "#ff5f5f"}
            items.append(Row(f"GAMEPLANS ({len(gameplans)})", "header", None))
            for gp in gameplans:
                # Rich markup: color the [tool] tag, keep the name default/white.
                # The opening bracket is escaped so it renders literally.
                color = tool_hex.get(gp.tool, "#ff8700")
                items.append(Row(f"[{color}]\\[{gp.tool}][/] {gp.name}", "gameplan", gp))
            items.append(Row(f"WORDLISTS ({len(wordlists)})", "header", None))
            for wl in wordlists:
                items.append(Row(wl.name, "wordlist", wl))
            for it in items:
                if getattr(it, "kind", None) == "header":
                    it.add_class("header")
            with Horizontal():
                yield ListView(*items, id="list")
                with VerticalScroll(id="detailwrap"):
                    yield Static("", id="detail")
            yield Static("", id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#list", ListView).focus()

        def _render(self, row) -> None:
            detail = self.query_one("#detail", Static)
            if row is None or row.kind == "header":
                detail.update("Select a gameplan or wordlist on the left.")
                return
            if row.kind == "gameplan":
                lines = gameplan_detail_lines(row.payload)
            else:
                lines = wordlist_detail_lines(row.payload, wordlists)
            detail.update("\n".join(lines))

        def on_list_view_highlighted(self, event) -> None:
            self._render(event.item)

        def action_load(self) -> None:
            lv = self.query_one("#list", ListView)
            row = lv.highlighted_child
            status = self.query_one("#status", Static)
            if row is None or getattr(row, "kind", None) == "header":
                return
            if row.kind == "gameplan":
                msg = on_load(row.payload.tool, row.payload.name) if on_load else "Loading unavailable."
            elif row.payload.referenced_by:
                msg = f"'{row.payload.name}' loads via a gameplan -- Enter a gameplan that uses it."
            else:
                msg = f"'{row.payload.name}' is standalone -- not part of a gameplan."
            status.update(msg)

    ExplorerApp().run()


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
