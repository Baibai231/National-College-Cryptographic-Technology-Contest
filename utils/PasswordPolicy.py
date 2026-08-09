#!~/anaconda3/env3/MyAUtomaticPolicy/bin/python
import base64
import difflib
import json
import re
from typing import Callable, Union, Iterator, List
from urllib.parse import unquote

from loguru import logger
from bs4 import BeautifulSoup

from utils.APDriver import APDriver
import utils.util_basic as uub
import utils.util_str_generator as uusg
from utils.ImageOCRUtils import ImageOCRUtils
from utils.login_policy_utils.LoginRegexes import LoginRegexes


def scan_json(obj, indent: int = 0, func: Callable = None) -> str:
    # Recursively prints the keys and values of a JSON object.
    ret: str = ""
    if isinstance(obj, dict):
        for k, v in obj.items():
            logger.debug('  ' * indent + str(k) + ":")
            _tmp_ret: str = scan_json(v, indent + 1, func)
            if _tmp_ret != "":
                ret = _tmp_ret
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            logger.debug(f"  " * indent + f"Array index {i}:")
            _tmp_ret: str = scan_json(item, indent + 1, func)
            if _tmp_ret != "":
                ret = _tmp_ret
    else:
        logger.debug('  ' * indent + str(obj))
        if func and func(str(obj)):
            logger.info(f"{str(obj)} meets the function.")
            ret = str(obj)
    return ret


def _err_msg_check(_str: str):
    if re.search(LoginRegexes.ERROR_MESSAGE, str(_str), re.I):
        return True
    return False


class PasswordPolicy(object):
    max_retries = 5

    password_combination = {
        "digit": 0,
        "lower": 0,
        "upper": 0,
        "letter": 0,
        "symbol": 0,
        "combination_3": 0,
        "combination_4": 0
    }

    preset_user_info = {
        "name": [],
        "username": [],
        "email": []
    }

    def _get_password_combination(self, password: str) -> dict:

        combination_3 = set()
        combination_4 = set()
        for i in password:
            if i.isdigit():
                self.password_combination["digit"] += 1
                combination_3.add("digit")
                combination_4.add("digit")
            elif i.isalpha():
                self.password_combination["letter"] += 1
                combination_3.add("letter")
                if i.islower():
                    self.password_combination["lower"] += 1
                    combination_4.add("lower")
                else:
                    self.password_combination["upper"] += 1
                    combination_4.add("upper")
            else:
                self.password_combination["symbol"] += 1
                combination_3.add("symbol")
                combination_4.add("symbol")
            self.password_combination["combination_3"] = len(combination_3)
            self.password_combination["combination_4"] = len(combination_4)
        return self.password_combination

    # Check success or failure
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

    @staticmethod
    def _handle_request(request_data: dict, submit_info: dict) -> bool:
        """ Handle the network request

        Args:
            request_data: dict
            submit_info: dict, the submitted data
        Returns:
            bool, the request method, POST or GET
        """
        _method: str = request_data["method"]
        _post_data: str = unquote(request_data["postData"])
        _get_data: str = unquote(request_data["url"])
        _pattern_str: str = fr"{submit_info['u_name']}={submit_info['u_value']}"
        if _method == "POST":
            if _post_data and re.search(_pattern_str, _post_data, re.I):
                return True
        elif _method == "GET":
            if _get_data and re.search(_pattern_str, _get_data, re.I):
                return True
        else:
            return False

    @staticmethod
    def _handle_response(response_data: dict):
        ret_response: str = ""
        _response_type: str = response_data["mimeType"] or ""
        _response_data_code: bool = response_data["responseBody"]["base64Encoded"]
        _response_data_body: str = response_data["responseBody"]["body"]
        if _response_data_code:
            _response_data_body = base64.b64decode(_response_data_body).decode("utf-8")
        if _response_type == "application/json":
            _response_data_body: dict = json.loads(_response_data_body)
            scan_check: str = scan_json(obj=_response_data_body, func=_err_msg_check)
            return scan_check
        elif _response_type == "text/html":
            _response_data_body: BeautifulSoup = BeautifulSoup(_response_data_body, "html.parser")

            def is_visible(tag):
                return "style" not in tag.attrs or "display:none" not in tag.get("style", "")

            _text: list = [
                tag.get_text(strip=True) for tag in _response_data_body.find_all(is_visible, recursive=True)
                if tag.get_text(strip=True) != "" and not tag.find_all()
            ]
            _text = list(set(_text))
            for _t in _text:
                if re.search(LoginRegexes.ERROR_MESSAGE, str(_t), re.I):
                    logger.info(f"Error message found in network response in {_t}.")
                    return str(_t)
        else:
            logger.warning(f"New type {_response_type} of response ...")
        return ""

    def _get_err_msg_from_logs(self, _driver: APDriver, logs: list, submit_info: dict) -> str:
        def get_response_body(request_id):
            try:
                return _driver.execute_cdp_cmd(
                    "Network.getResponseBody",
                    {"requestId": request_id}
                )
            except Exception:
                return ""

        network_dict: dict = {}
        _ret_value: str = ""

        for entry in logs:
            log_json = json.loads(entry["message"])["message"]
            if log_json["method"] == "Network.requestWillBeSent":
                request_d = log_json["params"]["request"]
                request_data = {
                    "type": log_json["params"]["type"] or "",
                    "mixedContentType": log_json["params"]["request"]["mixedContentType"] or "",
                    "id": log_json["params"]["requestId"] or "",
                    "url": request_d["url"] or "",
                    "method": request_d["method"] or "",
                    "header": request_d["headers"] or "",
                    "postData": log_json["params"]["request"]["postData"] if "postData" in request_d else "",
                }

                if request_data["type"] != "XHR" and request_data["type"] != "Document":
                    continue

                if re.search(self._forbidden_suffixes, request_data["url"].split("#")[0], re.IGNORECASE):
                    continue

                if request_data["id"] != "" and request_data["id"] not in network_dict.keys():
                    network_dict[request_data["id"]] = {
                        "request_data": request_data,
                        "response_data": []
                    }
            elif log_json["method"] == "Network.responseReceived":
                response = log_json["params"]["response"]
                response_data = {
                    "mimeType": log_json["params"]["response"]["mimeType"] or "",
                    "url": response["url"] or "",
                    "status": response["status"] or "",
                    "id": log_json["params"]["requestId"] or "",
                    "responseBody": get_response_body(log_json["params"]["requestId"]) or ""
                }
                if response_data["responseBody"] == "":
                    continue
                if (response_data["mimeType"] != "application/json"
                        and response_data["mimeType"] != "application/xml"
                        and response_data["mimeType"] != "text/html"
                        and response_data["mimeType"] != "text/plain"):
                    continue

                if re.search(self._forbidden_suffixes, response_data["url"].split("#")[0], re.IGNORECASE):
                    continue

                if response_data["id"] != "" and response_data["id"] in network_dict.keys():
                    if "response_data" in network_dict[response_data["id"]].keys():
                        network_dict[response_data["id"]]["response_data"].append(response_data)

        _response_handle: dict = {}
        for key, value in network_dict.items():
            if value['response_data']:
                _request_data: dict = value["request_data"]
                if self._handle_request(_request_data, submit_info):
                    logger.info(f"request_data: {_request_data}")
                    _response_data: dict = value["response_data"]
                    # logger.info(f"response_data: {_response_data}")
                    _ret_value = self._handle_response(_response_data[-1])
                    if _ret_value != "":
                        # TODO: get the last info, think the last request should be true (need to be modified)
                        _response_handle = _response_data[-1]
                    else:
                        continue
        if _response_handle:
            logger.info(_response_handle)
            return _ret_value
        return ""

    @staticmethod
    def _diff_two_source(original_source: str, sub_source: str, is_plain: bool = False) -> List[str]:
        """ Found difference between page sources
        """
        source_differ: difflib.Differ = difflib.Differ()
        source_diff: Iterator[str] = source_differ.compare(
            original_source.splitlines(),
            sub_source.splitlines()
        )
        source_diff_list: List[str] = []
        ret_list: List[str] = []
        for diff in source_diff:
            if diff.startswith("+"):
                if is_plain:
                    append_str: str = re.sub(r"<.*?>", "", diff[1:].strip())
                else:
                    append_str: str = diff[1:].strip()
                if append_str != "":
                    source_diff_list.append(append_str)
        for i in source_diff_list:
            if not is_plain:
                soup = BeautifulSoup(i, "html.parser")
                formatted_html = soup.prettify()
                for j in formatted_html.splitlines():
                    ret_list.append(j.strip())
            else:
                ret_list.append(i.strip())
        return ret_list

    def _get_err_msg_from_source(self, original_source: str, after_source: str, in_plain: bool = False) -> str:
        after_captcha_diff: List[str] = self._diff_two_source(original_source, after_source, in_plain)
        for i in after_captcha_diff:
            if re.search(LoginRegexes.ERROR_MESSAGE, i, flags=re.I) is not None:
                return i
        return ""

    @staticmethod
    def _get_err_msg_from_img(original_path: str, after_path: str) -> str:
        img_util = ImageOCRUtils()
        diff_list: List[str] = img_util.diff_two_images(original_path, after_path)
        for diff_msg in diff_list:
            if re.search(LoginRegexes.ERROR_MESSAGE, diff_msg, flags=re.I) is not None:
                return diff_msg
        return ""
