class LoginRegexes(object):
    # common error message - need to add more information
    ERROR_MESSAGE: str = r"\b(incorrect|wrong|not match|doesn't match|doesn't exist|" \
                         r"not exist|isn't right|not right|fail|wasn't right|not right|" \
                         r"failed|invalid)\b|错误|不正确|失败|无效|用户不存在"

    LOGOUT_KEYWORDS: str = r'log.?out|sign.?out|log.?off|sign.?off|exit|quit|invalidate|'

    VERIFICATION_MSG: str = r"(\W|^)(verify|verification)(\W|$)"


