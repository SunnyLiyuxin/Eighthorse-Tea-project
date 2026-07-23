"""生图服务：调豆包 Seedream 文生图（火山方舟 Ark）。

设计要点（镜像 llm_service.generate）：
- 基于 openai SDK（OpenAI 兼容），Ark 端点 {base_url}/images/generations。
  凭证走 IMAGE_*（ARK API Key + Ark base_url）——与 LLM_* 相互独立、不回退
  （当前 LLM_* 多半指向 DeepSeek，不覆盖 Ark 生图端点）。
- 同步调用，与现有同步 service 风格一致（FastAPI 把同步 handler 丢线程池跑）。
- 失败永不抛：未启用 / 网络 / 超时 / 解析失败统一返回降级状态，由路由层走 fallback。
  生图无 seed 兜底（没有预置图），与文本三接口"退回 seed"不同。

图源选择：CogView-4 中文文字渲染能力不稳，而海报初衷是把"知识点 + 产品文案"
直接印在图上，纯无字照片偏题。豆包 Seedream（doubao-seedream-5-0-pro-260628）
图内中文渲染准确，response_format="url" 直接返临时 URL（与 CogView 同构，
无需改 b64 落盘架构），故切图源为 Seedream。

prompt 富化（图内渲染文字）：marketing-asset.image_prompt 只写画面物体 + 产地，
本服务在发图前组装成 full-bleed 海报 prompt——画面 + 镜头（scene）+ 风格（style）
+ 图内中文知识文字（copy）+ 画质后缀。copy 由 router 按 tea_id + language 从
seed asset 表取（headline/subheadline/body），service 不直接查 DB（保持解耦、
便于测试）。无 copy 时退化纯画面出图（图里没字）。
零 LLM 调用、零幻觉、确定性——marketing-asset 契约的 image_prompt 字段仍保持精短，
富化只在生图内部发生，对前端透明。

watermark=false 经 extra_body 透传去水印（Ark 扩展参数，SDK 不暴露）；
Seedream 无 quality 参数（CogView 的 quality="hd" 已废弃）。

返回 (result | None, status)：
  status ∈ "ok" / "disabled" / "network_error" / "timeout"
         / "parse_error" / "gateway_error"
  result = {"url": str, "model": str, "size": str, "style": str, "scene": str, "language": str | None}

缓存（镜像 intent_service）：按 prompt + size + style + scene + language 算
input_hash，命中且 created_at ≤29 天即复用、跳过 Seedream 调用；否则调
Seedream、成功后写回。缓存命中仍标 success（对前端透明）。style / scene /
language 必须计入键——切换会命中旧缓存即缓存投毒（language 尤其关键：同
prompt 不同 language 印不同语言文字，不进键会串成错语言图）。
"""

import logging
from datetime import datetime, timedelta, timezone

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

from app.config import get_settings
from app.llm_schemas import ImageResult
from app.services import output_store

logger = logging.getLogger("app.image")

# 生图缓存有效期：Ark 图片临时链接 30 天，留 1 天裕量提前判 miss 重生。
# 注意：Seedream pro 2K 出图偏慢（首图常 >90s），image_timeout 默认 300s
# （超时也计费，故给足而非早掐）；缓存命中时跳过调用，同输入二次请求很快。
_CACHE_TTL = timedelta(days=29)

# status 取值（与 llm_service 对齐，便于路由层统一处理）
FALLBACK_DISABLED = "disabled"
FALLBACK_NETWORK = "network_error"
FALLBACK_TIMEOUT = "timeout"
FALLBACK_PARSE = "parse_error"
FALLBACK_GATEWAY = "gateway_error"

# 确定性片段 + 风格/镜头：富化 Seedream 出图，组装成 full-bleed 图内渲染文字的海报。
# 不依赖 LLM、零幻觉、确定性。watermark 走请求体 extra_body；Seedream 无 quality。
#
# 四层职责切分（避免光照/构图在 seed 与片段里打架）：
#   - seed / LLM image_prompt：画面物体 + 产地线索（茶具/茶汤/道具），
#     不写镜头、光照、色调、氛围（交由 scene/style 注入，否则切换失效），
#     不写"no generated text"——Seedream 就是要在图里渲染中文知识文字
#   - copy：图内中文文字（headline/subheadline/body），由 router 取 seed asset 注入
#   - _SCENE_FRAGMENTS[scene]：镜头与构图（特写/产地广角/商品图）
#   - _STYLE_FRAGMENTS[style]：光照 + 色调 + 氛围 + 背景（风格化轴）
#   - _QUALITY_SUFFIX：画质词（不含"no text"——Seedream 要生成文字）
# P1 已证明：prompt 残留 "Professional commercial product photography / elegant
# composition" 这类企业画册美学词会把出图拽向商务老气风。故默认走 fresh
# 清新风，business 风格片段才显式给商务信号（要商务时调用方显式传 style=business）。
#
# scene 维度（P3）：解决"要素同质化"——默认 closeup 总是一杯茶+花+茶叶，
# 加 scene=landscape 画产地广角山林、scene=product 画商品罐图。
# scene 与 style 正交，组合数 = scene × style，缓存键含两者 + language 防投毒。

DEFAULT_STYLE = "fresh"
DEFAULT_SCENE = "closeup"
DEFAULT_LANGUAGE: str | None = None  # 不取 copy、纯画面出图
# copy=None 时缓存键 language 段的占位，避免与有 copy 的请求串成错语言图。
_NO_COPY_TOKEN = "_no_copy"

# 镜头片段：只写镜头、构图，不写光照/色调/氛围（避免与 style 打架），
# 也不写画质（留给 _QUALITY_SUFFIX）。每个片段是一段英文短语，不含句末标点。
# closeup：主体中下部特写，茶具茶汤为主——当前默认、最安全。
# landscape：产地广角，人物/茶具在画面下部、上方山林背景，文字安全区更大。
# product：商品罐图主体居中，茶具道具陪衬，适合电商/品牌展示。
# 三者统一竖版 9:16 移动海报构图；文字如何叠在图上由 copy 段 + full-bleed 措辞负责。
_SCENE_FRAGMENTS: dict[str, str] = {
    "closeup": (
        "vertical 9:16 mobile poster composition, close-up product shot, "
        "main subject centered in the lower-middle frame"
    ),
    "landscape": (
        "vertical 9:16 mobile poster composition, wide establishing shot of the "
        "tea's origin landscape, small tea ware and hands in the lower third, "
        "expansive mountain and forest scenery filling the upper two-thirds"
    ),
    "product": (
        "vertical 9:16 mobile poster composition, centered product packaging shot, "
        "a sealed tea canister as the main subject in the middle, tea ware and dry "
        "leaves as supporting props below"
    ),
}

# 风格片段：只写光照 / 色调 / 氛围 / 背景，不写构图与画质（避免与 seed / 画质后缀
# 冲突）。每个片段是一段英文短语，不含句末标点（由 _enrich_prompt 统一拼接）。
_STYLE_FRAGMENTS: dict[str, str] = {
    "fresh": (
        "soft diffused morning daylight, fresh green and ivory color palette, "
        "airy clean background with light wood and fresh foliage, bright clean "
        "and natural mood"
    ),
    "business": (
        "dramatic low-key studio lighting, dark charcoal and warm gold color "
        "palette, dark premium background with deep walnut wood and subtle gold "
        "accents, serious authoritative luxury commercial mood"
    ),
    "guofeng": (
        "classical Chinese aesthetic, traditional ink-painting-inspired muted "
        "palette of celadon green, ink black and vermillion red, aged rice paper "
        "texture background with pine and plum blossom motifs, soft warm lantern "
        "glow, elegant oriental cultural mood"
    ),
}

# 画质后缀：保留画质词，但去掉 CogView 时代的 "No text, no watermark"——
# Seedream 的全部意义就是把中文知识文字渲染进图，禁文字约束已废弃。
_QUALITY_SUFFIX = (
    ", shallow depth of field, sharp focus on the subject, high detail, 8k, "
    "photorealistic"
)

# 图内文字渲染的措辞骨架（实测有效：文字直接叠在照片上、full-bleed 无白边）。
# copy 为空时整段不注入（退化纯画面出图）。中文 copy 直接照搬进 prompt——
# Seedream 中文渲染稳定，无需转译。
_TEXT_OVERLAY_TEMPLATE = (
    "\n\nChinese text is overlaid DIRECTLY on the photograph (not in a white "
    "box), with a subtle dark gradient behind the text areas for legibility:\n"
    "Top, large bold headline overlaid on the upper photo: {headline}\n"
    "Below headline, smaller subheadline overlaid: {subheadline}\n"
    "Bottom, a block of Chinese knowledge text overlaid on the lower photo:\n"
    "{body}\n\n"
    "ALL Chinese characters must be clearly legible and correctly formed, "
    "no garbled, broken, or invented strokes. The text is integrated into the "
    "poster composition as part of the design, not floating in a white area."
)


def _client() -> OpenAI:
    """构造 OpenAI 兼容 client（指向配置的 IMAGE_BASE_URL）。"""
    s = get_settings()
    api_key, base_url = s.image_credentials()
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=s.image_timeout,
        max_retries=0,  # 不静默延长延迟；失败即降级
    )


def _normalize_style(style: str | None) -> str:
    """归一化 style：lower / strip；未知或 None → DEFAULT_STYLE。

    未知 style 不抛、走默认 + log（生图无 seed 兜底，不能因 style 拼错而白屏）。
    """
    if not style:
        return DEFAULT_STYLE
    s = style.strip().lower()
    if s not in _STYLE_FRAGMENTS:
        logger.warning("未知 style=%r，回退默认 %s", style, DEFAULT_STYLE)
        return DEFAULT_STYLE
    return s


def _normalize_scene(scene: str | None) -> str:
    """归一化 scene：lower / strip；未知或 None → DEFAULT_SCENE。

    未知 scene 不抛、走默认 + log（与 style 同理）。
    """
    if not scene:
        return DEFAULT_SCENE
    s = scene.strip().lower()
    if s not in _SCENE_FRAGMENTS:
        logger.warning("未知 scene=%r，回退默认 %s", scene, DEFAULT_SCENE)
        return DEFAULT_SCENE
    return s


def _normalize_language(language: str | None) -> str:
    """归一化 language：lower / strip；None / 空 → _NO_COPY_TOKEN（不取 copy）。

    language 只用作 copy 取值的开关 + 缓存键隔离——只有 zh / en 两种 seed asset，
    其他值取不到 copy 也会退化纯画面，但 language 本身仍进缓存键避免与有效
    language 的请求串。未知 language 不抛、不 log（取不到 copy 已是合理降级）。
    """
    if not language:
        return _NO_COPY_TOKEN
    return language.strip().lower()


def _enrich_prompt(
    prompt: str, style: str, scene: str, copy: dict | None
) -> str:
    """给画面描述 prompt 套 scene 镜头 + style 风格 + 图内中文文字 + 画质后缀。

    seed/LLM image_prompt 只写画面物体 + 产地线索；镜头由 scene 注入，光照/色调/
    氛围由 style 注入——同一茶 prompt × N 镜头 × M 风格，无 seed 爆炸、不调 LLM、
    确定性。copy 提供时把 headline/subheadline/body 直接渲染进 prompt（Seedream
    中文渲染稳定）；copy 为空则退化纯画面出图。零 LLM、零幻觉。
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return prompt
    # 去掉末尾句号再补后缀，避免双句号
    if prompt.endswith(("。", ".")):
        prompt = prompt[:-1]
    scene_frag = _SCENE_FRAGMENTS[scene]
    style_frag = _STYLE_FRAGMENTS[style]
    base = f"{prompt}. {scene_frag}, {style_frag}{_QUALITY_SUFFIX}"

    # copy 三个字段都空则不注入文字段（纯画面出图）
    headline = (copy or {}).get("headline") or ""
    subheadline = (copy or {}).get("subheadline") or ""
    body = (copy or {}).get("body") or ""
    if not (headline or subheadline or body):
        return base
    return base + _TEXT_OVERLAY_TEMPLATE.format(
        headline=headline, subheadline=subheadline, body=body,
    )


def generate_image(
    *,
    prompt: str,
    size: str | None = None,
    style: str | None = None,
    scene: str | None = None,
    copy: dict | None = None,
    language: str | None = None,
) -> tuple[dict | None, str]:
    """调豆包 Seedream 生图（图内渲染中文知识文字）。

    Args:
        prompt: 图片生成 prompt（通常来自 marketing-asset.image_prompt，画面物体描述）
        size: 输出尺寸，空则用配置默认 image_size（Ark 用档位字符串如 "2K"）
        style: 风格（fresh / business）；空或未知 → DEFAULT_STYLE（fresh）
        scene: 镜头（closeup / landscape / product）；空或未知 → DEFAULT_SCENE（closeup）
        copy: 图内中文文字 {"headline","subheadline","body"}；None → 纯画面出图
        language: copy 的语言（zh / en）；与 copy 配合计入缓存键。None → 不取 copy

    Returns:
        (result | None, status)。
        成功 → ({"url","model","size","style","scene","language"}, "ok")；
        否则 → (None, fallback_reason)。
    """
    s = get_settings()
    if not s.image_enabled:
        return None, FALLBACK_DISABLED

    used_size = size or s.image_size
    effective_style = _normalize_style(style)
    effective_scene = _normalize_scene(scene)
    effective_language = _normalize_language(language)
    enriched_prompt = _enrich_prompt(prompt, effective_style, effective_scene, copy)

    # 先查缓存：命中且未过期即复用，跳过 Seedream 调用。
    # 缓存键用原始 prompt + size + style + scene + language（style/scene/language
    # 必须计入，否则切换会命中旧缓存——缓存投毒。language 尤其关键：同 prompt
    # 不同 language 印不同语言文字，不进键会串成错语言图）。copy 文本不直接进键
    # ——它由 (tea_id, language) 决定，language 进键已隔离。
    input_hash = output_store.compute_input_hash(
        ImageResult, prompt, used_size, effective_style, effective_scene,
        effective_language,
    )
    cached = output_store.get_cached(input_hash)
    if cached is not None and _cache_fresh(cached):
        return _build_result(cached, s.image_model, used_size), "ok"

    try:
        resp = _client().images.generate(
            model=s.image_model,
            prompt=enriched_prompt,
            n=1,
            size=used_size,
            response_format="url",  # 我们要 URL（Ark 临时链接）
            # watermark / stream 是 Ark 扩展参数，SDK 不暴露，经 extra_body 透传。
            # watermark=false 去水印；stream=false 同步返回。
            extra_body={"watermark": False, "stream": False},
        )
    except APITimeoutError:
        logger.warning("生图超时 model=%s timeout=%s", s.image_model, s.image_timeout)
        return None, FALLBACK_TIMEOUT
    except APIConnectionError as e:
        # APITimeoutError 是 APIConnectionError 子类，必须放它之前
        logger.warning("生图连接失败 model=%s err=%s", s.image_model, e)
        return None, FALLBACK_NETWORK
    except APIStatusError as e:
        body = ""
        try:
            body = e.response.text[:500]
        except Exception:
            body = ""
        logger.warning(
            "生图网关错误 model=%s status=%s body=%s err=%s",
            s.image_model, e.status_code, body, e,
        )
        return None, FALLBACK_GATEWAY
    except Exception as e:  # 其他未预期异常，兜底为 network_error
        logger.warning("生图调用失败（未分类）model=%s err=%s", s.image_model, e)
        return None, FALLBACK_NETWORK

    # 取图片 URL；代理可能返回非标准 ImagesResponse 形状，统一兜住。
    try:
        url = resp.data[0].url
    except (AttributeError, IndexError, TypeError) as e:
        logger.warning(
            "生图响应非标准 ImagesResponse 形状，降级 model=%s type=%s err=%s",
            s.image_model, type(resp).__name__, e,
        )
        return None, FALLBACK_PARSE
    if not url:
        logger.warning("生图响应 data[0].url 为空，降级 model=%s", s.image_model)
        return None, FALLBACK_PARSE

    now = datetime.now(timezone.utc).isoformat()
    has_copy = bool(copy and (copy.get("headline") or copy.get("subheadline") or copy.get("body")))
    content = {
        "url": url, "model": s.image_model, "size": used_size,
        "style": effective_style, "scene": effective_scene,
        # language 落库：None 时存 _NO_COPY_TOKEN 占位（与缓存键一致）
        "language": effective_language if has_copy else _NO_COPY_TOKEN,
        "created_at": now,
    }
    output_store.persist(
        output_type="image",
        tea_id=None,
        route_id=None,
        input_hash=input_hash,
        content=content,
    )
    logger.info(
        "生图成功 model=%s size=%s style=%s scene=%s language=%s copy=%s prompt_chars=%d",
        s.image_model, used_size, effective_style, effective_scene,
        effective_language, "y" if has_copy else "n", len(enriched_prompt),
    )
    return _build_result(content, s.image_model, used_size), "ok"


def _cache_fresh(cached: dict) -> bool:
    """缓存是否在有效期内（created_at ≤29 天）。

    created_at 缺失或解析失败视为过期（强制重生，避免死链）。
    """
    created = cached.get("created_at")
    if not created:
        return False
    try:
        ts = datetime.fromisoformat(created)
    except (ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts < _CACHE_TTL


def _build_result(content: dict, model: str, size: str) -> dict:
    """从缓存内容组装返回结果（命中缓存时模型/尺寸/风格/镜头/语言沿用缓存值）。"""
    lang = content.get("language")
    return {
        "url": content["url"],
        "model": content.get("model") or model,
        "size": content.get("size") or size,
        "style": content.get("style"),
        "scene": content.get("scene"),
        # language=_NO_COPY_TOKEN 表示纯画面出图（无文字），对外回显 None
        "language": None if lang == _NO_COPY_TOKEN else lang,
    }
