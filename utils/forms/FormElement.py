#!/usr/bin/python

import re

from collections import OrderedDict
from random import choice, randint
from string import ascii_uppercase, ascii_lowercase
from faker import Faker
from googletrans import Translator
from selenium.webdriver.support.select import Select
from ..Regexes import Regexes

''' Wrapper class for Selenium's form input WebElements.
'''


def _lname_male():
    # name = FormElement._faker.last_name_male()
    name = choice(ascii_uppercase) + ''.join(choice(ascii_lowercase) for i in range(6))
    return name


def _fname_male():
    # name = FormElement._faker.first_name_male()
    name = choice(ascii_uppercase) + ''.join(choice(ascii_lowercase) for i in range(6))
    return name


def _birthdate():
    year = 0
    while year < 1980 or year > 1997:
        parts = FormElement._faker.date().split("-")
        parts.reverse()
        date = ".".join(parts)
        year = int(date.split(".")[-1])
    return date


def _user_name():  # Mix it up a bit, so we don't hit a common username
    # return "daheiduo7841@gmail.com"
    return FormElement._faker.user_name() + FormElement._faker.user_name()[:4]


def _phone():
    phone_no = ""
    while not phone_no or any(True if token in phone_no else False for token in FormElement._phone_blacklist_chars):
        phone_no = FormElement._faker.phone_number()
    return phone_no


def _rand_age():
    return randint(21, 65)


def _area_code():
    return "1"


def _profile_pic():
    return "/path/to/pic.jpg"


def _password():
    return "how-i-met-your-monther-111"


def _gmail():
    return "daheiduo@foxmail.com"  # Depending on the account we are using


def _split_and_remove_spaces(input_string: str, delimiters: str) -> list:
    """
    Split the input string into a list using multiple delimiters and remove spaces

    Args:
        input_string (str): The input string to be split.
        delimiters (str): A string containing all the delimiters

    Returns:
        list: A list of substrings without spaces
    """
    pattern = "[" + re.escape(delimiters) + "]"
    result_list = re.split(pattern, input_string)

    # Remove spaces
    result_list = [substring.strip() for substring in result_list if substring.strip()]
    return result_list


class FormElement(object):
    _caller_prefix = "FormElement"

    # Static faker object to fill out values
    _faker = Faker()
    _translator = Translator()
    _phone_blacklist_chars = ["x", "-", ".", "(", ")", "+"]
    _DEFAULT_RULE = "KJASHDahiudasIUDYAIUSydisudhakjnendemndne"
    _common_delimiters = ",;|/"

    _make_fixed_flat_set: list = [
        "___.___.___-__",
        "+1",
        "3~15个字符,中文字符7个以内",
        "benutzername",
        "client id",
        "codice titolare",
        "digite seu cpf ou e-mail",
        "ds logon username",
        "email",
        "email address",
        "email masih kosong",
        "email/手機號碼",
        "e-mail/username",
        "e-mail address",
        "enter username",
        "enter user name",
        "identifiant",
        "kullanıcı adı",
        "kunden-id",
        "login",
        "nick",
        "nom d'usuari",
        "nom utilisateur",
        "rut",
        "siret",
        "this is usually your email address",
        "tu dni",
        "uid/用戶名/email",
        "uporabnik...",
        "user/codice",
        "user id",
        "user name",
        "username",
        "username or email",
        "username or email:",
        "username/email",
        "usuario",
        "your email address",
        "ååååmmddxxxx",
        "아이디 or @이하 모두 입력",
        "Имя",
        "Имя (логин)",
        "Логин",
        "Логин...",
        "Логин (e-mail)",
        "שם משתמש",
        "כתובת דוא''ל",
        "اسم العضو",
        "اسم المستخدم",
        "الاسم",
        "نام کاربری",
        "メールアドレス",
        "อีเมล",
        "用户名",
        "用户名/email",
        "邮箱/手机",
        "帳號",
        "請輸入身份證字號",
        "请用微博帐号登录",
        "请输入手机号或邮箱",
        "请输入邮箱或手机号",
        "邮箱/手机/展位号",
        "手机号/邮箱"
    ]

    _make_placeholder_set: dict = {
        "email": ["email", "邮箱"],
        "phone": ["手机号", "手机", "手機號碼"]
    }

    def __init__(self, driver, input_webElement):
        self._rules = None
        self._required = None
        self._driver = driver
        self._web_element = input_webElement
        self._str, self._str_tokenized = self._gen_element_str()
        self._labels = []  # This is for dedicated labels that we are certain are referring to this element
        self._possible_labels = []  # This one is for labels that we extracted structurally, but could be referring to other elements. Use as last resort
        self._pattern = None
        self._value = None
        self._placeholders = self._driver.get_attribute(self._web_element, "placeholder")

    def get_web_element(self):
        return self._web_element

    def set_web_element(self, web_element):
        self._web_element = web_element

    ''' Construct element's string from representative attributes
    '''

    def _gen_element_str(self):
        elid = self.get("id")
        elname = self.get("name")
        elaction = self.get("action")
        elplaceholder = self.get("placeholder")
        eltype = self.get("type")
        elvalue = self.get("value")
        elstr = "%s|%s|%s|%s|%s|%s" % (elid, elname, eltype, elaction, elplaceholder, elvalue)
        elset = {elid, elname, eltype, elaction, elplaceholder, elvalue} - {None} - {"undefined"} - {""}
        return "%s|" % "|".join(elset), list(elset)

    ''' Return the specified attribute
    '''

    def get(self, attribute):
        return self._web_element.get_attribute(attribute)

    ''' Return the specified property
    '''

    def get_tag_name(self):
        return self._web_element.tag_name

    def get_prop(self, property):
        return self._web_element.get_property(property)

    def get_labels(self, stringified=False):
        return self._labels if not stringified else "|".join(self._labels)

    def add_label(self, label):
        self._labels.append(label)

    def get_possible_labels(self, stringified=False):
        return self._possible_labels if not stringified else "|".join(self._possible_labels)

    def add_possible_label(self, label):
        self._possible_labels.append(label)

    def get_pattern(self):
        return self._pattern

    def set_pattern(self, pattern):
        self._pattern = pattern

    def get_element_str(self, tokenized=False):
        return self._str if not tokenized else self._str_tokenized

    ''' Check if the element is required, first by checking if the HTML `required` attribute is set and if not if it is present as a substring
        in the element's code
    '''

    def is_required(self):
        self._required = self._driver.is_required(self._web_element) \
                         or re.search(r"required|\*", self.get_labels(stringified=True), re.IGNORECASE) \
                         or re.search(r"required|\*", self.get("outerHTML"), re.IGNORECASE)
        return self._required

    def _get_input_length(self):
        input_length = None
        maxlength = self.get("maxlength")
        input_size = self.get_prop("size")
        maxlength = int(maxlength) if maxlength else maxlength
        input_size = int(input_size) if input_size else input_size
        if maxlength and 50 >= maxlength > 0:
            input_length = maxlength
        if input_length is None and input_size and 50 >= input_size > 0:
            input_length = input_size
        if input_length is None:
            input_length = 12
        return input_length

    ''' Based on the input's type, labels, attributes and/or possible secondary labels, fill it out
    '''

    def fill(self, override_rules=None, radio_check=False, test_password: str = ""):
        if override_rules is None:
            override_rules = {}
        value = None
        etype = self._driver.get_type(self._web_element)
        etag = self._driver.get_tag(self._web_element)

        if etype in {"hidden", "image", "submit", "reset"}:
            pass
        if etag == "select":
            self._rules = FormElement._select_rules
            value = self._fill_select()
        elif etype == "radio":
            if radio_check:
                self._fill_check()
        elif etype == "checkbox":
            self._fill_check()
        elif etype == "text":
            inputLength = self._get_input_length()
            # TODO: Need to consider the placeholder, id, class, and other attributes
            # place_holder = self._driver.get_attribute(self._web_element, "placeholder")
            self._rules = FormElement._text_rules
            value = self._fill_text(etype=etype, inputLength=inputLength, override_rules=override_rules, test_password=test_password)
        elif etag == "textarea" or etype in {"password", "number", "tel", "search", "email"}:
            # Need to change when need to consider the patterns
            inputLength = self._get_input_length()
            self._rules = FormElement._text_rules
            value = self._fill_text(etype=etype, inputLength=inputLength, override_rules=override_rules, test_password=test_password)
        elif etype == "date" or etype == "datetime-local":
            value = self._driver.set_value(self._web_element, FormElement._faker.date())
        elif etype == "file":
            try:
                self._driver.send_keys(self._web_element, _profile_pic())
            # self._web_element.send_keys(FormElement._profile_pic())
            except Exception as e:
                pass
            # Logger.spit("Exception when trying to fill out file input", caller_prefix = FormElement._caller_prefix)
        elif etype == "month":
            value = self._driver.set_value(self._web_element, "-".join(FormElement._faker.date().split("-")[:2]))
        elif etype == "week":
            value = self._driver.set_value(self._web_element, "-W".join(FormElement._faker.date().split("-")[:2]))
        elif etype == "range":
            value = self._driver.set_value(self._web_element, str(choice(list(range(100)))))
        elif etype == "time":
            value = self._driver.set_value(self._web_element, FormElement._faker.time())
        elif etype == "url":
            value = self._driver.set_value(self._web_element, FormElement._faker.url())
        self._value = value
        return value

    ''' Decide pattern to fill out field
    '''

    def _decide_rule(self, allow_trans=True):
        # Need special handle for type="text" fields , especially not for the specific order ...
        fill_rule = None
        # print(self._rules)
        # Check the placeholder of the field
        if self._placeholders:
            ph_list = _split_and_remove_spaces(self._placeholders, self._common_delimiters)
            # Heuristic: consider email first
            for email_keyword in self._make_placeholder_set["email"]:
                for ph in ph_list:
                    if email_keyword in ph:
                        fill_rule = Regexes.EMAIL
                        break
                if fill_rule:
                    break
        if fill_rule is None:
            for rule in self._rules:  # Fallback to dedicated labels
                if any([True if re.search(rule, lbl, re.IGNORECASE) else False for lbl in self._labels]):
                    fill_rule = rule
                    break
        if fill_rule is None:  # Fallback to element's stringified HTML
            for rule in self._rules:
                if any([True if re.search(rule, lbl, re.IGNORECASE) else False for lbl in self._str_tokenized]):
                    fill_rule = rule
                    break
        if fill_rule is None:  # Fallback to secondary possible labels (Could be mismatched due to structural diffs)
            for rule in self._rules:
                if any([True if re.search(rule, lbl, re.IGNORECASE) else False for lbl in self._possible_labels]):
                    fill_rule = rule
                    break
        # Before falling back to the default, detect language and try to translate the element's labels and tokenized string
        # and call _decide_rule again. Also, if any translation is successful and matches, update its labels, so we don't have to do it
        # again in potential retries of the form submission.
        if fill_rule is None:
            if allow_trans:
                # Logger.spit("Nothing matched. Attempting to translate labels.", caller_prefix = FormElement._caller_prefix)
                self._translate_labels()
                fill_rule = self._decide_rule(allow_trans=False)
            else:
                fill_rule = FormElement._DEFAULT_RULE  # Last resort, fallback to default rule
        return fill_rule

    # Translate the element's labels
    def _translate_labels(self):
        to_translate = self._str_tokenized + self._labels + self._possible_labels
        translated = [res.text for res in FormElement._translator.translate(to_translate)]
        slice1 = len(self._str_tokenized)
        slice2 = slice1 + len(self._labels)

        self._str_tokenized += translated[:slice1]
        self._labels += translated[slice1:slice2]
        self._possible_labels += translated[slice2:]

    def _fill_text(self, etype="text", inputLength=12, override_rules=None, test_password: str = ""):
        # place_holder = self._driver.get_attribute(self._web_element, "placeholder")
        if override_rules is None:
            override_rules = {}
        rule = self._decide_rule()
        if override_rules and rule in override_rules:
            # Use the caller's provided value instead (e.g. a specific username when logging in); If matches password, leave as is though
            # However, if NO rule matched, and we have overriding rules (only login in our case and generally the caller wants custom values), use the caller's "default" value
            value = override_rules[rule]
        elif rule is FormElement._DEFAULT_RULE:
            value = self._rules[rule](min_chars=8 if inputLength >= 8 else 1, max_chars=inputLength)
        else:
            if rule == Regexes.PASSWORD and test_password != "":
                value = test_password
            else:
                value = self._rules[rule]()

        try:
            self._driver.send_keys(self._web_element, value)
        except Exception as e:
            # Logger.spit("Exception when sending keys to element: %s" % stringify_exception(e),
            #             caller_prefix=FormElement._caller_prefix)
            value = self._driver.set_value(self._web_element, value)
        return value

    def _fill_check(self):
        self._driver.check_element(self._web_element)

    def _fill_select(self):
        rule = self._decide_rule()

        select = Select(self._web_element)
        opts = select.options
        val = None
        idx = -1

        if rule is FormElement._DEFAULT_RULE and len(opts) > 0:  # If not match, just pick a random choice
            tries = 0
            max_tries = 10
            idx = 0
            while tries < max_tries and (not val or val == "undefined" or val == "null"):  # Avoid invalid options
                opt = choice(opts)
                if opts.index(opt) == 0 and len(opts) > 1:  # The first one is usually a label-like option
                    continue
                val = opt.get_attribute("value").strip()
                idx = opts.index(opt)
                if len(opts) == 1:
                    break
                tries += 1
        if idx != -1:
            self._driver.set_selected_index(self._web_element, idx)
        return val

    # Rules to fill out inputs, based on their labels/attributes
    _text_rules = OrderedDict()
    # Names
    _text_rules[Regexes.EMAIL] = _gmail
    _text_rules[Regexes.FIRST_NAME] = _lname_male
    _text_rules[Regexes.LAST_NAME] = _fname_male
    _text_rules[Regexes.FULL_NAME] = _faker.name_male
    _text_rules[Regexes.USERNAME] = _user_name
    _text_rules[Regexes.NAME_PREFIX] = _faker.prefix_male
    # password
    _text_rules[Regexes.PASSWORD] = _password
    # Phones
    _text_rules[Regexes.PHONE_AREA] = _area_code
    _text_rules[Regexes.PHONE] = _phone
    # Dates
    _text_rules[Regexes.MONTH] = _faker.month
    _text_rules[Regexes.DAY] = _faker.day_of_month
    _text_rules[Regexes.YEAR] = _faker.year
    _text_rules[Regexes.BIRTHDATE] = _birthdate
    # Age
    _text_rules[Regexes.AGE] = _rand_age
    # email, profile pics
    _text_rules[Regexes.FILE] = _profile_pic
    # Addresses
    _text_rules[Regexes.ZIPCODE] = _faker.zipcode
    _text_rules[Regexes.CITY] = _faker.city
    _text_rules[Regexes.COUNTRY] = _faker.country
    _text_rules[Regexes.STATE] = _faker.state
    _text_rules[Regexes.STREET] = _faker.street_name
    _text_rules[Regexes.BUILDING_NO] = _faker.building_number
    _text_rules[Regexes.ADDRESS] = _faker.street_address
    # SSN etc.
    _text_rules[Regexes.SSN] = _faker.ssn
    # Credit cards
    _text_rules[Regexes.CREDIT_CARD_EXPIRE] = _faker.credit_card_expire
    _text_rules[Regexes.CREDIT_CARD_CVV] = _faker.credit_card_security_code
    _text_rules[Regexes.CREDIT_CARD] = _faker.credit_card_number
    # Company stuff
    _text_rules[Regexes.COMPANY_NAME] = _faker.company
    #### END SPECIFIC REGEXES - START GENERIC ####
    _text_rules[Regexes.NUMBER_COARSE] = _faker.numerify
    _text_rules[Regexes.USERNAME_COARSE] = _user_name
    # Default
    _text_rules[_DEFAULT_RULE] = _faker.pystr

    _select_rules = {
        _DEFAULT_RULE: choice
    }
