import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.core.runner import live_status_tally, make_flood_detector


def _write_jsonl(path: Path, statuses: list[int]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for i, s in enumerate(statuses):
            fh.write(json.dumps({"url": f"http://x/{i}", "status": s}) + "\n")


class StatusTallyTests(TestCase):
    def test_counts_by_status(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "out.jsonl"
            _write_jsonl(p, [200] * 30 + [301] * 5 + [403] * 2)
            counts = live_status_tally(p)()
            self.assertEqual(counts, {200: 30, 301: 5, 403: 2})

    def test_incremental(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "out.jsonl"
            _write_jsonl(p, [200] * 3)
            tally = live_status_tally(p)
            self.assertEqual(tally(), {200: 3})
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"url": "http://x/n", "status": 200}) + "\n")
            self.assertEqual(tally(), {200: 4})


class FloodDetectorTests(TestCase):
    def _detector(self, statuses, threshold=100):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "out.jsonl"
            _write_jsonl(p, statuses)
            return make_flood_detector(live_status_tally(p), threshold)(0.0)

    def test_fires_on_dominant_flood(self):
        reason = self._detector([200] * 300, threshold=100)
        self.assertIsNotNone(reason)
        self.assertIn("200", reason)

    def test_ignores_below_threshold(self):
        self.assertIsNone(self._detector([200] * 50, threshold=100))

    def test_ignores_when_not_dominant(self):
        # 120 mixed across many codes, none dominant enough
        mixed = ([200] * 60 + [301] * 60 + [403] * 60)
        self.assertIsNone(self._detector(mixed, threshold=100))

    def test_ignores_small_sample(self):
        self.assertIsNone(self._detector([200] * 10, threshold=5))  # below min_total
