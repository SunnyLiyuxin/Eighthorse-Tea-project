"""表达生成接口（层 3）：国内表达 + 跨文化表达。

LLM disabled（conftest autouse）→ 走 seed 兜底，llm_generated=false 且
不输出 llm_fallback_reason 键（§1.4 契约）。重点验证：
- seed 字段骨架完整（ID/trace/source）
- 横向翻译关系 source_expression_id 真实指向国内 seed
- 非开放参数组合走 fallback
"""

from tests.conftest import TEA_ID

DOMESTIC_EXPR_ID = "expr_cn_szz_tgy_nx"
CROSS_EXPR_ID = "expr_en_szz_tgy_nx_coffee"


def test_domestic_expression_llm_disabled(client):
    resp = client.post(f"/api/teas/{TEA_ID}/domestic-expression", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    d = body["data"]
    for k in ("expression_id", "tea_id", "outputs", "source_profile_id", "trace_id"):
        assert k in d
    assert d["expression_id"] == DOMESTIC_EXPR_ID
    assert d["source_profile_id"] == "flavor_szz_tgy_nx"
    # 国内表达是翻译源文，无源文
    assert d.get("source_expression_id") is None
    # outputs 三个 slot
    for k in ("story_style", "scientific_style", "emotional_style"):
        assert isinstance(d["outputs"].get(k), str) and d["outputs"][k]

    meta = body["meta"]
    assert meta["llm_generated"] is False
    # §1.4 契约：未启用 LLM 时 llm_generated=false 但不输出 llm_fallback_reason
    assert "llm_fallback_reason" not in meta, "未启用 LLM 不应输出 llm_fallback_reason"
    assert isinstance(meta["used_rule_ids"], list)


def test_domestic_expression_tea_not_found(client):
    resp = client.post("/api/teas/nonexistent/domestic-expression", json={})
    assert resp.json()["error"]["code"] == "TEA_NOT_FOUND"


def test_cross_cultural_expression(client):
    resp = client.post(
        f"/api/teas/{TEA_ID}/cross-cultural-expression",
        json={
            "target_language": "en",
            "market": "western",
            "audience_reference": "specialty_coffee_lovers",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    d = body["data"]
    assert d["translation_id"] == CROSS_EXPR_ID
    # 横向翻译派生：source_expression_id 指向国内 seed（与实际翻译源文一致）
    assert d["source_expression_id"] == DOMESTIC_EXPR_ID
    assert d["source_profile_id"] == "flavor_szz_tgy_nx"
    for k in ("literal_explanation", "beginner_analogy", "cultural_narrative"):
        assert isinstance(d["outputs"].get(k), str) and d["outputs"][k]
    assert isinstance(d.get("analogy_rules"), list)

    meta = body["meta"]
    assert meta["llm_generated"] is False
    assert "llm_fallback_reason" not in meta


def test_cross_cultural_unsupported_params_return_fallback(client):
    """非开放参数组合不报错，走 fallback。"""
    # language
    r = client.post(f"/api/teas/{TEA_ID}/cross-cultural-expression",
                    json={"target_language": "ja", "market": "western",
                          "audience_reference": "specialty_coffee_lovers"})
    assert r.json()["meta"]["fallback"] is True
    # market
    r = client.post(f"/api/teas/{TEA_ID}/cross-cultural-expression",
                    json={"target_language": "en", "market": "europe",
                          "audience_reference": "specialty_coffee_lovers"})
    assert r.json()["meta"]["fallback"] is True
    # audience_reference
    r = client.post(f"/api/teas/{TEA_ID}/cross-cultural-expression",
                    json={"target_language": "en", "market": "western",
                          "audience_reference": "foobar"})
    assert r.json()["meta"]["fallback"] is True
