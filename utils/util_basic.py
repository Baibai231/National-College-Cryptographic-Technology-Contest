import os
import random
import threading
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


# ---- 日志按站点路由：解决并发下 loguru 全局 sink 串台的问题 ----
# loguru 的 logger 是进程级单例。并发测多站点时，每个站点各 add 一个文件 sink，
# 但所有 sink 都会收到进程里所有线程的日志，导致 A 站点的日志写进 B 站点的文件。
# 用 thread-local 记录"当前线程正在测哪个站点"，给每个 sink 加 filter：
# 只有"发日志的线程所属站点 == 该 sink 的站点"时才落盘，其余线程的日志被过滤掉。
_site_local = threading.local()
_added_sites = set()


def set_log_site(site_name):
    """把当前线程正在测试的站点名写入 thread-local（供 sink filter 路由）。"""
    _site_local.name = site_name


def _site_filter(site_name):
    def _filter(record):
        return getattr(_site_local, "name", None) == site_name
    return _filter


def get_logger(site_name):
    log_dir = get_absolute_dir_path() + "/../logs/"
    # 并发安全：多 worker 同时创建同一目录可能 FileExistsError（实测
    # runoob/vercel/wix 并发跑时日志目录竞争），exist_ok=True 幂等。
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass

    site_dir = log_dir + "/" + site_name + "/"
    try:
        os.makedirs(site_dir, exist_ok=True)
    except Exception:
        pass

    # 关键：先把当前线程绑定到该站点，sink 的 filter 据此路由日志。
    set_log_site(site_name)

    # 幂等：同一站点只加一次文件 sink，避免重复调用 get_logger 写两份日志。
    if site_name in _added_sites:
        return logger
    _added_sites.add(site_name)

    # Get the current date and time
    current_time = datetime.now()

    # Format the output
    formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")

    logger.add(os.path.join(site_dir, f"{site_name}-{formatted_time}-DEBUG.log"),
               rotation="00:00", level="DEBUG", filter=_site_filter(site_name))
    logger.add(os.path.join(site_dir, f"{site_name}-{formatted_time}-INFO.log"),
               rotation="00:00", level="INFO", filter=_site_filter(site_name))
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
