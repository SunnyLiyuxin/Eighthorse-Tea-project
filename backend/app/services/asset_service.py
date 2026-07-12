"""营销物料层（第 4 层）：国内物料 + 跨文化物料，同等重要、相同生成方式。

language=zh → 读取国内表达生成中文物料，source_expression_id 指向国内表达。
language=en → 读取跨文化表达生成英文物料，source_translation_id 指向跨文化表达。
两者均为纵向追溯链上一级；横向翻译关系不在物料层处理。

在规则约束下接入 LLM 生成海报文案 copy + image_prompt；雷达数值
visual_data 是事实数据，始终从 seed 取，LLM 不碰。未启用 / 失败时透明
退回 seed 文案。LLM 生成结果经 output_store 按 input_hash 缓存进
generated_outputs 表。真图 / 真视频仍为 P2 fallback（image_generation_enabled=false）。

seed 存储字段（id / tea_id / asset_type）为内部字段，响应字段名严格对齐
docs/接口文档.md（asset_id）。
"""

from app import data_loader
from app.config import get_settings
from app.llm_schemas import AssetCopy
from app.services import llm_service, output_store, prompts, rules_service

_LLM_OK = "ok"


def get_marketing_asset(
    tea_id: str,
    language: str,
    asset_type: str = "poster",
    platform: str | None = None,
    route_id: str | None = None,
    style: str | None = None,
) -> tuple[dict | None, str, dict]:
    """生成营销物料。

    Returns:
        (asset_data, status, llm_meta)。
        status ∈ "ok" / "tea_not_found" / "language_not_supported"
        / "asset_not_found"。
    """
    if data_loader.get_tea(tea_id) is None:
        return None, "tea_not_found", _empty_meta()
    if language not in ("zh", "en"):
        return None, "language_not_supported", _empty_meta()

    record = data_loader.get_asset_by_language(tea_id, language)
    if record is None:
        return None, "asset_not_found", _empty_meta()

    # 规则筛选：物料层筛选 marketing_asset 规则（如事实边界）
    market = "domestic" if language == "zh" else "western"
    audience_reference = "domestic_general" if language == "zh" else "specialty_coffee_lovers"
    selected = rules_service.select_rules(
        scope="marketing_asset",
        market=market,
        audience_reference=audience_reference,
        tea_id=tea_id,
    )

    copy = record["copy"]
    image_prompt = record["image_prompt"]
    llm_generated = False
    fallback_reason: str | None = None

    if get_settings().llm_enabled:
        # 物料文案依据 = 对应语言的表达 outputs（国内表达 / 跨文化表达）
        expr_type = "domestic" if language == "zh" else "cross_cultural"
        expr_record = data_loader.get_expression_by_tea(tea_id, expr_type)
        if expr_record is None:
            fallback_reason = "expression_source_missing"
        else:
            tea = data_loader.get_tea(tea_id) or {}
            flavor = data_loader.get_flavor_profile(tea_id) or {}
            system_prompt, user_prompt, _ = prompts.build_asset_copy_prompt(
                tea_id=tea_id, tea=tea, flavor=flavor,
                expression_outputs=expr_record["outputs"],
                language=language, market=market,
                audience_reference=audience_reference, platform=platform, style=style,
            )
            # 写路径缓存：同输入命中即复用，跳过本次 LLM 调用。
            input_hash = output_store.compute_input_hash(
                AssetCopy, system_prompt, user_prompt
            )
            cached = output_store.get_cached(input_hash)
            if cached is not None:
                copy = {
                    "headline": cached["headline"],
                    "subheadline": cached["subheadline"],
                    "body": cached["body"],
                }
                image_prompt = cached["image_prompt"]
                llm_generated = True
            else:
                llm_out, status = llm_service.generate(
                    system_prompt=system_prompt, user_prompt=user_prompt,
                    output_model=AssetCopy,
                )
                if status == _LLM_OK and llm_out:
                    copy = {
                        "headline": llm_out["headline"],
                        "subheadline": llm_out["subheadline"],
                        "body": llm_out["body"],
                    }
                    image_prompt = llm_out["image_prompt"]
                    llm_generated = True
                    output_store.persist(
                        output_type="marketing_asset",
                        tea_id=tea_id, route_id=route_id,
                        input_hash=input_hash, content=llm_out,
                    )
                else:
                    fallback_reason = status

    data = {
        "asset_id": record["id"],
        "tea_id": record["tea_id"],
        "asset_type": record["asset_type"],
        "platform": platform or record.get("platform", ""),
        "language": language,
        "copy": copy,
        "visual_data": record["visual_data"],  # 雷达数值由 seed 事实提供，LLM 不碰
        "image_prompt": image_prompt,
        # 国内物料纵向上一级 = 国内表达；跨文化物料纵向上一级 = 跨文化表达
        "source_expression_id": record.get("source_expression_id"),
        "source_translation_id": record.get("source_translation_id"),
        "trace_id": record["trace_id"],
    }
    if route_id:
        data["route_id"] = route_id
    if style:
        data["style"] = style

    llm_meta = {
        "llm_generated": llm_generated,
        "llm_fallback_reason": fallback_reason,
        "used_rule_ids": [r["id"] for r in selected],
    }
    return data, "ok", llm_meta


def _empty_meta() -> dict:
    return {
        "llm_generated": False,
        "llm_fallback_reason": None,
        "used_rule_ids": [],
    }
