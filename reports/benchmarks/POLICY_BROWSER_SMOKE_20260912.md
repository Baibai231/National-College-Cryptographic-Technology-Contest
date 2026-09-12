# 真实浏览器口令政策冒烟基准（2026-09-12）

## 范围与安全边界

- 目标：LinkedIn 公开注册页，来自 Top 100 预筛候选。
- 环境：Windows、Microsoft Edge 151、无头模式、单 worker。
- 行为：只在新口令字段填写本地候选并触发客户端校验。
- 未执行：表单提交、发送验证码、绕过 CAPTCHA、读取邮箱、创建账号。

## 复现命令

```powershell
.\.venv\Scripts\python.exe scripts/run_measurement.py `
  --preflight-candidates .cache/target-corpora/candidates_sample100_v3_20260912.jsonl `
  --only linkedin.com --kinds signup --measure-policy `
  --output .cache/target-corpora/policy_linkedin_optimized_v2_20260912.jsonl `
  --workers 1 --site-timeout 360 --headless `
  --inline-accept-quiet-seconds 3 --overwrite --checkpoint-every 1

.\.venv\Scripts\python.exe scripts/report_policy_coverage.py `
  .cache/target-corpora/policy_linkedin_optimized_v2_20260912.jsonl `
  --require-complete 1
```

## 结果

| 指标 | 值 |
|---|---:|
| 注册口令框到达 | 是 |
| 接受与拒绝对照 | 均观察到 |
| 长度下限 | 6 |
| 最大长度 | 到协议上界 128 未观察到 |
| 自适应长度探针 | 5 |
| 自适应组成探针 | 4 |
| 全部脱敏探针 | 37 |
| Emoji | 实测接受 |
| 泄露口令结论 | 1 条符合其他政策的泄露口令被接受，因此“不阻止所有泄露口令” |
| 总耗时 | 247 秒 |
| 严格质量状态 | `complete` |

同一环境的上一轮在已有 3 秒干净观察窗、但仍包含重复鼠标操作和 7 个 Unicode 枚举时耗时
343 秒。本轮减少 96 秒（约 28%），同时增加了真正的 Emoji 探针，未降低严格证据门。

## 解释

这是一条端到端可复现的完整样本，不代表总体覆盖率。当前严格目标进度为 1/1000；是否能
达到千站仍需由分片批量结果和 `--require-complete 1000` 验收，不能由单站成功外推。
