"""
diag_xuetangx_phone_tab.py — 一次性只读诊断探针

目的：xuetangx（学堂在线）手机号注册 tab 上的「inline 密码反馈」到底长什么样，
以及为什么 _detect_method() 在手机 tab 上拿不到反馈。

行为（严格遵守安全边界）：
  - 只填密码字段（不填手机号/身份信息、不点发送验证码、不提交、不创建账号）
  - 只读 DOM，不做任何提交/点击发送等动作

产出：把手机 tab 填坏密码后密码框附近的现场全量 dump 成 JSON，写到
      logs/xuetangx.com/diag_phone_tab_<ts>.json
"""

import sys
import os
import json
import time

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_new_driver
from utils.login_link_discovery import LoginLinkDiscovery
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

SITE = "https://www.xuetangx.com"

# 与 main.py._detect_method 完全一致的 JS setter（触发 React 受控组件的值更新）
JS_SET = """
var elm = arguments[0], txt = arguments[1];
elm.removeAttribute('aria-invalid');
var setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
setter.call(elm, txt);
elm.dispatchEvent(new Event('input', {bubbles: true}));
elm.dispatchEvent(new Event('change', {bubbles: true}));
"""

# 现场 dump：给定密码 XPath，返回密码框自身状态 + 门控判定 + 附近所有可见元素
# + detectPasswordFeedback / getWatchedFeedback 的返回值。
# 注意：用顶层 `return`（本项目 execute_script 已证明支持，见 main.py
#       "return getWatchedFeedback()"），并内置 try/catch 把 JS 报错也作为值
#       返回，避免任何异常被 Selenium 静默吞成 null。
DUMP_JS = r"""
try {
  var pwdXPath = arguments[0];
  var out = {};

  function evalX(xp){
    try {
      var r = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      return r.singleNodeValue;
    } catch(e){ return null; }
  }
  var el = evalX(pwdXPath);
  if (!el || el.nodeType !== 1) { out.error = 'pwd el not found: ' + pwdXPath; return out; }

  // ---- 1. 密码框自身状态 ----
  var cs = null;
  try { cs = getComputedStyle(el); } catch(e){}
  out.pwd = {
    tag: el.tagName, type: el.type || '', name: el.name || '', id: el.id || '',
    class: (typeof el.className === 'string') ? el.className : '',
    placeholder: el.placeholder || '',
    value: el.value || '',
    ariaInvalid: el.getAttribute('aria-invalid'),
    ariaDescribedby: el.getAttribute('aria-describedby'),
    color: cs ? cs.color : null,
    backgroundColor: cs ? cs.backgroundColor : null,
    borderColor: cs ? cs.borderColor : null,
    matchesInvalid: (function(){ try { return el.matches(':invalid'); } catch(e){ return null; } })(),
    validity: (function(){
      try { return { valid: el.validity.valid, message: el.validationMessage,
                     tooShort: el.validity.tooShort, patternMismatch: el.validity.patternMismatch }; }
      catch(e){ return null; }
    })(),
    outerHTML: el.outerHTML ? el.outerHTML.substring(0, 1500) : null
  };

  // ---- 2. 门控判定 ----
  out.gated = (typeof _isGatedForm === 'function') ? _isGatedForm(el) : 'no-fn';

  // ---- 3. form 内所有输入控件（确认 phone/code 是否存在 → 确认 gated 依据）----
  var form = null;
  try { form = el.closest('form'); } catch(e){}
  out.formTag = form ? form.tagName : null;
  var scope = form || document;
  out.formInputs = [];
  try {
    var inputs = scope.querySelectorAll('input, select, textarea');
    for (var i = 0; i < inputs.length; i++) {
      var inp = inputs[i];
      out.formInputs.push({
        tag: inp.tagName, type: inp.type || '', name: inp.name || '', id: inp.id || '',
        placeholder: inp.placeholder || '', visible: inp.offsetParent !== null,
        isPwd: inp === el
      });
    }
  } catch(e){}

  // ---- 4. 密码框 ancestor 链 4 层 + form 内所有可见元素的 tag/class/text/color ----
  var roots = [];
  var p = el.parentElement;
  for (var lvl = 0; lvl < 4 && p; lvl++) { roots.push(p); p = p.parentElement; }
  if (form) roots.push(form);
  var seen = {};
  out.nearby = [];
  for (var ri = 0; ri < roots.length; ri++) {
    var nodes = null;
    try { nodes = roots[ri].querySelectorAll('*'); } catch(e){ continue; }
    for (var ni = 0; ni < nodes.length; ni++) {
      var n = nodes[ni];
      var key = n.tagName + '|' + (typeof n.className === 'string' ? n.className : '')
              + '|' + (n.textContent || '').trim().substring(0, 60);
      if (seen[key]) continue;
      seen[key] = true;
      var rect = null;
      try { rect = n.getBoundingClientRect(); } catch(e){ continue; }
      if (rect.width <= 0 || rect.height <= 0) continue;
      if (n.offsetParent === null) continue;
      var txt = (n.textContent || '').trim().replace(/\s+/g, ' ');
      var ncs = null;
      try { ncs = getComputedStyle(n); } catch(e){}
      out.nearby.push({
        tag: n.tagName,
        class: (typeof n.className === 'string') ? n.className : '',
        text: txt.substring(0, 200),
        color: ncs ? ncs.color : null,
        w: Math.round(rect.width), h: Math.round(rect.height)
      });
    }
  }

  // ---- 5. 检测器三个视角的返回值 ----
  out.detectPasswordFeedback = (typeof detectPasswordFeedback === 'function')
      ? detectPasswordFeedback(pwdXPath) : 'no-fn';
  out.getWatchedFeedback = (typeof getWatchedFeedback === 'function')
      ? getWatchedFeedback() : 'no-fn';

  // ---- 6. 对密码框附近每个「短文本可见元素」跑一遍三闸门（诊断各闸门命中情况）----
  out.gateAudit = [];
  if (typeof _looksLikePwdFeedback === 'function' && typeof _isErrorColor === 'function'
      && typeof _isNonPwdFeedback === 'function') {
    for (var gi = 0; gi < out.nearby.length; gi++) {
      var e = out.nearby[gi];
      if (!e.text || e.text.length < 2 || e.text.length > 200) continue;
      out.gateAudit.push({
        text: e.text,
        color: e.color,
        looksLikePwd: _looksLikePwdFeedback(e.text),
        nonPwd: _isNonPwdFeedback(e.text)
      });
    }
  }

  return out;
} catch (e) {
  return { __js_error__: String((e && e.message) || e),
           __stack__: (e && e.stack) ? String(e.stack).substring(0, 800) : null };
}
"""


def dump_state(driver, password_xpath, label):
    """把当前 DOM 现场 dump 出来并返回 dict"""
    try:
        return driver.execute_script(DUMP_JS, password_xpath)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "label": label}


def main():
    driver = _get_new_driver()
    discovery = LoginLinkDiscovery(driver)
    result = {
        "site": SITE,
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": {},
    }

    try:
        # 1. 导航到注册页
        signup_url = discovery.navigate_to_signup(SITE)
        result["signup_url"] = signup_url
        print(f"[1] signup_url = {signup_url}")

        # 2. 找字段
        email_xpath, password_xpath = discovery.find_signup_fields()
        result["email_xpath"] = email_xpath
        result["password_xpath"] = password_xpath
        print(f"[2] email_xpath = {email_xpath}")
        print(f"[2] password_xpath = {password_xpath}")
        if not password_xpath:
            print("!! 未找到密码字段，中止")
            result["error"] = "no password field"
            return result

        # 3. 确保反馈 JS 已注入
        if not discovery.check_injected():
            discovery.inject()

        # 4. 等密码框可见
        pwd_el = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, password_xpath))
        )

        # 5. 初始现场（填任何东西之前 → 常驻规则提示基线）
        print("[5] dump 初始现场...")
        result["steps"]["initial"] = dump_state(driver, password_xpath, "initial")

        # 6. 填坏密码 "a" + focus/blur（与 _detect_method 一致）
        for probe_pwd in ["a", "k4m2x9a7"]:
            print(f"[6] 填坏密码 '{probe_pwd}' + focus/blur...")
            try:
                driver.execute_script(JS_SET, pwd_el, probe_pwd)
            except Exception as e:
                print(f"    fill 失败: {e}")

            # focus → blur
            try:
                pwd_el.click()
                time.sleep(0.2)
                ActionChains(driver).move_to_element(
                    pwd_el
                ).move_by_offset(
                    pwd_el.size['width'] + 30, 5
                ).click().perform()
            except Exception as e:
                print(f"    blur 失败: {e}")

            # 等反馈渲染
            time.sleep(1.5)
            result["steps"][f"after_{probe_pwd}"] = dump_state(
                driver, password_xpath, f"after_{probe_pwd}")

        # 7. 带 MutationObserver 的视角：watch → 填 → getWatchedFeedback
        print("[7] 启动 MutationObserver 重新观察一次...")
        try:
            ok = driver.execute_script("return watchPasswordFeedback(arguments[0])", password_xpath)
            print(f"    watchPasswordFeedback() = {ok}")
            driver.execute_script(JS_SET, pwd_el, "a")
            try:
                pwd_el.click()
                time.sleep(0.2)
                ActionChains(driver).move_to_element(
                    pwd_el
                ).move_by_offset(pwd_el.size['width'] + 30, 5).click().perform()
            except Exception:
                pass
            time.sleep(1.5)
            result["steps"]["observer_fill_a"] = dump_state(
                driver, password_xpath, "observer_fill_a")
        except Exception as e:
            result["steps"]["observer_error"] = f"{type(e).__name__}: {e}"

        print("[done] 现场采集完成")

    except Exception as e:
        import traceback
        traceback.print_exc()
        result["fatal_error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # 落盘
    host = "xuetangx.com"
    out_dir = os.path.join(_PROJECT_ROOT, "logs", host)
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    out_path = os.path.join(out_dir, f"diag_phone_tab_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"结果已保存到: {out_path}")

    return result


if __name__ == "__main__":
    main()
