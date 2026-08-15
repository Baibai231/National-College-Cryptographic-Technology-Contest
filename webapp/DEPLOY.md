# 服务器部署指南

把测量平台部署到服务器供组员访问。

## 方案对比

| 方案 | 费用 | 适用 |
|---|---|---|
| **A. 云服务器（推荐）** | 学生优惠约 60-100 元/年（阿里云/腾讯云轻量） | 需要实时分类（跑 Chrome） |
| B. 本地电脑 + 内网穿透 | 免费（frp/ngrok） | 临时演示 |
| C. 纯静态托管（Vercel/Netlify） | 免费 | 只展示数据库，不能实时分类 |

推荐 A：实时分类需要在服务器上跑 Chrome，必须有真实 Linux 服务器。

## 方案 A：云服务器（阿里云/腾讯云轻量）

### 1. 选配置

- 系统：Ubuntu 22.04 LTS
- 配置：2 核 2G 起（跑 Chrome 建议 2 核 4G）
- 学生认证有优惠价，或购买轻量应用服务器

### 2. 上传代码

```bash
# 本地把项目打成包上传（或 git clone）
scp -r ~/Desktop/2026\ Chinacode/large-scale-web-measurement user@服务器IP:~/measure
```

### 3. 服务器环境准备（一次性）

```bash
cd ~/measure

# Python 3.9+ 虚拟环境
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt fastapi uvicorn 2>&1 | tail -1

# Chrome 浏览器（实时分类必需）
sudo apt update
sudo apt install -y chromium-browser  # 或 google-chrome-stable
# 或运行项目自带脚本（如有）
```

### 4. 启动服务

```bash
# 无显示器环境：启用无头 Chrome
SITES_HEADLESS=1 ./webapp/run_server.sh 8000
```

### 5. 防火墙放行

```bash
sudo ufw allow 8000/tcp
# 云服务器控制台还要在安全组放行 8000 端口
```

组员访问：`http://服务器IP:8000`

### 6. （可选）开机自启 systemd

```bash
sudo tee /etc/systemd/system/sites-webapp.service > /dev/null << 'EOF'
[Unit]
Description=注册流程测量平台
After=network.target

[Service]
WorkingDirectory=/home/USER/measure
Environment=SITES_HEADLESS=1
Environment=SITES_ADMIN_TOKEN=请替换为高强度随机口令
Environment=SITES_CLASSIFY_CONCURRENCY=2
ExecStart=/home/USER/measure/.venv/bin/python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sites-webapp
```

### 7. （可选）域名 + Nginx

购买域名（需备案才能用 80 端口；不备案可用其他端口或 IP 直接访问）：

```nginx
server {
    listen 80;
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

## 方案 B：本地电脑 + 内网穿透（临时）

本地 `./webapp/run_server.sh 8000` 后，用 frp 或 ngrok 把 8000 端口暴露到公网：
组员访问临时公网地址（每次重启地址会变，适合演示）。

## 更新流程

代码与正式数据经 GitHub 部署；`reports/sites/sites_latest.jsonl` 和
`misc/manual_review.json` 是持久数据，`webapp/sites.db` 只是可重建索引。
立即部署（不要绕过网页增量快照直接 pull）：

```bash
cd ~/measure
./webapp/server_sync.sh
curl -fsS http://127.0.0.1:8000/api/stats
```

建议设置每 6 小时同步。脚本只快照服务器相对旧 HEAD 真正变化的网页站点/入口与
已审核人工条目，
用干净工作树拉取远端，再按站点/入口原子回放并提交；即使 Mac 与服务器同时修改
JSONL 也不会直接 rebase 冲突，未修改的服务器旧记录不会覆盖 Mac 新全量结果；拉取
失败时快照也会恢复。reports 变化时会重新生成档案。网页写请求与同步/数据库替换共享
跨进程锁；部署标记和 API 健康检查确保建库或重启失败后下一轮仍会重试。

```bash
chmod +x webapp/server_sync.sh
crontab -e
```

```cron
0 */6 * * * cd /home/ubuntu/measure && ./webapp/server_sync.sh >> logs/server_sync.log 2>&1
```

完整三端关系、实时刷新与正确率计算规则见 [DATA_FLOW.md](DATA_FLOW.md)。当前部署
版本继续使用 `v3`，不要改为 v4。

## 注意事项

- 实时分类接口在服务器上跑 Chrome（单次约 1-3 分钟），默认最多同时 2 个；超出时
  返回“稍后重试”，可用 `SITES_CLASSIFY_CONCURRENCY` 保守调整。接口拒绝本机、内网、
  保留地址和非 80/443 端口，避免公网页面被用于访问服务器内部服务。
- 当前公网地址仍是 HTTP；管理员口令会明文经过网络。正式长期使用应在域名备案后配置
  HTTPS/Nginx，未启用 HTTPS 前不要在不可信网络中输入管理员口令。
- 不提交任何真实身份信息：平台只观察和分类。
