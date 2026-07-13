"""image_service 生图服务契约测试（直调 service，monkeypatch 网络层）。

覆盖：
- 未启用 → (None, "disabled")
- 成功 → ({"url","model","size"}, "ok") + 写一条缓存
- 缓存命中（≤29 天）→ 不触网、不新增缓存
- 缓存过期（>29 天）→ 触网重生
- 各类失败（timeout/network/gateway/parse）→ (None, status)

用 monkeypatch 替换 OpenAI.images.generate 返假 ImagesResponse，不真调智谱。
"""

import httpx
import pytest
from datetime import datetime, timedelta, timezone
from openai import APIConnectionError, APIStatusError, APITimeoutError
from openai.types.images_response import ImagesResponse

from app.config import Settings
from app.llm_schemas import ImageResult
from app.services import image_service, output_store
from tests.conftest import _patch_get_settings

ENABLED_SETTINGS = Settings(
    image_api_key="fake-image-key",
    image_base_url="https://open.bigmodel.cn/api/paas/v4",
    image_model="cogview-4",
    image_size="1024x1024",
)
DISABLED_SETTINGS = Settings(image_api_key="", image_base_url="")


def _fake_images_response(url: str = "https://example.com/img.png") -> ImagesResponse:
    """构造一个最小可用的假 ImagesResponse。"""
    return ImagesResponse(
        id="fake",
        created=1710000000,
        model="cogview-4",
        data=[{"url": url}],
    )


# ---------------------------------------------------------------------------
# 未启用
# ---------------------------------------------------------------------------


def test_generate_image_disabled(monkeypatch):
    _patch_get_settings(monkeypatch, DISABLED_SETTINGS)
    # 若被触网就抛错
    monkeypatch.setattr(
        image_service, "_client",
        lambda: (_ for _ in ()).throw(AssertionError("未启用不应触网")),
    )
    result, status = image_service.generate_image(prompt="test")
    assert result is None
    assert status == "disabled"


# ---------------------------------------------------------------------------
# 成功
# ---------------------------------------------------------------------------


def test_generate_image_success(monkeypatch):
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/ok.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())

    result, status = image_service.generate_image(prompt="赛珍珠铁观音海报")
    assert status == "ok"
    assert result is not None
    assert result["url"] == "https://example.com/ok.png"
    assert result["model"] == "cogview-4"
    assert result["size"] == "1024x1024"
    # 调用参数含 model/prompt/n/size/quality + extra_body(watermark)
    sent = calls[0]
    assert sent["model"] == "cogview-4"
    assert sent["n"] == 1
    assert sent["quality"] == "hd"
    assert sent["extra_body"] == {"watermark_enabled": False}
    # prompt 被富化：原"赛珍珠铁观音海报"+质量后缀，必须含 "professional"
    assert "赛珍珠铁观音海报" in sent["prompt"]
    assert "Professional commercial product photography" in sent["prompt"]
    assert "No text, no watermark" in sent["prompt"]
    # 写了一条缓存
    assert output_store.count_rows() == 1


def test_enrich_prompt_deterministic():
    """富化是纯函数、确定性：同输入两次结果一致；空 prompt 原样返回。"""
    a = image_service._enrich_prompt("茶海报")
    b = image_service._enrich_prompt("茶海报")
    assert a == b, "同 prompt 富化结果应一致"
    # 含质量后缀关键词
    assert "Professional commercial product photography" in a
    assert "No text, no watermark" in a
    # 去末尾句号后补后缀，避免双句号
    assert image_service._enrich_prompt("海报。") == image_service._enrich_prompt("海报")
    assert image_service._enrich_prompt("Poster.") == image_service._enrich_prompt("Poster")
    # 空 prompt 原样返回（不拼后缀）
    assert image_service._enrich_prompt("") == ""
    assert image_service._enrich_prompt("   ") == ""


# ---------------------------------------------------------------------------
# 缓存命中
# ---------------------------------------------------------------------------


def test_generate_image_cache_hit(monkeypatch):
    """已缓存且 ≤29 天 → 命中、不触网、不新增缓存。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    # 先预写一条新鲜的缓存（created_at = now，必在 29 天内）
    now_iso = datetime.now(timezone.utc).isoformat()
    input_hash = output_store.compute_input_hash(ImageResult, "海报prompt", "1024x1024")
    output_store.persist(
        output_type="image",
        tea_id=None,
        route_id=None,
        input_hash=input_hash,
        content={
            "url": "https://example.com/cached.png",
            "model": "cogview-4",
            "size": "1024x1024",
            "created_at": now_iso,  # 刚写，新鲜
        },
    )
    assert output_store.count_rows() == 1

    # 若被触网就抛错
    monkeypatch.setattr(
        image_service, "_client",
        lambda: (_ for _ in ()).throw(AssertionError("应命中缓存不触网")),
    )
    result, status = image_service.generate_image(prompt="海报prompt")
    assert status == "ok"
    assert result["url"] == "https://example.com/cached.png"
    assert output_store.count_rows() == 1, "命中缓存不应新增行"


def test_generate_image_cache_expired(monkeypatch):
    """缓存 >29 天 → 判 miss → 触网重生、覆盖。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    # 预写一条 40 天前的缓存（已过期）
    expired_iso = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    input_hash = output_store.compute_input_hash(ImageResult, "旧海报", "1024x1024")
    output_store.persist(
        output_type="image",
        tea_id=None,
        route_id=None,
        input_hash=input_hash,
        content={
            "url": "https://example.com/stale.png",
            "model": "cogview-4",
            "size": "1024x1024",
            "created_at": expired_iso,  # 40 天前
        },
    )

    class _FakeImages:
        def generate(self, **kw):
            return _fake_images_response("https://example.com/fresh.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="旧海报")
    assert status == "ok"
    assert result["url"] == "https://example.com/fresh.png", "过期缓存应被新生图覆盖"


# ---------------------------------------------------------------------------
# 各类失败
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["timeout", "network_error", "gateway_error", "parse_error"])
def test_generate_image_failure(monkeypatch, reason):
    """各类失败 → (None, status)，且不写缓存。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)

    class _FakeImages:
        def generate(self, **kw):
            if reason == "timeout":
                raise APITimeoutError("timeout")
            if reason == "network_error":
                raise APIConnectionError(request=None)
            if reason == "gateway_error":
                resp = httpx.Response(
                    status_code=429,
                    request=httpx.Request("POST", "https://x.com"),
                    text='{"error":"x"}',
                )
                raise APIStatusError(message="429", response=resp, body=None)
            # parse_error: data 为空
            return ImagesResponse(id="x", created=1, model="cogview-4", data=[])

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="x")
    assert result is None
    assert status == reason
    assert output_store.count_rows() == 0, "失败不应写缓存"
