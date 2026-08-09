"""
rate_controller.py — 人类行为节奏模拟与频率控制

模仿真实用户在浏览器中的操作节奏，降低被反爬系统识别为机器人的风险。

设计参考:
  - 原项目 utils/util_basic.py random_sleep()
  - 原项目 utils/util_test_password.py 中各延迟常量
  - LoginFormExploration helpers/formInteraction.js 按键间隔

新增原项目没有的能力:
  - 指数退避 (exponential backoff)
  - 连续提交后的强制冷却期
  - User-Agent 随机轮换
"""

import random
import time
from typing import Optional


class RateController:
    """节奏控制器 —— 每个表单/站点独立实例化"""

    # ================================================================
    # 延迟常量（秒）
    # ================================================================
    DELAY_BETWEEN_FIELDS   = (0.3, 0.8)   # 字段间切换
    DELAY_BETWEEN_KEYSTROKES = (0.05, 0.15) # 逐字符输入
    DELAY_BEFORE_SUBMIT    = (1.0, 3.0)   # 填完所有字段后，提交前
    DELAY_BETWEEN_TESTS    = (3.0, 8.0)   # 两次完整密码测试之间
    DELAY_COOLDOWN_AFTER_N = (15.0, 30.0) # 连续 N 次提交后的强制冷却
    COOLDOWN_THRESHOLD     = 5             # 触发冷却的连续提交次数
    MAX_BACKOFF_SECONDS    = 60.0          # 指数退避上限

    # User-Agent 轮换池
    _USER_AGENTS = [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ]

    def __init__(self):
        self._consecutive_submissions: int = 0
        self._failure_count: int = 0
        self._current_ua_index: int = 0

    # ================================================================
    # 操作级延迟
    # ================================================================

    def delay_between_fields(self) -> None:
        """字段间切换的随机延迟"""
        time.sleep(random.uniform(*self.DELAY_BETWEEN_FIELDS))

    def delay_between_keystrokes(self) -> None:
        """逐字符输入时的随机延迟"""
        time.sleep(random.uniform(*self.DELAY_BETWEEN_KEYSTROKES))

    def delay_before_submit(self) -> None:
        """填完所有字段后、提交前的随机延迟（模拟人类审阅）"""
        time.sleep(random.uniform(*self.DELAY_BEFORE_SUBMIT))

    def delay_between_tests(self) -> None:
        """两次完整测试之间的随机延迟"""
        time.sleep(random.uniform(*self.DELAY_BETWEEN_TESTS))

    # ================================================================
    # 频率控制
    # ================================================================

    def record_submission(self) -> None:
        """记录一次提交，累计到阈值时触发强制冷却"""
        self._consecutive_submissions += 1
        if self._consecutive_submissions >= self.COOLDOWN_THRESHOLD:
            cooldown = random.uniform(*self.DELAY_COOLDOWN_AFTER_N)
            time.sleep(cooldown)
            self._consecutive_submissions = 0

    def record_failure(self) -> float:
        """记录一次失败，返回指数退避后的等待时间"""
        self._failure_count += 1
        delay = self._backoff_delay()
        time.sleep(delay)
        return delay

    def record_success(self) -> None:
        """成功后重置失败计数"""
        self._failure_count = 0
        self._consecutive_submissions = 0

    def _backoff_delay(self) -> float:
        """指数退避: min(2^n + random(0,2), MAX_BACKOFF) 秒"""
        base = 2 ** min(self._failure_count, 5)
        return min(base + random.uniform(0, 2), self.MAX_BACKOFF_SECONDS)

    # ================================================================
    # 身份轮换
    # ================================================================

    def rotate_user_agent(self) -> str:
        """轮换 User-Agent 字符串"""
        ua = self._USER_AGENTS[self._current_ua_index]
        self._current_ua_index = (self._current_ua_index + 1) % len(self._USER_AGENTS)
        return ua

    @staticmethod
    def get_random_user_agent() -> str:
        """随机获取一个 User-Agent（不改变内部状态）"""
        return random.choice(RateController._USER_AGENTS)

    # ================================================================
    # 便捷方法（兼容原项目 random_sleep 的调用模式）
    # ================================================================

    @staticmethod
    def sleep(seconds: float) -> None:
        """固定延迟"""
        time.sleep(seconds)

    @staticmethod
    def sleep_range(lo: float, hi: float) -> None:
        """区间随机延迟"""
        time.sleep(random.uniform(lo, hi))
