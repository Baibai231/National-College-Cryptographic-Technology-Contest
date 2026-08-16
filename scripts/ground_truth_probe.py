"""全站地面真值探测：逐个打开站点收集认证界面的真实证据。

只观察不提交（安全边界）。每个站点记录：
- 可见认证文本（登录/注册/验证码/手机/微信/QQ/微博/扫码/合作…）
- 输入框 placeholder/type
- 第三方图标 img alt/title
- 注册链接 href+文本
- 检测到的 tab
供人工逐站与程序输出对照审计。
用法:
  .venv/bin/python3 scripts/ground_truth_probe.py misc/sites_base_60.txt --output /tmp/gt_evidence.jsonl
"""
import argparse
import json
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.util_test_password import _get_new_driver
from utils.login_link_discovery import LoginLinkDiscovery
from signup_flow_classifier.page_detector import detect_tabs_all_frames

AUTH_KEYWORDS = ("登录", "注册", "验证码", "短信", "微信", "QQ", "微博", "手机",
                 "密码", "扫码", "合作", "立即", "免费注册", "账号", "邮箱",
                 "忘记", "签约", "入驻", "app", "App", "下载", "验证")


def probe_site(driver, site_url: str, deep: bool = False) -> dict:
    ev = {"site": site_url, "url": "", "title": "", "inputs": [],
          "auth_texts": [], "sso_imgs": [], "register_links": [],
          "tabs": [], "note": ""}
    try:
        discovery = LoginLinkDiscovery(driver)
        try:
            discovery.navigate_to_signup(site_url)
        except Exception as exc:
            ev["note"] = "navigate_err:{}".format(str(exc)[:80])
        if deep:
            # 深度模式：hover 菜单展开 + 多轮重试
            from signup_flow_classifier.navigator import (
                detect_entry_button, safe_hover_menu)
            for attempt in range(2):
                try:
                    detect_entry_button(driver, "login")
                    hover_outcome = safe_hover_menu(driver, "login")
                    if hover_outcome and hover_outcome.changed:
                        ev["note"] = "hover_expanded"
                        break
                except Exception:
                    pass
                time.sleep(2.5)
        time.sleep(3)
        ev["url"] = driver.current_url
        try:
            ev["title"] = driver.title[:60]
        except Exception:
            pass
        data = driver.execute_script("""
        const vis = e => {const r=e.getBoundingClientRect(),s=getComputedStyle(e);
          return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
        const norm = s => (s||'').trim().replace(/\\s+/g,'');
        const inputs=[];
        for(const e of document.querySelectorAll('input,textarea')){
          if(!vis(e)) continue;
          inputs.push({ph:(e.getAttribute('placeholder')||'').slice(0,25),
                       ty:(e.getAttribute('type')||'')});
        }
        const texts=[];
        for(const e of document.querySelectorAll('div,span,li,a,button')){
          if(!vis(e)) continue;
          const t=norm(e.textContent);
          if(t.length>=2&&t.length<=20) texts.push(t);
        }
        const imgs=[];
        for(const e of document.querySelectorAll('img')){
          if(!vis(e)) continue;
          const a=e.getAttribute('alt')||'', t=e.getAttribute('title')||'';
          if(a||t) imgs.push({alt:a.slice(0,10),title:t.slice(0,10)});
        }
        const regs=[];
        for(const e of document.querySelectorAll('a')){
          if(!vis(e)) continue;
          const t=norm(e.textContent);
          const h=e.getAttribute('href')||'';
          if(/立即注册|免费注册|注册账号|新用户|注册会员/i.test(t) && h)
            regs.push({t:t.slice(0,10), h:h.slice(0,60)});
        }
        return {inputs, texts, imgs, regs};
        """)
        ev["inputs"] = data.get("inputs") or []
        texts = list(dict.fromkeys(data.get("texts") or []))
        ev["auth_texts"] = [t for t in texts
                            if any(k in t for k in AUTH_KEYWORDS)][:40]
        ev["sso_imgs"] = [x for x in (data.get("imgs") or [])
                          if x["alt"] or x["title"]][:20]
        ev["register_links"] = (data.get("regs") or [])[:5]
        try:
            ev["tabs"] = detect_tabs_all_frames(driver)
        except Exception:
            ev["tabs"] = []
    except Exception as exc:
        ev["note"] = "probe_err:{}".format(str(exc)[:100])
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return ev


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="站点清单文件（每行一个 URL）")
    ap.add_argument("--output", default="/tmp/gt_evidence.jsonl")
    ap.add_argument("--start", type=int, default=0, help="从第 N 个站点开始（断点续跑）")
    ap.add_argument("--deep", action="store_true", help="深度模式：hover/多轮/长等待")
    args = ap.parse_args()
    sites = [l.strip() for l in
             Path(args.input).read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    done = set()
    if Path(args.output).exists():
        for line in Path(args.output).read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["site"])
                except Exception:
                    pass
    out = open(args.output, "a", encoding="utf-8")
    try:
        for idx, site in enumerate(sites):
            if idx < args.start:
                continue
            if site in done:
                print(f"[{idx+1}/{len(sites)}] 跳过(已完成) {site}")
                continue
            print(f"[{idx+1}/{len(sites)}] 探测 {site}", flush=True)
            ev = probe_site(_get_new_driver(), site, deep=args.deep)
            out.write(json.dumps(ev, ensure_ascii=False) + "\n")
            out.flush()
            time.sleep(1)
    finally:
        out.close()
    print("完成，证据写入", args.output)


if __name__ == "__main__":
    main()
