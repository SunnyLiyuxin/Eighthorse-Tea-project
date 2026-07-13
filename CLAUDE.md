# CLAUDE.md

本文件用于 Claude Code 在本仓库中协作开发时快速理解项目目标、工程边界和实现约定。

## 项目状态

本项目处于可运行后端 Demo 阶段，项目名称尚未最终确定。当前目标是围绕主路径完成前后端联调与展示：

```text
1 款茶（铁观音）× 图片物料 ×（国内链 + 跨文化链）两条同构链路
```

两条链路均已在后端以 YAML seed 数据跑通：国内链面向国内消费者，跨文化链面向欧美精品咖啡爱好者。两条链共享同一款茶的知识与风味坐标，跨文化表达由国内表达按规则横向翻译派生而来。

三个生成接口（国内表达 / 跨文化表达 / 营销物料）已接入 LLM（OpenAI 兼容 SDK，默认指向 GLM，经 `backend/.env` 配置）。LLM 负责文本字段生成，ID / trace / source / 雷达数值仍由 seed 提供；未配置 key 或调用失败时透明退回 seed 预置表达（mock 兜底），不白屏。

真实生图已接入：`POST /api/image/generate` 调智谱 CogView-4（`quality=hd` + 关闭水印），返回临时图片 URL（30 天有效，同 prompt+size 按 input_hash 缓存 29 天）。与 `marketing-asset` 两步联调——物料层只产 `image_prompt`，生图拆为独立接口（解耦耗时）。生图时后端给精短 prompt 套确定性质量后缀（专业商品摄影 / 光照 / 构图 / 负面词），不调 LLM、零幻觉、确定性；`marketing-asset.image_prompt` 字段仍保持精短。生图凭证独立走 `IMAGE_*`（`backend/.env`），与 `LLM_*` 相互独立、不回退——当前 `LLM_*` 多半指向 DeepSeek，不覆盖智谱 `/images/generations`，故生图必须独立配 `IMAGE_*` 指向智谱。未配置 / 失败走 fallback（生图无 seed 兜底）。视频生成仍为 P2 占位。

不要默认扩展到多茶品、其他市场、其他受众参照系或真实视频生成。未开放能力应返回 fallback。

## 必读文档

开发前先阅读：

```text
README.md
docs/技术架构.md
docs/接口文档.md
```

参考资料：

```text
docs/系统架构.pdf
docs/赛题录屏.txt
```

`docs/接口文档.md` 是前后端 API 协作基准。接口字段变更必须同步更新该文档。

## 核心设计

系统采用四层架构：

```text
第 1 层：知识 / 证据层   （成分：茶品事实、工艺、成分、文化）
第 2 层：风味结构化层     （感知：成分 → 风味坐标）
第 3 层：表达生成层       （具象化：感知 → 可理解话术）
第 4 层：营销物料层       （多模态物料：表达 → 海报 / 雷达 / image_prompt）
```

四层在第 3、4 层各自分出国内、跨文化两条同构链路，共享第 1、2 层茶品事实。跨文化表达由国内表达按规则横向翻译派生而来——这是同层横向派生，不是纵向追溯链的一层。

每层都应能独立输出结果，并尽量能追溯到上一层依据。国内链与跨文化链各自纵向追溯，结构对称、各四层；翻译关系通过 `source_expression_id` 字段另行记录，不进入纵向追溯链。

核心原则：

```text
结构化知识库约束事实
结构化规则库约束判断
风味坐标承接感知
工作流负责任务拆解
LLM 负责在规则约束下表达转译
物料层负责传播展示
纵向追溯链证明每个输出有事实依据
翻译与类比为同层横向派生，不进纵向链
fallback 保证未开放功能也能稳定交互
```

## 技术栈约定

后端：

```text
FastAPI
SQLite
SQLAlchemy
Pydantic
YAML / JSON seed 文件
内存缓存
LLM API 可选
```

前端由前端组负责。后端只需保证接口稳定、JSON 字段清晰、Swagger 可调试、fallback 不白屏。

## 数据约定

运行时读路径已切库：`data_loader` 的 getter 查 `backend/data/tea.db`（由 `seed.py --reset` 从 `backend/data/seeds/*.yaml` 灌表）；写路径经 `output_store` 查/写 `generated_outputs` 表（LLM 输出缓存）。YAML 仍是数据源头，改了重跑 `seed.py --reset` 即生效。`all_seeds()` 仅 `seed.py` 灌表时用，运行时不再走内存 registry。

数据流：

```text
backend/data/seeds/*.yaml → backend/scripts/seed.py --reset → backend/data/tea.db（读真源 + LLM 输出缓存）
```

fresh clone 后须先跑 `python scripts/seed.py --reset` 灌表，否则启动会打印警告、读路径返回空/404。未灌表不 crash、不自动灌（显式匹配 runbook）。

`.db` 文件应被 gitignore。

每条关键数据统一字段：

```yaml
id:
type:
claim:
content:
source_type:
source:
confidence:
notes:
```

`source_type` 推荐取值：

```text
public_standard
paper
official_website
ecommerce
interview
social_media
team_assumption
industry_article
```

`confidence` 取值：

```text
high
medium
low
```

Agent 可以辅助收集和格式化科学信息，但来源和可信度由团队人工确认。业务信息以人类调研为主，Agent 只辅助整理。

规则同样是数据，不要硬编码成一个长 prompt。规则应放在 seed 文件中并导入 SQLite，例如：

```text
backend/data/seeds/generation_rules.yaml
```

运行时根据任务、市场、受众和茶品术语筛选相关规则，再注入 LLM prompt。

推荐规则字段：

```yaml
id:
scope:
market:
audience_reference:
trigger_terms:
priority:
instruction:
negative_example:
positive_example:
enabled:
```

## API 优先级

P0 已实现：

```http
GET  /api/demo-routes
GET  /api/teas
GET  /api/teas/{tea_id}/knowledge
GET  /api/teas/{tea_id}/flavor-profile
GET  /api/teas/{tea_id}/component-flavor
POST /api/teas/{tea_id}/domestic-expression
POST /api/teas/{tea_id}/cross-cultural-expression
POST /api/teas/{tea_id}/marketing-asset
POST /api/image/generate
GET  /api/trace/{output_id}
```

国内链与跨文化链均为主路径，`domestic-expression` 升级为 P0：它是跨文化表达横向翻译的源文，且国内物料同样走到物料层。`POST /api/image/generate` 升级为 P0：真实生图（CogView-4）已接入，与 `marketing-asset` 两步联调。

P1 建议：

```http
GET  /api/fallback
POST /api/fallback
```

P2 占位：

```http
POST /api/teas/{tea_id}/video-asset
POST /api/translate
POST /api/audio/generate
GET  /api/markets
GET  /api/audience-references
```

P2 接口可以先注册路由并返回 fallback。其中 `GET /api/markets` 与 `GET /api/audience-references` 已升级为真实枚举列表（从 `demo_routes` 派生），其余仍为占位 fallback。`POST /api/image/generate` 已升级为真实生图（见上），从 P2 移出。

## Fallback 规则

Demo 阶段未开放功能不要返回默认 404 或导致前端白屏。建议对 `/api/*` 未知路由统一返回 fallback JSON：

```json
{
  "success": true,
  "data": {
    "title": "功能暂未开放",
    "message": "该能力已在产品规划中，Demo 阶段暂不提供真实生成结果。",
    "available_route_id": "szz_western_coffee_poster"
  },
  "meta": {
    "demo_mode": true,
    "fallback": true,
    "fallback_reason": "feature_not_available"
  }
}
```

## 实现建议

当前后端已完成：

```text
FastAPI 路由
YAML seed 数据
data_loader 读路径切库（getter 查 SQLite，best-effort 降级不白屏）
SQLAlchemy models（13 表）
seed.py --reset（从 YAML 灌表，行数校验）
output_store（generated_outputs 表作 LLM 输出缓存，写路径接库）
P0 API（含真实生图 POST /api/image/generate，CogView-4）
P1 fallback
P2 占位 fallback（markets / audience-references 已升级为真实列表；image/generate 已升级为真实生图）
LLM service、Prompt 模板、输出 JSON 校验（LLM-primary + seed-fallback）
image_service（CogView-4 生图 + output_store 缓存，未启用/失败走 fallback）
pytest 测试覆盖（P0 / 生成 / 追溯 / LLM 降级 / 生图 / fallback / 读路径 shape 对齐）
Dockerfile / docker-compose 后端服务
```

后续优先顺序：

1. ~~搭建 FastAPI 项目结构。~~ ✅
2. ~~建 SQLAlchemy models，并让 `seed.py --reset` 从 YAML 生成 SQLite。~~ ✅
3. ~~将当前内存查询逐步替换为数据库查询。~~ ✅（读路径已切库）
4. ~~接入 LLM service、Prompt 模板和输出 JSON 校验。~~ ✅
5. ~~接入真实生图（CogView-4，POST /api/image/generate）。~~ ✅
6. 增加测试覆盖与前端联调。（测试覆盖已完成，前端联调待办）
7. 按部署环境收紧 CORS、文档入口和密钥配置。

不要接真实视频 API；真实生图已接入 CogView-4（智谱，经 `IMAGE_*` 配置，与 `LLM_*` 相互独立），经 `POST /api/image/generate` 暴露。`marketing-asset` 仍返 `image_prompt` 作为生图输入（两步联调）。

## 协作注意

- 不要引入未确定项目名。
- 不要把代理数据写成八马单品实测数据。
- 不要手动维护 SQLite `.db`。
- 不要把缓存结果提交到 Git。
- 不要把所有规则硬编码进 Python 或一个超长 prompt；规则应结构化存储、按需筛选。
- 不要随意修改 API 字段；如需修改，同步更新 `docs/接口文档.md`。
- 保持实现范围围绕主路径，其他能力用 fallback 预留。
