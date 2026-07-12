"""生成结果缓存与持久化（generated_outputs 表的读写）。

写路径接库：LLM 启用时，三个生成接口在调 LLM 前先按 input_hash 查缓存，
命中即复用、跳过本次 LLM 调用；LLM 成功后把结果写回，供后续同输入命中。

设计原则（DB 是 best-effort 加速器，不是硬依赖）：
- 任何 DB 异常（表不存在 / 磁盘满 / 文件锁 / 写冲突）都吞掉降级：
  get_cached → None，persist → 静默跳过。绝不让缓存故障把请求打成 500 或阻断
  LLM 调用 —— 缓存挂了，最坏就是每次都调 LLM，与未接缓存时行为一致。
- 缓存键 = sha256(output_model 类名 + system_prompt + user_prompt)。
  类名隔离不同 schema（国内 / 跨文化 / 物料哈希永不撞）；prompt 已含 tea_id /
  audience / style / market / 规则版本等全部决定输出的输入，输入一变哈希即变。
- 仅 LLM 启用且即将调用 LLM 时才查缓存；LLM 未启用 / 调用失败 / 源文缺失都不碰库。
- 运行时 engine 懒构造、只建 generated_outputs 一张表（不依赖 seed.py 是否跑过，
  也不建其他表 —— 读路径由 data_loader 查 tea.db 的 seed 表，与此独立）。
- 缓存对前端透明：cache hit 仍返回 LLM 生成内容（llm_generated=true），
  不新增响应字段，不改 §1.4 契约。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.database import Base, DB_PATH, make_engine, make_session
from app.models import GeneratedOutput

logger = logging.getLogger("app.output_store")

# 模块级懒 engine。None 表示尚未构造；首次 get_cached / persist 时才建。
# 测试用 set_test_db_path 重定向到临时库，teardown 用 reset_engine 恢复。
_engine: Engine | None = None
_db_path: Path | None = None  # 非 None 表示已显式重定向（测试用）


def _current_engine() -> Engine:
    """懒构造 engine；首次用时建 generated_outputs 表（create_all 幂等）。

    测试可通过 set_test_db_path 重定向到临时库；否则用真实 backend/data/tea.db。
    """
    global _engine
    if _engine is None:
        path = _db_path or DB_PATH
        _engine = make_engine(path)
        try:
            # 只建 generated_outputs 一张表：读路径不查库，无需其他表存在。
            Base.metadata.create_all(_engine, tables=[GeneratedOutput.__table__])
        except Exception as e:
            # 建表失败也不致命：后续读写各自 try/except 兜住，缓存整体不可用而已。
            logger.warning("output_store 建表失败，缓存将不可用：%s", e)
    return _engine


def set_test_db_path(db_path: Path) -> None:
    """测试用：把 engine 重定向到临时库，隔离真实 backend/data/tea.db。"""
    global _engine, _db_path
    if _engine is not None:
        _engine.dispose()
    _db_path = db_path
    _engine = make_engine(db_path)
    try:
        Base.metadata.create_all(_engine, tables=[GeneratedOutput.__table__])
    except Exception as e:
        logger.warning("output_store 测试库建表失败：%s", e)


def reset_engine() -> None:
    """测试 teardown：dispose engine 并清空重定向，恢复默认（下次懒构造回真实库）。"""
    global _engine, _db_path
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _db_path = None


def compute_input_hash(
    output_model: type, system_prompt: str, user_prompt: str
) -> str:
    """缓存键：sha256(模型类名 + system + user)。

    用 \\x00 分隔防前后拼接歧义。模型类名隔离不同 schema，保证三种生成接口
    的哈希空间互不相交。
    """
    h = hashlib.sha256()
    h.update(output_model.__name__.encode("utf-8"))
    h.update(b"\x00")
    h.update((system_prompt or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((user_prompt or "").encode("utf-8"))
    return h.hexdigest()


def get_cached(input_hash: str) -> dict | None:
    """按 input_hash 查缓存命中行；未命中 / 出错 → None。"""
    try:
        engine = _current_engine()
        with make_session(engine) as s:
            row = s.execute(
                select(GeneratedOutput.content_json).where(
                    GeneratedOutput.input_hash == input_hash
                )
            ).first()
        return dict(row[0]) if row and row[0] else None
    except Exception as e:
        logger.warning("output_store 读缓存失败，跳过缓存：%s", e)
        return None


def persist(
    *,
    output_type: str,
    tea_id: str | None,
    route_id: str | None,
    input_hash: str,
    content: dict,
) -> None:
    """把一次成功的 LLM 输出写回 generated_outputs。失败静默跳过。

    id 取 output_type + 哈希前 12 位，确定且可复现：同输入重复 persist 命中同 PK，
    触发 IntegrityError 被兜住（首写即生效，重复写无副作用）。
    """
    try:
        engine = _current_engine()
        obj = GeneratedOutput(
            id=f"{output_type}_{input_hash[:12]}",
            output_type=output_type,
            tea_id=tea_id,
            route_id=route_id,
            input_hash=input_hash,
            content_json=content,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with make_session(engine) as s:
            s.add(obj)
            s.commit()
    except Exception as e:
        logger.warning("output_store 写缓存失败，跳过：%s", e)


def count_rows() -> int:
    """诊断用：返回 generated_outputs 当前行数（测试断言缓存是否写入）。

    出错返回 -1（不抛），保持 best-effort 语义。
    """
    try:
        engine = _current_engine()
        with make_session(engine) as s:
            return len(s.execute(select(GeneratedOutput)).all())
    except Exception as e:
        logger.warning("output_store 计数失败：%s", e)
        return -1
