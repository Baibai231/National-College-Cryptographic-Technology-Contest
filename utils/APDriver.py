import os
import random
import re
from typing import Optional, Callable, List, Union, TypeVar

import psutil
import shutil
import signal
from copy import deepcopy
from time import time, sleep
from uuid import uuid4
from loguru import logger

import selenium.common.exceptions as sce
from pyvirtualdisplay import Display
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.webdriver import WebDriver as CWebDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC

from utils.Exceptions import *
from utils.Regexes import Regexes
from utils.URLUtils import URLUtils
from utils.forms import Form

CHROME: str = "chrome"
T = TypeVar("T")


class APDriver(Chrome):
    _caller_prefix: str = "APDriver"
    _forbidden_paths: List[str] = ["/", "/home", "~/Desktop"]
    _abs_path: str = os.path.dirname(os.path.abspath(__file__))
    _abs_profiles_path: str = "/tmp"
    _compatible_browsers: List[str] = [CHROME]
    _browser_instance_type: str = None

    # A regex of blacklisted suffixes.
    _forbidden_suffixes: str = (
        r"\.(mp3|wav|wma|ogg|mkv|zip|tar|xz|rar|z|deb|bin|"
        r"iso|csv|tsv|dat|txt|css|log|sql|xml|sql|mdb|apk|"
        r"bat|bin|exe|jar|wsf|fnt|fon|otf|ttf|ai|bmp|gif|"
        r"ico|jp(e)?g|png|ps|psd|svg|tif|tiff|cer|rss|key|"
        r"odp|pps|ppt|pptx|c|class|cpp|cs|h|java|sh|swift|"
        r"vb|odf|xlr|xls|xlsx|bak|cab|cfg|cpl|cur|dll|dmp|"
        r"drv|icns|ini|lnk|msi|sys|tmp|3g2|3gp|avi|flv|"
        r"h264|m4v|mov|mp4|mp(e)?g|rm|swf|vob|wmv|doc(x)?|"
        r"odt|pdf|rtf|tex|txt|wks|wps|wpd)$")

    """ Configuration options for APDriver.

    This configuration should always be set before booting the browser.
    For anything that is `enabled: True` and no other specific changes are made,
    APDriver's default configuration will be used.

    - @ browser: High-level browser options. These will be translated to actual browser-specific options by the selected subclass
        - @ enabled: If False, don't use any command line arguments in browser
        - @ no_ssl_errors: Supress browser-level SSL errors
        - @ disable_notifications: Disable push notifications
        - @ maximized: Start browser window maximized
        - @ no_default_browser_check: Prevent popup to make browser the default (if this is a fresh instance)
        - @ disable_cache: Disable all possible levels of cache
        - @ profile: Use specific profile. If None, a temporary new one will be generated
        - @ headless: Start headless
        - @ virtual: Use virtual display
        - @ vpn: Opera built-in VPN -- Not currently supported
    - @ ap_driver: High-level APDriver / Selenium specific options
        - @ max_retries: How many times to retry an operation by default, before giving up
        - @ timeout: Page load timeout in seconds
        - @ heartbeat_url: the url for heartbeat monitoring
        - @ max_boot_retries: the maximum number of booting process
        - @ scripts: the scripts loading
        - @ scripts_after_load: the scripts loading after the page loading
    """
    _base_config: dict = {
        "browser": {
            "enabled": True,
            "no_ssl_errors": True,
            "ignore_certificate_errors": True,
            "disable_notifications": True,
            "maximized": True,
            "no_default_browser_check": True,
            # "disable_cache": True,
            "profile": None,
            "headless": False,
            "virtual": False,
            "vpn": False
        },
        "ap_driver": {
            "max_retries": 10,
            "timeout": 120,
            "heartbeat_url": "https://baidu.com",
            "max_boot_retries": 3,
            "scripts": "",
            "scripts_after_load": ""
        }
    }

    # Maintain a stable copy of the default.
    _original_config: dict = deepcopy(_base_config)
    _all_children_proc: set = set()

    # APDriver's subprocesses (depending on configuration).
    _subprocesses: set = {"mitmdump", "Xvfb"}

    # Main JS lib needed by APDriver
    _scripts_file: str = os.path.join(_abs_path, "js/scripts.js")
    # Anti-bot / CMP JS files
    _notabot_file: str = os.path.join(_abs_path, "js", "notABot.js")
    _cmpdetect_file: str = os.path.join(_abs_path, "js", "cmpDetect.js")

    @classmethod
    def get_config(cls) -> dict:
        """Return the current configuration

        :return: return the _base_config variable
        """
        logger.debug("Get the basic configuration dict.")
        return cls._base_config

    @classmethod
    def set_config(cls, config: dict) -> None:
        """ Set APDriver config directly without calling a bunch of methods

        Update the config (not complete overwrite).
        We want to maintain the main structure and only pass the user defined options
        :param config: the user-defined configuration dict
        :return: return the updated configuration dict
        """
        logger.debug("Update the basic configuration dict.")
        cls._base_config.update(config)

    @classmethod
    def restore_base_config(cls) -> None:
        """ restore the configuration to the default configuration

        :return: return nothing ...
        """
        logger.debug("Restore the basic configuration dict.")
        APDriver._base_config = deepcopy(APDriver._original_config)

    @classmethod
    def _set_config_enabled(cls, feature: str, enabled: bool) -> None:
        """ set the feature enabled

        :param feature: e.g., browser, proxy
        :param enabled: True or False
        :return: return nothing ...
        """
        if feature not in cls._base_config:
            logger.error(f"Unknown configuration option: {feature}.")
            return
            # raise APDriverException("Unknown configuration option: %s" % feature, caller_prefix=APDriver._caller_prefix)
        logger.debug(f"Set the feature: {feature}, as {enabled}.")
        cls._base_config[feature]["enabled"] = enabled
        if not enabled:
            for option in cls._base_config[feature]:
                logger.info(f"Set all the options in {feature} as disabled.")
                cls._base_config[feature][option] = False

    @classmethod
    def _set_config_options(cls, feature: str, **kwargs) -> None:
        """ set the configuration of one feature option

        Only update specific features
        :param feature: e.g., browser, proxy
        :param kwargs: True or False
        :return: return nothing ...
        """
        cls._set_config_enabled(feature, True)
        for param in kwargs:
            if param in cls._base_config[feature]:
                logger.info(f"Set all the options in {feature}.")
                cls._base_config[feature][param] = kwargs[param]

    @classmethod
    def enable_browser_args(cls, **kwargs) -> None:
        cls._set_config_options("browser", **kwargs)

    @classmethod
    def disable_browser_args(cls) -> None:
        logger.info("Disable the browser options.")
        cls._set_config_enabled("browser", False)

    @classmethod
    def set_timeout(cls, timeout: Union[int, float]) -> None:
        logger.info(f"Set the ap_driver timeout: {timeout}.")
        cls._base_config["ap_driver"]["timeout"] = timeout

    @classmethod
    def set_max_retries(cls, max_retries: int) -> None:
        logger.info(f"Set the ap_driver max retries: {max_retries}.")
        cls._base_config["ap_driver"]["max_retries"] = max_retries

    @classmethod
    def set_heartbeat_url(cls, heartbeat_url: str) -> None:
        logger.info(f"Set the ap_driver heartbeat url: {heartbeat_url}.")
        cls._base_config["ap_driver"]["heartbeat_url"] = heartbeat_url

    @classmethod
    def set_scripts(cls, scripts_list: list) -> None:
        logger.info("Load the list of JS files (absolute paths), "
                    "to be evaluated on each new document (before anything else)")
        for script in scripts_list:
            with open(script, "r") as fp:
                APDriver._base_config["ap_driver"]["scripts"] += "\n\n" + fp.read()  # Append JS
                fp.seek(0)

    @classmethod
    def set_scripts_after_load(cls, scripts_list: list) -> None:
        """ Load the list of JS files (absolute paths)

        To be evaluated on each new document (after loading the page)
        """
        logger.info("Load the list of JS files (absolute paths), "
                    "to be evaluated on each new document (after loading the page)")
        for script in scripts_list:
            with open(script, "r") as fp:
                APDriver._base_config["ap_driver"]["scripts_after_load"] += "\n\n" + fp.read()  # Append JS
                fp.seek(0)

    @classmethod
    def boot(cls, **kwargs):
        logger.info("Trying to boot ...")
        for arg in kwargs:
            if kwargs[arg] and arg in APDriver._compatible_browsers:
                logger.info("Finding the ap_driver browser instance type.")
                APDriver._browser_instance_type = arg
                break
        if not APDriver._browser_instance_type:
            logger.error("Need to specify a browser [%s = True]" % "|".join(APDriver._compatible_browsers))
            return None
            # raise APDriverException(
            #     "Need to specify a browser [%s = True]" % "|".join(APDriver._compatible_browsers),
            #     caller_prefix=APDriver._caller_prefix)

        from .browser.CAPDriver import CAPDriver

        if APDriver._browser_instance_type == CHROME:
            logger.debug("Initialize the browser instance as Chrome.")
            constructor: CWebDriver() = CAPDriver
        else:
            logger.error("No available constructor found.")
            raise Exception("No available constructor found.")

        boot_retries: int = 0
        while boot_retries < APDriver._base_config["ap_driver"]["max_boot_retries"]:
            try:
                logger.info("Initialize the Chrome Driver")
                driver: Union[CWebDriver()] = constructor(refs=kwargs.pop("refs", {}),
                                                          redirects=kwargs.pop("redirects", {}),
                                                          retries=kwargs.pop("retries", {}))
                logger.debug("Keep used config for reboots and crash recoveries")
                driver._config = deepcopy(APDriver._base_config)
                if not driver.heartbeat():
                    logger.warning("Driver is not working properly")
                    logger.warning("Driver exited unexpectedly.")
                    driver.quit()
                    logger.error("Driver is not working properly.")
                    return None
                    # raise APDriverException("Driver is not working properly",
                    #                         caller_prefix=APDriver._caller_prefix)
            except sce.WebDriverException as e:
                logger.error("Error while starting XDriver.")
                boot_retries += 1
                if boot_retries < APDriver._base_config["ap_driver"]["max_boot_retries"]:
                    logger.info("Retrying ...")
                    continue
                APDriver.restore_base_config()
                logger.warning("Max retries exceeded, abort process!")
                return False
            logger.success("Browser booted!")
            logger.info("Restore base config, so other instances can be created and configured (differently)")
            APDriver.restore_base_config()
            logger.info("Reset the browser instance type as None.")
            APDriver._browser_instance_type = None
            return driver

    def __init__(self, *args, **kwargs):
        """ A dictionary used to store key value pairs of the form.

        "<WebElement Object>" : (method, *args, **kwargs, element_idx, return_length).
        Whenever a 'find_element_by_*' method is called, the final 'find_element(...)' equivalent will be stored as the value (with its args
        and possible kwargs), together with the reference of the WebElement to be returned (if found) as the key. If a StaleElementReferenceException
        or NoSuchElementException is later raised on that specific element, XDriver will re-invoke that method and try to re-fetch the element in question.

        Same applies for 'find_elements_by_*' methods, but in this case the underlying 'find_elements(...)' will also simulate a 'find_element_by_xpath'
        on each element in the returned list (which is what will be stored in this dict). This way, upon a StaleElementReferenceException, the stale object
        will be restored with the correct instance, otherwise, if we stored the whole list of elements and the actual 'find_elements' method, in case the
        returned list of elements does not match the length of the previously returned list, the exception should be raised, since we wouldn't be sure about which
        element is the correct one. """
        self._crawl_config: dict = {}
        self._last_url: str = ""
        self._recoverable_crashes: list = []
        self._config: dict = {}
        self._virtual_display: Display() = None
        # TODO: modify the type when using the mitmproxy resource
        self._proxy: object = None
        self._profile: str = ""
        self._REFS: dict = kwargs.get("refs", {})
        # Main JS lib needed by APDriver
        with open(self._scripts_file, "r") as fp:
            self._base_config["ap_driver"]["scripts"] += fp.read()
            fp.seek(0)

        """ A dictionary used to store key value pairs of the form.
        
        "https://example.com" : <WebElement Object>.
        Whenever a `get` method is invoked, the given URL will be stored as the key and the landing page's <html> WebElement will be stored as the value.
        The caller can then ask if the driver has been redirected from the specified URL and the stored WebElement will be checked for staleness.
        If the landing URL differs from the given URL, it will also be stored a a separate entry.
        """
        self._REDIRECTS: dict = kwargs.get("redirects", {})

        ''' Retry mode for invoked operations. Each method should have its own counter so they don't get mixed up
        '''
        self._RETRIES: dict = kwargs.get("retries", {})

        self._browser_type: str = APDriver._browser_instance_type

        from .browser.CAPDriver import CAPDriver

        if isinstance(self, CAPDriver):
            logger.info("Trying to start the chrome driver manager ...")
            # c_driver_manager: ChromeDriverManager() = ChromeDriverManager()
            # Chrome.__init__(self, service=CService(c_driver_manager.install()), options=kwargs.get("chrome_options"))
            Chrome.__init__(self, service=kwargs.get("service"), options=kwargs.get("options"))
        logger.success("Starting the chrome driver manager successfully ... ")
        self._children_proc: set = set(
            [child for child in psutil.Process(os.getpid()).children(recursive=True) if
             child not in APDriver._all_children_proc])
        APDriver._all_children_proc = APDriver._all_children_proc.union(self._children_proc)
        logger.info("Add all children processes into the set.")

    def get_profile(self) -> str:
        return self._profile

    """ Auxiliary method to easily run a task (`task_func`) in different browser setups. If no `drivers` list is given, all supported browsers will be used
    with default configurations. This can be further tuned to exclude one of the supported browsers by setting it to False in the `browsers` param. If the
    user wants to fine-tune the configuration of each browser instance under test, they should configure and boot each one before calling this method and
    pass the `drivers` list in the form: [{"browser" : str("browser name/unique ID"), "driver" : <XDriver instance>}, ...].
    The `task_func` function should always accept an XDriver instance as the first argument.
    If instructed to `quit` each instance will immediately shutdown after completing the task. 
    The results are formatted as a dict, of the form {"browser name/unique ID" : {"driver" : <XDriver instance>, "ret" : <task_func's return value>}, ...}
    """

    @classmethod
    def cross_browser_run(cls, task_func: Callable, *args, **kwargs) -> dict:
        drivers = kwargs.pop("drivers", [])
        browsers = kwargs.pop("browsers", {"chrome": True, "firefox": True, "opera": True})
        quit_arg = kwargs.pop("quit", True)

        if not drivers:
            logger.debug(
                "If no booted drivers are provided, default to check all supported browsers w/ default configs")
            for browser in browsers:
                if not browsers[browser]:
                    continue
                logger.info(f"Booting {browser}.")
                driver = APDriver.boot(chrome=browser == CHROME)
                drivers.append({"browser": browser, "driver": driver})

        results = {}
        for driver in drivers:
            ret = task_func(driver["driver"], browser=driver["browser"], *args, **kwargs)
            results[driver["browser"]] = {"driver": driver["driver"], "ret": ret}
            if quit_arg:
                logger.info("Quitting the driver {driver}")
                driver["driver"].quit()

        return results

    def enter_retry(self, method: str, max_retries: int = 10) -> bool:
        # Necessary so nested `_invokes` of the same method won't reset the retry counter
        retries, max_retries = self._RETRIES.get(method, [0, max_retries])
        self._RETRIES[method] = [retries, max_retries]
        if retries <= max_retries:
            return True
        return False

    def exit_retry(self, method: str) -> None:
        # Only need to pop the method name
        self._RETRIES.pop(method, None)

    """ Quit Browser.
    
    Stop virtual display if used, kill child processes (should only be the proxy, if used),
    clear StaleElement handling refs and delete profile if instructed.
    """

    def quit(self, clear_refs: bool = True, delete_profile: bool = True, delete_proxy_config: bool = True) -> None:
        try:
            logger.info("# First quit and then delete the temp profile, otherwise the browser will re-create it.")
            super(APDriver, self).quit()
        except sce.WebDriverException as e:
            logger.error("Exception while quiting browser")
            logger.warning(stringify_exception(e))
        finally:
            if self._virtual_display:
                logger.debug("Make sure Xvfb subprocess exits gracefully")
                self._virtual_display.stop()
            logger.debug("Killing all the child processes. No more grace.")
            self._kill_child_processes()

        if clear_refs:
            logger.debug("Clear StaleElement handling references.")
            self.clear_refs()

        if delete_profile:
            if self._profile in APDriver._forbidden_paths:
                # Logger.spit("Are you nuts? You were about to delete %s" % self._profile, warning = True, caller_prefix = self._caller_prefix)
                logger.error("Forbidden custom profile: %s" % self._profile)
                raise APDriverException("Forbidden custom profile: %s" % self._profile,
                                        caller_prefix=self._caller_prefix)
            try:
                shutil.rmtree(self._profile, ignore_errors=True)
            except sce.WebDriverException as e:
                logger.error("Could not delete custom chrome profile: %s" % self._profile)
                logger.warning(stringify_exception(e))

    def _kill_child_processes(self) -> None:
        killed = set()
        for child in self._children_proc:
            try:
                logger.debug("Don't kill anything other than the specified subprocesses")
                if not any([subproc in child.name() for subproc in APDriver._subprocesses]):
                    continue
                killed.add(child.name())
                logger.info(
                    "We want to send a SIGINT to the mitmdump subprocess, since SIGKIILL-ing it leaves unclean directories in /tmp")
                if 'mitmdump' in child.name():
                    child.send_signal(signal.SIGINT)
                else:
                    child.kill()
            except Exception as e:
                logger.error("Something bad happened ", e)
                pass
        logger.debug("Killed (%s): %s" % (len(killed), str(killed)))

    """ Make sure the browser is working properly
    """

    def heartbeat(self) -> bool:
        try:
            # So, apparently the driver sometimes needs a dummy operation to boot, otherwise the heartbeat might fail consecutively.
            # Need to investigate this more and find a more elegant workaround
            scr_filename = "/tmp/scr_%s.png" % str(uuid4())
            self.save_screenshot(scr_filename)  # So,
            os.remove(scr_filename)  # remove screenshot file if booted
            self.set_page_load_timeout(20)
            # Do not `_invoke` it, we want to see the exception if raised
            super(APDriver, self).get(APDriver._base_config["ap_driver"]["heartbeat_url"])
            # restore page load timeout after successful heartbeat
            self.set_page_load_timeout(APDriver._base_config["ap_driver"]["timeout"])
            return True
        except sce.TimeoutException as e:
            return False

    """ Custom method invoker to globally handle any exceptions that come up
    """

    def _invoke(self, method: Union[str, Callable[..., T]], *args, **kwargs) \
            -> Union[str, set, bool, list, dict, Form.Form, None]:
        web_element = None
        # In case we re-_invoke it, we need the original kwargs
        original_kwargs = dict(kwargs)
        ex = None
        ret_val = None
        try:
            # By default, retry all methods if possible, otherwise explicitly requested
            if kwargs.pop("retry", True):
                self.enter_retry(method,
                                 max_retries=kwargs.pop("max_retries", self._config["ap_driver"]["max_retries"]))
            web_element = kwargs.pop("webelement", None)
            ret_val = method(*args, **kwargs)
            # Need to explicitly set the ret value for WebDriver's get
            if method == super(APDriver, self).get:
                ret_val = True
            # The operation completed, no need to keep the retry counter
            self.exit_retry(method)
            ex = "No Problem"
            return ret_val
        except sce.UnexpectedAlertPresentException as ex:
            self._invoke_exception_handler(self._UnexpectedAlertPresentException_handler)
            # Nothing more to do for a `get`
            if method == super(APDriver, self).get:
                ret_val = True
        except (sce.InvalidSwitchToTargetException, sce.NoSuchFrameException, sce.NoSuchWindowException) as ex:
            # If no windows remain for some reason, raise it
            if len(self.window_handles) == 0:
                raise
            # Return to the default handle
            self.switch_to_default_content()
            ret_val = False
        except sce.InvalidSelectorException as ex:
            ret_val = False
        except (sce.InvalidElementStateException, sce.ElementNotSelectableException, sce.ElementNotVisibleException,
                sce.MoveTargetOutOfBoundsException) as ex:
            # No need to retry the operation since these won't change
            ret_val = False
        except sce.NoSuchElementException:
            ret_val = False
        except (sce.StaleElementReferenceException, sce.NoSuchElementException) as ex:
            # Check _REFS for given WebElement.
            if not self._invoke_exception_handler(self._StaleElementReference_handler, web_element):
                raise
            ret_val = False
        except (sce.TimeoutException, sce.WebDriverException, sce.InvalidCookieDomainException,
                sce.UnableToSetCookieException,
                sce.ImeNotAvailableException,
                sce.ImeActivationFailedException) as ex:
            str_ex = stringify_exception(ex)
            if ex is sce.TimeoutException or any([crash in str_ex for crash in self._recoverable_crashes]):
                # Reboot browser, maintain state and retry the operation
                if not self._invoke_exception_handler(self._TimeoutException_handler):
                    raise
                if method != super(APDriver, self).get:
                    # If it was `get`, it will be retried later on. For anything else, we need to manually go back to the last known URL
                    self.get(self._last_url)
                ret_val = False
            else:
                # The JS script setup we did on page load got screwed over by an async page load
                if "is not defined" in str_ex:
                    self.setup_page_scripts()
                else:
                    raise
        retries, max_retries = self._RETRIES.get(method, [None, None])
        # If we are not in retry mode OR if the retries have exceeded the threshold, either return a default value (if set) or raise the exception to the caller
        if method not in self._RETRIES or retries >= max_retries:
            self.exit_retry(method)
            # If a return value has been set, return it instead of raising the exception
            if ret_val is not None:
                return ret_val
            # These are considered fatal
            raise

        # About to re-invoke method. Increment retry counter
        self._RETRIES[method][0] += 1

        # `ex` may have been deleted automatically after the except clause exits (Python behavior
        # for `except ... as ex:` handlers), so re-fetch it defensively for the retry log.
        try:
            err_str = stringify_exception(ex, strip=True)
        except NameError:
            err_str = "unknown exception"
        logger.info("Retrying for: %s || Because: %s" % (method, err_str))
        return self._invoke(method, *args, **original_kwargs)

    # Exception handler invoker
    def _invoke_exception_handler(self, handler: Callable[..., T], *args, **kwargs) -> bool:
        try:
            return handler(*args, **kwargs)
        except sce.UnexpectedAlertPresentException:
            self._invoke_exception_handler(self._UnexpectedAlertPresentException_handler)
        except sce.NoAlertPresentException:  # This was raised during the _UnexpectedAlertPresentException_handler call.
            self.execute_script("window.alert = null;")
        except sce.TimeoutException:
            return False

    """ The caller must explicitly call this when the stored references are no longer needed,
    
    (e.g. when starting to evaluate a different domain)
    """

    def clear_refs(self) -> None:
        self._REFS = {}

    """ Exception handlers
    
    """

    def _StaleElementReference_handler(self, webelement: WebElement) -> bool:
        logger.debug("Handling StaleElementReferenceException")
        element_ref = id(webelement)
        if element_ref not in self._REFS:
            logger.warning("Stale WebElement not seen before ")
            return False
        method, args, kwargs = self._REFS[element_ref]
        # add some max timeout
        kwargs["timeout"] = 3
        # re-fetch element
        new_element = method(*args, **kwargs)
        # The element is not in the DOM, it's not just stale
        if not new_element:
            logger.warning("Element could not be re-fetched ")
            logger.warning("%s" % str(self._REFS[element_ref]))
            return False
        # Transparently update old web-element's reference
        webelement.__dict__.update(new_element.__dict__)
        return True

    """ If a timeout occurs we need to restore the browser instance, 
    
    since the chromedriver is unresponsive to any interaction with the page.
    Interestingly, `webdriver.quit` and a few other non-page specific commands work fine.
    """

    def _TimeoutException_handler(self) -> bool:
        logger.warning("Handling browser crash. Will try to restore XDriver.")
        # We don't want to clear the _REFS, delete the profile or the proxy config
        self.reboot(clear_refs=False, delete_profile=False, delete_proxy_config=False)
        return True

    """ Switch to the alert, dismiss it, override alert func to null and switch back to page
    """

    def _UnexpectedAlertPresentException_handler(self) -> None:
        logger.warning("Handling UnexpectedAlertPresentException")
        alert = self.switch_to.alert
        alert.dismiss()
        # Try to prevent the page from popping any more alerts
        self.execute_script("window.alert = null;")
        self.switch_to.default_content()

    """ Reboot browser with new profile. Transparent to callers
    """

    def reload_profile(self, profile: str, delete_profile: bool = True) -> None:
        logger.info("Reloading profile to: %s" % profile)
        self._config["browser"]["profile"] = profile
        # Don't clear `_REFS`, but delete old profile if instructed; keep proxy config
        self.reboot(clear_refs=False,
                    delete_profile=delete_profile,
                    delete_proxy_config=False)
        # Maybe this is not necessary
        self.get(self._last_url)

    """ Graceful exit browser and reboot with appropriate settings 
    
    (i.e. same proxy port, virtual display, same or different profile)
    """

    def reboot(self, clear_refs: bool = False, delete_profile: bool = False, delete_proxy_config: bool = False) -> None:
        logger.info("Rebooting browser..")
        # graceful exit (if possible)
        self.quit(clear_refs=clear_refs, delete_profile=delete_profile,
                  delete_proxy_config=delete_proxy_config)
        # Set up the base config to be used by the boot procedure
        APDriver._base_config = self._config

        new_instance = APDriver.boot(chrome=(self._browser_type == CHROME), refs={} if clear_refs else self._REFS,
                                     redirects={} if clear_refs else self._REDIRECTS,
                                     retries={} if clear_refs else self._RETRIES)

        if not new_instance:
            logger.error("Could not reboot browser.")
            raise APDriverException("Could not reboot browser.", caller_prefix=self._caller_prefix)
        # Transparently restore XDriver reference with new one
        self.__dict__.update(new_instance.__dict__)

    """ Webdriver Overridden Methods
    
    Most of the times we want to be aware if the base domain is redirected somewhere else
     (e.g. a "t.co/askjd" URL might redirect to a totally different domain)
    """

    def get(self, url: str, allow_redirections: bool = False) -> bool:
        # Handle single domains without scheme
        if not url.startswith("http"):
            url = "http://%s" % url
        # Store the last URL that was explicitly visited. Might be needed if the driver hangs to restore state
        self._last_url = url
        if not self._invoke(super(APDriver, self).get, url, max_retries=2):
            # If it timeouts, return False
            return False
        if not allow_redirections:
            redirection_url = self.current_url()
            if URLUtils.get_main_domain(url) != URLUtils.get_main_domain(redirection_url):
                logger.warning("%s redirected to: %s" % (url, redirection_url))
                return False
        self.setup_page_scripts()
        self.store_reference_element(url)
        # also landing URL in case it differs from the passed URL; quite common
        self.store_reference_element(self.current_url())
        return True

    # Set the last known URL (i.e. to a location that we didn't explicitly `get`)
    def set_last_url(self, url: str) -> None:
        self._last_url = url

    """ This is necessary since webdriver 's `page_source` is @property defined and thus cannot be safely invoked
    
    """

    def page_source(self) -> str:
        return self._invoke(self._page_source)

    def _page_source(self) -> str:
        return super(APDriver, self).page_source

    def rendered_source(self) -> str:
        return self._invoke(self.execute_script, "return document.getElementsByTagName('html')[0].innerHTML")

    """ This is necessary since webdriver 's `current_url` is @property defined and thus cannot be safely invoked 
    
    """

    def current_url(self) -> str:
        return self._invoke(self._current_url)

    def _current_url(self) -> str:
        return super(APDriver, self).current_url

    """ Try to switch to the given window
    """

    def switch_to_window(self, window_handle) -> bool:
        return self._invoke(self._switch_to_window, window_handle)

    def _switch_to_window(self, window_handle) -> bool:
        # Default `switch_to.window` hangs in case there is an open alert,
        # so we need a dummy op to trigger the alert handling
        self.execute_script("return 2;")
        self.switch_to.window(window_handle)
        return True

    """ Switch back to the default content
    """

    def switch_to_default(self) -> bool:
        return self._invoke(self._switch_to_default)

    def _switch_to_default(self) -> bool:
        self.switch_to.window(self.window_handles[0])
        return True

    def switch_to_default_content(self) -> bool:
        return self._invoke(self._switch_to_default_content)

    def _switch_to_default_content(self) -> bool:
        self.switch_to.default_content()
        return True

    """ Get and clear local/session storage
    """

    def get_local_storage(self) -> Union[dict, str, list, bool]:
        try:
            return self._invoke(self.execute_script, "return get_local_storage();")
        except Exception as e:
            logger.error("Something bad happened ", e)
            return {}

    def get_session_storage(self) -> Union[dict, str, list, bool]:
        try:
            return self._invoke(self.execute_script, "return get_session_storage();")
        except Exception as e:
            logger.error("Something bad happened ", e)
            return {}

    def clear_local_storage(self) -> bool:
        return self._invoke(self._clear_local_storage)

    def _clear_local_storage(self) -> bool:
        self.execute_script("localStorage.clear();")
        return True

    def clear_session_storage(self) -> bool:
        return self._invoke(self._clear_session_storage)

    def _clear_session_storage(self) -> bool:
        self.execute_script("sessionStorage.clear();")
        return True

    def clear_storage(self) -> None:
        self.clear_local_storage()
        self.clear_session_storage()

    """ Find and return an element after the given timeout
    """

    def find_element(self, by: str = By.ID, value: Optional[str] = None, timeout: int = 0, visible: bool = False,
                     webelement: WebElement = None) -> Union[WebElement, None]:

        # because the expected condition below (implementing the timeout) recursively calls `find_element`,
        # and a stack overflow occurs. Therefore, this ensures that the EC's calls will actually call the parent method
        if timeout == 0 and visible is False:
            ret = self._invoke(super(APDriver, self).find_element,
                               by=by, value=value) \
                if webelement is None else self._invoke(
                self._webelement_find_element_by,
                webelement,
                by=by, value=value)
        else:
            try:
                condition = EC.presence_of_element_located if not visible else EC.visibility_of_element_located
                ret = WebDriverWait(self, timeout).until(condition((by, value)))
            except sce.TimeoutException:
                return None

        ref = id(ret)
        if ret:
            self._REFS[ref] = (self.find_element, (),
                               {"by": by, "value": value,
                                "timeout": timeout, "visible": visible,
                                "webelement": webelement})
        return ret

    @staticmethod
    def _webelement_find_element_by(element, by: str = By.ID, value: Optional[str] = None) -> Union[WebElement, None]:
        return element.find_element(by=by, value=value)

    """ Find and return all matching elements after the given timeout
    """

    def find_elements(self, by: str = By.ID, value: Optional[str] = None, timeout: int = 0, visible: bool = False,
                      webelement: WebElement = None, *args, **kwargs) -> list:
        # We have to call this first b/c we need to simulate the given timeout.
        # Essentially wait for at least one such element to appear
        if timeout > 0:
            self.find_elements(by=by, value=value, timeout=timeout,
                               visible=visible, webelement=webelement,
                               *args, **kwargs)
        ret_elements = self._invoke(super(APDriver, self).find_elements,
                                    by=by, value=value, *args, **kwargs) \
            if webelement is None else self._invoke(self._webelement_find_elements_by,
                                                    webelement, by=by, value=value,
                                                    webelement=webelement, *args, **kwargs)
        if ret_elements:
            to_remove = set()
            # dom_paths = []
            # Collect the returned elements' DOMPath

            for el in ret_elements:
                try:
                    el_dompath = self.get_dompath(el)
                except sce.StaleElementReferenceException:
                    to_remove.add(el)
                    continue
                # Make sure the returned elements are robust against StaleElementReferenceExceptions by simulating a `find_element_by_xpath`
                ref = id(el)
                # If not already previously fetched
                if ref not in self._REFS:
                    self._REFS[ref] = (
                        self.find_element, (),
                        {"by": By.XPATH, "value": el_dompath,
                         "timeout": 5, "visible": False})

            for el in to_remove:
                ret_elements.remove(el)

        return ret_elements

    @staticmethod
    def _webelement_find_elements_by(element, by: str = By.ID, value: Optional[str] = None, *args, **kwargs):
        return element.find_elements(by=by, value=value, *args, **kwargs)

    """ Wrapper `find_element(s)` methods.
    """

    def find_element_by_id(self, id_: str, timeout: int = 0, visible: bool = False, webelement: WebElement = None) -> \
            Union[WebElement, None]:
        return self.find_element(By.ID, value=id_, timeout=timeout, visible=visible, webelement=webelement)

    def find_elements_by_id(self, id_: str, timeout: int = 0, visible: bool = False, webelement: WebElement = None,
                            *args, **kwargs) -> list:
        return self.find_elements(By.ID, value=id_, timeout=timeout, visible=visible, webelement=webelement, *args,
                                  **kwargs)

    def find_element_by_name(self, name_: str, timeout: int = 0, visible: bool = False,
                             webelement: WebElement = None) -> Union[WebElement, None]:
        return self.find_element(By.NAME, value=name_, timeout=timeout, visible=visible, webelement=webelement)

    def find_elements_by_name(self, name_: str, timeout: int = 0, visible: bool = False, webelement: WebElement = None,
                              *args, **kwargs) -> list:
        return self.find_elements(By.NAME, value=name_, timeout=timeout, visible=visible, webelement=webelement, *args,
                                  **kwargs)

    def find_element_by_class_name(self, class_name_: str, timeout: int = 0, visible: bool = False,
                                   webelement: WebElement = None) -> Union[WebElement, None]:
        return self.find_element(By.CLASS_NAME, value=class_name_, timeout=timeout, visible=visible,
                                 webelement=webelement)

    def find_elements_by_class_name(self, class_name_: str, timeout: int = 0, visible: bool = False,
                                    webelement: WebElement = None, *args, **kwargs) -> list:
        return self.find_elements(By.CLASS_NAME, value=class_name_, timeout=timeout, visible=visible,
                                  webelement=webelement, *args, **kwargs)

    def find_element_by_xpath(self, xpath_: str, timeout: int = 0, visible: bool = False,
                              webelement: WebElement = None) -> Union[WebElement, Form.Form, None]:
        return self.find_element(By.XPATH, value=xpath_, timeout=timeout, visible=visible, webelement=webelement)

    def find_elements_by_xpath(self, xpath_: str, timeout: int = 0, visible: bool = False,
                               webelement: WebElement = None, *args, **kwargs) -> list:
        return self.find_elements(By.XPATH, value=xpath_, timeout=timeout, visible=visible, webelement=webelement,
                                  *args, **kwargs)

    def find_element_by_css_selector(self, css_selector_: str, timeout: int = 0, visible: bool = False,
                                     webelement: WebElement = None) -> Union[WebElement, None]:
        return self.find_element(By.CSS_SELECTOR, value=css_selector_, timeout=timeout, visible=visible,
                                 webelement=webelement)

    def find_elements_by_css_selector(self, css_selector_: str, timeout: int = 0, visible: bool = False,
                                      webelement: WebElement = None, *args, **kwargs) -> list:
        return self.find_elements(By.CSS_SELECTOR, value=css_selector_, timeout=timeout, visible=visible,
                                  webelement=webelement, *args, **kwargs)

    def find_element_by_link_text(self, link_text_: str, timeout: int = 0, visible: bool = False,
                                  webelement: WebElement = None) -> Union[WebElement, None]:
        return self.find_element(By.LINK_TEXT, value=link_text_, timeout=timeout, visible=visible,
                                 webelement=webelement)

    def find_elements_by_link_text(self, link_text_: str, timeout: int = 0, visible: bool = False,
                                   webelement: WebElement = None, *args, **kwargs) -> list:
        return self.find_elements(By.LINK_TEXT, value=link_text_, timeout=timeout, visible=visible,
                                  webelement=webelement, *args, **kwargs)

    def find_element_by_tag_name(self, tag_name_: str, timeout: int = 0, visible: bool = False,
                                 webelement: WebElement = None) -> Union[WebElement, None]:
        return self.find_element(By.TAG_NAME, value=tag_name_, timeout=timeout, visible=visible, webelement=webelement)

    def find_elements_by_tag_name(self, tag_name_: str, timeout: int = 0, visible: bool = False,
                                  webelement: WebElement = None, *args, **kwargs) -> list:
        return self.find_elements(By.TAG_NAME, value=tag_name_, timeout=timeout, visible=visible, webelement=webelement,
                                  *args, **kwargs)

    def find_element_by_partial_link_text(self, partial_link_text_: str, timeout: int = 0, visible: bool = False,
                                          webelement: WebElement = None) -> Union[WebElement, None]:
        return self.find_element(By.PARTIAL_LINK_TEXT, value=partial_link_text_, timeout=timeout, visible=visible,
                                 webelement=webelement)

    def find_elements_by_partial_link_text(self, partial_link_text_: str, timeout: int = 0, visible: bool = False,
                                           webelement: WebElement = None, *args,
                                           **kwargs) -> list:
        return self.find_elements(By.PARTIAL_LINK_TEXT, value=partial_link_text_, timeout=timeout, visible=visible,
                                  webelement=webelement, *args, **kwargs)

    """ Auxiliary methods
    """

    def has_loaded(self, timeout: int = 0) -> bool:
        """
        Check whether the current page has loaded or not
        """
        end = time() + timeout
        while time() < end:
            if self._invoke(self.execute_script, "return document.readyState == \"complete\""):
                return True
            sleep(0.1)  # let it breathe
        return False

    def is_redirected(self, url: str, timeout: int = 5) -> bool:
        """
        Check if the webdriver has been redirected after fetching the given URL,
        using the reference element stored at that time
        """
        return self._invoke(self._is_redirected, url, timeout=timeout)

    def _is_redirected(self, url: str, timeout: int = 5) -> bool:
        reference_element = self._REDIRECTS.get(url, None)
        if reference_element is None:  # If an unknown URL is given, return True
            # Logger.spit("Unknown URL in `is_redirected` (%s)" % url, warning=True, caller_prefix=self._caller_prefix)
            print("Unknown URL in `is_redirected` (%s)" % url)
            return True
        end = time() + timeout
        while time() < end:
            try:
                reference_element.text  # dummy op to trigger the exception
            except sce.StaleElementReferenceException as e:
                return True
        return False

    def store_reference_element(self, url: str) -> None:
        # We directly use the parent class method, so the element will not be re-fetched when asked if stale,
        # since 'html' tags are always there and `is_stale` would always return True
        _redirection_element = super(APDriver, self).find_element(By.TAG_NAME, "html")
        self._REDIRECTS[url] = _redirection_element

    def wait_for_url_change(self, url: str, timeout: int = 5) -> bool:
        end = time() + timeout
        while time() < end:
            current = self.current_url()
            if current != url:
                return True
        return False

    def is_stale(self, element, visible: bool = False) -> bool:
        """
        Given a web element try to identify whether it has become stale or not
        """
        # Logger.set_warning_off()
        try:
            self.get_attribute(element, "id")  # dummy operation to see if we can re-fetch the element or not
            stale = False
        except sce.StaleElementReferenceException as e:
            stale = True
        # Logger.set_warning_on()
        return stale

    """ Move mouse over an element; triggers the 'mouseenter' DOM event
    """

    def move_to_element(self, element) -> bool:
        return self._invoke(self._move_to_element, element, webelement=element)

    def _move_to_element(self, element) -> bool:
        ActionChains(self).move_to_element(element).perform()
        return True

    """ Move mouse over an element and then away; triggers the 'mouseleave' DOM event
    """

    def move_away_from_element(self, element) -> bool:
        return self._invoke(self._move_away_from_element, element, webelement=element)

    def _move_away_from_element(self, element) -> bool:
        ActionChains(self).move_to_element(element).move_by_offset(100, 100).perform()
        # self.find_elements_by_tag_name("body")[0].click() # Dummy op to move away from element
        return True

    """ Move cursor over an element; triggers the 'mousemove' DOM event
    """

    def move_over_element(self, element) -> bool:
        return self._invoke(self._move_over_element, element, webelement=element)

    def _move_over_element(self, element) -> bool:
        ActionChains(self).move_to_element(element).move_by_offset(1, 1).move_by_offset(-1, -1).perform()
        return True

    """ Simple click. Goes over the given element and clicks.
    """

    def _click(self, element) -> bool:
        ActionChains(self).move_to_element(element).click().perform()
        return True

    def exact_click(self, element) -> bool:
        return self._invoke(self._exact_click, element, webelement=element)

    @staticmethod
    def _exact_click(element) -> bool:
        element.click()
        return True

    """ Useful for invisible elements that we want to trigger their `onClick`. 
    Also, since sometimes the element at hand is not the actual clickable,
    but rather a parent of the clickable, we might need to traverse and `js_click` its children
    """

    def js_click(self, element, with_children: bool = False) -> bool:
        return self._invoke(self._js_click, element, with_children=with_children, webelement=element)

    def _js_click(self, element, with_children: bool = False) -> bool:
        sleep(2)  # monkey fix for specific cases. let the clickable load its events (?)
        self.execute_script("arguments[0].click()", element)
        if with_children:
            try:
                children = self.find_elements_by_xpath(".//*", webelement=element)
                for child in children:
                    self.execute_script("arguments[0].click()", child)
            except sce.WebDriverException as ex:  # If one of the clicks causes a redirection, we most likely found what we were looking for
                if ex is sce.StaleElementReferenceException or "arguments[0].click is not a function" in stringify_exception(
                        ex):
                    logger.error("Something bad happened ", ex)
        return True

    def double_click(self, element) -> bool:
        return self._invoke(self._double_click, element, webelement=element)

    def _double_click(self, element) -> bool:
        ActionChains(self).move_to_element(element).double_click().perform()
        return True

    def context_click(self, element) -> bool:
        return self._invoke(self._context_click, element, webelement=element)

    def _context_click(self, element) -> bool:
        ActionChains(self).move_to_element(element).context_click().perform()
        return True

    # Wheel click
    def middle_click(self, element):
        return self._invoke(self._middle_click, element, webelement=element)

    def _middle_click(self, element) -> bool:
        self.execute_script(
            "var mouseWheelClick = new MouseEvent( \"click\", { \"button\": 1, \"which\": 1 }); arguments[0].dispatchEvent(mouseWheelClick)",
            element)
        return True

    """ Click and hold on the element; triggers the 'mousedown' DOM event
    """

    def mousedown(self, element) -> bool:
        return self._invoke(self._mousedown, element, webelement=element)

    def _mousedown(self, element) -> bool:
        ActionChains(self).move_to_element(element).click_and_hold().perform()
        return True

    """ Click and hold and then release the mouse on the element; 
    
    triggers the 'mouseup' event
    """

    def mouseup(self, element):
        return self._invoke(self._mouseup, element, webelement=element)

    def _mouseup(self, element) -> bool:
        ActionChains(self).move_to_element(element).click_and_hold().release().perform()
        return True

    def send_keys(self, element, keys) -> bool:
        return self._invoke(self._send_keys, element, keys, webelement=element)

    @staticmethod
    def _send_keys(element, keys) -> bool:
        element.send_keys(keys)
        return True

    def submit(self, element) -> bool:
        return self._invoke(self._submit, element, webelement=element)

    def _submit(self, element) -> bool:
        # element.submit()
        self.execute_script("arguments[0].submit()", element)
        return True

    """ Trigger the 'onsubmit' DOM event via locating and clicking the submit button
    
    If that fails, fall back to default `submit` above
    """

    def onsubmit(self, element) -> bool:
        return self._invoke(self._onsubmit, element, webelement=element)

    def _onsubmit(self, element) -> bool:
        try:
            submit_el = self.find_element_by_xpath(".//input[@type='submit']", webelement=element)
            ActionChains(self).move_to_element(submit_el).click().perform()
        except Exception as e:
            logger.error("Something bad happened ", e)
            self.submit(element)
        return True

    def reset(self, element) -> bool:
        return self._invoke(self._reset, element, webelement=element)

    def _reset(self, element) -> bool:
        self.execute_script("arguments[0].reset()", element)
        return True

    """ Trigger the 'onreset' DOM event via locating and clicking the reset button
    
    If that fails, fall back to default `reset` above
    """

    def onreset(self, element) -> bool:
        return self._invoke(self._onreset, element, webelement=element)

    def _onreset(self, element) -> bool:
        try:
            reset_el = self.find_element_by_xpath(".//input[@type='reset']", webelement=element)
            ActionChains(self).move_to_element(reset_el).click().perform()
        except Exception as e:
            logger.error("Something bad happened, ", e)
            self.reset(element)
        return True

    """ Trigger 'onfocus' and 'on focus in' DOM events
    """

    def focus(self, element) -> bool:
        return self._invoke(self._focus, element, webelement=element)

    def _focus(self, element) -> bool:
        try:
            ActionChains(self).move_to_element(element).click().perform()
        except Exception as e:
            self.execute_script("arguments[0].focus()", element)  # Fallback to JS
            logger.error("Something bad happened, ", e)
        return True

    """ Trigger 'on focus out' DOM event
    """

    def focusout(self, element) -> bool:
        return self._invoke(self._focusout, element, webelement=element)

    def _focusout(self, element) -> bool:
        try:
            self.execute_script("arguments[0].focus(); arguments[0].blur()", element)
        except Exception as e:
            # Click element to place focus, then click on upper left corner to remove focus
            ActionChains(self).move_to_element(element).click().move_by_offset(-2000, -2000).click().perform()
            logger.error("Something bad happened, ", e)
        return True

    """ Trigger 'onblur' DOM event
    """

    def blur(self, element) -> bool:
        return self._invoke(self._blur, element, webelement=element)

    def _blur(self, element) -> bool:
        try:
            self.execute_script("arguments[0].focus(); arguments[0].blur()", element)
        except Exception as e:
            # Click element to place focus, then click on upper left corner to remove focus
            ActionChains(self).move_to_element(element).click().move_by_offset(-2000, -2000).click().perform()
            logger.error("Something bad happened, ", e)
        return True

    """ This MUST be called before anything else in the current page's context, 
    
    so after a `get` or when redirected
    """

    def setup_page_scripts(self) -> None:
        # if self._browser_instance_type == FIREFOX: # Only needed for firefox. Chromium-based browsers use the DevTools API to add scripts on new docs
        self._invoke(self._setup_page_scripts)

    def _setup_page_scripts(self) -> None:
        # The gPt library is normally injected via CDP (Page.addScriptToEvaluateOnNewDocument),
        # but that does not cover cross-origin iframes (e.g. DataDome captcha frames).
        # If it is missing in the current context, inject it here.
        try:
            if self.execute_script("return typeof gPt;") != "function":
                with open(self._scripts_file, "r") as fp:
                    self.execute_script(fp.read())
        except Exception:
            pass

    # ===== 嫁接新增方法 =====

    # form_detection_addons.js 文件路径
    _addons_file: str = os.path.join(_abs_path, "js", "form_detection_addons.js")

    @classmethod
    def set_addons_file(cls, path: str) -> None:
        """设置 form_detection_addons.js 的路径"""
        cls._addons_file = path

    def setup_form_detection_addons(self) -> None:
        """注入 form_detection_addons.js（邮箱检测 + 链接发现）

        依赖 scripts.js 已注入（Fathom 框架 + gPt + onTopLayer）。
        通过检查 detectEmailInputs 函数是否存在来判断是否需要注入。
        """
        self._invoke(self._setup_form_detection_addons)

    def _setup_form_detection_addons(self) -> None:
        try:
            if self.execute_script("return typeof detectEmailInputs;") != "function":
                if os.path.isfile(self._addons_file):
                    with open(self._addons_file, "r", encoding="utf-8") as fp:
                        self.execute_script(fp.read())
        except Exception:
            pass

    def inject_login_link_discovery(self) -> None:
        """注入 scripts.js + form_detection_addons.js 到当前页面

        确保两个 JS 文件都已加载，顺序：scripts.js（Fathom 基础）→ addons（扩展功能）
        """
        self.setup_page_scripts()          # scripts.js
        self.setup_form_detection_addons()  # form_detection_addons.js

    # ------------------------------------------------------------------
    # 反自动化检测 (Anti-Bot)
    # ------------------------------------------------------------------

    def setup_anti_bot(self) -> None:
        """注入 notABot.js —— 修补 navigator.webdriver / chrome.runtime / plugins

        通过 CDP Page.addScriptToEvaluateOnNewDocument 注入，
        确保在每个新页面加载前执行，隐藏自动化痕迹。
        """
        self._invoke(self._setup_anti_bot)

    def _setup_anti_bot(self) -> None:
        try:
            if self.execute_script("return window.__notABotInjected;") is not True:
                if os.path.isfile(self._notabot_file):
                    with open(self._notabot_file, "r", encoding="utf-8") as fp:
                        self.execute_script(fp.read())
                    self.execute_script("window.__notABotInjected = true;")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CMP 弹窗检测与处理 (Consent Management Platform)
    # ------------------------------------------------------------------

    def setup_cmp_detection(self) -> None:
        """注入 cmpDetect.js (Consent-O-Matic) —— CMP 弹窗检测与处理引擎

        通过 CDP Page.addScriptToEvaluateOnNewDocument 注入，
        包含 ConsentEngine、CMP rules、GDPRConfig 等，
        自动检测并关闭常见的 Cookie Consent 弹窗。
        """
        self._invoke(self._setup_cmp_detection)

    def _setup_cmp_detection(self) -> None:
        try:
            if self.execute_script("return typeof ConsentEngine;") != "function":
                if os.path.isfile(self._cmpdetect_file):
                    with open(self._cmpdetect_file, "r", encoding="utf-8") as fp:
                        self.execute_script(fp.read())
        except Exception:
            pass

    def detect_and_handle_cmp(self, page_load_wait: float = 6.0,
                              action: str = "ACCEPT_ALL") -> bool:
        """在页面加载后等待 CMP 弹窗出现并自动处理

        模仿 LoginFormExploration helpers/utils.js 的 findCMP() 轮询逻辑：
        - 每 300ms 检查一次 CMP 是否检测到
        - 最长等待 page_load_wait 秒
        - 检测到后额外等待 2.5 秒让弹窗消失

        Args:
            page_load_wait: CMP 检测最长等待时间（秒）
            action: CMP 处理策略: 'NO_ACTION' | 'ACCEPT_ALL' | 'REJECT_ALL'

        Returns:
            True 如果检测到并处理了 CMP，否则 False
        """
        import time
        poll_interval = 0.3
        max_polls = int(page_load_wait / poll_interval)

        self._invoke(self._start_cmp_engine, action)

        for _ in range(max_polls):
            time.sleep(poll_interval)
            try:
                detected = self._invoke(self.execute_script,
                                        "return window.__cmpDetected === true;")
                if detected:
                    logger.info("CMP 弹窗已检测并处理")
                    time.sleep(2.5)  # POST_CMP_DETECTION_WAIT_TIME
                    return True
            except Exception:
                pass
        return False

    def _start_cmp_engine(self, action: str = "ACCEPT_ALL") -> None:
        """在浏览器上下文中实例化 ConsentEngine 并开始监听"""
        try:
            if self.execute_script("return typeof ConsentEngine;") != "function":
                return
            self.execute_script("""
                (function() {
                    if (window.__cmpEngineStarted) return;
                    window.__cmpEngineStarted = true;
                    window.__cmpDetected = false;

                    var config = (typeof cmpConfigData !== 'undefined') ? cmpConfigData : {};
                    var consentTypes = GDPRConfig ? GDPRConfig.defaultValues : {};
                    var debugValues = GDPRConfig ? GDPRConfig.defaultDebugFlags : {};

                    if ('""" + action + """' === 'NO_ACTION') {
                        debugValues.skipActions = true;
                    } else if ('""" + action + """' === 'ACCEPT_ALL') {
                        consentTypes = {A: true, B: true, D: true, E: true, F: true, X: true};
                    }

                    var engine = new ConsentEngine(config, consentTypes, debugValues, function(stats) {
                        window.__cmpDetected = true;
                    });
                })();
            """)
        except Exception:
            pass

    """ Returns True if the given WebElement appears to be on the top layer of the canvas
    """

    def isOnTopLayer(self, element) -> bool:
        return self._invoke(self.execute_script, "return onTopLayer(arguments[0]);", element, webelement=element)

    def is_displayed(self, element) -> bool:
        return self._invoke(self._is_displayed, element, webelement=element)

    @staticmethod
    def _is_displayed(element) -> bool:
        return element.is_displayed()

    """ Return a list of all anchor's `href` attributes, that point to the same domain
    """

    def get_internal_links(self) -> list:
        hrefs = self._invoke(self._get_internal_links)
        return hrefs

    def _get_internal_links(self) -> list:
        domain = URLUtils.get_main_domain(self.current_url())
        hrefs = []
        for anchor in self.find_elements_by_tag_name("a", timeout=0):
            try:
                # Don't be strict in stale references here, just move on
                href = anchor.get_attribute("href")
            except sce.StaleElementReferenceException:
                continue
            if URLUtils.get_main_domain(href) == domain:
                # We don't want visiting and probably downloading any irrelevant file. Also don't consider fragments
                if re.search(APDriver._forbidden_suffixes, href.split("#")[0], re.IGNORECASE):
                    continue
                hrefs.append(href)
        return hrefs

    def get_password_forms(self, *args, **kwargs) -> list:
        ret = self._invoke(self.execute_script, "return get_password_forms();")
        password_forms = []
        for form in ret:
            form, form_dompath = form
            password_forms.append(form)
            self._REFS[id(form)] = (
                self.find_element, (), {"by": By.XPATH, "value": form_dompath, "timeout": 5, "visible": False})
        return password_forms

    def _get_account_forms(
            self,
            access_form: list,
            login_only: bool = False,
            signup_only: bool = False
    ) -> [list, list]:
        """ When running in virtual or headless mode,
        the window is not fully maximized as in the real display.
        This causes the js code to misidentify account forms as not displayed,
        when they are, and thus they are not returned.
        The loop and `scroll_to` on all displayed forms of the page is necessary to avoid this.
        Not efficient but necessary. """
        login_forms = []
        signup_forms = []
        for f in access_form:
            append_dict = {
                # 0 means False
                "is_iframe": 0,
                "iframe_xpath": "",
                "is_click": 0,
                "click_xpath": "",
                # "form_element": None,
                "form_xpath": ""
            }
            if isinstance(f, list):
                f_click = f[1]
                append_dict["is_click"] = 1
                append_dict["click_xpath"] = self.get_dompath(f_click)
                f = f[0]
                f_click.click()
            # if f:
            #     self.scroll_to(f)
            # else:
            #     self.scroll_to_top()
            ret_list = self._invoke(self.execute_script, "return checkOneWebElementFormOrNot(arguments[0]);", f)
            # ret = self._invoke(self.execute_script, "return get_account_forms();")
            if ret_list[0] == 0:
                # We do not expect that this scenario will happen, as it's time-consuming
                # But some pages will load something before showing the form, -_-''' e.g., github.com
                sleep(random.randint(10, 15))
                ret_list = self._invoke(self.execute_script, "return checkOneWebElementFormOrNot(arguments[0]);", f)
                if ret_list[0] == 0:
                    # No forms, or something went terribly wrong
                    continue
            # self._REFS[id(form)] = (self.find_element, (), {"by" : By.XPATH, "value" : form_dompath, "timeout" : 5, "visible" : False})
            # SIGNUP FORM
            if ret_list[0] == 2:
                form, form_dompath = f, ret_list[1]
                if form in login_forms or not self.is_displayed(form):
                    continue
                # append_dict["form_element"] = form
                append_dict["form_xpath"] = form_dompath
                login_forms.append(append_dict)
                self._REFS[id(form)] = (
                    self.find_element, (), {"by": By.XPATH, "value": form_dompath, "timeout": 5, "visible": False})
            if ret_list[0] == 1:
                form, form_dompath = f, ret_list[1]
                if form in signup_forms or not self.is_displayed(form):
                    continue
                # append_dict["form_element"] = form
                append_dict["form_xpath"] = form_dompath
                signup_forms.append(append_dict)
                self._REFS[id(form)] = (
                    self.find_element, (), {"by": By.XPATH, "value": form_dompath, "timeout": 5, "visible": False})
            if (login_only and login_forms) or (signup_only and signup_forms) or (
                    not login_only and not signup_only and login_forms and signup_forms):
                return login_forms, signup_forms
        return login_forms, signup_forms

    """ Returns a tuple of two lists with all login and registration forms -> (login_forms, reg_forms)
    """

    def get_account_forms(self, login_only: bool = False, signup_only: bool = False, *args, **kwargs) -> [list, list]:
        """ When running in virtual or headless mode, the window is not fully maximized as in the real display.
            This causes the js code to misidentify account forms as not displayed, when they are, and thus they are not returned
            The loop and `scroll_to` on all displayed forms of the page is necessary to avoid this. Not efficient but necessary. """
        login_forms = []
        signup_forms = []
        displayed_forms = self.get_displayed_forms()
        # print(displayed_forms)
        # Dummy 1st element, so we try to fetch any account forms without messing with the scroll
        displayed_forms.insert(0, None)

        displayed_login_forms, displayed_signup_forms = self._get_account_forms(
            displayed_forms,
            login_only,
            signup_only)

        login_forms += displayed_login_forms
        signup_forms += displayed_signup_forms

        if not login_forms and not signup_forms:
            # if no forms are found, we will find new forms in iframes
            # But I don't know whether this logic is reasonable enough
            displayed_iframes = self.get_iframes()
            # Dummy 1st element, so we try to fetch any account forms without messing with the scroll
            displayed_iframes.insert(0, {"iframe": None, "form_list": []})
            for f_dict in displayed_iframes:
                # print(f_dict)
                self.switch_to.frame(f_dict["iframe"])
                iframes_login_forms, iframes_signup_forms = self._get_account_forms(
                    f_dict["form_list"],
                    login_only,
                    signup_only)
                new_iframes_login_forms = [{
                    **tmp, 'is_iframe': 1,
                    'iframe_xpath': f_dict["iframe_xpath"]
                } for tmp in iframes_login_forms]

                new_iframes_signup_forms = [{
                    **tmp, 'is_iframe': 1,
                    'iframe_xpath': f_dict["iframe_xpath"]
                } for tmp in iframes_signup_forms]
                login_forms += new_iframes_login_forms
                signup_forms += new_iframes_signup_forms
                self.switch_to.default_content()

        return login_forms, signup_forms

    def get_displayed_forms(self) -> list:
        return self._invoke(self._get_displayed_forms)

    def _get_displayed_forms(self) -> list:
        forms = self.find_elements_by_tag_name("form")
        ret_forms = []
        for form in forms:
            try:
                if self.is_displayed(form):
                    ret_forms.append(form)
            except sce.StaleElementReferenceException as e:
                continue

        """ We have two TODOs for future planning
        
        TODO: Need to consider the block elements like divs that used as forms -- maybe later -- now only for douban.com
        TODO: Consider how to click the no-redirection clickable element with keywords
        But this case is really rarely happened, or not wanted, so I don't want to consume too much time
        1. Find all elements containing the keywords ...
        2. Click it to check whether it will redirect to another page
        3. If not, find all the forms and divs in the page 
        """
        if not ret_forms:
            original_url = self.current_url()
            # TODO: Modify this after considering well for this part ... Maybe in the next version
            text_to_find: list = [
                "password", "passwort", "密码",
            ]
            for kw in text_to_find:
                switch_elements: list = self.find_elements_by_xpath(f"//*[contains(text(), '{kw}')]")
                for switch_element in switch_elements:
                    try:
                        if not self.is_displayed(switch_element):
                            logger.warning("This element is not displayed.")
                        sleep(0.1)
                        switch_element.click()
                        if self.current_url() == original_url:
                            new_forms = self.find_elements_by_tag_name("form")
                            for form in new_forms:
                                try:
                                    if self.is_displayed(form):
                                        ret_forms.append(form)
                                except sce.StaleElementReferenceException as e:
                                    continue
                            if not new_forms:
                                my_divs = self.find_elements_by_xpath(
                                    "//*[contains(@id, 'form') or contains(@class, 'form')]")
                                # for my_div in my_divs:
                                #     print("class", my_div.get_attribute("class"))
                                #     print("id", my_div.get_attribute("id"))
                                min_element: WebElement = self.find_element(By.TAG_NAME, "body")
                                for my_div in my_divs:
                                    my_res = self.execute_script(
                                        "return checkOneWebElementFormOrNot(arguments[0]);", my_div)
                                    my_xpath = self.get_dompath(my_div)
                                    if my_res[0] > 0:
                                        if min_element is None or len(
                                                min_element.find_elements(By.XPATH, my_xpath)) > 0:
                                            logger.debug("This is not the most inner element ... ")
                                            min_element = my_div
                                        logger.success("Find a hidden form ... ")
                                ret_forms.append([min_element, switch_element])
                        else:
                            self.back()
                    except Exception as e:
                        logger.warning(f"Error clicking on element which is not intractable", e)
        # print("ret_forms", ret_forms)
        return ret_forms

    def get_iframes(self) -> list:
        return self._invoke(self._get_iframes)

    def _get_iframes(self) -> list:
        ret_iframes: list = []
        found_iframes: list = self.find_elements_by_tag_name("iframe")
        for found_iframe in found_iframes:
            # Switch into the iframe
            # self.switch_to.frame(found_iframe)
            iframe_url = found_iframe.get_attribute("src")
            iframe_xpath = self.get_dompath(found_iframe)

            if iframe_url and iframe_url != "about:black":
                self.switch_to.frame(found_iframe)
                self.setup_page_scripts()
                form_list = self._get_displayed_forms()
                self.switch_to.default_content()
                if not form_list:
                    continue
                ret_iframes.append({
                    "iframe": found_iframe,
                    "iframe_xpath": iframe_xpath,
                    "form_list": form_list
                })
        return ret_iframes

    def get_login_forms(self, *args, **kwargs) -> list:
        return self.get_account_forms(login_only=True, *args, **kwargs)[0]

    def get_signup_forms(self, *args, **kwargs) -> list:
        return self.get_account_forms(signup_only=True, *args, **kwargs)[0]

    def fill_form(self, form: dict, submit: bool = False, required_only: bool = False,
                  override_rules=None, test_password: str = "") -> [list, dict]:
        if override_rules is None:
            override_rules = {}
        values, source_dict = self._invoke(self._fill_form, form, submit=submit, required_only=required_only,
                                           override_rules=override_rules, webelement=form, test_password=test_password)
        return values, source_dict

    def _fill_form(self, form: dict, submit: bool = False, required_only: bool = False,
                   override_rules=None, test_password: str = "") -> [list, dict]:
        if override_rules is None:
            override_rules = {}

        f = Form.Form(self, form)
        values, source_dict = f.fill(submit=submit, required_only=required_only, override_rules=override_rules, test_password=test_password)
        return values, source_dict

    def fill_and_submit(self, form: dict, required_only: bool = False, override_rules: bool = None, test_password: str = "") -> [list, dict]:
        if override_rules is None:
            override_rules = {}
        return self.fill_form(form, submit=True, required_only=required_only, override_rules=override_rules, test_password=test_password)

    def get_form_labels(self, form: dict) -> list:
        f = self._invoke(Form.Form, self, form, webelement=form)  # `_invoke` it in case the form has become stale
        return f.get_labels() if form else []

    """ Element specific auxiliary methods
    """

    # Get an element's DOMPath
    def get_dompath(self, element) -> str:
        # print(self.execute_script("return gPt(arguments[0]).toLowerCase();", element))
        try:
            dompath = self._invoke(self.execute_script, "return gPt(arguments[0]).toLowerCase();", element,
                                   webelement=element)
        except Exception as e:
            raise  # Debug debug Debug
        # Construct element's full dompath and substitute any namespace part of it (contains ':') with a wildcard (*)
        return "//html%s" % "/".join(
            [part if ":" not in part else "*" for part in dompath.split("/")]) if dompath else dompath

        # Get element's outerHTML

    def get_element_src(self, element, full: bool = False) -> str:
        src = self._invoke(self.execute_script, "return arguments[0].outerHTML;", element, webelement=element)
        if not full:
            return "%s>" % src.split(">")[0] if src else src
        return src

    # Get element's attributes as a dict
    def get_attributes(self, element) -> dict:
        return self._invoke(self.execute_script, "return get_attributes(arguments[0]);", element,
                            webelement=element)

    # Get element's attribute
    def get_attribute(self, element, attribute: str) -> str:
        # return self._invoke(element.get_attribute, attribute, webelement = element)
        return self._invoke(self._get_attribute, element, attribute, webelement=element)

    @staticmethod
    def _get_attribute(element, attribute: str) -> str:
        return element.get_attribute(attribute)

    def get_property(self, element, e_property: str) -> str:
        return self._invoke(self._get_property, element, e_property, webelement=element)

    @staticmethod
    def _get_property(element, e_property: str) -> str:
        return element.get_property(e_property)

    # Get an element's tag in lowercase
    def get_tag(self, element) -> str:
        return self._invoke(self.execute_script, "return arguments[0].tagName.toLowerCase()", element,
                            webelement=element)

    # Check whether an element's tag matches the given tag
    def is_tag(self, element, tag: str) -> bool:
        return self.get_tag(element) == tag.lower()

    # Get an element's type
    def get_type(self, element) -> str:
        try:
            etype = self._invoke(self.execute_script, "return arguments[0].type", element, webelement=element)
            etype = etype.lower() if etype else ""
        except Exception as e:
            logger.error("Something bad happened, ", e)
            etype = self.get_attribute(element, "type")
        return etype.lower() if etype else ""

    # Check whether an element's type matches the given type
    def is_type(self, element, c_type: str) -> bool:
        return self.get_type(element) == c_type.lower()

    # Check whether the given element is `required`
    def is_required(self, element) -> bool:
        return self._invoke(self.execute_script, "return arguments[0].required", element, webelement=element)

    # Check whether the given element is a form input
    def is_form_input(self, element) -> bool:
        tag = self.get_tag(element)
        etype = self.get_type(element)
        if (tag != "input" and tag != "textarea" and tag != "select") or etype == "submit" or etype == "hidden":
            return False
        return True

    # Get and set the given element's value
    def get_value(self, element) -> str:
        return self._invoke(self.execute_script, "return arguments[0].value", element, webelement=element)

    def set_value(self, element, value: str) -> str:
        self._invoke(self.execute_script, "arguments[0].value = '%s';" % value, element, webelement=element)
        return value

    # Mark the given element as `checked`
    def check_element(self, element) -> None:
        self._invoke(self.execute_script, "arguments[0].checked = true;", element, webelement=element)

    # Check if the given element is `checked`
    def is_checked(self, element) -> bool:
        return self._invoke(self.execute_script, "return arguments[0].checked", element, webelement=element)

    # Select the given index, when given a `Select` webelement
    def set_selected_index(self, element, idx: str) -> None:
        self._invoke(self.execute_script, "arguments[0].selectedIndex = '%s';" % idx, element, webelement=element)

    def get_parent(self, element) -> str:
        return self._invoke(self.execute_script, "arguments[0].parentElement", element, webelement=element)

    def get_children(self, element) -> list:
        return self._invoke(self.execute_script, "arguments[0].children", element, webelement=element)

    def get_descendants(self, element) -> list:
        ret = self.find_elements_by_xpath(".//*", webelement=element)
        if ret:
            # return [element for element in ret if element and type(element) != list]
            return [element for element in ret if element]
        return ret

    # Scroll element into view
    def scroll_to(self, element) -> None:
        ret = self._invoke(self.execute_script, "arguments[0].scrollIntoView(true);", element, webelement=element)

    # Scroll to top of the page
    def scroll_to_top(self) -> None:
        ret = self._invoke(self.execute_script, "window.scrollTo(0, 0);")

    # Get current page's URL scheme
    def get_scheme(self) -> str:
        return self._invoke(self.execute_script, "return window.location.protocol")

    ''' Quite coarse grained method to determine if an element is or contains a (re)CAPTCHA. Used mainly for forms.
    '''

    def has_captcha(self, element) -> bool:
        src = self.get_element_src(element, full=True)
        if re.search(Regexes.CAPTCHA, src, re.IGNORECASE):
            return True
        return False

    """ Check whether the current page contains a given regex in src
    """

    def contains_in_src(self, pattern: str, exact: bool = False) -> bool:
        return self._contains_in(self.rendered_source(), pattern, exact=exact)

    """ Check whether the current page contains a given regex in its DISPLAYED text
    """

    def contains_in_text(self, pattern: str, exact: bool = False) -> bool:
        body = self.find_element_by_tag_name("body")
        if not body:
            return False
        return self._contains_in(body.text, pattern, exact=exact)

    """ Check whether the current page contains any element (displayed or not) with the given pattern in its source
    """

    def contains_element_with(self, pattern: str, tags: list = None, displayed: bool = True,
                              exact: bool = False) -> bool:
        elements = []
        if tags:
            for tag in tags:
                elements += self.find_elements_by_tag_name(tag)
        else:
            elements = self.find_elements_by_xpath("//body/*")  # Not really useful

        for el in elements:
            if displayed and not self.is_displayed(el):
                continue
            if self._contains_in(self.get_element_src(el), pattern, exact=exact):
                return True
        return False

    @staticmethod
    def _contains_in(search_string: str, pattern: str, exact: bool = False) -> bool:
        if re.search(pattern, search_string, re.IGNORECASE if not exact else 0):
            return True
        return False

    def get_elements_by_class(self, class_name: str, tag: str = None) -> list:
        return self._invoke(self.execute_script, "return getElementsByXPath(arguments[0]);",
                            "//%s[contains(@class, %s)]" % (tag if tag else "*", class_name))

    def get_third_party_scripts(self) -> set:
        return self._invoke(self._get_third_party_scripts)

    def _get_third_party_scripts(self) -> set:
        first_party_domain = URLUtils.get_main_domain(self.current_url())
        third_party_scripts = set()

        for s in self.find_elements_by_tag_name("script"):
            src = self.get_attribute(s, "src")
            if not src:
                continue
            src_domain = URLUtils.get_main_domain(src)
            if src_domain != first_party_domain:
                third_party_scripts.add(s)

        return third_party_scripts

    """ Configurable built-in crawler. Call `craw_init` with the desired arguments, use a `while crawl_next()` to execute the crawl and `crawl_exit` to restore the crawl state
    """

    def crawl_init(self, starting_url: str, bfs: bool = True, dfs: bool = False, depth: int = 1, follow: list = None,
                   nofollow: list = None, top=None, break_func=None,
                   allow_fragments=True) -> None:
        if not bfs and not dfs:
            raise APDriverException("No crawl mode was selected", caller_prefix=self._caller_prefix)
        self._crawl_config = {
            "bfs": bfs,
            "dfs": dfs,
            "depth": depth,
            "cur_depth": 0,
            "follow": follow,
            "nofollow": nofollow,
            "top": top,
            "base_domain": URLUtils.get_main_domain(starting_url),
            "break_func": break_func,
            "allow_fragments": allow_fragments,
            "focused": follow or nofollow,
            "state": {0: [starting_url]},  # key is depth, value is list of lists
            "visited": set()
        }

    def _get_current_crawl_depth(self) -> int:
        cur_depth = -1
        if self._crawl_config["bfs"]:
            cur_depth = min(self._crawl_config["state"].keys())  # In BFS, we always get the minimum available depth
        elif self._crawl_config["dfs"]:
            cur_depth = max(self._crawl_config["state"].keys())  # In DFS, we always get the maximum available depth
        return cur_depth

    def _get_next_crawl_url(self) -> [str, int]:
        cur_depth = self._get_current_crawl_depth()
        # Remove next url from "tree"
        next_url = self._crawl_config["state"][cur_depth].pop(0)
        if not self._crawl_config["state"][cur_depth]:  # If the current depth is empty, pop it
            self._crawl_config["state"].pop(cur_depth)

        return next_url, cur_depth

    """ All crawling logic is in here. See inline comments.
        When the next URL of the crawl is fetched, it is also returned. 
        When the crawl is done, returns False.
    """

    def crawl_next(self) -> Union[str, bool]:
        # If all depths have been explored, return False so the caller knows the crawl finished
        if not self._crawl_config["state"]:
            return False

        next_url, cur_depth = self._get_next_crawl_url()

        while (next_url in self._crawl_config["visited"]
               or (self._crawl_config["focused"]
                   and cur_depth != 0
                   and (self._crawl_config["follow"]
                        and not any([True if re.search(regex, next_url, re.IGNORECASE) else False for regex in
                                     self._crawl_config["follow"]]) or
                        self._crawl_config["nofollow"]
                        and any([True if re.search(regex, next_url, re.IGNORECASE) else False for regex in
                                 self._crawl_config["nofollow"]])))):
            if not self._crawl_config["state"]:
                return False
            next_url, cur_depth = self._get_next_crawl_url()  # We initially did this recursively, but pages with A LOT of links caused a max recursion exception

        # In DFS mode ONLY, for unvisited URLs we need to traverse all stored URLs in higher layers so the crawl will be complete
        if self._crawl_config["dfs"]:
            for depth in sorted(self._crawl_config["state"].keys()):  # Traverse keys (seen depths/layers) in asc order
                if depth >= cur_depth:
                    break
                if next_url in self._crawl_config["state"][depth]:
                    return self.crawl_next()

        if not self.get(next_url):  # A redirection to a different domain occurred, we don't want that
            return self.crawl_next()
        self._crawl_config["visited"].add(next_url)

        # Check if the final URL has been visited or store the final URL as well
        redirection_url = self.current_url()
        if redirection_url != next_url and redirection_url in self._crawl_config["visited"]:
            return self.crawl_next()
        if redirection_url != next_url:
            self._crawl_config["visited"].add(redirection_url)

        next_depth = cur_depth + 1
        # If the next layer exceeds the crawl depth, don't store the next links
        if next_depth > self._crawl_config["depth"]:
            return next_url
        links = self.get_internal_links()
        if not links:  # No links? No dice
            return next_url

        if next_depth not in self._crawl_config["state"]:
            self._crawl_config["state"][next_depth] = []
        # Store the links in the order they were collected and the top X, if `top` was specified
        if not self._crawl_config["top"]:
            self._crawl_config["state"][next_depth] += links
        else:
            self._crawl_config["state"][next_depth] += links[:self._crawl_config["top"]]
        return next_url

    def crawl_exit(self):
        self._crawl_config = {}

    def get_source_list(self, body_element: WebElement) -> List[str]:
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
            self.switch_to.frame(iframe)
            iframe_body: WebElement = self.find_element(By.TAG_NAME, "body")
            if iframe_body:
                ret_list.append(iframe_body.get_attribute("innerHTML"))
            # ret_list.append(self.page_source())
            self.switch_to.default_content()
        return ret_list

    @staticmethod
    def get_source_str(body_element: WebElement) -> str:
        """ get the source of the body element

        Args:
            body_element: WebElement, goal

        Returns:
            Return a string, containing only the body innerHTML
        """
        return body_element.get_attribute("innerHTML")
