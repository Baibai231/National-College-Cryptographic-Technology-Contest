# Cloudflare Radar 一键批量测量指南

本文档说明如何使用 `run_cloudflare_radar.ps1` 从 Cloudflare Radar Domain Rankings
生成网站目标，并接入 CryptoScope 的预筛与口令策略测量流程。

## 1. 功能概览

脚本位于：

```text
run_cloudflare_radar.ps1
scripts/run_radar_measurement.py
```

它会自动完成以下步骤：

1. 从 Cloudflare Radar 获取全球或地区域名排行；
2. 保存带响应 SHA-256 的榜单快照；
3. 生成标准化、去重后的目标域名清单；
4. 使用只读 HTTP 预筛寻找登录/注册入口；
5. 可选地启动浏览器口令策略测量；
6. 生成 JSONL 结果和覆盖率报告。

Cloudflare 官方说明中，`radar/ranking/top` 提供最多 100 个有序域名；更大范围使用
`ranking_top_200`、`ranking_top_1000` 等数据集流。大 bucket 是无序集合，因此工具不会
把文件位置伪装成流行度排名。

参考文档：

- [Cloudflare Domains ranking](https://developers.cloudflare.com/radar/investigate/domain-ranking-datasets/)
- [Cloudflare Radar Top API](https://developers.cloudflare.com/api/resources/radar/subresources/ranking/methods/top/)

## 2. 环境准备

在仓库根目录创建并安装虚拟环境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r webapp\requirements-server.txt
```

需要安装 Chrome 或 Microsoft Edge。批量模式默认使用无头浏览器。

## 3. 配置 Cloudflare API Token

不要把 Token 写入代码、命令历史或提交到 Git。仅在当前 PowerShell 会话中设置：

```powershell
$env:CLOUDFLARE_API_TOKEN = "<你的 Cloudflare API Token>"
```

脚本默认读取 `CLOUDFLARE_API_TOKEN`，也可以通过 `--api-token-env` 指定其他环境变量名。

## 4. 只获取榜单并预筛

下面的命令默认不会填写口令框，也不会启动主动口令策略探针：

```powershell
.\run_cloudflare_radar.ps1 `
  --top 1000 `
  --output-dir .cache\target-corpora\cloudflare-radar `
  --preflight-workers 16 `
  --resume
```

如果只需要地区 Top 100，例如中国地区：

```powershell
.\run_cloudflare_radar.ps1 `
  --top 100 `
  --location CN `
  --output-dir .cache\target-corpora\cloudflare-radar-cn `
  --resume
```

参数规则：

- `--top 1..100`：使用 Radar 有序榜单，可搭配 `--location CN` 等地区代码；
- `--top 101..1000000`：使用全球 `POPULAR` bucket，不支持地区参数；
- `--resume`：保留已经完成的预筛和后续测量记录；
- `--snapshot PATH`：离线复用此前生成的榜单快照，不再访问 Radar API；
- `--supplement FILE`：追加中文站点或专题站点清单，可重复指定。

## 5. 启动口令策略测量

主动测量必须提供站点所有者或研究负责人出具的授权范围文件：

```json
{
  "authorized_hosts": ["example.com", "*.owned.example"],
  "expires_at": "2026-12-31T23:59:59Z"
}
```

也可以使用 UTF-8 文本，每行一个主机名：

```text
example.com
login.owned.example
*.owned.example
```

然后运行：

```powershell
.\run_cloudflare_radar.ps1 `
  --top 1000 `
  --output-dir .cache\target-corpora\cloudflare-radar `
  --measure-policy `
  --authorization-manifest scope.json `
  --browser-workers 2 `
  --site-timeout 900 `
  --require-complete 1000 `
  --resume
```

脚本和底层测量器仍遵守以下边界：

- 不绕过 CAPTCHA、扫码或第三方授权；
- 不发送短信/邮件验证码；
- 不创建账号、不登录真实账号；
- 只在安全可达的注册口令框中进行客户端校验探针；
- 同一主机的注册和登录任务自动串行；
- 超时会清理 worker 派生的浏览器进程。

## 6. 生成的文件

`--output-dir` 下会生成：

| 文件 | 说明 |
|---|---|
| `radar_snapshot.json` | Radar 响应摘要、榜单类型、时间和响应哈希 |
| `targets.txt` | 可直接供批量测量使用的 URL 清单 |
| `targets.json` | 目标域名、来源、排名/桶位置和去重元数据 |
| `preflight.jsonl` | 只读 HTTP 预筛结果 |
| `candidates.jsonl` | 按优先级排序的注册入口候选 |
| `policy.jsonl` | 浏览器策略测量结果 |
| `coverage.json` | 机器可读覆盖率报告 |
| `coverage.md` | Markdown 覆盖率报告 |

注意：大 bucket 没有可靠的单域名流行度排名，`targets.json` 中的 `rank` 会保持为
`null`，`bucket_position` 仅代表快照文件中的稳定位置。

## 7. 断点续跑、分片与阶梯测试

建议先运行小规模阶梯测试：

```powershell
# 先预筛 20 个
.\run_cloudflare_radar.ps1 --top 1000 --max-sites 20 --output-dir .cache\radar-20 --resume

# 再测量第 0/4 片
.\run_cloudflare_radar.ps1 `
  --top 1000 `
  --output-dir .cache\radar-shard-0 `
  --measure-policy `
  --authorization-manifest scope.json `
  --shard-count 4 `
  --shard-index 0 `
  --resume
```

只有通过严格证据门的结果才会计入完整站点数。`--require-complete 1000` 未达到目标时
返回退出码 2，但已完成的结果会保留，可直接使用 `--resume` 继续。

## 8. 离线复用快照

首次运行会生成：

```text
.cache/target-corpora/cloudflare-radar/radar_snapshot.json
```

后续可以固定同一批目标，不受 Radar 日榜更新影响：

```powershell
.\run_cloudflare_radar.ps1 `
  --top 1000 `
  --snapshot .cache\target-corpora\cloudflare-radar\radar_snapshot.json `
  --skip-preflight `
  --measure-policy `
  --authorization-manifest scope.json `
  --resume
```

`--skip-preflight` 必须同时指定快照，这是为了防止新榜单目标与旧候选文件混用。

## 9. 常见问题

### 未找到 API Token

确认当前 PowerShell 会话中存在：

```powershell
echo $env:CLOUDFLARE_API_TOKEN
```

如果 Token 失效或权限不足，脚本会在获取 Radar 榜单阶段停止，不会启动浏览器。

### 为什么 Top 1000 没有精确 rank

Cloudflare 对大范围排名提供的是无序 bucket。工具保留 `rank: null`，避免把数据集文件
位置误报为真实排名。

### 为什么预筛成功但完整策略数量很少

预筛只证明公开页面可访问或存在认证线索。完整策略还要求安全到达注册口令框、建立接受/拒绝
对照并完成长度、组成和允许项证据。验证码、邮箱验证、登录前置步骤和前端异步校验都会使站点
进入部分证据或阻断状态。

### 如何查看是否达到 1000 站

查看：

```text
<output-dir>/coverage.md
<output-dir>/coverage.json
```

其中 `goal_progress_percent` 是相对千站目标的进度，`complete_rate_percent` 是当前批次中
完整结果的比例，两者含义不同。
