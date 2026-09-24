from unittest import TestCase

from obliquity.cli import recommend_gameplan


def _host(tech=None, server=None, profile="generic"):
    return {"tech": tech, "server": server, "profile": profile}


class RecommendGameplanTests(TestCase):
    def test_tech_takes_priority(self) -> None:
        name, reason = recommend_gameplan(_host(tech="aspnet", server="iis"))
        self.assertEqual(name, "aspnet-standard")
        self.assertEqual(reason, "tech=aspnet")

    def test_php_tech(self) -> None:
        name, reason = recommend_gameplan(_host(tech="php"))
        self.assertEqual(name, "php-standard")

    def test_server_used_when_tech_unknown(self) -> None:
        name, reason = recommend_gameplan(_host(tech=None, server="iis"))
        self.assertEqual(name, "aspnet-standard")
        self.assertEqual(reason, "server=iis")

    def test_profile_app_type_used_when_tech_unknown(self) -> None:
        name, reason = recommend_gameplan(_host(profile="api"))
        self.assertEqual(name, "api-quick")
        self.assertEqual(reason, "profile=api")

    def test_profile_outranks_server(self) -> None:
        # app-type (api) is more intentful than the web server (iis)
        name, reason = recommend_gameplan(_host(profile="api", server="iis"))
        self.assertEqual(name, "api-quick")
        self.assertEqual(reason, "profile=api")

    def test_tech_value_in_profile_slot_no_longer_matches(self) -> None:
        # cleanup: aspnet/php belong to --tech now, not --profile, so putting a
        # tech value in the profile slot falls through (no overlap).
        name, reason = recommend_gameplan(_host(profile="aspnet"))
        self.assertEqual(name, "generic-quick")
        self.assertIsNone(reason)

    def test_falls_back_to_generic_quick_with_no_reason(self) -> None:
        name, reason = recommend_gameplan(_host(profile="generic"))
        self.assertEqual(name, "generic-quick")
        self.assertIsNone(reason)

    def test_matching_is_case_insensitive(self) -> None:
        name, reason = recommend_gameplan(_host(tech="ASPnet"))
        self.assertEqual(name, "aspnet-standard")

    def test_none_fields_do_not_crash(self) -> None:
        name, reason = recommend_gameplan({"tech": None, "server": None, "profile": None})
        self.assertEqual(name, "generic-quick")
        self.assertIsNone(reason)
