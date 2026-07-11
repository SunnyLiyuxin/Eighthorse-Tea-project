"""FastAPI 入口。

阶段一（静态可跑）：YAML seed 数据 + 规则筛选骨架 + 全套 P0 接口 + fallback。
数据来源 backend/data/seeds/*.yaml（经 app.data_loader 加载到内存 registry）。
未接 SQLite / LLM / 真实生图。

启动：
    cd backend
    uvicorn app.main:app --reload
    # 或直接：python app/main.py
Swagger: http://localhost:8000/docs
"""

# 让 `python app/main.py` 也能找到 `app` 包（把 backend/ 加入搜索路径）。
# 必须在 import app.* 之前执行。uvicorn 方式不受影响。
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import data_loader  # noqa: F401  启动时加载 seed
from app import responses
from app.routers import assets, debug, expressions, fallback, teas, trace

app = FastAPI(
    title="中国茶 AI 表达 Demo",
    description=(
        "中国茶感知与文化表达的分层翻译系统 Demo。"
        "主路径：1 款茶（铁观音）× 图片物料 ×（国内链 + 跨文化链）两条同构链路。"
    ),
    version="0.3.0",
)

# Demo 阶段放开 CORS，方便前端本地联调；上线前应收紧 origins。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """根路径：给个入口提示，非业务接口。"""
    return {
        "name": "中国茶 AI 表达 Demo",
        "docs": "/docs",
        "main_routes": [
            "/api/demo-routes",
            "/api/teas",
            "/api/teas/{tea_id}/knowledge",
            "/api/teas/{tea_id}/flavor-profile",
            "/api/teas/{tea_id}/domestic-expression",
            "/api/teas/{tea_id}/cross-cultural-expression",
            "/api/teas/{tea_id}/marketing-asset",
            "/api/trace/{output_id}",
        ],
    }


@app.get("/health")
def health():
    """健康检查。"""
    return {"status": "ok"}


@app.on_event("startup")
def _load_seeds_on_startup() -> None:
    """启动时预热 seed registry（data_loader 已 lru_cache，这里主动触发一次，
    便于在启动日志中确认 seed 加载正常，而非在首个请求时才暴露加载错误）。
    同时打印一次 LLM 启用状态，方便确认是否已接 LLM（不输出 key）。"""
    data_loader.all_seeds()
    from app.config import get_settings

    s = get_settings()
    if s.llm_enabled:
        print(f"[startup] LLM 已启用：model={s.llm_model} timeout={s.llm_timeout}")
    else:
        print("[startup] LLM 未启用（未配置 LLM_API_KEY / LLM_BASE_URL），生成接口走 mock 兜底")


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求体校验失败统一走 error 响应格式，前端解析一致。

    FastAPI 默认返回 {"detail": [...]}，这里改造成本项目的
    { success: false, error: {code, message} } 结构。
    """
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    message = first.get("msg", "请求参数校验失败")
    detail = f"{loc}: {message}" if loc else message
    return JSONResponse(
        status_code=422,
        content=responses.error("VALIDATION_ERROR", detail),
    )


# 挂载业务路由（顺序重要：具体路由须在 fallback 的 catch-all 之前注册，
# 否则 /api/{path:path} 会抢先匹配 /api/teas 等）。
app.include_router(teas.router)
app.include_router(expressions.router)
app.include_router(assets.router)
app.include_router(trace.router)
app.include_router(debug.router)  # /api/health-llm（调试用，非 P0 契约）
app.include_router(fallback.router)  # 含 P1/P2 占位 + /api/* 全局 catch-all


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
