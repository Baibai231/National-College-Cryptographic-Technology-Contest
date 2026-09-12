# 口令策略千站目标覆盖率

> 完整站点必须经过主动测量，同时具备接受/拒绝对照、长度边界、
> 字符组成和允许项证据；仅分类、数据库命中或页面提示不计入。

- 输入文件：reports\archive\full303_policy_20260829.jsonl
- 不同注册站点：303
- 完整测量站点：5 / 1000
- 当前批次完整率：1.65%
- 距离目标：995 个

## 测量漏斗

| 阶段 | 站点数 | 占输入站点 |
|---|---:|---:|
| 站点可访问 | 300 | 99.01% |
| 注册入口已确认 | 163 | 53.8% |
| 到达注册密码框 | 61 | 20.13% |
| 主动策略测量已运行 | 16 | 5.28% |
| 观察到接受对照 | 16 | 5.28% |
| 观察到拒绝对照 | 16 | 5.28% |
| 长度边界完整 | 13 | 4.29% |
| 字符组成完整 | 16 | 5.28% |
| 允许项完整 | 8 | 2.64% |

## 主要未完成原因

| 原因 | 站点数 |
|---|---:|
| `permissive_policy_incomplete` | 295 |
| `length_boundary_incomplete` | 290 |
| `accepted_control_missing` | 287 |
| `active_policy_measurement_not_run` | 287 |
| `composition_policy_incomplete` | 287 |
| `rejected_control_missing` | 287 |
| `password_field_not_reached` | 242 |
| `signup_entry_not_confirmed` | 140 |
| `infrastructure_error` | 3 |
| `policy_marked_inconclusive` | 1 |
