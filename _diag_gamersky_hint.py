"""gamersky.com 政策提示文本诊断 —— 「密码 (6-20位字母与数字、符号组合」是静态提示还是动态错误？

回答: 含「6-20位」的元素，在 空/1字符/纯字母/字母+数字/字母+数字+符号 各状态下
的 class、文字颜色、可见性、以及密码框的 placeholder / aria-describedby。

据此判断 full-form 的 _capture_dom_errors 是否把常驻政策提示误当拒绝信号。

用法:
  D:/Anaconda/anaconda/python.exe _diag_gamersky_hint.py
"""
import json
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_new_driver
from utils.login_link_discovery import LoginLinkDiscovery
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
from signup_flow_classifier.page_detector import _switch_to_frame_path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def reach_gamersky_reg(driver):
    site_url = "https://www.gamersky.com"
    discovery = LoginLinkDiscovery(driver)
    signup_url = discovery.navigate_to_signup(site_url)
    engine = SignupFlowClassifierEngine(driver)
    classification = engine.classify(
        signup_url, entry_kind="signup",
        entry_already_clicked=bool(getattr(discovery, "_entry_clicked", False)),
        stop_at_password=True,
    )
    pw = classification.get("password_field") or {}
    xpath = pw.get("xpath")
    frame_path = pw.get("frame_path") or ()
    if not xpath:
        _, xpath = discovery.find_signup_fields()
        frame_path = ()
    return xpath, frame_path, discovery


def dump_pw_and_hints(driver):
    """密码框属性 + 所有含「6-20」/「密码」政策字样的元素的状态。"""
    return driver.execute_script(
        "var out={pw:null, hints:[]};"
        "var pwEl=document.querySelector(\"input[type='password']\")"
        " || document.querySelector(\"#Password\");"
        "if(pwEl){"
        " var cs=getComputedStyle(pwEl);"
        " out.pw={placeholder:(pwEl.getAttribute('placeholder')||''),"
        "  cls:(pwEl.className||'').toString(),"
        "  aria_desc:(pwEl.getAttribute('aria-describedby')||''),"
        "  border:cs.borderColor, maxlength:(pwEl.getAttribute('maxlength')||'')};"
        "}"
        "var all=document.querySelectorAll('*');"
        "for(var i=0;i<all.length;i++){var e=all[i];"
        " var t=(e.textContent||'').trim().replace(/\\s+/g,' ');"
        " if(t.indexOf('6-20')!==-1||t.indexOf('6~20')!==-1||t.indexOf('密码')!==-1){"
        "  if(e.children.length>0) continue; /* leaf only */"
        "  var r=e.getBoundingClientRect();var c=getComputedStyle(e);"
        "  var vis=(r.width>0&&r.height>0&&c.display!=='none'&&c.visibility!=='hidden');"
        "  if(t.length>0&&t.length<120){"
        "   out.hints.push({tag:e.tagName,cls:(e.className||'').toString().slice(0,60),"
        "    color:c.color,vis:vis,rect:[Math.round(r.width),Math.round(r.height)],"
        "    txt:t.slice(0,100)});"
        "  }"
        " }"
        "}"
        "return out;",
    )


def fill_pwd(driver, el, s):
    """清空并输入，不提交、不填其他字段。"""
    driver.execute_script(
        "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "setter.call(arguments[0],'');"
        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el)
    if s:
        el.send_keys(s)
    time.sleep(0.8)


def main():
    print("[安全] 只观察：不填身份信息、不点发送验证码、不提交登录/注册、不创建账号。")
    driver = _get_new_driver()
    try:
        xpath, frame_path, discovery = reach_gamersky_reg(driver)
        print(f"password_xpath = {xpath}")
        print(f"frame_path = {frame_path}")

        if frame_path:
            _switch_to_frame_path(driver, frame_path)
        el = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, xpath)))

        print("\n===== 空状态（填写前） =====")
        print(json.dumps(dump_pw_and_hints(driver), ensure_ascii=False, indent=1))

        cases = [
            ("单字符 a", "a"),
            ("纯小写 8 位 abcdefgh（仅1类）", "abcdefgh"),
            ("字母+数字 8 位 Ab3defgh（2类）", "Ab3defgh"),
            ("字母+数字+符号 9 位 Ab3defgh!（3类）", "Ab3defgh!"),
        ]
        for label, pwd in cases:
            print(f"\n===== {label} : {pwd!r} =====")
            fill_pwd(driver, el, pwd)
            print(json.dumps(dump_pw_and_hints(driver), ensure_ascii=False, indent=1))
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
