# 八马茶语 · ChaYu-BAMA

面向飞书 AI 创赛的 Demo 原型：用结构化茶品知识、风味坐标和表达规则，生成面向国内消费者与海外受众的茶文化表达与营销物料数据。

当前主路径：

```text
3 款茶（铁观音 / 大红袍 / 金骏眉）× 图片物料 ×（国内链 + 跨文化链）
```

项目状态、四层架构、数据约定、API 优先级、fallback 规则等设计细节见下「文档」各篇，README 不重复。

## 本地复现

环境要求：`Python 3.11+`

```bash
cd backend
pip install -r requirements.txt
python scripts/seed.py --reset   # 灌表（fresh clone 必跑一次，生成 data/tea.db）
uvicorn app.main:app --reload
```

启动后访问：

```text
http://localhost:8000/docs      # Swagger，可直接调试接口
http://localhost:8000/api/demo-routes
```

运行测试：

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -v
```

## Docker 复现（一体化部署，推荐云服务器用法）

环境要求：Docker Desktop / Docker Engine + Docker Compose。

两个服务：`backend`（FastAPI:8000，构建时自动跑 `seed.py --reset` 灌表）+ `frontend`（nginx:8080，serve `frontend/` 静态 + 反代 `/api` 到 backend）。云服务器只需暴露 8080：浏览器访问 8080 拿前端页面，页面经 `frontend/api.js` 同源调 `/api`，无跨域、无需 CORS。

```bash
docker compose up -d --build        # 构建并拉起 backend + frontend
docker compose logs -f backend     # 看后端日志（含 LLM 启用状态）
docker compose down                 # 停止
```

启动后访问：

```text
http://localhost:8080          # 前端桌面原型 desktop-v2（移动端 mobile-v2，经 api.js 对接后端）
http://localhost:8080/docs      # 后端 Swagger（经 nginx 反代）
http://localhost:8000/docs      # 直连后端（也可，CORS 已放开）
```

密钥：`LLM_API_KEY` / `IMAGE_API_KEY` 等经 `./backend/.env`（gitignored）注入容器，不进镜像。未配置时生成走 seed 兜底、生图走 fallback，不白屏。生图走豆包 Seedream 2K，单图常耗时 >90s，nginx 反代超时已放宽到 310s。

> Windows 上若报 `failed to connect to the docker API ... dockerDesktopLinuxEngine`，先打开 Docker Desktop 等其 Linux Engine 运行完成再执行 compose。

## 部署到云服务器

### 方式一：GitHub Actions 自动部署（推荐）

推 `main` 即自动部署到云服务器 8080，无需登录服务器操作。流水线：`.github/workflows/deploy.yml`，服务器端脚本：`scripts/deploy-remote.sh`（同步 `origin/main` → `docker compose up -d --build`，幂等、不碰 `backend/.env`、不碰其他 compose 项目）。也支持在 GitHub Actions 页面手动 Run workflow。

**一次性准备**（在仓库 Settings → Secrets and variables → Actions 配两个 Secret）：

| Secret | 值 |
|---|---|
| `SSH_HOST` | 服务器 IP |
| `SSH_PRIVATE_KEY` | 部署私钥全文（对应服务器 `~/.ssh/authorized_keys` 里的公钥，`ed25519`） |

服务器侧一次性准备：

```bash
# 1. 服务器装好 docker + compose（首次）
# 2. 放置密钥（gitignored，仅在服务器上手动放一次，CI 不动它）
scp backend/.env.example root@<服务器>:/root/ChaYu-BAMA/backend/.env   # 再填入 LLM_API_KEY / IMAGE_API_KEY 等
# 3. 放行 8080：阿里云安全组入方向加 TCP 8080 / 0.0.0.0/0（OS ufw inactive，安全组是唯一卡点）
```

准备就绪后，`git push origin main` 即触发部署。访问 `http://<服务器IP>:8080`。

> 阿里云 ECS 的安全组在 OS 防火墙之外独立拦截：`ufw inactive`、`iptables ACCEPT`，但安全组未放行 8080 时外网会连接超时（服务器内 `curl localhost:8080` 正常）。80/443 能访问是因为博客部署时已放行。

### 方式二：手动部署

```bash
# 1. 服务器上 clone 仓库
git clone <repo> && cd ChaYu-BAMA
# 2. 放置密钥（不进 Git）
cp backend/.env.example backend/.env   # 填入 LLM_API_KEY / IMAGE_API_KEY 等
# 3. 拉起
docker compose up -d --build
# 4. 放行 8080 端口（安全组 / 防火墙），浏览器访问 http://<服务器IP>:8080
```

> 上线前应收紧 CORS（当前 `allow_origins=["*"]` 为 Demo 联调期放开）与 `/api/health-llm` 调试接口的访问控制。

## CI/CD

GitHub Actions：`.github/workflows/deploy.yml`。推 `main`（或 Actions 页手动触发）→ 在 GitHub runner 上用 `webfactory/ssh-agent` 注入部署密钥 → SSH 登服务器跑 `scripts/deploy-remote.sh`：`git reset --hard origin/main` + `docker compose up -d --build`。并发控制：`concurrency: deploy-server`，新触发排队不中断进行中的部署。

依赖仓库 Secret：`SSH_HOST`、`SSH_PRIVATE_KEY`（部署私钥，公钥在服务器 `authorized_keys`）。`backend/.env` 不进 Git、CI 不动它（仅在服务器上手动放一次）。

## 文档

| 文档 | 职责 |
|---|---|
| [docs/系统架构.md](./docs/系统架构.md) | 赛题理解与设计依据（why） |
| [docs/技术架构.md](./docs/技术架构.md) | 技术架构、数据流、实现原则（how） |
| [docs/接口文档.md](./docs/接口文档.md) | 前后端 API 协作基准（契约） |
| [docs/赛题录屏.txt](./docs/赛题录屏.txt) | 赛题原始素材（参考） |
| [docs/compromises.md](./docs/compromises.md) | 妥协记录（已实现但不启用 / 范围红线相关决策） |
| [docs/接口对接差异分析与方案.md](./docs/接口对接差异分析与方案.md) | 前后端对接差异分析（参考，非契约） |

当前限制：真实视频生成（video-asset 等）走 fallback、生产鉴权与安全配置尚未接入；CORS 为 Demo 联调期放开，上线前需收紧。其余能力边界见接口文档 §8 / §10。

## License

NO LICENSE。除团队内部协作和赛事提交用途外，未经团队明确许可，不默认授权复制、分发、修改或商业使用。
