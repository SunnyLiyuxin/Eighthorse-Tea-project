"""统一响应构造助手。

所有接口（成功 / fallback / 错误）都通过这里的函数返回，保证前端拿到的 JSON
结构一致：`{ success, data, meta }` 或 `{ success, error }`。
"""

from typing import Any


def success(data: Any, *, fallback: bool = False, **extra_meta) -> dict:
    """成功响应。extra_meta 里的键会合并进 meta（如 image_generation_enabled、
    llm_generated、used_rule_ids 等）。

    注意：LLM→seed 降级不应置 fallback=True（那会被归为"功能未开放"，
    误导前端）。降级用 meta.llm_generated=False + llm_fallback_reason 表示，
    仍走本函数且 fallback=False。
    """
    meta: dict[str, Any] = {"demo_mode": True, "fallback": fallback}
    if fallback:
        meta["fallback_reason"] = "feature_not_available"
    meta.update(extra_meta)
    return {"success": True, "data": data, "meta": meta}


def fallback_response(
    *,
    title: str = "功能暂未开放",
    message: str = "该能力已在产品规划中，Demo 阶段暂不提供真实生成结果。",
    available_route_id: str = "tieguanyin_western_coffee_poster",
    suggested_action: str | None = None,
    fallback_reason: str = "feature_not_available",
) -> dict:
    """未开放能力的统一 fallback 响应。"""
    data: dict[str, Any] = {
        "title": title,
        "message": message,
        "available_route_id": available_route_id,
    }
    if suggested_action:
        data["suggested_action"] = suggested_action
    return {
        "success": True,
        "data": data,
        "meta": {
            "demo_mode": True,
            "fallback": True,
            "fallback_reason": fallback_reason,
        },
    }


def error(code: str, message: str) -> dict:
    """错误响应（如 TEA_NOT_FOUND）。"""
    return {"success": False, "error": {"code": code, "message": message}}
