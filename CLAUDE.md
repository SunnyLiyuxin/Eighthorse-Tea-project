# CLAUDE.md

本文件用于 Claude Code 在本仓库中协作开发时快速理解项目目标、工程边界和实现约定。

## 项目状态

本项目处于可运行后端 Demo 阶段，项目名称尚未最终确定。当前目标是围绕主路径完成前后端联调与展示：

```text
1 款茶（铁观音）× 图片物料 ×（国内链 + 跨文化链）两条同构链路
```

两条链路均已在后端以 YAML seed 数据和 mock 输出跑通：国内链面向国内消费者，跨文化链面向欧美精品咖啡爱好者。两条链共享同一款茶的知识与风味坐标，跨文化表达由国内表达按规则横向翻译派生而来。

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

当前实现暂未接入 SQLite，运行时直接从 `backend/data/seeds/*.yaml` 加载到内存 registry。SQLite 数据库是后续运行产物，不作为人工维护的数据源。

后续推荐流程：

```text
backend/data/seeds/*.yaml → backend/scripts/seed.py → backend/data/tea.db
```

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
POST /api/teas/{tea_id}/domestic-expression
POST /api/teas/{tea_id}/cross-cultural-expression
POST /api/teas/{tea_id}/marketing-asset
GET  /api/trace/{output_id}
```

国内链与跨文化链均为主路径，`domestic-expression` 升级为 P0：它是跨文化表达横向翻译的源文，且国内物料同样走到物料层。

P1 建议：

```http
GET  /api/fallback
POST /api/fallback
```

P2 占位：

```http
POST /api/teas/{tea_id}/video-asset
POST /api/translate
POST /api/image/generate
POST /api/audio/generate
GET  /api/markets
GET  /api/audience-references
```

P2 接口可以先注册路由并返回 fallback。

## Fallback 规则

Demo 阶段未开放功能不要返回默认 404 或导致前端白屏。建议对 `/api/*` 未知路由统一返回 fallback JSON：

```json
{
  "success": true,
  "data": {
    "title": "功能暂未开放",
    "message": "该能力已在产品规划中，Demo 阶段暂不提供真实生成结果。",
    "available_route_id": "tieguanyin_western_coffee_poster"
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
data_loader 内存加载
P0 API
P1 fallback
P2 占位 fallback
Dockerfile / docker-compose 后端服务
```

后续优先顺序：

1. 搭建 FastAPI 项目结构。
2. 建 SQLAlchemy models，并让 `seed.py --reset` 从 YAML 生成 SQLite。
3. 将当前内存查询逐步替换为数据库查询。
4. 接入 LLM service、Prompt 模板和输出 JSON 校验。
5. 增加测试覆盖与前端联调。
6. 按部署环境收紧 CORS、文档入口和密钥配置。

不要先接真实生图或视频 API。Demo 阶段 `marketing-asset` 返回海报文案、雷达图数据和 `image_prompt` 即可。

## 协作注意

- 不要引入未确定项目名。
- 不要把代理数据写成八马单品实测数据。
- 不要手动维护 SQLite `.db`。
- 不要把缓存结果提交到 Git。
- 不要把所有规则硬编码进 Python 或一个超长 prompt；规则应结构化存储、按需筛选。
- 不要随意修改 API 字段；如需修改，同步更新 `docs/接口文档.md`。
- 保持实现范围围绕主路径，其他能力用 fallback 预留。
