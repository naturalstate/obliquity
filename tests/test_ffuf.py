from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.adapters.ffuf import build_command, parse_json_output


class FfufAdapterTests(TestCase):
    def test_parameter_command_contains_fuzz_template_and_controls(self) -> None:
        command = build_command(
            wordlist="params.txt",
            url_template="https://example.test/search?FUZZ=test",
            mode="clusterbomb",
            autocalibrate=True,
            rate=25,
            threads=10,
            match_codes="200,302",
            filter_size="1234",
        )
        self.assertIn("-u", command)
        self.assertIn("https://example.test/search?FUZZ=test", command)
        self.assertIn("-ac", command)
        self.assertEqual(command[command.index("-rate") + 1], "25")
        self.assertEqual(command[command.index("-fs") + 1], "1234")

    def test_raw_request_command_uses_request_protocol(self) -> None:
        command = build_command(wordlist="values.txt", request_file="request.txt", request_proto="http")
        self.assertIn("-request", command)
        self.assertEqual(command[command.index("-request-proto") + 1], "http")
        self.assertNotIn("-u", command)

    def test_parse_json_lines_normalizes_result(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "results.jsonl"
            output.write_text(
                '{"url":"https://example.test/search?q=admin","status":200,"length":42,"words":3,"lines":1}\n',
                encoding="utf-8",
            )
            findings = parse_json_output(output, run_id=1, project_id=2, host_id=3, source="parameter-value")
        self.assertEqual(findings[0]["status_code"], 200)
        self.assertEqual(findings[0]["content_length"], 42)
        self.assertEqual(findings[0]["source"], "parameter-value")
