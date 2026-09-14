# B-07 WebAuthn/Passkey真实公开页小样本实验

> 版本：v4（进行中）  
> 执行日期：2026-09-07  
> 执行环境：Mac本地、Chrome 152、无头、两轮串行  
> 交互边界：0次点击、0次输入、0次探针主动凭据API调用、0次认证器响应

## 1. 研究问题

USENIX Security 2026 Distinguished Paper *The State of Passkeys: Studying the
Adoption and Security of Passkeys on the Web* 的官方产物已知某些站点支持
Passkey。本实验不重复问“目录里有没有它”，而是回答：

1. 一个未登录访客仅打开公开认证页，能观察到多少Passkey证据？
2. 网页上出现“Passkey”控件，是否等于页面已经发起WebAuthn仪式？
3. 论文工具使用的两个well-known资源在本地网络下有多少可见？
4. 同一配置重复两轮时，公开页证据是否稳定？

不回答的问题：账号内Passkey设置、真实注册/签名成功、认证器私钥保护、
服务端challenge状态、断言验签和账号恢复。这些都需要授权账号实验。

## 2. 论文工具与标准如何进入代码

- 正样本来自论文官方仓库
  [`RUB-NDS/state-of-passkeys-artifacts`](https://github.com/RUB-NDS/state-of-passkeys-artifacts)
  的 `data/merged/2026-04-21-13-50-39.json`，固定提交为
  `0905470c983c46baaecbfa17044d2219e6cdd100`。
- 代码复现官方 detector 的两个资源：
  `/.well-known/passkey-endpoints` 和 `/.well-known/webauthn`。
- 第一个资源按 W3C *A Well-Known URL for Relying Party Passkey
  Endpoints* 检查 `enroll/manage` HTTPS字段；只统计结构，不访问其URL。
- 第二个资源按 WebAuthn Level 3 related-origins 检查 `origins`
  数组的句法、数量和是否包含当前origin；不保存原origin列表。
- 页面内只安装B-07已有被动包装器，它只观察页面自己对
  `navigator.credentials.create/get` 的调用，不主动发起WebAuthn仪式。

## 3. 样本与固定入口

| 站点 | 论文正样本 | 公开认证入口 |
|---|---:|---|
| github.com | 是 | `https://github.com/login` |
| google.com | 是 | `https://accounts.google.com/` |
| paypal.com | 是 | `https://www.paypal.com/signin` |
| ebay.com | 是 | `https://signin.ebay.com/ws/eBayISAPI.dll` |
| coinbase.com | 是 | `https://login.coinbase.com/signin` |
| yahoo.com | 是 | `https://login.yahoo.com/` |
| adobe.com | 是 | `https://account.adobe.com/` |
| cloudflare.com | 是 | `https://dash.cloudflare.com/login` |

这是“论文目录支持Passkey”的正样本，不是“未登录首屏必须发起
WebAuthn”的正样本。因此未观察到API不能计假阴性，只能计公开页覆盖不足。

## 4. 数学口径

对证据类型 \(x\) 的公开页覆盖率：

\[
C_x = \frac{N_x}{N_{cohort}}
\]

对已观察到Passkey DOM控件的页面，API调用条件比例：

\[
P(API\mid DOM) = \frac{N(API \cap DOM)}{N(DOM)}
\]

每个站点的特征集为 \(F_{i,1},F_{i,2}\)，两轮总体Jaccard一致性：

\[
J_{2r} =
\frac{\sum_i |F_{i,1}\cap F_{i,2}|}
{\sum_i |F_{i,1}\cup F_{i,2}|}
\]

对8个二值出现字段 \(X\) 的一致率：

\[
A_{2r}=\frac{\sum_{i,j}\mathbf{1}[x_{i,j,1}=x_{i,j,2}]}
{N_{paired}|X|}
\]

这些都是“可见证据覆盖/稳定性”指标，不是网站安全得分。

## 5. 两轮结果

| 证据 | 第1轮 | 第2轮 | 第1轮 \(C_x\) | 第2轮 \(C_x\) |
|---|---:|---:|---:|---:|
| 公开页完整加载 | 4/8 | 5/8 | 50.0% | 62.5% |
| DOM Passkey控件 | 0/8 | 1/8 | 0% | 12.5% |
| 页面自动发起WebAuthn API | 0/8 | 0/8 | 0% | 0% |
| WebAuthn请求配置 | 0/8 | 0/8 | 0% | 0% |
| COSE算法候选表 | 0/8 | 0/8 | 0% | 0% |
| 生命周期signal | 0/8 | 0/8 | 0% | 0% |
| passkey-endpoints | 1/8 | 1/8 | 12.5% | 12.5% |
| related-origins | 0/8 | 0/8 | 0% | 0% |

两轮完整配对8个站点：

- \(A_{2r}=0.9688\)，即64个二值出现位中62个一致。
- \(J_{2r}=0.7143\)。Jaccard低于二值一致率，是因为稀疏特征集对单次
  GitHub加载差异很敏感；并非其他站点同时大量漂移。
- 唯一差异站点是GitHub：第1轮加载超时，第2轮完整加载后观察到
  `Sign in with a passkey`。

## 6. 站点级核对

| 站点 | 第1轮 | 第2轮 | 解释 |
|---|---|---|---|
| GitHub | 加载超时，UNKNOWN | 页面完整加载，DOM Passkey=observed，API=UNKNOWN | 手工核对公开页确有 `Sign in with a passkey`；程序命中正确，且未把“有按钮”错当成“已发起API” |
| Google | 加载超时 | 加载超时 | 本地直连环境不可稳定观测，UNKNOWN |
| PayPal | 加载超时 | 加载超时 | 最终URL仍为官方登录页，但DOM加载不完整，UNKNOWN |
| eBay | 加载成功，无DOM/API | 同左 | `passkey-endpoints` 两轮均可取，`enroll/manage`两字段均为有效HTTPS，两个均指向外部主机；程序没有跟进 |
| Coinbase | DNS安全拒绝 | DNS安全拒绝 | 本机DNS返回非公网地址，两轮在Chrome启动前跳过，UNKNOWN |
| Yahoo | 加载成功，无DOM/API | 同左 | 未登录首屏未观察到Passkey，不否定账号内支持 |
| Adobe | 加载成功，无DOM/API | 同左 | 同上 |
| Cloudflare | 加载成功，无DOM/API | 同左 | 同上 |

## 7. 人工确认结论

GitHub第2轮的程序证据为：当前页确实是 `https://github.com/login`，
DOM认证上下文命中 `passkey`，同时密码字段可见；WebAuthn调用计数为0。
手工读取GitHub当前公开登录页可确认其显示 `Sign in with a passkey`。
所以“控件可见=observed”是正确的，“API未观察到=unknown”也是正确的。

eBay的well-known结果在两轮均为：TLS证书验证通过，响应为JSON，
`enroll/manage` 共2个已知字段，均为有效HTTPS URL，原URL没有保存也没有跟进。
这是“公开管理元数据句法正确”，不是“eBay整体Passkey安全”。

## 8. 本阶段证明了什么

1. 论文目录的Passkey支持信息不能直接当成未登录首屏的可观测性。
2. 小样本中仅1/8站在一轮完整加载时显示Passkey控件，而0/8自动发起API。
   因此B-07第二阶段的challenge、RP scope、COSE算法、UV和生命周期指标
   不是代码无效，而是在“纯被动+未登录+不点击”权限下很少被触发。
3. 两轮二值一致率高，但页面加载状态会直接影响稀疏证据；单轮不足以成为论文结论。
4. 这一阶段更适合报告“公开Passkey可发现性”，而不是“Passkey服务端安全性”。

## 9. 下一步建议（本次未执行）

1. 在 `safe_interaction` 模式下，只点击明确的“Sign in with a passkey”控件，
   用CDP WebAuthn虚拟认证器而不是真实系统认证器，观察请求参数与失败路径。
2. 为每站保留“目录证据→公开DOM→API仪式→请求配置→授权账号服务端实验”五层证据梯子。
3. 扩大到论文目录的分层随机样本，按地区、站点类别、首屏/二步身份流程分层，
   报告Wilson置信区间，不用当前8站推广到整个Web。
4. 授权账号阶段再进行challenge跨会话唯一性、成功断言UV/UP、
   签名算法协商、凭据删除/恢复signal等密码学测量。

## 10. 产物索引

- 固定样本：`config/webauthn_public_cohort.json`
- well-known探针：`application_security/passkey_well_known.py`
- 实验脚本：`scripts/probe_webauthn_public_cohort.py`
- 两轮分析：`scripts/analyze_webauthn_public_rounds.py`
- 有效第1轮：`reports/archive/webauthn_public_r1_20260907.jsonl`
- 有效第2轮：`reports/archive/webauthn_public_r2_20260907.jsonl`
- 对比结果：`reports/archive/webauthn_public_comparison_20260907.json`
- 受限环境诊断轮：`reports/archive/webauthn_public_diagnostic_sandbox_20260907.jsonl`

本实验没有修改SQLite、`reports/sites` 正式站点结果或 `misc/manual_review.json`，
没有运行303站分类/口令政策回归，没有提交、推送或部署服务器。
