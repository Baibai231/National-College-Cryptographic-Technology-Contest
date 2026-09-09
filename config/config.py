import pathlib
import logging
import random
from typing import Dict


class Config(object):
    """ Class for our global configurations
    """

    # Project root path, computed from this file's location so it works on any machine
    PROJECT_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]
    ROOT_PATH: str = str(PROJECT_ROOT) + "/"
    SCREENSHOT_PATH: str = str(PROJECT_ROOT / "screenshots") + "/"
    LOGIN_SCREENSHOT_PATH: str = SCREENSHOT_PATH + "LoginPolicy/"

    # Path for saving logs
    LOG: pathlib.Path = PROJECT_ROOT / "logs"
    # DEBUG|INFO|WARNING|ERROR
    LOG_LEVEL = logging.INFO

    # Max retries
    VERIFY_LOGIN_RETRIES = 3

    # timeout
    TYPO_TEST_INTERVAL: int = 3601
    REQUEST_TIMEOUT: int = 5
    SCREENSHOT_TIMEOUT: int = random.randint(1, 3)

    # --- 并发配置 ---
    MAX_CONCURRENT_CRAWLERS: int = 4       # 最大并发数（Selenium 较重，建议 ≤4）
    MAX_RETRIES_PER_URL: int = 2           # 每个 URL 最大重试次数
    CRAWLER_TIMEOUT_SECONDS: int = 300     # 单站点超时（秒）

    # --- 反爬 / CMP 配置 ---
    ENABLE_ANTI_BOT: bool = True           # 启用反自动化检测（notABot.js）
    ENABLE_CMP_DETECTION: bool = True      # 启用 CMP 弹窗检测（Consent-O-Matic）
    CMP_ACTION: str = "REJECT_ALL"         # 隐私保护默认值；分类器不会自动 ACCEPT_ALL
    CMP_MAX_WAIT_SECONDS: float = 6.0      # CMP 检测最长等待（秒）
    CMP_POLL_INTERVAL_SECONDS: float = 0.3 # CMP 轮询间隔（秒）

    # Usually the code of the response will be the response status (200, 404, etc.).
    # If an error occurs (e.g., response is NULL or browser is stuck), using the error codes below
    ERROR_CODES: Dict[str, int] = {
        "response_error": -1,
        "browser_error": -2
    }


