"""落地页 + 商品静态资源

ASSETS_DIR 指向 houdan/static/，供两类资源共用：
  - /product/asset/landing/landing.jpg   落地页主图
  - /product/asset/products/<slug>.jpg   商品封面（slug 与 product.cover_url 对应）

替换图片直接覆盖对应路径文件即可，无需改后端代码。
"""
import os
from flask import Blueprint, send_from_directory, Response

bp = Blueprint("landing", __name__)

ASSETS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "static")
)


@bp.get("")
def landing_page():
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no" />
  <title>观澜数码租赁 · 3C数码专业估价与线下回收服务</title>
  <style>
    :root {
      --bg: #f3f4f7;
      --card: #ffffff;
      --card-soft: #eef0f4;
      --text: #1a1f2e;
      --text-sub: #5b6373;
      --text-mute: #9aa4b2;
      --accent: #e85a4f;
      --navy: #565f80;
      --navy-deep: #3f4868;
      --divider: #d5d9e2;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: var(--bg); }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }
    .page { max-width: 750px; margin: 0 auto; padding: 24px 28px 0; }

    /* ===== Hero ===== */
    .hero {
      background: var(--card);
      border-radius: 22px;
      padding: 44px 36px 24px;
      box-shadow: 0 6px 22px rgba(30, 38, 60, 0.06);
    }
    .hero h1 {
      font-size: 44px;
      line-height: 1.08;
      margin: 0 0 10px;
      font-weight: 800;
      letter-spacing: -0.5px;
    }
    .hero .sub {
      font-size: 22px;
      font-weight: 700;
      color: var(--text);
      margin: 0;
    }
    .hero .visual {
      position: relative;
      margin-top: 18px;
      aspect-ratio: 4 / 3;
      background:
        url("/product/asset/landing/hero.png") center/contain no-repeat;
    }

    /* ===== Section title ===== */
    .section-title {
      text-align: center;
      margin: 56px 0 14px;
    }
    .section-title h2 {
      font-size: 34px;
      font-weight: 800;
      margin: 0 0 14px;
      letter-spacing: -0.3px;
    }
    .section-title p {
      font-size: 18px;
      line-height: 1.7;
      color: var(--text-sub);
      margin: 0 auto;
      max-width: 78%;
    }

    /* ===== Steps card ===== */
    .steps {
      margin-top: 22px;
      background: var(--card-soft);
      border-radius: 18px;
      padding: 32px 26px;
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: 130px 1fr;
      gap: 18px;
    }
    .steps ol {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 26px;
    }
    .steps li {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 6px;
      color: var(--text-sub);
      font-size: 16px;
    }
    .steps li .icon {
      width: 30px;
      height: 30px;
      color: var(--text);
      opacity: 0.7;
    }
    .steps li.active { color: var(--accent); }
    .steps li.active .icon { color: var(--accent); opacity: 1; }
    .steps .photos {
      position: relative;
    }
    .steps .photos::before {
      content: "";
      position: absolute;
      left: 0; right: 0; top: 50%;
      height: 1px;
      border-top: 1px dashed #c8cdd8;
    }
    .steps .photos .ph {
      width: 100%;
      height: 50%;
      background-position: center;
      background-repeat: no-repeat;
      background-size: contain;
    }
    .steps .photos .ph.top    { background-image: url("/product/asset/landing/headset-front.png"); }
    .steps .photos .ph.bottom { background-image: url("/product/asset/landing/headset-back.png"); }

    /* ===== Compare card ===== */
    .compare-wrap {
      position: relative;
      margin: 28px 0 40px;
    }
    .compare {
      background: var(--navy);
      border-radius: 16px;
      padding: 26px 22px 22px;
      color: #fff;
      position: relative;
    }
    .compare h3 {
      margin: 0 0 18px;
      font-size: 22px;
      font-weight: 700;
    }
    .compare .rows {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .compare .row {
      display: grid;
      grid-template-columns: 88px 1fr;
      align-items: center;
      gap: 10px;
    }
    .compare .row .lbl {
      color: #fff;
      font-size: 15px;
      font-weight: 500;
      padding-left: 4px;
    }
    .compare .row .val {
      background: var(--navy-deep);
      color: #fff;
      font-size: 14px;
      padding: 10px 14px;
      border-radius: 10px;
    }
    .compare .floating {
      position: absolute;
      top: -42px;
      right: -10px;
      width: 130px;
      height: 90px;
      background: url("/product/asset/landing/mini-headset.png") center/contain no-repeat;
      pointer-events: none;
    }

    /* ===== Footer ===== */
    .footer {
      max-width: 750px;
      margin: 40px auto 0;
      background: var(--card);
      color: var(--text-sub);
      padding: 32px 28px 24px;
      box-shadow: 0 -2px 12px rgba(30, 38, 60, 0.04);
    }
    .footer .brand {
      display: flex;
      align-items: center;
      margin-bottom: 20px;
    }
    .footer .brand .logo {
      width: 60px;
      height: 60px;
      background: url("/product/asset/landing/icon.png") center/contain no-repeat;
    }
    .footer .cols {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px 24px;
      padding-bottom: 22px;
      border-bottom: 1px solid var(--divider);
    }
    .footer .col h4 {
      margin: 0 0 10px;
      font-size: 14px;
      font-weight: 600;
      color: var(--text);
      letter-spacing: 0.3px;
    }
    .footer .col ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .footer .col li {
      font-size: 13px;
      line-height: 1.6;
      color: var(--text-sub);
    }
    .footer .col li .k {
      color: var(--text-mute);
      margin-right: 6px;
    }
    .footer .copy {
      margin-top: 18px;
      text-align: center;
      font-size: 12px;
      line-height: 1.7;
      color: var(--text-mute);
    }
    .footer .copy .company {
      color: var(--text-sub);
      font-size: 13px;
      margin-bottom: 4px;
    }
  </style>
</head>
<body>
  <main class="page">
    <!-- Hero -->
    <section class="hero">
      <p class="sub">二手闲置物品专业估价与线下回收服务</p>
      <div class="visual" role="img" aria-label="VR 一体机与控制器"></div>
    </section>


    <!-- Compare -->
    <header class="section-title">
      <h2>估价优势</h2>
      <p>估价更有保障，把控整个过程，为您提供更加方便快捷的服务。</p>
    </header>

    <div class="compare-wrap">
      <section class="compare">
        <h3>服务</h3>
        <div class="rows">
          <div class="row">
            <div class="lbl">估价</div>
            <div class="val">专业估价，不惧比价</div>
          </div>
          <div class="row">
            <div class="lbl">检测</div>
            <div class="val">专业质检，全程可追溯</div>
          </div>
          <div class="row">
            <div class="lbl">物流服务</div>
            <div class="val">同城免费上门</div>
          </div>
          <div class="row">
            <div class="lbl">服务</div>
            <div class="val">一对一顾问，随时响应</div>
          </div>
        </div>
      </section>
      <div class="floating" aria-hidden="true"></div>
    </div>
  </main>

  <footer class="footer">
    <div class="brand">
      <div class="logo" role="img" aria-label="观澜数码"></div>
    </div>

    <div class="cols">
      <div class="col">
        <h4>服务范围</h4>
        <ul>
          <li>二手闲置物品专业估价</li>
          <li>同城免费上门</li>
        </ul>
      </div>
      <div class="col">
        <h4>联系我们</h4>
        <ul>
          <li><span class="k">客服</span>400-000-0000</li>
          <li><span class="k">时间</span>周一至周日 9:00-21:00</li>
          <li><span class="k">地址</span>海南省海口市</li>
        </ul>
      </div>
    </div>

    <div class="copy">
      <div class="company">示例数码租赁有限责任公司</div>
    </div>
  </footer>
</body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


@bp.get("/asset/<path:filename>")
def asset(filename):
    return send_from_directory(ASSETS_DIR, filename)
