"""表达生成层（第 3 层）：国内表达 + 跨文化表达，两条同构链路。

国内链与跨文化链地位对等。跨文化表达由国内表达按规则横向翻译派生，
该关系通过 source_expression_id 记录，不进入纵向追溯链。

在规则约束下接入 LLM 做真生成；未启用 / 失败时透明退回 seed 预置表达
（mock_outputs.yaml），不白屏。LLM 只覆盖文本字段，ID / trace / source
字段全留 seed，纵向追溯链不断。LLM 生成结果经 output_store 按 input_hash
缓存进 generated_outputs 表，同输入命中即复用。

seed 存储字段（id / expression_type / strategy_id）为内部字段，
不进接口响应；响应字段名严格对齐 docs/接口文档.md（expression_id / translation_id）。
"""

from app import data_loader
from app.config import get_settings
from app.llm_schemas import CrossCulturalExpressionOutputs, DomesticExpressionOutputs
from app.services import llm_service, output_store, prompts, rules_service

# status：LLM 状态映射到 meta.llm_fallback_reason
_LLM_OK = "ok"


def _resolve_llm(
    *, system_prompt: str, user_prompt: str, output_model: type
) -> tuple[dict | None, str]:
    """统一调用 LLM；未启用 / 失败时返回 (None, fallback_reason)。"""
    return llm_service.generate(
        system_prompt=system_prompt, user_prompt=user_prompt, output_model=output_model,
    )


def get_domestic_expression(
    tea_id: str, audience: dict, style: str | None = None
) -> tuple[dict | None, str, dict]:
    """生成国内中文表达。

    Returns:
        (expression_data, status, llm_meta)。
        status ∈ "ok" / "tea_not_found" / "expression_not_found"。
        llm_meta：{"llm_generated": bool, "llm_fallback_reason": str | None,
                  "used_rule_ids": list[str]}，供路由层并入响应 meta。
    """
    if data_loader.get_tea(tea_id) is None:
        return None, "tea_not_found", _empty_meta()

    record = data_loader.get_expression_by_tea(tea_id, "domestic")
    if record is None:
        return None, "expression_not_found", _empty_meta()

    # 规则筛选：国内链筛选 domestic_expression 规则（select_rules 结果同时注入 prompt）
    # selected 在 LLM 路径下经 render_rules_for_prompt 注入 prompt；并暴露 used_rule_ids
    selected = rules_service.select_rules(
        scope="domestic_expression",
        market="domestic",
        audience_reference="domestic_general",
        tea_id=tea_id,
    )

    outputs = record["outputs"]  # 默认兜底 = seed 文本
    llm_generated = False
    fallback_reason: str | None = None

    if get_settings().llm_enabled:
        tea = data_loader.get_tea(tea_id) or {}
        flavor = data_loader.get_flavor_profile(tea_id) or {}
        knowledge = data_loader.get_knowledge(tea_id) or {}
        system_prompt, user_prompt, _ = prompts.build_domestic_prompt(
            tea_id=tea_id, tea=tea, flavor=flavor, knowledge=knowledge,
            audience=audience or record.get("audience", {}), style=style,
        )
        # 写路径缓存：同输入命中即复用，跳过本次 LLM 调用。
        input_hash = output_store.compute_input_hash(
            DomesticExpressionOutputs, system_prompt, user_prompt
        )
        cached = output_store.get_cached(input_hash)
        if cached is not None:
            outputs = cached
            llm_generated = True
        else:
            llm_out, status = _resolve_llm(
                system_prompt=system_prompt, user_prompt=user_prompt,
                output_model=DomesticExpressionOutputs,
            )
            if status == _LLM_OK and llm_out:
                outputs = llm_out
                llm_generated = True
                output_store.persist(
                    output_type="domestic_expression",
                    tea_id=tea_id, route_id=None,
                    input_hash=input_hash, content=llm_out,
                )
            else:
                fallback_reason = status  # disabled / network_error / timeout / parse_error

    data = {
        "expression_id": record["id"],
        "tea_id": record["tea_id"],
        "audience": audience or record.get("audience", {}),
        "outputs": outputs,
        "source_profile_id": record["source_profile_id"],
        "trace_id": record["trace_id"],
    }
    if style:
        data["style"] = style

    llm_meta = {
        "llm_generated": llm_generated,
        "llm_fallback_reason": fallback_reason,
        "used_rule_ids": [r["id"] for r in selected],
    }
    return data, "ok", llm_meta


def get_cross_cultural_expression(
    tea_id: str,
    target_language: str,
    market: str,
    audience_reference: str,
) -> tuple[dict | None, str, dict]:
    """生成跨文化表达。

    跨文化表达由国内表达横向翻译派生：取国内 seed outputs 作翻译源文，
    连同风味坐标 / 跨文化术语 / 规则注入 LLM 做信达雅转译。
    source_expression_id 仍指向国内 seed 记录（与实际翻译源文一致）。

    Returns:
        (expression_data, status, llm_meta)。
        status ∈ "ok" / "tea_not_found" / "expression_not_found"
        / "language_not_supported" / "market_not_supported"
        / "audience_not_supported"。
    """
    if data_loader.get_tea(tea_id) is None:
        return None, "tea_not_found", _empty_meta()
    if target_language != "en":
        return None, "language_not_supported", _empty_meta()
    if market != "western":
        return None, "market_not_supported", _empty_meta()
    if audience_reference != "specialty_coffee_lovers":
        return None, "audience_not_supported", _empty_meta()

    record = data_loader.get_expression_by_tea(tea_id, "cross_cultural")
    if record is None:
        return None, "expression_not_found", _empty_meta()

    selected = rules_service.select_rules(
        scope="cross_cultural_expression",
        market=market,
        audience_reference=audience_reference,
        tea_id=tea_id,
    )

    outputs = record["outputs"]
    analogy_rules = record.get("analogy_rules", [])
    llm_generated = False
    fallback_reason: str | None = None

    if get_settings().llm_enabled:
        # 翻译源文 = 国内 seed outputs（与 source_expression_id 指向一致）
        domestic_record = data_loader.get_expression_by_tea(tea_id, "domestic")
        if domestic_record is None:
            # 主路径上国内 seed 必然存在；缺失则不调 LLM、退回跨文化 seed 兜底
            fallback_reason = "domestic_source_missing"
        else:
            tea = data_loader.get_tea(tea_id) or {}
            flavor = data_loader.get_flavor_profile(tea_id) or {}
            knowledge = data_loader.get_knowledge(tea_id) or {}
            terms = data_loader.list_cross_cultural_terms()
            system_prompt, user_prompt, _ = prompts.build_cross_cultural_prompt(
                tea_id=tea_id, tea=tea, flavor=flavor, knowledge=knowledge,
                domestic_outputs=domestic_record["outputs"],
                cross_cultural_terms=terms,
                target_language=target_language, market=market,
                audience_reference=audience_reference,
            )
            # 写路径缓存：同输入命中即复用，跳过本次 LLM 调用。
            input_hash = output_store.compute_input_hash(
                CrossCulturalExpressionOutputs, system_prompt, user_prompt
            )
            cached = output_store.get_cached(input_hash)
            if cached is not None:
                outputs = {
                    "literal_explanation": cached["literal_explanation"],
                    "beginner_analogy": cached["beginner_analogy"],
                    "cultural_narrative": cached["cultural_narrative"],
                }
                analogy_rules = cached.get("analogy_rules", [])
                llm_generated = True
            else:
                llm_out, status = _resolve_llm(
                    system_prompt=system_prompt, user_prompt=user_prompt,
                    output_model=CrossCulturalExpressionOutputs,
                )
                if status == _LLM_OK and llm_out:
                    outputs = {
                        "literal_explanation": llm_out["literal_explanation"],
                        "beginner_analogy": llm_out["beginner_analogy"],
                        "cultural_narrative": llm_out["cultural_narrative"],
                    }
                    analogy_rules = llm_out.get("analogy_rules", [])
                    llm_generated = True
                    output_store.persist(
                        output_type="cross_cultural_expression",
                        tea_id=tea_id, route_id=None,
                        input_hash=input_hash, content=llm_out,
                    )
                else:
                    fallback_reason = status

    data = {
        "translation_id": record["id"],
        "tea_id": record["tea_id"],
        "target_language": target_language,
        "market": market,
        "audience_reference": audience_reference,
        "outputs": outputs,
        "analogy_rules": analogy_rules,
        "source_profile_id": record["source_profile_id"],
        "source_expression_id": record.get("source_expression_id"),
        "trace_id": record["trace_id"],
    }

    llm_meta = {
        "llm_generated": llm_generated,
        "llm_fallback_reason": fallback_reason,
        "used_rule_ids": [r["id"] for r in selected],
    }
    return data, "ok", llm_meta


def _empty_meta() -> dict:
    """未命中主路径时（茶品 / 表达不存在、参数不支持）的空 LLM meta。"""
    return {
        "llm_generated": False,
        "llm_fallback_reason": None,
        "used_rule_ids": [],
    }
