"""baidu.com 政策提示文本颜色诊断 —— 为什么 observer 把「长度为8~14个字符」判成拒绝？

回答: 含「长度为8~14个字符」的元素，在 空/1字符/合法8字符(聚焦)/合法8字符(失焦) 各状态下
的 class、文字颜色、可见性，以及 getWatchedFeedback() 抓到了什么。

用法:
  .venv/bin/python tools/diagnostics/baidu_hint.py
"""
import json
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_new_driver
from utils.login_link_discovery import LoginLinkDiscovery
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
from signup_flow_classifier.page_detector import _switch_to_frame_path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains


def reach_baidu_reg(driver):
    site_url = "https://www.baidu.com"
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


def dump_hint(driver):
    return driver.execute_script(
        "var out=[];"
        "var all=document.querySelectorAll('*');"
        "for(var i=0;i<all.length;i++){var e=all[i];"
        " var t=(e.textContent||'').trim().replace(/\\s+/g,' ');"
        " if(t.indexOf('长度为8~14')!==-1||t.indexOf('8~14个字符')!==-1){"
        "  var r=e.getBoundingClientRect();var cs=getComputedStyle(e);"
        "  out.push({tag:e.tagName,cls:(e.className||'').toString().slice(0,80),"
        "   color:cs.color,"
        "   visible:(r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden'),"
        "   rect:[Math.round(r.width),Math.round(r.height)],"
        "   txt:t.slice(0,120)});}"
        "}"
        "return out;",
    )


def blur(driver, el):
    try:
        ActionChains(driver).move_to_element(el).move_by_offset(
            el.size['width'] // 2 + 30, 5).click().perform()
    except Exception as e:
        print("  blur 异常:", str(e).splitlines()[0])


def main():
    print("[安全] 只观察：不填身份信息、不点发送验证码、不提交。")
    driver = _get_new_driver()
    try:
        xpath, frame_path, discovery = reach_baidu_reg(driver)
        if frame_path:
            _switch_to_frame_path(driver, frame_path)
        el = WebDriverWait(driver, 8).until(
            EC.visibility_of_element_located((By.XPATH, xpath)))

        print("\n===== 空状态（填写前） =====")
        print("  hint:", json.dumps(dump_hint(driver), ensure_ascii=False))

        # 启动 observer
        driver.execute_script("return watchPasswordFeedback(arguments[0])", xpath)

        print("\n===== 输入 1 字符 'k' =====")
        el.click()
        el.send_keys("k")
        time.sleep(0.8)
        print("  hint:", json.dumps(dump_hint(driver), ensure_ascii=False))
        print("  watched:", json.dumps(
            driver.execute_script("return getWatchedFeedback()"), ensure_ascii=False))

        print("\n===== 输入合法 8 字符 'k4m2x9a7'（聚焦中） =====")
        el.send_keys("4m2x9a7")
        time.sleep(0.8)
        print("  hint:", json.dumps(dump_hint(driver), ensure_ascii=False))
        print("  watched:", json.dumps(
            driver.execute_script("return getWatchedFeedback()"), ensure_ascii=False))

        print("\n===== blur 后 =====")
        blur(driver, el)
        time.sleep(1.0)
        print("  hint:", json.dumps(dump_hint(driver), ensure_ascii=False))
        print("  watched:", json.dumps(
            driver.execute_script("return getWatchedFeedback()"), ensure_ascii=False))

        try:
            driver.execute_script("stopWatchingFeedback()")
        except Exception:
            pass
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
