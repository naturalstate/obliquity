"""Keyboard-only terminal-style Obliquity UI experiment (fake data)."""
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static


class TerminalHome(Screen):
    BINDINGS = [("1", "dirbust", "Dirbust"), ("2", "fuzz", "Fuzz"), ("3", "crack", "Crack"), ("s", "settings", "Settings"), ("d", "dashboard", "Dashboard"), ("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("OBLIQUITY  //  OPERATOR CONSOLE", id="title")
        yield Static("-" * 110, classes="rule")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Label("WORKFLOWS", classes="caption")
                yield ListView(
                    ListItem(Label("[1]  DIRECTORY DISCOVERY"), id="dirbust"),
                    ListItem(Label("[2]  PARAMETER FUZZING"), id="fuzz"),
                    ListItem(Label("[3]  HASH CRACKING (DEMO)"), id="crack"),
                    ListItem(Label("[s]  SETTINGS"), id="settings"),
                    ListItem(Label("[d]  LIVE DATA"), id="dashboard"),
                    id="menu",
                )
            with Vertical(id="right"):
                yield Label("PROJECT  acme-demo     TARGET  https://api.example.test", classes="caption")
                yield Static("STATUS     READY\nRUNS       06       FINDINGS   27\nREQUESTS   4,669    COVERAGE   67%\n\nRECENT EVENTS\n  03:34:18  ffuf   parameter candidate: debug\n  03:34:12  ferox  discovered /api/users\n  03:33:57  core   stage 2/3 complete", id="data")
        yield Static("UP/DOWN select   ENTER open   1/2/3 workflow   S settings   D data   Q quit", id="keys")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.notify(f"{event.item.id} selected (demo only)")

    def action_dirbust(self) -> None: self.notify("directory discovery selected")
    def action_fuzz(self) -> None: self.notify("parameter fuzzing selected")
    def action_crack(self) -> None: self.notify("hash cracking demo selected")
    def action_settings(self) -> None: self.notify("settings selected")
    def action_dashboard(self) -> None: self.notify("live data selected")
    def action_quit(self) -> None: self.app.exit()


class TerminalDemo(App[None]):
    TITLE = "Obliquity // Terminal Demo"
    CSS = """
    * { transition: none; }
    Screen { background: #080b09; color: #c6d2c9; }
    Header { background: #080b09; color: #79c98d; height: 1; }
    Footer { background: #151916; color: #9aaba0; height: 1; }
    #title { height: 2; padding: 0 1; color: #9ee3ad; text-style: bold; }
    .rule { color: #38543f; height: 1; }
    #body { height: 1fr; padding: 1 0; }
    #left { width: 38%; padding: 1 2 1 1; border-right: solid #304835; }
    #right { width: 62%; padding: 1 2; }
    .caption { color: #79c98d; text-style: bold; height: 2; }
    #menu { height: auto; background: transparent; border: none; }
    #menu > ListItem { height: 2; padding: 0 1; color: #b8c4bb; }
    #menu > ListItem.--highlight { background: #23442d; color: #edfff0; text-style: bold; }
    #data { color: #a8c5ad; padding: 1 0; }
    #keys { height: 2; padding: 0 1; color: #84978a; }
    """

    def on_mount(self) -> None:
        self.push_screen(TerminalHome())


if __name__ == "__main__":
    TerminalDemo().run()
