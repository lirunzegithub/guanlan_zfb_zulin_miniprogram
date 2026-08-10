"""行政区划码表下发

  GET /api/regions          整份省市区三级数据（小程序地址选择器用，客户端长期缓存）
  GET /api/regions/version  只返回 version，用来判断本地缓存是否过期（几十字节）

数据文件是 data/regions.json，由 scripts/build_regions.py 生成并随代码入库
（data/ 下唯一一个进仓库的 JSON，.gitignore 里有对应例外）。区划每年有调整，
换新码表就重跑脚本，version 会变，客户端下次启动自动重拉。

整份约 130KB，所以：进程内缓存 + gzip + ETag，正常情况下客户端只会下载一次。
"""
import gzip
import json
from pathlib import Path

from flask import Blueprint, Response, request

from app.response import fail, ok

bp = Blueprint("regions", __name__)

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "regions.json"

# (version, 原始 JSON bytes, gzip 后 bytes)；按文件 mtime 失效，改了码表不用重启进程
_cache: tuple[float, str, bytes, bytes] | None = None


def _load() -> tuple[str, bytes, bytes]:
    global _cache
    if not _FILE.exists():
        raise FileNotFoundError(
            f"缺少 {_FILE}，请在 houdan/ 下执行：python3 scripts/build_regions.py"
        )
    mtime = _FILE.stat().st_mtime
    if _cache and _cache[0] == mtime:
        return _cache[1], _cache[2], _cache[3]

    doc = json.loads(_FILE.read_text("utf-8"))
    version = str(doc.get("version") or "")
    raw = json.dumps(
        {"code": 0, "msg": "ok", "data": doc}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    _cache = (mtime, version, raw, gzip.compress(raw, 6))
    return version, raw, _cache[3]


@bp.get("")
def get_regions():
    try:
        version, raw, gz = _load()
    except FileNotFoundError as e:
        return fail(500, str(e))

    etag = f'W/"{version}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag, "Cache-Control": "public, max-age=86400"})

    use_gzip = "gzip" in (request.headers.get("Accept-Encoding") or "")
    resp = Response(gz if use_gzip else raw, mimetype="application/json")
    if use_gzip:
        resp.headers["Content-Encoding"] = "gzip"
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.get("/version")
def get_version():
    try:
        version, _, _ = _load()
    except FileNotFoundError as e:
        return fail(500, str(e))
    return ok({"version": version})
