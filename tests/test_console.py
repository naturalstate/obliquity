from unittest import TestCase

from obliquity.core.console import elapsed_time, live_progress_line, progress_bar


class LiveProgressTests(TestCase):
    def test_elapsed_time(self) -> None:
        self.assertEqual(elapsed_time(3661.9), "01:01:01")

    def test_progress_bar_clamps_values(self) -> None:
        self.assertEqual(progress_bar(-1, width=4), "[----]")
        self.assertEqual(progress_bar(1000, width=4), "[####]")

    def test_live_line_uses_completed_stage_boundary(self) -> None:
        line = live_progress_line(
            {
                "stage_number": 2,
                "total_stages": 3,
                "stage": "files",
                "elapsed": 65,
                "findings": 7,
            }
        )

        self.assertIn("Stage 2/3: files", line)
        self.assertIn("33%", line)
        self.assertIn("Elapsed 00:01:05", line)
        self.assertIn("Findings 7", line)
