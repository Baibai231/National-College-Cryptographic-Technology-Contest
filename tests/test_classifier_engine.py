import unittest

from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine


class UrlEntrySemanticsTests(unittest.TestCase):
    def test_query_based_signup_url_is_recognized(self):
        self.assertTrue(
            SignupFlowClassifierEngine._url_is_requested_entry(
                "https://passport.baidu.com/v2/?reg", "signup"
            )
        )

    def test_query_based_login_url_is_not_signup(self):
        self.assertFalse(
            SignupFlowClassifierEngine._url_is_requested_entry(
                "https://passport.baidu.com/v2/?login", "signup"
            )
        )

    def test_path_based_signup_still_works(self):
        self.assertTrue(
            SignupFlowClassifierEngine._url_is_requested_entry(
                "https://example.com/register", "signup"
            )
        )


class _Input:
    def __init__(self, input_type="text", name="", element_id="",
                 autocomplete=""):
        self.attrs = {
            "type": input_type,
            "name": name,
            "id": element_id,
            "autocomplete": autocomplete,
        }
        self.accessible_name = ""

    def get_attribute(self, name):
        return self.attrs.get(name, "")

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True


class _FieldDriver:
    def __init__(self, fields):
        self.fields = fields

    def find_elements(self, _by, value):
        return self.fields if value == "input" else []


class PasswordFieldLocationTests(unittest.TestCase):
    def test_autocomplete_password_field_is_locatable(self):
        driver = _FieldDriver([
            _Input(name="credential", element_id="new-secret",
                   autocomplete="section-register new-password")
        ])
        located = SignupFlowClassifierEngine(driver)._locate_password_field()
        self.assertEqual(located["frame_path"], ())
        self.assertIn("new-password", located["xpath"])
        self.assertIn("@id='new-secret'", located["xpath"])

    def test_search_field_with_login_name_is_not_password(self):
        driver = _FieldDriver([
            _Input(input_type="search", name="login_password_search")
        ])
        self.assertIsNone(
            SignupFlowClassifierEngine(driver)._locate_password_field())

    def test_new_password_is_preferred_over_current_password(self):
        driver = _FieldDriver([
            _Input(input_type="password", element_id="login-secret",
                   autocomplete="current-password"),
            _Input(input_type="text", element_id="signup-secret",
                   autocomplete="new-password"),
        ])
        located = SignupFlowClassifierEngine(driver)._locate_password_field()
        self.assertIn("new-password", located["xpath"])
        self.assertIn("signup-secret", located["xpath"])

    def test_xpath_quotes_attribute_values_safely(self):
        element = _Input(
            input_type="password", element_id='user\'s "secret"')
        xpath = SignupFlowClassifierEngine._make_xpath(element)
        self.assertIn("concat(", xpath)


if __name__ == "__main__":
    unittest.main()
