# 网站维护指南（完整版）

> 适用：注册流程测量平台（FastAPI + SQLite + Chrome 实时分类）
> 服务器：Ubuntu 22.04，网站 http://120.53.5.132:8000
> 更新：2026-08-14

---

## 一、版本问题

### 背景
版本号（`misc/measure_version.txt`）标记"代码大版本"，区分不同代码测出的结果。
网站显示当前版本，历史版本可查。

### 方案 1：大改动升版本（推荐）
```bash
# Mac
echo "v4" > misc/measure_version.txt     # 手动升版本（大改动才升）
# 重新测量需要更新的站（或全量）
.venv/bin/python scripts/run_measurement.py --input misc/sites_base_60.txt --output reports/sites/sites_latest.jsonl --workers 3
.venv/bin/python scripts/build_site_database.py
```
新结果标 v4 显示，旧 v3 自动进"历史结果"。

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
- **两轮结果不一样**：站点风控波动（登录弹窗时开时不开），不是版本问题。跑 2 次取多数。
- **网页入库的站版本低**：服务器代码旧。同步代码后重新入库即可（更新覆盖）。

---

## 二、同步问题（Mac ↔ 服务器）

### 背景
代码和数据的流向：Mac 是数据源头，服务器是展示+增量收集。

### 方案 1：标准同步流程（推荐）
```bash
# Mac 端
cd ~/Desktop/2026\ Chinacode/large-scale-web-measurement
.venv/bin/python scripts/pull_web_data.py --host http://120.53.5.132:8000 --token 你的口令
# ↑ 第1步：拉回服务器增量（新站/人工审核），保证 Mac 数据不丢
./webapp/package.sh
scp /tmp/measure.tar.gz ubuntu@120.53.5.132:~
# ↑ 第2步：打包上传

# 服务器端
cd ~ && mkdir -p measure && tar xzf measure.tar.gz -C measure
cp ~/manual_backup.json measure/misc/manual_review.json 2>/dev/null; true
cd measure && .venv/bin/python scripts/build_site_database.py && sudo systemctl restart sites-webapp
```
> 先拉回再上传，顺序不能反。

### 方案 2：服务器单独跑测量（不依赖 Mac 上传）
服务器有完整代码+Chrome，可以直接跑：
```bash
cd ~/measure
git pull   # 如果能连 GitHub；不能就连不了，用方案1
.venv/bin/python scripts/run_measurement.py --input misc/sites_base_60.txt --output reports/sites/sites_latest.jsonl --workers 3
.venv/bin/python scripts/build_site_database.py
sudo systemctl restart sites-webapp
```

### 常见问题
- **服务器连不上 GitHub**：正常（国内网络）。一律用方案 1（Mac 打包上传）。
- **包解压后文件散落**：必须用 `tar xzf xxx.tar.gz -C ~/measure`（-C 指定目录）。
- **人工审核数据被覆盖**：上传前先 `cp ~/measure/misc/manual_review.json ~/manual_backup.json`，解压后恢复。

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
- **审核后正确率没变**：审核只影响"人工已核验"计数和该站状态；程序正确率是自动计算的（程序结论 vs 人工文本粗匹配），如果人工文本写得不含"密码/验证码"关键词可能不计入匹配，属正常。

---

## 五、日常操作速查

| 想做什么 | 命令 |
|---|---|
| 本地预览网站 | `./webapp/run_server.sh 8000` → http://127.0.0.1:8000 |
| 更新服务器代码 | Mac `package.sh` + `scp` + 服务器 `tar -C ~/measure` + `restart` |
| 拉回网站数据 | `.venv/bin/python scripts/pull_web_data.py --host http://120.53.5.132:8000 --token 口令` |
| 全量重测 | `scripts/run_measurement.py --input misc/sites_base_60.txt --output reports/sites/sites_latest.jsonl --workers 3` |
| 重建数据库 | `scripts/build_site_database.py` |
| 审核人工提交 | 网页「待审核管理」或 `merge_reviews.py --apply` |
| 升版本 | `echo "v4" > misc/measure_version.txt` |
| 服务器重启自启 | systemd 已配置，重启服务器后网站自动恢复 |
