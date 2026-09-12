import unittest
from unittest.mock import Mock
from unittest import mock

from selenium.webdriver.common.by import By

from utils.login_link_discovery import LoginLinkDiscovery


class LoginLinkDiscoveryTests(unittest.TestCase):
    def test_open_signup_hint_requires_same_site_and_auth_signal(self):
        driver = Mock()
        driver.current_url = "https://accounts.example.co.uk/register"
        discovery = LoginLinkDiscovery(driver)
        discovery.inject = Mock()
        discovery._wait_for_page_ready = Mock()
        discovery._wait_for_spa_render = Mock()
        discovery._page_has_auth_signal = Mock(return_value=True)

        opened = discovery.open_signup_hint(
            "https://www.example.co.uk/",
            "https://accounts.example.co.uk/register",
        )
        self.assertEqual(opened, driver.current_url)
        driver.get.assert_called_once()
        self.assertTrue(discovery._entry_clicked)

        driver.reset_mock()
        self.assertIsNone(discovery.open_signup_hint(
            "https://example.co.uk/", "https://attacker.test/signup"))
        driver.get.assert_not_called()

    def test_try_switch_to_signup_tab_follows_new_window(self):
        driver = mock.MagicMock()
        driver.current_url = "https://passport.baidu.com/v2/?reg"
        driver.execute_cdp_cmd.return_value = {
            "result": {"value": {"found": True, "text": "立即注册"}}
        }
        driver.find_element.return_value = mock.MagicMock()
        type(driver).window_handles = mock.PropertyMock(
            side_effect=[["old"], ["old", "new"]]
        )

        discovery = LoginLinkDiscovery(driver)
        discovery._wait_for_page_ready = mock.MagicMock()
        discovery.reinject_into_current_tab = mock.MagicMock()
        discovery.find_password_fields = mock.MagicMock(
            return_value=["//*[@id='TANGRAM__PSP_4__password']"]
        )

        with mock.patch("time.sleep", return_value=None):
            switched = discovery._try_switch_to_signup_tab()

        self.assertTrue(switched)
        self.assertTrue(discovery._entry_clicked)
        driver.find_element.assert_called_once_with(
            By.CSS_SELECTOR, "[data-ap-signup-tab='1']"
        )
        driver.switch_to.window.assert_called_once_with("new")
        discovery.reinject_into_current_tab.assert_called_once_with()
        discovery.find_password_fields.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
