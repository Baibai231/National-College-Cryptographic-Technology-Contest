# 注册流程测量平台（Web 前端）

展示已测网站的注册流程（程序结果 + 人工复核），支持搜索和实时分类。

## 功能

- **搜索**：按域名/路线关键词搜数据库里的站点
- **详情**：每站展示程序测量（类型/路线/字段/阻断/步骤证据）+ 人工复核对照
- **实时分类**：输入任意网站主页 URL → 复用测量工具现场分类（安全只读）
- **访客安全证据**：实时结果增量展示认证因子、OAuth/OIDC、JWT/JWS和
  WebAuthn请求配置；未观察到不判定为不支持

## 本地运行

```bash
# 1. 构建数据库（final 测量结果 + 人工复核 → SQLite）
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

每轮新测量后：

```bash
.venv/bin/python scripts/build_site_database.py   # 重建数据库
./webapp/run_server.sh 8000                       # 重启生效
```

人工复核结果维护在 `misc/manual_review.json`，重建数据库时自动合并。

## 安全说明

- 实时分类只观察：不填身份信息、不发送验证码、不扫码、不提交注册/创建账号
- WebAuthn观察器不点击Passkey、不主动调用凭据或生命周期API，只脱敏记录页面
  自己发起的调用；challenge相等性只在单页内使用不可导出的随机HMAC标签比较，
  不保存challenge、比较标签、用户/凭据ID或认证器响应
- OIDC/JWKS探针只读取当前页面已暴露身份提供商的标准公开HTTPS元数据；逐跳阻断
  私网目标并限制响应大小，只展示issuer绑定与公钥摘要
- 服务器上实时分类需要 Chrome 环境（与测量工具相同）
