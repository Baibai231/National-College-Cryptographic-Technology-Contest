# 被动密码技术观察器

本模块把 CryptoScope AI v3.0 方案中的 OAuth/OIDC、JWT、WebAuthn、MFA、
账户恢复、Session、TLS 和 HTTP 安全响应头分析能力接入现有 v4 测量引擎，同时保持原有安全
边界：不登录、不填写身份字段、不发送验证码、不完成第三方授权、不创建账号。

## 输出位置

分类结果新增顶层字段 `security_observations`，不改变现有 `flow_type`、`policy` 或
`pwd_policy` 的含义。网页 API、异步任务、CLI 日志、批量 JSONL 和 SQLite 可重建
索引都保留该字段。

```json
{
  "security_observations": {
    "schema_version": "1.0",
    "collection_mode": "passive",
    "evidence_boundary": "current_safely_reachable_pre_authentication_page",
    "observed_capabilities": ["oauth_oidc", "mfa"],
    "observers_with_evidence": ["oauth_oidc", "mfa", "session_cookies"],
    "analyzers": {
      "oauth_oidc": {},
      "jwt": {},
      "webauthn": {},
      "mfa": {},
      "account_recovery": {},
      "session_cookies": {},
      "transport_security": {},
      "http_security_headers": {}
    },
    "assessment": {},
    "maturity": {}
  }
}
```

## 结论边界

- OAuth/OIDC：只检查当前页面可见链接和表单动作中的协议参数，不访问授权端点，
  不保存 `client_id`、`state`、`code_challenge` 或 `redirect_uri` 的值。
- JWT：只在浏览器页面上下文内识别 JWT 形状并返回算法、`exp`/`iss`/`aud` 是否
  存在以及签名段是否存在；不返回 Token，也不声称验证了签名。
- WebAuthn：页面出现 `autocomplete=webauthn` 或 Passkey/安全密钥语义才报告站点
  能力；浏览器支持 `PublicKeyCredential` 本身不算站点证据。
- MFA：报告观察到的认证因素或并列认证方式，但在未完成认证流程时始终将
  `mfa_enforcement` 标为 `not_determined`。
- Account Recovery：只识别当前页可见的“忘记密码/重置密码”等入口、目标协议统计和
  邮箱/短信/人工渠道提示；不点击入口、不发送消息、不验证重置 Token，也不测试网站是否
  会返回原口令。输出不保存恢复 URL。
- Session：只统计 Cookie 安全属性及疑似会话 Cookie 数量，不保存 Cookie 名和值；
  认证前 Cookie 不能代表登录后会话安全。
- Transport：复用 Chrome 已发生导航的性能事件，记录最终页协议、HTTP 协议、
  HTTP→HTTPS 跳转、TLS 版本/密码套件、证书名称匹配及有效期等有界元数据；不额外发起网络
  请求，不保存 URL、查询参数、证书主体或证书原文。
- HTTP 安全响应头：只针对当前主文档响应汇总 HSTS、CSP、nosniff、防嵌套、
  Referrer-Policy、Permissions-Policy、跨源隔离和缓存策略。CSP nonce/hash、Server
  版本及任何原始 Header 值均不进入结果。若主文档响应事件不可用，状态保持
  `not_observed`，不会把“无法读取”误报成“响应头缺失”。

`privacy.extra_network_request_sent=false` 表示观察器只消费测量流程本来就产生的导航
证据；它不会为了获取 Header 或证书再请求一次网站。

页面快照对开放 Shadow DOM 和同源 iframe 做有界扫描；跨域 iframe 仍受浏览器同源策略
限制，并由分类器的 WebDriver frame 聚合提供认证方式证据。

## 证据覆盖率与分维度评估

`assessment` 使用 `evidence_weighted_dimensions_v1` 模型，对五个维度分别展示得分、
覆盖率、已知项表现、证据、发现和建议：

| 维度 | 权重 |
|---|---:|
| 口令策略 | 30% |
| 认证机制 | 20% |
| 会话 Cookie | 15% |
| 传输安全 | 20% |
| HTTP 安全响应头 | 15% |

评分遵循以下约束：

- 未观察到的控制项不按 0 分处理，而是从得分分母中排除并降低覆盖率。
- 总分表示“已知证据的表现”，不是网站整体安全分；不同覆盖率的分数不能直接比较。
- 加权覆盖率不足 70% 时不输出字母等级，只显示有限证据得分。
- 口令策略只有在 inline/full 得到可信实测结果时才计分；页面提示、分类结论和失败探针
  不会被当作口令策略失败。
- 并列登录方式不作为 MFA 已启用的证据；MFA 强制性及登录后 Cookie 仍需授权人工复核。
- `observed_risk_level` 只汇总已确认观察，例如明文认证页、HTTPS 降级、过期/名称不匹配
  证书、旧 TLS 或会话 Cookie 属性问题；未知项不会被标为风险。

该评分是 CryptoScope 的内部、可复现测量指标，用于同口径研究和筛选人工复核目标，
不是漏洞证明、合规认证或对网站整体安全性的保证。

## CPAM 证据成熟度

`maturity` 使用 `cpam_evidence_ladder_v1`，对应方案中的 Level 0--6，但将
“连续证据支持等级”与“更高层能力信号”分开：

- `evidence_supported_level` 只沿已确认的连续层级上升；当前认证前测量通常最多确认
  Level 1 的基础口令认证。
- `highest_observed_capability_level` 可以记录更高层的非连续能力。例如页面明确提供
  Passkey/WebAuthn 时可观察到 Level 5 方向能力，但不会因此声称网站已达到 Level 5。
- Level 2 的服务端口令存储、Level 3 的 MFA 强制执行、Level 4 的风险认证和
  Level 6 的零信任架构无法由认证前页面可靠推断，保持 `unknown` 或 `unverified`。
- 并列的口令、短信、联合登录选项不是 MFA 已启用的证据；只有完成且确认强制的多因素
  序列才能支持 Level 3。

网页同时显示证据支持等级和更高能力方向，并固定标注“非完整成熟度等级”。

因此，“未观察到”不等于网站不支持该能力，“观察到”也不等于该机制已正确实施或通过
密码安全验证。后续风险评分必须同时显示证据覆盖率和未知维度。
