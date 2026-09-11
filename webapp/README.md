# 注册流程测量平台（Web 前端）

展示已测网站的注册流程（程序结果 + 人工复核），支持搜索和实时分类。

## 功能

- **搜索**：按域名/路线关键词搜数据库里的站点
- **详情**：每站展示程序测量（类型/路线/字段/阻断/步骤证据）+ 人工复核对照
- **实时分类**：输入任意网站主页 URL → 复用测量工具现场分类（安全只读）
- **自适应政策证据**：口令政策结果可展开查看长度边界、最少字符类数、固定必需类、
  已接受最小组合、各类最低数量、长度触发的 OR 放宽阈值和逐步决策；证据只保存
  候选结构，不保存口令原文

## Windows 本地一键运行（推荐）

在仓库根目录打开 PowerShell：

```powershell
.\webapp\run_local.ps1
```

脚本会自动完成以下工作：

- 首次运行时创建 `.venv` 并安装 Web 服务依赖；
- 浏览器驱动缓存到项目 `.cache`；Windows 没有 Chrome 时自动使用 Microsoft Edge；
- 用 `reports/sites/sites_latest.jsonl` 重建 SQLite 展示库；
- 自动合并 `reports/archive` 中最新一份全量口令策略实测结果；
- 仅在本机 `127.0.0.1:8000` 启动服务并打开浏览器；
- 生成本次实时测量所需的随机 `X-Measure-Token`，显示在终端中。

以后代码或数据更新后，再运行同一条命令即可重建并重启。常用选项：

```powershell
.\webapp\run_local.ps1 -NoBrowser       # 启动但不自动打开浏览器
.\webapp\run_local.ps1 -Port 8080       # 改用其他本地端口
.\webapp\run_local.ps1 -Stop            # 停止本地服务
```

脚本只会停止 PID 文件中、且可执行路径确认为本项目 `.venv` Python 的进程，
不会按端口或进程名批量结束其他程序。

## Linux/macOS 手动运行

```bash
# 1. 构建数据库（正式测量结果 + 人工复核 → SQLite）
.venv/bin/python scripts/build_site_database.py

# 2. 启动服务
chmod +x webapp/run_server.sh
./webapp/run_server.sh 8000

# 3. 浏览器打开
# http://127.0.0.1:8000
```

## 服务器部署

```bash
# 上传项目到服务器后：
./webapp/run_server.sh 8000

# 防火墙放行 8000 端口，组员访问:
# http://<服务器IP>:8000
```

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sites?q=关键词&limit=N` | 搜索站点 |
| GET | `/api/sites/{hostname}` | 站点详情 |
| GET | `/api/stats` | 统计（总数/人工核验数/类型分布） |
| POST | `/api/classify` | 输入 `{url, entry_kind}` 实时分类 |

## 数据更新流程

Windows 上每轮新测量或拉取新代码后重新运行：

```powershell
.\webapp\run_local.ps1
```

Linux/macOS 手动重建：

```bash
.venv/bin/python scripts/build_site_database.py   # 重建数据库
./webapp/run_server.sh 8000                       # 重启生效
```

人工复核结果维护在 `misc/manual_review.json`，重建数据库时自动合并。

历史批量口令测量的兼容格式为 `policy + method_used`；当前格式为
`pwd_policy + pwd_method`。数据库构建器会将二者统一为 Dashboard 的
`pwd_policy`，不会把流程分类中的 `policy` 误当成已测口令规则。

## 安全说明

- 实时分类只观察：不填身份信息、不发送验证码、不扫码、不提交注册/创建账号
- 服务器上实时分类需要 Chrome 环境（与测量工具相同）
