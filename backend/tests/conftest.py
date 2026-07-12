"""pytest 全局夹具。

LLM 禁用策略：直接 monkeypatch 每个模块里 `get_settings` 的名字绑定。
为什么不用 app.dependency_overrides：各 service / router / llm_service 里都是
`get_settings()` 直接函数调用（不是 Depends(get_settings)），DI 覆盖拦不住，
真 .env（gitignored，含真实 key）会让 llm_enabled=True 并真调 LLM。
而 `from app.config import get_settings` 在导入时已把函数对象绑到各模块命名空间，
所以必须逐个 patch 每个引用模块的 get_settings 属性。

测试默认全程 LLM disabled → 走 seed 兜底（与未接 LLM 行为一致）。
test_llm_fallback.py 用局部 fixture 覆盖此默认，单独验证降级契约。
显式传参构造 Settings(llm_api_key="", ...) 会覆盖 .env 读取（pydantic-settings v2
init 参数优先级高于文件/环境），干净绕开真实 key。
"""

import importlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import config
from app.config import Settings
from app.main import app

# 所有直接 `from app.config import get_settings` 后在运行时调用 get_settings() 的模块。
# 改 app.config.get_settings 不影响它们持有的导入期引用，须逐模块 patch。
_SETTINGS_MODULES = (
    "app.services.expression_service",
    "app.services.asset_service",
    "app.services.llm_service",
    "app.routers.debug",
    "app.main",
)

_DISABLED_SETTINGS = Settings(llm_api_key="", llm_base_url="")


def _patch_get_settings(monkeypatch, settings: Settings) -> None:
    """把各模块的 get_settings 名字替换成返回指定 settings 的 lambda。"""
    fn = lambda s=settings: s  # noqa: E731  闭包捕获 settings
    for mod_name in _SETTINGS_MODULES:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "get_settings", fn, raising=False)
    monkeypatch.setattr(config, "get_settings", fn, raising=False)


@pytest.fixture(autouse=True)
def llm_disabled(monkeypatch) -> Iterator[None]:
    """默认禁用 LLM：各模块 get_settings 返回未启用配置。

    autouse=True → 所有测试默认生效；test_llm_fallback.py 用局部 fixture 覆盖。
    """
    _patch_get_settings(monkeypatch, _DISABLED_SETTINGS)
    yield


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """FastAPI TestClient，与 uvicorn 同一 app 对象。"""
    with TestClient(app) as c:
        yield c


# 供测试复用
TEA_ID = "BAMA_SZZ_TGY_NX"
