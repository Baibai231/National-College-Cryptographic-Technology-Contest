# 被动密码技术观察器

本模块把 CryptoScope AI v3.0 方案中的 OAuth/OIDC、JWT、WebAuthn、MFA、
Session、TLS 和 HTTP 安全响应头分析能力接入现有 v4 测量引擎，同时保持原有安全
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
      "session_cookies": {},
      "transport_security": {},
      "http_security_headers": {}
    },
    "assessment": {}
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

因此，“未观察到”不等于网站不支持该能力，“观察到”也不等于该机制已正确实施或通过
密码安全验证。后续风险评分必须同时显示证据覆盖率和未知维度。
