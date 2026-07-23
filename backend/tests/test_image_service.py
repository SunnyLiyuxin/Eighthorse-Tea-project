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
    image_base_url="https://ark.cn-beijing.volces.com/api/v3",
    image_model="doubao-seedream-5-0-pro-260628",
    image_size="2K",
    image_quality="",  # Seedream 无 quality 参数
)
DISABLED_SETTINGS = Settings(image_api_key="", image_base_url="")


def _fake_images_response(url: str = "https://example.com/img.png") -> ImagesResponse:
    """构造一个最小可用的假 ImagesResponse。"""
    return ImagesResponse(
        id="fake",
        created=1710000000,
        model="doubao-seedream-5-0-pro-260628",
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
    assert result["model"] == "doubao-seedream-5-0-pro-260628"
    assert result["size"] == "2K"
    assert result["style"] == image_service.DEFAULT_STYLE, "不传 style 应回显默认 fresh"
    assert result["scene"] == image_service.DEFAULT_SCENE, "不传 scene 应回显默认 closeup"
    assert result["language"] is None, "不传 copy/language 应回显 None（纯画面）"
    # 调用参数含 model/prompt/n/size + extra_body(watermark/stream)；Seedream 无 quality
    sent = calls[0]
    assert sent["model"] == "doubao-seedream-5-0-pro-260628"
    assert sent["n"] == 1
    assert sent["size"] == "2K"
    assert "quality" not in sent, "Seedream 不传 quality"
    assert sent["response_format"] == "url"
    assert sent["extra_body"] == {"watermark": False, "stream": False}
    # prompt 被富化：原"赛珍珠铁观音海报"+ 默认 closeup 镜头片段 + fresh 风格片段 + 画质后缀
    assert "赛珍珠铁观音海报" in sent["prompt"]
    # 商务信号词已清除（实测会把出图拽向商务老气风）
    assert "Professional commercial product photography" not in sent["prompt"]
    assert "elegant composition" not in sent["prompt"]
    # 默认 closeup 镜头片段 + fresh 风格片段 + 画质仍在
    assert "close-up product shot" in sent["prompt"]
    assert "morning daylight" in sent["prompt"]
    assert "photorealistic" in sent["prompt"]
    # 不传 copy → 纯画面出图，prompt 不含图内文字骨架（Seedream 不再禁文字，但也无字可印）
    assert "Chinese text is overlaid" not in sent["prompt"]
    assert "No text, no watermark" not in sent["prompt"], "Seedream 不再含禁文字约束"
    # 写了一条缓存
    assert output_store.count_rows() == 1


def test_generate_image_landscape_scene(monkeypatch):
    """显式传 scene=landscape → 富化含产地广角镜头片段。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/land.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="岩茶海报", scene="landscape")
    assert status == "ok"
    assert result["scene"] == "landscape"
    sent = calls[0]["prompt"]
    # landscape 片段关键词（广角 / 山林 / 上下三分构图）
    assert "wide establishing shot" in sent
    assert "mountain and forest scenery" in sent


def test_generate_image_product_scene(monkeypatch):
    """显式传 scene=product → 富化含商品罐图镜头片段。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/prod.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="金骏眉海报", scene="product")
    assert status == "ok"
    assert result["scene"] == "product"
    sent = calls[0]["prompt"]
    assert "tea canister as the main subject" in sent


def test_generate_image_unknown_scene_falls_back(monkeypatch):
    """未知 scene → 回退默认 closeup，不抛、不白屏。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/sfb.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="海报", scene="nonexistent_scene")
    assert status == "ok"
    assert result["scene"] == image_service.DEFAULT_SCENE
    assert "close-up product shot" in calls[0]["prompt"]


def test_generate_image_business_style(monkeypatch):
    """显式传 style=business → 富化含商务片段，business 信号词进 prompt。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/biz.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="铁观音海报", style="business")
    assert status == "ok"
    assert result["style"] == "business"
    sent = calls[0]["prompt"]
    # business 片段关键词（低光照 / 深色奢华背景）
    assert "low-key studio lighting" in sent
    assert "dark charcoal" in sent
    # 商务美学信号词仍不出现（这些是禁词，business 片段也不含）
    assert "Professional commercial product photography" not in sent
    assert "elegant composition" not in sent


def test_generate_image_unknown_style_falls_back(monkeypatch):
    """未知 style → 回退默认 fresh，不抛、不白屏。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/fb.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="海报", style="nonexistent_style")
    assert status == "ok"
    assert result["style"] == image_service.DEFAULT_STYLE
    assert "morning daylight" in calls[0]["prompt"], "未知 style 应用默认 fresh 片段"


def test_generate_image_guofeng_style(monkeypatch):
    """显式传 style=guofeng → 富化含国风片段，东方美学信号词进 prompt，且不混入 fresh/business 信号。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response("https://example.com/gf.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="铁观音国风海报", style="guofeng")
    assert status == "ok"
    assert result["style"] == "guofeng"
    sent = calls[0]["prompt"]
    # 国风片段关键词（传统东方美学 / 水墨配色 / 宣纸背景）
    assert "classical Chinese aesthetic" in sent
    assert "ink-painting" in sent
    # 不应混入 fresh / business 的信号词（三套风格互斥）
    assert "morning daylight" not in sent
    assert "low-key studio lighting" not in sent
    # 商务美学禁词同样不出现
    assert "Professional commercial product photography" not in sent
    """同 prompt+size、不同 style → 不命中彼此缓存（style 进了哈希键）。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)

    class _FakeImages:
        def generate(self, **kw):
            return _fake_images_response("https://example.com/" + kw["prompt"][:1] + ".png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    image_service.generate_image(prompt="同款茶", style="fresh")
    # 第二次换 business，即使 prompt 相同也不应命中 fresh 的缓存
    r2, s2 = image_service.generate_image(prompt="同款茶", style="business")
    assert s2 == "ok"
    assert r2["style"] == "business", "换 style 必须重新生图（缓存键含 style）"


def test_generate_image_scene_in_cache_key(monkeypatch):
    """同 prompt+size+style、不同 scene → 不命中彼此缓存（scene 进了哈希键）。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)

    class _FakeImages:
        def generate(self, **kw):
            return _fake_images_response("https://example.com/" + kw["prompt"][:1] + ".png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    image_service.generate_image(prompt="同款茶", style="fresh", scene="closeup")
    # 第二次换 landscape，prompt/style 相同也不应命中 closeup 的缓存
    r2, s2 = image_service.generate_image(prompt="同款茶", style="fresh", scene="landscape")
    assert s2 == "ok"
    assert r2["scene"] == "landscape", "换 scene 必须重新生图（缓存键含 scene）"


def test_enrich_prompt_deterministic():
    """富化是纯函数、确定性：同输入两次结果一致；空 prompt 原样返回。"""
    a = image_service._enrich_prompt("茶海报", "fresh", "closeup", None)
    b = image_service._enrich_prompt("茶海报", "fresh", "closeup", None)
    assert a == b, "同 prompt + style + scene 富化结果应一致"
    # 含默认 closeup 镜头 + fresh 风格 + 画质，不含商务信号词，不含禁文字约束
    assert "close-up product shot" in a
    assert "morning daylight" in a
    assert "photorealistic" in a
    assert "No text, no watermark" not in a
    assert "Professional commercial product photography" not in a
    assert "elegant composition" not in a
    # business 风格片段含商务光照信号，但不含已禁的美学词
    biz = image_service._enrich_prompt("茶海报", "business", "closeup", None)
    assert "low-key studio lighting" in biz
    assert "elegant composition" not in biz
    # landscape / product 镜头片段关键词
    assert "wide establishing shot" in image_service._enrich_prompt("茶海报", "fresh", "landscape", None)
    assert "tea canister as the main subject" in image_service._enrich_prompt("茶海报", "fresh", "product", None)
    # guofeng（国风）风格片段：传统东方美学信号，区别于 fresh / business
    gf = image_service._enrich_prompt("茶海报", "guofeng", "closeup", None)
    assert "classical Chinese aesthetic" in gf
    assert "morning daylight" not in gf, "guofeng 不应混入 fresh 的光照信号"
    # 去末尾句号后补后缀，避免双句号
    assert image_service._enrich_prompt("海报。", "fresh", "closeup", None) == image_service._enrich_prompt("海报", "fresh", "closeup", None)
    assert image_service._enrich_prompt("Poster.", "fresh", "closeup", None) == image_service._enrich_prompt("Poster", "fresh", "closeup", None)
    # 空 prompt 原样返回（不拼后缀）
    assert image_service._enrich_prompt("", "fresh", "closeup", None) == ""
    assert image_service._enrich_prompt("   ", "fresh", "closeup", None) == ""


def test_enrich_prompt_with_copy_renders_in_image_text():
    """传 copy → 图内中文文字骨架注入 prompt；headline/subheadline/body 都进 prompt。"""
    copy = {
        "headline": "赛珍珠：先闻三香",
        "subheadline": "炒米香 · 果甜香 · 兰花香",
        "body": "浓香型安溪铁观音，三香层层递进。",
    }
    enriched = image_service._enrich_prompt("赛珍珠海报", "fresh", "closeup", copy)
    # 画面描述仍在
    assert "赛珍珠海报" in enriched
    # 图内文字骨架 + 三个 copy 字段都进 prompt
    assert "Chinese text is overlaid" in enriched
    assert "赛珍珠：先闻三香" in enriched
    assert "炒米香 · 果甜香 · 兰花香" in enriched
    assert "浓香型安溪铁观音，三香层层递进。" in enriched
    # 骨架要求 full-bleed、直接叠在照片上、无白边
    assert "DIRECTLY on the photograph" in enriched


def test_enrich_prompt_copy_all_empty_degrades_to_pure_image():
    """copy 三个字段都空 → 不注入文字骨架（纯画面出图）。"""
    for copy in (None, {}, {"headline": "", "subheadline": "", "body": ""}):
        enriched = image_service._enrich_prompt("海报", "fresh", "closeup", copy)
        assert "Chinese text is overlaid" not in enriched
        assert "海报" in enriched  # 画面描述仍在


def test_generate_image_language_in_cache_key(monkeypatch):
    """同 prompt+size+style+scene、不同 language（带 copy）→ 不命中彼此缓存。

    language 必须进缓存键：同 prompt 不同 language 印不同语言文字，
    不进键会串成错语言图。copy 由 router 取、service 只看 language 入参。
    """
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)

    calls = []

    class _FakeImages:
        def generate(self, **kw):
            calls.append(kw)
            return _fake_images_response(f"https://example.com/{kw['prompt'][:1]}.png")

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())

    copy_zh = {"headline": "中文标题", "subheadline": "中文副标题", "body": "中文正文"}
    copy_en = {"headline": "EN Title", "subheadline": "EN Sub", "body": "EN body"}
    image_service.generate_image(prompt="同款茶", style="fresh", scene="closeup",
                                 copy=copy_zh, language="zh")
    # 第二次换 language=en，prompt/style/scene 相同也不应命中 zh 的缓存
    r2, s2 = image_service.generate_image(prompt="同款茶", style="fresh", scene="closeup",
                                          copy=copy_en, language="en")
    assert s2 == "ok"
    assert r2["language"] == "en", "换 language 必须重新生图（缓存键含 language）"
    # 真触网两次（缓存不串）
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 缓存命中
# ---------------------------------------------------------------------------


def test_generate_image_cache_hit(monkeypatch):
    """已缓存且 ≤29 天 → 命中、不触网、不新增缓存。"""
    _patch_get_settings(monkeypatch, ENABLED_SETTINGS)
    # 先预写一条新鲜的缓存（created_at = now，必在 29 天内）。缓存键含 language 占位。
    now_iso = datetime.now(timezone.utc).isoformat()
    input_hash = output_store.compute_input_hash(
        ImageResult, "海报prompt", "2K", image_service.DEFAULT_STYLE,
        image_service.DEFAULT_SCENE, image_service._NO_COPY_TOKEN,
    )
    output_store.persist(
        output_type="image",
        tea_id=None,
        route_id=None,
        input_hash=input_hash,
        content={
            "url": "https://example.com/cached.png",
            "model": "doubao-seedream-5-0-pro-260628",
            "size": "2K",
            "style": image_service.DEFAULT_STYLE,
            "scene": image_service.DEFAULT_SCENE,
            "language": image_service._NO_COPY_TOKEN,
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
    input_hash = output_store.compute_input_hash(
        ImageResult, "旧海报", "2K", image_service.DEFAULT_STYLE,
        image_service.DEFAULT_SCENE, image_service._NO_COPY_TOKEN,
    )
    output_store.persist(
        output_type="image",
        tea_id=None,
        route_id=None,
        input_hash=input_hash,
        content={
            "url": "https://example.com/stale.png",
            "model": "doubao-seedream-5-0-pro-260628",
            "size": "2K",
            "language": image_service._NO_COPY_TOKEN,
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
            return ImagesResponse(id="x", created=1, model="doubao-seedream-5-0-pro-260628", data=[])

    monkeypatch.setattr(image_service, "_client", lambda: type("C", (), {"images": _FakeImages()})())
    result, status = image_service.generate_image(prompt="x")
    assert result is None
    assert status == reason
    assert output_store.count_rows() == 0, "失败不应写缓存"
