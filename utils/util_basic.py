import os
import random
import time
from loguru import logger
from datetime import datetime


def random_sleep(times=None):
    """
    sleep a random time
    :param times: an interval or a specific integer
    """
    if times is None:
        times = [3, 5]
    if type(times).__name__ == 'list' and len(times) >= 2:
        # uniform 同时支持整数和浮点区间（randint 遇浮点会抛异常）
        time.sleep(random.uniform(times[0], times[1]))
    elif type(times).__name__ == 'int' or type(times).__name__ == 'float':
        time.sleep(times)
    else:
        time.sleep(1)


def get_user_dir_path(user='~'):
    """
    get the user's directory path
    :param user: the name of user directory
    :return: return the user directory path
    """
    return os.path.expanduser(user)


def get_absolute_dir_path():
    """
    get the absolute dir path
    :return: return the absolute path
    """
    return os.path.dirname(os.path.abspath(__file__))


def get_each_character_num(input_string):
    ret_dict = {
        "digit": 0,
        "letter": 0,
        "upper": 0,
        "lower": 0,
        "symbol": 0,
        "type_num": 0
    }
    digit_cnt, upper_cnt, lower_cnt, symbol_cnt = 0, 0, 0, 0
    for i in input_string:
        if i.isdigit():
            ret_dict["digit"] += 1
            digit_cnt = 1
        elif i.isalpha():
            ret_dict["letter"] += 1
            if i.isupper():
                ret_dict["upper"] += 1
                upper_cnt = 1
            elif i.islower():
                ret_dict["lower"] += 1
                lower_cnt = 1
        else:
            ret_dict["symbol"] += 1
            symbol_cnt = 1
    type_num = digit_cnt + upper_cnt + lower_cnt + symbol_cnt
    ret_dict["type_num"] = type_num
    return ret_dict


def get_logger(site_name):
    log_dir = get_absolute_dir_path() + "/../logs/"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    site_dir = log_dir + "/" + site_name + "/"
    if not os.path.exists(site_dir):
        os.makedirs(site_dir)

    # Get the current date and time
    current_time = datetime.now()

    # Format the output
    formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")

    logger.add(os.path.join(site_dir, f"{site_name}-{formatted_time}-DEBUG.log"), rotation="00:00", level="DEBUG")
    logger.add(os.path.join(site_dir, f"{site_name}-{formatted_time}-INFO.log"), rotation="00:00", level="INFO")
    logger.info(f"Begin logging for testing {site_name}")
    return logger


def get_password_structure(password):
    ret_dict = {
        "digit": 0,
        "symbol": 0,
        "letter": 0,
        "lower": 0,
        "upper": 0,
        "cr3": 0,
        "cr4": 0
    }
    cr3 = set()
    cr4 = set()
    for i in password:
        if i.isdigit():
            ret_dict["digit"] += 1
            cr3.add("digit")
            cr4.add("digit")
        elif i.islower():
            ret_dict["lower"] += 1
            cr3.add("letter")
            cr4.add("lower")
        elif i.isupper():
            ret_dict["upper"] += 1
            cr3.add("letter")
            cr4.add("upper")
        else:
            ret_dict["symbol"] += 1
            cr3.add("symbol")
            cr4.add("symbol")
        ret_dict["cr3"] = len(cr3)
        ret_dict["cr4"] = len(cr4)
    return ret_dict
