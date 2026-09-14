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

    def test_reg_path_segment_is_signup(self):
        self.assertTrue(
            SignupFlowClassifierEngine._url_is_requested_entry(
                "https://passport.58.com/reg/", "signup"
            )
        )

    def test_reg_substring_is_not_signup(self):
        self.assertFalse(
            SignupFlowClassifierEngine._url_is_requested_entry(
                "https://example.com/region/news", "signup"
            )
        )


if __name__ == "__main__":
    unittest.main()
