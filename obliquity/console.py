"""Interactive console (REPL) for Obliquity -- a dual-mode CLI.

`obliquity console` drops into a msfconsole-style prompt where you type
commands without the `obliquity` prefix. Every one-shot command still works
verbatim; this just feeds each typed line back through the same argument
parser. `use <tool>` selects a tool so bare `run`/`plan`/`set`/... target it.
"""

from __future__ import annotations

import argparse
import shlex
import sys

from obliquity.core.console import c

TOOLS = ("bust", "fuzz", "crack", "brute")
# verbs that, once a tool is selected, auto-target that tool
TOOL_RUN_VERBS = ("run", "plan", "resume", "job", "creds")   # -> "<tool> <verb> ..."
TOOL_OPT_VERBS = ("set", "unset", "options")                 # -> "<verb> <tool> ..."
CONSOLE_VERBS = ("use", "back", "help", "clear", "exit", "quit", "q")

BANNER_HINT = (
    "Interactive console. Type commands without the 'obliquity' prefix.\n"
    "  use <bust|fuzz|crack|brute>   select a tool (then just 'run', 'set ...', 'options')\n"
    "  back                          deselect the tool\n"
    "  help                          list commands   |   exit / Ctrl-D   quit"
)


def _top_level_commands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices.keys())
    return set()


def _rewrite(tokens: list[str], tool: str | None) -> list[str] | None:
    """Map a typed line to a full argv, applying the selected tool. Returns
    None if the command is unknown in the current context."""
    verb = tokens[0]
    rest = tokens[1:]
    if verb in TOOLS:
        return tokens  # explicit full command, e.g. "bust run ..."
    if verb in TOOL_OPT_VERBS:
        # set/unset/options take the tool as first positional
        if rest and rest[0] in TOOLS:
            return tokens  # user gave the tool explicitly
        if tool:
            return [verb, tool, *rest]
        return tokens  # no tool selected: pass through (argparse will guide)
    if verb in TOOL_RUN_VERBS:
        if tool:
            return [tool, verb, *rest]
        return None  # need a tool
    return tokens  # any other top-level command (project, report, history, ...)


class Console:
    def __init__(self) -> None:
        self.tool: str | None = None
        self._parser = None
        self._commands: set[str] = set()

    @property
    def parser(self):
        if self._parser is None:
            from obliquity.cli import build_parser
            self._parser = build_parser()
            self._commands = _top_level_commands(self._parser)
        return self._parser

    def prompt(self) -> str:
        from obliquity.core.config import active_project
        import os
        project = os.environ.get("OBLIQUITY_PROJECT") or active_project() or "no project"
        ctx = f"{project}:{self.tool}" if self.tool else project
        return c(f"obliquity({ctx}) > ", "cyan", bold=True)

    def run(self) -> None:
        self._setup_readline()
        print(c("Obliquity console", "cyan", bold=True))
        print(c(BANNER_HINT, "gray"))
        while True:
            try:
                line = input(self.prompt())
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("^C")
                continue
            if not self._handle(line):
                break
        print(c("bye.", "gray"))

    def _handle(self, line: str) -> bool:
        """Returns False to exit the console."""
        line = line.strip()
        if not line:
            return True
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(c(f"parse error: {exc}", "red"))
            return True
        verb = tokens[0].lower()

        if verb in ("exit", "quit", "q"):
            return False
        if verb == "clear":
            print("\033[2J\033[H", end="")
            return True
        if verb == "help":
            self._help()
            return True
        if verb == "use":
            if len(tokens) < 2 or tokens[1] not in TOOLS:
                print(c(f"usage: use <{'|'.join(TOOLS)}>", "yellow"))
            else:
                self.tool = tokens[1]
                print(c(f"using {self.tool}", "green"))
            return True
        if verb == "back":
            self.tool = None
            return True

        _ = self.parser  # ensure commands loaded
        argv = _rewrite(tokens, self.tool)
        if argv is None:
            print(c(f"'{verb}' needs a tool -- 'use <tool>' first, or type e.g. '{TOOLS[0]} {verb} ...'", "yellow"))
            return True
        if argv[0] not in self._commands:
            print(c(f"unknown command: {argv[0]}   (type 'help')", "yellow"))
            return True

        # Dispatch through the real parser. Guard SystemExit (argparse errors,
        # die()) and any exception so the session survives a bad command.
        try:
            args = self.parser.parse_args(argv)
        except SystemExit:
            return True
        func = getattr(args, "func", None)
        if func is None:
            print(c("that command needs a subcommand (type 'help')", "yellow"))
            return True
        try:
            func(args)
        except SystemExit:
            pass
        except KeyboardInterrupt:
            print(c("\n^C (command interrupted)", "yellow"))
        except Exception as exc:  # noqa: BLE001 -- keep the REPL alive
            print(c(f"error: {exc}", "red"))
        return True

    def _help(self) -> None:
        print(c("Console verbs:", "magenta", bold=True))
        print("  use <tool> | back | help | clear | exit")
        print(c("With a tool selected, these target it:", "magenta", bold=True))
        print("  run | plan | resume | job ... | creds | set <opt> <val> | unset <opt> | options")
        print(c("Other commands (type as usual):", "magenta", bold=True))
        print("  project ... | host ... | wordlists ... | explore | coverage | runs | history | report ... | gameplans list | doctor | manual")
        print(c("Full help for any command: <command> -h", "gray"))

    def _setup_readline(self) -> None:
        try:
            import readline  # noqa: F401
        except ImportError:
            return  # Windows without pyreadline3: input() still works, no completion
        import readline
        words = sorted(set(TOOLS) | set(CONSOLE_VERBS) | set(TOOL_RUN_VERBS) | set(TOOL_OPT_VERBS) | self._top_words())

        def completer(text, state):
            options = [w for w in words if w.startswith(text)]
            return options[state] if state < len(options) else None

        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
        self._load_history(readline)

    def _top_words(self) -> set[str]:
        try:
            return self._commands or _top_level_commands(self.parser)
        except Exception:  # noqa: BLE001
            return set()

    def _load_history(self, readline) -> None:
        try:
            from obliquity.core.config import config_path
            hist = config_path().parent / "console_history"
            if hist.exists():
                readline.read_history_file(str(hist))
            import atexit
            atexit.register(lambda: _save_history(readline, str(hist)))
        except Exception:  # noqa: BLE001
            pass


def _save_history(readline, path: str) -> None:
    try:
        readline.set_history_length(1000)
        readline.write_history_file(path)
    except Exception:  # noqa: BLE001
        pass


def run_console() -> None:
    Console().run()
