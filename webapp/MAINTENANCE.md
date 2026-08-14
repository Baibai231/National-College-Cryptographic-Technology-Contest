# 网站维护指南（完整版）

> 适用：注册流程测量平台（FastAPI + SQLite + Chrome 实时分类）
> 服务器：Ubuntu 22.04，网站 http://120.53.5.132:8000
> 更新：2026-08-14

> 当前维护基线固定为 **v3**。本轮数据权威来源、网页实时写入、每 6 小时同步以及
> Mac/GitHub/服务器的完整关系见 [DATA_FLOW.md](DATA_FLOW.md)。不要把
> `webapp/sites.db` 当成唯一数据源，它只是可重建的网页索引。

---

## 一、版本问题

### 背景
版本号（`misc/measure_version.txt`）标记"代码大版本"，区分不同代码测出的结果。
网站显示当前版本，历史版本可查。

### 方案 1：未来确需大版本时再升版本
```bash
# Mac
# 当前任务不要修改 misc/measure_version.txt；它必须保持 v3
# 重新测量需要更新的站（或全量）
.venv/bin/python scripts/run_measurement.py --input misc/sites_base_60.txt --output reports/sites/sites_latest.jsonl --workers 3
.venv/bin/python scripts/build_site_database.py
```
当前改进周期的所有新结果仍标 `v3`。只有项目负责人以后明确决定新版本时才升级。

### 方案 2：小修复不升版本（日常用）
小 bug 修复后**不升版本**，直接重新测量受影响的站：
```bash
# 只重测几个站
printf "https://www.zhihu.com/\nhttps://www.imooc.com/\n" > /tmp/fix.txt
.venv/bin/python scripts/run_measurement.py --input /tmp/fix.txt --output reports/sites/sites_latest.jsonl --workers 1
.venv/bin/python scripts/build_site_database.py
```
结果仍是当前版本号，旧结果被覆盖。

### 判断"大改动 vs 小修复"
| 类型 | 示例 | 是否升版本 |
|---|---|---|
| 小修复 | 误判修复、等待时序、网络容错 | 否 |
| 大改动 | 分类逻辑重构、新增流程类型、字段语义变化 | 是 |

### 常见问题
- **两轮结果不一样**：站点风控会波动。两次全量后对差异项做第三次定向复测，
  采用多数结果；只有一轮取得有效页面证据时优先成功记录，三次都不同时标记人工关注。
- **网页入库的站版本低**：服务器代码旧。同步代码后重新入库即可（更新覆盖）。

---

## 二、同步问题（Mac ↔ 服务器）

### 背景
Mac 负责开发和全量验收，服务器负责展示与网页增量；GitHub 是两端的交换桥梁。
程序结果以 `reports/sites/sites_latest.jsonl` 为准，人工结果以
`misc/manual_review.json` 为准。服务器每 6 小时先保存网页增量，再拉取、重建、
重启和推送，因此不会用一次数据库重建抹掉网页新增站点或待审核记录。

### 方案 1：标准同步流程（推荐）
```bash
# Mac：提交并推送代码/正式数据；获取服务器网页增量时直接拉取
git push
git pull --rebase

# 服务器：立即部署（定时任务也会自动执行同一套安全流程）
cd ~/measure
./webapp/server_sync.sh
```
`server_sync.sh` 的顺序固定为：快照网页相对旧 HEAD 的真实增量 → 恢复干净工作树 →
pull --rebase → 按站点/入口原子回放增量 → 生成报告并提交 → 重建 SQLite → 重启 →
push。未变化的旧服务器记录不会覆盖 Mac 新全量结果；拉取失败也会先
恢复快照。完整解释见 `webapp/DATA_FLOW.md`。

### 方案 2：API 主动拉回（GitHub 暂未同步时）
```bash
cd "/Users/cjx_main/Desktop/2026 Chinacode/large-scale-web-measurement"
.venv/bin/python scripts/pull_web_data.py \
  --host http://120.53.5.132:8000 --token 你的口令
```
该脚本按 `(hostname, entry_kind)` 原子合并，保留完整状态、证据、置信度与错误信息。

### 常见问题
- **服务器连不上 GitHub**：`server_sync.sh` 会重试；仍失败时保留本地提交，下次继续。
- **人工审核或待审核会不会被覆盖**：已审核数据已写回 JSON；待审核行在重建 SQLite
  前备份并在重建后恢复。
- **网页新增站点何时可见**：写入成功后本浏览器立即可见，其他页面最多 30 秒刷新；
  GitHub/Mac 则等下一次同步（最多约 6 小时）。

---

## 三、网络问题

### 背景
- GitHub 国内不稳定：Mac 有代理能连，服务器直连常超时。
- Chrome/驱动下载源（Google）国内不稳定。

### 方案 1：GitHub 访问（Mac 代理 / 服务器超时重试）
```bash
# 服务器 git 操作失败时：
# 1) 多试几次（网络波动）
git pull   # 重试 2-3 次
# 2) 配置代理（如果有可用代理）
git config --global http.proxy http://代理IP:端口
# 3) 放弃 git，用 Mac 打包上传（见同步章节）
```

### 方案 2：Chrome 版本过旧/驱动不匹配
```bash
# 服务器 Chrome 是 Ubuntu 自带 85 版（太老）时，用 Mac 下载新版：
# Mac 上下载 linux64 的 Chrome+driver，scp 上传到 ~/measure/webapp/browser-linux/
# 解压后配置环境变量（已配置过）：
# SITES_CHROME_BIN=.../chrome-linux64/chrome
# SITES_CHROMEDRIVER=.../chromedriver-linux64/chromedriver
sudo systemctl show sites-webapp -p Environment   # 验证环境变量
```

### 常见问题
- **实时分类报 "cannot connect to chrome"**：缺系统库，`sudo apt install -y libnss3 libgbm1 libxshmfence1 ...`。
- **报错 "session not created"**：Chrome 与 chromedriver 版本不匹配，重新下载配套版本。
- **网站打不开**：防火墙没放行 8000 端口（控制台安全组 + `sudo ufw allow 8000`）。

---

## 四、组员提交问题

### 背景
组员网页提交人工观察 → 待审核表 → 管理员核验 → 合并进正式数据。

### 方案 1：网页审核（推荐，不用敲命令）
1. 网站右上角点「待审核管理」
2. 输入管理员口令（`SITES_ADMIN_TOKEN`，服务器 systemd 配置里）
3. 看列表：每条显示站点、登录/注册观察、提交人、时间
4. 点「通过」→ 自动合并进数据库 + manual_review.json，该站变"已人工核验"
5. 点「删除」→ 拒绝该提交

### 方案 2：命令行审核（服务器）
```bash
cd ~/measure
.venv/bin/python scripts/merge_reviews.py --db webapp/sites.db --manual misc/manual_review.json
# 先预览（不带 --apply）
.venv/bin/python scripts/merge_reviews.py --db webapp/sites.db --manual misc/manual_review.json --apply
# 确认无误后真正合并
.venv/bin/python scripts/build_site_database.py
sudo systemctl restart sites-webapp
```

### 方案 3：防重复提交（已内置）
- 提交弹窗打开时自动查询该站已有待审核份数，提示"已有 N 份待审核，请确认不重复"
- 详情页人工复核区显示"（N 份待审核）"

### 常见问题
- **组员重复提交**：已有提示。你审核时删除重复的即可。
- **口令忘了**：服务器 `sudo systemctl show sites-webapp -p Environment` 查看，或改 systemd 文件重新设置。
- **审核后正确率没变**：审核通过后会立即重新计算。`unknown`、程序异常或人工没有
  提供可比较字段时归入“证据不足”，不进入正确率分母；同时查看覆盖率才能知道
  已核验记录中有多少真正可比较。结构化选项比自由文本更稳定。

---

## 五、日常操作速查

| 想做什么 | 命令 |
|---|---|
| 本地预览网站 | `./webapp/run_server.sh 8000` → http://127.0.0.1:8000 |
| 更新服务器代码 | Mac push；服务器 `git pull --rebase`、重建数据库、重启服务 |
| 拉回网站数据 | `.venv/bin/python scripts/pull_web_data.py --host http://120.53.5.132:8000 --token 口令` |
| 全量重测 | `./webapp/update_data.sh`（默认合并四份清单，共 151 站） |
| 重建数据库 | `scripts/build_site_database.py` |
| 审核人工提交 | 网页「待审核管理」或 `merge_reviews.py --apply` |
| 查看当前版本 | `cat misc/measure_version.txt`（本轮必须为 `v3`） |
| 服务器重启自启 | systemd 已配置，重启服务器后网站自动恢复 |
