# reports 目录说明

## 目录结构

| 目录/文件 | 用途 |
|---|---|
| `sites/sites_latest.jsonl` | **最新测量记录**（所有站一次全量测量的结果，网站数据库的数据源） |
| `sites/sites_summary.md` | 站点汇总表（每站一行：分类、路线、字段、口令位置） |
| `sites/profiles/` | 每站详细档案（自动观察路线 + 步骤证据） |
| `archive/`（原 test/） | 历史测量批次（保留备查，不参与网站） |

## 使用流程

1. **测量**：`scripts/run_cn60_classify.py --input <站点清单> --output reports/sites/sites_latest.jsonl`
2. **生成档案**：`scripts/generate_cn60_profiles.py --results reports/sites/sites_latest.jsonl --profiles-dir reports/sites/profiles --summary reports/sites/sites_summary.md`
3. **更新网站数据库**：`scripts/build_site_database.py`（默认读 sites_latest.jsonl + misc/manual_review.json + misc/site_keywords.json）

每次新测量都写入 `sites_latest.jsonl`（覆盖），旧批次在 `archive/` 里保留。
