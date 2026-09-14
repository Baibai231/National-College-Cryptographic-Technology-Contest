# CryptoScope AI v4：B 系列阶段验收报告

日期：2026-09-08  
执行环境：Mac 本地；未使用服务器  
范围：B-00～B-11 身份认证与应用密码测量层

## 1. 结论先行

B 系列的**工程骨架已经闭合**：B-00～B-11 的预定模块、论文/标准登记、数学
口径、隐私边界、网页增量展示、实验语料清单、统计工具和自动测试均已落地。
这意味着项目已不再只是“登录/注册分类器 + 口令长度探针”，而是一个能从公开
访客证据出发，对认证入口、口令、MFA、OAuth/OIDC、JWT/JWS、Passkey、恢复、
二维码和表单秘密流进行分层测量的研究原型。

但**竞赛完整实证门槛尚未通过**。当前最明显的缺口是：

1. 25 个人工确认 inline 站中，只有 7 个形成严格完整政策，恢复率为
   28.0%，95% Wilson 区间为 [14.28%, 47.58%]；
2. 303 站历史固定档案中有 15 站输出 inline 结果，严格排除起点的
   `or_rule_likely` 不自洽结果后只有 14 站形成完整政策，即 4.62%；
3. B-03 尚无经过伦理处理的真实口令频率/破解真值，不能声称强度计准确；
4. B-10 已在本地靶场复现并阻断外传，但尚无经过伦理审核的真实站点样本；
5. 当前冻结代码尚未执行两轮新的 303 站全量，因此历史 75.58% 的档案一致率
   只能作为旧代码漂移基线，不能冒充当前验收；
6. MFA 强制、真实令牌验签、Passkey 登录后生命周期、恢复 Token、二维码扫码
   确认等性质需要授权测试账号，访客模式必须保持 `UNKNOWN`。

所以准确表述是：**B 系列代码阶段完成，访客/安全交互原型阶段部分通过，完整
竞赛实证阶段未通过。**

## 2. 五层实验语料

| 层 | 语料 | 当前数量 | 用途 |
|---|---|---:|---|
| A | 人工核验认证站 | 125 | 登录/注册结论与人工对照 |
| B | 人工确认 inline 站 | 25 | 口令政策恢复率和失败漏斗 |
| C | 全量网站语料 | 303 | 分类、政策覆盖、错误和漂移 |
| D | 论文 Passkey 正样本 | 8 | 复现论文目录到公开页证据的断层 |
| E | 本地可控合成场景 | 5 | 正负向、隐私和不干扰守卫验证 |

语料定义保存在 `config/b_layer_experiment_cohorts.json`。它只引用权威路径，
不复制或回写 `misc/manual_review.json`、`reports/sites` 或历史 JSONL。

## 3. B-00～B-11逐项状态

| 任务 | 作用 | 论文/标准方法如何进入代码 | 当前状态 |
|---|---|---|---|
| B-00 | 统一证据模型 | 每个模块必须声明密码学要素、论文、模式和限制；证据分 `verified/observed/inferred/documented/unknown` | 工程完成 |
| B-01 | 登录/注册认证图 | 将入口、字段、门槛和并行方法建成两条独立图分支，不再只压成一个 `flow_type` | 代码完成；节点/边真值不足 |
| B-02 | 口令政策探针 | 负对照、接受/拒绝双向证据、分层候选集、长度边界搜索、OR 规则自洽检查 | 7/25，实证未达标 |
| B-03 | 口令强度计 | 实现 USENIX Security 2023 的加权 Spearman、按攻击策略的 KL 散度、极端分箱 Precision 与 `Precision_Security` | 四维公式/工具完成；真实真值未做 |
| B-04 | MFA/OTP/RBA | 按 USENIX Security 2023 的可用性分类区分“页面提供”与“账号强制” | 访客层完成；强制关系未知 |
| B-05 | OAuth/OIDC | 执行 WPSE/FAPI 的端点与上下文绑定思想，以及 Discovery/RFC 8414 安全获取链 | 公开链完成；授权跳转未做 |
| B-06 | JWT/JWS | 按 RFC 7515 手工复核 RSA JWS，并以用途感知联合谓词约束 `iss/aud/time/nonce/typ` | 公开/离线验证完成 |
| B-07 | WebAuthn/Passkey | 使用论文官方产物、W3C WebAuthn 和 Chrome DevTools 空虚拟认证器；challenge 页内 HMAC 比较 | 公开及安全交互完成 |
| B-08 | 账号恢复 | 按 USENIX Security 2024 分开入口、因子、Token 生命周期、撤销和 OPRF 隐私 | 公开层完成；Token/撤销未知 |
| B-09 | 二维码登录 | 按 USENIX Security 2025 建模 `QrId/SessionID/Token` 与生成/扫码/确认三阶段 | 公开生成层完成；扫码攻击不执行 |
| B-10 | 提交前秘密流 | 复现 USENIX Security 2022 的合成邮箱/口令填充、脚本读监视和网络监视，并先阻断后报告 | 本地原型完成；真实样本未做 |
| B-11 | 数据集与统计 | 固定五层语料，统一覆盖率、证据率、Wilson 区间、Jaccard 与 Cohen kappa | 工具完成；两轮 303 未做 |

## 4. 当前数据能说明什么

### 4.1 登录/注册分类

权威 `reports/sites/sites_latest.jsonl` 与人工语料当前重叠 124 站；另有 1 个人工站
尚无权威测量结果。登录和注册始终分开计算：

| 侧别 | 一致 | 不一致 | 程序证据不足 | 人工描述不足 | 可判定样本 | 可判定一致率 | 覆盖率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 登录 | 76 | 15 | 28 | 5 | 91 | 83.52% | 73.39% |
| 注册 | 72 | 17 | 31 | 4 | 89 | 80.90% | 71.77% |

登录一致率 95% Wilson 区间为 [74.57%, 89.75%]，注册为
[71.52%, 87.72%]。这里的“准确率”只在可判定样本上计算：

\[
A=\frac{N_{match}}{N_{match}+N_{mismatch}},\qquad
C=\frac{N_{match}+N_{mismatch}}{N_{manual}}
\]

`UNKNOWN` 没有被硬算成正确或错误。不过人工数据还没有逐站标注完整图节点和
每一条跳转边，因此这些数字不能冒充认证图节点准确率或路径召回率。

### 4.2 口令政策漏斗

25 个人工 inline 站的当前严格结果：

| 结果类别 | 站点数 |
|---|---:|
| 完整可信政策 | 7 |
| 未到达口令框 | 6 |
| 人机/访问门槛 | 4 |
| 口令框来自未确认注册语境 | 3 |
| inline 反馈不确定 | 2 |
| 仅静态提示，无行为证据 | 1 |
| 到达口令框但 inline 不受支持 | 1 |
| 口令前先验证 | 1 |

因此低恢复率不是单一的“红框没识别到”：13/18 个失败首先发生在口令探针之前
（未到框、门槛、注册语境错误或先验证），另外 5 个才属于提示/反馈/inline
证据不足。下一轮优化应先提高入口和注册语境召回，再扩展反馈观察通道。

303 站 2026-09-04 档案共有 606 条登录/注册记录和 6 条运行错误；15 个唯一站
输出 inline 结果，其中 14 个通过严格完整性门槛。起点虽输出长度和 OR 分支，
但自洽检查明确标记 `_inconclusive`，所以不计入严格完整政策。

### 4.3 Passkey 两类实验

8 个论文正样本站两轮公开测量均有完整记录。两轮二值出现一致率为 0.9688，
加权特征 Jaccard 为 0.7143。目录中支持 Passkey 并不等于未登录首屏就能观察到
协议调用：第一轮/第二轮完整加载仅 4/8 与 5/8，WebAuthn API 自动调用均为 0/8。

GitHub 空虚拟认证器两轮实测均在显式点击前自动发起 conditional 认证，程序
正确停止点击；两轮 14/14 个脱敏配置字段一致：32 字节 challenge、当前主机 RP、
`userVerification=required`、空 `allowCredentials`、注册调用 0、虚拟凭据前后 0。

\[
A_{cfg}=\frac{\sum_i \mathbf{1}[x_i^{(1)}=x_i^{(2)}]}{N_{comparable}}=1
\]

### 4.4 B-08～B-10本地真实 Chrome 结果

- 恢复场景：观察到 1 个公开恢复控件和邮箱因子，公开证据覆盖率 1.0；Token
  熵、一次性、过期、旧会话撤销、旧认证器撤销全部保持 `UNKNOWN`。
- 二维码场景：2 次采样、1 次可比较、1 次变化，`R_QR=1.0`；没有返回二维码
  内容或 HMAC 材料，没有扫码或登录，协议绑定仍为 `UNKNOWN`。
- 表单泄漏场景：合成邮箱和口令各触发 1 次第三方 `fetch` 外传尝试；2 次尝试
  全部在浏览器内阻断，表单提交数 0、转发数 0、真人数据 0。该本地正样本判
  `FAIL` 的对象是“第三方口令外传尝试”，不是声称服务器已经收到数据。

## 5. 核心数学口径

### 5.1 证据覆盖和分类统计

\[
Precision=\frac{TP}{TP+FP},\quad
Recall=\frac{TP}{TP+FN},\quad
F_1=\frac{2PR}{P+R}
\]

\[
Y_{evidence}=\frac{N_{evidence}}{N_{total}},\qquad
U=\frac{N_{unknown}}{N_{total}}
\]

`UNKNOWN` 进入覆盖率和未知率，不进入可判定准确率分母。小样本比例同时输出
Wilson 95% 区间，不只报一个看似精确的百分比。

### 5.2 两轮一致性

\[
A_{2r}=\frac{N_{equal}}{N_{paired}},\qquad
J_{2r}=\frac{|F_1\cap F_2|}{|F_1\cup F_2|}
\]

\[
\kappa=\frac{p_o-p_e}{1-p_e}
\]

精确签名一致率、结论一致率、阳性集合 Jaccard 和 Cohen kappa 分开报告；耗时、
堆栈地址等噪声不混入语义签名。

口令强度计的离线猜测区分度按论文对每种攻击策略分别计算：

\[
KL(P\Vert Q)=\sum_i P(i)\log\frac{P(i)}{Q(i)}
\]

其中 (P) 为破解集合、(Q) 为未破解集合的强度分布；代码不接收明文口令，
不对零概率暗中平滑。没有真实破解真值时该值保持空，不能由网页接受/拒绝替代。

### 5.3 密码学安全联合谓词

OIDC 公开信任链：

\[
V_{chain}=V_{TLS}\land V_{issuer}\land V_{jwks\_https}\land V_{jwks\_fetch}
\]

JWT/JWS 用途感知验证：

\[
V_P=\bigwedge_{j\in R(P)}V_j,
\quad V_j\in\{V_{sig},V_{alg},V_{iss},V_{aud},V_{time},V_{nonce},V_{typ}\}
\]

WebAuthn challenge 重用率：

\[
R_{ch}=\frac{N_{reused}}{N_{compared}}
\]

恢复授权态联合谓词：

\[
V_{rec}=V_{entropy}\land V_{one\_time}\land V_{expiry}\land
V_{session\_revoke}\land V_{auth\_revoke}
\]

二维码授权态联合谓词：

\[
V_{QR}=V_{bind}\land V_{random}\land V_{server\_gen}\land
V_{one\_time}\land V_{token\_bind}\land V_{confirm}
\]

公开访客证据缺一项时不把联合谓词判为通过。

## 6. 本轮验证

- `.venv` 下 281 项单元/集成测试全部通过；
- 5 个 Mac 本地真实 Chrome 合成场景全部通过；
- B11 定向统计/审计 5 项通过；
- 五层语料数量全部匹配预期；
- 机器可读结果：`reports/archive/b_series_audit_20260908.json`；
- 未运行服务器，未修改 SQLite 和正式 `reports/sites`，未提交、推送或部署；
- 版本保持 v4。

## 7. 论文与标准入口

- USENIX Security 2023, *A Large-Scale Measurement of Website Login Policies*：
  https://www.usenix.org/conference/usenixsecurity23/presentation/al-roomi
- USENIX Security 2023, *No Single Silver Bullet: Measuring the Accuracy of
  Password Strength Meters*：
  https://www.usenix.org/conference/usenixsecurity23/presentation/wang-ding-silver-bullet
- USENIX Security 2023, *A Study of Multi-Factor and Risk-Based Authentication
  Availability*：
  https://www.usenix.org/conference/usenixsecurity23/presentation/gavazzi
- IEEE S&P 2019, *An Extensive Formal Security Analysis of the OpenID
  Financial-Grade API*：https://ieeexplore.ieee.org/document/8835218/
- IEEE S&P 2023, *FIDO2, CTAP 2.1, and WebAuthn 2*：
  https://ieeexplore.ieee.org/document/10179454/
- USENIX Security 2026, *The State of Passkeys*：
  https://www.usenix.org/conference/usenixsecurity26/presentation/jannett
- USENIX Security 2024, *Secure Account Recovery for a Privacy-Preserving Web
  Service*：https://www.usenix.org/conference/usenixsecurity24/presentation/little
- USENIX Security 2025, *Demystifying the (In)Security of QR Code-based Login*：
  https://www.usenix.org/conference/usenixsecurity25/presentation/zhang-xin
- USENIX Security 2022, *Leaky Forms*：
  https://www.usenix.org/conference/usenixsecurity22/presentation/senol
- W3C WebAuthn Level 3：https://www.w3.org/TR/webauthn-3/
- OAuth Security BCP RFC 9700：https://www.rfc-editor.org/info/rfc9700/
- JWT BCP RFC 8725：https://www.rfc-editor.org/rfc/rfc8725.html

## 8. 下一阶段的严格验收顺序

1. 给 125 站人工语料补“图节点 + 有向边 + 登录/注册最终语境”标签，计算节点
   Precision/Recall/F1 和路径召回率；
2. 对 25 个 inline 站按失败类别逐站复测，优先处理 6 个口令框未到达和 3 个
   注册语境错误，再处理 5 个反馈通道问题；
3. 为 B-03 寻找论文作者公开、合规且不含明文口令的频率/破解真值或只导入
   排名与标签；找不到就保留工具和公式，不伪造准确率；
4. 通过伦理清单选择 B-10 真实公开页，只用随机 `example.invalid` 合成值，仍然
   阻断匹配外发；
5. 冻结代码与配置后，在 Mac 本地执行两轮完全相同的 303 站全量，再生成逐站
   差异表；
6. 最后才使用团队自有或明确授权测试账号补 MFA、令牌、Passkey 生命周期、
   恢复和二维码确认实验。未经授权的账号后结论始终保持 `UNKNOWN`。
