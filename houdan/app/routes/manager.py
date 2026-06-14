"""管理后台入口

- GET  /manager                   → SPA 外壳（index.html）
- GET  /manager-assets/<path:p>   → 静态文件（.vue / .js / 资源）

为 SPA history 留位（当前用 hash 路由，不需要 catch-all，未来切 history 时再加）。
"""
import os
from flask import Blueprint, send_from_directory, send_file

bp_view = Blueprint("manager_view", __name__)
bp_static = Blueprint("manager_static", __name__)

MANAGER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "manager"))


@bp_view.get("")
@bp_view.get("/")
def manager_index():
    return send_file(os.path.join(MANAGER_DIR, "index.html"))


@bp_static.get("/<path:filename>")
def manager_assets(filename):
    return send_from_directory(MANAGER_DIR, filename)
