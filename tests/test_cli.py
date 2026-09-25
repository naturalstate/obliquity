from contextlib import redirect_stdout
from io import StringIO
from unittest import TestCase

from obliquity.cli import build_parser


class HelpTests(TestCase):
    def test_main_help_lists_workflow_examples(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn("obliquity project create acme", help_text)
        self.assertIn("obliquity bust run acme", help_text)
        self.assertIn("obliquity report html acme", help_text)

    def test_run_help_documents_advanced_options(self) -> None:
        output = StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(output):
            build_parser().parse_args(["bust", "run", "--help"])

        help_text = output.getvalue()
        self.assertIn("--rate-limit", help_text)
        self.assertIn("--proxy", help_text)
        self.assertIn("--header", help_text)
        self.assertIn("examples:", help_text)

    def test_run_accepts_report_options(self) -> None:
        args = build_parser().parse_args(
            ["bust", "run", "demo", "https://example.test", "--open-report"]
        )

        self.assertTrue(args.open_report)

    def test_bare_tool_commands_list_gameplans(self) -> None:
        from obliquity.cli import cmd_tool_gameplans
        for tool in ("bust", "fuzz", "crack", "brute"):
            args = build_parser().parse_args([tool])
            self.assertIs(args.func, cmd_tool_gameplans)
            self.assertEqual(args._tool, tool)

    def test_tool_subcommands_still_dispatch(self) -> None:
        from obliquity.cli import cmd_bust_run
        args = build_parser().parse_args(["bust", "run", "demo"])
        self.assertIs(args.func, cmd_bust_run)

    def test_explore_backend_flag(self) -> None:
        args = build_parser().parse_args(["explore", "--backend", "textual"])
        self.assertEqual(args.backend, "textual")

    def test_archive_accepts_nonexistent_project_mode(self) -> None:
        args = build_parser().parse_args(
            ["project", "archive", "demo", "--yes", "--if-exists"]
        )

        self.assertTrue(args.yes)
        self.assertTrue(args.if_exists)


class EscalationLadderTests(TestCase):
    def test_every_escalation_target_resolves_to_a_real_gameplan(self) -> None:
        from obliquity.cli import GAMEPLAN_ESCALATION, resolve_gameplan

        for source, target in GAMEPLAN_ESCALATION.items():
            resolve_gameplan(source)
            resolve_gameplan(target)

    def test_generic_ladder_is_three_steps(self) -> None:
        from obliquity.cli import GAMEPLAN_ESCALATION

        self.assertEqual(GAMEPLAN_ESCALATION["generic-quick"], "generic-standard")
        self.assertEqual(GAMEPLAN_ESCALATION["generic-standard"], "generic-deep")
