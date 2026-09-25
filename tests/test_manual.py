from io import StringIO
from contextlib import redirect_stdout
from unittest import TestCase

from obliquity.cli import build_parser, cmd_manual
from obliquity.manual import print_manual, render_manpage


class ManualTests(TestCase):
    def test_manual_command_parses(self):
        self.assertIs(build_parser().parse_args(["manual"]).func, cmd_manual)

    def test_print_manual_covers_all_pillars(self):
        out = StringIO()
        with redirect_stdout(out):
            print_manual()
        text = out.getvalue()
        for token in ("OBLIQUITY MANUAL", "bust", "fuzz", "crack", "brute", "obliquity explore"):
            self.assertIn(token, text)

    def test_manpage_is_roff(self):
        page = render_manpage()
        self.assertTrue(page.startswith(".TH OBLIQUITY 1"))
        self.assertIn(".SH NAME", page)
        self.assertIn(".SH DESCRIPTION", page)
