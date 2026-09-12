import unittest

from utils.signup_candidates import (
    rank_auth_entry_candidates,
    rank_signup_candidates,
    registered_domain,
    same_registered_site,
)


class SignupCandidatesTest(unittest.TestCase):
    def test_registered_domain_handles_common_country_suffixes(self):
        self.assertEqual(registered_domain("passport.example.com.cn"), "example.com.cn")
        self.assertEqual(registered_domain("www.example.co.uk"), "example.co.uk")
        self.assertTrue(same_registered_site(
            "https://www.example.com.cn", "https://account.example.com.cn/register"))

    def test_observed_signup_link_outranks_generated_path(self):
        ranked = rank_signup_candidates("https://www.example.com/", [{
            "href": "https://accounts.example.com/create-account?src=home",
            "innerText": "Create account",
            "score": 42,
        }])
        self.assertEqual(
            ranked[0]["url"],
            "https://accounts.example.com/create-account?src=home")
        self.assertEqual(ranked[0]["source"], "observed_link")

    def test_cross_site_and_destructive_links_are_excluded(self):
        ranked = rank_signup_candidates("https://example.com/", [
            {"href": "https://evil.test/signup", "innerText": "Sign up"},
            {"href": "/account/delete", "innerText": "Delete account"},
            {"href": "/support/register-product", "innerText": "Register product"},
        ])
        urls = {item["url"] for item in ranked}
        self.assertNotIn("https://evil.test/signup", urls)
        self.assertNotIn("https://example.com/account/delete", urls)
        self.assertNotIn("https://example.com/support/register-product", urls)

    def test_login_only_link_does_not_displace_signup_candidates(self):
        ranked = rank_signup_candidates("https://example.com/", [
            {"href": "/login", "innerText": "Log in", "score": 1000},
        ], limit=3)
        self.assertTrue(ranked)
        self.assertTrue(all("/login" not in item["url"] for item in ranked))

    def test_fragments_are_deduplicated(self):
        ranked = rank_signup_candidates("https://example.com/", [
            {"href": "/signup#email", "innerText": "Sign up"},
            {"href": "/signup#phone", "innerText": "Register"},
        ])
        signup = [item for item in ranked if item["url"] == "https://example.com/signup"]
        self.assertEqual(len(signup), 1)

    def test_login_page_is_ranked_as_shallow_crawl_entry(self):
        ranked = rank_auth_entry_candidates("https://example.com/", [
            {"href": "/login", "innerText": "Log in"},
            {"href": "/news", "innerText": "News"},
        ])
        self.assertEqual(ranked[0]["url"], "https://example.com/login")
        self.assertEqual(ranked[0]["intent"], "login")

    def test_auth_entry_ranking_rejects_cross_site(self):
        ranked = rank_auth_entry_candidates("https://example.com/", [
            {"href": "https://evil.test/login", "innerText": "Log in"},
        ])
        self.assertEqual(ranked, [])

    def test_generic_product_cta_is_not_signup(self):
        ranked = rank_auth_entry_candidates("https://example.com/", [
            {"href": "/connect", "innerText": "Get started"},
        ])
        self.assertEqual(ranked, [])

    def test_css_registration_class_does_not_turn_product_link_into_signup(self):
        ranked = rank_auth_entry_candidates("https://gandi.example/", [{
            "href": "/en/domain",
            "innerText": "Domain names",
            "className": "registration button",
        }])
        self.assertEqual(ranked, [])

    def test_domain_registration_is_not_account_signup(self):
        ranked = rank_auth_entry_candidates("https://gandi.example/", [{
            "href": "/en/domain",
            "innerText": "Register a domain",
        }])
        self.assertEqual(ranked, [])

    def test_event_registration_subdomain_is_not_account_signup(self):
        ranked = rank_auth_entry_candidates("https://example.com/", [{
            "href": "https://events.example.com/conference/begin",
            "innerText": "Register",
        }])
        self.assertEqual(ranked, [])

    def test_login_only_in_next_query_does_not_taint_link(self):
        ranked = rank_auth_entry_candidates("https://example.com/", [{
            "href": "/explore?next=%2Flogin", "innerText": "Explore",
        }])
        self.assertEqual(ranked, [])

    def test_compound_email_signup_path_is_recognized(self):
        ranked = rank_auth_entry_candidates("https://instagram.example/", [{
            "href": "/accounts/emailsignup/?next=%2Fwelcome",
            "className": "signup-link",
        }])
        self.assertEqual(ranked[0]["intent"], "signup")


if __name__ == "__main__":
    unittest.main()
