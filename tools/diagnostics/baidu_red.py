"""baidu.com 密码框「a」红色响应诊断 —— 只测一个密码 'a'，等 5 秒观察是否变红。

用法:
  .venv/bin/python tools/diagnostics/baidu_red.py
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


def snap(driver, el):
    return driver.execute_script(
        "var e=arguments[0];var cs=getComputedStyle(e);"
        "var r=e.getBoundingClientRect();"
        "var redBorder=function(c){var m=(c||'').match(/rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([\\d.]+))?/);"
        " if(!m)return false;var r=+m[1],g=+m[2],b=+m[3];"
        " var a=(m[4]!==undefined&&m[4]!=='')?parseFloat(m[4]):1.0;"
        " if(a<0.6)return false;"
        " return r>=170&&(r-g)>=80&&(r-b)>=80&&Math.abs(g-b)<=40;};"
        "return {border:cs.borderColor,isRed:redBorder(cs.borderColor),"
        " cls:(e.className||'').toString(),"
        " aria:e.getAttribute('aria-invalid'),"
        " valid:(e.validity?e.validity.valid:'n/a'),"
        " vmsg:(e.validationMessage||'')};",
        el,
    )


def nearby_err_text(driver, el):
    """收集密码框 4 层祖先内可见的短文本（可能含错误提示）。"""
    return driver.execute_script(
        "var el=arguments[0];"
        "function vis(e){var r=e.getBoundingClientRect();var cs=getComputedStyle(e);"
        "return r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden';}"
        "var out=[];var p=el;"
        "for(var lv=0;lv<4&&p;lv++){p=p.parentElement;if(!p)break;"
        " var nodes=p.querySelectorAll('span,div,p,small,em,strong,li,label,i');"
        " for(var i=0;i<nodes.length;i++){var n=nodes[i];if(vis(n)){"
        "  var t=(n.textContent||'').trim().replace(/\\s+/g,' ');"
        "  if(t.length>1&&t.length<120)out.push(t.slice(0,100));}}}"
        "var seen={},dedup=[];"
        "for(var j=0;j<out.length;j++){if(!seen[out[j]]){seen[out[j]]=1;dedup.push(out[j]);}}"
        "return dedup;",
        el,
    )


def fill_and_check(driver, el, label, js):
    """执行一次填充，等待 2s，返回是否变红 + 最终状态。"""
    # 清空
    driver.execute_script(
        "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "setter.call(arguments[0],'');"
        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el)
    time.sleep(0.4)
    driver.execute_script(js, el, "a")
    time.sleep(2.0)
    s = snap(driver, el)
    print(f"\n[{label}] isRed={s['isRed']} border={s['border']} cls={s['cls']}")
    return s


def main():
    print("[安全] 只观察：不填身份信息、不点发送验证码、不提交登录/注册、不创建账号。")
    driver = _get_new_driver()
    try:
        xpath, frame_path, discovery = reach_baidu_reg(driver)
        print(f"password_xpath = {xpath}")
        print(f"frame_path = {frame_path}")

        in_frame = False
        if frame_path:
            in_frame = _switch_to_frame_path(driver, frame_path)
            if not in_frame:
                print("切入 frame 失败")
                return

        try:
            if driver.execute_script("return typeof watchPasswordFeedback") != "function":
                LoginLinkDiscovery(driver).inject_feedback_into_current_frame()
        except Exception:
            pass

        el = WebDriverWait(driver, 8).until(
            EC.visibility_of_element_located((By.XPATH, xpath)))

        print("\n===== 填写前 =====")
        print(" 状态:", json.dumps(snap(driver, el), ensure_ascii=False))

        # ── 测试 1：现有 JS 填值（原生 setter + input + change）──
        JS_BASE = (
            "var elm=arguments[0],txt=arguments[1];"
            "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
            "setter.call(elm,txt);"
            "elm.dispatchEvent(new Event('input',{bubbles:true}));"
            "elm.dispatchEvent(new Event('change',{bubbles:true}));"
        )
        fill_and_check(driver, el, "测试1: JS setter+input+change", JS_BASE)

        # ── 测试 2：JS 填值 + 补发键盘事件（keydown/keypress/keyup）──
        JS_KEYS = (
            "var elm=arguments[0],txt=arguments[1];"
            "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
            "setter.call(elm,txt);"
            "var kd=new KeyboardEvent('keydown',{key:'a',bubbles:true});"
            "var kp=new KeyboardEvent('keypress',{key:'a',bubbles:true});"
            "var ku=new KeyboardEvent('keyup',{key:'a',bubbles:true});"
            "elm.dispatchEvent(kd);elm.dispatchEvent(kp);elm.dispatchEvent(ku);"
            "elm.dispatchEvent(new Event('input',{bubbles:true}));"
            "elm.dispatchEvent(new Event('change',{bubbles:true}));"
        )
        fill_and_check(driver, el, "测试2: JS setter + keydown/keypress/keyup + input", JS_KEYS)

        # ── 测试 3：JS 填值 + 仅 keyup + input ──
        JS_KEYUP = (
            "var elm=arguments[0],txt=arguments[1];"
            "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
            "setter.call(elm,txt);"
            "var ku=new KeyboardEvent('keyup',{key:'a',bubbles:true});"
            "elm.dispatchEvent(ku);"
            "elm.dispatchEvent(new Event('input',{bubbles:true}));"
        )
        fill_and_check(driver, el, "测试3: JS setter + keyup + input", JS_KEYUP)

        # ── 测试 4：真实 send_keys ──
        driver.execute_script(
            "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
            "setter.call(arguments[0],'');", el)
        time.sleep(0.4)
        el.click()
        el.send_keys("a")
        time.sleep(2.0)
        s = snap(driver, el)
        print(f"\n[测试4: send_keys] isRed={s['isRed']} border={s['border']} cls={s['cls']}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
