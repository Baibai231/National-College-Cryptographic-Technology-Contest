# CHANGELOG

> 记录本项目从"参赛代码"基线开始的变更历史。
> 原则：每次改动都要在这里加一行记录，包括：日期、改动人、改了哪个文件、为什么改、影响什么。

---

## v4 进行中（2026-08-15）

### 61. Windows 本地一键展示与历史口令策略入库（2026-09-10）

- [x] 新增 `webapp/run_local.ps1`：首次运行自动建立 `.venv`、安装缺失依赖，
      重建数据库后在 `127.0.0.1` 启动最新版 Dashboard，并支持安全停止、端口、
      固定测量令牌和不自动开浏览器等选项。
- [x] Windows 虚拟环境可能由启动器派生实际 Python 进程；新增本地服务包装器，
      由真正监听端口的进程写入结构化 PID 记录。停止前校验项目根目录、解释器路径
      和启动时间，避免残留旧服务或误停同机其他 Python 任务。
- [x] 本地数据库自动合并最新版认证流程数据与最近一次全量 policy 测量档案，
      无需手工拼接输入文件。
- [x] 旧 SQLite 记录只在源文件中不存在时补回；用规范化完整记录去重，使反复执行
      本地更新不会为每个站点重复追加同一批历史候选。
- [x] 兼容历史批量结果中的 `policy + method_used` 结构，将实测规则映射为
      `pwd_policy + pwd_method`；通过字段结构区分流程分类政策，避免类型混淆。
- [x] 修复首次打开 Dashboard、尚未填写测量令牌时任务区误报“口令错误”；改为
      明确提示填写令牌，清空令牌时停止无意义的任务轮询。
- [x] 增加本地 PID 生命周期、旧格式策略映射、分类政策隔离和空令牌界面回归检查；
      完整 235 项测试、
      Python 编译、PowerShell 语法、API 与浏览器展示验证通过。

### 60. 状态图去重、测量现场交接与现代长度覆盖（2026-09-10）

- [x] 为认证页面建立隐私保护的语义状态键：保留认证路由参数，丢弃 nonce、Token、
      跟踪参数和 fragment；重复状态不再膨胀路线与置信度，并记录显式 revisit 证据。
- [x] 增加“语义状态—安全动作”边去重，已经在同一视图尝试过的 tab 动作不会重复
      执行；全局分支覆盖仍保留，减少短信/密码/邮箱视图之间的振荡。
- [x] 分类器新增现场口令目标接口（XPath + iframe path）。主流程直接把同一
      WebDriver 中的活目标交给 inline 测量器，不再无条件重开 SPA 模态框；确需
      重定位时保留原始全分支分类、方法和证据，不被短重走结果覆盖。
- [x] 合法口令候选生成抽成共享模块；inline/full-form 都按常见长度边界优先、
      随后补齐全部长度，默认由原先 full-form 的 12 位上限扩展到 64 位，同时保留
      120 秒探测预算和 full-form 显式授权门槛。
- [x] 新增 7 项回归测试，覆盖状态去重、查询路由区分、64 位候选、16 位最低长度、
      SPA/iframe 现场直接交接及重定位证据保持；全量 229 项测试和编译检查通过。

### 59. 项目总览文档与 CMP 配置一致性（2026-09-09）

- [x] 新增仓库根目录 README，统一说明认证流程分类、智能字段识别、口令策略测量、
      被动密码技术观察、证据评分、批量任务、Web API、安全边界、安装与使用方法。
- [x] 汇总本轮 6 个开发提交修复的缺陷、新增功能、输出解释和已知限制，便于参赛展示、
      部署交接及后续研究复现。
- [x] 修复 `--no-cmp` 只修改显示状态、不能关闭新横幅处理的问题；CMP 默认配置从
      `ACCEPT_ALL` 收敛为 `REJECT_ALL`，使配置、代码和文档保持一致。
- [x] 完整 222 项回归测试、Python 编译检查及 CLI 帮助命令验证通过。

### 58. Cookie/GDPR 遮罩安全处理（2026-09-09）

- [x] 分类前自动扫描主文档及可见嵌套 iframe 中的 Cookie/CMP 横幅，避免遮罩
      阻挡页头登录、注册入口，提升海外网站可达率。
- [x] 仅允许“仅必要 Cookie”“全部拒绝”或明确 Cookie 容器中的关闭动作，按
      隐私保护顺序选择；永不点击“全部接受”、保存偏好、用户协议或表单提交。
- [x] 支持中、英、法、德、西、意、葡、荷、日、韩、俄常见拒绝文案，操作结果
      写入测量证据；普通协议弹窗的同名关闭按钮不会被误点。
- [x] 新增标签白名单、接受动作反例和交互边界测试；完整 221 项回归测试通过。

### 57. 非标准认证字段语义识别（2026-09-09）

- [x] 字段分类增加 `autocomplete`、`inputmode`、浏览器可访问名称、
      `aria-labelledby` 与关联 `<label>` 语义，覆盖组件库生成及视觉上无
      placeholder 的注册表单。
- [x] `one-time-code` 和验证码文案优先于 `type=tel`，避免把数字键盘型 OTP
      控件误判为手机号；搜索、按钮、文件等非认证 input 类型不再进入候选集。
- [x] 口令框定位支持 `autocomplete=new-password/current-password`，并安全编码
      XPath 属性值，使识别到的兼容型口令控件能够实际进入后续政策探测。
- [x] 开放 Shadow DOM、同源 iframe 与跨域 iframe 上下文统一使用上述语义；
      嵌入 JavaScript 语法检查和 216 项 Python 回归测试全部通过。

### 56. 账户恢复能力被动观察（2026-09-09）

- [x] 增加忘记密码、重置密码和账户恢复入口的只读观察，仅记录能力、位置和
      脱敏证据，不点击入口、不发送验证码、不获取或保存恢复令牌。
- [x] 页面快照有界遍历开放 Shadow DOM 与同源 iframe；网页详情同步展示恢复
      入口及证据边界，缺少证据时保持未知而非推断为不支持。

### 55. CPAM 证据成熟度阶梯（2026-09-09）

- [x] 增加 Level 0--6 的证据约束成熟度输出，区分“连续证据支持等级”和
      “观察到的更高能力”，防止证据断层造成跨级结论。
- [x] 不从页面外观推断服务端口令存储、强制 MFA、风险认证或零信任；网页展示
      当前等级、最高观察能力、缺失证据及解释。

### 54. 跨上下文认证覆盖与重试语义（2026-09-09）

- [x] 字段和页面语义聚合不再因主文档先发现输入框或阻断而提前返回，覆盖开放
      Shadow DOM、同源 iframe、跨域可见 iframe 及嵌套 frame。
- [x] SPA 变化指纹加入 Shadow DOM、同源 iframe、ARIA 展开/选中状态，并监视
      已切入的跨域认证 frame，提升组件化登录/注册弹窗的状态识别率。
- [x] 批量测量只重试瞬态浏览器/导航失败，保留原始 URL、路径和站点总超时，
      不对确定性的人机验证或无注册入口反复执行。

### 53. 证据覆盖率与可解释分维度评估（2026-09-09）

- [x] 增加口令策略、认证机制、会话 Cookie、传输安全和 HTTP 安全响应头五维评估，
      输出每维得分、覆盖率、已知项表现、证据、发现和改进建议。
- [x] 未知项从得分分母排除并降低覆盖率；加权覆盖率不足 70% 时不输出等级，避免把
      低覆盖高分误解为网站整体安全。
- [x] 口令策略只在可信 inline/full 实测后加入评估；分类、失败探针、MFA 并列方式及
      登录前 Cookie 不冒充已验证安全结论。
- [x] 网页增加五维评分表、已观察风险等级和中文建议，并明确不同覆盖率分数不可直接比较。

### 52. TLS 与 HTTP 安全配置被动观察（2026-09-09）

- [x] 复用 Chrome 现有页面导航的 performance/network 事件，增加最终协议、
      HTTP→HTTPS 跳转、HTTP 协议、TLS 版本/密码套件及证书有效期聚合分析；不为
      测量另发网络请求。
- [x] 增加 HSTS、CSP、nosniff、防嵌套、Referrer-Policy、Permissions-Policy、
      跨源隔离及缓存响应头观察；不保存 URL、查询参数、证书或原始 Header 值。
- [x] 缺少主文档响应证据时返回 `not_observed`，不把采集不可用误判为响应头缺失；
      网页结果区同步展示传输、证书、安全响应头和中文复核提示。

### 51. CryptoScope 被动密码技术观察器（2026-09-09）

- [x] 增加统一 `security_observations` 证据包，接入分类器、口令测量、批量 JSONL、
      SQLite 重建、异步任务和网页入库链路，不改变现有 flow/policy schema 语义。
- [x] 增加 OAuth/OIDC 参数存在性、JWT 脱敏元数据、WebAuthn/Passkey 页面能力、
      MFA 因素能力和会话 Cookie 属性观察器；全程不跟随授权、不登录、不发验证码。
- [x] Token、Cookie 值和 OAuth 参数值不落盘；MFA 并列方式不冒充强制多因素认证，
      WebAuthn 浏览器 API 可用也不冒充网站支持。
- [x] 网页详情及任务结果增加“安全能力被动观察”区，并明确显示认证前证据边界。

### 50. 口令推断正确性与公开任务接口加固（2026-09-09）

- [x] 修正泄露口令拦截结论的反向赋值，并增加“全部拒绝/存在接受”两类回归测试。
- [x] full-form 长度探针按已识别的字符组成、字母开头和分隔词约束生成候选，避免把
      组成规则误判成长度边界。
- [x] 移除运行时未使用的 pandas 依赖，修正服务器安装命令、SQLite 文件句柄释放、
      Windows 非 UTF-8 控制台输出和测试数据路径隔离。
- [x] 浏览器测量及任务接口增加 `X-Measure-Token` 鉴权；CORS 改为显式来源白名单；
      异步等待队列增加可配置上限；提交与执行前均复检 DNS 并拒绝内网/保留地址。
- [x] 删除或超时的运行中任务不再被后台结果“复活”，跳过该结果时也不再误退出
      长驻 worker 线程。
- [x] 部署文档补充测量口令、队列容量、跨域白名单和网络隔离要求。

### 49. 网页现场测量支持重复测试（2026-09-06）

- [x] 在现场分类区增加“重复测试（忽略数据库，重新打开网站测量）”开关；
      默认不勾选时保持原有缓存行为，勾选后任务列表和结果详情均显示重复测试标记。
- [x] 异步任务接口新增向后兼容的 `force_retest` 布尔字段；注册+登录分类会跳过
      两侧已有数据，口令政策会跳过已有政策，统一重新进入现场测量流程。
- [x] 重复测试结果仍只保存在任务中，不自动修改 `reports/`、`misc/` 或正式数据库；
      只有用户主动点击“加入数据库”并通过管理员口令后才会覆盖对应网站数据。
- [x] 新增后端缓存旁路和前端开关测试；保持 v4，不改分类/口令算法和数据 schema。

### 15. 口令政策测量可信度与安全边界收敛（2026-08-24，进行中）

背景：网页接入口令政策测量后，GitHub 等站点出现互相矛盾的规则；审查确认
inline 路径仍将“未观察到拒绝”直接当作接受，同时 `auto` 在无 inline 反馈时会
进入 full-form 提交，偏离“不填身份、不提交、不创建账号”的安全边界。

本轮约束：
- 版本继续使用 `v4`，不新增版本号；`reports/`、`misc/` 权威数据格式保持不变。
- `auto` 只允许安全 inline 探测；无可靠反馈必须返回无法判断并回退分类。
- full-form 默认关闭，只有显式授权且精确主机白名单命中时才允许进入。
- 用负对照建立当前表单确实会反馈的证据；没有证据时不得推断候选密码被接受。
- 修改后单独复核 GitHub 口令政策，并执行两轮全量回归、比较差异。

进度：
- [x] 审查最新远程执行链、现有测试、HANDOFF 安全边界和组员提交。
- [x] 收紧 `auto` / full-form 安全门：`auto` 无 inline 反馈时返回
      `inline_unsupported` 并回退分类；显式 `full` 也必须同时满足环境开关和
      精确 hostname 白名单，公开网页默认无法触发表单提交；inline 探测删除邮箱
      填写，只允许操作密码框，身份门控站点直接判为无法判断。
- [x] 引入接受/拒绝/无法判断证据状态与负对照：`TestPassword` 保存每次候选的
      `accepted/rejected/inconclusive` 及证据；一字符负对照未明确拒绝时整次政策
      测量停止并回退分类，“无拒绝”只有在同表单负对照成立后才可作差分接受。
- [x] 保守修复候选池、缓存和单变量探测：8–32 位每个长度覆盖二/三/四类字符，
      不再依赖错误文案才尝试大写/符号；缓存密码每轮重新验证；特殊符号探测改为
      等长替换，避免“加符号”和“超过最大长度”混淆。最大长度未知继续使用已验证
      基准长度，不向后续阶段传播 `None`。
- [x] 补充回归测试、整理诊断脚本并更新交接文档：6 个百度/学堂在线/
      游民星空诊断脚本迁入 `tools/diagnostics/`；补充安全说明；HANDOFF 顶部增加
      2026-08-24 增量，`reports/README.md` 修正为当前 v4、154 站、307 条。
  - 当前自动测试：149 项全部通过（新增安全门、负对照、分层候选、full-form
    默认惰性测试）；Python 编译检查通过。
- [x] GitHub 安全实测与两轮全量回归对比。
  - 已由第 16 条修复解决：入口定位/异步校验瞬态/限流识别修复后，GitHub
    口令政策可安全测得（长度 [8,72]），不再需要授权人工样本。

### 16. 注册入口定位 / 异步校验瞬态 / 14步逻辑缺陷修复（2026-08-27）

背景：组员反馈三个问题（注册入口定位不稳、14 站复测不稳、14 步逻辑策略
缺陷），且 GitHub 口令测量出现长度 [25,51]/[32,25] 等互相矛盾的垃圾值。

根因（三问题同源）：
1. `tryClickAndDetect` 用 `el.click()` 触发导航时 JS 执行上下文立即销毁，
   `result.clicked=true` 来不及执行，CDP awaitPromise 超时 → 所有注册链接
   被判"未找到或不可见"（入口定位 50%+ 失败）。
2. GitHub 等站点的异步服务端校验瞬态（validationMessage="Verifying…"/
   "Validation failed"）被 observer/field-state 误判为拒绝 → 8 位合法密码
   大部分被拒 → admissible 被迫凑成 25+ 位、长度下界测成 25。
3. 导航后 React 渲染慢（>5s）时分类器第一步就误判"无密码框"；GitHub 429
   限流页被误报"无注册入口"。
4. 14 步串行逻辑缺陷：组合测试先于长度（缺陷3）、admissible 找不到时返回
   全 False 空政策（缺陷1/6 错误传导）、check_special_symbols 无冗余字符时
   把 INCONCLUSIVE 误报为"允许符号"（缺陷2 符号鸡生蛋）、OR 规则（GitHub
   "≥15位 或 ≥8位含数字+小写"）超出模型表达力却静默输出失真结论（缺陷5）。

修复：
- [x] `form_detection_addons.js`：clicked 标记前置（导航销毁上下文不再丢结果）；
      HTML5 校验瞬态 "Verifying…" 返回无反馈等待稳定。
- [x] `login_link_discovery.py`：CDP 异常/clicked=false 时用 `current_url`
      兜底判导航成功。
- [x] `classifier_engine.py`：classify 主循环前增加 `_wait_for_any_auth_signal`
      （慢渲染站点不再误判无密码框）。
- [x] `browser_failures.py`：新增限流检测（too many requests → access_blocked）。
- [x] `util_test_password.py`：
      - field-state 路径对 "Verifying…"/"Validation failed" 标记 pending 继续
        轮询（不立即判拒绝）；
      - 轮询结束后最终复验（仅字段完全干净——无 error class/红边框且 valid——
        才改判接受，保护百度/gitee 自定义校验站，其轮询结束时 valid 可能为
        true 但红边框常驻，绝不能改判）；
      - 字段值被站点清空/改写 → 拒收信号（field_value_cleared_by_site），
        不再一律 inconclusive；
      - 负对照/基准"相位控制点"扩展：长度前、组合前、permissive 前各一次。
- [x] `site_agnostic_tester.py`：
      - 长度测试前置到组合测试之前（缺陷3），组合阶段独立控制点；
      - admissible 未找到时显式标记 `_inconclusive`（缺陷1/6），不再返回
        全 False 空政策；
      - 新增自洽校验 `self_consistency_check`：最小长度单类密码反推模型一致
        性，OR 规则被检测为 `or_rule_likely` 并标记 inconclusive（缺陷5），
        不再静默输出失真的 r_cmb14 结论。
- [x] `check_special_symbols` 无冗余字符时用"位置0替换@ + 同类对照"双探针
      消歧（缺陷2），不再把 INCONCLUSIVE 误报为允许符号。
- [x] `main.py`：`_policy_is_usable` 对 `or_rule_likely` 保留政策（长度等已测
      维度可信，inconclusive 标记随输出），其他 inconclusive 仍回退分类。

验证：
- GitHub：入口定位稳定成功；负对照成立；长度 [8,72]；8 位纯数字被拒
  （"Password needs a number and lowercase letter"）→ 自洽校验判
  `or_rule_likely` 并标记 inconclusive（诚实报告，不再输出失真的组合结论）。
- 百度：[8,14] + r_dig_min=1 + r_cmb34，自洽校验 consistent。
- gitee：[8,102]，自洽校验 consistent，负对照成立。
- 自动测试：149 项全部通过。

### 17. OR 规则刻画 + 突变步骤中间控制点（2026-08-27）

第 16 条把 OR 规则（GitHub "≥15 位 或 ≥8 位含数字+小写"）标记为
or_rule_likely 并 inconclusive，但没有探测规则本身。本条把 OR 规则从
"标记不可信"升级为"可刻画输出"：

- [x] `identify_or_rule`：自洽校验发现 OR 规则后，有界探测（5~7 个探针）
      - 最小长度下各单类（lower/upper/digit）是否足够；
      - 两两组合（lower+upper / lower+digit / upper+digit）哪些被接受；
      - 长度替代分支：单类密码从 lo+2 向上探测，找到"单类即可"的长度阈值。
      输出结构化 `_or_rule`（min_length / single_class_rejected /
      single_class_accepted / pair_classes / length_alternative）。
- [x] `site_agnostic_tester.py`：`self_consistency_check` 返回
      (ok, note, or_rule)，or_rule 随政策输出，消费方可看到已探测的真实行为。
- [x] P3 缺陷4（副作用隔离）：7 个连续突变步骤间插入两个中间控制点
      （r_l_start 后、r_dig_min 后），负对照/基准任一漂移即停止推断，
      避免后续步骤在污染状态下测出垃圾值。
- [x] 测试适配三返回值并新增断言（min_length / or_rule 结构）。

验证：156 项测试全部通过（新增 OR 刻画断言）。

### 18. 注册链接空壳页回退 + 14 站无头复测（2026-08-27）

背景：无头模式下 GitHub 首页"Sign up"链接不可见，先点到 MCP Registry 的
同名链接 → /mcp 空壳页被当注册页返回，分类误判 no_web_signup。

修复：
- [x] `_page_has_auth_signal`：导航到新 URL 后验证含认证 input
      （password/email/tel）或 URL 注册路径；不能用页面上任意
      "Sign up/登录" 链接文本当信号（GitHub 全站 header 常驻 Sign up）。
- [x] navigated / clicked=false 分支：URL 规范化比较（去尾斜杠/query），
      点击后仍在首页不再误判为导航成功。
- [x] `_wait_for_spa_render` / `_page_has_auth_signal` 的 JS 顶层 return
      语法错误（Runtime.evaluate 顶层 return 非法，被 except 保守放行，
      导致 SPA 等待永远"超时"、认证信号永远误判 True），包 IIFE 修复。

14 站无头复测（取 cn50 前 14 站，workers=2，260 秒，0 失败）：
- 8/14 与 round1 一致；6/14 差异（cls.cn→human_blocked、hexun→unknown、
  le.com→verification_then_password、stcn→unknown、yinyuetai→otp_only）。
- 差异站点有头复探：cls.cn/hexun/le.com 均有密码/邮箱框（入口可达），
  stcn/yinyuetai 均无（站点本身变化）。差异主要是站点反爬/改版及无头
  弹窗局限（CHANGELOG 第 14 条已记录），非本轮修复引入。

验证：156 项测试全部通过。

### 20. 口令政策广测 + inline 检测深度优化（2026-08-28）

广测（48 直通口令站 × signup/login = 96 条，最新代码）：
- **12 个唯一站点成功测出政策**（第 3 轮仅 3 个，成功率 13%→40%），
  全部无 inconclusive：163/网易云 [8,16]、腾讯云 [8,20]、百度/贴吧
  [8,14]、gitee [8,102]、cnblogs [8,50]、kuwo [6,16]、驴妈妈 [6,18]、
  ifeng [8,16]。
- 失败 18 站：inline_unsupported 9、政策不可信 6、captcha 4、重定位 2
  （第 2 轮复测 0 新增——失败站为提交时才校验型/验证码型，inline 安全
  边界内不可测）。

inline 检测深度优化（依失败模式逐轮修复）：
- [x] `_detect_method` 探针加 field-state 通道：observer 无反馈时检查
      validity/aria-invalid/error class/红边框（gamersky 等站反馈不走
      DOM 文本）。
- [x] `_looksLikePwdRule` 规则词放宽：灰色提示含"至少/必须/6-20/位/字符"
      等规则词也视为拒绝反馈（gamersky "密码不能带有中文…6-20位"实测）。
- [x] 文本节点直接插入捕获：提示先插入无尺寸临时容器再移动（gamersky），
      尺寸判断漏判第一阶段，改为直接用文本内容判断。
- [x] 反馈基线快照：watchPasswordFeedback 启动时快照页面已有密码提示，
      mutation 捕获相同文本跳过（12306 常驻"6-30位…"规则说明 blur 时
      被 React 重渲染误判为动态反馈）。
- [x] 用户名/账号格式错误过滤：12306 "6-30位字母、数字或_,字母开头"
      是用户名框提示（含"开头/下划线"特征词且无"密码"字样）。
- [x] 反馈邻近度过滤：反馈元素必须在密码框祖先链或同父容器内（12306
      用户名提示离密码框远，DOM 距离判断）。
- [x] `extract_hint_policy` 提示政策解析：inline 无法建立时，先填短密码
      触发提示闪现再扫描页面，解析长度区间/字符类输出 `_hint_policy`
      （gamersky 实测输出 min=6 max=20 "密码不能带有中文…"）；修复
      hint 调用变量名错误（host→_site_host，NameError 被吞）。

数据：`reports/archive/policy_wide{1,2}_20260828.jsonl`。

### 21. 150 站全量（分类器+密码测试）+ 分类器/口令识别优化（2026-08-29）

全量 153 站 × signup/login = 308 条（最新代码，有头修复链：登录兜底轮询
等待、hint 解析 iframe 扫描等），耗时 9.5 小时，失败仅 6 条（98% 完成）：
- **61 个直通口令站中 23 条测出完整长度政策（37%）**，12 个唯一站：
  163 系 [8,16]、腾讯云 [8,20]、百度/贴吧 [8,14]、gitee [8,102]、
  cnblogs [8,50]、kuwo [6,16]、驴妈妈 [6,18]、ifeng [8,16]。
  全部无 inconclusive，163 系四入口交叉一致、百度系一致——数据可信。
- 6 条 hint_only（inline 无法测但输出页面自述规则）。
- 分类分布：direct_password 61、human_blocked 59、otp_only 25、
  no_web_signup 9 等；unknown 136（44%，无头退化为主，CHANGELOG 第 14 条）。

本轮优化（自设目标：口令政策识别 + 分类器）：
- [x] 登录兜底点击后轮询等待认证信号最多 8s（阿里云/京东/链家等慢渲染
      弹窗不再误判 auth_entry_no_auth_state）。
- [x] hint 解析：过滤纯导航文本（"密码登录/忘记密码"无规则信息）；
      遍历所有可见 iframe 扫描（caixin 跨域 iframe 注册页）。
- [x] 前端展示 `_hint_policy`：任务结果弹窗黄色提示框（长度区间/
      字符要求/原文，标注"非实测"）；资料卡 classified_only 追加。

数据：`reports/archive/full150_policy_20260829.jsonl`。

### 22. 扩大测试范围（+150 新站，含国际站）（2026-08-29）

扩大范围：在 153 站基础上，合并 misc 全部列表（cn_new50/foreign100/
sites_new_30 等）去掉已测，新增 149 站（含 Google/YouTube/Facebook/
Amazon/Khan/Roblox/LinkedIn 等国际站），× signup/login = 300 条，
耗时 1.4 小时，失败仅 9（97% 完成）。

新增测出完整政策的站（7 个，国际站全部成功）：
- 七牛 [8,32]、DNSPod [8,20]、起点 [6,18]、ali213 [8,20]
- **LinkedIn [6,None]、Khan Academy [8,None]、Roblox [8,None]**（国际站）

分类分布：unknown 143（无网页认证站为主，youth.cn 等实测无任何认证
元素，unrecognized_page 是诚实记录）、human_blocked 56、direct_password
43、email_only 33 等。

修复：
- [x] `get_logger` makedirs 并发竞争 FileExistsError（runoob/vercel/wix
      实测多 worker 并发创建同目录），exist_ok=True 幂等化。
- [x] OR 规则长度替代分支步进 1 + 回溯确认精确边界（GitHub 阈值 15
      不再偏 1）。

数据：`reports/archive/expanded150_policy_20260829.jsonl`。

### 23. 负对照判定修复 + 无上限站验证（2026-08-29）

扩大测试后逐个攻破 direct_password 失败站，发现并修复：

- [x] **aria-invalid=false 误判为接受信号**：Discord 等 blur 不校验的站，
      "a" 填入后字段保持 aria-invalid=false → 被误判为"接受"→ 负对照
      变成"接受成立"→ 整站不可信。aria-invalid=false 只是无错误标记，
      不等于校验通过。修复：不 break 继续等 observer/错误文本；轮询
      3 秒无信号提前结束走负对照差分判定。
- [x] 负对照阶段（负对照未建立）不提前 break：GitHub 的 "a" 拒绝靠
      observer 捕获（"Password is too short"），提前退出会漏捕获。
      仅负对照已确认后的合法密码测试才 3s 提前 break。
- [x] 服务器部署流程修复：push 后未重启 webapp 导致旧代码运行
      （.deployed-head 落后），已补重启并更新标记。

验证（服务器实测）：
- 百度 [8,14] ✓、gitee [8,102] ✓（无回归）
- Discord 负对照正确不成立 → 回退分类（修复生效）
- LinkedIn [6,None] 新代码完整测出（无上限站耗时 60 分钟，探针多+
  每探针 40s，数据完整可信）

### 24. 无上限站耗时优化 + 303 站全量复测（2026-08-29）

无上限站（LinkedIn/Khan/Roblox）长度二分顶到 128 需 15-25 分钟（每探针
~45s 服务器），用户体验差。

- [x] `binary_search_max` 无上限早停：`mi >= 110` 仍被接受且输入框无
      maxlength 属性 → 判定无真实上限（max=None），提前结束二分。
      LinkedIn 实测：60 分钟 → 655 秒（11 分钟），提速 5 倍，结果
      [6,None] 完整可信。阈值 110 避开 gitee 实测 max=102 等真实上限站。

303 站全量复测（misc 全部列表 + 权威数据合并去重，× signup/login =
606 条，耗时 3 小时，失败仅 7）：
- **17 个唯一站测出完整长度政策（33 条）**，31 条可信（qidian 2 条
  or_rule_likely 诚实标记——起点 6 位单类被拒但模型无类要求，可能
  OR 规则）。
- 新增：ali213 [8,8]+dig=2（固定 8 位）、gitee login 稳定 [8,102]。
- 国际站稳定复现：LinkedIn [6,None]、Khan [8,None]、Roblox [8,None]。
- 分类分布：direct_password 97、human_blocked 122、unknown 274
  （无网页认证站为主）、email_only 39、otp_only 29 等。

数据：`reports/archive/full303_policy_20260829.jsonl`。

### 25. GitHub 负对照恢复 + OR 规则阈值精确化（2026-08-29）

问题：GitHub 负对照 "a" 变 inconclusive（8-28 修复 aria-invalid 后引入）——
"Validation failed"（服务端校验完成且失败的最终态）被当 pending 永久等待，
轮询结束无信号 → 负对照不成立 → 整站回退。

修复：
- [x] field-state 中 "Validation failed" 仍标 pending（可能瞬态），但
      Python 轮询层持续 2 秒未变 valid → 判 rejected（"a" 实测
      Validation failed 稳定 12 秒是最终拒绝态；合法密码立即 valid
      不受影响）。最终复验不改判（transient 正则匹配）。
- [x] 长度替代分支回溯已生效：GitHub `length_alternative` 从 16 精确到
      **15**（14 拒、15 接受——精确还原 "≥15 位" 替代分支）。

GitHub 本机完整实测（有头+代理）：
- 分类 direct_password ✓；inline 负对照成立 ✓；长度 [8,72] ✓
- _or_rule：8 位单类全拒、lower+digit=True、**length_alternative=15** ✓
- 服务器端 GitHub 入口受 IP 反爬影响（no_web_signup/worker 崩溃），
  属外部环境限制，非代码问题。

### 26. 有头全量回归（第 1 轮）（2026-08-30）

今日 12 个 commit 修改后，验证老站是否受影响 + 有头全量逐轮优化：

老站回归（16 个已知成功站 × 2 = 32 条，有头）：
- **22/32 测出（69%）**，21 条与全量 303 一致（tieba signup 为
  None→[8,14] 改善）——**老站全部不受影响**。
- 10 条失败均为"单侧偶发"（如 music.163 signup 失败但 login 成功、
  roblox signup 失败但 login 成功）——时序/反爬，非代码问题；
  LinkedIn/Roblox 600s 超时因有头每站 4-10 分钟。

有头全量第 1 轮（303 站 × 2 = 606 条，site_timeout 900s）进行中，
每轮分析失败模式并优化。

### 19. 全量验证 3 轮 + 无头批量密码测量修复（2026-08-28）

背景：合并后的代码（登录→注册兜底、iframe 口令框测量、自洽校验等）需
全量验证。发现批量脚本只分类不测密码、无头下 inline 反馈不触发两大问题。

修复：
- [x] `run_measurement.py`：`classify_one` 复用 `main.test_single_site`
      完整流程（此前只跑分类器，批量结果 policy 恒为空、method_used 恒
      None）；新增 `--measure-policy` 开关。
- [x] 无头 blur 兜底：无头模式下 ActionChains 坐标点击不触发 blur 校验
      （gitee 无头实测 inline 探针 3 次全无反馈），`_detect_method` 与
      `test_one_password` 在真实鼠标点击后补 JS blur + blur 事件。
- [x] 登录兜底快速预检：页面无可见登录入口文本时跳过兜底（无弹窗站
      白白耗时 15s+ 导致 site_timeout），等待压缩（3s→1.5s 等）。

三轮全量验证（无头，154 站 × signup/login = 308 条）：
- 第 1 轮全量分类：308 条 / error 46（site_timeout 40 + worker 6），
  与权威对比一致 177 差异 130（差异主因无头退化 human_blocked→unknown
  ×26 及超时 ×45，CHANGELOG 第 14 条已记录无头退化）。
- 第 2 轮 error 站重测：60 条 / 40 修复 / 7 仍超时。
- 第 3 轮 direct_password 站密码测量：94 条 / 5 条测出完整政策
  （cnblogs [8,50]、gitee [8,102]、kuwo [6,16]，均与已知政策吻合），
  33 条因真实安全边界回退分类（2 滑块验证码 + 31 无内联反馈）。

数据：`reports/archive/validation_round{1,2,3}_20260828.jsonl`。

### 14. v4 逐方法呈现（MultiMethod）+ unknown 攻坚（进行中）

背景：35% 记录（106/302）观察到≥2种注册/登录方法，但分类/存储/展示全链路
只保留单个 flow_type，方法信息被压扁。v4 目标是逐方法呈现 + 攻坚 unknown。

**关键决策（2026-08-15，用户拍板）：全量重跑采用有头 Chrome。**
实测无头模式（SITES_HEADLESS=1）让 30+ 站点（阿里云/豆瓣/贝壳/链家/小红书/
虎扑等）登录/注册弹窗不弹：v4 无头第 1 轮 145/302 条与 v3 不一致、40 条真实
结果退化（human_blocked/direct_password → no_web_signup/unknown）；有头模式
这些站全部恢复（douban→human_blocked 与 v3 一致）。因此：
- 全量重跑（Mac）用**有头**，与 v3 官方数据同口径；
- 服务器实时分类继续**无头**（SITES_HEADLESS=1 只影响服务器，实测正常）；
- 无信号 unknown 的 no_web_signup 升级已**回退**（防无头误判），no_web_signup
  只保留三处有明确证据的守卫（仅登录界面/登录页冒充注册/展开后只露登录口令框）。

已完成的改动：
- [x] `flow_types.py`：新增 `MethodResult`（method/name_zh/status/confidence/
      blockers/route/steps），`FlowResult.methods` 数组；flow_type 保留为主方法口径。
- [x] `classifier.py`：`aggregate_methods()` 聚合逻辑——从状态序列收集方法
      （含字段反推：password 字段→账号密码、code 字段→短信验证码），逐方法判定
      confirmed（出现过且无硬门槛）/blocked（只出现在有门槛的步骤）/observed
      （auto_signup 等文案语义）；口令路线存在时 phone/email/identifier 视为
      账号标识不单列方法；主方法状态与 flow_type 对齐（已到达口令步骤即 confirmed，
      页面级备选门槛不挂在主方法上）。
- [x] `evidence.py`：`finalize()` 统一接入聚合，所有分类路径自动带 methods。
- [x] 真实浏览器单站验收：12306/zhihu/feishu/segmentfault/china.com 登录注册
      双侧方法清单符合人工预期（china.com 正确呈现 账号密码+QQ+第三方 三方法并存）。
- [x] unknown 攻坚 A 类（人工确认无网页入口 8 站）：三处 NO_SIGNUP_ENTRY 返回
      从 unknown 改为 no_web_signup（仅登录界面守卫/登录页冒充注册/展开后只露
      登录口令框）；最终 unknown 路径增加"页面正常加载+全程无认证信号+从未点过
      入口 → no_web_signup"升级。实测 chinanews/coolapk/dewu/nbd/qunar/
      xinhuanet/zhuanzhuan 7 站转正；meituan/imooc 因 entry_click 波动保持
      unknown（防"弹窗没弹出来"误判）。
- [x] A 类晚渲染保护：sina/2345 等重页面入口可能晚渲染，下结论前
      `_wait_for_page_stable`（8s）后重新探测字段/tab/门槛，仍有信号则回 unknown，
      避免"没加载完"误判成"没有"；同时修复 `_wait_for_page_stable` 漏传
      driver 参数导致的 zhibo8 崩溃。
- [x] 批量流水线 methods 补齐：`scripts/run_measurement.py` 与
      `scripts/site_data_store.py::measurement_record` 白名单 schema 补
      `methods` 字段（网页"加入数据库"与批量重跑均保留方法清单），
      冒烟验证 12306/china.com 输出带方法；新增对应单元测试（108/108 通过）。
- [x] B 类波动组 3 连跑（无头）：36kr→otp_only、meituan→human_blocked（整页
      人机验证）、pan.baidu→direct_password 转正；anjuke 弹窗时开时不开；
      sina/2345/zhibo8（zhibo8.com）无头环境认证入口不可达，报 no_web_signup
      （"入口失效"语义，人工对照会如实显示差异，作为已知边界文档化）。
- [x] B 类结构难点组诊断：zol 修复——`safe_click_tab` 文本匹配与 `detect_tabs`
      统一为分词匹配（合并文本"短信登录 帐号登录"，zol 实测），tab 点击从
      no_password_signup_tab 修复为 clicked_and_changed；但注册视图字段仍
      检测不到（DOM 结构问题），zol 继续 unknown 如实记录。acfun 入口发现
      失败（登录/注册入口未找到）；thepaper 登录弹窗手机号+密码可识别但
      无独立注册入口（登录即注册语义）；v.qq/work.weixin 入口/切换问题；
      均作为已知结构难点记录在报告。
- [x] **v4 正式数据产出（有头，两轮全量+差异复测+仲裁）**：
      - 第 1 轮 302 条 0 失败、第 2 轮 302 条 0 失败；两轮 282/302 语义一致
        （93% 稳定），20 条差异项 15 站复测仲裁（多数投票/独立证据/回退 v3）。
      - 修复两处 v3 时代潜伏 bug：`_wait_for_page_stable` 漏传 driver 参数
        （空壳回退路径 line199 / 空白页检查路径 line789，全量跑才暴露，
        music.163 渲染超时、huaweicloud 空壳回退崩溃），复测全部 0 失败。
      - 正式数据 `reports/sites/sites_latest.jsonl` 302 条全 v4，151 站双侧
        齐全；未知 unknown 从 v3 的 101 降到 83，direct_password 从 64 升到 91。
      - 数据库重建：151 站 83 已核验，v3 旧记录进历史表；逐站档案/汇总表已重生成。
      - 指标：登录正确率 72.7%→80.7%、注册 80.0%→78.9%，覆盖率登录
        66.3%→68.7%、注册 60.2%→68.7%。
      - 方法清单全覆盖：详情 API/网页方法表格展示逐方法 confirmed/blocked/observed。
- [x] 回归测试 98/98 通过。
- [x] webapp 接入：详情 API 返回 `login/signup.methods`（旧 v3 数据为空数组兼容）；
      详情弹窗新增"方法清单"行（方法名+状态徽标+路线，confirmed/blocked/observed）；
      人工对照 reason 追加"程序观察到方法 vs 人工勾选方法"对照说明。
- [x] 人工提交表单改多行：登录/注册各一行一种方法输入，提交时解析行填充结构化
      traits（显式勾选优先；修复"无密码"被"密码"子串误判的 bug）。
- [x] 网页写入模型 v3/v4 双接受（默认 v4），前端"加入数据库"带 v4；
      `misc/measure_version.txt` 升至 v4；测试契约同步更新（107/107 通过）。
- [ ] unknown 攻坚 B 类（波动组 3 连跑取多数 + 结构难点组逐站诊断）
- [ ] 数据库/API/前端接入 methods + 人工提交改多行 + 人工对照集合化
- [ ] 升 v4 全量重跑 ×2（无头）+ 两轮对比仲裁
- [ ] 推送 + 服务器部署 + 公网验收



### 15. 网页表达大改版（2026-08-15，用户反馈 6 项）

1. **方法清单改"方法一/方法二"格式**：`方法一：账号密码（确认可用）` + 独立一行路线；
   页面形态翻译成人话（内嵌挂件→页面挂件、独立页→独立页面、弹窗/抽屉/分步表单…）。
2. **路线与字段去重**：详情页删除独立的"路线/字段/阻断"三行，信息并入方法清单
   与类型行；路线生成逻辑重写——tab 切换的并行视图不再线性化成"→"链
   （36kr 从"手机号、一次性验证码 → 短信验证码 → 手机号、口令"改为
   "手机号、一次性验证码（需短信验证码） → 手机号、口令"，字段+门槛合并展示）。
3. **去 AI 味**：方法状态 confirmed/blocked/observed → 确认可用/门槛阻拦/仅观察到；
   门槛显示中文（需短信验证码、需邮箱验证码、需用户协议确认）。
4. **历史程序结果补全 v3**：新增 `reports/archive/v3_official_20260814.jsonl`
   （从 git 提取 v3 正式 302 条），建库自动加载 `v*_official_*.jsonl`，历史表
   306 条（304 v3 + 2 v4），旧版本结果完整可查。
5. **卡片简化 + 详情结构化对比**：站点卡片只显示"登录识别正确/错误/待核验"
   徽标（不再贴大段原因）；详情页人工区改为结构化对比表
   （主类型/方法两列：程序 vs 人工，结论一行），完整原因折叠为小字。
6. **36kr 路线核查**：程序证据正确（短信视图 + 密码视图并行，tab 切换可达
   口令框），但 36kr 弹窗的微信/微博第三方入口藏在"更多方式"里未被发现，
   人工对照如实显示不一致（程序发现 3 方法 vs 人工 4 方法），留待人工复核。

### 16. 方法清单组合式改版（2026-08-15，用户反馈第二轮 5 项）

1. **删除登录/注册步骤 tab**：步骤证据只留在数据与档案里，网页不再展示。
2. **方法改为"用户视角组合"**（核心）：一个方法 = 完整登录方式，
   `手机号+验证码`/`邮箱+密码`/`账号/邮箱/手机号+密码`/`第三方（微信、QQ）`/
   `扫码`/`登录即注册`，字段用 + 连接，不再把手机号、验证码拆成独立方法；
   短信验证码属于方法本身（软门槛不使方法变"需验证"），只有人机/滑块/
   扫码确认等硬门槛才标"需验证"；第三方提供商合并为"第三方（微信、QQ）"。
   36kr 登录实测：方法一 手机号+密码、方法二 手机号+验证码（均已确认）。
   方法中的步骤/页面形态信息全部从网页移除。
3. **详情页布局**：登录对比表 + 注册对比表，下方"查看历史程序结果"和
   "反馈识别结果"。
4. **状态词解释**：已确认=程序在安全边界内看到该方法的全部要素；
   需验证=完成该方法需短信/人机/扫码等验证，程序不越验证；仅观察到=弱证据；
   详情页加一行"方法说明"解释三态。
5. **类型行加主方法**：如"密码直接可见 · 主方法：手机号+密码"；流程中文名
   更新为直白表述（密码直接可见/仅验证码（无密码）/需人工验证…），DB 词表同步。
6. 新增 `scripts/reaggregate_methods.py`：从 states 离线重算 methods，
   无需重跑浏览器全量（正式数据与三份轮次档案已全部重聚合）。

### 17. 数据层/展示层分离整改（2026-08-15，用户铁律）

用户明确：所有展示优化只针对服务器展示方式，**不改本地 reports/ 和 misc/
数据格式**；网页测新网站展示优化后的分类，实际写入记录的仍是数据层原始格式。
整改内容：
- reports 数据回滚到组合式改版前的原始格式（git 7a5e9a2）：sites_latest.jsonl
  方法按字段（账号密码/短信验证码…带 route），v3 官方存档不带 methods。
- classifier.py 恢复数据层 `aggregate_methods()`（引擎记录用它）；
  新增展示层 `combo_methods()`（组合式：手机号+验证码/第三方（微信、QQ）…），
  仅由 webapp/app.py 在 API 响应时从 states 计算，不落盘。
- 删除 `scripts/reaggregate_methods.py`（回写数据文件的脚本，违反铁律）。
- HANDOFF.md 记录该铁律；测试 117/117 通过。

### 18. 展示简化（2026-08-15，用户反馈第三轮 3 项）

1. 类型名改直白：密码直接可见→**有口令框**、先账号后密码→先账号后口令框、
   仅验证码（无密码）→仅验证码；DB 词表同步。
2. 方法清单删除状态词（已确认/需验证/仅观察到），只显示"方法一：手机号+密码"。
3. 删除详情页"方法说明"解释行。

### 19. 展示再简化（2026-08-15，用户反馈第四轮 2 项）

1. "登录即注册"是页面文案语义（手机号首次登录自动注册），不是可选方法——
   展示层不再单列（feishu/zhihu 等登录注册两侧方法清单不再出现）；
   数据层 records 里的 auto_signup 语义保留（铁律：数据不动）。
2. 人工对照 reason 删除"一致：/差异："前缀（结论由"识别正确/识别错误"徽标表达）。

## 变更速查表

| 日期时间 | 改动人 | 内容 | 相关文件 | 推送状态 |
|---|---|---|---|---|
| 2026-09-04 | cjx | inline 找不到 admissible 单点故障修复：降级为 maxlength 兜底（length[1]）+ _no_password_feedback 标记，与 full-form 口径对齐 | utils/site_agnostic_tester.py | 未推送 |
| 2026-09-03 | cjx | inline 方法测试顺序调整（长度先于组合）+ 备选池扩充（加大小写/符号候选）；百度、腾讯云回归通过 | utils/site_agnostic_tester.py、utils/util_test_password.py | 未推送 |
| 2026-09-03 | cjx | 游民星空 placeholder 误判修复：Layer 6 由拼接整段改为逐行检查，占位符「密码 (6-20位…」不再被无关「不能为空」干扰误判；gamersky 端到端验证 length[1]=20 + _no_password_feedback | full_form_tester/password_error_parser.py | 未推送 |
| 2026-09-03 | cjx | Chrome 152/ChromeDriver 版本不匹配修复：去 version_main=150 硬编码、新增 _installed_chrome_major() 本机版本探测、_find_cached_chromedriver 版本感知查找、npmmirror 镜像下载 152 驱动 | utils/util_test_password.py | 未推送 |
| 2026-08-23 | cjx | 游民星空 placeholder 误判诊断（待修：政策描述过滤/admissible 符号候选/单点故障） | full_form_tester/ | 未推送 |
| 2026-08-23 | cjx | gitee 强度计误判 + xuetangx 参数矛盾修复 | full_form_tester/form_submitter.py、password_error_parser.py | 未推送 |
| 2026-08-23 | cjx | 百度长度 min=32 误报修复（二分上界截断）+ 组合模型局限记录 | utils/util_test_password.py | 未推送 |
| 2026-08-23 | cjx | 密码政策测量链路激活 + 首批 13 站实测（5 站出完整政策） | utils/site_agnostic_tester.py、utils/util_test_password.py、full_form_tester/ | 未推送 |
| 2026-08-15 | Kimi（Mac） | 展示简化：类型名直白化（有口令框）、方法清单去状态词、删方法说明 | webapp/static/index.html、scripts/build_site_database.py、tests/ | 本次提交 |
| 2026-08-15 | Kimi（Mac） | 数据层/展示层分离：reports/misc 回滚原始格式、组合式方法只由 webapp 计算（combo_methods）、删除 reaggregate 回写脚本、HANDOFF 记录铁律 | signup_flow_classifier/、webapp/、scripts/、reports/、tests/、HANDOFF.md | 本次提交 |
| 2026-08-15 | Kimi（Mac） | 方法清单组合式改版：手机号+验证码/邮箱+密码组合、删除步骤 tab、类型行加主方法、状态三态解释、reaggregate_methods 离线重聚合 | signup_flow_classifier/、scripts/、webapp/、tests/ | 本次提交 |

| 日期时间 | 改动人 | 内容 | 相关文件 | 推送状态 |
|---|---|---|---|---|
| 2026-08-15 | Kimi（Mac） | 网页表达大改版：方法一/方法二格式、路线并行视图修复、历史补全 v3（306 条）、卡片徽标化+详情结构化对比表 | webapp/、scripts/build_site_database.py、reports/archive/v3_official_20260814.jsonl、tests/ | 本次提交 |
| 2026-08-15 | Kimi（Mac） | v4 正式数据（有头两轮全量+仲裁）：302 条全 v4，unknown 101→83、direct_password 64→91，覆盖率登录/注册均 68.7%，方法清单全链路呈现，修 2 处潜伏 bug | signup_flow_classifier/、scripts/、webapp/、reports/、tests/ | 本次提交 |
| 2026-08-15 | Kimi（Mac） | v4 逐方法呈现（MultiMethod）进行中：MethodResult 聚合 + 三处 NO_SIGNUP_ENTRY 改 no_web_signup + unknown 无信号升级；A 类 7 站转正 | signup_flow_classifier/、CHANGELOG.md | 未推送 |
| 2026-08-15 | Kimi（Mac） | 站点筛选按登录/注册双侧合并判定（识别不一致 10→18 站，此前登录侧错误被注册侧正确遮盖），新增"程序证据不足/人工证据不足"两个筛选；不动数据与版本 | webapp/static/index.html、HANDOFF.md | 本次提交 |
| 2026-08-15 | Codex（Mac） | v3 保守运行时加固（进行中）：修复并发入库/同步竞态与导出历史覆盖当前版本；同步失败安全中止；限制实时分类资源及内网目标；匿名不再读取待审核详情 | webapp/、scripts/、tests/ | 已推送，待服务器部署验收 |
| 2026-08-15 | Codex（Mac） | v3 数据闭环改进完成：网页持久化、结构化核验、双侧原因、诚实指标、unknown 优化、两轮全量回归及三端同步均完成并上线 | webapp/、scripts/、signup_flow_classifier/、tests/、reports/、HANDOFF.md | 已推送并于 00:00 定时部署验收 |
| 2026-08-14 | Codex（Mac） | 修正正式汇总表输出位置与逐站档案相对链接，删除两个已被正式域名取代的旧别名档案 | scripts/generate_profiles.py、reports/sites/sites_summary.md、reports/sites/profiles/ | 本次提交 |
| 2026-08-14 | Codex（Mac） | 保持 v3：修正扫码登录语义与第三方登录识别，新增两轮全量回归对比，并为网站正确/错误判断补充可读依据 | signup_flow_classifier/、scripts/run_measurement.py、scripts/compare_measurement_rounds.py、webapp/、tests/、reports/ | 本次提交 |
| 2026-08-12 | cjx（Mac） | 修复慕课网手机号字段被误判为 email、知乎机构号注册入口误当普通注册 | signup_flow_classifier/page_detector.py、utils/login_link_discovery.py、utils/js/form_detection_addons.js、tests/test_site_recognition_fixes.py | 未推送 |
| 2026-08-12 | cjx（Mac） | 从旧分支按能力挑选移植：多语言词表、弱结构词防御、容器硬规则、hover 菜单 | signup_flow_classifier/page_detector.py、signup_flow_classifier/navigator.py、signup_flow_classifier/classifier_engine.py、tests/ | 未推送 |
| 2026-08-12 | cjx（Mac） | 批量识别问题修复（36kr 文章误点/视口检查/叶子检查/beian 阻断/百度安全验证/URL 模式预算/JS 容错）+ reports 目录结构调整 | signup_flow_classifier/navigator.py、classifier_engine.py、browser_failures.py、page_detector.py、utils/login_link_discovery.py、scripts/、reports/ | 未推送 |

---

## 实现细节

### 8. v3 服务器运行时保守加固（2026-08-15，进行中）

- [x] 复现并发新增同一网站登录/注册时，JSONL 已有双侧结果但 SQLite 一侧缺失、
  另一请求触发唯一键异常的问题。
- [x] 网页新增、人工提交/审批/删除与六小时同步、独立数据库重建共用同一跨进程锁；
  同步期间读取仍可服务，写请求在临界区结束后继续，避免权威文件与服务索引分叉。
- [x] Git 基线读取异常改为安全中止，不再把“读取失败”误当空基线并全量回放；
  空增量不再错误报告总数为 0，旧人工快照也不会回退 `updated_at`。
- [x] 旧 SQLite 无法读取待审核记录时取消重建并保留旧库，避免静默丢弃仅存于库中的提交。
- [x] `/api/export` 改为在一致性锁内原样读取两份权威文件，不再从 SQLite 拼接后把
  历史版本排在当前版本之后，避免 Mac 拉取时旧结果覆盖当前 v3。
- [x] 公网实时分类限制为 HTTP(S) 公网 80/443 目标并限制并发 Chrome 数；匿名仅能查询
  单站待审核数量，完整人工内容需管理员口令；网页写入模型固定接受 v3。
- [x] 手动全量重测先写临时结果，成功后才在一致性锁内按站点/入口合并；测量中断不再留下
  半份正式 JSONL，151 站固定清单之外的网页新增网站也不会被全量重测抹掉；最终化步骤
  由 Python `fcntl` 锁托管，兼容没有 `flock` 命令的 macOS。
- [x] 命令行审核工具也接入同一锁和原子人工文件写入，保留结构化双侧字段，并将
  `feedback` 仅标记为已处理而不误写成人工核验结论。
- [x] 六小时同步新增“已部署 Git 提交”本机标记与 `/api/stats` 健康检查；若提交后建库、
  重启或健康检查失败，下一轮会继续部署而不因 HEAD 未再次变化而永久跳过；Git 网络
  操作增加单次 120 秒上限，避免断网时无限占用数据锁。
- [x] 离线程序/人工审计报告将 `match`、`mismatch`、证据不足分别统计和完整列出，
  不再把证据不足在终端笼统打印成“不一致”却从 Markdown 表中消失。
- [x] 完成 98 项自动化测试、本地真实 HTTP/安全边界验收、数据哈希与临时重建检查；
  两轮全量各 302 条（语义一致 285/302），13 站 26 条定向复测及失败项补测。
  审计候选虽把 unknown 101→96，但注册正确率 80.0%→78.8%，因此不覆盖正式 v3；
  详见 `reports/archive/v3_runtime_hardening_acceptance_20260815.md`。
- [ ] 完成 GitHub 推送、服务器自动部署及公网 API/页面验收。

### 7. v3 数据闭环、核验指标与识别优化（2026-08-14～15，已完成）

- [x] 网页新增/更新站点原子写入 `reports/sites/sites_latest.jsonl`，保留完整证据和未修改的一侧结果。
- [x] SQLite 先在旁路文件完整构建并原子替换，失败时旧库继续服务，同时保留待审核；
  服务器每 6 小时只快照相对旧 HEAD 真正变化的网页增量，干净 pull 后按
  站点/入口原子回放，避免 Mac/服务器同时改 JSONL 的冲突；失败时也恢复快照。
- [x] 人工核验改为结构化记录；登录、注册分别即时判断匹配/错误/证据不足并统计正确率与覆盖率。
- [x] 网站卡片将登录、注册两侧分别主动显示正确/错误/证据不足原因（任一侧错误都不会
  被另一侧正确结论遮住），审核后立即刷新，并每 30 秒同步其他浏览器的数据变化。
- [x] 针对现有 `unknown` 改进通用识别：备案页脚不再触发全页访问阻断，验证码/
  挑战 URL 归为可解释的人工阻断；补齐自动化测试，未加入网站域名硬编码。
- [x] 完成两轮 151 站全量回归（各 302 条，273 条语义一致）、46 条差异定向复测、
  多数/成功证据仲裁及人工抽查；正式数据 302 条全部保持 `v3`，无错误记录。
- [x] 更新 Mac、GitHub、服务器之间的数据流说明；GitHub 推送后由服务器 00:00 定时
  自动拉取、重建并重启，公网 API 与真实页面均完成验收。

阶段验证：正式 `unknown` 115→101；人工核验口径下，登录正确率 71.7%→72.7%、
覆盖率 63.9%→66.3%，注册正确率 79.2%→80.0%、覆盖率 57.8%→60.2%。
完整两轮差异和人工抽查见 `reports/archive/v3_data_sync_acceptance_20260814.md`。
`webapp/DATA_FLOW.md` 已写明 reports/manual 权威数据与 SQLite 可重建索引的边界。
最终验证：84/84 自动化测试、Shell/前端语法检查、151 站 API 冒烟通过；增量快照
测试确认网页变更可回放且不会覆盖 Mac 同期更新，完整快照回放精确恢复 302/302 条；真实浏览器
确认卡片主动展示登录/注册各自的正确/错误/证据不足原因，详情分别展示双侧原因，
结构化核验表单完整且控制台无错误。2026-08-15 00:00 服务器定时部署成功；公网核对
151 站全部 v3、程序错误 0、已核验双侧原因 166/166 完整。

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

### 19. 展示再简化（2026-08-15，用户反馈第四轮 2 项）

1. "登录即注册"是页面文案语义（手机号首次登录自动注册），不是可选方法——
   展示层不再单列（feishu/zhihu 等登录注册两侧方法清单不再出现）；
   数据层 records 里的 auto_signup 语义保留（铁律：数据不动）。
2. 人工对照 reason 删除"一致：/差异："前缀（结论由"识别正确/识别错误"徽标表达）。

### 20. 展示再简化（2026-08-15，用户反馈第五轮 2 项）

1. 详情页删除人工对照的大段原因文字（程序依据/观测路线/人工复核/程序观察到方法
   全删），对比表只留结构化行（主类型/方法/结论），结论用固定短语
   （程序与人工结论一致/不一致/证据不足，暂不判定）。
2. 现场分类结果（/api/classify）新增组合式方法清单（库内命中与实时分类两条
   路径都返回），网页分类框直接显示"方法一：手机号+验证码…"。

### 21. 报告格式统一（2026-08-15，用户反馈第六轮 3 项）

1. 人工对比表删除"主类型"行，只保留"方法"（程序 vs 人工）与"结论"两行。
2. 类型行删除"主方法：xxx"后缀，只显示流程徽标。
3. 现场分类结果框改为与单站详情报告同款表格（reportTableHtml 共享函数：
   类型/方法清单/口令政策/测量时间/程序版本），置信度/路线等作为辅助信息
   放在表格下方；/api/classify 返回组合式方法清单。

### 22. 分类器 v4.1 全视图探索（2026-08-15，用户第六轮大目标）

用户要求分类器"像真人一样"找出所有注册/登录方式。本轮改进：
1. **全视图探索**：看到口令框不再立即停止——切换所有检测到的 tab
   （短信/邮箱/注册/账密）逐一观察并记录方法（51.com 实测：账号登录视图
   外还有"手机登录"视图的 手机号+验证码，旧代码看到密码框就停漏掉短信视图）。
   - `classifier_engine.py`：tab_clicks_left 2→5、新增 visited_tabs 去重、
     `_TAB_EXPLORE_PRIORITY` 优先级、失败后 1.5s 重试一次、默认 max_steps 3→6。
2. **sms_tab 词表补全**（page_detector.py）：加"手机登录/手机号验证码登录/
   短信登 录"（51.com 弹窗"账号登录微信登录手机登录"合并文本实测）。
3. **现场分类呈现**（webapp）：both 模式一张表（登录|注册两列），单模式
   只显示对应列；app.py FLOW_ZH 词表同步直白标签。

### 23. v4.1 四轮全量回归完成（2026-08-15，用户第六轮大目标收尾）

用户要求：分类器像真人一样找出所有注册/登录方式，至少 4 次全量回归（每次
有意义、检查脚本判断），不过拟合、不追 100% 正确率，本地/GitHub 报告详细、
服务器呈现简洁，有头模式。

**四轮回归（有头，302 条/轮，0 崩溃，music.163 渲染超时除外）**：
- 第 1 轮：全视图探索（看密码框不停、切所有 tab）——23 条记录新增方法
  （36kr 补上邮箱+密码、华为云 3 方法、bilibili/新浪/优酷补验证码视图），
  抽查证据（华为云 step2 手机号+验证码视图 → step3 切密码视图）确认不是误报。
- 第 2 轮：93% 稳定性（281/302 一致），探索新增方法全部稳定保留；
  21 条差异全是已知波动站。
- 第 3 轮：三轮 flow 一致率 93%（267/288）；抽查知乎/京东/淘宝/豆瓣/小红书
  方法清单与真实登录方式吻合（知乎 4 方法、淘宝仅验证码、网易云仅扫码）。
- 第 4 轮：四轮多数仲裁 + 有效证据优先（error/unknown 不占多数，平票取最新，
  四轮全失败保留上一版有效证据——music.163 signup 渲染超时 4 次回退旧记录）。

**最终数据（302 条，151 站）**：direct_password 94（v3 为 64）、unknown 82
（v3 为 101）、human_blocked 80、otp_only 28、sso_only 7、no_web_signup 6。
注册覆盖率 68.7%→71.1%；登录 80.7%/68.7% 不变。仲裁决策 302 条全部可追溯
（reports/archive/v4_r2_final_decisions.md）。

**已知边界（不过拟合，如实记录）**：
- 51.com 弹窗 tab 栏波动渲染（8 轮轮询仅偶现），手机登录视图时有时无，
  多数轮只记录到账号+密码+第三方；已按多数取稳定结果。
- deeix.gaoxiaobei.top 只有登录页：登录=有口令框、注册=无网页注册（判断正确，
  此前是旧呈现造成的误读）；已加入 misc/sites_extra.txt 后续一并测量。
- 各站"更多方式"折叠里的第三方入口部分仍不可达（安全边界内不点隐藏折叠）。

### 24. 修复方法清单消失（2026-08-15 深夜，用户报告）

`reportTableHtml` 里 `tds(methodsHtml)` 把整个站点对象传给期望数组的
methodsHtml（对象无 length → 显示"—"），口令政策同样传错参数。改为
`tds((e) => methodsHtml((e || {}).methods))`。用无头浏览器实测详情弹窗
渲染验证：36kr 登录 3 方法/注册 1 方法、口令政策正常显示。

### 25. 方法级对照"部分一致" + 结构化人工提交（2026-08-16，用户反馈）

1. **不再"少识别方法也算对"**：`_manual_comparison` 流程判定 match 后做方法级
   对照——人工结构化确认的方法（口令/验证码/扫码/第三方）程序缺失时，状态
   降级为 partial（部分一致），结论显示"程序方法识别不全，缺失：XX"。
   2345 实测：程序 2 方法 vs 人工 3 方法（缺第三方）→ 部分一致（不再算"对"）；
   方法齐全仍为 match。统计新增 partial 桶（不计入正确率分母、计入覆盖率），
   卡片新增"部分一致"徽标，列表新增"部分一致"筛选。
2. **修复"无注册界面但方法清单有方法"的矛盾**：signup=no_web_signup 时方法
   清单清空（观察到的字段来自登录弹窗，2345 实测）；classify 接口同步。
   判"不一致"本身是诚实的——程序认为无注册界面、人工认为有注册，真实分歧
   留给人工复核，而非强行一致。
3. **人工提交改为结构化方法填词**：方法一/方法二…每行勾选要素（手机号/邮箱/
   账号/口令/验证码/人机验证/扫码/第三方/协议/无注册界面），自动 "+" 连接并
   实时预览（如"手机号+验证码"）；提交时自动生成 structured 布尔集合；
   删除自由文本输入与旧"结构化核验"勾选区（保留备注）。
4. **修复服务器同步 SIGPIPE 中止**：`git status | head -40` 在改动文件多时
   head 提前退出致 git 收 SIGPIPE，pipefail 下脚本以 141 中止（提交步骤跳过，
   残留未提交文件挡住下次 rebase）。加 `|| true` 吞掉该退出码。

### 26. 修复测量流量误走系统代理（2026-08-16，用户发现 Clash 流量 2 天烧 200G）

根因：macOS 系统代理（Clash Verge 1082 端口）开启时，Chrome 默认读取系统
代理，测量脚本只在显式配置环境变量代理时才传 --proxy-server，导致全部测量
流量经 Clash 境外节点转发——4 轮全量回归 + 波动组 + 结构难点诊断约 2000+
次中文站页面访问，单页几十 MB，2 天烧掉 200G 代理流量。
修复：`utils/util_test_password.py` 两个 driver 创建点——未显式配置
CRAWL_PROXY/HTTPS_PROXY/HTTP_PROXY 时强制加 `--no-proxy-server` 绕过系统
代理（中文站直连更快且零代理流量；显式配置代理的行为不变）。
验证：百度直连正常；119 项测试通过。

### 27. 全站地面真值审计 + 图片型第三方识别修复（2026-08-16，用户强烈要求）

用户随手查 cctv.com 即发现程序漏了图片型第三方/注册链接，质疑此前四轮全量
回归的核对质量。深刻反思：前四轮只验证了"程序内部自洽"，没有"打开网站对照
现实"。本次整改：

**1. 全 152 站地面真值逐站核对**（亲自逐站完成）：
- 新增 `scripts/ground_truth_probe.py`：自动化打开每个站点收集真实认证证据
  （输入框/认证文本/第三方图标/注册链接/tab），证据 /tmp/gt_evidence.jsonl。
- 审计报告 `reports/archive/v4_3_ground_truth_audit.md`：152 站逐站对照，
  汇总：✅一致 53 站、⚠️缺方法 11 站、❓探测未复现弹窗 85 站（波动/App-first）、
  🔀站点跳转/反爬 3 站。

**2. 通用修复（不硬编码）**：
- `page_detector.py`：SSO 扫描选择器加入 `img`；`_sso_provider` 语义加入
  `alt` 属性；`icon_only` 改用元素自身 textContent 判定（img 的 title 会被
  _element_text 混入 text 导致纯图标误判）。
- `classifier_engine.py`：注册 tab 处理加重试（href 导航 + 点击各 2 次，
  中间 1.5s，cctv 弹窗刚渲染时取不到链接）。
- 端到端验证：52pojie 注册页 img alt=QQ登录/微信 → detect_methods 返回
  sso+qq+wechat ✓（单元测试 3 项 + 实测）。
- zhipin 重测改善（unknown → 手机号+验证码+微信）已合并进正式数据；
  其余站保持四轮多数结果（防波动回退）。

**3. 流程整改**：真值核对写入 HANDOFF 作为每轮全量的强制步骤——
  不附带"真值核对报告"的回归不算完成。

### 28. 展示词统一（2026-08-16）：部分一致 → 识别部分一致（卡片徽标/对比表/筛选按钮）

### 29. 分类口径合并（2026-08-16 规则）：识别部分一致并入识别基本一致

用户认为分类过多。规则：方法缺失不再单列"部分一致"状态，并入 match
（识别基本一致）——2345 这类"流程对但少识别第三方"的站重新归入识别基本
一致，但结论文字保留"方法识别不全，缺失：第三方"，信息不丢失。
- app.py：_manual_comparison 不再降级 partial（reason 注明缺失方法）；
  统计/站点状态移除 partial 桶。
- 前端：删除"部分一致"筛选按钮、徽标、结论分支。
- 效果：登录正确率 80.7→81.7%、覆盖率 68.7→71.4%；注册 76.3→77.0%、
  71.1→72.6%（原本 partial 的并入正确）。

### 30. 服务器权限根因修复（2026-08-16）

反复出现的"同步 PermissionError: manual_review.json"根因：systemd 服务
未指定用户（默认 root 运行），网页写入的文件变 root 属主，ubuntu 的同步
无法读取。修复：sites-webapp.service 增加 User=ubuntu/Group=ubuntu 并
重启，网页与服务文件属主一致，同步不再被权限阻塞。

### 31. 人工提交：登录侧"无登录界面"/注册侧"无注册界面"（2026-08-16）

结构化方法填词按侧区分"无界面"选项：登录审核勾"无登录界面"、注册审核勾
"无注册界面"，勾选即表示该站没有对应入口（同一 no_web 语义，数据层不变）。

### 32. 测量自动化与指标优化（2026-08-16，用户选定 1/2/4）

**第4项：波动站自动稳定**（scripts/run_measurement.py）：
新增 `--retry-unknown N`：主跑后对 unknown/error 记录自动重跑 N 轮，每轮后
对有效结果做多数投票，出现 ≥2 票多数即稳定落盘（不再依赖人工数轮仲裁）。

**第2项：方法覆盖度指标**（webapp/app.py + 前端）：
新增 `method_coverage` 聚合——人工结构化勾选的方法要素（口令/验证码/扫码/
第三方/无界面）里，程序方法清单识别出的比例（按方法数加权）。登录/注册
分开统计，网站头部展示"方法覆盖度 登录 X% / 注册 Y%（found/total）"。
当前数据样本量小（结构化人工提交刚上线），数字会随核验增多趋稳。

**第1项进行中**：85 个"未复现弹窗"站深度探测（hover 展开 + 多轮重试，
3 路并行）。

### 33. 深度探测完成，审计升级（2026-08-16）

- 85 个"未复现弹窗"站第二轮深度探测（hover 展开 + 多轮重试，3 路并行）：
  72 站补到新认证证据。
- 审计报告更新（v4_3_ground_truth_audit.md 两轮版）：✅一致 53→83 站、
  ⚠️缺方法 12 站（baidu/qq/tieba/mafengwo/pan.baidu/taptap/aliyun/cctv/
  51.com/dxy/v.qq/eastmoney）、❓深度探测仍无证据 37 站（App-first/无认证
  界面/反爬，如实记录）、🔀跳转/反爬 3 站。
- 缺方法站已用修复代码重测（zhipin 改善合并）；cctv/51/qq 等弹窗波动站
  的第三方/验证码方法需等弹窗打开的轮次才能体现，列入下轮全量验证目标。

### 34. 审核列表公开化 + 批量通过（2026-08-16）

- 待审核列表（含完整内容）从"仅管理员可见"改为所有人可见；
- 通过/删除仍需管理员口令；新增 `POST /api/reviews/batch-approve`
  （按 id 列表或 all 全量，逐条返回结果，失败不影响其余）；
- 前端：列表免口令加载，行前复选框 + "批量通过选中"；
- 审核逻辑抽成 `_approve_pending_row`（单条与批量共用）。

### 35. 口令可测性标签（inline/full/none）+ 组员文件补录 + 展示优化（2026-08-16）

1. **inline/full/none 口令框判定**：
   - 定义：inline=有口令框且不提交即可判断口令是否正确；full=有口令框但
     只有提交后才能判断；none=无口令框。
   - 人工提交表单：登录/注册/总判定三个单选；存入 structured.pwd_testability
     → manual_review.json 顶层 pwd_testability → SQLite 三列 → API/前端。
   - 站点卡片显示"口令判定 none/inline/full"徽标；详情页新增"口令判定（人工）"行。
2. **组员观察文件补录**：三份文件（前40/41-80表/81-121）覆盖 121 站，
   其中 81 站已录（已录为准不动），补录 40 站（41-80 表）到
   misc/manual_review.json（人工核验 84→124 站），含 pwd 标签。
3. **人工核验衍生报告**：新增 reports/manual/index.md（124 站总览表），
   权威数据仍在 misc/manual_review.json。
4. **方法覆盖度改名**：登录方法覆盖度/注册方法覆盖度。
5. **搜索防御**：输入 trim + 空结果提示。

### 36. v5 回归流程 + 稳定逻辑 bug 修复（2026-08-17）

用户要求两遍全量+逐站比对优化分类器。
- 启动 v5 第 1 轮（--retry-unknown 2 自动稳定）。
- **修复 --retry-unknown 数据清空 bug**：稳定阶段重写文件时先以 "w"
  截断再读旧内容，导致第 1 轮 304 条记录被清空（2026-08-17 实测）。
  改为先读后写，并抽出 `_write_stabilized` + 回归测试（127/127 通过）。
- 通用修复：`_TAB_KINDS` 新增 `qr_tab`（扫码登录/二维码登录）并加入
  全视图探索优先级（bilibili/zcool/zhipin/3dmgame 等扫码 tab 可切换）。

### 37. v5 两遍全量回归 + 逐站比对完成（2026-08-17）

用户要求：每个网站程序测一遍、我核一遍，两者比对优化分类器。
- **两遍全量**（有头 + --retry-unknown 2 自动稳定）：第 1 轮 304 条
  （修复稳定 bug 后重跑，文件完整）、第 2 轮 304 条；两轮 flow 一致率
  292/304（96%）。
- **逐站比对**（124 个已核验站）：程序方法清单 vs 人工核验描述，
  检查器含否定语义（无密码/无二维码不误判）。
- **通用修复**：qr_tab（扫码登录/二维码登录）纳入 tab 词表与全视图探索
  优先级（bilibili/zcool/zhipin/3dmgame 等扫码 tab 可切换）；
  **修复 --retry-unknown 重写清空数据的 bug**（先截断后读 → 先读后写，
  _write_stabilized + 回归测试）。
- **最终数据**：两轮仲裁（一致取第 2 轮；不一致按人工核验支持度，
  平票取第 2 轮；全失败保留旧证据——anjuke login 超时回退）。
  分布：direct_password 94、unknown 84、human_blocked 79、otp_only 28、
  no_web_signup 7、sso_only 5、email_only 3、verification_then_password 2。
- **残余差异（如实记录，不过拟合）**：约 35 站非空程序仍缺方法——多为
  隐藏折叠里的第三方（zhaopin 左上角微信等）、验证后口令（yicai/yiche/
  you.163/y.qq signup，安全边界不可达）、App-first/波动空程序 44 站。

### 38. v5 追加两遍全量（第 3、4 轮）完成（2026-08-17）

- 第 3 轮：304 条（失败 1，稳定后剩余 91 条未知/波动如实保留）。
- 第 4 轮：304 条（失败 1，稳定后剩余 89 条）。
- 四轮 flow 完全一致 282/304（93%）；不一致按多数投票仲裁，平票按人工
  核验支持度，全失败回退上一版。
- 最终数据（reports/sites/sites_latest.jsonl）：direct_password 97、
  unknown 81、human_blocked 79、otp_only 29、no_web_signup 7、sso_only 5、
  email_only 4、verification_then_password 2。决策表
  reports/archive/v5_final_decisions.md。
- 逐站比对残余差异与上轮相同性质：隐藏第三方/验证后口令/App-first 空程序
  （如实记录，不过拟合）。

### 39. 人工提交与展示调整（2026-08-17）

1. 人工提交只保留"总口令框判定（整站）"单选（inline/full/none），
   删除登录/注册单独判定；后端 ReviewRequest 同步清理。
2. 站点卡片删除"口令判定（人工）"徽标（卡片顶部只放程序测试结果）；
   详情页顶部报告表同步删除该行。
3. 人工复核对比表新增"口令政策"行：程序列显示"未测试"（TestPassword
   暂未接入，仅历史手工测过 GitHub）；人工列显示 inline/full/none
   （优先侧判定，否则用整站总判定）。

### 40. 补全 121 站 pwd 标签（2026-08-17）

此前补录只给 40 个未录入站加了 inline/full/none；文件 1/3 覆盖的 81 个
已录站在当时没有 pwd 字段所以看不到标签。本次按组员文件为这 81 站补充
pwd_testability（明确标注直接映射；"危险模式/仅登录界面"→登录 full、注册
none；未提密码框按 none），不覆盖原有方法与描述字段（已录为准）。
现有 121 站全部带 pwd 标签，reports/manual/index.md 已重新生成。

### 41. 探索点击后再观察一轮 + icourse163 诊断（2026-08-17）

- 通用改进：全视图探索时 tab 点击成功即再观察一轮（React 视图切换可能
  延迟，icourse163 手机号登录/邮箱登录/爱课程登录 tab 实测 clicked 但
  2 秒指纹窗口内视图未变）；回归验证 zhihu/bilibili 无退化、127 测试全过。
- icourse163 诊断：登录/注册均判"有口令框"（爱课程账号+密码），检测到
  短信/邮箱 tab 但因 React 渲染时序点击瞬间元素消失（与 cctv/51 同类
  已记录边界），短信验证码/邮箱视图方法未抓到——分类正确，方法不全。

### 42. 密码政策测量链路激活 + 首批 13 站实测（2026-08-18 ~ 08-23）

激活「参赛代码」侧的密码政策测量（TestPassword + site_agnostic_tester）：
- 流程：注册页发现 → 密码框定位 → 找可接受密码（admissible）→ 二分测长度
  min/max → 组合测字符类型（大小写/数字/符号、"N 类取 M"）→ permissive
  字符/序列/泄露密码。inline（内联实时反馈，判据=密码框变红/错误元素）为主，
  full-form（提交读错误）兜底。
- 输出 logs/<域名>/policy_<域名>.json（length + restrictive + permissive）。
- 安全边界：不填身份信息、不点发送验证码、不真正提交注册、不创建账号。
- 首批 13 站实测：5 站测出完整政策（百度 [8,14]、gitee [8,102]、学堂在线
  [8,16]、网易 163 [8,16]、腾讯云 [8,20]），7 站仅流程分类（游民星空/3dmgame/
  icourse163/知乎/bilibili/china/91），1 站无网页注册（aistudy666）。

### 43. 百度长度误报 min=32 修复 + 组合模型局限记录（2026-08-23）

- [x] 修复 `binary_search_min` 二分上界未截断导致的长度误报：百度真实长度
  8~14，但二分在 [0,32] 区间把 16~32 的"太长被拒"误判成"太短被拒"，一路
  顶到上界报 min=32。修复：上界截断到已确认合法的密码长度
  （`hi = min(min_interval[1], initial_len)`）。复测 min=8/max=14 正确。
- [x] 记录组合模型已知局限：百度真实政策为「字母/数字/标点至少包含 2 种」，
  引擎的 r_cmb 枚举（14/24/34/44）无法表达"任意 N 类取 M"，被近似为
  r_dig_min=1 + r_cmb34=True，代码注释标记为已知局限。

### 44. gitee 强度计误判 + xuetangx 参数矛盾修复（2026-08-23）

- [x] gitee 误落 full-form 且把"密码强度指示条"当拒绝信号：`_capture_dom_errors`
  搜索范围从整页收窄到密码框 ancestor chain + 最近 form；强度指示器
  （strength/强/弱/中）不再判为拒绝。稳定回 inline，结果 [8,102]。
- [x] xuetangx 参数矛盾（r_cmb33 与 r_cmb44 同时为 True、长度误测 9-32）：
  修复长度扩展时字符比例稀释导致的复杂度/长度混淆，复测 [8,16]。

### 45. 游民星空 placeholder 误判诊断（2026-08-23，进行中）

- [x] 诊断：游民星空密码框 placeholder「密码 (6-20位字母与数字、符号组合」
  是常驻静态文本，不是错误；密码框无客户端实时校验（边框恒灰、无错误元素），
  maxlength=20。该 placeholder 经提交前后 HTML diff（source_diff）泄漏进
  PasswordErrorParser，被中文正则（密码+字母/数字/符号/组合）误判为拒绝。
- [x] 待修 1：password_error_parser 加"政策描述型文本"过滤（`_is_policy_description`
  区分声明式 placeholder「密码(N位…组合)」与祈使式错误「密码需包含…」）；
  并修复 Layer 6 此前把 source_diff 多行拼成一段导致占位符被无关「不能为空」
  动词干扰——改为逐行 `_check_password_error`。gamersky 端到端复测通过：
  不再误报 `密码 (6-20位…`，最终走 maxlength 兜底得 `length[1]=20` +
  `_no_password_feedback=True`（游民星空密码框确实无专属反馈）。
- [x] 待修 2：find_admissible_password 候选池只含字母+数字（gen_random_str_no_symbol），
  要求符号的站永远找不到合法密码（鸡生蛋）→ 已加含符号候选（见 47）。
- [x] 待修 3：admissible 找不到时 run_password_policy_test 直接 return 空 policy
  （单点故障）→ 已降级为 maxlength 兜底（见 48）。

### 46. Chrome 152/ChromeDriver 版本不匹配修复（2026-09-03）

- [x] 背景：`SessionNotCreatedException: This version of ChromeDriver only
  supports Chrome version 150; Current browser version is 152.0.7977.65`。
  根因 `_get_shared_driver` 硬编码 `version_main=150`，且 `_find_cached_chromedriver`
  按文件大小选缓存（非版本匹配），拿到旧 150 驱动。
- [x] 修复：
  - 删除两处 `version_main=150` 硬编码，恢复 `uc.Chrome(options=...)` 默认；
  - 新增 `_installed_chrome_major()`：Windows 优先解析 Chrome 安装目录下
    `Application\<主版本>.<...>` 子目录名（比 BLBeacon 注册表可靠——后者常空），
    Linux/macOS 回退 `chrome --version`；
  - `_find_cached_chromedriver` 版本感知：命中缓存目录路径 `/<主版本>.<...>/`
    且与本机 Chrome 主版本一致才采用；
  - 经 npmmirror 镜像 `cdn.npmmirror.com/binaries/chrome-for-testing/` 下载
    152.0.7977.75 驱动（Google CDN DNS 被墙，`googlechromelabs.github.io`
    无法解析；本机无代理）。

### 47. inline 方法测试顺序 + 备选池扩充（2026-09-03）

背景：inline 方法此前先测组合（identify_combination_requirements）再测长度
（identify_min_and_max_length_limitations），组合消歧最脆弱且每步都触发
test_one_password（可能限速），放在长度前可能污染；同时备选池只有「小写+数字」，
要求符号的站（如腾讯云「需同时包含数字、字母以及特殊符号」）永远找不到合法
密码（鸡生蛋，即待修 2）。

- [x] 顺序调整（utils/site_agnostic_tester.py）：`run_password_policy_test`
  长度测试先于组合测试——长度是基础测量（二分 + 验证重试 + maxlength 兜底），
  先定死；组合放后面。长度种子用 admissible（本就不读 r_cmb*），顺序交换
  不污染长度种子。百度回归：min=8/max=14、r_dig_min=1 与改前一致。
- [x] 备选池扩充（utils/util_test_password.py）：`admissible_password_list`
  8/9/10 长度候选从「纯小写+数字」扩为四档——小写+数字（基础）、
  大写+小写+数字、小写+数字+符号、大写+小写+数字+符号，并按「先基础后加符号」
  排序（符号候选放末尾，避免污染不要求符号的站）。腾讯云回归：候选 1-8（无符号）
  全被拒「需同时包含数字、字母以及特殊符号」，候选 9 `k4m2x9a!` 被接受，
  最终 policy length=[8,20]、r_dig_min=1、r_sps_min=1、r_cmb24=True。
- [x] 待修 2 关闭：find_admissible_password 候选池加含符号候选已完成。

### 48. inline 找不到 admissible 单点故障修复（2026-09-04）

背景：`site_agnostic_tester.py::run_password_policy_test` 在
`find_admissible_password` 找不到合法密码时直接 `return` 空 policy（单点故障），
丢失「至少测出长度上限」的机会。full-form 侧早已有成熟降级
（`full_form_tester.py`：浏览器死 → 是否见过明确错误 → maxlength 兜底），
inline 侧此前缺失对应处理。

- [x] 修复（utils/site_agnostic_tester.py）：`not admissible` 分支改为三级降级——
  (1) 浏览器死 → 标 `_browser_dead` 返回；(2) 有 maxlength → `length[1]=maxlen`
  + `_no_password_feedback=True` + `_note`；(3) 无 maxlength → 按「是否见过密码
  专属拒绝信号」给诚实 note（真实表单但组合超出备选池 / 无拒绝信号无法验证）。
  输出字段（`_no_password_feedback`/`_note`/`length[1]`）与 full-form 口径对齐。
- [x] 关键决策：只用 maxlength 兜底（浏览器强制截断的硬上限，属实际政策），
  不解析 placeholder 里的「N-M位」——placeholder 是静态提示文本，违反
  「以密码框变红拒绝为准」铁律。
- [x] 验证：`py_compile` 通过；改动全在 `not admissible` 分支内，正常站点
  （找到 admissible 的）结构性不受影响。降级分支端到端触发需
  「inline 判定 + 备选池全失败」站点，当前环境无稳定目标，待实测触发。
