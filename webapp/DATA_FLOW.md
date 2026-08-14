# Mac、GitHub 与服务器数据闭环（v3）

## 哪份数据是权威数据

- `reports/sites/sites_latest.jsonl`：程序测量的权威数据，每个网站各有一条
  `login` 和一条 `signup` 记录；Mac 与服务器都通过 GitHub 同步它。
- `misc/manual_review.json`：已通过审核的人工核验权威数据。
- `reports/sites/profiles/` 与 `reports/sites/sites_summary.md`：由 JSONL 生成的
  人类可读报告，不反向覆盖 JSONL。
- `webapp/sites.db`：网站查询用的 SQLite 索引，可以由上述文件重建，不能作为
  唯一数据源。重建时会保留尚未审核的 `reviews_pending`。

## 一次网页操作怎样流转

### 新网站测量后选择“加入数据库”

1. 服务器先把完整登录/注册结果原子写入 `sites_latest.jsonl`，同一网站没有重测的
   另一侧会被保留；写文件失败时不会只改 SQLite。
2. 服务器立即更新 `sites.db`，所以网页无需等 Git 同步即可看到新结果；其他已打开
   的浏览器页面最多 30 秒自动刷新。
3. 每 6 小时 `server_sync.sh` 只快照网页相对服务器旧 HEAD 真正修改的站点/入口与
   人工条目，用干净工作树拉取 GitHub，再原子回放这些增量；随后重新生成档案/汇总、提交、
   重建数据库、重启服务并推送。拉取失败时也会先恢复快照，网页数据不会丢失。
4. Mac 执行 `git pull --rebase` 后即可在 `reports/sites/sites_latest.jsonl` 和逐站档案中
   得到该网站。若要主动从服务器 API 拉取，可使用 `scripts/pull_web_data.py`。

### 人工核验

1. 提交后只进入 `reviews_pending`，网页即时显示为“待审核”，不会提前改变正确率。
2. 管理员通过后，文本和结构化字段同时写入 `sites.db` 与
   `misc/manual_review.json`；网页立即分别比较登录、注册结果并给出正确、错误或
   证据不足的原因。
3. `unknown`、测量异常，以及人工未明确描述比较字段的记录不算“正确”或“错误”，
   而是证据不足。正确率分母仅含能比较的记录，覆盖率表示能比较记录占已核验记录的
   比例。
4. 下一次服务器定时同步把已审核人工数据推送到 GitHub，Mac 拉取后即可获得。

## 三端关系

```text
Mac（开发、全量测量、验收）
  ├─ push 代码与正式 reports ──> GitHub
  └─ pull 服务器提交 <────────── GitHub

GitHub（唯一交换桥梁和历史版本）
  ├─ 服务器定时 pull 代码/数据
  └─ 接收服务器增量快照回放后 push 的网页新增站点、报告和已审核人工数据

服务器（实时分类、协作审核、网页展示）
  ├─ reports/manual：持久数据
  └─ SQLite：即时网页索引，可重建
```

服务器不能直接修改 Mac 文件，Mac 也不会直接读取服务器磁盘；两端通过 GitHub
交换持久数据。网页接口只负责服务器当下的即时写入和显示。

## 常用命令

服务器立即部署 Mac 已推送的更新：

```bash
cd ~/measure
git pull --rebase
.venv/bin/python scripts/build_site_database.py
sudo systemctl restart sites-webapp
curl -fsS http://127.0.0.1:8000/api/stats
```

Mac 获取服务器最近一次已推送的数据：

```bash
cd "/Users/cjx_main/Desktop/2026 Chinacode/large-scale-web-measurement"
git pull --rebase
```

服务器定时任务（建议每 6 小时）：

```cron
0 */6 * * * cd /home/ubuntu/measure && ./webapp/server_sync.sh >> logs/server_sync.log 2>&1
```

整个改进周期保持 `misc/measure_version.txt` 为 `v3`。
