from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from obliquity.adapters.hashcat import build_command, parse_output
from obliquity.core.crackplan import CrackStage


class BuildCommandTests(TestCase):
    def test_dictionary_attack_puts_hashfile_then_wordlist_last(self) -> None:
        stage = CrackStage(name="dict", attack_mode="dictionary", wordlist="words.txt")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"))

        self.assertEqual(command[-2:], ["hashes.txt", "words.txt"])
        self.assertIn("-m", command)
        self.assertEqual(command[command.index("-m") + 1], "0")
        self.assertEqual(command[command.index("-a") + 1], "0")

    def test_mask_attack_puts_hashfile_then_mask_last(self) -> None:
        stage = CrackStage(name="mask", attack_mode="mask", mask="?d?d?d?d")
        command = build_command("hashes.txt", 1000, stage, Path("out.txt"))

        self.assertEqual(command[-2:], ["hashes.txt", "?d?d?d?d"])
        self.assertEqual(command[command.index("-a") + 1], "3")

    def test_rules_flag_included_when_stage_has_rules(self) -> None:
        stage = CrackStage(name="dict", attack_mode="dictionary", wordlist="words.txt", rules="best64.rule")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"))

        self.assertEqual(command[command.index("-r") + 1], "best64.rule")

    def test_outfile_format_is_hash_colon_plain(self) -> None:
        # 1,2 (comma-separated, NOT a bitmask sum) -- confirmed against real
        # hashcat 7.1.2: "3" alone produces hex_plain, not hash:plain.
        stage = CrackStage(name="dict", attack_mode="dictionary", wordlist="words.txt")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"))

        self.assertEqual(command[command.index("--outfile-format") + 1], "1,2")

    def test_combinator_uses_a1_and_both_wordlists_in_order(self) -> None:
        stage = CrackStage(name="comb", attack_mode="combinator", wordlist="a.txt", wordlist2="b.txt")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"))

        self.assertEqual(command[command.index("-a") + 1], "1")
        self.assertEqual(command[-3:], ["hashes.txt", "a.txt", "b.txt"])

    def test_hybrid_wordlist_mask_uses_a6_wordlist_then_mask(self) -> None:
        stage = CrackStage(name="hyb", attack_mode="hybrid-wordlist-mask", wordlist="w.txt", mask="?d?d?d?d")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"))

        self.assertEqual(command[command.index("-a") + 1], "6")
        self.assertEqual(command[-3:], ["hashes.txt", "w.txt", "?d?d?d?d"])

    def test_hybrid_mask_wordlist_uses_a7_mask_then_wordlist(self) -> None:
        stage = CrackStage(name="hyb", attack_mode="hybrid-mask-wordlist", wordlist="w.txt", mask="?d?d")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"))

        self.assertEqual(command[command.index("-a") + 1], "7")
        self.assertEqual(command[-3:], ["hashes.txt", "?d?d", "w.txt"])

    def test_restore_file_path_added_to_normal_run(self) -> None:
        stage = CrackStage(name="dict", attack_mode="dictionary", wordlist="w.txt")
        command = build_command("hashes.txt", 0, stage, Path("out.txt"), restore_file=Path("s.restore"))

        self.assertEqual(command[command.index("--restore-file-path") + 1], "s.restore")

    def test_restore_produces_minimal_command(self) -> None:
        stage = CrackStage(name="dict", attack_mode="dictionary", wordlist="w.txt")
        command = build_command(
            "hashes.txt", 0, stage, Path("out.txt"),
            session="sess", restore_file=Path("s.restore"), restore=True,
        )

        self.assertIn("--restore", command)
        self.assertEqual(command[command.index("--restore-file-path") + 1], "s.restore")
        # must NOT reissue the full attack args -- hashcat reads those from the file
        self.assertNotIn("-a", command)
        self.assertNotIn("-m", command)
        self.assertNotIn("w.txt", command)

    def test_restore_without_restore_file_raises(self) -> None:
        stage = CrackStage(name="dict", attack_mode="dictionary", wordlist="w.txt")
        with self.assertRaises(ValueError):
            build_command("hashes.txt", 0, stage, Path("out.txt"), restore=True)


class ParseOutputTests(TestCase):
    def test_parses_hash_colon_plaintext_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "cracked.txt"
            output.write_text("482c811da5d5b4bc6d497ffa98491e38:password123\n", encoding="utf-8")
            results = parse_output(output, run_id=1, project_id=2, job_id=3, source="stage-1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["hash"], "482c811da5d5b4bc6d497ffa98491e38")
        self.assertEqual(results[0]["plaintext"], "password123")

    def test_ignores_lines_without_a_separator(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "cracked.txt"
            output.write_text("password123\n", encoding="utf-8")
            results = parse_output(output, run_id=1, project_id=2, job_id=3, source="stage-1")

        self.assertEqual(results, [])

    def test_missing_output_file_returns_empty(self) -> None:
        results = parse_output(Path("/nonexistent/cracked.txt"), run_id=1, project_id=2, job_id=3, source="stage-1")
        self.assertEqual(results, [])
