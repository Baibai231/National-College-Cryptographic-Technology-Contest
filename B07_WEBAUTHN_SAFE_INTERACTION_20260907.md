# B-07 WebAuthn/Passkey空虚拟认证器受控交互实验

日期：2026-09-07  
环境：Mac 本地，Chrome 152，无头、独立会话  
公开目标：GitHub 官方 Passkey 登录入口  
运行边界：不输入账号或口令、不注册、不提交表单、不使用真实认证器、不尝试登录成功

## 1. 研究问题

B-07 第三阶段证明“Passkey 目录阳性”不等于“普通公开登录首屏能观察到
WebAuthn 请求”。本阶段继续回答两个更窄的问题：

1. 在严格白名单和空虚拟认证器条件下，公开 Passkey 登录入口是否会发起
   `navigator.credentials.get({publicKey: ...})`？
2. 观察到的请求是由测量程序点击触发，还是页面在点击前通过 conditional UI
   自动发起？

这两个来源必须分开。否则页面预触发会被错误计入按钮点击收益。

## 2. 论文与标准如何进入代码

- USENIX Security 2026 *The State of Passkeys* 的官方工具使用浏览器与认证器
  仿真研究真实部署。本实验复用这一“浏览器 + 虚拟认证器 + 页面仪式观察”方法，
  但收紧为无需账号的空认证器模式。
- IEEE S&P 2023 的 FIDO2/WebAuthn 形式化工作提供 challenge-response、RP绑定、
  用户验证和公钥凭据的密码学属性框架。
- W3C WebAuthn Level 3 的自动化接口由 Chrome DevTools `WebAuthn` 域直接执行：
  启用 CTAP2.1 内部虚拟认证器、读取凭据数并在结束时删除认证器。

代码不是仅展示论文名字：虚拟认证器参数、仪式分类、challenge/RP/UV 摘要和
两轮配置向量都由上述接口实际生成。

## 3. 安全守卫

公开站点只有同时满足以下条件才允许进入交互判断：

- URL 属于预先固定的 HTTPS 主机；
- 每站最多 1 次点击，且只能匹配唯一、可见、启用的精确 Passkey 文本；
- 测量程序填写字段数为 0；
- CTAP2.1 虚拟认证器初始凭据数为 0；
- 页面导航前阻断 `navigator.credentials.create({publicKey})`；
- 若页面已在点击前发起 WebAuthn，立即停止寻找或点击控件；
- 结束时虚拟凭据仍为 0，随后删除虚拟认证器并退出浏览器。

安全守卫定义为：

\[
I_{guard}=\mathbf{1}[N_{input}=0\land N_{probe\_cred}=0\land
N_{seed}=0\land N_{after}=0\land N_{real\_auth}=0]
\]

显式点击触发率只计算点击以后新增的认证调用：

\[
Y_{WA}=\frac{N_{get,after\ click}}{N_{explicit\ click}}
\]

页面预触发单独记录：

\[
I_{pre}=\mathbf{1}[N_{get,before\ click}>0]
\]

两轮脱敏配置一致率为：

\[
A_{cfg}=\frac{\sum_i\mathbf{1}[x_i^{(1)}=x_i^{(2)}]}
{N_{comparable}}
\]

## 4. 合成页验证

本地合成页只有一个精确 `Sign in with a passkey` 按钮。真实 Chrome 虚拟认证器
链路得到：

- 按钮点击 1 次；
- 页面发起认证 `get` 1 次、注册 `create` 0 次；
- challenge 长度 32 字节；
- RP 为当前主机，`userVerification=required`；
- 虚拟凭据前后均为 0；
- 点击触发与安全守卫均 PASS。

这证明“点击以后新增调用”的代码路径可运行，不依赖伪造的 Python 结果。

## 5. GitHub 两轮结果

| 指标 | 第1轮 | 第2轮 |
|---|---:|---:|
| 页面加载到官方登录页 | 是 | 是 |
| 明确点击次数 | 0 | 0 |
| 点击前自动认证调用 | 1 | 1 |
| 认证模式 | conditional | conditional |
| challenge 长度 | 32 字节 | 32 字节 |
| RP关系 | 当前主机 | 当前主机 |
| userVerification | required | required |
| allowCredentials数量 | 0 | 0 |
| 注册调用 | 0 | 0 |
| 虚拟凭据（前/后） | 0/0 | 0/0 |
| 安全守卫 | PASS | PASS |

两轮 14 个可比较脱敏特征全部一致，`A_cfg=14/14=1.0`。第一轮耗时
67.708 秒、第二轮 5.174 秒，说明网络/页面装载时间仍有明显漂移；耗时没有混入
配置一致率。

最重要的结论不是“按钮没点到”，而是 GitHub 在精确点击前就自动发起了
conditional WebAuthn。程序正确停止点击，将显式触发率保持 UNKNOWN，同时把
`I_pre=1` 单独判为观察通过。强行继续点隐藏或尚未可用的控件反而会产生重叠仪式，
破坏归因。

## 6. 能宣称与不能宣称

可以宣称：在两轮未登录公开测量中，GitHub 官方入口稳定发起 conditional
WebAuthn 认证请求；公开参数为 32 字节 challenge、当前主机 RP、UV required、
空 allowCredentials；空虚拟认证器和零输入守卫成立。

不能宣称：challenge 具备全局新鲜性、服务端正确保存或比对 challenge、签名验签
正确、账号绑定安全、Passkey 添加/删除/恢复安全，或 GitHub 登录已经成功。这些都
需要授权账号和服务端状态。

## 7. 可复核产物

- 两轮结果：`reports/archive/webauthn_safe_github_r1_20260907.jsonl`、
  `reports/archive/webauthn_safe_github_r2_20260907.jsonl`
- 对比：`reports/archive/webauthn_safe_github_comparison_20260907.json`
- 探针：`scripts/probe_webauthn_safe_interaction.py`
- 两轮分析：`scripts/analyze_webauthn_safe_rounds.py`
- 合成验证：`scripts/smoke_webauthn_safe_interaction.py`

所有文件只保存派生长度、枚举、数量和关系，不保存 challenge 原文、RP ID、
credential ID、认证器响应或任何账号信息。
