# CLAUDE.md

本文件用于 Claude Code 在本仓库中协作开发时快速理解**工程边界与协作约束**。
项目设计、数据约定、API 契约、fallback 规则等细节不在本文件重复——读对应权威文档。

## 必读文档（按需阅读，各司其职）

| 文档 | 职责 | 何时读 |
|---|---|---|
| [README.md](./README.md) | 项目入口、本地复现、Docker 部署、文档索引 | 新进仓库 |
| [docs/系统架构.md](./docs/系统架构.md) | 赛题理解、设计依据（why） | 需理解设计动机时 |
| [docs/技术架构.md](./docs/技术架构.md) | 四层架构、数据流、技术栈、数据策略、追溯机制（how） | 改后端结构/数据/规则前 |
| [docs/接口文档.md](./docs/接口文档.md) | API 契约、字段定义、P0/P1/P2、fallback 接口、前端枚举映射 | 改任何 API / 联调前 |
| [docs/compromises.md](./docs/compromises.md) | 妥协记录（已实现但不启用 / 范围红线相关决策） | 恢复搁置能力 / 复审范围时 |

指针速查（详见对应文档）：
- 四层架构 / 总体设计 → `docs/技术架构.md §2 / §3`
- 技术栈 → `§4`；数据策略（seed / SQLite / 证据字段 / 规则数据）→ `§6`
- LLM 调用边界与降级 → `§9`；fallback 设计 → `§10`；API 分层 → `§11`；可追溯机制 → `§12`
- API 字段 / 请求响应 / 优先级 / fallback 接口 → `docs/接口文档.md`（§5 表达含 hint 映射、§6.2 生图、§7 追溯、§8 fallback、§10 优先级）
- 前端中文枚举 → 后端内部值映射 → `backend/app/enum_map.py`（映射表单一真源）
- 前端 v2 对接层 → `frontend/api.js`（`BAMA_API` 封装所有后端调用，茶名须用后端全名对齐 `/api/teas`；BASE 自适应同源、`meta.fallback` 统一拦截）
- Docker 一体化部署 → `docker-compose.yml` + `deploy/nginx.conf`（backend:8000 + frontend nginx:8080 反代，index 已切 `desktop-v2.html`）
- CI/CD → `.github/workflows/deploy.yml` + `scripts/deploy-remote.sh`（推 main 即 SSH 部署到云服务器 8080；密钥经仓库 Secret `SSH_HOST` / `SSH_PRIVATE_KEY` 注入）
- 赛题理解 / 风味轮研究 / 跨文化类比依据 → `docs/系统架构.md`

**接口字段变更必须同步更新 `docs/接口文档.md`，枚举变更同步 `backend/app/enum_map.py`。**

## 项目状态

可运行一体化 Demo（后端 FastAPI + 前端 v2 纯后端对接版 + Docker 部署），项目名已确定：中文「八马茶语」/ 英文「ChaYu-BAMA」。主路径与当前进度见 README「文档」与下「实现进度」；四层架构、数据流、生图、降级、fallback 等设计细节见技术架构 / 接口文档，本文件不重复。未开放能力返回 fallback；不默认扩展到其他市场 / 其他受众 / 真实视频。

## 协作约束（代码不可推断的红线，必守）

- **项目名已确定，勿改写或引入别称**：中文「八马茶语」、英文「ChaYu-BAMA」（大小写即此形式，勿写成 Chayu / ChaYu-Bama / 八马茶语BAMA 等）。旧称「中国茶 AI 表达 Demo」「Eighthorse-Tea（codename）」勿再用作项目名。
- **不要把代理数据写成八马单品实测数据。**（成分代理数据须标注为"公开文献代理数据"，见技术架构 §3.1 / §14.1）
- **不要手动维护 SQLite `.db`。**（`data/tea.db` 由 `seed.py --reset` 从 YAML 灌表，被 gitignore）
- **不要把缓存结果提交到 Git。**（`.db` / 生图 URL 缓存均不入库）
- **不要把所有规则硬编码进 Python 或超长 prompt。**（规则结构化存 `backend/data/seeds/generation_rules.yaml`，按任务/市场/受众/术语筛选后注入，见技术架构 §6.4）
- **不要随意修改 API 字段。**（改了须同步 `docs/接口文档.md`）
- **不要接真实视频 API。**（`video-asset` 等保持 P2 fallback）
- 保持实现范围围绕主路径，其他能力用 fallback 预留。
- **开题报告是「方案陈述」而非「实现契约」，且本地私有不入库。**（`docs/开题报告/` 已 gitignore，勿 add；报告用工程概念表述、不贴代码符号——变量名 / 字段名 / 路由路径归代码与接口文档，报告里只用「追溯标识 / 可复现灌表脚本 / schema-gated 约束解码」等概念化措辞；改报告时不动编号、不增标题、仅就地改写；README / CLAUDE 文档索引不指向它，避免断链。）

## 密钥约定

- LLM / API key 只在 `backend/.env`（gitignored），**绝不**进被跟踪文件或 Docker 镜像。
- `backend/.env` 原则上不得由助手读取。
- `health-llm` 调试接口不输出明文 key，`base_url` 仅回显 scheme + host。
- 生图凭证独立走 `IMAGE_*`（指向火山方舟 Ark），与 `LLM_*` 相互独立、不回退——ARK key 需在控制台开通模型并关闭"安全体验模式"推理限额，否则 429。

## 实现进度

已完成：FastAPI 路由 / SQLAlchemy models（16 表）/ `seed.py --reset` / 读路径切库 / LLM service + Prompt + JSON 校验 / 真实生图（豆包 Seedream）/ output_store 缓存 / pytest 覆盖（164 passed）/ 前后端枚举映射（`app/enum_map.py`：platform/style/tone/length/content_theme/task_type/flavor_reference）/ 前端 v2 纯后端对接版（`frontend/desktop-v2.html` + `mobile-v2.html` + `api.js`，已取代 v1 mock 原型）/ Docker 一体化部署（`docker-compose.yml` backend + frontend nginx 网关，已构建验证全链路）/ GitHub Actions 自动部署（`.github/workflows/deploy.yml` + `scripts/deploy-remote.sh`，推 main 即部署到云服务器 8080，密钥经仓库 Secret 注入）/ 前端 favicon + `apple-touch-icon`（复用 `frontend/bama-logo.png`，两 HTML `<head>` 引用）。

后续优先顺序：

1. ~~搭建 FastAPI 项目结构。~~ ✅
2. ~~建 SQLAlchemy models，`seed.py --reset` 从 YAML 生成 SQLite。~~ ✅
3. ~~内存查询替换为数据库查询。~~ ✅（读路径已切库）
4. ~~接入 LLM service、Prompt 模板和输出 JSON 校验。~~ ✅
5. ~~接入真实生图。~~ ✅（图源后已切豆包 Seedream 并修复出图质量，见下第 6、7 项）
6. ~~修生图出图质量——清商务信号词 + style 风格维度 + scene 镜头维度，seed 退化为纯画面物体。~~ ✅
7. ~~图源切豆包 Seedream + 图内渲染中文知识文字。~~ ✅（详见接口文档 §6.2）
8. ~~前端枚举映射 + Docker 一体化部署。~~ ✅（enum_map 统一前端中文枚举→后端英文内部值；nginx 反代 `/api`，前端同源调无跨域）
9. ~~增加测试覆盖与前端联调。~~ ✅（测试 164 passed；前端 v2 已切纯后端对接 `api.js`，茶名对齐后端全名、枚举经 `enum_map` 映射；`api.js` BASE 自适应同源、`meta.fallback` 统一拦截已修，见 commit ca07362；对话框用户友好性三处修复——生成中即时 typing 指示器 + 分阶段文案、物料文案换行保留、fallback/错误视觉区分，见 commit 2a7f84c）
10. ~~按部署环境收紧 CORS、文档入口和密钥配置。~~ ✅（CORS 已收紧：`config.py` 增 `cors_allowed_origins`（env `CORS_ALLOWED_ORIGINS`，逗号分隔）+ `cors_origins()`；`main.py` 中间件由 `allow_origins=["*"]` 改为读 `cors_origins()`（默认空=同源 only）。Docker 部署下前端与 `/api` 经 nginx 同 origin，浏览器不发 `Origin` 头，不需要放行跨域——空即最严。`allow_credentials=false`、`allow_methods=GET,POST,OPTIONS`、`allow_headers=Content-Type`。`.env.example` 末尾加 `CORS_ALLOWED_ORIGINS=` 占位 + 说明。文档同步：接口文档 §1.5、README 两处、CLAUDE.md 此处。）
11. ~~GitHub Actions 自动部署到云服务器（8080）。~~ ✅（`.github/workflows/deploy.yml` + `scripts/deploy-remote.sh`；密钥经仓库 Secret 注入）

> fresh clone 后须先跑 `python scripts/seed.py --reset` 灌表，否则启动打印警告、读路径返回空 / 404。未灌表不 crash、不自动灌。（Docker 方式构建时镜像内自动跑 `seed.py --reset`，无需手动灌表。）
