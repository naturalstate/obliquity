from unittest import TestCase

from obliquity.core.crackplan import (
    CrackStage,
    find_builtin_crackplan,
    fingerprint_crack_stage,
    load_crackplan,
)


class SmokeCrackplanTests(TestCase):
    def test_smoke_wordlist_resolves_next_to_profile(self) -> None:
        crackplan = load_crackplan(find_builtin_crackplan("smoke-test"))

        self.assertEqual(len(crackplan.stages), 1)
        self.assertTrue(crackplan.stages[0].wordlist.endswith("smoke-test-wordlist.txt"))


class CrackStageValidationTests(TestCase):
    def test_dictionary_stage_requires_wordlist(self) -> None:
        with self.assertRaises(ValueError):
            CrackStage(name="bad", attack_mode="dictionary")

    def test_mask_stage_requires_mask(self) -> None:
        with self.assertRaises(ValueError):
            CrackStage(name="bad", attack_mode="mask")

    def test_mask_stage_with_mask_is_valid(self) -> None:
        stage = CrackStage(name="ok", attack_mode="mask", mask="?d?d?d?d")
        self.assertEqual(stage.mask, "?d?d?d?d")


class FingerprintTests(TestCase):
    def test_fingerprint_changes_with_hash_type(self) -> None:
        crackplan = load_crackplan(find_builtin_crackplan("smoke-test"))
        stage = crackplan.stages[0]

        fp_md5 = fingerprint_crack_stage("hashes.txt", 0, crackplan, stage, project_id=1)
        fp_ntlm = fingerprint_crack_stage("hashes.txt", 1000, crackplan, stage, project_id=1)

        self.assertNotEqual(fp_md5, fp_ntlm)

    def test_fingerprint_is_scoped_to_project(self) -> None:
        crackplan = load_crackplan(find_builtin_crackplan("smoke-test"))
        stage = crackplan.stages[0]

        fp_project_1 = fingerprint_crack_stage("hashes.txt", 0, crackplan, stage, project_id=1)
        fp_project_2 = fingerprint_crack_stage("hashes.txt", 0, crackplan, stage, project_id=2)

        self.assertNotEqual(fp_project_1, fp_project_2)
