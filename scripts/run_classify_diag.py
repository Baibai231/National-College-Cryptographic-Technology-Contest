"""注册流程分类诊断脚本 —— 只观察、不填字段、不提交、不测口令政策。

用法:
  .venv/bin/python scripts/run_classify_diag.py https://www.imooc.com --kind signup
  .venv/bin/python scripts/run_classify_diag.py https://www.zhihu.com --kind signup
  .venv/bin/python scripts/run_classify_diag.py https://www.zhihu.com --kind signup --kind login
"""
import argparse
import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_new_driver
from utils.login_link_discovery import LoginLinkDiscovery
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
from signup_flow_classifier.navigator import detect_entry_button, safe_click_entry
from signup_flow_classifier.page_detector import (
    detect_fields_all_frames, detect_tabs_all_frames, detect_blockers,
)
from signup_flow_classifier.browser_failures import detect_access_block

SAFE_NOTE = (
    "\n[安全] 只观察和分类：不填身份信息、不点发送验证码、不提交登录/注册、不创建账号。"
)


def dump_page_snapshot(driver, label: str) -> dict:
    """只读页面快照：可见控件关键词、字段、tab、阻断、认证面。"""
    snap = {"label": label}
    try:
        snap["url"] = driver.current_url
        snap["title"] = driver.title
    except Exception:
        snap["url"] = ""
        snap["title"] = ""
    try:
        snap["fields"] = detect_fields_all_frames(driver)
    except Exception:
        snap["fields"] = []
    try:
        snap["tabs"] = detect_tabs_all_frames(driver)
    except Exception:
        snap["tabs"] = []
    try:
        snap["blockers"] = detect_blockers(driver)
    except Exception:
        snap["blockers"] = []
    try:
        snap["access_block"] = detect_access_block(driver)
    except Exception:
        snap["access_block"] = None
    # 可见认证面文本关键词（只读 innerText 采样，不点任何东西）
    try:
        texts = driver.execute_script(
            "const vis=e=>{const r=e.getBoundingClientRect(),"
            "s=getComputedStyle(e);return r.width>0&&r.height>0"
            "&&s.display!=='none'&&s.visibility!=='hidden'};"
            "const kw=/登录|登陆|注册|密码|账号|账户|手机|邮箱|微信|扫码|验证码|sign ?in|log ?in|register|create ?account/i;"
            "const out=[];"
            "for(const e of document.querySelectorAll("
            "'a,button,[role=tab],[role=button],[class*=tab i],[class*=login i],[class*=register i],[class*=auth i],dialog,[aria-modal=true]')){"
            " if(vis(e)){const t=(e.innerText||'').trim().replace(/\\s+/g,' ');"
            " if(t&&t.length<60&&kw.test(t))out.push({tag:e.tagName,text:t.slice(0,50),"
            "  cls:(e.className||'').toString().slice(0,40),href:(e.getAttribute('href')||'').slice(0,80)});}}"
            "const seen=new Set(),dedup=[];"
            "for(const o of out){const k=o.tag+'|'+o.text+'|'+o.href;if(!seen.has(k)){seen.add(k);dedup.push(o);}}"
            "return dedup.slice(0,40);"
        )
        snap["auth_controls"] = texts or []
    except Exception:
        snap["auth_controls"] = []
    return snap


def run_classify(driver, site_url: str, kind: str) -> dict:
    print(f"\n{'='*70}\n[Phase 1] 发现{kind}入口: {site_url}")
    discovery = LoginLinkDiscovery(driver)
    signup_url = discovery.navigate_to_signup(site_url)

    engine = SignupFlowClassifierEngine(driver)
    if not signup_url:
        print("[Phase 1] 注册页发现失败，回退：对当前页直接分类")
        signup_url = driver.current_url
    else:
        print(f"[Phase 1] 注册页: {signup_url}")

    entry_clicked = getattr(discovery, "_entry_clicked", False)
    print(f"[Phase 1] 入口是否已被点击: {entry_clicked}")
    print(f"\n[Phase 2] 分类 {kind} 流程 ...")

    result = engine.classify(
        signup_url, entry_kind=kind,
        entry_already_clicked=bool(entry_clicked and kind == "signup"),
    )

    summary = {
        "site": site_url,
        "entry_kind": kind,
        "final_url": result.get("final_url"),
        "flow_type": result.get("flow_type"),
        "class_letter": result.get("class_letter"),
        "confidence": result.get("confidence"),
        "stop_reason": result.get("stop_reason"),
        "primary_method": result.get("primary_method"),
        "ui_type": result.get("ui_type"),
        "should_proceed": result.get("should_proceed"),
        "password_reached": result.get("password_reached"),
        "policy": result.get("policy"),
        "error": result.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[Phase 2] 状态序列:")
    for s in result.get("states", []):
        if isinstance(s, dict):
            st = s
        else:
            st = {
                "step": getattr(s, "step", ""),
                "url": getattr(s, "url", ""),
                "fields": getattr(s, "fields", []),
                "tabs": getattr(s, "tabs", []),
                "blockers": getattr(s, "blockers", []),
                "methods": getattr(s, "methods", []),
                "actions": getattr(s, "actions", []),
                "ui_type": getattr(s, "ui_type", ""),
            }
        print(json.dumps(st, ensure_ascii=False))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="网站 URL，如 https://www.imooc.com")
    ap.add_argument("--kind", action="append", default=["signup"],
                    choices=["signup", "login"],
                    help="入口类型，可多次指定，默认 signup")
    ap.add_argument("--out", default="/tmp/classify_diag.jsonl", help="JSONL 输出")
    args = ap.parse_args()

    print(SAFE_NOTE)
    driver = _get_new_driver()
    results = []
    try:
        for kind in args.kind:
            try:
                r = run_classify(driver, args.url, kind)
                results.append(r)
                snap = dump_page_snapshot(driver, f"after_{kind}")
                print(f"\n[Phase 3] {kind} 结束后页面快照:")
                print(json.dumps(snap, ensure_ascii=False, indent=1))
                results.append(snap)
            except Exception as e:
                import traceback
                traceback.print_exc()
                results.append({"site": args.url, "entry_kind": kind,
                                "error": str(e)[:200]})
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    with open(args.out, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n结果已追加到 {args.out}")


if __name__ == "__main__":
    main()
