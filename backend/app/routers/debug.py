"""调试路由：LLM 健康检查。

非 P0 契约接口，标 debug/internal，用于 Demo 当场确认 LLM 是否接上、是否可用。
不输出明文 key；base_url 仅暴露 scheme+host，掩码 path 与 query。
"""

from urllib.parse import urlparse

from fastapi import APIRouter

from app import responses
from app.config import get_settings

router = APIRouter(prefix="/api", tags=["debug"])


def _mask_base_url(url: str) -> str:
    """只保留 scheme + host，掩码 path / query，避免泄露完整端点。"""
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "(invalid)"
    return f"{parsed.scheme}://{parsed.netloc}/**"


@router.get("/health-llm")
def health_llm():
    """LLM 健康检查：返回启用状态 / 模型 / 掩码 base_url / 是否支持 JSON mode。"""
    s = get_settings()
    return responses.success(
        {
            "llm_enabled": s.llm_enabled,
            "llm_model": s.llm_model,
            "llm_base_url_masked": _mask_base_url(s.llm_base_url),
            "llm_supports_json_mode": s.llm_supports_json_mode,
        },
    )
