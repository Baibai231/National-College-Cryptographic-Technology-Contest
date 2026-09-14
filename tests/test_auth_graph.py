import copy
import unittest

from application_security.auth_graph import AUTH_GRAPH_MANIFEST, build_auth_graph


class AuthenticationGraphTests(unittest.TestCase):
    def setUp(self):
        self.entries = {
            "login": {
                "flow_type": "direct_password",
                "stop_reason": "password_step_reached",
                "states": [
                    {
                        "step": 1,
                        "url": "https://example.com/",
                        "ui_type": "standalone_page",
                        "fields": [],
                        "actions": ["entry_click"],
                        "blockers": [],
                        "methods": [],
                    },
                    {
                        "step": 2,
                        "url": "https://example.com/login",
                        "ui_type": "modal",
                        "fields": ["identifier", "password"],
                        "actions": ["tab_click"],
                        "blockers": [],
                        "methods": ["sso", "github"],
                    },
                    {
                        "step": 3,
                        "url": "https://example.com/login",
                        "ui_type": "modal",
                        "fields": ["phone", "code"],
                        "actions": [],
                        "blockers": ["sms_code"],
                        "methods": ["sms"],
                    },
                ],
            },
            "signup": {
                "flow_type": "verification_then_password",
                "states": [
                    {
                        "step": 1,
                        "url": "https://example.com/register",
                        "fields": ["email", "code"],
                        "actions": [],
                        "blockers": ["email_code"],
                        "methods": [],
                    }
                ],
            },
        }

    def test_login_and_signup_are_separate_graph_branches(self):
        graph = build_auth_graph("example.com", self.entries).to_dict()
        node_ids = {node["node_id"] for node in graph["nodes"]}
        self.assertIn("login:entry", node_ids)
        self.assertIn("signup:entry", node_ids)
        self.assertIn("login:method:password", node_ids)
        self.assertIn("signup:method:email_code", node_ids)
        self.assertNotEqual("login:entry", "signup:entry")

    def test_graph_preserves_parallel_methods_and_gates(self):
        graph = build_auth_graph("example.com", self.entries).to_dict()
        node_ids = {node["node_id"] for node in graph["nodes"]}
        self.assertIn("login:method:github", node_ids)
        self.assertIn("login:method:sso", node_ids)
        self.assertIn("login:method:sms", node_ids)
        self.assertIn("login:gate:sms_code", node_ids)
        relations = {edge["relation"] for edge in graph["edges"]}
        self.assertIn("advance", relations)
        self.assertIn("switch_view", relations)
        self.assertIn("blocked_by", relations)

    def test_graph_contains_traceable_page_evidence(self):
        graph = build_auth_graph("example.com", self.entries).to_dict()
        self.assertEqual(len(graph["evidence"]), 4)
        self.assertTrue(all(item["level"] == "observed"
                            for item in graph["evidence"]))
        self.assertIn(
            "al-roomi-login-policies-usenix23", graph["paper_ref_ids"])

    def test_builder_does_not_mutate_legacy_records(self):
        before = copy.deepcopy(self.entries)
        build_auth_graph("example.com", self.entries)
        self.assertEqual(self.entries, before)

    def test_manifest_declares_crypto_and_papers(self):
        self.assertTrue(AUTH_GRAPH_MANIFEST.crypto_elements)
        self.assertTrue(AUTH_GRAPH_MANIFEST.paper_refs)


if __name__ == "__main__":
    unittest.main()
