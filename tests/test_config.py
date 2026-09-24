from argparse import Namespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from obliquity.core import config
from obliquity.cli import normalize_host_target


class ActiveProjectConfigTests(TestCase):
    def test_roundtrip_set_get_clear(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OBLIQUITY_HOME": tmp}):
                self.assertIsNone(config.active_project())
                config.set_active_project("acme")
                self.assertEqual(config.active_project(), "acme")
                config.set_active_project("other")  # overwrite
                self.assertEqual(config.active_project(), "other")
                config.clear_active_project()
                self.assertIsNone(config.active_project())

    def test_corrupt_config_is_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OBLIQUITY_HOME": tmp}):
                config.config_path().parent.mkdir(parents=True, exist_ok=True)
                config.config_path().write_text("{not valid json")
                self.assertIsNone(config.active_project())  # no crash


class NormalizeHostTargetTests(TestCase):
    def test_url_in_project_slot_shuffles_to_url(self) -> None:
        args = Namespace(project="https://api.acme.com", url=None)
        normalize_host_target(args)
        self.assertIsNone(args.project)
        self.assertEqual(args.url, "https://api.acme.com")

    def test_plain_project_name_is_left_alone(self) -> None:
        args = Namespace(project="acme", url=None)
        normalize_host_target(args)
        self.assertEqual(args.project, "acme")
        self.assertIsNone(args.url)

    def test_both_given_is_untouched(self) -> None:
        args = Namespace(project="acme", url="https://api.acme.com")
        normalize_host_target(args)
        self.assertEqual(args.project, "acme")
        self.assertEqual(args.url, "https://api.acme.com")
