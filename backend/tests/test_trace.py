"""纵向追溯链：四层结构，国内链/跨文化链各自对称。

重点验证：
- 物料 → 表达 → 风味坐标 → 知识依据，四层 level 3→0
- 横向翻译关系不进纵向链（trace 内不含 source_expression_id 跨链跳转）
"""

ASSET_EN = "asset_szz_poster_en"
ASSET_ZH = "asset_szz_poster_zh"


def test_trace_cross_cultural_chain(client):
    resp = client.get(f"/api/trace/{ASSET_EN}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    d = body["data"]
    assert d["output_id"] == ASSET_EN
    assert d["output_type"] == "marketing_asset"
    trace = d["trace"]
    assert len(trace) == 4
    # level 单调递减 3→0
    levels = [n["level"] for n in trace]
    assert levels == [3, 2, 1, 0]
    # 各层 id 链通
    assert trace[0]["id"] == ASSET_EN
    assert trace[1]["id"] == "expr_en_szz_tgy_nx_coffee"
    assert trace[2]["id"] == "flavor_szz_tgy_nx"
    assert trace[3]["id"] == "knowledge_szz_tgy_nx"
    # 每层有 summary
    for n in trace:
        assert n["name"] and n["summary"]


def test_trace_domestic_chain(client):
    resp = client.get(f"/api/trace/{ASSET_ZH}")
    d = resp.json()["data"]
    assert d["output_type"] == "marketing_asset"
    trace = d["trace"]
    assert len(trace) == 4
    assert [n["level"] for n in trace] == [3, 2, 1, 0]
    assert trace[1]["id"] == "expr_cn_szz_tgy_nx"
    assert trace[2]["id"] == "flavor_szz_tgy_nx"  # 两链共享底层


def test_trace_not_found(client):
    resp = client.get("/api/trace/nonexistent_id")
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "TRACE_NOT_FOUND"


def test_trace_expression_id(client):
    """追溯表达本身（level 2 起点）。"""
    resp = client.get("/api/trace/expr_en_szz_tgy_nx_coffee")
    d = resp.json()["data"]
    assert d["output_type"] == "expression"
    trace = d["trace"]
    # 表达 → 风味 → 知识，三层
    assert len(trace) == 3
    assert [n["level"] for n in trace] == [2, 1, 0]
