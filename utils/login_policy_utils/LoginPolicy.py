import base64
import difflib
import json
import random
import re
import string
import time
from typing import List, Dict, Optional, Iterator
from urllib.parse import unquote

import loguru
import requests
from bs4 import BeautifulSoup
from requests import Response
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait

from LoginRegexes import LoginRegexes
from config.config import Config
from utils.APDriver import APDriver
from utils.PasswordPolicy import PasswordPolicy
from utils.Regexes import Regexes
from utils.URLUtils import URLUtils
from utils.login_policy_utils import LoginPolicyException as LPException
from utils.util_redis import UtilRedis
from utils.ImageOCRUtils import ImageOCRUtils

tmp_login_info: Dict[str, dict] = {
    "github.com": {
        "login_url": "https://github.com/login",
        "is_iframe": 0,
        "iframe_xpath": "",
        "is_click": 0,
        "click_xpath": "",
        "form_xpath": "//html/BODY/DIV[1]/DIV[3]/MAIN[1]/DIV[1]/DIV[4]/FORM[1]"
    },
    "douban.com": {
        "login_url": "https://douban.com",
        "is_iframe": 1,
        "iframe_xpath": "//html/body/div[2]/div[1]/div[1]/iframe[1]",
        "is_click": 1,
        "click_xpath": "//html/body/div[1]/div[1]/ul[1]/li[2]",
        "form_xpath": "//html/BODY/DIV[1]/DIV[2]/DIV[1]"
    }
}


# The main class for reproducing the login policy inference process of USENIX Security 2023 by Frank Li
class LoginPolicy(PasswordPolicy):
    # CTwo original passwords for registration
    _correct_password_list: List[str] = ["MxT7zcS4k5-@", "MxT7zct41S"]
    # Correct password after testing registration, testing order is the index of the list
    _correct_password: str = ""

    HTTP_STATUS_CODE: int = 0
    HTTP_IS_REDIRECTED: int = 1
    HTTPS_STATUS_CODE: int = 2
    HTTPS_IS_REDIRECTED: int = 3

    _forbidden_suffixes: str = (
        r"\.(mp3|wav|wma|ogg|mkv|zip|tar|xz|rar|z|deb|bin|"
        r"iso|csv|tsv|dat|txt|css|log|sql|xml|sql|mdb|apk|"
        r"bat|bin|exe|jar|wsf|fnt|fon|otf|ttf|ai|bmp|gif|"
        r"ico|jp(e)?g|png|ps|psd|svg|tif|tiff|cer|rss|key|"
        r"odp|pps|ppt|pptx|c|class|cpp|cs|h|java|sh|swift|"
        r"vb|odf|xlr|xls|xlsx|bak|cab|cfg|cpl|cur|dll|dmp|"
        r"drv|icns|ini|lnk|msi|sys|tmp|3g2|3gp|avi|flv|"
        r"h264|m4v|mov|mp4|mp(e)?g|rm|swf|vob|wmv|doc(x)?|"
        r"odt|pdf|rtf|tex|txt|wks|wps|wpd|js)$")

    def __init__(self, logger: loguru.logger, test_site: str, my_redis: UtilRedis) -> None:
        """ The constructor of LoginPolicy class

        Args:
            logger: loguru.logger, the logger for logging the process
            test_site: str, the tested site for login policy inference
            my_redis: UtilRedis, the implementation for redis database operation
        """
        self._driver: APDriver = None
        self._my_logger: loguru.logger = logger
        self._my_logger.add("./test.log")
        self._target: str = test_site
        self._domain: str = URLUtils.get_domain(test_site, strip_www=True)
        self._redis: UtilRedis = my_redis
        self._login_form_info: dict = tmp_login_info[self._domain]

    def init_driver(self, driver: APDriver) -> None:
        if not self._driver:
            self._driver = driver

    def _is_url_redirect(self) -> list:
        """ Secure login environment -- whether the page is redirected

        Returns:
            ret_list: list
                0: HTTP Status code, e.g., 200
                1: Whether the http page is redirected
                2: HTTPS Status code, e.g., 200
                3: Whether the https page is redirected
        """
        ret_list: list = [-1, -1, -1, -1]
        # If the driver is not initialized, return the original list
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return ret_list
        # Get the domain of the url
        domain_name: str = URLUtils.strip_scheme(self._target)
        # The script for return the status code for the login page
        status_code_script: str = "return window.performance.getEntries()[0]['responseStatus']"
        try:
            # Access the HTTP page
            http_url: str = "http://" + domain_name
            self._driver.get(http_url)
            WebDriverWait(self._driver, 0.5)
            http_status_code: str = self._driver.execute_script(status_code_script)
            self._my_logger.debug(f"HTTP status code: {http_status_code}")
            # Digit 1 means that the status code is 200
            ret_list[self.HTTP_STATUS_CODE] = 1 if http_status_code == "200" else 0
            http_current_url = self._driver.current_url()

            if URLUtils.main_url(http_url) != URLUtils.main_url(http_current_url):
                if URLUtils.get_scheme(http_current_url) == "https":
                    self._my_logger.info(f"The HTTP url {http_url} has transferred into HTTPS url {http_current_url}.")
                    # 2 -> redirect for https
                    ret_list[self.HTTP_IS_REDIRECTED] = 2
                else:
                    # 1 -> no scheme changed
                    self._my_logger.info(f"The url {http_url} has transferred into url {http_current_url}.")
                    ret_list[self.HTTP_IS_REDIRECTED] = 1
            else:
                # 0 -> no redirection
                self._my_logger.info("No redirection has happened.")
                ret_list[self.HTTP_IS_REDIRECTED] = 0

            # Access HTTPS page
            https_url: str = "https://" + domain_name
            self._driver.get(https_url)
            WebDriverWait(self._driver, 0.5)
            https_status_code: str = self._driver.execute_script(status_code_script)
            self._my_logger.debug(f"HTTPS status code: {https_status_code}")
            ret_list[self.HTTPS_STATUS_CODE] = 1 if https_status_code == "200" else 0
            https_current_url: str = self._driver.current_url()
            if URLUtils.main_url(https_url) != URLUtils.main_url(https_current_url):
                # 1 -> no scheme changed
                self._my_logger.info(f"The url {https_url} has transferred into url {https_current_url}.")
                ret_list[self.HTTPS_IS_REDIRECTED] = 1
            else:
                # 0-> no redirection
                self._my_logger.info("No redirection has happened.")
                ret_list[self.HTTPS_IS_REDIRECTED] = 0
        except Exception as ex:
            self._my_logger.error(f"Something bad has happened ... {str(ex)}")
            ret_list = [-1, -1, -1, -1]
        return ret_list

    def _check_mixed_content_error(self) -> bool:
        """ Secure login environment -- https page mixed content errors (Heuristic)

        Returns:
            bool, whether the https page has mixed content errors ...
        """
        domain_name: str = "https://" + URLUtils.strip_scheme(self._target)
        try:
            request_proxy: dict = {
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890"
            }
            response = requests.get(domain_name, timeout=5, proxies=request_proxy)
            response.raise_for_status()
            html_content: str = response.text
            # Parse the HTML content using BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            # Check if any of the elements have http:// instead of https
            mixed_content_errors = []
            elements_sets: set = set()
            # Find all elements with specific attributes
            elements_with_attributes: dict = {
                "src": ["script", "img", "link", "audio", "video", "source", "iframe", "embed", "a"],
                "href": ["a", "link"],
                "action": ["form"],
                "srcset": ["img", "source"],
                "data-src": ["img"],
                "data": ["object"],
                "value": ["param"]
            }
            for attr_key, element_value in elements_with_attributes.items():
                elements_list: list = soup.find_all(elements_with_attributes[attr_key])
                for element in elements_list:
                    if attr_key in element.attrs:
                        elements_sets.add(element[attr_key])

            elements_list = list(elements_sets)
            for attribute_value in elements_list:
                if attribute_value.startswith("http://"):
                    mixed_content_errors.append(f"Mixed content error: {attribute_value} in {domain_name}")
            if mixed_content_errors:
                self._my_logger.warning("Mixed content errors found.")
                for error in mixed_content_errors:
                    self._my_logger.warning(error)
                return True
            else:
                self._my_logger.info("No mixed content errors found.")
                return False
        except requests.exceptions.RequestException as e:
            self._my_logger.error(f"Error fetching {domain_name}: {e}")
            return False

    def _mixed_content_error_in_log(self) -> dict:
        """ Secure login environment -- https page mixed content errors (In logs)

        get the mixed_content_error using chrome log

        Returns:
            Return a list which consists of warning logs and error logs as two lists
        """
        ret_dict = {
            "warning_log": [],
            "error_log": [],
            "severe_log": [],
            "critical_log": []
        }
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return {}
        self._driver.get(self._target)
        browser_logs = self._driver.get_log("browser")
        for browser_log in browser_logs:
            if "level" in browser_log:
                if browser_log["level"] == "WARNING":
                    ret_dict["warning_log"].append(browser_log["message"])
                elif browser_log["level"] == "ERROR":
                    ret_dict["error_log"].append(browser_log["message"])
                elif browser_log["level"] == "SEVERE":
                    ret_dict["severe_log"].append(browser_log["message"])
                elif browser_log["level"] == "CRITICAL":
                    ret_dict["critical_log"].append(browser_log["message"])
                else:
                    continue
        return ret_dict

    def check_secure_login_environment(self) -> dict:
        """ [Callable] Checking secure login environment

        Returns:
            return the dict for all testing scenarios
                - http_status_code
                - http_redirect
                - https_status_code
                - https_redirect
                - mixed_content_error
                - chrome_dev_tools_log
        """
        ret_list = self._is_url_redirect()
        ret_dict = {
            "http_status_code": ret_list[self.HTTP_STATUS_CODE],
            "http_redirect": ret_list[self.HTTP_IS_REDIRECTED],
            "https_status_code": ret_list[self.HTTPS_STATUS_CODE],
            "https_redirect": ret_list[self.HTTPS_IS_REDIRECTED],
            "mixed_content_error": self._check_mixed_content_error(),
            "chrome_dev_tools_log": self._mixed_content_error_in_log()
        }
        return ret_dict

    def _input_value(self,
                     element: WebElement,
                     value: str,
                     is_human: bool = False,
                     is_uncommon_char: bool = False) -> None:
        """ Account Credential Entry: copy & paste test

        Simulating copy/paste or human tap behaviors ...

        Args:
            element: WebElement, usually the password field
            value: str, the filled value
            is_human: bool, True means we need to simulate the user to input
            is_uncommon_char: bool, True means that we need to use JavaScript script to input the value
        """
        try:
            if not self._driver:
                self._my_logger.error("Please initialize the driver first ...")
                return
            # JavaScript Script to clear the input field
            js_clean_value_script: str = """
            var elm = arguments[0];
            elm.value = '';
            elm.dispatchEvent(new Event('change'));
            """
            # self._driver.execute_script(js_clean_value_script, element)
            element.clear()
            js_copy_paste_script = """
            var elm = arguments[0], txt = arguments[1];
            elm.value += txt;
            elm.dispatchEvent(new Event('change'));
            """
            if is_human:
                for one_char in value:
                    if is_uncommon_char:
                        self._driver.execute_script(js_copy_paste_script, element, one_char)
                    else:
                        element.send_keys(one_char)
                    time.sleep(round(random.uniform(0.1, 0.5), 2))
            else:
                if is_uncommon_char:
                    self._driver.execute_script(js_copy_paste_script, element, value)
                else:
                    element.send_keys(value)
            if is_uncommon_char:
                actions = ActionChains(self._driver)
                actions.send_keys(Keys.TAB).perform()
                time.sleep(0.1)
                actions.move_to_element(element).click().perform()
        except LPException.ImproperProcessException as e:
            raise LPException.ImproperProcessException(f"Executing JavaScript Code Fails ... {e}")

    def check_whether_copy_paste_allowed(self, element: WebElement, value: str, is_uncommon: bool = False) -> bool:
        """ Check whether the copy and paste method is allowed for the specific input field

        Args:
            element: WebElement, the tested web element
            value: str, the filled string
            is_uncommon: bool, whether the inputted value has special characters like emoji

        Returns:
            bool, Return whether the copy and paste method is allowed
        """
        self._input_value(element, value, False, is_uncommon)
        if element.get_attribute("value") != "" and value == element.get_attribute("value"):
            self._my_logger.success("This website allows users to copy and paste the password ...")
            return True
        else:
            self._input_value(element, value, True, is_uncommon)
            time.sleep(1)
            if element.get_attribute("value") != "" and value == element.get_attribute("value"):
                self._my_logger.warning("This website disallows users to copy and paste the password ...")
                return False
            else:
                self._my_logger.error("The site does not allow driver to fill the field ... or other bad things ")
                return False

    def _get_form_action(self, form_element: WebElement) -> str:
        """ [Temporary] Password transmission https check

        Check whether the password is transmitted through HTTPS
        Args:
            form_element: WebElement, the expected input webelement is a Form Element

        Returns:
            str, the expected return value is the action attribute or empty string
            e.g., a form without action or a no-form element
        """
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return ""

        if form_element.tag_name.lower() == "form":
            action_attribute = form_element.get_attribute("action")
            if action_attribute:
                return action_attribute
        else:
            return ""

    def get_form_action(self, form_element: WebElement) -> str:
        return self._get_form_action(form_element)

    def check_transfer_security(self, form_element: WebElement) -> bool:
        action = self.get_form_action(form_element)
        if action.startswith("http://"):
            return False
        else:
            return True

    @staticmethod
    def _initialize_typo_password_dict(correct_password: str) -> Dict[str, str]:
        """ Initialize the typo password dictionary

        Args:
            correct_password: str,
                we need construct the correct password carefully
                -> at least, it should have lowercase letters, and end up with generally characters
        """

        def incorrect_case(pw: str) -> str:
            for idx, char in enumerate(pw):
                if char.isalpha():
                    first_char = char.swapcase()
                    result_str: str = pw[:idx] + first_char + pw[idx + 1:]
                    return result_str
            return pw

        def cap_locks_inverted_case(pw: str) -> str:
            return pw.swapcase()

        def cap_locks_all_upper(pw: str) -> str:
            return pw.upper()

        def extra_char(pw: str, is_front: bool = True) -> str:
            random_letter = random.choice(string.ascii_letters)
            if is_front:
                return random_letter + pw
            else:
                return pw + random_letter

        def missing_shift_key(pw: str) -> str:
            # Implement in Windows like keyboard, may need modification in OSX system
            swap_dict: Dict[str, str] = {
                "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
                "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
                "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
                "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
                "-": "_", "_": "-", "=": "+", "+": "=", "{": "[",
                "}": "]", ":": ";", ";": ":", "<": ",", ",": "<",
                ">": ".", ".": ">", "?": "/", "/": "?", "`": "~",
                "~": "`"
            }
            last_char: str = pw[-1]
            if last_char.isalpha():
                return pw[:-1] + last_char.swapcase()
            elif last_char in swap_dict:
                return pw[:-1] + swap_dict[last_char]
            return pw

        typo_password_dict: Dict[str, str] = {
            "incorrect_case": incorrect_case(correct_password),
            "cap_locks_inverted_case": cap_locks_inverted_case(correct_password),
            "cap_locks_all_upper": cap_locks_all_upper(correct_password),
            "extra_char_front": extra_char(correct_password, True),
            "extra_char_end": extra_char(correct_password, False),
            "missing_shift_key": missing_shift_key(correct_password)
        }
        return typo_password_dict

    def _pw_typo_tolerant_check(self) -> Dict[str, bool]:
        """ Password validation - Check domain's typo-tolerant policy

        Testing passwords with typos
        - Assert that the login url is found and user have registered in the site
        - Find the login form, and be able to input values to the form
        - Use the correct credential to do the pilot test
        - Use six types of typos to detect whether the domain is typo-tolerant
        """
        test_correct: bool = False
        max_retry_times: int = Config.VERIFY_LOGIN_RETRIES
        retires_times: int = 0
        ret_dict: Dict[str, bool] = {}
        try:
            # Assert that the correct password is obtained
            assert self._correct_password != "", "Correct password should not be empty."
            # Assert that the login info is obtained
            assert self._login_form_info is not None, "Login form info should be obtained."
            typo_password_dict = self._initialize_typo_password_dict(self._correct_password)
            while test_correct is False and retires_times <= max_retry_times:
                test_correct = self._verify_login(self._correct_password)
                retires_times += 1
            assert test_correct is True, "Correct credential are regarded as NOT true"
            for typo_type, typo_password in typo_password_dict.items():
                # if typo is accepted
                if self._verify_login(typo_password):
                    self._my_logger.success(f"Type {typo_type} is accepted!")
                    ret_dict[typo_type] = True
                else:
                    self._my_logger.info(f"Type {typo_type} is not accepted!")
                    ret_dict[typo_type] = False
                # Set the typo test interval for not being considered as bot =_=|||
                time.sleep(Config.TYPO_TEST_INTERVAL)
        except AssertionError as ae:
            self._my_logger.error(f"There are assertions that are not satisfied: {ae}")
        except Exception as oe:
            self._my_logger.error(f"No assertion errors happen: {oe}.")
        return ret_dict

    def pw_typo_tolerant_check(self) -> Dict[str, bool]:
        return self._pw_typo_tolerant_check()

    def _verify_login(self, test_password: str) -> bool:
        return self.login_fill_and_submit(test_password)

    def login_fill_and_submit(self, test_password: str = "") -> bool:
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return False
        login_url: str = self._login_form_info["login_url"]
        self._driver.get(login_url)
        time.sleep(1)
        # [# 1] Initialization, the original appearance when visiting the page
        body_element: WebElement = self._driver.find_element_by_tag_name("body")
        original_source: List[str] = self._driver.get_source_list(body_element)
        sf: dict = self._login_form_info
        # TODO: Consider to overwrite this function to add a log info
        self._driver.save_screenshot(Config.LOGIN_SCREENSHOT_PATH + f"{self._domain}_initial.png")
        if not sf:
            self._my_logger.warning("Did not locate signup form ... ")
            return False
        else:
            # If no `override_rules` are provided, APDriver will generate new ones.
            # To see what rules you can set see `utils/forms/FormElement.py`
            self._driver.execute_cdp_cmd("Network.enable", {})
            values, source_dict = self._driver.fill_and_submit(sf, test_password=test_password)
            logs: list = self._driver.get_log("performance")
            return self._verify_login_after_submit(sf, original_source, source_dict, logs)

    def _verify_login_after_submit(self, form_info: dict, original_source: list, sub_source: dict, logs: list) -> bool:
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return False
        """
        after_fill: After filling the forms, and before submitting the form
        after_sub: Right after submitting the form
        test_red: Seconds after submitting the form -> test captcha in this

        Args:
            original_source, list: the first element is the innerHTML, the rest items are inner iframes
            sub_source, dict: after_fill, after_sub, test_red ()
        """
        # Get into the iframe if needed
        is_iframe: bool = form_info["is_iframe"]
        if is_iframe:
            iframe_ele = self._driver.find_element_by_xpath(form_info["iframe_xpath"])
            self._driver.switch_to.frame(iframe_ele)

        # Initialize variables
        error_message: bool = False
        # When there is no captcha or captcha is solved
        captcha: bool = False
        verification: bool = False

        # Search for CAPTCHA and error messages
        # Note that when searching for CAPTCHA, should go into the iframe !
        try:
            find_captcha_list: List[str] = self._diff_two_source(
                "\n".join(sub_source["after_fill"]), "\n".join(sub_source["test_red"]))
            for i in find_captcha_list:
                # TODO: Modify this when encountering new CAPTCHA types
                if re.search(r"captcha", i, re.I) and i.startswith("<iframe"):
                    self._my_logger.info("CAPTCHA found, handling it ...")
                    # TODO: Modify this when we find ways to handle CAPTCHA automatically
                    time.sleep(0.3)
                    captcha = True
                else:
                    captcha = False
        except Exception as e:
            self._my_logger.error(f"Something bad happened: {e}")
            captcha = False
        self._driver.save_screenshot(Config.LOGIN_SCREENSHOT_PATH + f"{self._domain}_after_submission.png")
        solved_captcha: bool = True
        if not solved_captcha:
            # Cannot solve the CAPTCHA
            return False

        # Snapshot after handling the CAPTCHA
        error_message_list: List[str] = []
        # TODO: Should check whether the potential captcha is solved
        source_error_msg: bool = False
        current_body: WebElement = self._driver.find_element_by_tag_name("body")
        after_captcha: List[str] = self._driver.get_source_list(current_body)

        source_msg: str = self._get_err_msg_from_source(original_source[0], after_captcha[0], in_plain=True)
        if source_msg != "":
            source_error_msg = True

        ocr_error_msg: bool = False
        ocr_msg: str = self._get_err_msg_from_img(
            Config.LOGIN_SCREENSHOT_PATH + f"{self._domain}_initial.png",
            Config.LOGIN_SCREENSHOT_PATH + f"{self._domain}_after_submission.png"
        )

        if ocr_msg != "":
            ocr_error_msg = True

        tmp_dict_info: dict = {
            "u_name": "name",
            # "u_name": "login",
            "u_value": "daheiduo@foxmail.com",
            "p_name": "password",
            "p_value": "daheiduoyankdbaskjdhkasjhdkjashdi145.."
        }

        network_logs: str = self._get_err_msg_from_logs(self._driver, logs, tmp_dict_info)

        info_from_logs: bool = True if network_logs != "" else False

        if ocr_error_msg:
            self._my_logger.warning("[OCR Source] Error message found in OCR.")
            error_message = True
        elif info_from_logs:
            self._my_logger.warning("[Network Source] Error message found in Network Response.")
            error_message = True
        elif source_error_msg:
            self._my_logger.warning("[HTML Source] Error message found in source, needing further exploration.")
            error_message = True
        else:
            self._my_logger.info("[HTML Source] No error message found ...")

        # Find and iterate all input elements in this page
        # Find verification fields in this page / form elements
        # TODO: Re-consider this part: aiming to find email / phone verification ?
        input_list: List[WebElement] = self._driver.find_elements_by_tag_name("input")
        for i in input_list:
            if i.is_displayed():
                _input: WebElement = i
                _input_id: str = _input.get_attribute("id") or ""
                _input_label_ele_list: list = []
                if _input_id != "":
                    _input_label_ele_list: list = self._driver.find_elements_by_xpath(
                        f"//label[@for='{_input_id}']")
                # Get the label close to the input element
                _input_outer_html = _input.get_attribute("outerHTML") or ""
                if len(_input_label_ele_list) != 1:
                    _label_outer_html = ""
                else:
                    _label_outer_html = _input_label_ele_list[0].get_attribute("outerHTML") or ""
                if re.search(LoginRegexes.VERIFICATION_MSG, _input_outer_html, flags=re.I) is not None:
                    verification = True
                    self._my_logger.debug(f"Verification information found in input outer html ... {verification}")
                    break
                if re.search(LoginRegexes.VERIFICATION_MSG, _label_outer_html, flags=re.I) is not None:
                    verification = True
                    self._my_logger.debug(f"Verification information found in label outer html ... {verification}")
                    break

        if verification:
            self._my_logger.warning("Exiting for there are verification elements ... ")

        if error_message or verification:
            return False
        self._my_logger.info("No error message or verification is found; verify the login process.")

        tmp_info: List[str] = ["freedomFu"]

        return self._verify_login_heuristic(tmp_info)

    # [#8 Enhancement]
    def _verify_login_heuristic(self, login_info: List[str]) -> bool:
        # Use some heuristic methods to verify our login
        # Navigate to landing page
        new_driver = APDriver.boot(chrome=True)
        try:
            self._driver.get(self._target)
            page_source: str = self._driver.page_source()

            ocr_path: str = Config.LOGIN_SCREENSHOT_PATH + f"{self._domain}_verify_login.png"
            new_ocr_path: str = Config.LOGIN_SCREENSHOT_PATH + f"{self._domain}_new_verify_login.png"
            time.sleep(Config.SCREENSHOT_TIMEOUT)
            self._driver.save_screenshot(ocr_path)
            new_driver.get(self._target)
            new_page_source: str = new_driver.page_source()
            time.sleep(Config.SCREENSHOT_TIMEOUT)
            new_driver.save_screenshot(new_ocr_path)
            page_response: Response = requests.get(self._target, timeout=Config.REQUEST_TIMEOUT)
        except Exception as e:
            self._my_logger.error(f"Error in getting page response: {e}.")
            return False

        # Verify response
        if page_response is None or page_response.status_code >= 400:
            self._my_logger.error("The response shows the wrong result.")
            return False

        # May need to accept the Cookies

        # Search page HTML for account indicators (name, username, email)
        if (self._verify_account_indicator(page_source, ocr_path, login_info)
                and not self._verify_account_indicator(new_page_source, new_ocr_path, login_info)):
            self._verify_logout_indicator(self._driver)
            return True

        # Search page HTML for logout element
        if self._verify_logout_indicator(self._driver) and not self._verify_logout_indicator(new_driver):
            return True

        # Try to access the login page and find the login forms
        login_url: str = self._login_form_info["login_url"] or ""
        assert login_url != "", "The login url should be ready!"
        self._driver.get(login_url)
        cur_url: str = self._driver.current_url() or ""
        if cur_url != login_url:
            self._my_logger.warning("The login page is redirected!")
        # Try to find form
        try:
            login_forms: list = self._driver.get_login_forms()
            if len(login_forms) > 0:
                self._my_logger.warning("Found a login form ...")
                return False
            else:
                self._my_logger.info("Found no login forms ...")
                return True
        except Exception as e:
            # May need retry
            self._my_logger.error(f"Something bad happens: {e}")
        time.sleep(100)
        return False

    def _verify_account_indicator(self, page_source: str, ocr_path: str, login_info: List[str]) -> bool:
        try:
            login_info_regex = "|".join(login_info)
            img_util = ImageOCRUtils()
            ocr_source: List[str] = img_util.get_image_str_list(ocr_path)
            ocr_source.append(page_source)
            search_list: List[str] = ocr_source
            for search_ele in search_list:
                if re.search(f"(^|\\W)({login_info_regex})($|\\W)", search_ele):
                    self._my_logger.success("Successfully found account indicator ...")
                    return True
        except Exception as e:
            self._my_logger.error(f"Some errors happen when verifying the account indicator: {e}.")
        return False

    def _verify_logout_indicator(self, driver: APDriver) -> bool:
        try:
            # Find all clickable elements and find the inner text
            elements: List[WebElement] = driver.find_elements_by_css_selector(Regexes.CLICKABLE)
            located_btn: List[WebElement] = []
            for ele in elements:
                if not ele.is_displayed():
                    continue
                _inner_text: str = ele.text or ""
                _text: str = ele.get_attribute("textContent") or ""
                _value: str = ele.get_attribute("value") or ""
                if (re.search(Regexes.LOGOUT_KEYWORD, _inner_text, re.I)
                        or re.search(Regexes.LOGOUT_KEYWORD, _text, re.I)
                        or re.search(Regexes.LOGOUT_KEYWORD, _value, re.I)):
                    located_btn.append(ele)
            if len(located_btn) > 0:
                self._my_logger.success("Found logout indicators in button")
                return True
        except Exception as e:
            self._my_logger.error(f"Some errors happen when verifying the logout indicator: {e}.")
            pass

        try:
            # Find all links with logout keywords
            urls_ele: List[WebElement] = driver.find_elements_by_css_selector("a[href]")
            located_url: List[WebElement] = []
            for url in urls_ele:
                href_attr: str = url.get_attribute("href") or ""
                if re.search(Regexes.LOGOUT_KEYWORD, href_attr, re.I):
                    located_url.append(url)
            if len(located_url) > 0:
                self._my_logger.success("Found logout indicators in urls")
                return True
        except Exception as e:
            self._my_logger.error(f"Some errors happen when verifying the logout indicator: {e}.")
            return False
        self._my_logger.warning("Found no indicators to confirm the login success !")
        return False

    def test_verify_login_heuristic(self) -> bool:
        self._driver.get("https://github.com/login")
        time.sleep(30)
        tmp_info: List[str] = ["freedomFu"]
        return self._verify_login_heuristic(tmp_info)

    def test(self) -> bool:
        ret = False
        self._driver.get("https://github.com/login")
        time.sleep(2)

        email_address = "daheiduo@foxmail.com"
        test_password = "test_my_password_hei_duo"
        email_elem = self._driver.find_element(By.ID, value="login_field")
        pwd_elem = self._driver.find_element(By.ID, value="password")

        self._input_value(email_elem, email_address)
        time.sleep(2)
        self._input_value(pwd_elem, test_password)
        time.sleep(2)

        print(pwd_elem.get_attribute("value"))

        if pwd_elem.get_attribute("value") != "" and test_password == pwd_elem.get_attribute("value"):
            ret = True
            self._my_logger.success("This website allows users to copy and paste the password ...")
        else:
            self._input_value(pwd_elem, test_password, True)
            time.sleep(2)
            if pwd_elem.get_attribute("value") != "" and test_password == pwd_elem.get_attribute("value"):
                self._my_logger.warning("This website disallows users to copy and paste the password ...")
            else:
                self._my_logger.error("There is something amazing happening ... ")

        ap_log_list = self._driver.get_log("browser")
        if not ap_log_list:
            print("There is no log ...")
        for ap_log in ap_log_list:
            print("level: \t %s" % ap_log["level"])
            print("message: \t %s" % ap_log["message"])
            print("source: \t %s" % ap_log["source"])
            print("timestamp: \t %s" % ap_log["timestamp"])

        time.sleep(2)
        return ret

    def another_test(self) -> None:
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return
        url = "https://www.facebook.com/r.php?locale=en_US&display=page"
        self._driver.get(url)
        time.sleep(3)
        with open("../js/scripts.js", "r") as js_file:
            js_code = js_file.read()
            js_file.seek(0)
        form_element = self._driver.find_elements_by_tag_name("form")
        my_ret = self._driver.execute_script(js_code + "return detectSignUpForms(arguments[0]);", form_element[0])
        print(my_ret)
        time.sleep(3)

    def test_douban_login(self) -> None:
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return
        url = "https://accounts.douban.com/passport/login"
        self._driver.get(url)
        time.sleep(3)
        with open("../js/scripts.js", "r") as js_file:
            js_code = js_file.read()
            js_file.seek(0)
        li_password_login = self._driver.find_element_by_class_name("account-tab-account")
        li_password_login.click()
        form_element = self._driver.find_elements_by_class_name("account-form")
        for single_form_element in form_element:
            # print(i)
            my_ret = self._driver.execute_script(
                js_code + "return detectLoginForms(arguments[0]);",
                single_form_element)
            print(my_ret)

    def test_main(self) -> None:
        if not self._driver:
            self._my_logger.error("Please initialize the driver first ...")
            return
        login_urls = []
        signup_urls = []
        """ Configure the crawl
        """
        self._driver.crawl_init(self._target, bfs=True, depth=2, follow=[Regexes.AUTH])
        while self._driver.crawl_next():
            new_login_dict: dict = {
                "url": self._driver.current_url(),
                "login_form_info": []
            }
            new_signup_dict: dict = {
                "url": self._driver.current_url(),
                "signup_form_info": []
            }
            login_forms, signup_forms = self._driver.get_account_forms()
            print(login_forms)
            print(signup_forms)
            if login_forms:
                for login_form in login_forms:
                    new_login_dict["login_form_info"].append(login_form)
                    # print(self._driver.get_dompath(login_form))
                login_urls.append(new_login_dict)

            if signup_forms:
                for signup_form in signup_forms:
                    new_signup_dict["signup_form_info"].append(signup_form)
                signup_urls.append(new_signup_dict)

            if login_urls and signup_urls:
                break

        print("Login urls: %s" % login_urls)
        print("Signup urls: %s" % signup_urls)
        store_dict = {
            "login_url": "",
            "login_xpath": "",
            "signup_url": "",
            "signup_xpath": ""
        }

        if login_urls:
            store_dict["login_url"] = login_urls[0]["url"]
            login_form_list: list = login_urls[0]["login_form_info"]
            login_form_len: int = len(login_form_list)
            login_form_keys = range(login_form_len)
            store_dict["login_xpath"] = dict(zip(login_form_keys, login_form_list))

        if signup_urls:
            print(signup_urls[0]["signup_form_info"])
            store_dict["signup_url"] = signup_urls[0]["url"]
            signup_form_list: list = signup_urls[0]["signup_form_info"]
            signup_form_len: int = len(signup_form_list)
            signup_form_keys = range(signup_form_len)
            store_dict["signup_xpath"] = dict(zip(signup_form_keys, signup_form_list))

        if login_urls or signup_urls:
            _connected_redis = self._redis.connect_redis()
            _connected_redis.set(self._target, json.dumps(store_dict))
            self._redis.disconnect_redis()


if __name__ == '__main__':
    my_logger = loguru.logger
    ap_driver = APDriver.boot(chrome=True)
    util_redis = UtilRedis(my_logger)
    # my_domain = "https://github.com"
    my_domain = "https://douban.com"
    lp = LoginPolicy(my_logger, my_domain, util_redis)
    lp.init_driver(ap_driver)
    # lp.test_verify_login_heuristic()
    # lp.test_main()
    lp.login_fill_and_submit(test_password="daheiduoyankdbaskjdhkasjhdkjashdi145..")
    ap_driver.close()
