#!~/anaconda3/env3/MyAUtomaticPolicy/bin/python
import os
import random

import loguru
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.common.by import By

import utils.util_str_generator as uusg
import utils.util_basic as uub

from utils.PasswordPolicy import PasswordPolicy
from utils.APDriver import APDriver
from utils.creation_policy_utils import CreationPolicyException as CPException


class CreationPolicy(PasswordPolicy):
    # default minimum length of tested password
    _min_len_val = 6
    # default medium length of tested password
    _mid_len_val = 10
    # default maximum length of tested password
    _max_len_val = 32
    # absolute path
    _abs_path = os.path.dirname(os.path.abspath(__file__))
    # default site name
    _site_name = "default_name.suffix"
    # default admissible password
    _admissible_password = ""
    # format of creation policy
    _creation_policy = {
        "length": {
            # the allowed maximum length
            "length_max": 0,
            # the allowed minimum length
            "length_min": 0
        },
        # False means the requirement is invalid
        "restrictive": {
            # Do not allow special symbols
            "re_disallow_sps": False,
            # Require multiple word structure
            "re_mul_words": False,
            # Require the password starts with a letter
            "re_letter_start": False,
            # The minimum number of digits
            "re_digit_min": 0,
            # The minimum number of uppercase letters
            "re_upper_min": 0,
            # The minimum number of lowercase letters
            "re_lower_min": 0,
            # The minimum number of letters
            "re_letter_min": 0,
            # The minimum number of special symbols
            "re_symbol_min": 0,
            # Two of (letter, digit, symbol) is required
            "re_combination_2_of_3": False,
            # Two of (upper, lower, digit, symbol) is required
            "re_combination_2_of_4": False,
            # Three of (upper, lower, digit, symbol) is required
            "re_combination_3_of_4": False
        },
        # False means this kind of character is not allowed
        "permissive": {
            "permitted_characters": {
                # Allow space character
                "pr_space": False,
                # Allow unicode characters
                "pr_unicode": False,
                # Allow emoji characters
                "pr_emoji": False,
                # Allow special symbol .
                "pr_symbol_dot": False,
                # Allow special symbol !
                "pr_symbol_exclamation": False,
                # Allow special symbol _
                "pr_symbol_underline": False,
                # Allow special symbol #
                "pr_symbol_hashtag": False
            },
            "permitted_sequences": {
                # Repetitive characters: 111 aaa
                "pr_repetitive": False,
                # Sequential characters: 123 abc
                "pr_sequential": False,
                # Dictionary strings: google apple
                "pr_dictionary": False,
                # Identifier information: username, email, name
                "pr_identifier": False
            },
            "short_and_long_password": {
                # Password consisting of short digits
                "pr_short_digit": False,
                # Password consisting of long digits
                "pr_long_digit": False
            },
            "breached_passwords": {
                "pr_breached": False
            }
        }
    }

    # the default admissible password list
    _admissible_password_list = {
        "6": [
            "M-7c4@", "M-7cS@", "Mx-7c@", "Mx7c4@", "Mx7cS@",
            "M-7cS4", "M-7S4@", "x-7c4@", "Mx-cS@", "Mx7cS4"
        ],
        "7": [
            "M7-cS4@", "Mx7-c4@", "Mx-cS4@", "Mx7-cS4", "Mx7zcS4"
        ],
        "8": [
            "Mx7-cS4@", "MxT7zcS4"
        ],
        "9": [
            "Mx7-cS4@y", "MxT7zcS4t"
        ],
        "10": [
            "MxT7zcS4-@", "MxT7zcS4t1"
        ]
    }

    # [PROTECTED -- BEGIN]
    def _find_admissible_password(self) -> str:
        """ Find the admissible password

        Returns:
            Return the admissible password

        Raises:
            NoAdmissiblePasswordException: Unable to find the admissible password
        """
        # Set the return flag, if admissible password found, set flag to True and break the loop
        ret_flag = False
        self._logger.info(f"Begin finding the admissible password for {self._site_name}.")
        for i in range(self._min_len_val, self._max_len_val + 1):
            test_pwd_list = self._admissible_password_list[str(i)]
            for pwd in test_pwd_list:
                # TODO: Remove this code when our <check whether a process is successful or not> module is finished
                if self._test_one_password(pwd, self._find_admissible_password.__name__):
                    ret_flag = True
                    self._admissible_password = pwd
                    self._logger.success(f"Successfully find the admissible password {self._admissible_password}")
                    break
            if ret_flag:
                break
        if not ret_flag:
            self._logger.warning("There is no admissible password available.")
            raise CPException.NoAdmissiblePasswordException("Unable to find the admissible password.")
        return self._admissible_password

    def _check_and_set_special_symbols(self) -> bool:
        """ [Restrictive -- Special Symbols]

        Check whether the special symbols are allowed in the password

        Returns:
            If the symbol is allowed, return True
        """
        if self._admissible_password == "":
            ret_message = "No admissible password available; Improper process here."
            self._logger.error(ret_message)
            raise CPException.ImproperProcessException(ret_message)

        for i in self._admissible_password:
            if i.isalnum():
                continue
            else:
                self._logger.info(f"The tested password {self._admissible_password} contains a special symbol.")
                self._creation_policy["restrictive"]["re_disallow_sps"] = False
                return False

        self._logger.info(f"The tested password {self._admissible_password} does not contain a special symbol.")
        self._creation_policy["restrictive"]["re_disallow_sps"] = True
        return True

    def _change_and_test_multiple_word_password(self) -> bool:
        """ [Restrictive -- Multiple word structure]

        Change the admissible password to a password that not complying with multiple-word structure

        Returns:
            Return the check results
        """
        if self._admissible_password == "":
            ret_message = "No admissible password available; Improper process here."
            self._logger.error(ret_message)
            raise CPException.ImproperProcessException(ret_message)
        ret_str, last_str = "", ""
        self._logger.debug("Breaking the multiple word structure ...")
        # move all the no-alpha letters to the end
        for i in self._admissible_password:
            if i.isalpha():
                ret_str += i
            else:
                last_str += i
        ret_str = ret_str + last_str
        if self._test_one_password(ret_str, self._change_and_test_multiple_word_password.__name__):
            self._logger.info(f"The no-multiple-word structure is allowed.")
            return False
        else:
            self._logger.info(f"The multiple-word structure is required.")
            return True

    def _change_and_test_letter_start_password(self, is_multiple_word: bool) -> bool:
        """ [Restrictive -- Letter Start]

        Change the admissible password to a password that do not start with a letter

        Returns:
            Return the check results
        """
        if self._admissible_password == "":
            ret_message = "No admissible password available; Improper process here."
            self._logger.error(ret_message)
            raise CPException.ImproperProcessException(ret_message)
        ret_str = ""
        first_digit_idx, second_digit_idx = -1, -1
        for i, char in enumerate(self._admissible_password):
            if not char.isalpha():
                if first_digit_idx == -1:
                    first_digit_idx = i
                else:
                    second_digit_idx = i
                break
        self._logger.debug("Breaking the letter-start password ...")

        if is_multiple_word:
            self._logger.debug("Require multiple word structure, and move the second non-alpha character ...")
            if second_digit_idx == -1:
                # TODO: Actually, this should not happen, if it requires passphrase, this should never be False
                return True
            idx = second_digit_idx
        else:
            idx = first_digit_idx
            ret_str = (self._admissible_password[idx]
                       + self._admissible_password[0:idx]
                       + self._admissible_password[idx + 1:])

        if self._test_one_password(ret_str, self._change_and_test_letter_start_password.__name__):
            self._logger.info(f"The no-multiple-word structure is allowed.")
            return False
        else:
            self._logger.info(f"The multiple-word structure is required.")
            return True

    def _change_and_test_lower_upper_minimum(self, is_upper: bool, is_no_a_sps: bool) -> int:
        ret_minimum = 2
        invoke_name = self._change_and_test_lower_upper_minimum.__name__
        if is_upper:
            self._logger.info("Identifying the minimum number of upper letters.")
            changed_ap = self._admissible_password.lower()
        else:
            self._logger.info("Identifying the minimum number of lower letters.")
            changed_ap = self._admissible_password.upper()

        if self._test_one_password(changed_ap, invoke_name):
            self._logger.info(f"Password {changed_ap} with non-tested-character can be accepted.")
            ret_minimum = 0
        else:
            self._logger.info(f"Password {changed_ap} with non-tested-character can not be accepted.")
            changed_dict = uub.get_each_character_num(changed_ap)
            index_of_first_case = None
            if is_upper:
                index_of_first_case = next((i for i, c in enumerate(self._admissible_password) if c.isupper()), None)
            else:
                index_of_first_case = next((i for i, c in enumerate(self._admissible_password) if c.islower()), None)

            if index_of_first_case is not None:
                self._logger.debug("Find the first upper/lower character index for the admissible password.")
                # Change the first letter back to the previous case
                modified_str = (changed_ap[:index_of_first_case] +
                                self._admissible_password[index_of_first_case] +
                                changed_ap[index_of_first_case + 1:])
            else:
                self._logger.warning("Failed to find the first upper/lower character index for the admissible password.")
                modified_str = self._admissible_password

            # Now, we need to check the number of character types
            if changed_dict["type_num"] >= 3:
                self._logger.info("Character type is >= 3 after removing one type of characters.")
                if self._test_one_password(modified_str, invoke_name):
                    self._logger.info("Adding one character is enough to generated an allowed password.")
                    ret_minimum = 1
                else:
                    self._logger.info("Adding one character is not enough to generated an allowed password.")
                    ret_minimum = 2
            elif changed_dict["type_num"] == 2:
                self._logger.info("The character type is 2 after removing one type of characters.")
                if is_no_a_sps:
                    self._logger.info("No special symbol is allowed ... ")
                    if self._test_one_password(modified_str, invoke_name):
                        self._logger.info("Adding one character is enough to generated an allowed password.")
                        ret_minimum = 1
                    else:
                        self._logger.info("Adding one character is not enough to generated an allowed password.")
                        ret_minimum = 2
                else:
                    last_letter_index = None
                    for index, char in enumerate(reversed(changed_ap)):
                        if char.isalpha():
                            last_letter_index = len(changed_ap) - index - 1
                            break
                    self._logger.info("Finding the index of the last letter.")

                    try:
                        self._logger.info("Assertion: the number of letters should not be zero.")
                        assert last_letter_index is not None, "the number of letters should not be zero"
                    except AssertionError as ae:
                        self._logger.error(f"Assertion error: {ae}.")
                        raise AssertionError
                    tmp_ap = changed_ap
                    if changed_dict["dict"] == 0:
                        tmp_char = uusg.gen_random_digit(1)
                    else:
                        tmp_char = uusg.gen_random_symbol_character(1)
                    tmp_ap = tmp_ap[:last_letter_index] + tmp_char + self._admissible_password[last_letter_index + 1:]
                    # test whether a 3 of 4 password can be accepted, true -> 0, false -> then should add a lowercase
                    self._logger.info("Adding a symbol/digit in the password.")
                    if self._test_one_password(tmp_ap, invoke_name):
                        self._logger.info(f"Password {tmp_ap} with non-tested-character can be accepted.")
                        ret_minimum = 0
                    else:
                        if self._test_one_password(modified_str, "add a lowercase letter"):
                            self._logger.info("Adding one character is enough to generated an allowed password.")
                            ret_minimum = 1
                        else:
                            self._logger.info("Adding one character is not enough to generated an allowed password.")
                            ret_minimum = 2
            else:
                try:
                    assert changed_dict["type_num"] >= 2, "the type number should be lower than 2"
                    self._logger.info("Assertion: The number of character type should be larger than or equal to 2.")
                except AssertionError as ae:
                    self._logger.error("The number of character type is less than 2, which is not expected.")

        return ret_minimum



    def _test_one_password(self, test_pwd: str, invoke_function: str) -> bool:
        """ TODO: Remove after former modules finished. Temporary testing code for GitHub.com

        This logic includes three parts:
            - Find the signup page
            - Find the form fields
            - Check whether the password is accepted

        Args:
            test_pwd: the tested password
            invoke_function: the function name of the outer function

        Returns:
            Return whether the password is accepted
        """
        retries = 1
        self._logger.info(f"Begin tests for password {test_pwd} from {invoke_function}")
        while retries <= self.max_retries:
            # ap_driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            ap_driver = APDriver.boot(chrome=True)
            try:
                ap_driver.get("https://github.com/signup")
                uub.random_sleep([3, 5])
                email_address = "fuheiduo@foxmail.com"
                continue_btn = ap_driver.find_elements(By.CLASS_NAME, "signup-continue-button")
                email_elem = ap_driver.find_element(By.NAME, "user[email]")
                email_elem.send_keys(email_address)
                uub.random_sleep([3, 5])
                continue_btn[0].click()
                uub.random_sleep([3, 5])
                password_elem = ap_driver.find_element(By.NAME, "user[password]")
                JS_ADD_TEXT_TO_INPUT = """
                var elm = arguments[0], txt = arguments[1];
                elm.value += txt;
                elm.dispatchEvent(new Event('change'));
                """
                ap_driver.execute_script(JS_ADD_TEXT_TO_INPUT, password_elem, test_pwd)
                actions = ActionChains(ap_driver)
                actions.send_keys(Keys.TAB).perform()
                uub.random_sleep(0.1)
                actions.move_to_element(password_elem).click().perform()
                continue_btn = ap_driver.find_elements(By.CLASS_NAME, "signup-continue-button")
                uub.random_sleep([3, 5])
                if continue_btn[1].is_enabled():
                    flag = True
                    self._logger.success(f"The tested password {test_pwd} is accepted.")
                else:
                    flag = False
                    self._logger.warning(f"The tested password {test_pwd} is rejected.")
                uub.random_sleep([3, 5])
                ap_driver.close()
                return flag
            except Exception as e:
                self._logger.error(f"Tested password {test_pwd} failed to process due to {str(e)}.")
                ap_driver.refresh()
                retries += 1

    # [PROTECTED -- END]

    # [PUBLIC -- BEGIN]
    def __init__(self,
                 logger: loguru.logger,
                 site_name: str,
                 signup_url: str,
                 is_random_info: bool,
                 ) -> None:
        """ Constructor of CreationPolicy class

        Args:
            logger: the logger object
            site_name: the site name
            signup_url: the found signup url
            is_random_info: whether generate random value for fields
        """
        self._logger = logger
        self._site_name = site_name
        # [BEGIN] - Initialize the admissible password
        self._logger.debug("Initialize the admissible password")
        for i in range(self._mid_len_val + 1, self._max_len_val + 1):
            sub_str = uusg.gen_random_str_no_symbol(i - self._mid_len_val)
            self._admissible_password_list[str(i)] = [
                self._admissible_password_list[str(self._mid_len_val)][0] + sub_str,
                self._admissible_password_list[str(self._mid_len_val)][1] + sub_str
            ]
        # [END] - Initialize the admissible password

        # [BEGIN] - Initialize the inputting strings
        if is_random_info:
            self.username = uusg.gen_random_username()
            self.name = uusg.gen_random_username()
            self.email = uusg.gen_random_email()
        else:
            self.username = random.choice(self.preset_user_info["username"])
            self.name = random.choice(self.preset_user_info["name"])
            self.email = random.choice(self.preset_user_info["email"])
        # [END] - Initialize the inputting strings
        # print(self._admissible_password_list, self.username, self.name, self.email)

    def find_admissible_password(self) -> bool:
        """ [Step 1: Find the admissible password]

        Find the admissible password and store in the dict

        Returns:
            Return whether the admissible password is found or not
        """
        if self._admissible_password == "":
            try:
                self._admissible_password = self._find_admissible_password()
            except CPException.NoAdmissiblePasswordException as nape:
                self._logger.debug(f"Raise NoAdmissiblePasswordException: {nape}")
                return False
        return True

    def handle_restrictive_parameters(self) -> bool:
        """ [Step 2: Get the restrictive parameters]

        Five steps:
            - Check the special symbol
            - Check the multiple word structure
            - Check the letter start
            - Check the minimum character number
            - Check the combination requirement

        Returns:
            Return whether the handling process for restrictive parameters is successful
        """

        if self._admissible_password == "":
            error_msg = "No admissible password available; Improper process here."
            self._logger.error(error_msg)
            raise CPException.ImproperProcessException(error_msg)
        # Check the special symbol
        is_re_disallow_sps = self._check_and_set_special_symbols()
        # Check the multiple word structure
        is_re_mul_words = self._change_and_test_multiple_word_password()
        # Check the letter start
        is_re_letter_start = self._change_and_test_letter_start_password(is_re_mul_words)
        self._logger.success("The process operates successfully ... ")
        return True

        # Check the minimum character number
        # Check the combination requirement

    def handle_length_parameters(self) -> bool:
        """ [Step 3: Get the limited length parameters]

        Three steps:
            - Get the minimum length password which satisfying the restrictive parameters
            - Find the minimum limitation of the password length
            - Find the maximum limitation of the password length
        """

        pass

    def handle_permissive_parameters(self):
        """ [Step 4: Get the permissive parameters]

        Four steps:
            - Check the permitted characters
            - Check the permitted sequences
            - Check the long and short digit passwords
            - Check the breached password
        """
        pass

    def sanity_check(self):
        """ [Step 5: Operate the sanity check]

        Two steps:
            - Generate the junky password
            - Operate the sanity check, and expect an error
        """
        pass

    def get_creation_policy(self):
        return self._creation_policy


if __name__ == '__main__':
    my_logger = loguru.logger
    my_site_name = "github.com"
    my_signup_url = "test_url"  # APDriver.get(my_site_name)
    """ The functionality of the my_dict variable
    
    Here, I want the dictionary to store the location method of my crawler.
    In a nutshell, I want to ensure my policy inference should never handle 
    the page and form inference.
    So this dict is stored as the undergraduate's toml file format
    """
    my_dict = {

    }
    cp = CreationPolicy(my_logger, my_site_name, my_signup_url, True)
    # step 1: find the admissible password

    is_find_ap = cp.find_admissible_password()
    is_get_restrictive = False
    is_get_length_limit = False
    is_get_permissive = False
    if is_find_ap:
        is_get_restrictive = cp.handle_restrictive_parameters()
