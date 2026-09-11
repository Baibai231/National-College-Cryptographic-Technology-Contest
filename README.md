# CryptoScope AI：网站认证与口令策略智能测量平台

CryptoScope AI 是一套面向研究和授权安全评估的网站认证流程、口令策略与密码技术
测量工具。它以浏览器自动化为基础，能够寻找登录/注册入口，识别多步骤认证流程，
在证据充分时测量口令规则，并对 OAuth/OIDC、JWT、WebAuthn、MFA、账户恢复、
Session Cookie、TLS 和 HTTP 安全响应头进行被动观察。

本仓库由竞赛初版持续演进而来。目前的重点不是“强行完成注册”，而是在明确安全边界
内扩大网站覆盖率，并把成功、阻断、未知和推断证据分别记录，避免将“没有观察到”误报
为“不支持”或“允许”。

> 仅对你拥有或已获授权的网站执行测量。请控制并发和频率，遵守目标网站条款、法律法规
> 及研究伦理要求。

## 当前具备的功能

### 1. 登录与注册入口发现

- 从首页、独立认证页、弹窗、抽屉、悬停菜单和站内链接发现登录/注册入口。
- 支持 SPA 页面、延迟渲染、新窗口、同站子域名和相对链接。
- 支持开放 Shadow DOM、同源 iframe、跨域可见 iframe 和嵌套 iframe。
- 使用短文本、ARIA、HTML 属性、结构位置和同站约束综合打分。
- 排除备案链接、机构注册、正文作者卡片、广告小 iframe 等常见误报。
- 页面指纹覆盖输入框、按钮、弹窗、ARIA 展开/选中状态和 iframe，用于识别
  URL 不变化的组件状态切换。

### 2. 认证流程分类

工具分别测量注册和登录流程，输出页面状态序列、认证方式、阻断原因、置信度与证据。

| 类型 | `flow_type` | 含义 |
|---|---|---|
| A | `direct_password` | 当前安全可达页面直接出现口令框 |
| B | `identifier_then_password` | 先提供账号标识，再进入口令步骤 |
| C | `verification_then_password` | 必须先经过短信/邮箱验证，之后才能设置口令 |
| D | `otp_only` / `email_only` | 当前流程不使用长期静态口令 |
| E | `multiple_methods` | 同时观察到多种认证方式 |
| F | `sso_only` | 只观察到第三方或统一身份登录 |
| G | `human_blocked` | 被验证码、扫码、App 确认等人工环节阻断 |
| H | `no_web_signup` | 未发现可用网页注册入口 |
| I | `unknown` | 页面异常或证据不足，不能可靠分类 |

除主类型外，v4 结果还会逐项列出密码、短信、扫码、微信、QQ、Google、Apple、
GitHub 等认证方式的 `confirmed`、`blocked` 或 `observed` 状态，不再把多种方式压缩成
一个不可解释的标签。

### 3. 智能表单字段识别

- 识别 `email`、`phone`、`identifier`、`password` 和 `code` 字段。
- 综合 `type`、`name`、`id`、`placeholder`、`aria-label`、`aria-labelledby`、
  关联 `<label>`、浏览器可访问名称、`autocomplete` 和 `inputmode`。
- 支持 `type="text" + autocomplete="new-password"` 等兼容型口令控件。
- 正确识别使用 `type="tel"` 或数字键盘实现的 OTP 验证码框。
- 同页存在登录与注册表单时，优先定位 `new-password`，避免误测登录口令框。
- 排除搜索、按钮、文件、复选框、隐藏字段等非认证输入控件。
- 对动态 XPath 中的特殊字符进行安全编码。

### 4. 口令策略测量

当注册上下文中的口令框可安全到达，并且页面能够提供可信的内联校验反馈时，可以测量：

- 最小和最大长度；未找到可靠上限时输出未知，而不是把探测上界当作真实上限。
- 数字、大写字母、小写字母、特殊字符及字符类别组合要求。
- 字母开头、空格/非 ASCII 字符等限制。
- 允许的特殊字符、长短口令、常见序列和泄露口令候选。
- “较短口令需多类字符，较长口令可放宽”等 OR 组合规则。
- 页面声明的 `maxlength` 和口令提示文案，作为独立证据而非无条件真值。
- inline 与 full-form 共享 `adaptive-length-v1` 自适应长度规划器：以已确认可接受
  口令为锚点，通过二分决策选择下一次最有信息量的长度，不再线性遍历整个区间。
- 共享 `adaptive-composition-v1` 字符组成规划器：在相同长度下按字符类子集格逐层
  探测，区分“任意 N 类即可”和“某些类固定必需”，再对固定必需类二分推断最低数量。
- 自适应探测受 24 次预算限制，输出每一步搜索区间、三态结果、下一步决策和边界
  置信度；可分享的决策证据只保留长度与字符类别，不包含候选口令原文。

每次测量先建立明确拒绝的负对照，再解释其他候选的反馈。没有负对照、页面反馈不稳定、
身份字段门控或结果自相矛盾时，会输出 `inconclusive`，不会把“没有看到报错”当成接受。
测量过程按阶段保存增量结果，浏览器中途崩溃时尽量保留已确认部分。

### 5. 跨上下文与现代前端覆盖

- 主文档已有邮箱框时仍继续聚合 iframe 中的口令框，不再提前返回。
- 主文档存在阻断信号时仍收集 frame 内的认证方式和字段。
- 跨域 frame 可通过 WebDriver 切换测量；同源 frame 与开放 Shadow DOM 使用深度扫描。
- SPA 状态变化同时监视主文档和已操作的跨域认证 frame。
- 支持 Shadow DOM/iframe 内的注册 tab、密码 tab 和结构化认证入口。
- 对 `autocomplete`、关联标签和可访问名称使用统一分类逻辑。

### 6. Cookie/GDPR 遮罩安全处理

为避免海外网站的隐私横幅遮住页头入口，分类前会检查主文档和可见 iframe：

- 优先选择“仅必要 Cookie”，其次“全部拒绝”，最后才关闭明确的 Cookie 横幅。
- 支持中、英、法、德、西、意、葡、荷、日、韩、俄常见文案。
- 不点击“全部接受”、保存偏好、用户协议或注册表单提交。
- 普通协议弹窗即使存在同名“关闭”按钮，也不会被当作 Cookie 横幅处理。
- 可通过 `--no-cmp` 完全禁用；默认策略为 `REJECT_ALL`。

### 7. 密码技术被动观察

观察器复用浏览器已经访问的页面和网络事件，不为分析额外请求网站：

| 模块 | 当前能够观察的内容 | 明确不做的事 |
|---|---|---|
| OAuth/OIDC | 授权链接中的 flow、PKCE、state 等参数是否存在 | 不跟随授权、不保存参数值 |
| JWT | `alg`、`exp`、`iss`、`aud`、签名段等脱敏元数据 | 不保存 Token、不声称验证签名 |
| WebAuthn | Passkey、安全密钥和站点 WebAuthn 语义 | 不把浏览器支持冒充站点支持 |
| MFA | 当前页面观察到的认证因素和方式 | 不把并列登录方式冒充强制 MFA |
| 账户恢复 | 忘记/重置口令入口和渠道提示 | 不点击恢复入口、不发送消息、不取 Token |
| Session | 疑似会话 Cookie 的 Secure、HttpOnly、SameSite 聚合 | 不保存 Cookie 名和值 |
| TLS | HTTPS 跳转、TLS 版本、密码套件、证书有效期等 | 不另发请求、不保存证书原文 |
| HTTP Header | HSTS、CSP、nosniff、防嵌套、Referrer/Permissions Policy 等 | 不保存原始 Header 值 |

输出包含五维证据覆盖率评估，以及 CPAM Level 0--6 证据成熟度阶梯。成熟度严格区分
“连续证据支持等级”和“观察到的更高能力”：例如观察到 Passkey 可以记录 Level 5 方向
能力，但不会据此声称网站整体已经达到 Level 5。服务端口令存储、MFA 强制性、风险认证
和零信任架构在认证前页面无法可靠验证时保持未知。

详细说明见 [docs/SECURITY_OBSERVERS.md](docs/SECURITY_OBSERVERS.md)。

### 8. 批量测量、稳定化与报告

- 单站、多站和文件列表输入，支持受控并发。
- 注册、登录两侧独立测量，并支持仅分类或同时测量口令策略。
- JSON、JSONL、分站日志和阶段性 `.partial.json` 输出。
- `--resume` 断点续跑、`--only` 选择子集、`--site-timeout` 进程级超时。
- 只对浏览器崩溃、基础设施、导航、超时等瞬态失败重试。
- `--retry-unknown` 多轮复测并按有效证据多数结果稳定化。
- 结果可重建为 SQLite 查询库，并生成逐站 Markdown 报告。
- 支持结构化人工核验、程序与人工结果对照、待审核队列和历史版本。

### 9. Web Dashboard 与 API

FastAPI + 静态前端提供：

- 站点搜索、详情、分类分布、正确率和覆盖率统计。
- 注册/登录路线、逐方法证据、口令策略、被动安全观察、五维评分和 CPAM 展示。
- 同步实时分类与口令策略接口。
- 可持久化的异步任务队列，支持查询、取消排队任务和删除任务记录。
- “忽略缓存重新测量”，新结果需人工确认后才加入正式数据库。
- 管理员审核接口、JSON 导出和服务器数据同步流程。

写接口默认需要 `X-Measure-Token` 或管理员令牌；实时目标会在排队和执行前检查 DNS，
拒绝本机、私网、保留地址和非 80/443 端口。队列、Chrome 并发和 CORS 来源均可限制。

## 安全边界

默认 `auto` 模式遵守以下约束：

- 可以：浏览公开页面、点击明确的登录/注册/tab/下一步入口、处理隐私保护型 Cookie
  横幅、只向口令框填写测试候选、读取页面内联反馈。
- 不可以：填写真实邮箱或手机号、发送验证码、扫码、完成第三方授权、绕过 CAPTCHA、
  登录真实账号或创建账号。
- 无可靠内联反馈时停止为 `inline_unsupported` 或 `inconclusive`，不自动升级为提交表单。
- `full` 模式可能填写身份字段并提交，默认关闭；只有调用者显式选择 `full`，同时设置
  环境开关和精确主机白名单后才能运行。

不要根据认证前结果推断服务端口令哈希算法、登录后 Session 安全、MFA 强制执行或完整
零信任架构。所有评分必须与 `coverage`、`evidence` 和未知项一起解读。

## 环境要求

- Python 3.9+
- Chrome 或 Chromium；Windows 未安装 Chrome 时可自动回退到 Microsoft Edge
- Windows、Linux；无图形服务器建议使用无头模式
- 建议每个 Chrome worker 至少预留约 1 GB 内存，并发通常不超过 2--4

## 安装

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r webapp\requirements-server.txt
```

### Linux/macOS

```bash
python3 -m venv .venv
.venv/bin/pip install -r webapp/requirements-server.txt
```

## 使用方法

### 测量单个网站

```bash
python main.py --method auto https://example.com
```

`auto` 是推荐模式：先分类注册流程，仅在能够建立可靠内联反馈时测量口令策略。
结果保存到：

```text
logs/<hostname>/policy_<hostname>.json
```

### 测量多个网站

```bash
python main.py -c 2 https://example.com https://example.org
```

也可以创建 UTF-8 文本文件，每行一个 URL：

```bash
python main.py -i urls.txt -c 2
```

生产研究中建议先用 `-c 1` 或 `-c 2` 小规模验证，再逐步扩大范围。

### 批量分类与稳定化

```bash
python scripts/run_measurement.py \
  --input urls.txt \
  --kinds signup,login \
  --output reports/run.jsonl \
  --workers 2 \
  --site-timeout 90 \
  --retry-unknown 2
```

增加 `--measure-policy` 后，会对安全到达注册口令框的网站继续执行口令策略测量；单站可能
需要 5--15 分钟：

```bash
python scripts/run_measurement.py \
  --input urls.txt \
  --kinds signup \
  --output reports/policy_run.jsonl \
  --workers 1 \
  --site-timeout 900 \
  --measure-policy \
  --resume
```

### 显式启用 full-form

除非你控制目标网站或已获得明确授权，否则不要启用。PowerShell 示例：

```powershell
$env:PASSWORD_POLICY_ALLOW_FULL_FORM = "1"
$env:PASSWORD_POLICY_FULL_FORM_ALLOWLIST = "test.example.com"
python main.py --method full https://test.example.com
```

白名单按规范化后的完整 hostname 精确匹配，不支持通配符或后缀匹配。

### 启动 Web 平台

Windows 本地展示推荐使用一键脚本。在仓库根目录运行：

```powershell
.\webapp\run_local.ps1
```

它会自动创建环境、安装缺失依赖、合并最新版流程数据与最近一次全量口令策略数据、
重建展示数据库并打开 `http://127.0.0.1:8000`。代码或结果更新后重复运行即可；停止服务：

```powershell
.\webapp\run_local.ps1 -Stop
```

需要自定义端口、禁止自动打开浏览器或固定实时测量口令时，可分别使用 `-Port`、
`-NoBrowser` 和 `-MeasureToken`。以下是服务端或手动启动方式。

Linux：

```bash
SITES_HEADLESS=1 \
SITES_MEASURE_TOKEN='请替换为高强度随机值' \
.venv/bin/python -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
```

Windows PowerShell：

```powershell
$env:SITES_HEADLESS = "1"
$env:SITES_MEASURE_TOKEN = "请替换为高强度随机值"
.\.venv\Scripts\python.exe -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。部署到服务器前请阅读
[webapp/DEPLOY.md](webapp/DEPLOY.md) 和 [webapp/DATA_FLOW.md](webapp/DATA_FLOW.md)。

常用 API：

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/sites` | 查询已入库站点 |
| GET | `/api/sites/{host}` | 站点详情 |
| GET | `/api/stats` | 统计与覆盖率 |
| POST | `/api/classify` | 实时注册/登录流程分类 |
| POST | `/api/policy` | 实时口令策略测量 |
| POST | `/api/tasks` | 提交异步分类或口令任务 |
| GET | `/api/tasks/{task_id}` | 查询异步任务 |
| GET | `/api/export` | 导出数据 |

实时分类请求示例：

```bash
curl -X POST http://127.0.0.1:8000/api/classify \
  -H 'Content-Type: application/json' \
  -H 'X-Measure-Token: your-token' \
  -d '{"url":"https://example.com","entry_kind":"signup"}'
```

## 输出结构

主要结果字段：

```json
{
  "flow_type": "direct_password",
  "class_letter": "A",
  "confidence": "high",
  "stop_reason": "password_step_reached",
  "methods": [],
  "states": [],
  "evidence": [],
  "policy": {},
  "security_observations": {
    "collection_mode": "passive",
    "analyzers": {},
    "assessment": {},
    "maturity": {}
  }
}
```

解释结果时重点检查：

- `stop_reason`：为什么结束，而不只看最终类型。
- `confidence` 和 `evidence`：结论依据是否充分。
- `states`：每一步实际看到了哪些字段、方式和阻断。
- `policy._inconclusive`：口令策略是否因为反馈不足或状态漂移而无法确认。
- `security_observations.assessment.coverage`：评分覆盖了多少可验证证据。
- `not_observed`：表示本次安全可达范围内没有证据，不代表能力不存在。

## 本轮修复与新增功能

以下为最近一轮集中开发成果，详细变更记录见 [CHANGELOG.md](CHANGELOG.md)：

| 提交 | 修复或新增内容 |
|---|---|
| 当前开发版 | 新增自适应长度与字符组成推断；修复 Python 3.12 浏览器驱动兼容；新增 Windows 本地一键展示；历史实测口令策略正确映射到 Dashboard；新增认证语义状态/动作边去重；分类现场口令字段直接交给策略测量器；合法口令搜索覆盖扩展至 64 位且常见边界优先 |
| `a50c8e3` | 修复泄露口令结论反向、长度/组合交叉污染、无证据即接受等问题；加固公开测量接口、队列、CORS、DNS/SSRF 和任务生命周期 |
| `9b46253` | 修复主文档字段导致 iframe 提前返回、主页面阻断掩盖 frame 语义、SPA/Shadow 状态漏检和确定性失败无意义重试 |
| `4b798a7` | 新增证据约束的 CPAM 成熟度阶梯，防止跨级和服务端能力过度推断 |
| `90935f8` | 新增账户恢复入口及渠道的被动观察，不点击、不发验证码、不保存恢复 URL/Token |
| `52dc092` | 新增 autocomplete、inputmode、可访问名称和关联 label 字段识别；修复 OTP/手机号、搜索框和登录/注册口令框误判 |
| `df8ff9b` | 新增隐私优先的 Cookie/GDPR 横幅处理，覆盖多语言与 iframe |

关键修复还包括：

- `auto` 不再在内联反馈不足时自动提交完整注册表单。
- 所有候选结论必须建立在同页面负对照和明确接受/拒绝证据上。
- 无真实最大长度证据时不再把 `128` 等探测边界写成网站政策。
- OR 组合政策可以结构化输出，不再强行塞入单一 AND 模型。
- 全视图探索结束后恢复注册口令视图，减少误用隐藏登录框。
- 重复认证状态和已经尝试过的状态—tab 边会被去重，避免路线膨胀和来回振荡。
- iframe 路径随口令框定位结果传递到测量器。
- inline/full-form 合法口令候选默认覆盖 8--64 位，仍受时间预算和授权边界限制。
- 固定顺序的数字/大小写/符号突变已改为固定长度的字符类子集实验，可输出最少
  字符类数、所有已接受最小组合、固定必需类及其最低数量，并保留三态决策路径。
- Windows 本地展示会自动重建数据库并合并最近一次全量口令实测档案，旧版
  `policy + method_used` 结果也能在“口令策略”区域显示。
- 运行中任务被删除或超时后，不会被后台线程重新“复活”。
- 重试保留原始 URL/path 和站点总超时，只处理瞬态失败。
- 被动观察不保存原始 Token、Cookie、URL 参数、Header 或证书内容。

## 目录结构

```text
main.py                       单站/多站口令策略测量入口
signup_flow_classifier/       认证入口、页面状态、流程分类与安全导航
utils/                        浏览器驱动、表单发现、口令突变测试
full_form_tester/             显式授权后才可使用的全表单路径
security_observers/           OAuth/JWT/WebAuthn/MFA/恢复/Session/TLS/Header
scripts/                      批量测量、数据库构建、报告和维护脚本
webapp/                       FastAPI、Dashboard、任务队列与部署脚本
reports/                      正式结果和逐站报告
misc/                         站点清单与人工复核数据
tests/                        回归测试
docs/                         安全观察器及数据流说明
```

## 测试

```bash
python -m unittest discover -s tests
python -m compileall -q main.py signup_flow_classifier security_observers
```

当前测试覆盖流程分类、入口识别、跨 iframe/Shadow DOM、SPA 指纹、口令证据状态、
自适应长度/字符组成推断、安全观察器、评分、API 权限、任务队列、Cookie 横幅和
前端展示等关键路径；当前完整回归测试共 260 项。

## 已知限制

- 封闭 Shadow DOM 无法由普通浏览器自动化直接遍历。
- CAPTCHA、短信/邮箱验证码、扫码和 App 确认会按人工阻断停止，不会绕过。
- 部分网站只有提交后才验证口令；默认安全模式下这类网站会保持无法判断。
- 认证前 Cookie 不能代表登录后 Session；页面能力也不能证明服务端实现安全。
- 地域、A/B 实验、登录状态、浏览器指纹、限流和临时网络错误会影响结果。
- 大规模研究应进行多轮测量、保留时间戳，并对关键结论进行人工复核。
