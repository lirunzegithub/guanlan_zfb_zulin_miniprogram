"""Flask 应用工厂"""
from flask import Flask, jsonify, request, g
from flask_cors import CORS

from app.response import ok, fail  # noqa: F401  对外保留 import path
from app.storage.repos import init_seeds
from app import auth_user_token
from app.routes.products import bp as products_bp
from app.routes.categories import bp as categories_bp
from app.routes.banners import bp as banners_bp
from app.routes.orders import bp as orders_bp
from app.routes.user import bp as user_bp
from app.routes.addresses import bp as addresses_bp
from app.routes.service import bp as service_bp
from app.routes.alipay import bp as alipay_bp
from app.routes.landing import bp as landing_bp
from app.routes.home import bp as home_bp
from app.routes.manager import bp_view as manager_view_bp, bp_static as manager_static_bp
from app.routes.admin import bp as admin_bp
from app.routes.comments import bp as comments_bp
from app.routes.favorites import bp as favorites_bp
from app.routes.share import bp as share_bp
from app.routes.coupons import bp_public as coupons_bp, bp_user as user_coupons_bp
from app.routes.auth import bp as auth_bp


# ---------------------- 用户鉴权白名单 ----------------------
# 不在白名单的 /api/* 都要求 Authorization: Bearer <token>。
# /api/admin/* 完全跳过（有独立的管理后台 session），非 /api/ 路径也不管。
_AUTH_EXEMPT_EXACT: set[tuple[str, str]] = {
    ("POST", "/api/auth/login"),
    ("GET",  "/api/orders/tabs"),
    ("GET",  "/api/comments"),
}

# (method, prefix) —— prefix 用 startswith 匹配
_AUTH_EXEMPT_PREFIX: tuple[tuple[str, str], ...] = (
    ("POST", "/api/alipay/notify/"),   # 支付宝服务器侧调用，自己带验签
    ("GET",  "/api/products"),         # 商品列表/详情公开浏览
    ("GET",  "/api/categories"),
    ("GET",  "/api/banners"),
    ("GET",  "/api/service/"),
    ("GET",  "/api/share/products/"),  # 分享卡片可被未登录用户预览
    ("GET",  "/api/share/stats/"),
    ("GET",  "/api/coupons"),          # 公开优惠券列表
)


def _is_public(method: str, path: str) -> bool:
    if (method, path) in _AUTH_EXEMPT_EXACT:
        return True
    return any(method == m and path.startswith(p) for m, p in _AUTH_EXEMPT_PREFIX)


def create_app():
    app = Flask(__name__)
    CORS(app)
    init_seeds()

    @app.before_request
    def _auth_guard():
        path = request.path or ""
        # 只管 /api/ 下且不是 /api/admin/*；其他路径有自己的鉴权或就是公开页
        if not path.startswith("/api/") or path.startswith("/api/admin"):
            return
        public = _is_public(request.method, path)
        # 公开页也尝试解析 token：拿到就填 g.user_id，让 detail/列表里"按需返回"的
        # 字段（如 favorited）能正确反映当前用户视角；拿不到则匿名放行。
        token = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
        sess = auth_user_token.get(token) if token else None
        if sess:
            g.user_id = sess["user_id"]
            g.user_token = token
            return
        if public:
            return
        return jsonify(code=401, msg="未登录或登录已过期", data=None), 401

    @app.errorhandler(404)
    def _not_found(_):
        return jsonify(code=404, msg="not found", data=None), 404

    @app.errorhandler(Exception)
    def _err(e):
        return jsonify(code=500, msg=str(e), data=None), 500

    # 根路径 / 渲染平台介绍页（HTML）；JSON 探测请打 /api/* 各具体端点
    app.register_blueprint(home_bp)

    app.register_blueprint(auth_bp,       url_prefix="/api/auth")
    app.register_blueprint(products_bp,   url_prefix="/api/products")
    app.register_blueprint(categories_bp, url_prefix="/api/categories")
    app.register_blueprint(banners_bp,    url_prefix="/api/banners")
    app.register_blueprint(orders_bp,     url_prefix="/api/orders")
    app.register_blueprint(user_bp,       url_prefix="/api/user")
    app.register_blueprint(addresses_bp,  url_prefix="/api/user/addresses")
    app.register_blueprint(service_bp,    url_prefix="/api/service")
    app.register_blueprint(alipay_bp,     url_prefix="/api/alipay")
    app.register_blueprint(landing_bp,    url_prefix="/product")
    app.register_blueprint(manager_view_bp,   url_prefix="/manager")
    app.register_blueprint(manager_view_bp,   url_prefix="/manage", name="manager_view_m")
    app.register_blueprint(manager_static_bp, url_prefix="/manager-assets")
    app.register_blueprint(admin_bp,          url_prefix="/api/admin")
    app.register_blueprint(comments_bp,       url_prefix="/api/comments")
    app.register_blueprint(favorites_bp,      url_prefix="/api/user/favorites")
    app.register_blueprint(share_bp,          url_prefix="/api/share")
    app.register_blueprint(coupons_bp,        url_prefix="/api/coupons")
    app.register_blueprint(user_coupons_bp,   url_prefix="/api/user/coupons")

    # 定时任务（每小时扫描 recv 状态订单，物流期已过自动转 using + 同步阿里）
    from app.scheduler import start_scheduler
    start_scheduler()

    return app
