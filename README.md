# 中国茶 AI 表达 Demo

本项目是一个面向飞书 AI 创赛的 Demo 原型，用结构化茶品知识、风味坐标和表达规则，生成面向国内消费者与海外受众的茶文化表达和营销物料数据。

当前 Demo 聚焦一条可复现主路径：

```text
铁观音 × 图片物料 ×（国内链 + 跨文化链）
```

后端已实现 P0 Demo 接口，当前阶段使用 `backend/data/seeds/*.yaml` 中的静态 seed 数据和 mock 输出，不依赖真实 LLM、生图服务或数据库。后续可以在此基础上接入 SQLite、LLM、前端和云端部署。

## 当前能力

已支持的主要接口：

```http
GET  /api/demo-routes
GET  /api/teas
GET  /api/teas/{tea_id}/knowledge
GET  /api/teas/{tea_id}/flavor-profile
POST /api/teas/{tea_id}/domestic-expression
POST /api/teas/{tea_id}/cross-cultural-expression
POST /api/teas/{tea_id}/marketing-asset
GET  /api/trace/{output_id}
GET  /api/fallback
POST /api/fallback
```

暂未开放的功能会返回统一 fallback JSON，避免前端白屏或默认 404。

## 目录说明

```text
backend/
  app/                 FastAPI 后端代码
  data/seeds/          当前 Demo 的 YAML seed 数据
  scripts/seed.py      后续接入 SQLite 的占位脚本
  requirements.txt     Python 依赖
  Dockerfile           后端容器镜像定义
docker-compose.yml     本地 Docker Compose 配置
docs/
  接口文档.md           前后端接口约定
  技术架构.md           系统设计说明
```

## 本地复现

环境要求：

```text
Python 3.11+
```

安装依赖并启动后端：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

启动后访问：

```text
http://localhost:8000/docs
http://localhost:8000/health
http://localhost:8000/api/demo-routes
```

`/docs` 是 FastAPI 自动生成的 Swagger UI，可直接调试接口。

## Docker 复现

环境要求：

```text
Docker Desktop 或 Docker Engine
Docker Compose
```

在项目根目录运行：

```bash
docker compose up --build backend
```

后台运行：

```bash
docker compose up -d --build backend
```

查看日志：

```bash
docker compose logs -f backend
```

停止服务：

```bash
docker compose down
```

启动后访问：

```text
http://localhost:8000/docs
http://localhost:8000/health
```

如果 Windows 上出现 `failed to connect to the docker API ... dockerDesktopLinuxEngine`，说明 Docker Desktop 的 Linux Engine 尚未启动。先打开 Docker Desktop，等待其运行完成后再执行 compose 命令。

## 当前限制

当前版本用于 Demo 联调，尚未接入：

```text
SQLite / SQLAlchemy 持久化
真实 LLM API
真实图片生成 API
前端服务容器
生产环境鉴权与安全配置
```

## 文档

- [docs/接口文档.md](./docs/接口文档.md)：接口字段和前后端协作基准
- [docs/技术架构.md](./docs/技术架构.md)：系统架构、数据流和后续扩展说明

## License

NO LICENSE

当前仓库未声明开源许可证。除团队内部协作和赛事提交用途外，未经团队明确许可，不默认授权复制、分发、修改或商业使用。
