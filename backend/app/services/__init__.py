"""服务层（业务逻辑）：被 routers 调用，不碰 HTTP / JSON 响应格式。

数据来自 SQLite：data_loader getter 查 tea.db（seed.py --reset 灌表）；
LLM 生成结果经 output_store 写入 generated_outputs 表缓存。services 只负责
检索、筛选、组装和校验，不碰 YAML 加载细节。
"""
