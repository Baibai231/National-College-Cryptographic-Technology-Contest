import unittest

from signup_flow_classifier.evidence import record_step, semantic_state_key
from signup_flow_classifier.flow_types import FlowResult, PageState


class SemanticStateGraphTests(unittest.TestCase):
    def test_volatile_query_and_action_history_do_not_duplicate_state(self):
        result = FlowResult(site="example.com")
        first = PageState(
            step=1,
            url="https://example.com/auth?nonce=one",
            ui_type="modal",
            fields=["phone", "code"],
            blockers=["sms_code"],
            methods=["phone"],
            available_actions=["send_code"],
            tabs=["password_tab"],
        )
        repeated = PageState(
            step=4,
            url="https://example.com/auth?nonce=two#login",
            ui_type="modal",
            fields=["code", "phone"],
            blockers=["sms_code"],
            methods=["phone"],
            available_actions=["send_code"],
            tabs=["password_tab"],
            actions=["tab_click"],
            note="returned from another branch",
        )

        self.assertIs(record_step(result, first), first)
        self.assertIs(record_step(result, repeated), first)
        self.assertEqual(len(result.states), 1)
        self.assertIn("step=4;state_revisit_of=1", result.evidence)
        self.assertEqual(semantic_state_key(first), semantic_state_key(repeated))

    def test_materially_different_fields_create_a_new_state(self):
        result = FlowResult(site="example.com")
        record_step(result, PageState(
            step=1, url="https://example.com/auth", fields=["phone", "code"]
        ))
        record_step(result, PageState(
            step=2, url="https://example.com/auth", fields=["email", "password"]
        ))
        self.assertEqual(len(result.states), 2)

    def test_query_routed_signup_and_login_remain_distinct(self):
        signup = PageState(
            url="https://passport.example.com/v2/?reg&nonce=secret",
            fields=["identifier", "password"],
        )
        login = PageState(
            url="https://passport.example.com/v2/?login&nonce=other",
            fields=["identifier", "password"],
        )
        self.assertNotEqual(semantic_state_key(signup), semantic_state_key(login))


if __name__ == "__main__":
    unittest.main()
