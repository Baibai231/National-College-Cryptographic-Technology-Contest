"""从服务器拉取网站数据并合并进本地（保持 Mac 与网站数据一致）。

用法:
  .venv/bin/python scripts/pull_web_data.py \
      --host http://120.53.5.132:8000 \
      --token 你的管理员口令 \
      [--output reports/sites/sites_latest.jsonl]

说明:
  - 拉取服务器全量站点记录（含网页新增/修改的站）+ 人工核验
  - 按 (hostname, entry_kind) 合并进本地 sites_latest.jsonl（服务器数据覆盖本地同站）
  - 合并 manual_review.json（服务器人工核验覆盖本地同站）
  - 跑完后本地重建数据库即可与网站一致
"""
import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))


def fetch(host, token):
    import urllib.request
    req = urllib.request.Request(
        host.rstrip("/") + "/api/export",
        headers={"X-Admin-Token": token},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def merge_records(records, jsonl_path):
    """按 (hostname, entry_kind) 合并：服务器记录覆盖本地同站同入口。"""
    local = {}
    if os.path.isfile(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                key = (r.get("hostname"), r.get("entry_kind"))
                local[key] = r
    added = updated = 0
    for r in records:
        key = (r.get("hostname"), r.get("entry_kind"))
        if not key[0] or not key[1]:
            continue
        if key in local:
            updated += 1
        else:
            added += 1
        local[key] = r
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in local.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return added, updated, len(local)


def merge_manual(manual_data, manual_path):
    """合并人工核验：服务器 manual 覆盖本地同站。"""
    local = {}
    if manual_path.is_file():
        with open(manual_path, encoding="utf-8") as f:
            local = json.load(f)
    server_sites = manual_data.get("sites", {})
    local_sites = local.setdefault("sites", {})
    merged = 0
    for host, entry in server_sites.items():
        if host not in local_sites or local_sites[host] != entry:
            local_sites[host] = entry
            merged += 1
    local["updated_at"] = manual_data.get("updated_at", "")
    with open(manual_path, "w", encoding="utf-8") as f:
        json.dump(local, f, ensure_ascii=False, indent=2)
    return merged


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="http://120.53.5.132:8000")
    ap.add_argument("--token", required=True)
    ap.add_argument("--output",
                    default=str(_PROJECT_ROOT / "reports" / "sites" / "sites_latest.jsonl"))
    args = ap.parse_args()

    print(f"从 {args.host} 拉取数据…")
    data = fetch(args.host, args.token)
    records = data.get("records", [])
    print(f"收到 {len(records)} 条测量记录")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    added, updated, total = merge_records(records, str(out))
    print(f"合并到 {out}: 新增 {added} 条，更新 {updated} 条，共 {total} 条")

    manual_path = _PROJECT_ROOT / "misc" / "manual_review.json"
    merged_manual = merge_manual(data.get("manual", {}), manual_path)
    print(f"人工核验合并: {merged_manual} 站更新")

    print("\n下一步（本地）:")
    print("  .venv/bin/python scripts/build_site_database.py")
    print("  ./webapp/run_server.sh 8000   # 本地预览或打包上传")


if __name__ == "__main__":
    main()
