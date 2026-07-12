"""SQLAlchemy ORM 模型：与 backend/data/seeds/*.yaml 一一对应。

设计约定：
- 嵌套结构（origin/process/story、dimensions 列表、outputs/analogy_rules、
  copy/visual_data）统一用 JSON 列，不为每个嵌套子结构建关系表。
- 主键用 seed 里的可读字符串 id；tea_knowledge / flavor_profiles 没有 id
  字段，按其天然唯一键（tea_id / profile_id）作主键。
- 字段不齐（如 shelf_life_months 仅部分茶有）一律 nullable=True，不在
  schema 层硬约束 —— seed 是事实源，表如实反映。
- expressions / assets 单独建表（非塞进 generated_outputs），字段差异大、
  便于测试断言。generated_outputs 存 LLM 生成结果缓存（output_store 写入）。
- tea_terms 在 seed 里是 dict（tea_id → [term...]），展开成独立表行。
- trace_links 如实反映 seed 的扁平 trace_nodes + parent 结构，不用边表。

灌表逻辑见 scripts/seed.py。
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


class Tea(Base):
    __tablename__ = "teas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    origin: Mapped[str | None] = mapped_column(String)
    brand: Mapped[str | None] = mapped_column(String)
    demo_available: Mapped[bool | None] = mapped_column(Boolean)
    series: Mapped[str | None] = mapped_column(String)
    tea_class: Mapped[str | None] = mapped_column(String)
    product_archetype: Mapped[str | None] = mapped_column(String)
    demo_sku: Mapped[str | None] = mapped_column(String)
    grade: Mapped[str | None] = mapped_column(String)
    shelf_life_months: Mapped[int | None] = mapped_column(Integer)  # 牛一无此字段
    shelf_life: Mapped[str | None] = mapped_column(String)  # 仅牛一有
    standard: Mapped[str | None] = mapped_column(String)
    brand_sensory: Mapped[str | None] = mapped_column(String)
    cultural_core: Mapped[str | None] = mapped_column(String)
    core_process: Mapped[str | None] = mapped_column(String)
    brew_method_id: Mapped[str | None] = mapped_column(String)
    region_note: Mapped[str | None] = mapped_column(String)  # 赛珍珠无此字段


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    claim: Mapped[str | None] = mapped_column(String)
    source_type: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[str | None] = mapped_column(String)
    evidence_level: Mapped[str | None] = mapped_column(String)
    collected_by: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)


class TeaKnowledge(Base):
    """每款茶一条知识卡片，以 tea_id 作主键（天然唯一）。"""

    __tablename__ = "tea_knowledge"

    tea_id: Mapped[str] = mapped_column(
        String, ForeignKey("teas.id"), primary_key=True
    )
    origin: Mapped[dict | None] = mapped_column(JSON)  # region/terroir/source_note
    process: Mapped[dict | None] = mapped_column(JSON)  # name/steps[]/key_technique/brand_claim
    story: Mapped[dict | None] = mapped_column(JSON)  # title/content/cultural_core
    evidence_ids: Mapped[list | None] = mapped_column(JSON)  # list[str]


class FlavorProfile(Base):
    __tablename__ = "flavor_profiles"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    tea_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("teas.id"), index=True
    )
    dimensions: Mapped[list | None] = mapped_column(JSON)  # list[dict]
    component_notes: Mapped[list | None] = mapped_column(JSON)  # list[dict]


class DemoRoute(Base):
    __tablename__ = "demo_routes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tea_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("teas.id"), index=True
    )
    tea_name: Mapped[str | None] = mapped_column(String)
    market: Mapped[str | None] = mapped_column(String)
    target_language: Mapped[str | None] = mapped_column(String)
    audience_reference: Mapped[str | None] = mapped_column(String)
    asset_type: Mapped[str | None] = mapped_column(String)
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(String)


class GenerationRule(Base):
    __tablename__ = "generation_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str | None] = mapped_column(String)
    market: Mapped[str | None] = mapped_column(String)
    audience_reference: Mapped[str | None] = mapped_column(String)
    priority: Mapped[str | None] = mapped_column(String)
    instruction: Mapped[str | None] = mapped_column(String)
    negative_example: Mapped[str | None] = mapped_column(String)
    positive_example: Mapped[str | None] = mapped_column(String)
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    trigger_terms: Mapped[list | None] = mapped_column(JSON)  # list[str]


class CrossCulturalTerm(Base):
    __tablename__ = "cross_cultural_terms"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chinese: Mapped[str | None] = mapped_column(String)
    english: Mapped[str | None] = mapped_column(String)
    explanation: Mapped[str | None] = mapped_column(String)
    analogy_strategy: Mapped[str | None] = mapped_column(String)
    preserve_strategy: Mapped[str | None] = mapped_column(String)
    evidence_ids: Mapped[list | None] = mapped_column(JSON)  # list[str]


class ExpressionStrategy(Base):
    __tablename__ = "expression_strategies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str | None] = mapped_column(String)
    market: Mapped[str | None] = mapped_column(String)
    audience_reference: Mapped[str | None] = mapped_column(String)
    instruction: Mapped[str | None] = mapped_column(String)
    output_slots: Mapped[list | None] = mapped_column(JSON)  # list[str]


class Expression(Base):
    """预置表达（seed mock_outputs.expressions）。"""

    __tablename__ = "expressions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tea_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("teas.id"), index=True
    )
    expression_type: Mapped[str | None] = mapped_column(String)
    strategy_id: Mapped[str | None] = mapped_column(String)
    target_language: Mapped[str | None] = mapped_column(String)  # 国内表达无
    market: Mapped[str | None] = mapped_column(String)  # 国内表达无
    audience_reference: Mapped[str | None] = mapped_column(String)  # 国内表达无
    source_profile_id: Mapped[str | None] = mapped_column(String)
    source_expression_id: Mapped[str | None] = mapped_column(String)  # 国内表达为 null
    trace_id: Mapped[str | None] = mapped_column(String)
    audience: Mapped[dict | None] = mapped_column(JSON)  # age_group/...
    outputs: Mapped[dict | None] = mapped_column(JSON)  # story_style/... 或 literal_explanation/...
    analogy_rules: Mapped[list | None] = mapped_column(JSON)  # 仅跨文化有


class Asset(Base):
    """预置物料（seed mock_outputs.assets）。"""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tea_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("teas.id"), index=True
    )
    asset_type: Mapped[str | None] = mapped_column(String)
    platform: Mapped[str | None] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    image_prompt: Mapped[str | None] = mapped_column(String)
    source_expression_id: Mapped[str | None] = mapped_column(String)  # 国内链
    source_translation_id: Mapped[str | None] = mapped_column(String)  # 跨文化链
    trace_id: Mapped[str | None] = mapped_column(String)
    copy: Mapped[dict | None] = mapped_column(JSON)  # headline/subheadline/body
    visual_data: Mapped[dict | None] = mapped_column(JSON)  # radar list


class TraceLink(Base):
    """扁平 trace_nodes + parent 结构（非边表）。横向翻译关系不在此表。"""

    __tablename__ = "trace_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    node_type: Mapped[str | None] = mapped_column(String)
    level: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(String)
    parent: Mapped[str | None] = mapped_column(String, index=True)  # 根节点为 null


class TeaTerm(Base):
    """tea_terms 展开：seed 里是 dict(tea_id → [term...])，这里每行一条。"""

    __tablename__ = "tea_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tea_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("teas.id"), index=True
    )
    term: Mapped[str | None] = mapped_column(String, index=True)


class GeneratedOutput(Base):
    """LLM 生成结果缓存表（output_store 写入，按 input_hash 去重复用）。"""

    __tablename__ = "generated_outputs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    output_type: Mapped[str | None] = mapped_column(String)
    tea_id: Mapped[str | None] = mapped_column(String)
    route_id: Mapped[str | None] = mapped_column(String)
    input_hash: Mapped[str | None] = mapped_column(String)
    content_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[str | None] = mapped_column(String)  # ISO 时间戳，seed.py 灌时写入
