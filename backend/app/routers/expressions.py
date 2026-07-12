"""表达生成路由（第 3 层）：国内表达 + 跨文化表达。"""

from fastapi import APIRouter

from app import responses
from app.schemas import CrossCulturalExpressionRequest, DomesticExpressionRequest
from app.services import expression_service

router = APIRouter(prefix="/api", tags=["expressions"])


@router.post("/teas/{tea_id}/domestic-expression")
def create_domestic_expression(tea_id: str, body: DomesticExpressionRequest):
    """生成国内中文表达。

    国内表达是跨文化表达横向翻译的源文，属 Demo 主路径，必须预置。
    启用 LLM 时由规则约束生成；未启用 / 失败时退回 seed 预置表达。
    """
    expr, status, llm_meta = expression_service.get_domestic_expression(
        tea_id=tea_id,
        audience=body.audience.model_dump(exclude_none=True),
        style=body.style,
    )
    if status == "tea_not_found":
        return responses.error("TEA_NOT_FOUND", "未找到对应茶品")
    if status == "expression_not_found":
        return responses.fallback_response(
            message="该茶品国内表达 Demo 阶段尚未预置。",
        )

    return responses.success(expr, **_llm_meta_kwargs(llm_meta))


@router.post("/teas/{tea_id}/cross-cultural-expression")
def create_cross_cultural_expression(tea_id: str, body: CrossCulturalExpressionRequest):
    """生成跨文化表达（由国内表达横向翻译派生，关系记于 source_expression_id）。"""
    expr, status, llm_meta = expression_service.get_cross_cultural_expression(
        tea_id=tea_id,
        target_language=body.target_language,
        market=body.market,
        audience_reference=body.audience_reference,
    )

    if status == "tea_not_found":
        return responses.error("TEA_NOT_FOUND", "未找到对应茶品")
    if status in (
        "language_not_supported",
        "market_not_supported",
        "audience_not_supported",
    ):
        # 非开放参数组合 → fallback，不报错
        return responses.fallback_response(
            message="当前目标语言 / 市场 / 受众参照系 Demo 阶段暂未开放。",
            suggested_action="Demo 主路径：铁观音 × 英语 × 欧美市场 × 精品咖啡爱好者。",
        )
    if status == "expression_not_found":
        return responses.fallback_response(
            message="该茶品跨文化表达 Demo 阶段尚未预置。",
        )

    return responses.success(expr, **_llm_meta_kwargs(llm_meta))


def _llm_meta_kwargs(llm_meta: dict) -> dict:
    """把 service 返回的 LLM meta 摊成 responses.success 的 extra_meta。

    llm_fallback_reason 仅在非 None（即走了 LLM 但降级）时输出；完全没启用时为 None，
    保持与旧响应一致（不增字段，避免前端困惑）。used_rule_ids 始终输出。
    """
    kwargs: dict = {
        "llm_generated": llm_meta["llm_generated"],
        "used_rule_ids": llm_meta["used_rule_ids"],
    }
    if llm_meta.get("llm_fallback_reason") is not None:
        kwargs["llm_fallback_reason"] = llm_meta["llm_fallback_reason"]
    return kwargs
