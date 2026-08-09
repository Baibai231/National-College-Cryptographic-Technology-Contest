#!/usr/bin/python

import re
import time
from typing import List, Dict

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from loguru import logger

from .FormElement import FormElement
from ..Exceptions import stringify_exception
from ..Regexes import Regexes

from time import sleep


class Form(object):
    _caller_prefix = "Form"
    _MAX_STEPS = 5

    def __init__(self, driver, form_info: dict) -> None:
        # super().__init__(parent, id_)
        from utils.APDriver import APDriver
        self._driver: APDriver = driver
        """ Template for form information (in a dictionary format)
        
        is_iframe: whether the form is in a iframe
        iframe_xpath: if is_iframe is 1, then found the iframe and get into the iframe
        is_click: if the form need to be clicked once to at the top layer
        click_xpath: if is_click is 1, then found the clickable element and click it
        form_xpath: when the form is present, found the form using xpath
        """
        try:
            self._iframe_flag = False
            if form_info["is_iframe"] == 1:
                iframe_element = self._driver.find_element_by_xpath(form_info["iframe_xpath"])
                self._driver.switch_to.frame(iframe_element)
                self._iframe_flag = True
            if form_info["is_click"] == 1:
                click_element = self._driver.find_element_by_xpath(form_info["click_xpath"])
                click_element.click()
            time.sleep(0.3)
            form_element = self._driver.find_element_by_xpath(form_info["form_xpath"])
            self._form = form_element
            # if iframe_flag:
            #     self._driver.switch_to.default_content()
        except Exception as e:
            print("Error happens", e)
            raise
        # print(self._form)
        self._str, self._str_tokenized = self._gen_form_str()
        self._has_captcha = self._detect_captcha()

    ''' Generate a form representation string. This is different from the form signature and is used for string matching against known regexes
    '''

    def _gen_form_str(self):
        elid = self._form.get_attribute("id")
        elname = self._form.get_attribute("name")
        elaction = self._form.get_attribute("action")
        elclass = self._form.get_attribute("class")
        elstr = "%s|%s|%s|%s" % (elid, elname, elaction, elclass)
        elset = {elid, elname, elaction, elclass} - {None} - {"undefined"} - {""}
        return "%s|" % "|".join(elset), frozenset(elset)

    ''' Check if the form matches any known/common sign-up form regexes
    '''

    def is_signup_form(self):
        return True if re.search(Regexes.SIGNUP, self._str, re.IGNORECASE) else False

    ''' Check if the form matches any known/common `other` form regexes
    '''

    def is_other_form(self):
        return True if re.search(Regexes.OTHER_FORM, self._str, re.IGNORECASE) else False

    ''' Check the form's source, to determine whether it contains a (re-)CAPCTHA or not
    '''

    def _detect_captcha(self):
        form_src = self._driver.get_element_src(self._form, full=True)
        if re.search(Regexes.CAPTCHA, form_src, re.IGNORECASE):
            return True
        return False

    def has_captcha(self):
        return self._has_captcha

    ''' Check if the form is likely on the top layer
    '''

    def is_on_top_layer(self):
        # First check if the form is on top. If yes, we're good
        formOnTop = self._driver.isOnTopLayer(self._form)
        if formOnTop:
            return True
        # Otherwise, check if more than half of its elements are on top
        elements = (self._form.find_elements_by_tag_name("label") +
                    self._form.find_elements_by_tag_name("input") +
                    self._form.find_elements_by_tag_name("textarea") +
                    self._form.find_elements_by_tag_name("select") +
                    self._form.find_elements_by_tag_name("button"))
        elementsOnTop = 0
        for element in elements:
            if self._driver.isOnTopLayer(element):
                elementsOnTop += 1
        if elementsOnTop >= len(elements) / 2:
            return True
        return False

    def _assign_labels(self):
        label_str = ""
        last_label_str = ""
        label_for_id = None

        label_fors = {}

        elements = []

        self._radio_check = True

        # First traverse the form elements one by one, in the order they appear and collect labels for each input
        # Intuition is that inputs are placed right after their accompanying <label> descriptions
        for element in self._driver.get_descendants(self._form):
            form_element = FormElement(self._driver, element)
            element_label = None

            # # # TEST # # #
            # Leave those even if hidden
            if self._driver.get_type(form_element.get_web_element()) == "checkbox":
                pass
            elif self._driver.get_type(form_element.get_web_element()) == "radio":
                # If a radio is already checked, don't check any others
                if self._driver.is_checked(form_element.get_web_element()):
                    self._radio_check = False
            elif not self._driver.is_displayed(form_element.get_web_element()):
                continue

            if self._driver.is_form_input(form_element.get_web_element()):
                if not label_str:
                    # propagate last known label to unlabelled inputs
                    label_str = last_label_str
                form_element.add_possible_label(label_str)
                elements.append(form_element)
                last_label_str = label_str
                # reset label string for next input
                label_str = ""
            elif self._driver.is_tag(form_element.get_web_element(), "label"):
                label_str = form_element.get_prop("textContent")
                label_for_id = form_element.get("for")
                if label_for_id:
                    if label_for_id in label_fors:
                        label_fors[label_for_id].append(label_str)
                    else:
                        label_fors[label_for_id] = [label_str]
        # Assign dedicated labels to each element (if found)
        for element in elements:
            eid = element.get("id")
            for label_str in label_fors.get(eid, []):
                element.add_label(label_str)

        return elements

    def get_labels(self):
        _labels = []
        try:
            elements = self._assign_labels()
            for element in elements:
                el_str = element.get_element_str()
                el_lbls = element.get_labels(stringified=True)
                el_plbls = element.get_possible_labels(stringified=True)

                _labels.append(
                    {
                        "str": el_str,
                        "labels": el_lbls,
                        "possible_labels": el_plbls
                    }
                )
        except Exception as e:
            # Logger.spit("Error while assigning labels", warning=True, caller_prefix=Form._caller_prefix)
            # Logger.spit("%s" % stringify_exception(e), warning=True, caller_prefix=Form._caller_prefix)
            print("Error while assigning labels", e)
            pass
        return _labels

    def _get_source_list(self, body_element: WebElement) -> List[str]:
        """ get the source of the body element

        Args:
            body_element: WebElement, goal

        Returns:
            Return a string list, containing the body innerHTML, and also the inner iframes
            The first element is the body innerHTML
        """
        ret_list: List[str] = [body_element.get_attribute("innerHTML")]
        iframe_list: List[WebElement] = body_element.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframe_list:
            self._driver.switch_to.frame(iframe)
            iframe_body: WebElement = iframe.find_element(By.TAG_NAME, "body")
            if iframe_body:
                ret_list.append(iframe_body.get_attribute("innerHTML"))
            self._driver.switch_to.default_content()
        return ret_list

    def _get_source_str(self, body_element: WebElement) -> str:
        """ get the source of the body element

        Args:
            body_element: WebElement, goal

        Returns:
            Return a string, containing only the body innerHTML
        """
        return body_element.get_attribute("innerHTML")

    ''' Fill the form
    '''

    def fill(self,
             submit: bool = True,
             required_only: bool = False,
             override_rules: bool = None,
             test_password: str = ""
             ) -> [list, Dict[str, str]]:
        """ Fill the inputted form

        Args:
            submit: bool, submit the form
            required_only: bool, only fill the explicitly required field
            override_rules: bool
            test_password: str
        Returns:
            list, dict
        """
        if override_rules is None:
            override_rules = {}
        _values = []
        ret_dict: Dict[str, List[str]] = {
            "after_fill": [],
            "after_sub": [],
            "test_red": []
        }

        cur_url = self._driver.current_url()
        self._driver.store_reference_element(cur_url)
        try:
            elements = self._assign_labels()
            for element in elements:
                if required_only and not element.is_required():
                    continue
                el_str = element.get_element_str()
                el_lbls = element.get_labels(stringified=True)
                el_plbls = element.get_possible_labels(stringified=True)
                """ Add some new properties for element
                """
                el_type = element.get_prop("type")
                el_id = element.get_prop("id")
                el_class = element.get_prop("class")
                el_placeholder = element.get_prop("placeholder")
                # Put the field empty ...
                self._driver.set_value(element.get_web_element(), "")
                val = element.fill(override_rules=override_rules, radio_check=self._radio_check, test_password=test_password)
                _values.append(
                    {
                        "str": el_str,
                        "labels": el_lbls,
                        "possible_labels": el_plbls,
                        "type": el_type,
                        "id": el_id,
                        "class": el_class,
                        "placeholder": el_placeholder,
                        "value": val
                    }
                )
            # [# 2] After filling out the form
            body_element: WebElement = self._driver.find_element_by_tag_name("body")
            ret_dict["after_fill"] = self._driver.get_source_list(body_element)
            # sleep(1)
            if _values and submit:
                logger.info("Waiting a bit for submit buttons to become enabled ...")
                # Temporary? Give it some time to activate the submit buttons
                sleep(0.5)
                submit_btns = [
                    sb for sb in
                    self._driver.find_elements_by_tag_name("button", webelement=self._form)
                    if self._driver.is_displayed(sb)]
                submit_inputs = [
                    si for si in self._driver.find_elements_by_tag_name("input", webelement=self._form)
                    if (self._driver.is_type(si, "submit") or self._driver.is_type(si, "button"))
                    and self._driver.is_displayed(si)]
                submit_as = [
                    sa for sa in self._driver.find_elements_by_tag_name("a", webelement=self._form)
                    if self._driver.is_displayed(sa) and (
                            re.search(Regexes.SIGNUP, self._driver.get_element_src(sa), re.IGNORECASE)
                            or re.search(r"submit", self._driver.get_element_src(sa), re.IGNORECASE)
                            # The tag <a> may be surrounded by a parental <div> element
                            or re.search(r"submit", self._driver.get_element_src(sa.find_element(By.XPATH, "..")),
                                         re.IGNORECASE)
                    )]
                submit_btns += submit_inputs
                # use detected <a> elements ONLY if we haven't found a submit button/input
                if not submit_btns:
                    submit_btns += submit_as
                if len(submit_btns) == 1:
                    click_btn: WebElement = submit_btns[0]
                    logger.info("Located exactly one submit button. Will click it ...")
                    try:
                        click_btn.click()
                    except Exception as e:
                        if self._form.tag_name != "form":
                            logger.warning(f"The element is not a form, and could not be clicked: {e}", e)
                            return
                        logger.error(f"Could not click it. Will submit: {e}")
                        self._driver.submit(self._form)
                else:
                    # Note that a div may do not have a submit function ...
                    if self._form.tag_name != "form":
                        logger.warning("The element is not a form, we will not try to submit it")
                        return
                    logger.warning("Located %s. Will submit ..." % "no submit buttons" if len(
                        submit_btns) == 0 else "more than one submit buttons")
                    self._driver.submit(self._form)
                logger.info("Waiting a bit for potential page redirection ...")
                # Get a snapshot after submitting the form
                body_element = self._driver.find_element_by_tag_name("body")
                ret_dict["after_sub"] = self._driver.get_source_list(body_element)
                sleep(2)
                if not self._driver.is_redirected(cur_url):
                    logger.warning("Form submission does not seem to cause a redirection ...")
                body_element = self._driver.find_element_by_tag_name("body")
                ret_dict["test_red"] = self._driver.get_source_list(body_element)
        except Exception as e:  # Screw the exceptions, if we submitted something we still need to return
            # Logger.spit("%s" % stringify_exception(e), warning=True, caller_prefix=Form._caller_prefix)
            raise

        return _values, ret_dict
