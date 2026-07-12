"""LLM 降级契约测试（核心，防昨天那种契约漂移）。

覆盖 §1.4 全部语义：
- llm_enabled=True 但 LLM 调用失败 → llm_generated=false、llm_fallback_reason=具体原因、
  仍 success=true 且 fallback=false（降级不误置 fallback）
- llm_enabled=False → llm_generated=false 且不输出 llm_fallback_reason 键
- domestic_source_missing / expression_source_missing（调 LLM 前源文缺失）

用 monkeypatch 替换 llm_service.generate 或 data_loader 取源文函数，不真调 LLM。
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.services import llm_service
from tests.conftest import _SETTINGS_MODULES, _patch_get_settings, TEA_ID

ENABLED_SETTINGS = Settings(
    llm_api_key="fake-key-for-testing",
    llm_base_url="https://fake.example.com",
    llm_model="fake-model",
    llm_supports_json_mode=True,
)
DISABLED_SETTINGS = Settings(llm_api_key="", llm_base_url="")


@pytest.fixture(autouse=True)
def _enable_llm(monkeypatch, client: TestClient):
    """覆盖 conftest 的 disabled 默认：本文件让 llm_enabled=True。

    conftest 的 llm_disabled（autouse）先 setup 设 disabled；本 fixture 后 setup，
    覆盖成 enabled —— fixture 后注册者胜。teardown 时 conftest 已清，不污染其他文件。
    """
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    yield


# ---------------------------------------------------------------------------
# (1) LLM 启用但调用失败 → 降级契约
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,reason", [
    ("parse_error", "parse_error"),
    ("timeout", "timeout"),
    ("network_error", "network_error"),
    ("gateway_error", "gateway_error"),
])
def test_domestic_expression_llm_failure_degrades(status, reason, client, monkeypatch):
    """LLM 失败 → 退回 seed，meta 标降级原因，但响应仍是 success / 非 fallback。"""
    monkeypatch.setattr(llm_service, "generate", lambda **kw: (None, status))
    resp = client.post(f"/api/teas/{TEA_ID}/domestic-expression", json={})
    body = resp.json()
    assert body["success"] is True, "降级仍是成功响应"
    assert body["meta"]["fallback"] is False, "降级不得置 fallback=true"
    assert body["meta"]["llm_generated"] is False
    assert body["meta"]["llm_fallback_reason"] == reason
    assert body["data"]["outputs"]["story_style"]  # 退回的 seed 文本仍在
    assert isinstance(body["meta"]["used_rule_ids"], list)


def test_cross_cultural_llm_failure_degrades(client, monkeypatch):
    monkeypatch.setattr(llm_service, "generate", lambda **kw: (None, "gateway_error"))
    resp = client.post(
        f"/api/teas/{TEA_ID}/cross-cultural-expression",
        json={"target_language": "en", "market": "western",
              "audience_reference": "specialty_coffee_lovers"},
    )
    body = resp.json()
    assert body["meta"]["llm_generated"] is False
    assert body["meta"]["llm_fallback_reason"] == "gateway_error"
    assert body["meta"]["fallback"] is False
    # source_expression_id 仍指向国内 seed（降级不改追溯诚实）
    assert body["data"]["source_expression_id"] == "expr_cn_szz_tgy_nx"


def test_asset_llm_failure_keeps_radar_from_seed(client, monkeypatch):
    """LLM 失败 → 文案退 seed，雷达数值始终来自 seed（LLM 从不碰雷达）。"""
    monkeypatch.setattr(llm_service, "generate", lambda **kw: (None, "parse_error"))
    resp = client.post(
        f"/api/teas/{TEA_ID}/marketing-asset",
        json={"language": "en", "asset_type": "poster"},
    )
    body = resp.json()
    assert body["meta"]["llm_generated"] is False
    assert body["meta"]["llm_fallback_reason"] == "parse_error"
    radar = body["data"]["visual_data"]["radar"]
    assert isinstance(radar, list) and radar
    assert all(isinstance(r["value"], int) for r in radar)


# ---------------------------------------------------------------------------
# (2) 调 LLM 前源文缺失 → domestic_source_missing / expression_source_missing
# ---------------------------------------------------------------------------


def test_cross_cultural_domestic_source_missing(client, monkeypatch):
    """跨文化链取国内表达作翻译源文，国内 seed 缺失 → domestic_source_missing。"""
    from app import data_loader

    real_cc = data_loader.get_expression_by_tea(TEA_ID, "cross_cultural")

    def fake_get(tea_id, expr_type):
        return None if expr_type == "domestic" else real_cc

    monkeypatch.setattr(data_loader, "get_expression_by_tea", fake_get)
    resp = client.post(
        f"/api/teas/{TEA_ID}/cross-cultural-expression",
        json={"target_language": "en", "market": "western",
              "audience_reference": "specialty_coffee_lovers"},
    )
    body = resp.json()
    assert body["meta"]["llm_generated"] is False
    assert body["meta"]["llm_fallback_reason"] == "domestic_source_missing"
    assert body["meta"]["fallback"] is False


def test_asset_expression_source_missing(client, monkeypatch):
    """物料层取对应语言表达作文案依据，该表达 seed 缺失 → expression_source_missing。"""
    from app import data_loader
    monkeypatch.setattr(data_loader, "get_expression_by_tea", lambda *a, **kw: None)
    resp = client.post(
        f"/api/teas/{TEA_ID}/marketing-asset",
        json={"language": "en", "asset_type": "poster"},
    )
    body = resp.json()
    assert body["meta"]["llm_generated"] is False
    assert body["meta"]["llm_fallback_reason"] == "expression_source_missing"


# ---------------------------------------------------------------------------
# (3) LLM 未启用 → 不输出 llm_fallback_reason 键
# ---------------------------------------------------------------------------


def test_llm_disabled_no_fallback_reason_key(client, monkeypatch):
    """llm_enabled=False 时 llm_generated=false 但 meta 不含 llm_fallback_reason。"""
    _patch_get_settings(monkeypatch, DISABLED_SETTINGS)
    # generate 不应被调用；若被调，抛错让测试失败
    monkeypatch.setattr(
        llm_service, "generate",
        lambda **kw: (_ for _ in ()).throw(AssertionError("llm_enabled=False 时不应调 LLM")),
    )
    body = client.post(f"/api/teas/{TEA_ID}/domestic-expression", json={}).json()
    assert body["meta"]["llm_generated"] is False
    assert "llm_fallback_reason" not in body["meta"]
