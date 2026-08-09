#!/usr/bin/python

class Regexes(object):
    """BEGIN SPECIFIC REGEXES
    """
    # e-mail
    EMAIL = r"e(\-|_|\s)*mail"
    # misc identifiers
    FULL_NAME = r"full(\-|_|\s)*name"
    FIRST_NAME = r"(f(irst|ore)?|m(iddle)?)(\-|_|\s)*name"
    LAST_NAME = r"(l(ast|st)?|s(u)?(r)?)(\-|_|\s)*name"
    USERNAME = r"(u(s(e)?r)?|nick|display|profile)(\-|_|\s)*name"
    NAME_PREFIX = r"prefix"
    # password
    PASSWORD = "password|passwd"
    # Phones
    PHONE_AREA = r"phone(\-|_|\s)*area|area(\-|_|\s)*code|phone(\-|_|\s)*(pfx|prefix|prfx)"
    PHONE = r"(mobile|cell|tel|phone)"
    # Dates
    MONTH = r"month"
    DAY = r"day"
    YEAR = r"year"
    BIRTHDATE = r"birthdate|birthday|date(\-|_|\s)*of(\-|_|\s)*birth"
    # gender
    AGE = r"(\-|_|\s)+age(\-|_|\s)+"
    GENDER = r"gender|sex"
    # profile pics
    FILE = r"^file|photo|picture"
    # Addresses
    ADDRESS = r"addr"
    ZIPCODE = r"(post(al)?|zip)(\-|_|\s)*(code|no|num)"
    CITY = r"city|town|location"
    COUNTRY = r"country"
    STATE = r"state|province"
    STREET = r"street"
    BUILDING_NO = r"(building|bldng|flat|apartment|apt|home|house)(\-|_|\s)*(num|no)"
    # SSN etc.
    SSN = r"(ssn|vat|social(\-|_|\s)*sec(urity)?(\-|_|\s)*(num|no)?)"
    # Credit cards
    CREDIT_CARD = r"card(\-|_|\s)*(no|num)|credit(\-|_|\s)*(no|num|card)"
    CREDIT_CARD_EXPIRE = r"expire|expiration"
    CREDIT_CARD_CVV = r"sec(urity)?(\-|_|\s)*(no|num|cvv|code)"
    # Company stuff
    COMPANY_NAME = r"company|organi(z|s)ation|institut(e|ion)"
    """END SPECIFIC REGEXES
    START GENERIC
    """
    NUMBER_COARSE = r"num|code"
    USERNAME_COARSE = r"us(e)?r|login"
    OTHER_FORM = r"link|search"
    SSO_SIGNUP_BUTTONS = r"((create|register|make)|(new))\s*(new\s*)?(user|account|profile)"

    VERIFY_ACCOUNT = r"((verify|activate)(\syour)?\s(account|e(-|\s)*mail|info))|((verification|activation) (e(-|\s)*mail|message|link|code|number))"
    VERIFIED_ACCOUNT = r"(user(-|\s))?(account|profile)\s+(was|is|has)?(been)?(verified|activated|attivo)|(verification|activation)\s+(was|is|has)(been)?\s+(completed|done|successful)?"
    VERIFY_VERBS = r"verify|activate"
    IDENTIFIERS = r"%s|%s|%s|%s|%s" % (FULL_NAME, FIRST_NAME, LAST_NAME, USERNAME, EMAIL)
    IDENTIFIERS_NO_EMAIL = r"%s|%s|%s|%s" % (FULL_NAME, FIRST_NAME, LAST_NAME, USERNAME)

    SUBMIT = r"submit"
    LOGIN = r"(log|sign)([^0-9a-zA-Z]|\s)*(in|on)|authenticat(e|ion)|/(my([^0-9a-zA-Z]|\s)*)?(user|account|profile|dashboard)"
    SIGNUP = r"sign([^0-9a-zA-Z]|\s)*up|regist(er|ration)?|(create|new)([^0-9a-zA-Z]|\s)*(new([^0-9a-zA-Z]|\s)*)?(acc(ount)?|us(e)?r|prof(ile)?)"
    SSO = r"[^0-9a-zA-Z]+sso[^0-9a-zA-Z]+|oauth|openid"
    AUTH = r"%s|%s|%s|auth|(new|existing)([^0-9a-zA-Z]|\s)*(us(e)?r|acc(ount)?)|account|connect|profile|dashboard" % (
        LOGIN, SIGNUP, SSO)
    LOGOUT = r"(log|sign)(-|_|\s)*(out|off)"

    PROFILE = r"account|profile|dashboard|settings"

    CAPTCHA = r"(re)?captcha"
    CONSENT = r"consent|gdpr"
    COOKIES_CONSENT = r"agree|accept"

    URL = r"(?:(?:https?|ftp)://)(?:\S+(?::\S*)?@)?(?:(?!10(?:\.\d{1,3}){3})(?!127(?:\.\d{1,3}){3})(?!169\.254(?:\.\d{1,3}){2})(?!192\.168(?:\.\d{1,3}){2})(?!172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}(?:\.(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-4]))|(?:(?:[a-z\\x{00a1}\-\\x{ffff}0-9]+-?)*[a-z\\x{00a1}\-\\x{ffff}0-9]+)(?:\.(?:[a-z\\x{00a1}\-\\x{ffff}0-9]+-?)*[a-z\\x{00a1}\-\\x{ffff}0-9]+)*(?:\.(?:[a-z\\x{00a1}\-\\x{ffff}]{2,})))(?::\d{2,5})?(?:/[^\s]*)?"

    CLICKABLE: str = (r'button,*[role="button"],*[onclick],input[type="button"],input[type="submit"],'
                      r'a[href="#"]')

    LOGOUT_KEYWORD: str = (r'log.?out|sign.?out|log.?off|sign.?off|exit|quit|invalidate|退出|'
                           r'注销|使无效')


if __name__ == '__main__':
    import re
    s = "1; mode=block; report=http://139.91.70.121"
    r = r"([0|1])\s*(\s*;\s*mode\s*=\s*block)?(\s*;\s*report\s*=\s*%s)?" % Regexes.URL
    m = re.match(r, s, re.IGNORECASE)
    print(m)
    if m:
        print(m.group())
