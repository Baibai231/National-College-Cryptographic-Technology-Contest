import faker
import random
import string


def gen_random_str_no_symbol(target_length=8):
    """
    generate a random string with specific length, excluding symbols
    :param target_length: the targeted length of the generated string
    :return the generated string
    """
    # rand_str = ''.join(random.sample(string.ascii_letters + string.digits, target_length))
    rand_str = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(target_length))
    return rand_str


def gen_random_str_with_symbol(target_length=8):
    """
    generate a random string with specific length, including symbols
    :param target_length: the targeted length of the generated string
    :return: return the generated string
    """
    rand_str = ''.join(random.choice(string.ascii_letters + string.digits + string.punctuation) for _ in range(target_length))
    return rand_str


def gen_random_digit(target_length=3):
    """
    return a random-generated digit list
    :param target_length: the targeted length
    :return: return a digit string with specific length
    """
    # rand_digit_str = ''.join(random.sample(string.digits, target_length))
    # rand_digit_str = ''.join(random.sample(string.ascii_letters + string.digits + string.punctuation, target_length))
    rand_str = ''.join(random.choice(string.digits) for _ in range(target_length))
    return rand_str


def gen_random_letter_character(target_length=1):
    """
    generate a string including only letters, and the target length is 1 by default
    :param target_length: the targeted length
    :return: the generated string
    """
    # rand_letter_character = ''.join(random.sample(string.ascii_letters, target_length))
    rand_str = ''.join(random.choice(string.ascii_letters) for _ in range(target_length))
    return rand_str


def gen_random_upper_character(target_length=1):
    """
    generate a string including only upper letters, and the target length is 1 by default
    :param target_length: the targeted length
    :return: the generated string
    """
    rand_str = ''.join(random.choice(string.ascii_uppercase) for _ in range(target_length))
    # rand_letter_character = ''.join(random.sample(string.ascii_uppercase, target_length))
    return rand_str


def gen_random_lower_character(target_length=1):
    """
    generate a string including only lower letters, and the target length is 1 by default
    :param target_length: the targeted length
    :return: the generated string
    """
    # rand_letter_character = ''.join(random.sample(string.ascii_lowercase, target_length))
    rand_str = ''.join(random.choice(string.ascii_lowercase) for _ in range(target_length))
    return rand_str


def gen_random_symbol_character(target_length=1):
    """
    generate a string including only letters, and the target length is 1 by default
    :param target_length: the targeted length
    :return: return the generated string
    """
    # rand_symbol_character = ''.join(random.sample(string.punctuation, target_length))
    rand_str = ''.join(random.choice(string.punctuation) for _ in range(target_length))
    return rand_str


def gen_random_email():
    """
    generate a random email
    :return: return the generated email
    """
    list_of_domains = (
        'com',
        # 'net',
        # 'org',
        # 'gov'
    )
    list_of_company = (
        'gmail',
        'foxmail',
        'yahoo',
        # 'weibo',
        # 'outlook',
        # 'aol',
        # 'icloud',
        # 'protonmail'
    )
    fake = faker.Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    company = fake.random_element(elements=list_of_company)
    dns_org = fake.random_element(elements=list_of_domains)
    email = f"{first_name}_{last_name}@{company}.{dns_org}".lower()
    return email


def gen_random_full_name():
    """
    generate a full name
    :return: return the full name
    """
    fake = faker.Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    full_name = f"{first_name} {last_name}".lower()
    return full_name


def gen_random_username():
    fake = faker.Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    random_user_name = f"{first_name}_{last_name}".lower() + str(gen_random_digit(3))
    return random_user_name


def transfer_symbol_into_digit(admissible_password):
    ret_str = ""
    for i in admissible_password:
        if not i.isalnum():
            ret_str += gen_random_digit(1)
        else:
            ret_str += i
    return ret_str


def transfer_digit_into_symbol(admissible_password):
    ret_str = ""
    fake = faker.Faker()
    for i in admissible_password:
        if i.isdigit():
            ret_str += fake.random_element(elements=('-', '@'))
        else:
            ret_str += i
    return ret_str


def transfer_lower_into_upper(admissible_password):
    return admissible_password.upper()


def transfer_upper_into_lower(admissible_password):
    return admissible_password.lower()


def transfer_upper_into_symbol(admissible_password):
    """把大写字母替换为安全符号 '!'，保持其余字符不变。

    用于「缺失 upper」探测：把 3 类密码 lower+upper+digit 转成
    lower+digit+symbol（仍 3 类，仅去掉大写），避免 .lower() 把类别
    塌缩成 2 类（lower+digit）被 3-of-4 站点误拒，进而误判为 4-of-4。
    '!' 经 permissive 测试确认合法且不破坏 163 等站点的内联校验提示。
    """
    ret_str = ""
    for i in admissible_password:
        if i.isupper():
            ret_str += '!'
        else:
            ret_str += i
    return ret_str


def transfer_lower_into_symbol(admissible_password):
    """把小写字母替换为安全符号 '!'，保持其余字符不变（对称于 transfer_upper_into_symbol）。"""
    ret_str = ""
    for i in admissible_password:
        if i.islower():
            ret_str += '!'
        else:
            ret_str += i
    return ret_str


def transfer_letter_to_digit(admissible_password):
    ret_str = ""
    for i in admissible_password:
        if i.isalpha():
            ret_str += gen_random_digit(1)
        else:
            ret_str += i
    return ret_str


def transfer_sth_to_letter(admissible_password):
    ret_str = ""
    for i in admissible_password:
        if i.isalpha():
            ret_str += i
        else:
            ret_str += gen_random_letter_character(1)
    return ret_str
