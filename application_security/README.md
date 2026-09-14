# B层：身份认证与应用密码测量

本目录承载从“单一登录/注册分类”向“论文驱动的认证图谱与密码技术测量”迁移的
新增代码。旧版 `reports/` JSONL 和 `misc/` 人工数据保持原格式；新视图优先在读取
时计算，确认稳定后再讨论是否升级权威数据 schema。

## 核心约束

每个进入比赛核心的检测器必须通过 `ModuleManifest` 声明：

- 明确的密码学或认证要素；
- 可回答的研究问题；
- 至少一篇同行评审论文；
- 可运行的安全模式；
- 不能从现有证据推出的结论。

`models.py` 提供不可变证据、结论和模块结果。证据等级是
`verified / observed / inferred / documented / unknown`，不得用“没有看到拒绝”
替代已验证的接受证据。

## 当前实现

- `auth_graph.py`：从现有 login/signup 状态序列实时构建两条独立认证分支；
- 认证方法和验证门槛以图节点表达，不再压成唯一 `flow_type`；
- 图谱结果已作为增量 API 字段输出，但不会写回正式 JSONL；
- `authentication_surface.py`：把口令、OTP、联合登录、二维码和Passkey整理为
  论文支撑的访客可见能力结论；MFA/RBA强制情况在无账号模式下保持未知；
- `passive_protocol_probe.py`：只读当前认证DOM，记录OAuth/OIDC端点与参数名、
  `state/nonce/PKCE`是否公开可见、Passkey控件和MFA/RBA提示；不保存参数值、
  不跟随第三方链接、不触发认证器；
- 网页详情和现场分类结果展示“访客可见认证安全（论文证据层）”，明确区分
  “公开入口已观察”与“协议安全已经验证”；
- `paper_registry.py`：维护B层核心论文的稳定标识与官方链接。
- `password_meter_evaluation.py`：落实 USENIX Security 2023 的加权
  Spearman、极端分箱 Precision 与 PrecisionSecurity；现场模式另外计算本站
  强度提示和本站校验的内部一致性，不把缺少破解真值的结果冒充为准确率。
- `jose_validation.py`：落实 IEEE S&P 2019 FAPI/JARM 的签名与上下文绑定思想，
  按 RFC 7515/7517/7519/8725 与 NIST SP 800-131A Rev.2 解析JWT/JWS/JWKS、
  执行RSA JWS验签和2048位模数门槛，并以
  `iss/aud/time/nonce/typ`联合谓词限制“通过”结论；网页现场模式不读取Cookie或
  Web Storage，只分析当前URL/DOM属性中已经公开的JOSE对象。
- `webauthn_observer.py`：在页面加载前包装但不主动调用
  `navigator.credentials.create/get`，只捕获页面自己发起的WebAuthn公开请求配置；
  challenge和用户/凭据ID在浏览器内脱敏，只输出字节长度、数量、枚举项与COSE
  算法编号。第二阶段按 USENIX Security 2026 的 PASSKEYS-RADAR/
  PASSKEYS-ATTACKER测量维度，增加固定IANA快照的算法分级、RP scope宽度、
  conditional/discoverable/non-discoverable模式、用户验证边界，以及三种
  Passkey生命周期signal API的被动观察。模块落实 IEEE S&P 2023 的
  FIDO2/WebAuthn形式化安全属性，并按 WebAuthn Level 3 Recommendation检查
  挑战、RP绑定和公开配置条件。
- `oidc_discovery.py`：对DOM已观察到或操作者明确提供的issuer执行有边界的
  Discovery/JWKS读取；逐跳执行公网DNS、固定IP连接、TLS证书、响应大小和JSON
  校验，只输出issuer绑定与密钥数量/类型/位数摘要，不保存JWK材料。

## B36 OIDC Discovery/JWKS数学口径

公开元数据链只有在TLS证书、issuer精确绑定、JWKS HTTPS地址和JWKS实际取得均
有证据时，才判定“公开发现链绑定通过”：

\[
V_{chain}=V_{TLS}\land V_{issuer}\land V_{jwks\_https}\land V_{jwks\_fetch}
\]

\[
C_{chain}=\frac{\sum_{j\in R}\mathbf{1}[V_j\neq unknown]}{|R|},
\quad R=\{TLS,issuer,jwks\_https,jwks\_fetch\}
\]

这里的PASS只针对公开元数据链，不代表某个JWT已经验签。JWKS卫生层另外检查
公开对称/私钥材料、RSA模数、重复 `kid`、畸形key、`alg=none`、算法与密钥类型
绑定，以及元数据/JWKS算法集合交集；发现明确问题可以FAIL/WEAK，但没有发现问题
仍保持UNKNOWN，因为一次公钥快照不能证明服务端实际私钥、算法白名单、key选择、
轮换和令牌上下文验证均正确。

## B35/B37 WebAuthn/Passkey数学口径

对第 `i` 个页面发起的WebAuthn仪式，根据注册或认证分别选择公开参数集合
`R_i`。配置证据覆盖率定义为：

\[
C_{WA}=\frac{1}{n}\sum_{i=1}^{n}
\frac{\sum_{j\in R_i}\mathbf{1}[o_{ij}\ \text{observed}]}{|R_i|}
\]

注册集合当前含 `challenge长度 / RP关系 / userVerification / COSE算法集合 /
residentKey`；认证集合含 `challenge长度 / RP关系 / userVerification /
allowCredentials数量 / mediation`。该公式只回答“请求配置看到了多少”，不是安全
评分。WebAuthn Level 3 要求challenge由RP在可信环境随机生成、响应值与原值匹配，
并建议至少16字节；访客侧只能证实长度，所以：

\[
|challenge|<16\Rightarrow weak,\qquad
|challenge|\ge16\not\Rightarrow secure
\]

即明显过短可以报告弱项，长度达标仍保持 `unknown`；没有服务端状态就不能证明
随机性、新鲜性、RP验签、origin/RP ID校验、计数器或用户验证实际执行。

B37在单个页面文档内生成不可导出的随机HMAC密钥，只将challenge映射为浏览器内
比较标签；Python和报告只得到“是否和前序调用相等”，得不到challenge、密钥或标签：

\[
R_{ch}=\frac{N_{reused}}{N_{compared}}
\]

只要观察到重复，即可证伪该文档内对应调用的新鲜性；`R_ch=0`不能证明服务端全局
唯一，也不能验证响应是否和原challenge匹配。

注册请求中的COSE集合记为 (A)，固定的IANA 2026-08-25推荐非对称签名集合记为
(R_{sig,recommended})：

\[
V_{alg}=(A\neq\varnothing)\land(A\subseteq R_{sig,recommended})
\]

弃用、不推荐、对称MAC或未知/非签名算法均会破坏该窄谓词。这里的PASS只说明
“本次请求的算法候选表合规”，不证明认证器最终选择或服务器正确验签。

RP scope宽度只保留域名标签差，不保存RP ID原文：

\[
B_{RP}=\max_i(|labels(host_i)|-|labels(rp_i)|)
\]

`B_RP>0`表示显式向父域放宽，按论文报告为攻击面扩大并标记WEAK，而不是声称漏洞
已被利用；不同域候选可能使用WebAuthn related-origins，在没有读取授权文档时保持
UNKNOWN。`userVerification=discouraged`也必须先和无口令路径、成功断言UV标志绑定，
访客模式不会单凭请求参数判定不安全。

### B-07空虚拟认证器受控交互

受控交互只对白名单HTTPS主机启用Chrome DevTools WebAuthn自动化接口，创建
不含凭据的CTAP2.1内部虚拟认证器。每轮输入字段数为0、显式点击最多1次；页面
导航前阻断注册 `create`，虚拟认证器前后凭据数必须为0。页面若在点击前已经发起
conditional认证，则停止点击，并将其与点击收益分开：

\[
Y_{WA}=\frac{N_{get,after\ click}}{N_{explicit\ click}},\quad
I_{pre}=\mathbf{1}[N_{get,before\ click}>0]
\]

因此GitHub公开入口的自动conditional调用不会被误写成“按钮触发成功”。

## B34 JWT/JWS/JWKS数学口径

JWT不是“能解码就可信”。先根据令牌用途 (P)（ID Token、JARM、JAR、客户端
断言或普通JWT）确定必查集合 (R(P))，只有集合内的联合谓词全部完成并为真，
才能判定验证通过：

\[
V_P=\bigwedge_{j\in R(P)}V_j,quad
V_j\in\{V_{sig},V_{alg},V_{iss},V_{aud},V_{time},V_{nonce},V_{typ}\}
\]

证据覆盖率单独计算，禁止把“没检查”当成“检查通过”：

\[
C_P=\frac{\sum_{j\in R(P)}\mathbf{1}[V_j\neq unknown]}{|R(P)|}
\]

其中RSA JWS的签名复核执行 RFC 7515 Appendix A.2 的公开密钥运算：

\[
m=s^e\bmod n,\qquad
EM=\mathrm{I2OSP}(m,k),\qquad
EM\stackrel{?}{=}00\|01\|FF\cdots FF\|00\|DigestInfo(H(M))
\]

当前研究验证器覆盖 `RS256/RS384/RS512`。ECDSA、EdDSA、PSS等算法只报告结构
证据，不自行实现密码库；将来应接入受维护的JOSE实现后再扩展验签。
`iss/aud/time`是已知OIDC/FAPI类用途的基础绑定项；`nonce/typ`在令牌实际包含、
调用者提供预期值或相应协议配置要求时加入 (R(P))，避免把某一种JWT规则误套到
所有用途。

## B33 口令强度计数学口径

在线猜测场景使用论文的频率加权秩相关：

\[
\rho_w=\frac{\sum_i w_i(x_i-\bar{x}_w)(y_i-\bar{y}_w)}
{\sqrt{\sum_i w_i(x_i-\bar{x}_w)^2\sum_i w_i(y_i-\bar{y}_w)^2}}
\]

离线破解场景先按每一种攻击策略分别比较破解口令和未破解口令的强度分布：

\[
KL(P\Vert Q)=\sum_i P(i)\log\frac{P(i)}{Q(i)}
\]

其中 (P) 是破解集合、(Q) 是未破解集合的强度桶分布；brute-force、
dictionary、probability和combined四种攻击者不得混在一起。实现不偷偷加平滑项：
当 (P(i)>0,Q(i)=0) 时显式标记无限散度，避免实验参数被代码悄悄改变。

最低/最高强度分箱另外使用：

\[
Precision=\frac{NC_L+NR_H}{NR_L+NC_L+NR_H+NC_H}
\]

\[
Precision_{Security}=\beta W_L\frac{NC_L}{NR_L+NC_L}
+(1-\beta)W_H\frac{NR_H}{NR_H+NC_H},\quad \beta=0.8
\]

现场浏览器没有口令人群频率与 cracked/uncracked 真值，不能计算以上准确率。
现场只报告自创但严格限界的站内一致率：

\[
C_{site}=1-\frac{N_{accepted,weak}+N_{rejected,strong}}{N_{paired}}
\]

观察到任一方向性矛盾可形成 `weak` 证据；即使有限样本的
`C_site=1`，也只能表示“当前样本内未发现矛盾”，结论仍为 `unknown`，不能升级
成安全通过或强度计准确。

`scripts/evaluate_password_meter.py` 可对经过伦理处理、且不含口令正文的标注
JSON/JSONL运行论文四类指标；KL输入只含攻击策略、强度桶、破解标签和可选聚合
计数，不需要口令正文。缺少任一类真值时对应结果保持 `null`。

## B08 账号恢复公开证据

`recovery_analysis.py` 按 USENIX Security 2024 的流程分层，将公开恢复入口、
恢复因子、Token生命周期、旧会话/认证器撤销与OPRF用户目录隐私分开。访客模式
不填写邮箱/手机号、不发送恢复请求，因此只计算：

\[
C_{rec}=\frac{I_{entry}+I_{factor}+I_{form}}{3}
\]

授权态安全结论需要全部联合证据：

\[
V_{rec}=V_{entropy}\land V_{one\_time}\land V_{expiry}\land
V_{session\_revoke}\land V_{auth\_revoke}
\]

公开页即使观察到邮箱恢复入口，也不能把后一个谓词判为通过，更不能据此推断
网站实现了论文的OPRF协议。

## B09 二维码登录生命周期

`qr_lifecycle.py` 按 USENIX Security 2025 的 `QrId / SessionID / Token` 和
生成、扫码、确认三阶段模型工作。公开模式只观察生成阶段；二维码图片、canvas
或SVG表示仅在浏览器内用不可导出的随机HMAC密钥进行相等性比较，Python只取得
“是否变化”和计数：

\[
R_{QR}=\frac{N_{changed}}{N_{compared}}
\]

\[
V_{QR}=V_{bind}\land V_{random}\land V_{server\_gen}\land
V_{one\_time}\land V_{token\_bind}\land V_{confirm}
\]

刷新率不能证明QrId随机、一次性或和Session绑定。公开模式不解码、不扫码、
不修改、不重放，也不尝试登录。

## B10 提交前表单秘密流

`leaky_forms.py` 直接落实 USENIX Security 2022 *Leaky Forms* 的浏览器测量方法：
在页面加载前安装读取/网络包装器，在浏览器内生成一次性合成邮箱和口令，触发
input/change/blur但不提交；监视原文、大小写、URL编码、Base64和SHA-256派生
表示。匹配标记的fetch/XHR/sendBeacon/form尝试会先记录后阻断，输出不含标记、
请求体、完整URL或哈希。

\[
E_{pre}=\frac{N_{detected\ before\ submit}}{N_{filled\ fields}}
\]

\[
I_{leak\_guard}=\mathbf{1}[N_{submit}=0\land N_{forwarded}=0\land N_{real}=0]
\]

第三方口令外传尝试可判FAIL，但仅表示浏览器端尝试被观察且阻断，不表示服务器
已收到。脚本读取与网络外传分开报告。

## B11 实验统计与阶段门槛

`experiment_metrics.py` 提供Precision/Recall/F1、Wilson置信区间、证据取得率、
UNKNOWN率、两轮精确一致率、阳性Jaccard与Cohen kappa。UNKNOWN保留在覆盖率，
但不得混入可判定准确率：

\[
P=\frac{TP}{TP+FP},\quad R=\frac{TP}{TP+FN},\quad
F_1=\frac{2PR}{P+R}
\]

\[
J_{2r}=\frac{|F_1\cap F_2|}{|F_1\cup F_2|},\qquad
\kappa=\frac{p_o-p_e}{1-p_e}
\]

`scripts/audit_b_series.py` 固定并核对A/B/C/D/E五层语料，机器可读输出保存在
`reports/archive/b_series_audit_20260908.json`，论文型总结见
`B_SERIES_STAGE_REPORT_20260908.md`。当前门槛是“工程文件通过、访客阶段部分通过、
完整竞赛实证未通过”，不能互相替代。

## 后续模块顺序

1. 口令政策漏斗与强度计一致性（第一阶段已完成：证据采集、公式、离线工具、
   Web结果；真实数据集准确性实验待做）；
2. MFA/OTP/RBA因子关系（已完成访客可见层，授权对照实验待做）；
3. OAuth/OIDC浏览器侧协议证据（已完成静态DOM元数据与公开
   Discovery/JWKS链；授权跳转链验证待做）；
4. JWT/JWS/JWKS被动验证（已完成公开结构探针、RSA验签、联合谓词、隐私边界、
   Discovery/JWKS安全抓取与Web展示；真实令牌到issuer/JWKS的授权闭环待做）；
5. WebAuthn/Passkey调用和公开参数（第一阶段已完成：可见控件、页面发起API调用、
   脱敏配置与公式；授权虚拟认证器/服务端断言验证待做）；
6. 恢复与二维码公开层已完成；授权条件下的Token、撤销、扫码确认与重放防护待测；
7. 提交前表单秘密流本地安全交互已完成；真实站点需伦理清单后再测；
8. 固定当前代码后执行两轮303站全量，并补认证图节点/边人工真值。

任何需要创建账号、发送验证码、伪造令牌或主动攻击的检测，默认不得在公开网站
模式运行。
