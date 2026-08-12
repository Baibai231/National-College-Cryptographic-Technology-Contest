# CHANGELOG

> 记录本项目从"参赛代码"基线开始的变更历史。
> 原则：每次改动都要在这里加一行记录，包括：日期、改动人、改了哪个文件、为什么改、影响什么。

---

## 变更速查表

| 日期时间 | 改动人 | 内容 | 相关文件 | 推送状态 |
|---|---|---|---|---|
| 2026-08-12 | cjx（Mac） | 修复慕课网手机号字段被误判为 email、知乎机构号注册入口误当普通注册 | signup_flow_classifier/page_detector.py、utils/login_link_discovery.py、utils/js/form_detection_addons.js、tests/test_site_recognition_fixes.py | 未推送 |

---

## 实现细节

### 1. 修复 imooc（慕课网）注册手机号字段被误判为 email（2026-08-12）

问题：慕课注册弹窗的手机号输入框 `name="email"` 但 placeholder 是"请输入注册手机号"，
原分类按 `name/id` 结构属性先命中 email 提示词，导致 `fields=[email, code]`、
`blockers=[email_code]`、`primary_method=email` 全部错位。

修复（通用规则，非硬编码）：

- `classify_input_type()` 与 `_classify_combined()` 增加"用户可见语义优先"规则：
  placeholder/aria-label 明确含手机号（且不含邮箱语义）→ 判 `phone`；
  明确含邮箱（且不含手机语义）→ 判 `email`；两者并存时保留原结构判定。
- JS 侧 `detectEmailInputs()`（Fathom 邮箱检测）同样加入可见语义守卫，
  防止 `name="email"` 的精确匹配（权重 9.42）把手机号框误报为邮箱。
- 效果：imooc 真实复测 `fields=[phone, code]`、`blockers=[sms_code]`、
  `primary_method=sms`，与人工观察（+86 手机号 + 短信验证码 + 协议）一致。

### 2. 修复 zhihu（知乎）"注册机构号"被当作普通用户注册入口（2026-08-12）

问题：知乎首页唯一带"注册"文案的链接是"注册机构号"（/org/signup），
CDP 链接发现层（`getLoginLinkAttrs` → `navigate_to_signup`）没有机构注册排除，
signup 测量直接跳到机构注册页并给出 email+password+code 的误分类。
`navigator.detect_entry_button` 已有 `_is_organizational_signup` 排除，
但 CDP 层独立成环，未共享该守卫。

修复：

- `navigate_to_signup()` 与 `ensure_form_visible()` 的 CDP 点击循环中，
  点击前用 `_is_organizational_signup()` 检查解析后的目标 URL，命中即跳过。
- 效果：zhihu 真实复测落在 `/signin`（登录/注册弹窗），识别为
  `sso + phone + wechat`、`human_blocked` 安全停止，不再进入机构注册页。

### 3. 回归测试

- 新增 `tests/test_site_recognition_fixes.py`：14 个用例，
  覆盖可见语义优先规则（imooc 反例、正常邮箱、混合语义、验证码、
  aria-label、type=tel/email）与机构注册排除（zhihu /org/signup、
  带 query、enterprise/register、正常 signup 不被误杀）。
- `PYTHONPATH=. .venv/bin/python -m unittest tests.test_site_recognition_fixes -q` 全通过。

## 其他

- 新增 `scripts/run_classify_diag.py`：只分类不测政策的诊断脚本
  （观察入口发现 → 流程分类 → 页面快照），用于复现与验收识别问题。
- Chromedriver 缓存更新至 151.0.7922.138 并重新签名（macOS 26 签名校验问题）。
