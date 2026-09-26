from unittest import TestCase

from obliquity.cli import build_parser, cmd_console
from obliquity.console import Console, _rewrite


class RewriteTests(TestCase):
    def test_run_verb_prefixes_selected_tool(self):
        self.assertEqual(_rewrite(["run", "--dry-run"], "bust"), ["bust", "run", "--dry-run"])
        self.assertEqual(_rewrite(["plan"], "crack"), ["crack", "plan"])
        self.assertEqual(_rewrite(["creds"], "brute"), ["brute", "creds"])

    def test_run_verb_without_tool_is_none(self):
        self.assertIsNone(_rewrite(["run"], None))

    def test_option_verbs_insert_tool(self):
        self.assertEqual(_rewrite(["set", "endpoint", "/x"], "fuzz"), ["set", "fuzz", "endpoint", "/x"])
        self.assertEqual(_rewrite(["options"], "fuzz"), ["options", "fuzz"])
        self.assertEqual(_rewrite(["unset", "endpoint"], "fuzz"), ["unset", "fuzz", "endpoint"])

    def test_explicit_tool_passthrough(self):
        # first token is a tool name -> full command, untouched
        self.assertEqual(_rewrite(["bust", "run"], "fuzz"), ["bust", "run"])
        # explicit tool given to set -> not double-inserted
        self.assertEqual(_rewrite(["set", "fuzz", "endpoint", "/x"], "bust"),
                         ["set", "fuzz", "endpoint", "/x"])

    def test_other_commands_passthrough(self):
        self.assertEqual(_rewrite(["project", "list"], "bust"), ["project", "list"])
        self.assertEqual(_rewrite(["history"], None), ["history"])


class ConsoleCommandTests(TestCase):
    def test_console_subcommand_parses(self):
        self.assertIs(build_parser().parse_args(["console"]).func, cmd_console)

    def test_use_and_back_update_context(self):
        con = Console()
        self.assertIsNone(con.tool)
        con._handle("use bust")
        self.assertEqual(con.tool, "bust")
        con._handle("back")
        self.assertIsNone(con.tool)

    def test_exit_returns_false(self):
        con = Console()
        self.assertFalse(con._handle("exit"))
        self.assertFalse(con._handle("quit"))
        self.assertTrue(con._handle("help"))  # non-exit verbs keep going

    def test_unknown_command_survives(self):
        con = Console()
        self.assertTrue(con._handle("definitely-not-a-command"))
