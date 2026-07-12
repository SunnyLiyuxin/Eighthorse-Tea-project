"""营销物料接口（层 4）：国内物料 + 跨文化物料。

LLM disabled → copy/image_prompt 走 seed。重点验证：
- 雷达数值来自 seed 事实（visual_data.radar），LLM 不碰
- image_generation_enabled=False（真图仍 P2）
- 国内物料 source_expression_id / 跨文化物料 source_translation_id 纵向指向
"""

from tests.conftest import TEA_ID


def _check_radar(radar):
    assert isinstance(radar, list) and radar
    for r in radar:
        assert "label" in r and "value" in r
        assert isinstance(r["value"], int)  # 事实数据，整数
        assert 0 <= r["value"] <= 10


def test_domestic_asset(client):
    resp = client.post(
        f"/api/teas/{TEA_ID}/marketing-asset",
        json={"language": "zh", "asset_type": "poster"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    d = body["data"]
    assert d["language"] == "zh"
    for k in ("headline", "subheadline", "body"):
        assert isinstance(d["copy"].get(k), str) and d["copy"][k]
    _check_radar(d["visual_data"]["radar"])
    # image_generation_enabled 在 meta 上（responses.success 摊进 meta）
    assert body["meta"]["image_generation_enabled"] is False
    # 国内物料纵向上一级 = 国内表达
    assert d["source_expression_id"] == "expr_cn_szz_tgy_nx"
    assert d.get("source_translation_id") is None
    assert d["trace_id"] == "asset_szz_poster_zh"

    meta = body["meta"]
    assert meta["llm_generated"] is False
    assert "llm_fallback_reason" not in meta


def test_cross_cultural_asset(client):
    resp = client.post(
        f"/api/teas/{TEA_ID}/marketing-asset",
        json={"language": "en", "asset_type": "poster"},
    )
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["language"] == "en"
    for k in ("headline", "subheadline", "body"):
        assert isinstance(d["copy"].get(k), str) and d["copy"][k]
    _check_radar(d["visual_data"]["radar"])
    # 跨文化物料纵向上一级 = 跨文化表达
    assert d["source_translation_id"] == "expr_en_szz_tgy_nx_coffee"
    assert d.get("source_expression_id") is None


def test_asset_unsupported_language_fallback(client):
    resp = client.post(
        f"/api/teas/{TEA_ID}/marketing-asset",
        json={"language": "ja", "asset_type": "poster"},
    )
    body = resp.json()
    assert body["meta"]["fallback"] is True


def test_asset_tea_not_found(client):
    resp = client.post("/api/teas/nonexistent/marketing-asset",
                       json={"language": "zh"})
    assert resp.json()["error"]["code"] == "TEA_NOT_FOUND"
