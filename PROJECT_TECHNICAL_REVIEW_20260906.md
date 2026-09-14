# 项目技术全景、当前进度、原始代码对比与后续路线

> 文档日期：2026-09-06  
> 当前版本：v4（不得自行升级为 v5）  
> 用途：组会/教师汇报、组员交接、后续代码审查与研究路线讨论  
> 状态：基于当前代码、线上 `/api/stats`、正式 JSONL、303 站实验档案和学长原始压缩包逐项核对  

---

## 1. 一句话结论

本项目已经从学长最初的「GitHub 单站口令突变实验代码」，扩展为一个在明确安全边界下运行的「登录/注册流程分类 + inline 口令政策测量 + 批量回归 + 人工核验 + Web 展示 + 三端数据同步」研究原型。

当前可以演示，也有真实数据和可解释证据，但还不能宣称为通用、稳定、竞赛完成态系统。最需要优先处理的不是页面美化，而是两个结构性瓶颈：

1. 登录和注册执行链没有真正分离，部分批量口令实验甚至把第二次注册测量标成了 login。
2. 人工确认的 inline 站点很多，但从「找到入口」到「完整政策」存在多层漏斗；25 个人工标记的 signup inline 站中，修复后全量只恢复 7 个，恢复率 28.0%。

---

## 2. 本文的数据依据和口径

本文将「事实」「代码证据」「推论」分开。主要依据如下：

| 数据源 | 用途 | 当前快照 |
|---|---|---:|
| `misc/measure_version.txt` | 当前测量版本 | v4 |
| `reports/sites/sites_latest.jsonl` | 本地正式程序结果 | 307 条、154 个 hostname |
| `misc/manual_review.json` | 人工核验权威数据 | 125 站已核验 |
| 线上 `/api/stats` | 当前展示站统计 | 155 站、125 站已核验、0 待审核 |
| `reports/archive/full303_policy_20260829.jsonl` | 303 站历史口令全量 | 606 条、7 条错误、17 个政策站 |
| `reports/archive/headless_postfix_round1_20260904.jsonl` | Chrome 修复后第一轮 | 606 条、6 条错误、15 个政策站 |
| `reports/archive/headless_postfix_round2_20260905.jsonl` | Chrome 修复后第二轮 | 12/606 后中断 |
| 学长 `MyAutomaticPolicy-main.zip` | 原始代码基线 | 2024-01-25，45 个实际文件 |
| 自动测试 | 当前代码级回归 | 162 项通过 |

重要口径：

- `reports/sites/sites_latest.jsonl` 是正式数据。
- `reports/archive/` 是实验档案，未验收的轮次不得覆盖正式数据。
- Web 的 SQLite 只是可重建索引，不是权威源。
- `unknown` 是证据不足的拒答，不等同于程序判断错误。
- 线上 155 站而本地正式数据 154 站，说明服务器可能有 1 个尚未回流 Mac 的网页增量，后续同步前必须核对。
- 303 站口令档案的 login 行存在执行链标签问题，不能直接作为真正登录测量结论，详见第 10 节。

---

## 3. 项目目标和安全边界

### 3.1 项目要解决的问题

项目希望自动回答两个层次的问题：

1. 网站的登录和注册流程属于什么类型？
2. 如果注册时可以安全到达口令框，网站对口令长度、字符组成和其他属性有什么要求？

完整目标链为：

```text
输入网站 URL
  ↓
寻找登录/注册入口、弹窗、Tab、新窗口、iframe
  ↓
记录页面状态和安全可达认证方式
  ↓
分类登录/注册流程
  ↓
注册上下文中是否到达口令框？
  ├─ 否：输出分类、方法和阻断证据
  └─ 是：尝试安全 inline 口令政策测量
          ↓
       负对照 → 可接受基准 → 长度 → 组合 → 自洽/OR → 允许项
          ↓
结构化 JSONL → SQLite → Web 展示 → 人工核验
```

### 3.2 不允许突破的边界

公开网站默认必须满足：

- 不填写真实姓名、手机号、邮箱或身份证信息。
- 不发送短信/邮箱验证码。
- 不扫码，不在 App 中确认。
- 不绕过图片、滑块或其他人机验证。
- 不提交登录/注册表单，不创建账号。
- 可以安全点击入口、切换 Tab、展开菜单和执行不提交表单的导航。
- inline 测量只操作口令框。
- 没有可靠反馈时必须返回无法判断，不能把「没有观察到拒绝」直接当作接受。
- full-form 默认关闭，只有环境开关和精确 hostname 白名单同时命中才允许。
- 每个口令探针必须是 `accepted`、`rejected`、`inconclusive` 三态之一。
- Web 入口必须拒绝内网、保留地址和非 80/443 端口，保持 SSRF 防线。

这意味着部分提交后才校验、验证码后才设置密码的网站，在当前公开测量边界内本来就不可完整测量。覆盖率不能通过越过安全边界来换取。

---

## 4. 当前系统架构

```text
┌─────────────────────────────────────────────────────────────────┐
│ 输入：网页现场任务 / 单站 CLI / 批量站点清单                    │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 浏览器与入口层                                                   │
│ _get_new_driver → LoginLinkDiscovery → navigator                │
│ 处理 Chrome、代理、无头模式、入口、Tab、弹窗、iframe、新窗口     │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 分类层                                                           │
│ page_detector → SignupFlowClassifierEngine → classifier         │
│ 输出 PageState、flow_type、methods、blockers、evidence           │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 口令政策层（仅注册口令，且只在可安全测时进入）                   │
│ SitePasswordPolicyTester → TestPassword                         │
│ 负对照、候选、长度、组合、自洽、OR、允许字符和泄露口令           │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 数据与验收层                                                     │
│ archive → 两轮比较/仲裁 → sites_latest.jsonl → SQLite            │
└──────────────────────────────┬──────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ 展示与协作层                                                     │
│ FastAPI + 单页前端 + 人工核验 + 服务器定时同步                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. 目录和代码结构

### 5.1 根目录

| 文件/目录 | 作用 | 当前地位 |
|---|---|---|
| `main.py` | 单站完整注册分类和口令政策测量入口 | 当前口令主链 |
| `form_detector.js` | 早期嫁接的表单检测入口 | 保留，需按调用链判断 |
| `signup_flow_classifier/` | 登录/注册流程分类器 | 当前分类核心 |
| `utils/` | 学长遗留基础 + 当前浏览器、入口和口令算法 | 新旧混合核心 |
| `full_form_tester/` | 全表单提交探测 | 新增但默认禁用 |
| `scripts/` | 批量、比较、选优、建库、同步、审计 | 当前工程主链 |
| `reports/` | 正式结果、逐站报告和实验档案 | 权威数据与证据 |
| `misc/` | 版本、站点清单、人工核验和搜索关键词 | 权威配置/人工数据 |
| `webapp/` | API、前端、SQLite和服务器同步 | 当前展示系统 |
| `tests/` | 单元/回归测试 | 当前 162 项通过 |
| `tools/diagnostics/` | 百度等站点的真实页面诊断脚本 | 研究诊断辅助 |
| `logs/` | 单站运行日志和政策 JSON | 运行产物，不是正式库 |

### 5.2 分类器核心

| 文件 | 作用 |
|---|---|
| `signup_flow_classifier/flow_types.py` | 定义 `FlowType`、`StopReason`、`UIType`、`PageState`、`MethodResult`、`FlowResult` |
| `page_detector.py` | 检测字段、Tab、扫码、SSO、协议、验证码、人机验证、页面形态和 iframe |
| `navigator.py` | 安全点击入口/Tab/下一步，处理 hover、链接兜底、新窗口和 iframe |
| `classifier_engine.py` | 有界状态探索、慢渲染等待、全视图遍历和注册上下文守卫 |
| `classifier.py` | 根据状态序列确定 `flow_type`，生成数据层 `aggregate_methods()` 和展示层 `combo_methods()` |
| `browser_failures.py` | 区分访问拒绝、限流、服务器错误、空白页、验证码和浏览器死亡 |
| `evidence.py` | 记录步骤和最终证据 |
| `policy.py` | 生成分类层的 authentication/measurement 摘要 |

当前分类类型：

| flow_type | 含义 |
|---|---|
| `direct_password` | 安全可达页面直接出现长期口令框 |
| `identifier_then_password` | 先输入账号标识，之后出现口令 |
| `verification_then_password` | 先短信/邮箱验证，之后设置口令 |
| `otp_only` | 只确认一次性验证码路线 |
| `email_only` | 只确认邮箱路线，未确认口令或验证 |
| `multiple_methods` | 多种主认证方式并存的历史主类型 |
| `sso_only` | 只确认第三方 SSO/OAuth |
| `human_blocked` | 被验证码、滑块、扫码、App确认等阻断 |
| `no_web_signup` | 有充分证据认为没有网页注册入口 |
| `unknown` | 页面已打开但证据不足，拒绝猜测 |

### 5.3 口令政策核心

| 文件 | 作用 |
|---|---|
| `utils/login_link_discovery.py` | 从首页寻找注册页、弹窗、Tab、新窗口和 iframe 口令框 |
| `utils/site_agnostic_tester.py` | 编排政策阶段，保存中间 checkpoint |
| `utils/util_test_password.py` | Chrome、inline 反馈、三态探针、候选、长度、组合、自洽和 OR 规则 |
| `utils/js/form_detection_addons.js` | 浏览器侧字段/反馈观察和 MutationObserver |
| `utils/PasswordPolicy.py` | 学长原始口令政策数据模型，当前仍保留 |
| `full_form_tester/` | 填写其他字段并尝试提交的高风险路径，公开站默认关闭 |

### 5.4 数据和批处理

| 文件 | 作用 |
|---|---|
| `scripts/run_measurement.py` | 批量执行、并发、超时、断点续跑、失败熔断 |
| `scripts/compare_measurement_rounds.py` | 两轮结果差异比较 |
| `scripts/select_measurement_results.py` | 从多轮中筛选稳定记录 |
| `scripts/finalize_measurement_data.py` | 将验收候选提升为正式数据 |
| `scripts/site_data_store.py` | JSONL/人工数据加锁、原子 upsert |
| `scripts/build_site_database.py` | 正式 JSONL + 人工核验 → SQLite |
| `scripts/generate_profiles.py` | 生成逐站档案和汇总报告 |
| `scripts/audit_program_vs_manual.py` | 程序/人工差异审计 |
| `scripts/pull_web_data.py` | 从服务器导出并合并网页新增数据 |
| `scripts/snapshot_data_changes.py` | 服务器同步前快照网页增量 |

### 5.5 Web 系统

| 文件 | 作用 |
|---|---|
| `webapp/app.py` | FastAPI API、统计、对照、任务队列、入库、人工审核 |
| `webapp/static/index.html` | Bootstrap 单页前端，无 Node 构建 |
| `webapp/sites.db` | 可重建 SQLite 索引，非唯一数据源 |
| `webapp/server_sync.sh` | 服务器快照增量、pull、回放、建库、重启和 push |
| `webapp/DATA_FLOW.md` | Mac/GitHub/服务器数据关系 |
| `webapp/DEPLOY.md` | 部署说明，部分 v3 文案已过期 |

### 5.6 数据层/展示层铁律

- `aggregate_methods()` 生成引擎原始方法记录，写入 JSONL。
- `combo_methods()` 只在 API 返回时生成用户视角组合。
- `reports/` 和 `misc/` 是数据层，不能为改显示批量重写。
- SQLite 可以重建，不能反向覆盖权威 JSONL。
- 单侧 login 入库不能抹掉已有 signup，反之亦然。
- 未完成两轮回归和差异复核，实验档案不能覆盖 `sites_latest.jsonl`。

---

## 6. 当前项目能做什么

### 6.1 登录/注册分类

当前能处理的通用结构包括：

- 首页直接登录/注册入口。
- 首页只有登录，注册藏在登录弹窗中。
- 注册入口是 Tab、链接、SPA 状态、新窗口或 iframe。
- React/Vue 异步渲染。
- 密码、短信、邮箱、扫码和 SSO 多视图。
- hover 菜单、抽屉、协议弹窗和页面内挂件。
- 第三方按钮文字位于 `alt`、`title` 或 aria 属性。
- 机构注册、备案链接和正文弱文本误点防御。
- 安全可达范围内的多种认证方法记录。
- 验证码、扫码、滑块、App确认等阻断识别。
- 无法判断时保留 `unknown`，不伪造结论。

### 6.2 inline 口令政策测量

当前在有可靠前端即时反馈的网站上可尝试测量：

- 最小长度和有界最大长度。
- 是否要求字母开头。
- 大写、小写、数字、符号最少数量。
- 部分 k-of-n 字符组合。
- 部分 OR 规则。
- 特殊字符、空格等允许性。
- 重复和连续序列。
- 短口令、长口令。
- 部分泄露口令拒绝。
- 每个候选的接受/拒绝/无法判断证据。

当前不会把强度计或提示文字单独作为真值。综合观察：

- HTML5 validity/validationMessage。
- `aria-invalid`。
- error/invalid class。
- 红色边框或样式状态。
- 密码框附近的错误文本。
- DOM MutationObserver。
- 字段值是否被网站清空或改写。
- 异步状态是否稳定。
- 错误是否来自其他字段。

### 6.3 批量与协作能力

- 多站点、login/signup 双侧批量运行。
- 多进程、单站超时、断点续跑。
- Chrome 启动错误连续熔断。
- unknown/error 多轮重测。
- 两轮比较和差异仲裁。
- 程序结果、人工核验、历史版本和统计展示。
- Web 异步现场分类和政策任务。
- 管理员加入正式 JSONL 和 SQLite。
- 服务器定时同步 GitHub，Mac 后续 pull 回流。

---

## 7. 与学长原始代码的详细对比

### 7.1 总体变化

| 维度 | 学长原始代码 | 当前项目 |
|---|---|---|
| 可运行目标 | `github.com` 写死 | 任意 URL、多站点、站点清单 |
| 主入口规模 | `main.py` 32 行 | `main.py` 1038 行 |
| 口令核心规模 | `util_test_password.py` 1341 行 | 3137 行 |
| 表单发现 | APDriver BFS 深度2 | 通用入口发现 + 分类器状态探索 |
| 登录/注册结果 | 找到 form 后打印 URL | 流程类型、方法、门槛、状态、证据 |
| 口令测试 | GitHub 固定 URL/选择器 | 动态注册页、XPath、iframe、共享 driver |
| 探针结论 | True/False | accepted/rejected/inconclusive |
| 浏览器 | 每个候选新建 Chrome | 同站复用、版本匹配、进程保护 |
| 输出 | 日志中的 Python dict | JSON/JSONL、正式库、档案、Web |
| 批量回归 | 无 | 303 站 × login/signup、比较、仲裁 |
| 人工核验 | 无 | 125 站人工结果和程序对照 |
| Web/API | 无 | FastAPI、任务、审核、统计、历史 |
| 自动测试 | 一个 GitHub 实验脚本 | 15 个测试模块、162 项通过 |

### 7.2 学长原始可执行逻辑

原始 `main.py` 核心为：

```python
target = "github.com"
ap_driver.crawl_init(target, bfs=True, depth=2, follow=[Regexes.AUTH])
while ap_driver.crawl_next():
    login_forms, signup_forms = ap_driver.get_account_forms()
```

它负责爬取和发现 form，但没有把发现、政策测量和结构化输出接成通用链。

原始 GitHub 测试写死：

- `https://github.com/signup`
- `user[email]`
- `user[password]`
- `signup-continue-button`

每个候选都会新建 Chrome、填写随机邮箱、点击 Continue、填写口令，再根据按钮是否可用判断接受/拒绝。

### 7.3 当前对原始算法的继承

以下部分完整或基本保留：

- `utils/PasswordPolicy.py`
- `utils/Regexes.py`
- `utils/URLUtils.py`
- `utils/forms/Form.py`
- `utils/forms/FormElement.py`
- `utils/creation_policy_utils/CreationPolicy.py`
- `utils/login_policy_utils/LoginPolicy.py`
- `utils/js/scripts.js`
- 泄露密码和词典文件

深度修改但仍继承学长思想的部分：

- `utils/util_test_password.py`
- `utils/APDriver.py`
- `utils/browser/CAPDriver.py`
- `utils/util_str_generator.py`

因此准确表述不是「完全重写」，而是：

> 学长提供了爬虫、表单抽象、口令政策字段和候选变异方法；当前项目补齐并重构了通用入口、流程分类、可信证据、安全边界、批量验收、数据闭环和展示系统。

### 7.4 口令算法的关键修正

1. 增加一字符负对照；负对照不成立时停止推断。
2. 从布尔结果改为三态证据。
3. 不再每个候选启动一个浏览器。
4. 从 GitHub 固定选择器改为动态 XPath 和 iframe 路径。
5. 将长度测量移到组合测量之前，避免长度拒绝污染字符结论。
6. 候选从旧的 6～10 位模板改为 8～32 位二/三/四类分层候选。
7. 特殊符号探针使用等长替换，避免同时改变长度和字符类。
8. 在阶段之间反复验证负对照和可接受基准。
9. 增加自洽检查，发现当前模型无法表达的约束。
10. 增加有限 OR 规则探测，GitHub 的长度替代分支可精确到 15。
11. 没有有限最大长度证据时输出 `None`，不把固定搜索上界 128 当真实上限。
12. 异步 `Verifying…`/`Validation failed` 等状态等待稳定再解释。

---

## 8. 当前正式数据和线上表现

### 8.1 本地正式库

`reports/sites/sites_latest.jsonl` 当前为：

| 项目 | 数量 |
|---|---:|
| 总记录 | 307 |
| hostname | 154 |
| signup | 154 |
| login | 153 |
| error | 0 |
| 正式 `pwd_policy` | 1 |

缺少的 login 侧是 `163.com`；其 signup 正式记录包含一份 inline `pwd_policy`。

正式分类分布：

| flow_type | login | signup |
|---|---:|---:|
| direct_password | 66 | 34 |
| human_blocked | 32 | 47 |
| otp_only | 11 | 18 |
| unknown | 40 | 41 |
| no_web_signup | 0 | 7 |
| verification_then_password | 0 | 2 |
| sso_only | 2 | 3 |
| email_only | 2 | 2 |

### 8.2 线上人工对照指标

线上当前 155 站，125 站已人工核验，0 待审核。

| 指标 | login | signup |
|---|---:|---:|
| match | 77 | 73 |
| mismatch | 15 | 17 |
| evaluated | 92 | 90 |
| verified | 125 | 125 |
| 条件正确率 | 83.7% | 81.1% |
| 覆盖率 | 73.6% | 72.0% |
| 程序证据不足 | 28 | 31 |
| 人工证据不足 | 5 | 4 |

条件正确率计算：

```text
login  = 77 / (77 + 15) = 83.7%
signup = 73 / (73 + 17) = 81.1%
```

如果把所有已人工核验站点作为分母，端到端正确覆盖为：

```text
login  = 77 / 125 = 61.6%
signup = 73 / 125 = 58.4%
```

这两个数字更能反映「随机给一个人工核验站，程序最终能否给出正确明确结论」。因此后续汇报必须同时给出条件正确率、覆盖率和端到端正确覆盖，不能只报告 83.7%/81.1%。

方法级人工样本目前较少：

| 指标 | login | signup |
|---|---:|---:|
| 样本站点 | 11 | 11 |
| 人工确认方法总数 | 31 | 17 |
| 程序找到 | 23 | 12 |
| 方法覆盖率 | 74.2% | 70.6% |

11 站样本不足以支持很强的方法级泛化结论。

---

## 9. 303 站口令政策实验进度

### 9.1 历史 303 站全量

`full303_policy_20260829.jsonl`：

| 项目 | 数量 |
|---|---:|
| 站点 | 303 |
| 标签记录 | 606 |
| 运行错误 | 7 |
| 最终 inline 政策记录 | 33 |
| 唯一政策站 | 17 |
| signup 标签 direct_password | 48 |
| signup 标签完整 inline | 16 |
| signup direct_password → 完整政策 | 33.3% |
| 全站 → 唯一完整政策 | 5.6% |

17 个唯一政策站包括：腾讯云、网易系、百度/贴吧、ali213、DNSPod、Gitee、凤凰、Khan Academy、酷我、LinkedIn、同程、起点、七牛、Roblox 等。

### 9.2 Chrome 修复后第一轮

`headless_postfix_round1_20260904.jsonl`：

| 项目 | 数量 |
|---|---:|
| 站点 | 303 |
| 标签记录 | 606 |
| 有效 JSON | 606 |
| 运行错误 | 6 |
| 最终 inline 政策记录 | 28 |
| 唯一政策站 | 15 |
| signup 标签 direct_password | 41 |
| signup 标签完整 inline | 15 |
| signup direct_password → 完整政策 | 36.6% |
| 全站 → 唯一完整政策 | 5.0% |

6 条错误：

- `www.ly.com login`：worker 无结果。
- `www.21jingji.com login`：worker 无结果。
- `www.linkedin.com signup`：900 秒超时。
- `www.booking.com login`：worker 无结果。
- `lichess.org signup/login`：两侧均 900 秒超时。

本轮没有再出现 macOS Chrome 系统级崩溃。

### 9.3 Chrome 修复后第二轮

`headless_postfix_round2_20260905.jsonl`：

- 计划 606 条。
- 实际写入 12 条，覆盖 6 站。
- 12 条均为有效 JSON，0 运行错误。
- 之后执行会话退出。
- 已按用户要求停止，不续跑。
- 因第二轮不完整，当前没有修复后两轮全量差异报告。

因此目前不能声称「最新程序已完成两轮全量稳定性验收」。

---

## 10. 核心结构问题一：登录和注册没有真正分离

### 10.1 分类任务先统一执行注册发现

当前 `scripts/run_measurement.py::classify_one(site, kind)` 无论 `kind` 是 login 还是 signup，都会先运行：

```python
discovery = LoginLinkDiscovery(driver)
signup_url = discovery.navigate_to_signup(site)
result = engine.classify(signup_url, entry_kind=kind, ...)
```

Web 的 `_run_live_classification(url, kind)` 也执行相同逻辑。

后果：

- login 任务可能从注册页或注册弹窗开始。
- 登录入口没有独立的 discovery 过程。
- 注册 Tab、注册 URL 和登录上下文可能互相污染。
- 只有登录而没有注册的网站可能被不必要地引向注册兜底。
- login/signup 状态序列容易过度相似。
- 登录准确率难以通过局部关键词修补继续提高。

### 10.2 `--measure-policy` 分支完全忽略 `kind`

更严重的是：开启 `--measure-policy` 后，批量代码直接调用：

```python
result = test_single_site(site, method="auto")
```

`main.test_single_site()` 只运行注册发现、注册分类和注册口令政策，并不接受 `kind`。

外层随后仍使用原任务的 `entry_kind` 写记录。因此：

```text
signup 行 = 一次注册测量
login 行  = 另一次注册测量，但标签写成 login
```

量化证据：

| 档案 | 成对站点 | 核心字段相同 | states 完全相同 | policy 完全相同 |
|---|---:|---:|---:|---:|
| 历史303全量 | 303 | 272（89.8%） | 261（86.1%） | 279（92.1%） |
| 修复后第一轮 | 303 | 268（88.4%） | 264（87.1%） | 278（91.7%） |

并非 100% 相同，是因为两次注册运行会受网络、时序、页面变体和反爬影响，而不是因为分别测了登录和注册。

结论：

- 两个303站口令档案的 login 行不能用来研究真实登录流程。
- “28条 inline”不能解释为28个独立登录/注册政策，只对应15个唯一站点的重复注册尝试。
- 这个问题修复前不应继续新一轮全量政策回归。
- 旧档案应保留为证据，但要在元数据/文档中标记 login 标签污染，不能删除后假装不存在。

### 10.3 登录正确率的其他结构原因

线上15个 login mismatch 中，程序主类型分布：

| 程序类型 | 数量 |
|---|---:|
| human_blocked | 9 |
| otp_only | 3 |
| direct_password | 1 |
| email_only | 1 |
| sso_only | 1 |

这说明大量错误不是简单的关键词漏识别，而是：

1. 自动化浏览器先遇到 CAPTCHA/滑块，人工正常浏览器看到认证路线。
2. `flow_type` 同时承担「认证方法」和「停止状态」两个角色。
3. 多种认证方式被压成一个主类型，人工却记录了完整方法集合。
4. 入口、IP、无头模式、语言和时间造成页面差异。
5. 人工核验可能来自另一天或不同环境，网站已改版。

例如 `pan.baidu.com` 人工记录扫码/手机验证码，程序首先看到的是全页人机验证，主类型成为 `human_blocked`。程序可能正确记录了“被验证挡住”，但并没有达到人工看到的认证视图。此时不能只靠修改最终映射提高正确率。

---

## 11. 核心结构问题二：人工 inline 很多，完整政策很少

### 11.1 人工 inline 基线

`misc/manual_review.json` 中 125 个已核验站点的 `pwd_testability`：

| 人工口令可测性 | login | signup |
|---|---:|---:|
| inline | 25 | 25 |
| full | 31 | 23 |
| none | 65 | 73 |
| 缺失 | 4 | 4 |

人工明确标记为 signup inline 的 25 站为：

```text
cloud.tencent.com, pan.baidu.com, tieba.baidu.com,
www.10jqka.com.cn, www.12306.cn, www.163.com, www.52pojie.cn,
www.58.com, www.acfun.cn, www.cctv.com, www.china.com,
www.cnblogs.com, www.gitee.com, www.ifeng.com, www.ly.com,
www.pcauto.com.cn, www.pconline.com.cn, www.people.com.cn,
www.pinduoduo.com, www.qyer.com, www.suning.com, www.vip.com,
www.zol.com.cn, y.qq.com, you.163.com
```

### 11.2 自动全量对人工 inline 的恢复率

| 档案 | 人工 inline 总数 | 自动得到完整政策 | 恢复率 |
|---|---:|---:|---:|
| 历史303全量 | 25 | 7 | 28.0% |
| 修复后第一轮 | 25 | 7 | 28.0% |

修复后第一轮恢复的7站：

| 站点 | 长度结果 |
|---|---|
| `cloud.tencent.com` | `[8,20]` |
| `tieba.baidu.com` | `[8,14]` |
| `www.163.com` | `[8,16]` |
| `www.cnblogs.com` | `[8,50]` |
| `www.gitee.com` | `[8,102]` |
| `www.ly.com` | `[6,18]` |
| `you.163.com` | `[8,16]` |

未恢复的18站：

| 站点 | 修复后第一轮 signup 标签结果 | 主要掉落阶段 |
|---|---|---|
| `pan.baidu.com` | unknown / classified_only | 入口或访问环境 |
| `www.10jqka.com.cn` | unknown / classified_only | 入口/分类 |
| `www.12306.cn` | direct_password / classified_only | 政策结果不可信 |
| `www.52pojie.cn` | no_web_signup / classified_only | 注册入口错误 |
| `www.58.com` | no_web_signup / classified_only | 注册入口错误 |
| `www.acfun.cn` | no_web_signup / classified_only | 注册入口错误 |
| `www.cctv.com` | email_only / classified_only | 未到注册口令视图 |
| `www.china.com` | direct_password / hint-only | 仅提取 `[8,20]` 页面提示 |
| `www.ifeng.com` | human_blocked / classified_only | 自动化阻断 |
| `www.pcauto.com.cn` | direct_password / hint-only | 仅提取 `[8,16]` 页面提示 |
| `www.pconline.com.cn` | otp_only / classified_only | 未到口令视图 |
| `www.people.com.cn` | unknown / classified_only | 注册页发现失败 |
| `www.pinduoduo.com` | unknown / classified_only | 入口/商家路线 |
| `www.qyer.com` | direct_password / classified_only | 政策结果不可信 |
| `www.suning.com` | human_blocked / classified_only | 自动化阻断 |
| `www.vip.com` | direct_password / hint-only | 仅提取 `[8,20]` 页面提示 |
| `www.zol.com.cn` | direct_password / classified_only | inline/政策阶段无明确记录 |
| `y.qq.com` | sso_only / classified_only | 未找到本站口令路线 |

对这18站进一步分解：

| 掉落位置 | 站点数 | 占18站 |
|---|---:|---:|
| 在到达 direct_password 前掉落 | 12 | 66.7% |
| 已到 direct_password，但未形成完整政策 | 6 | 33.3% |

这说明「最终政策少」的最大瓶颈首先是入口、分类、注册上下文和口令框可达性，而不只是最后的候选密码算法。

### 11.3 为什么“看见红框”不等于“能测完整政策”

真实漏斗是：

```text
人工看到密码框即时反馈
  ↓
自动浏览器是否找到相同注册入口
  ↓
是否确认这是注册口令而非登录口令
  ↓
探索结束后能否重新定位相同口令框
  ↓
一字符负对照是否产生密码专属拒绝
  ↓
能否找到至少一个可接受候选
  ↓
负对照和基准是否能重复稳定
  ↓
长度测试是否单调、未受字符规则污染
  ↓
组合规则是否能被当前模型表达
  ↓
整个过程中页面是否未限流、未漂移、未崩溃
  ↓
完整可信政策
```

任何一层失败，最终都会没有完整 `pwd_policy`。

### 11.4 拒绝证据和接受证据不对称

inline 网站通常很容易表达「这个密码错了」：红框、错误文字、`aria-invalid=true`。但合法密码可能什么也不显示。

如果程序使用：

```text
没有红框 = 接受
```

会把页面没响应、校验没触发、其他字段门控等情况误判为接受。

当前程序要求先用一字符负对照证明通道有效，再把候选的无拒绝作为差分接受证据。这提高可信度，但显著降低覆盖率。这是安全测量的可观测性问题，不是简单再补几个正则就能彻底解决。

### 11.5 其他字段会污染密码判断

注册表单经常同时要求手机号、邮箱、验证码、确认密码、协议或用户名。在不填写这些字段的安全约束下：

- 整个表单可能统一变红。
- 密码框的 error class 可能来自整表无效。
- 用户名错误可能显示在密码框附近。
- 下一步按钮始终 disabled，无法作为密码接受证据。
- 密码只有提交后才校验。

因此人工能看到“即时反馈”，并不保证自动程序在不提供身份信息时能把反馈可靠归因到密码本身。

### 11.6 当前结果把多个失败阶段折叠为 `classified_only`

当前主链在以下情况都会把 `method_used` 改成 `classified_only`：

- 未检测到可靠 inline。
- CAPTCHA/滑块。
- 负对照不成立。
- 找不到可接受密码。
- 控制点漂移。
- 策略自相矛盾。
- 口令框重定位失败。
- 浏览器死亡且无可信长度。

这造成研究数据丢失：最终无法准确回答“多少站检测到 inline、多少站负对照成功、多少站在候选阶段失败”。现有 note 能解释部分记录，但修复后第一轮仍有6个 direct_password 失败记录没有充分阶段说明。

### 11.7 修复后 direct_password 未出政策的记录分解

修复后第一轮 signup 标签中：

- 41个 `direct_password`。
- 15个得到完整 inline 政策。
- 26个没有完整政策。

按现有 note 粗分这26个：

| 原因 | 数量 |
|---|---:|
| inline密码专属反馈未建立 | 8 |
| 已进入政策测试但结果不可信 | 4 |
| CAPTCHA/滑块门槛 | 2 |
| 密码框重定位失败 | 1 |
| 仅提取到提示政策或其他 note | 5 |
| note 不足，无法确定失败阶段 | 6 |

该表也说明必须新增结构化漏斗字段，而不是继续依赖自由文本 note。

---

## 12. 目前已解决的重要问题

### 12.1 注册藏在登录界面中

已支持登录弹窗里的注册 Tab、链接、新窗口、SPA、iframe和多层入口。百度/pan.baidu、人民网等结构已有专门的通用守卫和回退。

结论：常见结构显著改善，但长尾网站仍会失败，25个人工inline站中仍有多个在入口阶段掉落。

### 12.2 口令候选和14步顺序

已修正：

- 分层候选。
- 长度先于组合。
- 等长符号替换。
- 负对照。
- 中间控制点。
- 自洽检查。
- 有限 OR 规则。
- 无上限输出 `None`。

结论：算法内部明显比原始版本可靠，但仍受入口、反馈可观测性和模型表达力限制。

### 12.3 GitHub矛盾政策

此前出现 `[25,51]`、`[32,25]` 等矛盾值。修复异步反馈解释后，本机安全实测为：

- 长度 `[8,72]`。
- 8位单字符类拒绝。
- `lower+digit` 可接受。
- 单类长度替代阈值15。

服务器端仍可能因GitHub限流或IP环境无法稳定到达注册页面。

### 12.4 macOS Chrome崩溃

根因包括 Chrome 152 与缓存 ChromeDriver 151 不匹配、多有头进程同时注册图形应用等。已增加：

- 浏览器/驱动主版本严格匹配。
- Chrome启动跨进程锁。
- macOS多并发默认无头。
- 有头自动限制单并发。
- 多进程驱动保护。
- 连续启动失败熔断。
- 中断时回收worker。

修复后第一轮606条未再出现系统级Chrome崩溃。

---

## 13. 当前尚未解决的问题

### P0：影响数据有效性的结构问题

1. login任务先执行 signup discovery。
2. `--measure-policy` 忽略 `kind`，login标签实际装入第二次signup结果。
3. 旧303口令档案的login侧不能作为登录研究证据。
4. 第二轮只有12/606，缺少完整两轮稳定性结论。
5. 最新Chrome修复和回归文件仍在本地未提交，GitHub/服务器不能通过pull获得。

### P1：分类器模型问题

1. `flow_type` 混合认证方法、可达性和阻断状态。
2. 多方法站点仍被主类型压缩，正确率评价可能低估部分正确识别。
3. `unknown`主要集中于入口隐藏、App-first、无网页认证、自动化隐藏和慢渲染。
4. 无头/有头、服务器/Mac、IP和语言环境会改变页面。
5. 人工核验与程序测量不是同一时间同一环境，网站改版会制造假差异。
6. 方法级结构化人工样本只有11站，证据规模不足。

### P1：口令政策测量问题

1. 人工inline恢复率仅7/25=28.0%。
2. 303站全站完整政策覆盖约5.0%～5.6%。
3. 负向拒绝证据强，正向接受证据弱。
4. 其他必填字段会造成连带invalid，反馈难以归因。
5. SPA/iframe重定位仍不稳定。
6. 多次探针会积累页面状态、限流和缓存。
7. 当前固定字段模型难以表达任意布尔条件。
8. 提交后才校验的网站在公开安全边界内不可完整测。
9. `classified_only`折叠多个失败阶段，缺少可观测漏斗。

### P2：Web和数据闭环问题

1. 后端已有正确/错误详细 `reason`，详情页没有完整显示 `comparison.reason`。
2. policy任务只要状态为done，前端就显示“口令政策测量完成”，即使 `policy_measured=false`。
3. 旧任务历史中保留修复前GitHub失败，容易误导。
4. 正式 `sites_latest.jsonl` 只有1条 `pwd_policy`，大部分政策仍只在archive。
5. 线上155站、本地154站，需要安全同步。
6. 部分Web文档仍有过期v3文案。
7. 服务当前为HTTP，没有HTTPS。

### P2：原始代码遗留技术债

1. `APDriver/CAPDriver`与新的 `_get_new_driver` 两套浏览器体系并存。
2. 多个旧模块保留但主链使用程度不清晰。
3. `site_agnostic_tester.py` 顶部仍写Node/Puppeteer流程，当前实际主链已不同。
4. 原始 `r_cmb*` 固定字段难以表达复杂策略。
5. 部分工具参数存在小瑕疵，例如分类诊断脚本 `--kind` 的 append默认值可能造成signup重复。

---

## 14. 未来技术方向

### 14.1 第一优先级：真正分离 login/signup

建议改造成：

```python
navigate_to_auth(homepage_url, entry_kind="login" | "signup")
```

或提供独立的：

```python
navigate_to_login()
navigate_to_signup()
```

要求：

- 两侧都从同一主页快照独立开始。
- login不经过注册发现器。
- signup不借用登录结果作为注册口令证据。
- 政策测量每站只运行一次，并且只挂在signup记录。
- 批量数据中不再出现“login标签的注册政策”。
- `AuthFlowClassifierEngine`替代语义偏向注册的类名和参数。

验收指标建议：

- 25个人工inline站逐站检查起始入口。
- 15个当前login mismatch逐站复测。
- login/signup状态序列相同率不能再因代码复用接近90%；相同必须有页面证据解释。
- 数据记录写入真实 `entry_kind` 执行路径。

### 14.2 重构分类结果：方法、可达性、阻断三轴分离

建议主结构：

```json
{
  "methods": [
    {"method": "phone_otp", "status": "confirmed"},
    {"method": "password", "status": "observed"}
  ],
  "reachability": "blocked",
  "blockers": ["captcha"],
  "stage": "entry",
  "primary_flow": "phone_otp"
}
```

评价分别计算：

- 入口是否找到。
- 方法集合 precision/recall/F1。
- 口令存在性准确率。
- 阻断类型准确率。
- 流程阶段准确率。
- 整体主类型准确率。

这样可以区分“程序看到了正确手机号路线但被滑块挡住”和“程序进入了完全错误页面”。

### 14.3 建立结构化口令测量漏斗

每个站点保存：

```json
{
  "password_field_reached": true,
  "password_field_relocated": true,
  "inline_feedback_detected": true,
  "negative_control_rejected": true,
  "admissible_password_found": false,
  "controls_stable": false,
  "length_completed": false,
  "composition_completed": false,
  "policy_completed": false,
  "failure_stage": "admissible_search",
  "failure_reason": "all_candidates_rejected"
}
```

下一轮才能精确报告：

```text
303站
→ 多少发现注册入口
→ 多少看到注册密码框
→ 多少确认inline
→ 多少建立负对照
→ 多少找到可接受密码
→ 多少完成长度
→ 多少完成组合
→ 多少最终可信
```

### 14.4 提升正向接受证据

在不提交表单的前提下，优先寻找状态转移：

- error class 从有到无。
- 红框从红恢复普通颜色。
- 错误文字明确消失。
- `aria-invalid` 从true稳定转为false。
- success图标或通过文案出现。
- 下一步按钮从disabled变enabled，但不点击。
- 同一候选重复两次得到相同转换。

只有出现“由明确错误状态恢复到正常”的差分，才能增强接受证据。不能简单放宽成“没红就是接受”。

### 14.5 自适应反馈等待和状态重置

建议：

- 首个负对照测出网站反馈延迟分布。
- 后续等待时间按该站延迟自适应，而不是统一固定秒数。
- 每个探针前保存表单指纹。
- 每N个探针重新打开注册视图，防状态累积。
- 对SPA使用组件重新挂载检测，而不是只复用旧XPath。
- 对iframe记录稳定frame语义而不是只记录脆弱索引路径。

### 14.6 从固定字段升级为约束表达式

当前 `r_dig_min/r_cmb24` 模型适合简单AND约束，未来可升级为：

```text
(length >= 15)
OR
(length >= 8 AND lower >= 1 AND digit >= 1)
```

进一步支持：

- 任意AND/OR组合。
- N-of-M字符类。
- 条件长度规则。
- 禁止用户名/邮箱相似。
- 字典词和语言词规则。
- 重复、连续、键盘模式。
- Unicode归一化、空格和截断。
- 泄露口令拒绝。

可以将探针选择改为主动学习：每次选择最能区分剩余候选模型的密码，减少探针数量、限流和页面漂移。

### 14.7 建立竞赛级评测集

建议从现有人工数据构建三类集合：

1. 入口分类集：125个人工站，重点补齐login/signup独立入口和方法集合。
2. inline金标准集：现有25个人工inline站，逐站记录负对照、正向证据、反馈DOM和真实政策。
3. 困难/不可测集：验证码后设密码、提交后校验、App-first、强风控站。

每站保存：

- 时间、地区、IP出口、浏览器版本、headless/headful。
- 首页和认证页截图。
- 关键DOM/可访问性树摘要。
- 人工方法集合。
- inline反馈类型和延迟。
- 真实政策来源与人工复核方法。
- 至少两轮程序结果。

### 14.8 论文/竞赛可形成的研究问题

当前数据支持进一步研究：

1. 安全边界下黑盒口令政策测量的可观测性极限。
2. 中文网站中短信、扫码、第三方和验证后设密码的生态差异。
3. 条件正确率与拒答覆盖率之间的权衡。
4. 多视图认证界面的状态图分类。
5. 基于三态证据和主动学习的低探针政策推断。
6. 自动化环境、无头模式和IP对认证页面的测量偏差。
7. 对不可越过门槛使用右删失/区间估计，而不是强行猜测政策。

---

## 15. 推荐实施顺序和量化验收门槛

### 阶段A：修复数据有效性

1. 修复login/signup入口分离。
2. 修复`--measure-policy`忽略kind。
3. 政策只存signup侧。
4. 给旧archive增加已知问题说明。
5. 新增对应单元测试。

建议验收：

- 自动测试继续全通过。
- login任务代码路径不调用`navigate_to_signup()`。
- policy批量每站只运行一次。
- login记录不含注册 `pwd_policy`。

### 阶段B：25个人工inline定向回归

当前基线：7/25=28.0%。

不要直接跑303站。先逐站记录漏斗，目标不是立即追求100%，而是让每个失败都有唯一、可审计阶段。建议第一目标：

- 25/25都有结构化failure_stage。
- 注册入口/口令框到达率明显高于当前13/25。
- 完整政策恢复率先从7/25提高到至少15/25；达不到时给出安全边界或网站行为证据。
- 同一站连续两次政策核心结论一致。

这里的15/25是建议工程目标，不是当前已达到数据。

### 阶段C：分类器小样本验收

选择：

- 15个当前login mismatch。
- 28个login程序证据不足。
- 25个人工inline站。
- 10个no-web/App-first站。

分别验证入口、方法、阻断和主类型，避免一个flow_type掩盖错误来源。

### 阶段D：两轮303站全量

只有阶段A～C稳定后再执行：

- 同一代码、同一版本v4。
- 同一站点清单。
- 同一headless/headful口径。
- 两轮完整606条。
- 比较入口、方法、阻断、漏斗阶段和政策。
- 差异项定向复测或人工仲裁。
- 验收后才决定是否提升到正式数据。

---

## 16. 如何测试一个网站

### 16.1 网页入口

打开：`http://120.53.5.132:8000`

在“输入网站主页，现场分类”区域：

1. 输入完整URL。
2. 选择注册+登录、注册、登录或测试密码政策。
3. 提交任务。
4. 在“我的测量任务”中查看队列/运行/完成状态。
5. 点击“查看”查看详细结果。

注意：

- 分类任务如果数据库已有结果，可能直接返回缓存，并非重新访问网站。
- policy任务状态done只表示任务结束，不一定测出政策。
- 真正成功需要看到 `policy_measured=true`、`method_used=inline` 和完整 `length/restrictive/permissive`。
- `classified_only`表示只完成分类。
- hint-only是页面自述线索，不是程序探针真值。
- “加入数据库”会先写正式JSONL，再更新SQLite；需要管理员口令。

### 16.2 Mac单站完整注册政策

```bash
.venv/bin/python main.py https://example.com --method auto
```

结果：

```text
logs/<hostname>/policy_<hostname>.json
```

### 16.3 只做注册分类诊断

```bash
.venv/bin/python scripts/run_classify_diag.py https://example.com
```

默认追加到 `/tmp/classify_diag.jsonl`。当前 `--kind` append默认值存在重复signup的小瑕疵，修复前不要用它做严格login-only实验。

### 16.4 自动测试

```bash
.venv/bin/python -m unittest discover -s tests -q
```

2026-09-06当前结果：162项通过。

---

## 17. 当前Git和发布状态

当前：

```text
branch: main
HEAD/origin: 7b02928
version: v4
```

本地仍有未提交修改/文件：

- `CHANGELOG.md`
- `misc/manual_review.json`（只移除测试污染的 `private.example`）
- `scripts/run_measurement.py`
- `tests/test_site_data_store.py`
- `utils/util_test_password.py`
- `tests/test_run_measurement_safety.py`
- `CURSOR_PROJECT_GUIDE.md`
- 四个最新回归档案
- 本文档

因此：

- 最新本地代码不等于GitHub已发布代码。
- 服务器不能仅靠pull获得未提交修复。
- 当前阶段按用户要求只做梳理，不继续第二轮、不提交、不push、不部署。

---

## 18. 汇报时建议使用的结论

### 18.1 可以诚实宣称的成果

> 我们在学长的口令政策变异算法基础上，构建了一个面向真实网站的安全测量平台。系统能寻找复杂登录/注册入口，记录多阶段页面和认证方法，并在不提交表单的前提下使用负对照、三态证据和自洽检查测量部分网站的inline口令政策。当前拥有303站批量实验、125站人工核验、Web展示和Mac/GitHub/服务器数据闭环。

### 18.2 不能夸大的部分

不能宣称：

- 能测任意网站完整政策。
- 最新代码已经通过两轮全量验收。
- 303档案中的login/signup政策是两套独立测量。
- 83.7%代表全部登录站都能正确识别。
- 红框出现就足以推断完整政策。
- archive中的政策已经全部进入正式网站。

### 18.3 当前最重要的研究结论

> 项目的主要挑战已经从“如何写更多站点特判”转变为“如何保证入口语义正确、如何表达多方法和阻断、如何在不提交表单时建立可靠正向证据，以及如何量化从人工inline到完整政策之间的漏斗”。现有数据中，login端到端正确覆盖为61.6%，signup为58.4%；25个人工inline站只恢复7个完整政策，恢复率28.0%；303站完整政策覆盖约5%。这些数据明确指出了下一阶段应优先修复的架构与测量科学问题。

---

## 19. 数据复核命令

正式记录数：

```bash
wc -l reports/sites/sites_latest.jsonl
```

运行测试：

```bash
.venv/bin/python -m unittest discover -s tests -q
```

查看线上统计：

```bash
curl -fsS http://120.53.5.132:8000/api/stats
```

查看当前Git状态：

```bash
git status --short --branch
git log -5 --oneline --decorate
```

两轮比较工具：

```bash
.venv/bin/python scripts/compare_measurement_rounds.py --help
```

注意：修复login/signup执行链之前，不应继续生成新的全量政策结论。

