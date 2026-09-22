"""Posting-inspired Obliquity Textual experiment.

This is a standalone keyboard UI prototype with fake data. It does not call
feroxbuster, ffuf, hashcat, or the production Obliquity database.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Checkbox, Input, Label, ListItem, ListView, RichLog, Static


def menu_item(key: str, title: str, detail: str, item_id: str) -> ListItem:
    return ListItem(
        Horizontal(
            Label(key, classes="menu-key"),
            Label(title, classes="menu-title"),
            Label(detail, classes="menu-detail"),
            classes="menu-row",
        ),
        id=item_id,
    )


class ChromeScreen(Screen):
    """Shared keyboard behavior for every demo page."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("q", "quit", "Quit"),
    ]

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class HomeScreen(ChromeScreen):
    BINDINGS = ChromeScreen.BINDINGS + [
        ("1", "open_project", "Project"),
        ("2", "open_targets", "Targets"),
        ("3", "open_workflow", "Workflow"),
        ("4", "open_files", "Wordlists"),
        ("5", "open_settings", "Settings"),
        ("6", "open_console", "Console"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("[b #68f5c0]Obliquity[/] [#4ba58a]4.0.0-ui[/]                                      [#8190a6]operator@local[/]", id="masthead", markup=True)
        with Horizontal(id="command-bar"):
            yield Static("[#091426 on #2c806d]  PROJECT  [/]", markup=True, classes="command-mode")
            yield Static(" [#f08df2]acme-lab[/]  [#8190a6]//[/]  [#dcdee5]https://api.example.test[/]", markup=True, id="command-target")
            yield Static("[#091426 on #6ff3c5] READY [/]", markup=True, id="command-state")
        with Horizontal(id="workspace"):
            with Vertical(id="collection-pane"):
                yield Static(" Collection ", classes="pane-title")
                yield ListView(
                    menu_item("01", "Project", "session and reporting", "project"),
                    menu_item("02", "Targets", "2 hosts defined", "targets"),
                    menu_item("03", "Workflow", "choose an operation", "workflow"),
                    menu_item("04", "Wordlists", "browse and select files", "files"),
                    menu_item("05", "Settings", "runtime preferences", "settings"),
                    menu_item("06", "Live console", "simulated stream", "console"),
                    id="home-menu",
                )
                yield Static("\n  PROJECT\n  └─ acme-lab\n     ├─ api.example.test\n     └─ admin.example.test", id="project-tree")
            with Vertical(id="request-pane"):
                yield Static(" Session ", classes="pane-title bright-title")
                yield Static("Overview   Targets   Coverage   History", classes="tab-line")
                yield Static("━" * 66, classes="active-rule")
                with Horizontal(id="summary-row"):
                    yield Static("[b #68f5c0]2[/]\n[#8190a6]TARGETS[/]", markup=True, classes="summary")
                    yield Static("[b #68f5c0]6[/]\n[#8190a6]RUNS[/]", markup=True, classes="summary")
                    yield Static("[b #f08df2]27[/]\n[#8190a6]FINDINGS[/]", markup=True, classes="summary")
                    yield Static("[b #68f5c0]67%[/]\n[#8190a6]COVERAGE[/]", markup=True, classes="summary")
                yield Static(
                    "[b #dcdee5]Recent activity[/]\n\n"
                    "[#68f5c0]GET[/]  /api/users              [#68f5c0]200[/]  feroxbuster\n"
                    "[#68f5c0]GET[/]  /search?debug=true      [#68f5c0]200[/]  ffuf\n"
                    "[#f0c674]GET[/]  /admin                  [#f0c674]403[/]  feroxbuster\n"
                    "[#8190a6]SYS[/]  generic-standard        complete\n\n"
                    "[#8190a6]Use Up/Down to move through Collection. Press Enter to open.[/]",
                    id="activity",
                    markup=True,
                )
        yield Static("[#f08df2]^j[/] Down   [#f08df2]^k[/] Up   [#f08df2]Enter[/] Open   [#f08df2]Tab[/] Focus   [#f08df2]q[/] Quit", id="keybar", markup=True)

    def on_mount(self) -> None:
        self.query_one("#home-menu", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        actions = {
            "project": self.action_open_project,
            "targets": self.action_open_targets,
            "workflow": self.action_open_workflow,
            "files": self.action_open_files,
            "settings": self.action_open_settings,
            "console": self.action_open_console,
        }
        action = actions.get(event.item.id)
        if action:
            action()

    def action_open_project(self) -> None: self.app.push_screen(ProjectScreen())
    def action_open_targets(self) -> None: self.app.push_screen(TargetScreen())
    def action_open_workflow(self) -> None: self.app.push_screen(WorkflowScreen())
    def action_open_files(self) -> None: self.app.push_screen(FileScreen())
    def action_open_settings(self) -> None: self.app.push_screen(SettingsScreen())
    def action_open_console(self) -> None: self.app.push_screen(ConsoleScreen())


class DetailScreen(ChromeScreen):
    page_title = "Page"
    page_hint = "Tab Focus   Esc Back   q Quit"

    def compose(self) -> ComposeResult:
        yield Static(f"[b #68f5c0]Obliquity[/] [#4ba58a]4.0.0-ui[/]                                      [#8190a6]{self.page_title.lower()}@local[/]", id="masthead", markup=True)
        yield Static(f"[#091426 on #2c806d]  {self.page_title.upper()}  [/]  [#8190a6]// keyboard workspace[/]", id="detail-command", markup=True)
        yield from self.compose_body()
        yield Static(self.page_hint, id="keybar")

    def compose_body(self) -> ComposeResult:
        yield Static("Override this page")


class ProjectScreen(DetailScreen):
    page_title = "Project"
    page_hint = "Tab Next field   Enter Apply   Esc Back   q Quit"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="detail-workspace"):
            with Vertical(classes="side-nav"):
                yield Static(" Project ", classes="pane-title")
                yield Static("▸ Identity\n  Report\n  Storage\n  Archive", classes="plain-nav")
            with Vertical(classes="editor-pane"):
                yield Static(" Identity ", classes="pane-title bright-title")
                yield Label("Project name", classes="field-label")
                yield Input(value="acme-lab", id="project-name")
                yield Label("Report title", classes="field-label")
                yield Input(value="ACME external assessment", id="report-title")
                yield Checkbox("Generate report after each operation", value=True)
                yield Checkbox("Open HTML report when complete", value=False)


class TargetScreen(DetailScreen):
    page_title = "Targets"
    page_hint = "Up/Down Select   Enter Toggle   Tab Focus   Esc Back"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="detail-workspace"):
            with Vertical(classes="side-nav"):
                yield Static(" Hosts ", classes="pane-title")
                yield ListView(
                    ListItem(Label("● api.example.test")),
                    ListItem(Label("○ admin.example.test")),
                    ListItem(Label("+ add target")),
                    id="target-list",
                )
            with Vertical(classes="editor-pane"):
                yield Static(" Target detail ", classes="pane-title bright-title")
                yield Static("[#8190a6]SCHEME[/]   [#68f5c0]https[/]\n[#8190a6]HOST[/]     api.example.test\n[#8190a6]PORT[/]     443\n[#8190a6]STATE[/]    [#68f5c0]reachable[/]\n\n[#8190a6]LAST RUN[/]  ffuf / parameter-names-quick\n[#8190a6]REQUESTS[/]  1,240", markup=True, classes="detail-text")

    def on_mount(self) -> None: self.query_one("#target-list", ListView).focus()


class WorkflowScreen(DetailScreen):
    page_title = "Workflow"
    page_hint = "Up/Down Select   Enter Choose   Tab Focus   Space Toggle   Esc Back"

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="detail-workspace"):
            with Vertical(classes="side-nav"):
                yield Static(" Operations ", classes="pane-title")
                yield ListView(
                    ListItem(Label("DIR  Directory discovery"), id="dir"),
                    ListItem(Label("FUZ  Parameter fuzzing"), id="fuzz"),
                    ListItem(Label("API  Request fuzzing"), id="api"),
                    ListItem(Label("REP  Generate report"), id="report"),
                    id="workflow-list",
                )
            with Vertical(classes="editor-pane"):
                yield Static(" Request ", classes="pane-title bright-title")
                yield Static("Options   Headers   Filtering   Output", classes="tab-line")
                yield Static("━" * 62, classes="active-rule")
                yield Checkbox("Autocalibrate false positives", value=True)
                yield Checkbox("Follow redirects", value=False)
                yield Checkbox("Resume completed coverage", value=True)
                yield Label("Rate limit", classes="field-label")
                yield Input(value="50", placeholder="requests / second")
                yield Label("Extensions", classes="field-label")
                yield Input(value="php,html,js,json")

    def on_mount(self) -> None: self.query_one("#workflow-list", ListView).focus()


class FileScreen(DetailScreen):
    page_title = "Wordlists"
    page_hint = "Up/Down Scroll   Enter Select file   Tab Change pane   Esc Back"

    FILES = [
        ("DIR", "..", "parent directory"),
        ("DIR", "Discovery/", "18 files"),
        ("DIR", "Fuzzing/", "42 files"),
        ("TXT", "common.txt", "4,614 lines"),
        ("TXT", "raft-small-words.txt", "43,003 lines"),
        ("TXT", "parameters-top1000.txt", "1,000 lines"),
        ("TXT", "api-endpoints.txt", "2,721 lines"),
        ("TXT", "extensions-web.txt", "36 lines"),
        ("TXT", "quick-smoke.txt", "24 lines"),
        ("TXT", "custom-acme.txt", "318 lines"),
    ]

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="detail-workspace"):
            with Vertical(id="file-pane"):
                yield Static(" ~/.obliquity/wordlists ", classes="pane-title")
                yield ListView(
                    *[
                        ListItem(
                            Horizontal(Label(kind, classes="file-kind"), Label(name, classes="file-name"), Label(size, classes="file-size")),
                            id=f"file-{index}",
                        )
                        for index, (kind, name, size) in enumerate(self.FILES)
                    ],
                    id="file-list",
                )
            with Vertical(id="preview-pane"):
                yield Static(" Preview ", classes="pane-title bright-title")
                yield Static("[#8190a6]SELECTED[/]  none\n[#8190a6]TYPE[/]      -\n[#8190a6]LINES[/]     -\n\nChoose a file to inspect its metadata.\nPress Enter to use it for the demo workflow.", id="file-preview", markup=True)

    def on_mount(self) -> None: self.query_one("#file-list", ListView).focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.item.id is None:
            return
        index = int(event.item.id.split("-")[1])
        kind, name, size = self.FILES[index]
        self.query_one("#file-preview", Static).update(
            f"[#8190a6]SELECTED[/]  [#68f5c0]{name}[/]\n[#8190a6]TYPE[/]      {kind}\n[#8190a6]SIZE[/]      {size}\n\n[#dcdee5]Preview[/]\nadmin\napi\nassets\nbackup\nconfig\ndebug\nhealth\ninternal"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = int((event.item.id or "file-0").split("-")[1])
        self.notify(f"Selected {self.FILES[index][1]} for this demo")


class SettingsScreen(DetailScreen):
    page_title = "Settings"
    page_hint = "Tab Next setting   Space Toggle   Ctrl+S Save   Esc Back"
    BINDINGS = DetailScreen.BINDINGS + [("ctrl+s", "save", "Save")]

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="detail-workspace"):
            with Vertical(classes="side-nav"):
                yield Static(" Settings ", classes="pane-title")
                yield Static("▸ Interface\n  Execution\n  Reporting\n  Network", classes="plain-nav")
            with Vertical(classes="editor-pane"):
                yield Static(" Interface ", classes="pane-title bright-title")
                yield Checkbox("Compact terminal layout", value=True)
                yield Checkbox("Show operation transitions", value=False)
                yield Checkbox("Display live request rate", value=True)
                yield Checkbox("Confirm before stopping a run", value=True)
                yield Checkbox("Automatically open reports", value=False)
                yield Label("Refresh interval (milliseconds)", classes="field-label")
                yield Input(value="500")

    def action_save(self) -> None: self.notify("Demo settings saved", severity="information")


class ConsoleScreen(DetailScreen):
    page_title = "Live Console"
    page_hint = "Up/Down Scroll   End Latest   Esc Back   q Quit"

    def compose_body(self) -> ComposeResult:
        with Vertical(classes="detail-workspace", id="console-workspace"):
            yield Static(" Stream   Findings   Requests   Errors ", classes="pane-title bright-title")
            yield RichLog(id="stream", markup=True, wrap=False)

    def on_mount(self) -> None:
        log = self.query_one("#stream", RichLog)
        rows = [
            "[#8190a6]03:34:01[/] [#68f5c0]SYS[/]  stage 2/3 started — parameter-names-quick",
            "[#8190a6]03:34:02[/] [#68f5c0]GET[/]  /search?debug=test          200  2.8kb",
            "[#8190a6]03:34:03[/] [#68f5c0]GET[/]  /search?admin=test          403  0.4kb",
            "[#8190a6]03:34:04[/] [#f08df2]HIT[/]  parameter candidate: debug",
            "[#8190a6]03:34:05[/] [#68f5c0]GET[/]  /api/v1/users               200  1.2kb",
            "[#8190a6]03:34:06[/] [#f0c674]WRN[/]  response baseline changed",
            "[#8190a6]03:34:07[/] [#68f5c0]SYS[/]  1,240 / 4,669 requests complete",
        ]
        for row in rows:
            log.write(row)
        log.focus()


class ObliquityPostingDemo(App[None]):
    TITLE = "Obliquity UI Study"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    * { scrollbar-color: #6a467b; scrollbar-background: #101e31; }
    Screen { background: #08172a; color: #dcdee5; }
    #masthead { height: 3; padding: 1 2 0 2; background: #08172a; }
    #command-bar { height: 2; margin: 0 2 1 2; background: #102841; }
    .command-mode { width: 16; }
    #command-target { width: 1fr; padding: 0 1; }
    #command-state { width: 9; content-align: center middle; }
    #workspace, .detail-workspace { height: 1fr; padding: 1 2; }
    #collection-pane { width: 34%; border: solid #9857aa; border-title-color: #9857aa; }
    #request-pane { width: 66%; margin-left: 1; border: solid #d468e5; }
    .pane-title { height: 1; color: #a46db3; text-style: bold; padding-left: 1; }
    .bright-title { color: #dcdee5; text-align: right; padding-right: 1; }
    #home-menu, #target-list, #workflow-list, #file-list { height: auto; background: transparent; border: none; }
    ListItem { height: 2; padding: 0 1; color: #bdc2ca; }
    ListItem.--highlight { background: #236b63; color: #effffb; text-style: bold; }
    .menu-row { height: 2; }
    .menu-key { width: 4; color: #68f5c0; }
    .menu-title { width: 18; }
    .menu-detail { width: 1fr; color: #8190a6; }
    #project-tree { color: #8190a6; padding: 0 2; }
    .tab-line { height: 2; padding: 0 2; color: #9299a5; }
    .active-rule { color: #68f5c0; height: 1; padding: 0 2; }
    #summary-row { height: 6; padding: 1 2; }
    .summary { width: 1fr; text-align: center; background: #10243a; margin-right: 1; padding: 1; }
    #activity { padding: 1 2; background: #0b1d32; height: 1fr; }
    #keybar { dock: bottom; height: 1; background: #07111f; color: #dcdee5; padding: 0 2; }
    #detail-command { height: 2; margin: 0 2; background: #102841; padding: 0 1; }
    .side-nav { width: 31%; border: solid #9857aa; }
    .editor-pane { width: 69%; margin-left: 1; border: solid #d468e5; padding: 0 1; }
    .plain-nav { padding: 1 2; color: #aeb4be; }
    .field-label { color: #8190a6; height: 1; margin: 1 1 0 1; }
    Input { height: 3; margin: 0 1; border: none; background: #142d49; color: #dcdee5; }
    Input:focus { border: none; background: #1b3a59; color: #ffffff; }
    Checkbox { height: 2; margin: 0 1; color: #bdc2ca; }
    Checkbox:focus { background: #203d53; color: #68f5c0; }
    .detail-text { padding: 2; }
    #file-pane { width: 55%; border: solid #9857aa; }
    #preview-pane { width: 45%; margin-left: 1; border: solid #d468e5; }
    .file-kind { width: 5; color: #68f5c0; }
    .file-name { width: 1fr; }
    .file-size { width: 18; color: #8190a6; text-align: right; }
    #file-preview { padding: 2; }
    #console-workspace { border: solid #d468e5; padding: 0; }
    #stream { height: 1fr; background: #071322; color: #bdc2ca; border: none; padding: 1 2; }
    """

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


if __name__ == "__main__":
    ObliquityPostingDemo().run()
