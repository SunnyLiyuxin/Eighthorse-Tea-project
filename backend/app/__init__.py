"""Eighthorse-Tea 后端应用包。

运行时读路径查 SQLite（data_loader getter，seed.py --reset 灌表）；写路径经
output_store 缓存 generated_outputs 表。LLM 已接入（可选，未配置 key / 失败时
退回 seed 兜底）。未接真实生图 / 视频。
"""
