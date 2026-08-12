# CHANGELOG

> 记录本项目从"参赛代码"基线开始的变更历史。
> 原则：每次改动都要在这里加一行记录，包括：日期、改动人、改了哪个文件、为什么改、影响什么。

---

## 变更速查表

| 日期时间 | 改动人 | 内容 | 相关文件 | 推送状态 |
|---|---|---|---|---|
| 2026-08-12 | cjx（Mac） | 修复慕课网手机号字段被误判为 email、知乎机构号注册入口误当普通注册 | signup_flow_classifier/page_detector.py、utils/login_link_discovery.py、utils/js/form_detection_addons.js、tests/test_site_recognition_fixes.py | 未推送 |
| 2026-08-12 | cjx（Mac） | 从旧分支按能力挑选移植：多语言词表、弱结构词防御、容器硬规则、hover 菜单 | signup_flow_classifier/page_detector.py、signup_flow_classifier/navigator.py、signup_flow_classifier/classifier_engine.py、tests/ | 未推送 |
| 2026-08-12 | cjx（Mac） | 批量识别问题修复（36kr 文章误点/视口检查/叶子检查/beian 阻断/百度安全验证/URL 模式预算/JS 容错）+ reports 目录结构调整 | signup_flow_classifier/navigator.py、classifier_engine.py、browser_failures.py、page_detector.py、utils/login_link_discovery.py、scripts/、reports/ | 未推送 |

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

### 4. 从旧分支按能力挑选移植（2026-08-12）

背景：组员的新仓库基于已推送旧代码重构（`utils/signup_flow/` → `signup_flow_classifier/`），
8/8–8/9 的多个修复未包含在内。两个分支历史完全无关，整体 `git merge` 会
产生 13 个 add/add 冲突并造成两套分类器并存，因此改为按能力挑选移植：

1. **多语言词表**（page_detector.py）：`_EMAIL/_PHONE/_PASSWORD/_CODE/_IDENTIFIER_HINTS`
   扩展西/法/德/日/韩/俄；captcha 阻断词（"Verify you're a human" 等 8 种语言）；
   `_NEXT_TEXTS`、`_SEND_CODE_HINTS`、`_SUBMIT_HINTS`、`register_tab` 词表同步扩展。
2. **入口多语言词表**（navigator.py）：`_ENTRY_REGISTER_TEXTS`、`_ENTRY_LOGIN_TEXTS`
   扩展 8 语言；`_entry_text_match` 的 short_hints 同步。
3. **弱结构词防御**（navigator.js 入口打分）：非"登录/注册"文本、仅靠
   user/avatar 等弱结构词命中且位于正文内容区（article/main/card 或视口下半部）
   的元素判为内容卡片不点击（虎嗅作者卡片反例修复）。
4. **容器硬规则**（navigator.js 入口打分）：LI/DIV/SPAN 无 href 容器不能压过
   显式 A/BUTTON（博客园"我的博客" hover 菜单修复）。
5. **hover 菜单能力**（navigator.py + classifier_engine.py）：新增
   `detect_hover_candidate()` + `safe_hover_menu()`；classifier 入口点击前，
   检测到入口是无 href 容器或缺失时先尝试 hover 头部用户/账号菜单展开登录链接。

验证：

- 新增 6 个多语言/入口/hover 回归用例（合计 20/20 通过）。
- 日文入口 fixture `multilingual_japanese_entry.html` 端到端：
  "新規登録" → `direct_password`，密码框可达。
- 真实站复测无回归：imooc `human_blocked / sms`（与移植前一致）；
  zhihu `human_blocked / sso`、停在 `/signin`（与移植前一致）。

注意：本次未移植 `utils/signup_flow/` 整棵旧目录、旧 `testcases/run_*.py` 入口
与 Fathom 兜底差异；若组员需要旧测量入口，再单独评估。

## 其他

- 新增 `scripts/run_classify_diag.py`：只分类不测政策的诊断脚本
  （观察入口发现 → 流程分类 → 页面快照），用于复现与验收识别问题。
- Chromedriver 缓存更新至 151.0.7922.138 并重新签名（macOS 26 签名校验问题）。

### 5. 批量识别问题修复与目录结构调整（2026-08-12）

背景：跑完 60 站后人工核对发现多类识别问题（36kr 跳文章、b站/qq/163/sina 异常、
知乎跳备案查询页、贴吧找不到入口、脉脉卡死等）。逐类定位并修复：

1. **36kr 跳转文章**（navigator.py）：文章标题"公司刚注册…"里的"注册"被
   `strongStructural`（文本匹配）当成认证结构。修复：结构语义只基于属性
   （class/id/href/aria/title/alt），文本匹配只走 explicit 精确匹配。
2. **页脚备案链接误点**（navigator.py）：入口候选加**视口相交检查**，
   页脚/正文底部的"注册"相关链接（href 含 registerSystemInfo）不再当入口。
3. **div>span 按钮误过滤**（navigator.py）：叶子式检查只对"可点击子元素
   （A/BUTTON）文本相同"才跳过；36kr `div.user-login > span(登录)` 不再被误删。
4. **知乎跳 beian.mps.gov.cn**（browser_failures.py）：反爬重定向到公安备案
   查询站识别为 `access_blocked`（URL 主机 + 页面文本双重检测）。
5. **贴吧找不到入口**：百度安全验证整页滑块识别为访问阻断
   （"百度安全验证/请完成下方验证后继续操作"标记）。
6. **脉脉卡死 5 分钟**：URL 模式探测预算 14→3（/signup、/register、/join），
   CDP 链接点击层 25 秒总预算，重试等待 6→3 秒、链接兜底 8→5 秒。
   脉脉从 4:55 降到约 1:09。
7. **b站弹窗被重复点击关闭**（classifier_engine.py）：已有认证状态
   （tabs/blockers/modal）时不重复点入口；`entry_already_clicked` 时保留
   一次兜底点击（弹窗可能已自动关闭）。b站 3 连跑稳定 direct_password。
8. **qq 短信 tab**（page_detector.py）：`_detect_page_semantics` 的 tab 检测
   选择器补 div/span/li；qq 弹窗识别出 sms_tab 并尝试切换（如实记录）。
9. **51cto JS 异常**（login_link_discovery.py）：`detect_email_inputs`/
   `find_password_fields` 对 404 页上的 Fathom JS 异常容错；
   `_cdp_eval` 异常信息带上 JS 描述。
10. **163/sina/qq/b站等**：修复后批量复测 163、sina 达 direct_password，
   与人工一致；qq 默认扫码如实报 human_blocked。

效果（修复前后 60 站对比）：

- 注册 unknown：20 → 8（-60%）
- 注册 direct_password：9 → 13
- 登录 direct_password：29 → 31

目录结构（用户要求）：

- `reports/test/`：测试输出（批量 JSONL、汇总表、单站档案）
- `reports/final/`：真实测量结果（61 站总表 + 单站档案 + 合并 JSONL）
- 每测一个新网站 → 先在 test/ 生成，核对后并入 final/。

验证：回归测试 24/24 通过；修复站 3 连跑稳定；61 站 final 档案已生成。

### 6. 新 60 站清单 + 页脚备案链接误点修复（2026-08-12）

- 新增 `misc/cn_sites_new60.txt`：60 个未测过的国内网站，覆盖搜索/门户
  （百度、人民网、新华网、央视网）、视频/音乐（抖音、快手、小红书、AcFun、
  网易云、QQ音乐、酷狗）、社区（V2EX、酷安、吾爱破解、即刻、看雪）、
  财经（东方财富、同花顺）、生活（大众点评、饿了么、携程、同程、飞猪、
  12306、高德）、电商（得物、闲鱼、转转、网易严选）、办公云（钉钉、飞书、
  企业微信、阿里云、腾讯云、华为云、百度网盘）、游戏（TapTap、游民星空）、
  招聘（猎聘）、医疗（丁香园）等。与老 60 站去重校验通过。
- 修复抖音首页误点页脚备案链接（CDP 链接发现把"京公网安备"当注册入口，
  导航到 /jingxuan 视频页）：`navigate_to_signup` CDP 点击层与
  `navigator._mark_entry_in_current_context` JS 都排除备案/版权链接
  （文本含"备案/公网安备"或 href 含 beian/mps.gov.cn/beian.gov.cn）。
  修复后抖音登录弹窗识别完整（signup=human_blocked 手机号+验证码，
  login=direct_password）。
- 结果：新 60 站 120 条记录（登录 direct_password 24、注册 direct_password 12、
  注册 verification_then_password 1）；music.163.com 偶发渲染超时已单独复测。
- 合并后 `reports/final/` 共 121 站（老 60 + 新 60 + 慕课）244 条记录。
