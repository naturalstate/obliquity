"""Standalone Obliquity Textual UI playground.

This is intentionally a fake-data demo. It does not run tools, write the
Obliquity database, or change the production CLI. Install Textual separately:

    python -m pip install textual
    python -m obliquity.tui_demo

The demo explores compact navigation, keyboard-first forms, screen
transitions, settings, tables, sparklines, and live terminal-style data.
"""

from __future__ import annotations

import random
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Select,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
)


class Brand(Static):
    DEFAULT_CSS = """
    Brand { color: #b4d9ba; text-style: bold; padding: 0 1; height: 3; }
    """

    def render(self) -> str:
        return "OBLIQUITY  //  OPERATOR CONSOLE\n────────────────────────────────────────"


class SlideScreen(Screen):
    """A restrained fade-in used for page changes."""

    def on_mount(self) -> None:
        self.styles.opacity = 0.0
        self.styles.animate("opacity", 1.0, duration=0.18)


class MenuItem(Button):
    DEFAULT_CSS = """
    MenuItem { width: 1fr; height: 3; content-align: left middle; margin: 0 0 1 0; }
    MenuItem:hover { background: $accent-darken-2; }
    MenuItem.-active { background: $accent; color: $text; text-style: bold; }
    """


class HomeScreen(SlideScreen):
    BINDINGS = [
        ("1", "open_dirbust", "Dirbust"),
        ("2", "open_fuzz", "Fuzz"),
        ("3", "open_crack", "Crack"),
        ("s", "settings", "Settings"),
        ("d", "dashboard", "Dashboard"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="home-shell"):
            yield Brand()
            with Horizontal(id="home-columns"):
                with Vertical(id="home-menu"):
                    yield Label("SELECT WORKFLOW", classes="eyebrow")
                    yield ListView(
                        ListItem(Label("[1]  DIRECTORY DISCOVERY"), id="dirbust"),
                        ListItem(Label("[2]  PARAMETER / API FUZZING"), id="fuzz"),
                        ListItem(Label("[3]  PASSWORD / HASH CRACKING"), id="crack"),
                        ListItem(Label("[S]  SETTINGS"), id="settings"),
                        ListItem(Label("[D]  LIVE DASHBOARD"), id="dashboard"),
                        id="main-menu",
                    )
                with Vertical(id="home-preview"):
                    yield Label("PROJECT SNAPSHOT", classes="eyebrow")
                    yield Static("PROJECT  acme-demo\nTARGET   https://api.example.test\nSTATUS   ready for operator input", id="snapshot")
                    yield Static("Choose a workflow to configure a staged operation.\n\nThe production CLI remains available outside this demo.", id="home-hint")
            yield Static("↑↓ navigate   Enter select   1/2/3 workflows   S settings   D dashboard   Q quit", classes="key-hint")
        yield Footer()

    def on_mount(self) -> None:
        # Put keyboard focus on the menu so Up/Down work immediately.
        self.query_one("#main-menu", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        actions = {"dirbust": self.action_open_dirbust, "fuzz": self.action_open_fuzz, "crack": self.action_open_crack, "settings": self.action_settings, "dashboard": self.action_dashboard}
        action = actions.get(event.item.id)
        if action:
            action()

    def action_open_dirbust(self) -> None:
        self.app.push_screen(WorkflowScreen("DIRECTORY DISCOVERY", "feroxbuster", ["generic-quick", "generic-standard", "smoke-test"]))

    def action_open_fuzz(self) -> None:
        self.app.push_screen(WorkflowScreen("PARAMETER / API FUZZING", "ffuf", ["parameter-names-quick", "parameter-values-quick", "api-request-quick"]))

    def action_open_crack(self) -> None:
        self.app.push_screen(WorkflowScreen("PASSWORD / HASH CRACKING", "hashcat", ["dictionary", "mask", "rule-based"]))

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_dashboard(self) -> None:
        self.app.push_screen(DashboardScreen())

    def action_quit(self) -> None:
        self.app.exit()


class WorkflowScreen(SlideScreen):
    def __init__(self, title: str, tool: str, plans: list[str]) -> None:
        super().__init__()
        self.title_text = title
        self.tool = tool
        self.plans = plans

    BINDINGS = [("escape", "back", "Back"), ("enter", "review", "Review"), ("tab", "focus_next", "Next field")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(classes="page-shell"):
            yield Brand()
            yield Label(f"{self.title_text}  /  {self.tool.upper()}", classes="page-title")
            with Horizontal(classes="form-columns"):
                with Vertical(classes="form-panel"):
                    yield Label("TARGET", classes="eyebrow")
                    yield Input(value="https://api.example.test", placeholder="Target URL", id="target")
                    yield Label("GAMEPLAN / MODE", classes="eyebrow")
                    yield Select([(plan, plan) for plan in self.plans], value=self.plans[0], id="plan")
                    yield Label("WORDLIST", classes="eyebrow")
                    yield Select([("Built-in quick list", "quick"), ("SecLists / custom file", "custom"), ("Choose file...", "file")], value="quick", id="wordlist")
                    yield Checkbox("Resume completed work", value=True, id="resume")
                    yield Checkbox("Open report when complete", value=True, id="report")
                with Vertical(classes="form-panel detail-panel"):
                    yield Label("OPERATION PREVIEW", classes="eyebrow")
                    yield Static(self._preview(), id="operation-preview")
                    yield Label("OPTIONAL CONTROLS", classes="eyebrow")
                    yield Checkbox("Proxy through Burp", id="proxy")
                    yield Checkbox("Autocalibration / smart filtering", value=True, id="smart")
                    yield Input(placeholder="Rate limit (optional)", id="rate")
            yield Static("Esc back   Tab next field   Space toggle   Enter review", classes="key-hint")
        yield Footer()

    def _preview(self) -> str:
        return f"Tool        {self.tool}\nPurpose     {self.title_text.lower()}\nStages      3 simulated\nRequests    4,669 estimated\nTime        08:20 estimated\nCoverage    no prior operation"

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_review(self) -> None:
        self.app.push_screen(ReviewScreen(self.title_text, self.tool))


class ReviewScreen(SlideScreen):
    BINDINGS = [("escape", "back", "Back"), ("enter", "launch", "Launch")]

    def __init__(self, title: str, tool: str) -> None:
        super().__init__()
        self.title_text = title
        self.tool = tool

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(classes="page-shell review-shell"):
            yield Brand()
            yield Label("REVIEW OPERATION", classes="page-title")
            with Vertical(classes="review-card"):
                yield Static(f"TOOL        {self.tool}\nOPERATION   {self.title_text}\nTARGET      https://api.example.test\nGAMEPLAN    parameter-names-quick\nWORDLIST    parameter-names-quick.txt\nREQUESTS    4,669 estimated\nREPORT      open after completion", id="review-data")
                yield Static("Enter launch   Esc back", classes="key-hint")
            yield Button("LAUNCH SIMULATION", id="launch", variant="success")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch":
            self.action_launch()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_launch(self) -> None:
        self.app.push_screen(LiveScreen(self.tool, self.title_text))


class SettingsScreen(SlideScreen):
    BINDINGS = [("escape", "back", "Back"), ("ctrl+s", "save", "Save")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(classes="page-shell"):
            yield Brand()
            yield Label("SETTINGS", classes="page-title")
            with Vertical(classes="settings-card"):
                yield Checkbox("Show colored transitions", value=True, id="transitions")
                yield Checkbox("Show spinner during runs", value=True, id="spinner")
                yield Checkbox("Open reports automatically", value=False, id="open-reports")
                yield Checkbox("Use compact dashboard layout", value=True, id="compact")
                yield Select([("Cyan / green", "cyan"), ("Amber / violet", "amber"), ("Monochrome", "mono")], value="cyan", id="theme")
            yield Static("Space toggle   Tab next   Ctrl+S save   Esc back", classes="key-hint")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_save(self) -> None:
        self.notify("Settings saved for this demo session", severity="information")


class DashboardScreen(SlideScreen):
    BINDINGS = [("escape", "back", "Back"), ("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(classes="page-shell dashboard-shell"):
            yield Brand()
            yield Label("LIVE PROJECT DASHBOARD", classes="page-title")
            with TabbedContent(initial="overview"):
                with TabPane("Overview", id="overview"):
                    with Horizontal(classes="metric-row"):
                        yield Static("27\nFINDINGS", classes="metric metric-green")
                        yield Static("2/3\nSTAGES", classes="metric")
                        yield Static("08:20\nELAPSED", classes="metric")
                        yield Static("67%\nCOVERAGE", classes="metric")
                    yield Sparkline([2, 3, 4, 3, 7, 6, 8, 9, 11, 10, 14], id="traffic")
                with TabPane("Findings", id="findings"):
                    yield DataTable(id="findings-table")
                with TabPane("Terminal", id="terminal"):
                    yield RichLog(id="terminal-log", highlight=True, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#findings-table", DataTable)
        table.add_columns("Status", "Path", "Tool", "Size")
        for row in [("200", "/api/users", "ffuf", "1.2kb"), ("403", "/admin", "ferox", "0.4kb"), ("200", "/search?q=FUZZ", "ffuf", "2.8kb"), ("301", "/backup", "ferox", "0.1kb")]:
            table.add_row(*row)
        log = self.query_one("#terminal-log", RichLog)
        log.write("[obliquity] attached to simulated run stream")
        log.write("[feroxbuster] stage 2/3 running ...")
        log.write("[ffuf] parameter-name candidate: debug")
        log.write("[obliquity] report event: finding recorded")
        self.set_interval(0.8, self._tick)

    def _tick(self) -> None:
        sparkline = self.query_one("#traffic", Sparkline)
        data = list(sparkline.data or [])[-24:]
        sparkline.update(data + [random.randint(3, 16)])
        self.query_one("#terminal-log", RichLog).write(f"[{datetime.now():%H:%M:%S}] simulated event received")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self.notify("Dashboard refreshed", severity="information")


class ObliquityTuiDemo(App[None]):
    TITLE = "Obliquity // Operator Console Demo"
    CSS = """
    * { transition: opacity 180ms linear; }
    Screen { background: #0b0d0c; color: #c5cec8; }
    Header { background: #0b0d0c; color: #83c995; height: 1; }
    Footer { background: #161917; color: #8b9991; height: 1; }
    #home-shell, .page-shell { width: 100%; height: 100%; padding: 0 1; }
    #home-shell:before, .page-shell:before { content: " OBLIQUITY / SESSION 07 / LOCAL  ::  READY "; color: #83c995; height: 1; dock: top; }
    #home-columns, .form-columns { height: 1fr; padding: 1 0; }
    #home-menu { width: 42%; padding: 1 2 0 0; border: solid #39433d; border-left: none; }
    #home-preview { width: 58%; padding: 1 2; border: solid #39433d; border-right: none; background: #101310; }
    #snapshot { color: #9ed2a8; padding: 1 2; border: solid #47634e; background: #0d110e; }
    #home-hint { color: #829188; padding: 2 1; }
    .eyebrow { color: #83c995; text-style: bold; margin: 1 0; }
    .page-title { color: #b4d9ba; text-style: bold; padding: 1 0; border-bottom: solid #39433d; }
    #main-menu { height: auto; border: none; background: transparent; }
    #main-menu > ListItem { padding: 0 1; height: 2; color: #aab5ae; }
    #main-menu > ListItem.--highlight { background: #31523a; color: #effff1; text-style: bold; }
    .form-panel { width: 1fr; padding: 1 2; border: solid #39433d; background: #101310; margin: 0 1; }
    .detail-panel { color: #abd4c2; }
    .review-shell { align: center middle; }
    .review-card, .settings-card { width: 70%; padding: 2 3; border: solid #47634e; background: #101310; }
    .settings-card { width: 60%; }
    .key-hint { color: #829188; padding: 1 0; dock: bottom; }
    .dashboard-shell { padding: 1 2; }
    .metric-row { height: 7; }
    .metric { width: 1fr; margin: 1; padding: 1; text-align: center; color: #9ac9a9; border: solid #39433d; background: #101310; text-style: bold; }
    .metric-green { color: #83c995; border: solid #47634e; }
    #traffic { height: 10; margin: 1 0; color: #40e3a0; background: #091b20; }
    DataTable { height: 1fr; }
    RichLog { height: 1fr; border: solid #39433d; background: #080a09; color: #9ed2a8; }
    Button { margin: 1 0; }
    Select, Input { margin: 0 0 1 0; }
    """

    SCREENS = {"home": HomeScreen}

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


if __name__ == "__main__":
    ObliquityTuiDemo().run()
