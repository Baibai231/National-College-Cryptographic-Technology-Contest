# CHANGELOG

> 记录本项目从"参赛代码"基线开始的变更历史。
> 原则：每次改动都要在这里加一行记录，包括：日期、改动人、改了哪个文件、为什么改、影响什么。

---

## 变更速查表

| 日期时间 | 改动人 | 内容 | 相关文件 | 推送状态 |
|---|---|---|---|---|
| 2026-08-14 | Codex（Mac） | 保持 v3：修正扫码登录语义与第三方登录识别，新增两轮全量回归对比，并为网站正确/错误判断补充可读依据 | signup_flow_classifier/、scripts/run_measurement.py、scripts/compare_measurement_rounds.py、webapp/、tests/、reports/ | 本次提交 |
| 2026-08-12 | cjx（Mac） | 修复慕课网手机号字段被误判为 email、知乎机构号注册入口误当普通注册 | signup_flow_classifier/page_detector.py、utils/login_link_discovery.py、utils/js/form_detection_addons.js、tests/test_site_recognition_fixes.py | 未推送 |
| 2026-08-12 | cjx（Mac） | 从旧分支按能力挑选移植：多语言词表、弱结构词防御、容器硬规则、hover 菜单 | signup_flow_classifier/page_detector.py、signup_flow_classifier/navigator.py、signup_flow_classifier/classifier_engine.py、tests/ | 未推送 |
| 2026-08-12 | cjx（Mac） | 批量识别问题修复（36kr 文章误点/视口检查/叶子检查/beian 阻断/百度安全验证/URL 模式预算/JS 容错）+ reports 目录结构调整 | signup_flow_classifier/navigator.py、classifier_engine.py、browser_failures.py、page_detector.py、utils/login_link_discovery.py、scripts/、reports/ | 未推送 |

---

## 实现细节

### 6. 扫码语义、第三方登录与报告解释（2026-08-14）

- 扫码与表单可以同时存在：二维码记录为 `methods=qr`；只有页面确实没有可用字段时，
  才把 `scan` 作为阻断原因，避免“有手机号/密码框却被扫码阻断”的误判。
- 扩展图标按钮和常见第三方提供方识别，并排除站点自身品牌被误当第三方登录；
  同时识别“登录即注册”语义及更完整的短信验证码文案。
- 批量脚本支持合并多份站点清单、去重与显式覆盖输出；增加两轮结果的逐入口语义对比。
- 报告后端改用逐字段人工/程序对照；匹配项展示“为什么正确”，不匹配项展示
  程序识别与人工记录的具体差异，不再把人工未知项算作正确。
- 版本号继续为 `v3`，没有升级为 v4。

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

### 7. 注册识别核心修复（2026-08-12，前 40 站人工复核反馈）

组员人工复核前 40 站后反馈三类问题，全部定位并修复：

1. **登录界面密码框被误当注册证据**（shimo/51cto/百度/B站/caixin/dongchedi
   等"仅登录"站）：`classify()` 的 signup 流程从不点击登录弹窗里的
   "立即注册"tab，且密码框出现时不检查是否真正进入注册视图。
   - 修复：signup 模式检测到 `register_tab` 时优先点击（百度/pan.baidu/
     贴吧等登录弹窗藏注册按钮的站实测）；
   - 密码框判断加"注册上下文"守卫：signup 模式必须点过注册入口/注册 tab
     或 URL 明确是注册页，密码框才算注册密码框；
   - 最终分类加"仅登录界面"守卫：全程没确认注册上下文时即使有密码框
     也报 `no_signup_entry`（shimo.im 实测：从误报 direct_password 改为
     正确 no_signup_entry）。
   - 修正 `entry_already_clicked` 语义：navigate_to_signup 点击的可能是
     登录按钮（百度等只有登录的站），不再无条件把 signup_entry_clicked
     置 True，由 classify 自行确认注册上下文。

2. **登录界面藏注册按钮没找到**（pan.baidu/tieba/10jqka/acfun/cctv/china）：
   登录弹窗里的"立即注册/注册账号"tab 存在但从没被点击。
   - 修复同上（register_tab 优先点击）。实测 acfun→direct_password（注册
     有密码）、10jqka→verification_then_password（先手机验证后密码）、
     cctv→no_signup_entry（仅登录）均正确。

3. **扫码下载被误当登录/注册**（coolapk/dewu）：scan 词表含"扫码下载"，
   首页"手机扫码下载App"被当成扫码登录阻断。
   - 修复：从 scan 词表移除"扫码下载"（下载引导不是认证），保留
     "扫码登录/扫码注册"等认证语境词。

4. 附：amap/dingtalk 的手机号+验证码方式检测确认正确（fields=phone+code，
   sms_code 阻断），此前误报为扫码是旧记录，重跑后更新。

验证：10 站回归（36kr/163/sina/bilibili/cnblogs/jianshu/gitee/douban/
weibo/csdn）分类与修复前一致；回归测试 26/26 通过。

### 8. 注册识别第三轮修复（2026-08-13，81-100 站人工复核 + 前 40 站复核补充）

组员复核 81-100 站 + 前 40 站补充反馈，修复：

1. **社交关注二维码误判第三方登录**（meituan）：sso 检测对纯展示性
   div/span（无 href 无 onclick，"下载和关注"区的微信/微博二维码）
   不再判定为第三方登录；只认可点击元素（A/BUTTON/role=button/onclick）。
   实测 meituan：sso_only → unknown（无登录界面，与人工一致）。

2. **登录页藏注册链接但点击不导航**（people/cctv）：注册 tab 是链接型
   （<a href="/u/reg">）时，优先直接导航 href（register_href_nav 兜底），
   不再依赖点击。实测 people：no_signup_entry → direct_password
   （手机号+验证码+密码注册，人工确认正确）。

3. **纯 div 登录按钮被过滤**（thepaper）：explicit 精确匹配的"登录"文本
   div（cursor:auto 无 onclick，React 事件绑上层）不再要求 nativeInteractive。
   实测 thepaper：登录弹窗可识别（手机号+密码+sms_code 阻断）。

4. **第三方提供商词表扩展**：新增 gitee/支付宝/淘宝/小米/华为；
   QQ 增加裸词匹配。实测 oschina 识别出 gitee 第三方登录。

5. **扫码下载误判**（coolapk/dewu，承接上一轮）：确认从 scan 词表移除
   "扫码下载"后两站均正确报 unknown（无登录注册表单）。

81-100 站核验结果：meituan/mgtv/miguvideo/nbd/pinduoduo/qunar/taptap/
thepaper 等"无表单/仅验证码/人机验证"站均如实分类；people/cctv 注册
识别修复；oschina 补上 gitee 第三方。剩余差异主要是"第三方图标按钮无
文字"类（部分站第三方只有图标），以及 qyer 等"密码框可见但验证码在
前置步骤"的保守分类（不填字段的安全边界内）。

回归：10 站无退化；回归测试 26/26 通过。

### 9. 41-80 站复核 + 100 站回归（2026-08-13）

组员复核 41-80 站（全部标注"正确"），程序输出与人工基本吻合。
针对回归中发现的普世问题修复：

1. **短信 tab 无条件优先点击**（kuaishou）：弹窗默认短信/手机号登录视图时，
   无论是否有阻断都先点 sms_tab 打开字段（不限于阻断场景）。
   实测快手：sso_only → otp_only（手机号+验证码，人工确认）。

2. **注册入口点击无变化时不算进入注册上下文**（10jqka）：登录弹窗点
   "注册"入口 changed=False 时不再置 signup_entry_clicked，否则 register_tab
   会被跳过。实测同花顺恢复 verification_then_password（先手机验证后密码）。

3. **sso 检测加认证上下文限制**（eastmoney/meituan）：首页无弹窗/字段/
   认证 URL 时，"关注微博/微信"分享链接（外部 href）不再误判第三方登录。
   实测东方财富：sso_only → unknown（首页无认证界面）；弹窗内的第三方
   （oschina gitee 等）照常识别。

4. **机构注册排除扩展**（zol）：主机含 dealer/merchant/business/enterprise
   的注册页视为机构入驻（zol 的 dealer.zol.com.cn 经销商注册实测），
   不再冒充普通用户注册。

5. 前 100 站（老60+新60前40）完整回归：200 条记录零失败（含之前偶发
   超时的 music.163）。分类变化逐条核验：10jqka 修复、eastmoney/meituan
   sso 误判修复为正向；jianshu/36kr 的 human_blocked 波动为风控随机
   （简书滑块反爬时有时无），非代码退化。

验证：回归测试 26/26 通过；final 更新至 122 站档案；
test/ 新增 cn100_regression_20260813.jsonl（100 站回归快照）。

### 10. 101-121 站复核 + tab 分词 + 全量 121 站对比（2026-08-13）

组员复核 101-121 站反馈，修复与验证：

1. **tab 检测与点击分词匹配**（zol 等）：一个元素含多个 tab 名
   （"短信登录 帐号登录"合并文本）的站，detect_tabs 与 safe_click_tab
   都支持包含匹配（≤12 字短文本）。
2. **safe_click_tab 可见性判定改为 getBoundingClientRect**（快手等）：
   offsetParent 在部分 SPA 为 null 但元素可见可点（快手登录弹窗实测）。
3. **sms_tab 点击失败时短等重试**：tab 元素刚渲染时 safe_click_tab
   可能找不到，等一轮观察字段/tab 出现。

121 站程序 vs 人工对比（注册侧，41 个人工复核站）：

- 实质一致 36/41（meituan/nbd/qunar/zhuanzhuan/xinhuanet 无界面、
  smzdm/taobao/sohu 仅验证码、xiachufang 仅扫码、v2ex 仅第三方、
  thepaper 仅手机验证码等均一致）。
- 表达差异 5 站（qyer/sina/pcauto/people/vip）：程序与人工都承认
  密码框存在，差异在验证码位置的表述粒度；安全边界内（不填手机号）
  无法进一步区分验证码前置。
- 无程序把事实搞错的站。

已确认的波动站（风控随机，非代码问题）：kuaishou（登录弹窗时开时
不开）、jianshu/36kr（滑块反爬时有时无）、music.163（渲染超时偶发）。

已知边界（不跨域安全设计）：y.qq/you.163 注册藏在跨域跳转
（QQ登录/网易邮箱）里，工具不跟随跨域，如实报阻断/仅验证码。

验证：回归测试 26/26；10 站回归无退化；121 站完整跑通（music.163
偶发超时除外）。

### 11. 波动站攻坚 + 协议处理 + 空壳注册页回退 + 30 新站 + 4 轮全量回归（2026-08-13）

**波动站攻坚**（各跑 3 次验证）：
- kuaishou：登录弹窗对自动化风控（3 次全 unknown，new-reco 页面无弹窗）
- jianshu：稳定（3 次 direct_password）
- 36kr：弹窗时开时不开（otp_only/unknown 交替）→ 人工修正为 otp_only
- music.163：渲染超时偶发（human_blocked/error 交替）→ 取 human_blocked

**安全边界站结论**（y.qq/you.163）：注册藏在跨域 OAuth/账号中心（QQ 登录
授权页、网易邮箱注册）中，工具不跟随跨域 = 安全设计，如实报阻断/仅验证码。

**结构难点站**：
- mgtv：新增**协议弹窗处理**（安全点击"我同意"进入主界面，普世能力），
  实测 mgtv 协议点击成功进入主界面（登录入口是 icon-only 后续难点）
- zol：tab 合并文本分词匹配已实现；点击仍不稳定（单元素含多 tab 名），
  如实 unknown
- 协议处理只在页面无认证状态时触发，且要求协议上下文（class/相邻文本），
  避免误点普通页面文字；回归验证无退化。

**ActionChains 入口点击**（juejin/leetcode 等 React hover 弹窗）：原生
click 后弹窗不保持，改用真实鼠标事件点击（无退化，稳定站回归正常）。

**空壳注册页回退**（ximalaya/chinaacc）：navigate 到的 signup URL 页面
无任何认证内容时，回退站首页重新找真实入口。实测喜马拉雅从 unknown
→ human_blocked（扫码登录弹窗）。

**30 个新中文站**（misc/cn_sites_new30.txt）：360/3dmgame/51/7k7k/
58pic/cctalk/chinaacc/cyzone/guazi/hujiang/jiguang/mingdao/ximalaya 等，
60 条记录零失败。自测核验：360/3dmgame/51/7k7k direct_password（有密码
注册）✓，jiguang email_only ✓，cyzone verification_then_password ✓，
58pic 有手机号+第三方（sso_only 不完整但方向对），ximalaya/chinaacc
空壳已修复。

**4 轮全量回归**（120 站，共 4 轮 960 条）：232/240 四轮稳定（97%），
8 条波动集中在 5 个风控站（36kr/52pojie/dianping/eastmoney/jd/zhipin）。
多数投票 + 人工修正取最终结果。

验证：回归测试 26/26；final 更新至 152 站档案（153 站点）。

### 12. 注册流程测量平台 Web 前端（2026-08-13）

新增 webapp/ 前端平台，供团队访问已测网站的注册流程：

- **数据层**：`scripts/build_site_database.py` 把 final JSONL + 人工复核
  （misc/manual_review.json，81 站已录入）合并为 SQLite（152 站）。
- **后端**：`webapp/app.py`（FastAPI）
  - GET /api/sites?q= 搜索；GET /api/sites/{host} 详情；
  - GET /api/stats 统计；POST /api/classify 实时分类（复用测量工具）。
- **前端**：`webapp/static/index.html`（Bootstrap 单页）
  - 搜索框 + 站点卡片列表（程序分类 + 人工核验徽标）；
  - 详情弹窗（登录/注册类型、路线、字段、阻断、步骤证据、人工对照）；
  - URL 分类输入框（输入网站主页 → 现场分类，安全只读）。
- **部署**：`webapp/run_server.sh` 一键启动（默认 8000 端口，0.0.0.0
  监听，服务器部署后组员经 http://IP:8000 访问）。
- 本地全链路验证通过：页面、搜索、详情、实时分类（知乎→人工阻断）。

### 13. 平台功能升级：关键词搜索 + 人工提交 + 口令政策预留 + 部署方案（2026-08-13）

按用户反馈升级 Web 平台：

1. **中文关键词搜索**（`misc/site_keywords.json`）：120+ 域名 → 中文名/
   别名映射（慕课→imooc、知乎、京东等），搜索"慕课"能命中 www.imooc.com。
2. **详情弹窗修复**：补 bootstrap bundle JS，【登录步骤】【注册步骤】tab
   正常切换显示。
3. **首页显示全部站点**：limit 50 → 1000，加"全部/已核验/待核验"筛选。
4. **去 emoji/AI 味**：标题、按钮文案改为朴素表述。
5. **组员提交人工观察**：
   - 前端"提交人工观察"按钮（登录/注册/备注/姓名）
   - POST /api/reviews 写入待审核表；GET /api/reviews/pending 查看；
     DELETE /api/reviews/{id} 核验后删除
   - `scripts/merge_reviews.py`：核验后合并进 manual_review.json → 重建
     数据库 → 重启服务，形成完整协作闭环。
6. **口令政策预留**：数据库 details_json 存 login_policy/signup_policy，
   详情页新增"口令政策"行（后续 TestPassword 测量结果直接展示）。
7. **服务器部署**（`webapp/DEPLOY.md`）：云服务器方案（Ubuntu + Chrome
   + systemd 自启 + 可选 Nginx）；`SITES_HEADLESS=1` 环境变量启用无头
   Chrome（服务器无显示器环境）。

验证：搜索（慕课/知乎/京东）、详情（policy）、提交/查看/删除审核、
首页渲染全部通过；回归测试 26/26。

## 版本更新流程约定（重要，2026-08-14 起生效）

每次修改**注册分类相关逻辑**（大版本）后，**必须重跑全部站点并更新数据**，否则网站显示的是旧代码测的结果：

```bash
# 1. 升版本号（大改动才升，小修复不用）
echo "v4" > misc/measure_version.txt

# 2. 重跑全部站点（150站约40分钟）
.venv/bin/python scripts/run_measurement.py \
  --input misc/sites_base_60.txt --input misc/sites_extra_60.txt --input misc/sites_new_30.txt \
  --output reports/sites/sites_latest.jsonl --workers 3

# 3. 重建数据库 + 提交
.venv/bin/python scripts/build_site_database.py
git add -A && git commit -m "data: v4 全量重测" && git push

# 4. 服务器自动/手动同步（webapp/server_sync.sh 或 git pull + build + restart）
```

判断标准：
- **大版本**：分类逻辑重构、新增流程类型、字段语义变化 → 升版本 + 全量重跑
- **小修复**：误判修复、等待时序、网络容错 → 不升版本，只重跑受影响的站

注意：重跑结果写入 `reports/sites/sites_latest.jsonl`（覆盖），旧版本结果在网站"历史结果"里可查。
