"""baidu.com 失焦(blur)后仍变红诊断 —— 回答两个问题:

1. ActionChains 点击右侧空白处后，密码框是否真的失焦？（查 document.activeElement）
2. 合法密码 (k4m2x9a7) vs 非法密码 (a) vs 超长密码，blur 后边框颜色/class/aria 随时间如何变化？
   —— 用于区分「CSS 过渡瞬态」和「持久误拒」。

用法:
  .venv/bin/python tools/diagnostics/baidu_blur.py
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


def snap(driver, el):
    """一次采样：边框颜色/是否红/class/aria/validity/是否聚焦。"""
    return driver.execute_script(
        "var e=arguments[0];var cs=getComputedStyle(e);"
        "var redBorder=function(c){var m=(c||'').match(/rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([\\d.]+))?/);"
        " if(!m)return false;var r=+m[1],g=+m[2],b=+m[3];"
        " var a=(m[4]!==undefined&&m[4]!=='')?parseFloat(m[4]):1.0;"
        " if(a<0.6)return false;"
        " return r>=170&&(r-g)>=80&&(r-b)>=80&&Math.abs(g-b)<=40;};"
        "var active=(document.activeElement===e)?'YES':((document.activeElement&&document.activeElement.tagName)||'none');"
        "return {border:cs.borderColor,isRed:redBorder(cs.borderColor),"
        " cls:(e.className||'').toString(),"
        " aria:e.getAttribute('aria-invalid'),"
        " valid:(e.validity?e.validity.valid:'n/a'),"
        " vmsg:(e.validationMessage||'').slice(0,80),"
        " active:active,"
        " vlen:e.value.length};",
        el,
    )


def nearby_hint(driver, el):
    """抓取密码框 3 层祖先内可见文本（政策提示）。"""
    return driver.execute_script(
        "var el=arguments[0];"
        "function vis(e){var r=e.getBoundingClientRect();var cs=getComputedStyle(e);"
        "return r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden';}"
        "var out=[];var p=el;"
        "for(var lv=0;lv<3&&p;lv++){p=p.parentElement;if(!p)break;"
        " var ns=p.querySelectorAll('span,div,p,small,em,strong,li,label,i');"
        " for(var i=0;i<ns.length;i++){var n=ns[i];if(vis(n)){"
        "  var t=(n.textContent||'').trim().replace(/\\s+/g,' ');"
        "  if(t.length>1&&t.length<120)out.push(t.slice(0,100));}}}"
        "var seen={},d=[];for(var j=0;j<out.length;j++){if(!seen[out[j]]){seen[out[j]]=1;d.push(out[j]);}}"
        "return d;",
        el,
    )


def do_blur(driver, el):
    """按修正后的 offset 点击右侧空白处。返回是否抛异常。"""
    err = None
    try:
        ActionChains(driver).move_to_element(el).move_by_offset(
            el.size['width'] // 2 + 30, 5
        ).click().perform()
    except Exception as e:
        err = str(e).splitlines()[0]
    return err


def test_one(driver, el, label, pwd):
    print(f"\n{'='*60}\n[{label}] password={pwd!r}")
    # 1) 先清空并失焦（清除上一轮状态）
    driver.execute_script(
        "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "setter.call(arguments[0],'');"
        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));", el)
    time.sleep(0.3)
    do_blur(driver, el)
    time.sleep(0.5)
    print("  reset+blur 后:", json.dumps(snap(driver, el), ensure_ascii=False))

    # 2) 聚焦 + 键盘输入
    el.click()
    el.send_keys(pwd)
    time.sleep(0.3)
    print("  send_keys 后(聚焦中):", json.dumps(snap(driver, el), ensure_ascii=False))

    # 3) blur
    err = do_blur(driver, el)
    print(f"  blur 点击 {'成功' if not err else '异常: '+err}")
    # 4) 采样：blur 后 0s / 0.5s / 1s / 1.5s / 2s / 3s
    print("    +0.0s:", json.dumps(snap(driver, el), ensure_ascii=False))
    time.sleep(0.5)
    print("    +0.5s:", json.dumps(snap(driver, el), ensure_ascii=False))
    time.sleep(0.5)
    print("    +1.0s:", json.dumps(snap(driver, el), ensure_ascii=False))
    time.sleep(0.5)
    print("    +1.5s:", json.dumps(snap(driver, el), ensure_ascii=False))
    time.sleep(0.5)
    print("    +2.0s:", json.dumps(snap(driver, el), ensure_ascii=False))
    time.sleep(1.0)
    print("    +3.0s:", json.dumps(snap(driver, el), ensure_ascii=False))


def main():
    print("[安全] 只观察：不填身份信息、不点发送验证码、不提交登录/注册、不创建账号。")
    driver = _get_new_driver()
    try:
        xpath, frame_path, discovery = reach_baidu_reg(driver)
        print(f"password_xpath = {xpath}")
        print(f"frame_path = {frame_path}")

        if frame_path:
            if not _switch_to_frame_path(driver, frame_path):
                print("切入 frame 失败")
                return

        el = WebDriverWait(driver, 8).until(
            EC.visibility_of_element_located((By.XPATH, xpath)))

        print("\n===== 密码框尺寸 =====")
        print("  size:", el.size, "rect:", el.rect)
        print("  政策提示附近文本:", json.dumps(nearby_hint(driver, el), ensure_ascii=False))

        # 依次测：非法 (a) / 合法 8位 (k4m2x9a7) / 合法 12位 / 超长
        test_one(driver, el, "非法-单字符", "a")
        test_one(driver, el, "合法-8位字母数字", "k4m2x9a7")
        test_one(driver, el, "合法-12位混合", "k4m2x9a7ty1K")
        test_one(driver, el, "超长-36位", "k4m2x9a7tyixays4Ww3ufTXh1hBLKd5V")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
