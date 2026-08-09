"""
data_generator.py — 智能虚拟数据生成

为注册表单中各类字段生成合理合规的虚拟数据。

策略: 内置中文姓名库（优先） + faker zh_CN locale（补充）

可生成类型:
  - 中文姓名 (2-3字，100姓氏 + 80+名字用字)
  - 邮箱 (复用 util_str_generator.gen_random_email)
  - 中国大陆手机号 (1[3-9]xxxxxxxxx)
  - 用户名 / 公司 / 地址 / 邮编 / 生日 / 性别 / URL 等 (faker)
"""

import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Callable

import faker as _faker_lib

from utils import util_str_generator as uusg


# ================================================================
# 内置中文姓名库
# ================================================================

# 常见单姓（100个，按使用频率排序）
_SURNAMES: list = [
    "李","王","张","刘","陈","杨","赵","黄","周","吴",
    "徐","孙","胡","朱","高","林","何","郭","马","罗",
    "梁","宋","郑","谢","韩","唐","冯","于","董","萧",
    "程","曹","袁","邓","许","傅","沈","曾","彭","吕",
    "苏","卢","蒋","蔡","贾","丁","魏","薛","叶","阎",
    "余","潘","杜","戴","夏","钟","汪","田","任","姜",
    "范","方","石","姚","谭","廖","邹","熊","金","陆",
    "郝","孔","白","崔","康","毛","邱","秦","江","史",
    "顾","侯","邵","孟","龙","万","段","雷","钱","汤",
    "尹","黎","易","常","武","乔","贺","赖","龚","文",
]

# 男性名字用字
_GIVEN_MALE: list = [
    "伟","强","磊","洋","勇","军","杰","涛","明","超",
    "峰","辉","鹏","浩","亮","刚","健","飞","帅","旭",
    "波","斌","志","义","兴","良","海","仁","宁","健",
    "恒","之","为","立","林","成","龙","威","正","平",
    "康","博","毅","彬","福","富","顺","信","光","天",
    "达","安","宏","和","彪","进","若","建","国","克",
]

# 女性名字用字
_GIVEN_FEMALE: list = [
    "芳","娜","敏","静","丽","婷","雪","娟","艳","玲",
    "霞","红","梅","燕","萍","莉","琴","云","晶","秀",
    "兰","凤","洁","慧","英","桂","芬","淑","美","荣",
    "珍","花","春","佳","瑞","蓉","琼","勤","香","惠",
    "怡","君","巧","艺","悦","蕾","华","秋","岚","月",
    "芝","青","银","如","瑜","嘉","荷","思","婉","柔",
]

# 通用名字用字（男女皆可）
_GIVEN_COMMON: list = [
    "文","华","宁","平","晓","欣","宇","然","佳","晨",
    "阳","睿","琪","琳","思","雨","悦","嘉","辰","玉",
    "涵","子","一","铭","之","亦","帆","远","言","安",
    "乐","颜","悦","瑶","念","菲","彤","薇","云","秋",
]


# ================================================================
# 字段类型枚举（与 field_classifier 保持一致）
# ================================================================

FIELD_EMAIL            = "EMAIL"
FIELD_PASSWORD         = "PASSWORD"
FIELD_CONFIRM_PASSWORD = "CONFIRM_PASSWORD"
FIELD_USERNAME         = "USERNAME"
FIELD_FULL_NAME        = "FULL_NAME"
FIELD_FIRST_NAME       = "FIRST_NAME"
FIELD_LAST_NAME        = "LAST_NAME"
FIELD_PHONE            = "PHONE"
FIELD_COMPANY          = "COMPANY"
FIELD_URL              = "URL"
FIELD_ADDRESS          = "ADDRESS"
FIELD_CITY             = "CITY"
FIELD_COUNTRY          = "COUNTRY"
FIELD_ZIPCODE          = "ZIPCODE"
FIELD_STREET           = "STREET"
FIELD_BIRTHDATE        = "BIRTHDATE"
FIELD_AGE              = "AGE"
FIELD_GENDER           = "GENDER"
FIELD_BIO              = "BIO"
FIELD_UNKNOWN          = "UNKNOWN"


class DataGenerator:
    """虚拟数据生成器 —— 每个站点独立实例化，保持身份一致性"""

    def __init__(self, locale: str = "zh_CN"):
        """
        Args:
            locale: faker locale，默认 zh_CN
        """
        self.locale = locale
        self._faker = _faker_lib.Faker(locale)
        self._eng_faker = _faker_lib.Faker("en_US")  # 英文 fallback

        # 为该站点生成一个固定身份（同一站点内多次测试复用身份信息）
        self._identity = self._generate_identity()

        # 字段类型 → 生成器映射
        self._generators: Dict[str, Callable[[], str]] = {
            FIELD_EMAIL:            self._gen_email,
            FIELD_PASSWORD:         self._gen_placeholder,  # 密码由外部传入
            FIELD_CONFIRM_PASSWORD: self._gen_placeholder,
            FIELD_USERNAME:         self._gen_username,
            FIELD_FULL_NAME:        self._gen_full_name,
            FIELD_FIRST_NAME:       self._gen_first_name,
            FIELD_LAST_NAME:        self._gen_last_name,
            FIELD_PHONE:            self._gen_phone,
            FIELD_COMPANY:          self._gen_company,
            FIELD_URL:              self._gen_url,
            FIELD_ADDRESS:          self._gen_address,
            FIELD_CITY:             self._gen_city,
            FIELD_COUNTRY:          self._gen_country,
            FIELD_ZIPCODE:          self._gen_zipcode,
            FIELD_STREET:           self._gen_street,
            FIELD_BIRTHDATE:        self._gen_birthdate,
            FIELD_AGE:              self._gen_age,
            FIELD_GENDER:           self._gen_gender,
            FIELD_BIO:              self._gen_bio,
            FIELD_UNKNOWN:          self._gen_unknown,
        }

    # ================================================================
    # 公开 API
    # ================================================================

    def generate(self, field_type: str, test_password: Optional[str] = None) -> str:
        """为指定字段类型生成虚拟数据

        Args:
            field_type: 字段类型（FIELD_* 常量）
            test_password: 仅 PASSWORD/CONFIRM_PASSWORD 使用

        Returns:
            生成的字符串值
        """
        if field_type == FIELD_PASSWORD:
            return test_password or self._gen_password()
        if field_type == FIELD_CONFIRM_PASSWORD:
            return test_password or self._gen_password()

        gen = self._generators.get(field_type)
        if gen:
            return gen()
        return self._gen_unknown()

    def get_fixed_email(self) -> str:
        """返回该站点固定身份的邮箱"""
        return self._identity["email"]

    def get_fixed_username(self) -> str:
        """返回该站点固定身份的用户名"""
        return self._identity["username"]

    def get_fixed_full_name(self) -> str:
        """返回该站点固定身份的全名"""
        return self._identity["full_name"]

    # ================================================================
    # 固定身份生成（每站点一次）
    # ================================================================

    def _generate_identity(self) -> dict:
        """生成一个随机但内部一致的身份"""
        surname = random.choice(_SURNAMES)
        # 70% 概率二字名
        if random.random() < 0.7:
            pool = _GIVEN_COMMON + _GIVEN_MALE + _GIVEN_FEMALE
            given = random.choice(pool) + random.choice(pool)
        else:
            pool = _GIVEN_COMMON + _GIVEN_MALE + _GIVEN_FEMALE
            given = random.choice(pool)
        full_name = surname + given

        pinyin_first = self._eng_faker.first_name()
        pinyin_last = self._eng_faker.last_name()
        username = f"{pinyin_first}_{pinyin_last}{random.randint(100, 999)}".lower()

        domains = ("gmail.com", "foxmail.com", "yahoo.com", "outlook.com")
        email = f"{pinyin_first}.{pinyin_last}{random.randint(10, 99)}@{random.choice(domains)}".lower()

        return {
            "full_name": full_name,
            "username": username,
            "email": email,
            "phone": f"1{random.choice('3456789')}{''.join(random.choices(string.digits, k=9))}",
        }

    # ================================================================
    # 各字段类型生成器
    # ================================================================

    def _gen_email(self) -> str:
        if random.random() < 0.5:
            return self._identity["email"]
        return uusg.gen_random_email()

    def _gen_username(self) -> str:
        if random.random() < 0.6:
            return self._identity["username"]
        return self._faker.user_name()

    def _gen_full_name(self) -> str:
        """生成中文姓名（2-3字）"""
        surname = random.choice(_SURNAMES)
        if random.random() < 0.7:
            pool = _GIVEN_COMMON + _GIVEN_MALE + _GIVEN_FEMALE
            given = random.choice(pool) + random.choice(pool)
        else:
            pool = _GIVEN_COMMON + _GIVEN_MALE + _GIVEN_FEMALE
            given = random.choice(pool)
        return surname + given

    def _gen_first_name(self) -> str:
        pool = _GIVEN_COMMON + _GIVEN_MALE + _GIVEN_FEMALE
        return random.choice(pool) + random.choice(pool)

    def _gen_last_name(self) -> str:
        return random.choice(_SURNAMES)

    def _gen_phone(self) -> str:
        """中国大陆手机号: 1[3-9]xxxxxxxxx"""
        if random.random() < 0.5:
            return self._identity["phone"]
        return f"1{random.choice('3456789')}{''.join(random.choices(string.digits, k=9))}"

    def _gen_company(self) -> str:
        try:
            return self._faker.company()
        except Exception:
            return self._eng_faker.company()

    def _gen_url(self) -> str:
        return self._eng_faker.url()

    def _gen_address(self) -> str:
        try:
            return self._faker.address().replace("\n", " ")
        except Exception:
            return self._eng_faker.street_address()

    def _gen_city(self) -> str:
        try:
            return self._faker.city()
        except Exception:
            return self._eng_faker.city()

    def _gen_country(self) -> str:
        try:
            return self._faker.country()
        except Exception:
            return "China"

    def _gen_zipcode(self) -> str:
        return self._faker.postcode() if hasattr(self._faker, "postcode") else "100000"

    def _gen_street(self) -> str:
        try:
            return self._faker.street_name()
        except Exception:
            return self._eng_faker.street_name()

    def _gen_birthdate(self) -> str:
        """YYYY-MM-DD 格式"""
        try:
            dob = self._faker.date_of_birth(minimum_age=18, maximum_age=55)
            return dob.strftime("%Y-%m-%d") if hasattr(dob, "strftime") else str(dob)[:10]
        except Exception:
            dob = datetime.now() - timedelta(days=random.randint(18 * 365, 55 * 365))
            return dob.strftime("%Y-%m-%d")

    def _gen_age(self) -> str:
        return str(random.randint(18, 60))

    def _gen_gender(self) -> str:
        return random.choice(["男", "女", "male", "female"])

    def _gen_bio(self) -> str:
        try:
            return self._faker.text(max_nb_chars=50)
        except Exception:
            return self._eng_faker.text(max_nb_chars=50)

    def _gen_password(self) -> str:
        """默认密码（仅在外部未传入 test_password 时使用）"""
        return uusg.gen_random_str_no_symbol(8) + "1@aA"

    def _gen_placeholder(self) -> str:
        """占位——密码类型字段不应调用此方法"""
        return ""

    def _gen_unknown(self) -> str:
        """未知类型字段的默认填充"""
        try:
            return self._faker.pystr(min_chars=3, max_chars=10)
        except Exception:
            return self._eng_faker.pystr(min_chars=3, max_chars=10)
