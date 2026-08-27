# reports 目录说明

## 目录结构

| 目录/文件 | 用途 |
|---|---|
| `sites/sites_latest.jsonl` | **程序测量权威数据**（按 hostname + entry_kind；当前 154 站、307 条 v4，个别站可能只有安全可达的一侧） |
| `sites/sites_summary.md` | 站点汇总表（每站一行：分类、路线、字段、口令位置） |
| `sites/profiles/` | 每站详细档案（自动观察路线 + 步骤证据） |
| `archive/`（原 test/） | 两轮全量、差异复测、仲裁与验收记录（保留备查，不直接参与网站） |

## 使用流程

1. **测量**：`scripts/run_measurement.py --input <站点清单> --output <批次.jsonl> --kinds signup,login`
2. **两轮验收**：先用 `compare_measurement_rounds.py` 找差异，再对差异项复测并用
   `select_measurement_results.py --baseline <旧正式结果>` 仲裁；不得用 unknown/error
   覆盖同一版本的最后有效证据。
3. **生成档案**：`scripts/generate_profiles.py --results reports/sites/sites_latest.jsonl --profiles-dir reports/sites/profiles --summary reports/sites/sites_summary.md`
4. **更新网站数据库**：`scripts/build_site_database.py`（默认读 sites_latest.jsonl + misc/manual_review.json + misc/site_keywords.json）

网页“加入数据库”会先原子更新 `sites_latest.jsonl` 再更新 SQLite，并保留没有重测的
另一侧记录。全量回归先写入 `archive/`，通过两轮对比、差异复测和人工抽查后才提升为
正式 `sites_latest.jsonl`；SQLite 只是可重建的服务索引。
