import unittest

from scripts.generate_profiles import _render_summary_table


class GenerateProfilesSummaryTests(unittest.TestCase):
    def test_summary_can_prefix_profile_links(self):
        route = {
            "raw_result": {"flow_type": "unknown"},
            "observed_route": "未确认具体方式",
            "password_state": "not_observed_in_safely_reachable_flow",
            "policy": {},
            "safe_stop": "已走完当前安全可达范围",
        }
        payloads = [{
            "sites": [{
                "id": "example.com",
                "name": "example.com",
                "automatic": {"login": route, "signup": route},
            }],
        }]

        profile_index = _render_summary_table(payloads)
        site_summary = _render_summary_table(payloads, "profiles/")

        self.assertIn("(example.com.md)", profile_index)
        self.assertIn("(profiles/example.com.md)", site_summary)


if __name__ == "__main__":
    unittest.main()
