"""数据访问层：从 SQLite 查询 seed 数据（读路径已切库）。

getter 查 backend/data/tea.db（由 seed.py --reset 从 data/seeds/*.yaml 灌表）；
generated_outputs 表作 LLM 输出缓存由 output_store 读写，与读路径独立。
all_seeds()/_load() 仅保留给 seed.py 灌表时读 YAML 用，运行时 getter 不走内存。

getter 签名与返回 shape 与内存版逐字段对齐（ORM 顶层字段 + JSON 列原样），
所以 router / service / 测试无感。seed.py 仍用 all_seeds()/_load() 读 YAML 灌库。

读 engine 模块级懒构造（镜像 output_store 模式）：默认指向 data/tea.db；
测试用 set_read_db_path 重定向到临时库，reset_read_engine 恢复。best-effort：
查询异常记日志返回 None/[]，不让 DB 故障把读请求打成 500（由上层响应暴露缺失）。
"""

from functools import lru_cache
from pathlib import Path

import logging

import yaml
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.database import DB_PATH, make_engine, make_session
from app.models import (
    Asset,
    CrossCulturalTerm,
    DemoRoute,
    EvidenceSource,
    Expression,
    FlavorProfile,
    GenerationRule,
    Tea,
    TeaKnowledge,
    TeaTerm,
    TraceLink,
)

logger = logging.getLogger("app.data_loader")

# backend/app/data_loader.py → backend/data/seeds
SEEDS_DIR = Path(__file__).resolve().parent.parent / "data" / "seeds"


def _load(name: str) -> dict:
    """读取单个 seed 文件为 dict（仅 seed.py 灌表时用）。"""
    path = SEEDS_DIR / f"{name}.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=None)
def all_seeds() -> dict:
    """一次性加载全部 seed 为 registry。

    仅 seed.py 灌表时调用（读 YAML 是 seed.py 的职责）。运行时 getter 已改查 DB，
    不再走本函数。保留是为了 seed.py 不重复实现 YAML 读取逻辑。
    """
    return {
        "teas": _load("teas").get("teas", []),
        "evidence_sources": _load("evidence").get("evidence_sources", []),
        "tea_knowledge": _load("knowledge").get("tea_knowledge", []),
        "flavor_profiles": _load("flavor_profiles").get("flavor_profiles", []),
        "demo_routes": _load("demo_routes").get("demo_routes", []),
        "rules": _load("generation_rules").get("rules", []),
        "cross_cultural_terms": _load("cross_cultural_terms").get("cross_cultural_terms", []),
        "expression_strategies": _load("expression_strategies").get("expression_strategies", []),
        "expressions": _load("mock_outputs").get("expressions", []),
        "assets": _load("mock_outputs").get("assets", []),
        "trace_nodes": _load("trace_links").get("trace_nodes", []),
        "tea_terms": _load("trace_links").get("tea_terms", {}),
    }


# ---------------------------------------------------------------------------
# 读 engine（懒构造 + 测试可重定向）
# ---------------------------------------------------------------------------

_read_engine: Engine | None = None
_read_db_path: Path | None = None  # 非 None 表示已显式重定向（测试用）


def _current_read_engine() -> Engine:
    """懒构造读 engine。首次查询时建，指向 data/tea.db 或测试重定向路径。

    不在此建表：seed.py --reset 负责 create_all + 灌数据。读路径只查不建。
    """
    global _read_engine
    if _read_engine is None:
        path = _read_db_path or DB_PATH
        _read_engine = make_engine(path)
    return _read_engine


def set_read_db_path(db_path: Path) -> None:
    """测试用：把读 engine 重定向到指定库（隔离真实 backend/data/tea.db）。"""
    global _read_engine, _read_db_path
    if _read_engine is not None:
        _read_engine.dispose()
    _read_db_path = db_path
    _read_engine = make_engine(db_path)


def reset_read_engine() -> None:
    """测试 teardown：dispose 读 engine 并清空重定向，恢复默认。"""
    global _read_engine, _read_db_path
    if _read_engine is not None:
        _read_engine.dispose()
    _read_engine = None
    _read_db_path = None


def _row_to_dict(obj) -> dict | None:
    """把 ORM 行序列化成 dict（取已声明列名 → 值，JSON 列已是 dict/list）。"""
    if obj is None:
        return None
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _safe_query(default):
    """装饰器：查询异常（表缺失/锁/磁盘）降级为默认值，不让 DB 故障打成 500。

    未灌表时（OperationalError: no such table）返回空 list / None，由上层响应
    自然暴露（list 空、单条 None→TEA_NOT_FOUND 等），符合"未灌表不白屏"原则。
    """

    def deco(fn):
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (OperationalError, SQLAlchemyError) as e:
                logger.warning("data_loader 查询失败，降级为 %r：%s", default, e)
                return default

        return wrapper

    return deco


# 优先级排序权重：规则筛选后按 high > medium > low 排序
PRIORITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------------------
# 查询函数（services 用）—— 体内存扫描已换 ORM select 查询
# ---------------------------------------------------------------------------


@_safe_query(default=[])
def list_teas() -> list[dict]:
    with make_session(_current_read_engine()) as s:
        rows = s.execute(select(Tea)).scalars().all()
    return [_row_to_dict(r) for r in rows]


@_safe_query(default=None)
def get_tea(tea_id: str) -> dict | None:
    with make_session(_current_read_engine()) as s:
        row = s.execute(select(Tea).where(Tea.id == tea_id)).scalar_one_or_none()
    return _row_to_dict(row)


@_safe_query(default=[])
def list_demo_routes() -> list[dict]:
    with make_session(_current_read_engine()) as s:
        rows = s.execute(select(DemoRoute)).scalars().all()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 市场 / 受众参照系枚举（从 demo_routes 派生 + 双语 label）
# ---------------------------------------------------------------------------

# label 是 Demo 阶段的展示名映射，标 TODO：真市场 catalog 落地后迁入 seed。
_MARKET_LABELS: dict[str, dict[str, str]] = {
    "domestic": {"label_zh": "国内", "label_en": "Domestic"},
    "western": {"label_zh": "欧美", "label_en": "Western"},
}
_AUDIENCE_LABELS: dict[str, dict[str, str]] = {
    "domestic_general": {
        "label_zh": "国内大众消费者",
        "label_en": "Domestic general consumers",
    },
    "specialty_coffee_lovers": {
        "label_zh": "欧美精品咖啡爱好者",
        "label_en": "Western specialty coffee lovers",
    },
}


def list_markets() -> list[dict]:
    """从 demo_routes 派生去重后的市场列表，附双语展示名。"""
    seen: dict[str, None] = {}
    for r in list_demo_routes():
        m = r.get("market")
        if m and m not in seen:
            seen[m] = None
    return [
        {"id": m, **_MARKET_LABELS.get(m, {"label_zh": m, "label_en": m})}
        for m in seen
    ]


def list_audience_references() -> list[dict]:
    """从 demo_routes 派生去重后的受众参照系列表，附双语展示名。"""
    seen: dict[str, None] = {}
    for r in list_demo_routes():
        a = r.get("audience_reference")
        if a and a not in seen:
            seen[a] = None
    return [
        {"id": a, **_AUDIENCE_LABELS.get(a, {"label_zh": a, "label_en": a})}
        for a in seen
    ]


@_safe_query(default=None)
def get_knowledge(tea_id: str) -> dict | None:
    with make_session(_current_read_engine()) as s:
        row = s.execute(
            select(TeaKnowledge).where(TeaKnowledge.tea_id == tea_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        knowledge = _row_to_dict(row)
        tea = get_tea(tea_id) or {}
        evidence_ids = knowledge.get("evidence_ids") or []
        evidence_map: dict[str, dict] = {}
        if evidence_ids:
            ev_rows = s.execute(
                select(EvidenceSource).where(EvidenceSource.id.in_(evidence_ids))
            ).scalars().all()
            evidence_map = {e.id: _row_to_dict(e) for e in ev_rows}
    return _build_knowledge_card(tea_id, knowledge, tea, evidence_map)


def _build_knowledge_card(
    tea_id: str, knowledge: dict, tea: dict, evidence_map: dict[str, dict]
) -> dict:
    """组装知识卡片：tea 基础信息 + 产地 + 工艺 + 故事 + 证据明细。

    与内存版逐字段对齐：evidence 每条有 id/source_type/title/source/confidence/note。
    title 取 evidence 的 source 字段（与内存版一致）。
    """
    evidence = [
        {
            "id": eid,
            "source_type": evidence_map[eid]["source_type"],
            "title": evidence_map[eid]["source"],
            "source": evidence_map[eid]["source"],
            "confidence": evidence_map[eid]["confidence"],
            "note": evidence_map[eid].get("notes", ""),
        }
        for eid in (knowledge.get("evidence_ids") or [])
        if eid in evidence_map
    ]
    return {
        "tea": {
            "id": tea.get("id", tea_id),
            "name": tea.get("name", ""),
            "category": tea.get("category", ""),
            "origin": tea.get("origin", ""),
            "brand": tea.get("brand", ""),
        },
        "origin": knowledge.get("origin", {}),
        "process": knowledge.get("process", {}),
        "story": knowledge.get("story", {}),
        "evidence": evidence,
    }


@_safe_query(default=None)
def get_flavor_profile(tea_id: str) -> dict | None:
    with make_session(_current_read_engine()) as s:
        row = s.execute(
            select(FlavorProfile).where(FlavorProfile.tea_id == tea_id)
        ).scalar_one_or_none()
    # 丢弃 profile_id（内部存储字段），与内存版返回 shape 对齐（仅 dimensions + component_notes）
    if row is None:
        return None
    d = _row_to_dict(row)
    return {"dimensions": d.get("dimensions"), "component_notes": d.get("component_notes")}


@_safe_query(default=None)
def get_expression(expression_id: str) -> dict | None:
    with make_session(_current_read_engine()) as s:
        row = s.execute(
            select(Expression).where(Expression.id == expression_id)
        ).scalar_one_or_none()
    return _row_to_dict(row)


@_safe_query(default=None)
def get_expression_by_tea(tea_id: str, expression_type: str) -> dict | None:
    """按茶品 + 类型（domestic / cross_cultural）取预置表达。"""
    with make_session(_current_read_engine()) as s:
        row = s.execute(
            select(Expression).where(
                Expression.tea_id == tea_id,
                Expression.expression_type == expression_type,
            )
        ).scalar_one_or_none()
    return _row_to_dict(row)


@_safe_query(default=None)
def get_asset_by_language(tea_id: str, language: str) -> dict | None:
    """按茶品 + 语言取预置物料（zh→国内物料，en→跨文化物料）。"""
    with make_session(_current_read_engine()) as s:
        row = s.execute(
            select(Asset).where(
                Asset.tea_id == tea_id,
                Asset.language == language,
            )
        ).scalar_one_or_none()
    return _row_to_dict(row)


@_safe_query(default=None)
def get_asset(asset_id: str) -> dict | None:
    with make_session(_current_read_engine()) as s:
        row = s.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
    return _row_to_dict(row)


@_safe_query(default=None)
def get_trace_node(output_id: str) -> dict | None:
    """取追溯节点：返回 id/node_type/level/name/summary/parent（与内存版 shape 对齐）。"""
    with make_session(_current_read_engine()) as s:
        row = s.execute(
            select(TraceLink).where(TraceLink.id == output_id)
        ).scalar_one_or_none()
    if row is None:
        return None
    d = _row_to_dict(row)
    # ORM 列名是 node_type，内存版 seed key 也是 node_type；补 id 字段（内存版直接带 id）
    return {
        "id": d["id"],
        "node_type": d.get("node_type"),
        "level": d.get("level"),
        "name": d.get("name"),
        "summary": d.get("summary"),
        "parent": d.get("parent"),
    }


@_safe_query(default=[])
def get_tea_terms(tea_id: str) -> list[str]:
    with make_session(_current_read_engine()) as s:
        rows = s.execute(
            select(TeaTerm.term).where(TeaTerm.tea_id == tea_id)
        ).all()
    return [r[0] for r in rows if r[0] is not None]


@_safe_query(default=[])
def all_rules() -> list[dict]:
    with make_session(_current_read_engine()) as s:
        rows = s.execute(select(GenerationRule)).scalars().all()
    return [_row_to_dict(r) for r in rows]


@_safe_query(default=[])
def list_cross_cultural_terms() -> list[dict]:
    """全部跨文化术语（供跨文化表达 prompt 注入）。"""
    with make_session(_current_read_engine()) as s:
        rows = s.execute(select(CrossCulturalTerm)).scalars().all()
    return [_row_to_dict(r) for r in rows]
