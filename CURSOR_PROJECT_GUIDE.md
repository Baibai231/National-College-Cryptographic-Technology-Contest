# Cursor 项目完整上下文与修改指南

> 用途：交给对本项目完全没有上下文的 Cursor，用于代码审查、继续开发和验收。
> 最后更新：2026-09-04。
> 当本文与代码、`CHANGELOG.md` 或当前 Git 状态冲突时，以代码、
> `CHANGELOG.md` 和当前 Git 状态为准。实验进度会继续变化，不要只依赖文档中的行数快照。

---

## 1. 先看结论

这是一个面向中文和国际网站的「注册/登录流程分类 + 口令政策测量 +
人工核验展示」研究原型。项目不是普通的表单自动化，而是一个在明确安全边界下运行的
测量系统：

1. 打开目标网站，尽可能找到登录/注册入口、tab、弹窗、iframe 和多阶段页面。
2. 记录页面字段、验证门槛、可用方法和状态变化，生成注册/登录流程分类。
3. 如果在注册上下文中安全到达口令框，且网站会在不提交表单时给出可验证的
   inline 反馈，则用负对照和单变量探针推断口令政策。
4. 无法取得可靠证据时必须输出「无法判断/仅完成分类」，不能猜测。
5. 程序结果、人工核验和两者的正确/错误原因通过 FastAPI 网站展示。

当前版本必须保持 **v4**，除非项目负责人明确要求，不得自行升为 v5。

当前成熟度：

- 可作为「小型分类器 + 可靠拒答的 inline 口令政策测量」原型演示。
- 还不能宣称是「能测任意网站完整口令政策」的通用系统。
- 后续研究重点应是复杂约束表达、自适应探针、标准评测集和跨站稳定性，
  而不是继续堆私有站点特判。

---

## 2. 阅读顺序和信息优先级

Cursor 在修改代码前建议按以下顺序阅读：

1. `CURSOR_PROJECT_GUIDE.md`：当前总览和修改边界。
2. `CHANGELOG.md` 顶部的第 15～27 条：最新口令测量、GitHub 矛盾、两轮回归和
   Chrome 崩溃修复。
3. `HANDOFF.md` 顶部 2026-08-24 增量：数据层/展示层铁律与安全边界。
4. 当前 `git status` 和 `git diff`：工作树不干净，未提交修改都是当前任务的一部分。
5. 核心执行链：`main.py` → `signup_flow_classifier/` →
   `utils/site_agnostic_tester.py` → `utils/util_test_password.py`。
6. 批处理和数据：`scripts/run_measurement.py`、`scripts/site_data_store.py`、
   `reports/README.md`。
7. 网站：`webapp/app.py`、`webapp/static/index.html`、`webapp/DATA_FLOW.md`。

注意：`webapp/README.md`、`webapp/MAINTENANCE.md`、`webapp/DATA_FLOW.md` 和
`webapp/DEPLOY.md` 的部分段落仍写着 v3，这是过期文案。真实当前版本是 v4。
这些文档的数据流原则仍然有效，但不得照抄其「保持 v3」的句子。

---

## 3. 安全边界：最高优先级

本项目对公开网站的默认行为必须满足：

- 不填写真实姓名、手机号、邮箱、身份证或其他真实身份信息。
- 不点击「发送验证码」，不接收或猜测短信/邮箱验证码。
- 不扫码、不在 App 中确认、不绕过滑块或人机验证。
- 不提交登录/注册表单，不创建账号。
- 可安全点击入口、切换 tab、展开菜单、点击不会提交表单的「下一步」。
- inline 口令测量只操作口令框，不填身份字段，不提交表单。
- `auto` 模式只允许 inline；inline 无可靠反馈时必须回退到仅分类。
- full-form 默认完全关闭。只有同时设置
  `PASSWORD_POLICY_ALLOW_FULL_FORM=1` 且目标 hostname 精确命中
  `PASSWORD_POLICY_FULL_FORM_ALLOWLIST` 才能启用。不得将通配域名加入白名单。
- 「没有观察到拒绝」不等于「网站接受该口令」。只有当同一表单的一字符负对照
  明确被拒绝后，才能把无拒绝差分作为接受证据。
- 每个探针的结果必须是 `accepted` / `rejected` / `inconclusive` 三态之一。
- 当页面限流、访问拒绝、浏览器死亡、表单门控、负对照失败或探针自相矛盾时，
  必须拒答，不得生成看似完整的假政策。
- Web 现场分类拒绝本机、内网、保留地址以及非 80/443 端口，不得弱化这个 SSRF 防线。

任何以「提高成功率」为理由自动填身份信息、发送验证码、提交公开站表单的改动，
都是回归和越界，不是优化。

---

## 4. 整体架构与执行链

```text
站点 URL
  ↓
LoginLinkDiscovery（寻找注册页/弹窗/tab/新窗口/iframe）
  ↓
SignupFlowClassifierEngine（安全探索，形成 PageState 序列）
  ↓
classifier.py（流程类型 + 原始方法聚合）
  ↓
main.test_single_site
  ├─ 没有注册口令框 / 有门槛 / 无可靠 inline 反馈 → classified_only
  └─ 可靠 inline 反馈 → SitePasswordPolicyTester / TestPassword
         ↓
       负对照 → 可接受口令 → 长度 → 组合 → 自洽/OR → 允许项
  ↓
JSONL 测量记录
  ├─ reports/archive/（未验收的轮次）
  └─ reports/sites/sites_latest.jsonl（验收后的权威数据）
         ↓
scripts/build_site_database.py
         ↓
webapp/sites.db（可重建索引）
         ↓
FastAPI API + webapp/static/index.html
```

### 4.1 核心文件

| 文件 | 职责 | 修改风险 |
|---|---|---|
| `main.py` | 单站完整执行链：发现、分类、口令测量、可信性判断和回退 | 高 |
| `utils/login_link_discovery.py` | 寻找登录/注册入口、直接路由、弹窗、tab、iframe 口令框 | 高 |
| `signup_flow_classifier/page_detector.py` | 字段、方法、阻断、tab、SSO 提供商和页面形态识别 | 高 |
| `signup_flow_classifier/navigator.py` | 安全点击入口/tab/下一步，处理 hover、新窗口和 iframe | 高 |
| `signup_flow_classifier/classifier_engine.py` | 有界状态探索、全视图 tab 遍历、注册上下文守卫、口令框定位 | 很高 |
| `signup_flow_classifier/classifier.py` | 把 PageState 序列分类，生成数据层 methods；同时提供展示层 combo_methods | 很高 |
| `signup_flow_classifier/flow_types.py` | 分类枚举和 JSON 数据结构 | 很高，变更即 schema 变更 |
| `signup_flow_classifier/browser_failures.py` | 访问拒绝、限流、服务器错误、空白页、浏览器死亡分型 | 中高 |
| `utils/site_agnostic_tester.py` | 口令政策阶段编排和中间控制点 | 很高 |
| `utils/util_test_password.py` | Chrome 启动、inline 反馈检测、探针执行、长度/字符/组合/OR 规则 | 很高 |
| `utils/js/form_detection_addons.js` | 注册链接、字段和密码反馈的浏览器侧观察 | 很高 |
| `scripts/run_measurement.py` | 批量测量、并发进程、单站超时、断点续跑、启动失败熔断 | 很高 |
| `scripts/site_data_store.py` | 权威 JSONL/人工数据的原子 upsert 和锁 | 很高，不可破坏原子性 |
| `scripts/build_site_database.py` | 把 JSONL + 人工核验构建成 SQLite，保留历史和待审核 | 高 |
| `webapp/app.py` | API、统计、人工对照、实时测量队列、数据入库 | 高 |
| `webapp/static/index.html` | 无前端构建步骤的单页展示 | 中 |
| `webapp/server_sync.sh` | 服务器网页增量快照、pull、回放、建库、重启、push | 很高 |

### 4.2 原始组员代码与当前主链

`main.py`、`utils/`、`full_form_tester/` 中保留了早期组员的自动口令政策代码。
`signup_flow_classifier/`、`scripts/`、`webapp/` 是后续构建的分类、数据闭环与展示层。
不要因为某个文件看似「旧」就直接删除；先用实际 import/调用链确认。

`full_form_tester/` 仍在仓库中，但对公开网站默认不运行。不能为了提高覆盖率
将它恢复成 `auto` 的兜底路径。

---

## 5. 注册/登录分类器

### 5.1 分类体系

| flow_type | 含义 |
|---|---|
| `direct_password` | 安全可达页面已直接看到长期口令框 |
| `identifier_then_password` | 先填账号/邮箱/手机标识，后续步骤出现口令框 |
| `verification_then_password` | 需先通过短信/邮箱验证，后续才设口令 |
| `otp_only` | 安全可达范围内只看到一次性验证码，未看到长期口令 |
| `email_only` | 只确认邮箱路线，未观察到口令或验证 |
| `multiple_methods` | 多种主认证方式并存的历史主类型；v4 更重要的是 `methods[]` |
| `sso_only` | 只发现第三方 SSO/OAuth |
| `human_blocked` | 被短信、图形/滑块、扫码或 App 确认等人工门槛阻断 |
| `no_web_signup` | 有充分证据认为没有可用网页注册入口 |
| `unknown` | 页面已打开，但没有足够证据可靠分类 |

`unknown` 不是「错误」，而是研究结果中的诚实拒答。不得为降低 unknown 比例就把它
粗暴映射成 `no_web_signup`。

### 5.2 PageState 证据

每一步记录：

- `url`：当前 URL。
- `ui_type`：`standalone_page` / `modal` / `drawer` / `multi_step_wizard` /
  `inline_widget` / `sso_iframe` / `unknown`。
- `fields`：`email` / `phone` / `password` / `code` / `identifier`。
- `actions`：已执行动作。
- `blockers`：`captcha` / `sms_code` / `email_code` / `verification_code` /
  `slide` / `scan` / `app_confirm` / `tos` / `other`。
- `methods`：可见认证方式和 SSO 提供商。
- `available_actions`：当前可能的安全动作。
- `tabs`：口令、短信、邮箱、注册、扫码等视图。
- `note`：观察和停止原因。

`FlowResult` 除主 `flow_type` 外还有 `methods[]`。每个 `MethodResult` 包含方法名、
`confirmed/blocked/observed` 状态、置信度、门槛和出现步骤。

### 5.3 导航与长尾适配

当前已处理的通用情况包括：

- 主页只有登录入口，注册藏在登录弹窗里。
- 「立即注册」是 tab、链接、SPA 状态切换或新窗口。
- React/Vue 异步渲染慢，入口点击后需等待认证信号。
- 口令框在 iframe 或跨域 iframe 中。
- 登录/注册弹窗有扫码、短信、口令、邮箱等多个 tab。
- 第三方入口是图片/icon，文本在 `alt` / `title` / aria 属性里。
- hover 菜单、协议弹窗、抽屉和页面内挂件。
- 机构注册、备案链接、文章正文中的「登录/注册」弱文本误点防御。
- 点击导航时 JS execution context 销毁导致的 CDP 返回值丢失。
- GitHub 限流页、百度安全验证、空白认证页和服务器错误页。

仍有长尾问题：App-first、认证入口对自动化隐藏、滑块/验证码、只有提交后才
校验的口令表单、强风控和站点随时改版。

### 5.4 数据层方法与展示层方法

这是不可破坏的设计：

- `aggregate_methods()` 生成引擎原始方法记录，随 JSONL 落盘。
- `combo_methods()` 只在 Web API 返回时生成用户视角的组合方法，例如
  `手机号+验证码`、`邮箱+密码`、`第三方（微信、QQ）`。
- 不得为了改显示去重写 `reports/` 中的 methods。
- 数据文件保留详细 route/steps，展示层可以简化，但不得反向污染数据层。

---

## 6. 口令政策测量

### 6.1 什么情况才会测量

`main.test_single_site()` 先完成注册流程分类。只有当分类结果中
`signup_password_reached=True`，并能重新定位注册口令框时，才继续口令测量。

重要：登录表单中看到口令框不能当作注册口令框。这个「注册上下文守卫」是防止
把登录政策误写成注册政策的关键边界。

### 6.2 inline 反馈通道

不把「口令强度计」或「一段静态提示词」当作唯一真值。当前综合检查：

- HTML5 `validity` / `validationMessage`。
- `aria-invalid`。
- error class、可见错误文本、红色边框/样式变化。
- DOM MutationObserver 捕获动态提示。
- 口令框的值是否被站点清空或改写。
- 反馈是否位于口令框附近，避免把用户名/邮箱错误当作口令反馈。
- 页面基线快照，避免把常驻静态提示的 React 重渲染当作新反馈。
- `Verifying…` 等异步中间态需等待稳定；GitHub 的 `Validation failed`
  需持续稳定 2 秒后才能当作最终拒绝。

### 6.3 当前探针顺序

1. 一字符负对照：确认该表单确实会对明显无效口令给出拒绝反馈。
2. 在 8～32 位中按二类/三类/四类字符分层寻找可接受基准口令。
3. 在长度测量前重新验证负对照和基准。
4. 先推断最小/最大长度，再测组合约束，避免长度错误污染字符类结论。
5. 测试字母开头、大/小写、数字、符号最少数量和 k-of-n 类组合。
6. 执行自洽检查：用已推断模型解释探针，检测平面属性无法表达的 OR 规则。
7. 如果疑似 OR，有界测试各单类、两两组合和单类长度替代阈值。
8. 在进入允许项测试前再次验证控制点。
9. 通过等长替换测试特殊符号，避免同时改变长度和符号两个变量。
10. 测试允许字符、重复/连续序列、长短口令和泄露口令拦截。

任意中间控制点漂移，后续结论必须停止或标记 inconclusive。

### 6.4 口令政策输出

实测政策的主结构：

```json
{
  "length": [8, 72],
  "restrictive": {
    "r_l_start": false,
    "r_dig_min": 1,
    "r_upp_min": 0,
    "r_low_min": 1,
    "r_sps_min": 0,
    "r_cmb24": false,
    "r_cmb34": false,
    "r_cmb44": false
  },
  "permissive": {
    "permitted_characters": {},
    "permitted_sequences": {},
    "short_and_long_password": {},
    "breached_password": {}
  },
  "_probe_evidence": [],
  "_or_rule": {},
  "_inconclusive": false
}
```

`length[1] = null` 表示在有界探针范围内未发现有限上限，不等于数学上证明永远无上限。

`policy` 与 `pwd_policy` 必须区分：

- `policy`：分类器输出的 authentication/measurement 摘要。
- `pwd_policy`：`length/restrictive/permissive` 组成的真实口令探针结果。
- `pwd_method`：`inline` / `full` / `classified_only` 等实际路径。

网页入库和数据库构建时不得把 `policy` 和 `pwd_policy` 混写。

### 6.5 GitHub 案例

GitHub 曾因异步 `Verifying…` / `Validation failed` 被过早解释，产生
`[25,51]` 和 `[32,25]` 这类明显矛盾的长度结果。当前本机安全实测为：

- 长度范围 `[8,72]`。
- 8 位时单字符类被拒绝。
- `lower + digit` 组合可接受。
- 存在长度达到 15 位的替代分支。

线上任务历史中仍有修复前的 GitHub 失败记录，不能用它们判断当前算法。

---

## 7. 数据层和 reports 铁律

### 7.1 权威数据

- `reports/sites/sites_latest.jsonl`：程序测量权威数据。
- `misc/manual_review.json`：已审核人工核验权威数据。
- `misc/site_keywords.json`：域名与中文关键词。
- `reports/sites/sites_summary.md` 和 `reports/sites/profiles/`：从权威 JSONL 生成的人类可读报告。
- `webapp/sites.db`：可重建服务索引，不是唯一数据源，已被 `.gitignore` 忽略。
- `reports/archive/`：轮次实验、差异、仲裁和历史证据，默认不直接参与线上展示。

绝对不得：

- 为了前端美化而批量重写 `reports/` 或 `misc/` 数据格式。
- 直接用 SQLite 反向覆盖权威 JSONL。
- 未完成两轮回归和差异复核，就用实验轮次覆盖 `sites_latest.jsonl`。
- 用新一轮 `unknown/error` 覆盖同版本最后的有效证据。
- 未读取当前差异就还原、清理或删除用户的数据文件。

### 7.2 单条 JSONL 记录结构

主键是 `(hostname, entry_kind)`，`entry_kind` 只能是 `login` 或 `signup`。

主要字段：

- `site`、`hostname`、`entry_kind`、`measured_at`、`version`。
- `flow_type`、`confidence`、`stop_reason`、`primary_method`、`ui_type`。
- `start_url`、`final_url`。
- `states[]`、`methods[]`、`evidence[]`。
- `policy`：分类摘要。
- `pwd_policy`：口令政策实测。
- `pwd_method`：口令测量方法。
- `error`：运行异常；分类拒答不一定是 error。

`scripts/site_data_store.py` 使用临时文件 + `fsync` + `os.replace` 原子替换，并对
权威文件加锁。修改时必须保持：

- 单侧 login 入库不能抹掉已有 signup，反之亦然。
- 写 JSONL 失败时不能只修改 SQLite。
- 同步、网页入库、人工审核和建库共用一个跨进程数据锁。

### 7.3 人工核验

组员提交人工观察后，先进入 SQLite 的 `reviews_pending`，不会立即改变正确率。
管理员通过后，才写入 `misc/manual_review.json` 并即时重新计算对照。

统计对 login/signup 分开计算：

- `match`：程序和人工可比较且一致。
- `mismatch`：程序和人工可比较且冲突。
- `inconclusive_program`：程序证据不足。
- `inconclusive_manual`：人工记录没有明确所需比较维度。
- 正确率 = `match / (match + mismatch)`。
- 覆盖率 = `(match + mismatch) / manual_verified`。

因此只看正确率是不完整的；必须同时报告覆盖率。

---

## 8. Web 展示系统

### 8.1 组成

- FastAPI：`webapp/app.py`。
- 前端：`webapp/static/index.html` + 本地 `bootstrap.min.css`，无 Node 构建步骤。
- SQLite：`webapp/sites.db`，可从 JSONL + manual review 重建。
- 线上地址：`http://120.53.5.132:8000`。
- 默认无头：`webapp/app.py` 会默认设置 `SITES_HEADLESS=1`。

### 8.2 API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/sites?q=&limit=` | 搜索/列出站点 |
| GET | `/api/sites/{host}` | 单站详情、程序与人工对照 |
| GET | `/api/sites/{host}/history` | 历史程序版本 |
| GET | `/api/stats` | 站点数、正确率、覆盖率、方法覆盖度和原因列表 |
| POST | `/api/classify` | 同步单侧现场分类 |
| POST | `/api/policy` | 同步口令政策测量 |
| POST | `/api/tasks` | 提交异步分类/口令任务 |
| GET | `/api/tasks` / `/api/tasks/{id}` | 任务列表/状态 |
| POST | `/api/tasks/{id}/cancel` | 取消尚未执行的任务 |
| DELETE | `/api/tasks/{id}` | 删除任务历史 |
| POST | `/api/sites` | 把现场结果原子写入权威 JSONL 和 SQLite，需管理员口令 |
| GET/POST/DELETE | `/api/reviews/...` | 提交、查看、通过、批量通过或删除人工观察 |
| GET | `/api/export` | 导出权威程序/人工数据，需管理员口令 |

`SITES_ADMIN_TOKEN` 只应由服务器环境提供，不得写入代码、文档或提交历史。

### 8.3 当前线上数据快照

截至 2026-09-04 实时查询：

- 线上正式展示 155 个站点，125 个已人工核验，0 个待审核。
- 注册：73/90 一致，正确率 81.1%，覆盖率 72.0%。
- 登录：77/92 一致，正确率 83.7%，覆盖率 73.6%。
- 登录方法覆盖度 74.2%（23/31），注册方法覆盖度 70.6%（12/17）。

本地 `reports/sites/sites_latest.jsonl` 是 154 个 hostname、307 条记录。线上 155 站与本地
154 站的差异可能来自服务器网页新增数据尚未被 Mac pull；不要未比较就任意覆盖任一侧。

### 8.4 已知展示问题

1. **任务执行完成 ≠ 口令政策测量成功**。当前后台只要 worker 无异常结束就把
   `status` 设为 `done`，前端又显示「口令政策测量完成」。但结果可能是
   `policy_measured=false` / `classified_only`。
2. `/api/stats` 已为正确和错误站点生成完整 `reason`，但当前详情页
   `compRow()` 只显示方法列和「结论一致/不一致」，没有渲染 `comparison.reason`。
3. 任务列表有多条 GitHub/Gamersky/12306 修复前的重复测试，默认展开会干扰判断。
4. 口令结果应显式分为：完整实测、页面提示非实测、仅分类、证据不足、
   被验证阻断、执行失败。
5. 线上仍是 HTTP。管理员口令会明文经过网络，未配置 HTTPS 前不应在不可信网络使用。
6. 站点列表是「正式展示集」，303 站批处理输出是「实验回归集」；页面未向用户
   清晰解释两个数量为什么不同。

---

## 9. Mac、GitHub 和服务器的关系

```text
Mac
  - 修改代码
  - 运行单元测试和两轮全量验收
  - 生成实验档案和正式 reports
  - push 到 GitHub
        ↓
GitHub
  - 代码和持久数据的唯一交换桥梁
  - 保留历史版本
        ↓↑
服务器
  - FastAPI + SQLite + Chrome 152
  - 展示、实时分类/口令任务、人工审核
  - 网页入库后立即更新 JSONL 和 SQLite
  - 每 6 小时快照网页增量、pull、回放、建库、重启、push
```

远程仓库：

```text
git@github.com:Baibai231/National-College-Cryptographic-Technology-Contest.git
```

关键原则：

- Mac 不直接读写服务器文件，服务器也不直接修改 Mac；通过 GitHub 交换持久数据。
- 服务器上不应在有网页增量时直接 `git pull`。应运行 `./webapp/server_sync.sh`，
  它会先快照增量再变基和回放。
- 服务器同步顺序受保护：旧 HEAD 增量快照 → 干净 pull/rebase → 原子回放 →
  生成报告 → 提交 → 建库 → 重启 → API 健康检查 → push。
- pull 失败也必须恢复快照，不能丢网页新增数据。
- 服务器使用 SSH 连 GitHub，国内 HTTPS 连接可能不稳定。

---

## 10. 测试、全量回归与数据提升

### 10.1 快速自动测试

```bash
.venv/bin/python -m unittest discover -s tests -q
```

当前已通过 162 项。本仓库的 `.venv/bin/pytest` 不一定存在，不要因此误判为测试失败。

测试必须隔离真实数据文件。历史上测试曾因没有 monkeypatch `MANUAL_PATH`，将
`private.example` 写入真实 `misc/manual_review.json`。当前已修复并清除该污染。

### 10.2 批量测量

一个常用的 303 站全量语料是对以下文件合并去重：

- `misc/sites_base_60.txt`
- `misc/sites_extra_60.txt`
- `misc/sites_new_30.txt`
- `misc/sites_extra.txt`
- `misc/cn_new50.txt`
- `misc/foreign100.txt`

范例：

```bash
.venv/bin/python scripts/run_measurement.py \
  --input misc/sites_base_60.txt \
  --input misc/sites_extra_60.txt \
  --input misc/sites_new_30.txt \
  --input misc/sites_extra.txt \
  --input misc/cn_new50.txt \
  --input misc/foreign100.txt \
  --kinds signup,login \
  --output reports/archive/<new-round>.jsonl \
  --workers 3 \
  --site-timeout 900 \
  --measure-policy
```

不要把范例中的 `<new-round>` 原样执行。要使用新的、不会覆盖现有证据的档案名。

`scripts/run_measurement.py` 当前保护：

- macOS 上多 worker 批处理默认使用无头 Chrome，避免 AppKit/LaunchServices 崩溃。
- 显式要求有头时会保守降为单 worker。
- Chrome/ChromeDriver 主版本自动检测，不再硬编码过期主版本。
- 每个 worker 使用独立浏览器进程和安全回收。
- 连续 3 次浏览器启动失败会熔断整批，防止生成数百条假失败。
- `--resume` 只跳过成功记录，会重试会话创建失败、超时等 error 记录。
- `--retry-unknown N` 可重试 unknown/error 并根据有效结果投票。

### 10.3 两轮验收是强制规则

对分类器、注册入口发现、inline 反馈或口令探针逻辑的重要修改，必须：

1. 跑完第 1 轮全量。
2. 用相同版本、参数、站点集合和浏览器模式跑完第 2 轮。
3. 使用 `scripts/compare_measurement_rounds.py` 生成逐站差异报告。
4. 对差异项进行定向第 3 次复测或人工打开网站核验。
5. 比较不仅看 `flow_type`，还要看 fields、blockers、methods、stop_reason、
   错误类别、`method_used`、长度和其他口令政策字段。
6. 使用 `scripts/select_measurement_results.py` 仲裁，但不能让 unknown/error 覆盖旧有有效证据。
7. 生成逐站真值/差异报告并人工抽查后，才能提升到 `sites_latest.jsonl`。

仅证明「两轮程序输出一样」不等于证明「两轮都符合真实网站」。
项目历史上曾因只做内部一致性而漏掉图片型第三方入口。所以差异分析必须包含真实
网页证据或人工核验。

### 10.4 当前回归状态

- `reports/archive/full303_policy_20260829.jsonl`：606 条，7 条运行失败，33 条 inline，
  覆盖 17 个唯一站点。
- `reports/archive/headful_r1_20260830.jsonl`：修复前的有头第 1 轮，606 条，
  600 条正常，6 条运行失败，30 条 inline，17 个唯一站点。
- `reports/archive/headful_r2_20260904.jsonl`：无效故障证据。前 12 条都是 macOS
  并发有头 Chrome 启动崩溃，已中止，不得当作第 2 轮成果。
- `reports/archive/headless_postfix_round1_20260904.jsonl`：Chrome 批处理修复后的
  **无头第 1 轮**，已完成 606 条；6 条运行错误，28 条 inline，
  覆盖 15 个唯一站点。
- `reports/archive/headless_postfix_round2_20260905.jsonl`：修复后的
  **无头第 2 轮中断记录**，停在 12/606，12 条均为有效 JSON 且无运行错误。
  用户已明确要求不再续跑；不得将它冒充为完整第 2 轮成果。

查看当前进度：

```bash
wc -l reports/archive/headless_postfix_round1_20260904.jsonl
stat reports/archive/headless_postfix_round1_20260904.jsonl
```

---

## 11. 当前 Git 和工作树（务必保留）

截至本文生成时：

- 分支：`main`。
- 本地 HEAD 和 `origin/main`：`7b02928`。
- 当前修改尚未 commit/push，因为修复后两轮全量验收还没结束。

已修改：

- `CHANGELOG.md`：口令测量、有头回归和 Chrome 崩溃修复记录。
- `scripts/run_measurement.py`：浏览器模式选择、进程回收、启动失败熔断、resume 错误重试。
- `utils/util_test_password.py`：Chrome/driver 版本匹配、并发启动安全和口令探针修正。
- `tests/test_site_data_store.py`：真实数据文件测试隔离。
- `misc/manual_review.json`：只删除测试污染的 `private.example`，其他人工数据未改。

未跟踪：

- `tests/test_run_measurement_safety.py`：新的批处理安全测试。
- `reports/archive/headful_r1_20260830.jsonl`：完整有头第 1 轮证据。
- `reports/archive/headful_r2_20260904.jsonl`：12 条无效启动故障证据。
- `reports/archive/headless_postfix_round1_20260904.jsonl`：已完成的修复后第 1 轮。
- `reports/archive/headless_postfix_round2_20260905.jsonl`：仅 12/606 的中断记录，当前不续跑。

不得执行 `git reset --hard`、`git checkout -- <file>`、批量删除 untracked 文件，也不得
在未理解差异时用远程分支覆盖当前工作树。

---

## 12. 当前已解决的三个核心问题

### 问题 1：主界面只有登录，注册口令框藏在更深层

判断：**常见结构基本解决，长尾结构未全解决**。

已支持登录到注册的 tab/链接兜底、直接路由、SPA/新窗口、iframe、慢渲染和
注册上下文守卫。百度、网盘、163、GitHub 等典型路线已经可达。但 2345、AcFun、
新浪、澎湃等仍可能因弹窗波动或隐藏入口而漏判。

### 问题 2：14 个站第一轮通过，第二轮超过一半失败

判断：**结构性错误大幅改善，站点波动与风控无法完全消除**。

已加入负对照、三态证据、字段状态/ARIA/样式/DOM 文本多通道、异步稳定等待、
字段被清空检测、基线快照、反馈邻近过滤、iframe、阶段控制点、浏览器死亡和
访问限制分型。但站点改版、验证码、反爬、服务端提交后才校验等情况在安全边界内
仍只能拒答。

### 问题 3：口令候选集和 14 步顺序错误

判断：**当前属性模型内已基本解决**。

已将长度放到组合前，使用分层候选、缓存复验、等长符号替换、自洽检查、OR 规则
有界刻画和多个控制点。当前尚未充分表达更一般的布尔规则、用户名/邮箱相似性、
词典/语言、Unicode 规范化、截断、上下文口令和可重复性置信度。

---

## 13. 已知技术债和审查重点

Cursor 审查时建议优先关注：

1. `webapp/static/index.html` 任务状态文案：需将 job status 和 measurement outcome 分开。
2. 详情页需渲染已有 `comparison.reason`，正确和错误都应解释。
3. 任务历史应按 hostname/kind 展示最新结果，旧任务折叠，不能直接删除用户需要的证据。
4. `run_measurement.py` 的子进程、超时、Ctrl-C、熔断和结果队列之间是高风险区，
   任何改动都要有模拟单测，再做 1～2 站点烟测，不要直接开 606 条。
5. `util_test_password.py` 有很长的历史函数和旧模型，先用调用链确认正在使用的路径，
   再重构，不要大面积机械改写。
6. `PasswordPolicy.password_combination` 等旧代码包含类属性可变对象，需检查实际调用范围，
   不要在不确定时假定其与当前 inline 主链无关。
7. `measurement_record()` 和部分旧文档的默认版本字样仍是 v3。Web 当前会显式传 v4，
   但不应在没有测试的情况下随意改默认值或批量重写历史数据。
8. 无头/有头结果存在环境敏感性。分类变化必须区分代码退化、站点波动、风控和浏览器模式。
9. Chrome 主版本与 ChromeDriver 必须匹配。不得恢复硬编码 `version_main=150`。
10. 不得把静态口令提示或强度计单独当作 accepted/rejected 真值。
11. 不要为单个站点写 hostname 特判，除非是明确的直达路由配置且有通用兜底。
12. 网站当前只有 HTTP；安全审查应将 HTTPS/反向代理列为部署问题，不要在前端隐藏风险。

---

## 14. Cursor 修改代码时的工作规则

1. 修改前先执行 `git status --short --branch` 和针对性 `git diff`。
2. 保留用户和其他工具的未提交改动，只修改当前任务所需文件。
3. 不得终止、覆盖或重复启动正在运行的全量回归，除非用户明确要求。
4. 前端修改只修展示层，不回写权威 reports/misc 格式。
5. 数据 schema、FlowType、PageState 或 methods 原始格式变化属于高风险改动，需先说明迁移策略。
6. 分类/口令测量修复必须增加相应单元测试；对实站问题优先生成最小可复现 fixture。
7. 先跑快速测试，再跑单站/小批烟测，最后才评估是否需要两轮全量。
8. 分类器、入口、反馈解释或候选集发生实质变化后，必须完成两轮全量与真值抽查。
9. 所有实质修改及验证结果都要同步到 `CHANGELOG.md`。
10. 未经用户明确要求，不要 commit、push、部署、改服务器数据或升版。
11. 继续使用 v4，不要改为 v5。
12. 提交结果时明确说明：改了什么、为什么、测了什么、哪些没测、是否动了数据文件。

---

## 15. 常用操作

### 查看版本与状态

```bash
cat misc/measure_version.txt
git status --short --branch
git diff --check
```

### 单元测试

```bash
.venv/bin/python -m unittest discover -s tests -q
```

### 单站分类诊断

```bash
.venv/bin/python scripts/run_classify_diag.py https://example.com --kind signup
```

### 单站完整链

```bash
.venv/bin/python main.py https://example.com --method auto
```

`auto` 不会自动 full-form。

### 建立本地 SQLite 索引

```bash
.venv/bin/python scripts/build_site_database.py
```

### 本地运行 Web

```bash
./webapp/run_server.sh 8000
```

### 生成报告

```bash
.venv/bin/python scripts/generate_profiles.py \
  --results reports/sites/sites_latest.jsonl \
  --profiles-dir reports/sites/profiles \
  --summary reports/sites/sites_summary.md
```

### 比较两轮

```bash
.venv/bin/python scripts/compare_measurement_rounds.py \
  reports/archive/<round1>.jsonl \
  reports/archive/<round2>.jsonl \
  --report reports/archive/<compare>.md \
  --json reports/archive/<compare>.json
```

### 服务器安全同步

```bash
cd ~/measure
./webapp/server_sync.sh
curl -fsS http://127.0.0.1:8000/api/stats
```

不要在有网页增量的服务器上用裸 `git pull` 代替 `server_sync.sh`。

---

## 16. 当前最合理的下一阶段

### P0：收尾当前修复

1. 当前先停止测量推进，梳理代码、边界、历史成果和未解决问题。
2. 不把 12/606 的第 2 轮中断文件当作完整验收结果。
3. 如果未来重新启动验收，再决定是否续跑第 2 轮、生成差异报告并做人工真值确认。
4. 未经用户新的明确要求，不 commit/push，不服务器部署。

### P1：收尾展示

1. 区分「任务运行状态」和「测量结果状态」。
2. 在正确和错误站详情中显示已存在的原因文本。
3. 按站点/类型去重展示最新任务，旧结果可展开查看。
4. 明确展示「实测/提示/仅分类/证据不足/阻断/失败」。
5. 规划 HTTPS，在部署前保持管理员口令风险提示。

### P2：向密码/密码技术竞赛靠拢

建议将项目的研究核心表述为：

> 在不提交注册、不使用真实身份和不绕过人机验证的条件下，基于主动实验和可解释证据，
> 推断公开网站的注册路径与口令约束，并对不可观察条件诚实拒答。

技术深化方向：

1. **形式化约束语言**：支持长度、字符类、k-of-n、OR/AND 分支、条件长度、禁止序列、
   用户名相似、字典/泄露口令、Unicode 规范化和截断。
2. **自适应探针**：根据当前候选政策集选择信息增益最大的下一个口令，而不是固定 14 步。
3. **标准基准集**：建立 50～100 个可复现站点/镜像的人工真值，按 inline、提交后校验、
   多阶段、iframe、OR 规则、验证码等分层。
4. **评测指标**：入口发现召回率、分类 macro-F1、政策 exact match、单属性 P/R/F1、
   拒答率、两轮重复一致率、平均探针数和耗时。
5. **多通道证据融合**：DOM 文本、validity、ARIA、样式差分、字段值、异步时序和安全的只读网络响应。
6. **可重放证据**：固定随机种子，保存探针序列、时间线、DOM 摘要和必要截图，支持失败重放。
7. **安全不可达建模**：对短信/验证码后的口令政策作为右删失/不可观测结果，
   在授权测试站或自建镜像中单独评估，不在真实网站绕过门槛。
8. **消融实验**：对比早期固定顺序、无负对照、只看红框、当前多通道、自适应探针等版本，
   用数据证明每个设计的价值。

---

## 17. 完成一次修改的验收清单

- [ ] 没有改变 v4。
- [ ] 没有弱化安全边界或开启公开站 full-form。
- [ ] 没有把分类 `policy` 与实测 `pwd_policy` 混写。
- [ ] 没有为前端展示而重写 reports/misc 数据格式。
- [ ] 没有覆盖或删除当前未提交工作。
- [ ] 新逻辑有单元测试，162 项基线未退化。
- [ ] 如果修改了浏览器或实站链，已先做小批烟测。
- [ ] 如果修改了分类/口令逻辑，已计划或完成两轮全量回归。
- [ ] 差异不只看程序内部一致性，也与真实网页/人工真值对照。
- [ ] 权威 JSONL 和人工数据的写入仍然是原子的。
- [ ] `git diff --check` 通过。
- [ ] `CHANGELOG.md` 已记录改动、原因、影响和验证。
- [ ] 向用户说明测试边界和未完成项，不把任务 done 说成政策 measured。
