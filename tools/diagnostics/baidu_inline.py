"""baidu.com inline 失败诊断 —— 只观察密码框反馈，不填身份信息、不提交。

用法:
  .venv/bin/python tools/diagnostics/baidu_inline.py
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
from signup_flow_classifier.page_detector import (
    _switch_to_frame_path, _visible_frame_paths,
)


def dump_password_fields(driver, label):
    """枚举主文档 + 所有 iframe 里的 password 输入框状态（可见性/可用性/边框）。"""
    print(f"\n===== {label} =====")
    # 主文档
    try:
        js = (
            "var out=[];"
            "var els=document.querySelectorAll(\"input[type='password']\");"
            "for(var i=0;i<els.length;i++){"
            " var e=els[i];var r=e.getBoundingClientRect();"
            " var cs=getComputedStyle(e);"
            " out.push({frame:'MAIN',id:e.id,cls:(e.className||'').toString().slice(0,50),"
            "  visible:(r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden'&&cs.opacity!=='0'),"
            "  disabled:e.disabled,border:cs.borderColor,"
            "  rect:[Math.round(r.width),Math.round(r.height)]});"
            "}"
            "return out;"
        )
        main_fields = driver.execute_script(js)
    except Exception as e:
        print(f"  主文档枚举失败: {e}")
        main_fields = []
    for f in main_fields:
        print(f"  {f}")
    if not main_fields:
        print("  (主文档无 password 输入框)")

    # 各 iframe
    try:
        for path in _visible_frame_paths(driver):
            if not _switch_to_frame_path(driver, path):
                continue
            try:
                fields = driver.execute_script(
                    "var out=[];"
                    "var els=document.querySelectorAll(\"input[type='password']\");"
                    "for(var i=0;i<els.length;i++){"
                    " var e=els[i];var r=e.getBoundingClientRect();"
                    " var cs=getComputedStyle(e);"
                    " out.push({frame:'" + json.dumps(list(path)) + "',id:e.id,"
                    "  cls:(e.className||'').toString().slice(0,50),"
                    "  visible:(r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden'&&cs.opacity!=='0'),"
                    "  disabled:e.disabled,border:cs.borderColor,"
                    "  rect:[Math.round(r.width),Math.round(r.height)]});"
                    "}"
                    "return out;"
                )
                for f in fields:
                    print(f"  {f}")
            finally:
                driver.switch_to.default_content()
    except Exception as e:
        print(f"  iframe 枚举失败: {e}")


def probe_feedback(driver, xpath, frame_path):
    """在指定 frame 内填短密码 'a'，blur 后捕获各类反馈。"""
    print(f"\n===== 探测反馈 xpath={xpath} frame_path={frame_path} =====")
    in_frame = False
    if frame_path:
        in_frame = _switch_to_frame_path(driver, frame_path)
        if not in_frame:
            print(f"  ✗ 无法切入 frame {frame_path}")
            return
    try:
        # 注入反馈 JS（若缺失）
        try:
            if driver.execute_script("return typeof watchPasswordFeedback") != "function":
                LoginLinkDiscovery(driver).inject_feedback_into_current_frame()
                print("  已补注入反馈 JS")
        except Exception as e:
            print(f"  补注入失败: {e}")

        # 检查密码框附近的 DOM 结构（政策提示 / 强度计 / 错误占位）
        def dump_nearby(el):
            return driver.execute_script(
                "var el=arguments[0];"
                "function vis(e){var r=e.getBoundingClientRect();var cs=getComputedStyle(e);"
                "return r.width>0&&r.height>0&&cs.display!=='none'&&cs.visibility!=='hidden';}"
                "var out=[];"
                "var p=el;"
                "for(var lv=0;lv<4&&p;lv++){p=p.parentElement;"
                " if(!p)break;"
                " var nodes=p.querySelectorAll('span,div,p,small,em,strong,b,li,label,i');"
                " for(var i=0;i<nodes.length;i++){var n=nodes[i];"
                "  if(vis(n)){var t=(n.textContent||'').trim().replace(/\\s+/g,' ');"
                "   if(t.length>1&&t.length<120)out.push({lv:lv,tag:n.tagName,cls:(n.className||'').toString().slice(0,40),txt:t.slice(0,100)});}}"
                "}"
                "var seen={},dedup=[];"
                "for(var j=0;j<out.length;j++){var k=out[j].lv+'|'+out[j].tag+'|'+out[j].txt;"
                " if(!seen[k]){seen[k]=1;dedup.push(out[j]);}}"
                "return dedup.slice(0,40);",
                el,
            )

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            el = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, xpath)))
        except Exception as e:
            print(f"  ✗ 找不到可见密码框: {e}")
            return

        print("  密码框附近 DOM（填写前）:")
        for n in dump_nearby(el):
            print(f"    [{n['lv']}] <{n['tag']}> cls={n['cls']!r} txt={n['txt']!r}")

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            el = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, xpath)))
        except Exception as e:
            print(f"  ✗ 找不到可见密码框: {e}")
            return

        # 填写前状态
        def snap(tag):
            return driver.execute_script(
                "var e=arguments[0];var cs=getComputedStyle(e);"
                "return {cls:(e.className||'').toString().slice(0,60),"
                " aria:e.getAttribute('aria-invalid'),"
                " border:cs.borderColor,"
                " valid:(e.validity?e.validity.valid:'n/a'),"
                " vmsg:(e.validationMessage||'').slice(0,80),"
                " value_len:e.value.length};",
                el,
            )

        print("  填写前:", snap("before"))

        # 启动 observer
        obs = driver.execute_script("return watchPasswordFeedback(arguments[0])", xpath)
        print("  observer 启动:", obs)

        js_set = (
            "var elm=arguments[0],txt=arguments[1];"
            "elm.removeAttribute('aria-invalid');"
            "var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
            "setter.call(elm,txt);"
            "elm.dispatchEvent(new Event('input',{bubbles:true}));"
            "elm.dispatchEvent(new Event('change',{bubbles:true}));"
        )
        driver.execute_script(js_set, el, "a")
        time.sleep(0.3)

        # focus + blur（对比：ActionChains 真实点击 vs JS blur）
        try:
            el.click()
            time.sleep(0.2)
        except Exception as e:
            print("  focus 异常:", e)
        try:
            ActionChains(driver).move_to_element(el).move_by_offset(
                el.size['width'] + 30, 5).click().perform()
            print("  [ActionChains blur] 成功")
        except Exception as e:
            print("  [ActionChains blur] 失败:", str(e).splitlines()[0])
        # 无论 ActionChains 是否成功，都补一次 JS blur，确保失焦触发校验
        try:
            driver.execute_script(
                "arguments[0].blur();arguments[0].dispatchEvent(new Event('blur',{bubbles:true}))",
                el)
            print("  [JS blur] 已执行")
        except Exception as e:
            print("  [JS blur] 失败:", e)

        # 采样 0.5s / 1.0s / 1.5s
        for t in [0.5, 1.0, 1.5]:
            time.sleep(0.5)
            print(f"  +{t}s 状态:", snap(f"t{t}"))
            try:
                got = driver.execute_script("return getWatchedFeedback()")
                if got:
                    print(f"     observer反馈: {json.dumps(got, ensure_ascii=False)}")
            except Exception as e:
                print(f"     observer读取失败: {e}")

        # 静态兜底检测
        try:
            fb = driver.execute_script("return detectPasswordFeedback(arguments[0])", xpath)
            print("  静态检测 detectPasswordFeedback:", json.dumps(fb, ensure_ascii=False))
        except Exception as e:
            print("  静态检测失败:", e)

        print("  密码框附近 DOM（填写 'a' 并 blur 后）:")
        for n in dump_nearby(el):
            print(f"    [{n['lv']}] <{n['tag']}> cls={n['cls']!r} txt={n['txt']!r}")

        try:
            driver.execute_script("stopWatchingFeedback()")
        except Exception:
            pass
    finally:
        if in_frame:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass


def main():
    print("[安全] 只观察和分类：不填身份信息、不点发送验证码、不提交登录/注册、不创建账号。")
    site_url = "https://www.baidu.com"
    driver = _get_new_driver()
    try:
        print(f"\n===== Phase 1: 发现注册入口 {site_url} =====")
        discovery = LoginLinkDiscovery(driver)
        signup_url = discovery.navigate_to_signup(site_url)
        print(f"  signup_url = {signup_url}")

        engine = SignupFlowClassifierEngine(driver)
        print(f"\n===== Phase 2: 分类流程 =====")
        classification = engine.classify(
            signup_url, entry_kind="signup",
            entry_already_clicked=bool(getattr(discovery, "_entry_clicked", False)),
            stop_at_password=True,
        )
        print("  flow_type:", classification.get("flow_type"))
        print("  signup_password_reached:", classification.get("signup_password_reached"))
        print("  password_field:", json.dumps(classification.get("password_field"), ensure_ascii=False))
        print("  final_url:", classification.get("final_url"))

        dump_password_fields(driver, "分类后 password 输入框全景")

        pw_field = classification.get("password_field") or {}
        xpath = pw_field.get("xpath")
        frame_path = pw_field.get("frame_path")
        if not xpath:
            # 兜底用 find_signup_fields
            _, xpath = discovery.find_signup_fields()
            frame_path = None
            print("  (fallback find_signup_fields xpath =", xpath, ")")
        if xpath:
            probe_feedback(driver, xpath, frame_path)
        else:
            print("  ✗ 未拿到密码字段 XPath")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
