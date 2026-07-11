"""Fallback 路由。

P1：GET/POST /api/fallback —— 显式 fallback 入口。
P2：占位接口（video-asset / translate / image/generate / audio/generate
     / markets / audience-references）统一返回 fallback，避免 404。
"""

import functools
import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import responses
from app.schemas import FallbackRequest

router = APIRouter(prefix="/api", tags=["fallback"])


@router.get("/fallback")
def get_fallback():
    """显式 fallback 入口（P1）。"""
    return responses.fallback_response()


@router.post("/fallback")
def post_fallback(body: FallbackRequest):
    """前端访问未开放功能时的统一占位（P1）。"""
    return responses.fallback_response(
        message=f"功能 {body.feature or '未知'} 已在产品规划中，Demo 阶段暂不提供。"
        if body.feature
        else "该能力已在产品规划中，Demo 阶段暂不提供真实生成结果。"
    )


# ---------------------------------------------------------------------------
# P2 占位接口：注册路由 + 返回 fallback，不实现真实逻辑
# ---------------------------------------------------------------------------


@router.post("/teas/{tea_id}/video-asset")
def video_asset(tea_id: str):
    """视频生成（P2 占位）。"""
    return responses.fallback_response(message="视频生成 Demo 阶段暂不开放。")


@router.post("/translate")
def translate(body: dict | None = None):
    """通用翻译（P2 占位）。"""
    return responses.fallback_response(
        message="通用翻译 Demo 阶段暂不开放，跨文化表达请走 cross-cultural-expression。"
    )


@router.post("/image/generate")
def image_generate(body: dict | None = None):
    """真实生图（P2 占位）。"""
    return responses.fallback_response(
        message="真实生图 Demo 阶段暂不开放，marketing-asset 返回 image_prompt 供前端渲染。"
    )


@router.post("/audio/generate")
def audio_generate(body: dict | None = None):
    """音频生成（P2 占位）。"""
    return responses.fallback_response(message="音频生成 Demo 阶段暂不开放。")


@router.get("/markets")
def markets():
    """市场列表（P2 占位）。"""
    return responses.fallback_response(message="市场列表 Demo 阶段暂以 demo-routes 暴露。")


@router.get("/audience-references")
def audience_references():
    """受众参照系列表（P2 占位）。"""
    return responses.fallback_response(message="受众参照系列表 Demo 阶段暂以 demo-routes 暴露。")


# ---------------------------------------------------------------------------
# 全局 /api/* 404 fallback：未知 API 路由不返回默认 404，返回 fallback JSON
# ---------------------------------------------------------------------------


def _registered_routes(app) -> list[tuple[str, set[str]]]:
    """已注册路由的 (path, methods) 列表，来自 OpenAPI schema 的 paths。

    不遍历 app.routes 内部结构：新版 FastAPI 把 include_router 存成 _IncludedRouter
    （path=None、无 .routes），递归收集会漏掉全部业务路由。改用 app.openapi()['paths']
    ——它是 FastAPI 暴露已注册路由的稳定接口，键即去尾斜杠的规范路径
    （如 /api/teas/{tea_id}/knowledge），值含该路径支持的 method 列表。参数占位
    {tea_id} 保留，可被 _compile_route 编译成 [^/]+ 正则用于动态段比对。

    返回 (path, methods) 元组列表：重定向前既要 path 匹配，也要当前请求方法被该
    路由支持——否则 GET 请求命中一条 POST-only 路由时，会 302 重定向到同一 URL
    （重定向保持原方法），永远到不了 POST handler，形成"重定向太多次"死循环。
    """
    routes: list[tuple[str, set[str]]] = []
    try:
        schema = app.openapi()
    except Exception:
        schema = {"paths": {}}
    for path, ops in schema.get("paths", {}).items():
        methods = {m.upper() for m in ops if m.lower() in
                   {"get", "post", "put", "delete", "patch", "head", "options"}}
        routes.append((path.rstrip("/"), methods))
    return routes


# catch-all 自身模式：app.openapi() 会把 /{path:path} 收为 /api/{path}，
# 它匹配任意单段，会让"真未知路由"自匹配后重定向到自己（死循环）。这里显式排除。
_CATCH_ALL_PATTERN = "/api/{path}"


@functools.lru_cache(maxsize=None)
def _compile_route(pattern: str) -> re.Pattern:
    """把 FastAPI 路径模式编译成锚定正则。

    {param} 段匹配 [^/]+，其余字面量逐段 re.escape 后拼接（避免正则注入）。
    如 /api/teas/{tea_id}/knowledge → ^/api/teas/[^/]+/knowledge$。
    用于把具体 URL 与动态段路由模式比对（catch-all 收到的尾斜杠请求需重定向）。
    """
    parts = re.split(r"(\{[^/]+\})", pattern.rstrip("/"))
    src: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("{") and part.endswith("}"):
            src.append(r"[^/]+")
        else:
            src.append(re.escape(part))
    return re.compile("^" + "".join(src) + "$")


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def catch_all_api(path: str, request: Request):
    """捕获所有未匹配的 /api/* 请求。

    本路由挂在 prefix="/api" 下，path 是去掉 "/api/" 后的部分
    （如 "demo-routes/" 或 "teas/tieguanyin_001/knowledge/"）。

    重定向前同时校验 path 与 method：
    - 若带尾斜杠的请求其实命中某已注册路由、且该路由支持当前请求方法
      （含动态段路由 /teas/{tea_id}/knowledge/），则 302 重定向到无尾斜杠的规范形式，
      修复"真实路由被 catch-all 误吞成 fallback"。
    - 若 path 匹配但方法不被该路由支持（如 GET 命中一条 POST-only 路由），
      不重定向（重定向保持原方法，会死循环），直接走 fallback。
    - 否则返回 fallback（fallback_reason=api_not_implemented）。
    """
    normalized = path.rstrip("/")
    target = f"/api/{normalized}"
    # 第一遍：找 path 匹配且支持当前方法的已注册路由 → 302 重定向到无尾斜杠规范形式
    for registered, methods in _registered_routes(request.app):
        if registered == _CATCH_ALL_PATTERN:
            continue  # 跳过 catch-all 自身，避免真未知路由自匹配重定向死循环
        if request.method.upper() not in methods:
            continue  # 方法不匹配：重定向保持原方法，会死循环，不重定向
        if _compile_route(registered).match(target):
            return RedirectResponse(url=target, status_code=302)

    # 第二遍：path 匹配但方法不支持 → 该路由存在，只是请求方法错了
    # （如 GET 命中一条 POST-only 路由）。给出方法提示，而非"接口未实现"的误导。
    for registered, methods in _registered_routes(request.app):
        if registered == _CATCH_ALL_PATTERN:
            continue
        if _compile_route(registered).match(target):
            allowed = "/".join(sorted(methods))
            return responses.fallback_response(
                title="请求方法不匹配",
                message=f"该接口需用 {allowed} 访问，当前为 {request.method.upper()}。",
                suggested_action="可在 Swagger 调试：/docs",
                fallback_reason="method_not_allowed",
            )

    return responses.fallback_response(
        title="接口暂未开放",
        message="该接口尚未在 Demo 后端中实现。请确认是否属于后续功能。",
        fallback_reason="api_not_implemented",
    )
