"""根域名平台介绍页（HTML 渲染）。

your-domain.example.com 浏览器访问看到的就是这一页；
JSON 服务探测请打 /api/* 各具体端点。

设计语言：暖白纸感 + 墨色宋体编辑排版 + 珊瑚红点睛，无斜线元素。
非线性 3D：鼠标惯性视差首屏 / 可拖拽惯性 3D 品类环 / 滚动 3D 翻转入场。
零外部依赖（无 CDN 字体、无 JS 库），国内访问速度不受影响。
"""
from flask import Blueprint, Response

bp = Blueprint("home", __name__)


_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>观澜数码租赁 · 芝麻免押 3C 数码租赁平台</title>
  <meta name="description" content="3C 数码免押租赁，芝麻信用授权，无需冻结现金；VR / 智能手机 / 笔记本 / 摄影器材按天租用。" />
  <link rel="icon" type="image/png" href="/product/asset/landing/icon.png" />
  <link rel="apple-touch-icon" href="/product/asset/landing/icon.png" />
  <style>
    :root {
      --paper: #ffffff;
      --paper-2: #f7f7f8;
      --white: #ffffff;
      --ink: #181c29;
      --ink-soft: #2a2f40;
      --ink-dim: rgba(24, 28, 41, 0.6);
      --ink-mute: rgba(24, 28, 41, 0.4);
      --coral: #e85a4f;
      --coral-soft: rgba(232, 90, 79, 0.08);
      --gold: #b08e57;
      --line: rgba(24, 28, 41, 0.08);
      --line-strong: rgba(24, 28, 41, 0.16);
      --shadow-soft: 0 24px 60px rgba(24, 28, 41, 0.08);
      --shadow-deep: 0 30px 70px rgba(24, 28, 41, 0.14);
      --cream: #f3efe6;
      --font-display: "Songti SC", "STSong", "Noto Serif SC", "SimSun", serif;
      --font-body: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif;
      --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }
    html, body { background: var(--paper); }
    body {
      font-family: var(--font-body);
      color: var(--ink);
      min-height: 100vh;
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
    }
    ::selection { background: var(--coral); color: #fff; }

    /* ===== 大气背景：极淡渐变雾 + 细颗粒 ===== */
    .mist {
      position: fixed; inset: -20%;
      z-index: 0; pointer-events: none;
      background:
        radial-gradient(42% 38% at 16% 20%, rgba(232, 90, 79, 0.035), transparent 70%),
        radial-gradient(38% 34% at 86% 14%, rgba(86, 95, 128, 0.04), transparent 70%);
      animation: mistDrift 26s ease-in-out infinite alternate;
    }
    @keyframes mistDrift {
      from { transform: translate3d(-2%, -1%, 0) scale(1); }
      to   { transform: translate3d(2%, 2%, 0) scale(1.06); }
    }
    body::after {
      content: ""; position: fixed; inset: 0;
      z-index: 90; pointer-events: none; opacity: 0.028;
      background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2"/></filter><rect width="180" height="180" filter="url(%23n)"/></svg>');
    }

    /* ===== 滚动进度 ===== */
    .progress {
      position: fixed; top: 0; left: 0; height: 2px; width: 0;
      background: linear-gradient(90deg, var(--coral), var(--gold));
      z-index: 100;
    }

    /* ===== 顶栏 ===== */
    .nav {
      position: fixed; top: 0; left: 0; right: 0; z-index: 80;
      display: flex; align-items: center; justify-content: space-between;
      padding: 18px 40px;
      background: rgba(255, 255, 255, 0.78);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--line);
    }
    .nav .brand {
      display: flex; align-items: center; gap: 11px;
      font-family: var(--font-display);
      font-size: 19px; font-weight: 900; letter-spacing: 4px;
    }
    .nav .brand img {
      width: 34px; height: 34px;
      border-radius: 9px;
      border: 1px solid var(--line);
      background: var(--white);
      display: block;
    }
    .nav .cta {
      font-size: 13px; letter-spacing: 2px; text-decoration: none;
      color: var(--ink); border: 1px solid var(--line-strong);
      border-radius: 999px; padding: 9px 22px;
      background: var(--white);
      transition: border-color .3s, background .3s, color .3s;
    }
    .nav .cta:hover { border-color: var(--coral); color: var(--coral); background: var(--coral-soft); }

    .container { max-width: 1120px; margin: 0 auto; padding: 0 28px; position: relative; z-index: 2; }

    /* ============================================================
       Hero：3D 透视舞台（白色玻璃卡 + 同心圆环）
       ============================================================ */
    .hero {
      position: relative;
      min-height: 100vh;
      display: flex; align-items: center; justify-content: center;
      overflow: hidden;
      z-index: 1;
    }
    /* 同心圆环（圆形纹理，替代网格） */
    .halo {
      position: absolute; left: 50%; top: 52%;
      width: 1280px; height: 1280px;
      transform: translate(-50%, -50%);
      border-radius: 50%;
      background: repeating-radial-gradient(circle at 50% 50%, transparent 0 88px, rgba(24, 28, 41, 0.045) 88px 89px);
      -webkit-mask: radial-gradient(circle, #000 26%, transparent 66%);
      mask: radial-gradient(circle, #000 26%, transparent 66%);
      animation: haloBreath 12s ease-in-out infinite alternate;
      pointer-events: none;
    }
    @keyframes haloBreath {
      from { transform: translate(-50%, -50%) scale(1); }
      to   { transform: translate(-50%, -50%) scale(1.05); }
    }
    .glow {
      position: absolute; left: 50%; top: 52%;
      width: 56vw; height: 46vh;
      transform: translate(-50%, -50%);
      background: radial-gradient(50% 50% at 50% 50%, rgba(232, 90, 79, 0.06), transparent 72%);
      pointer-events: none;
    }

    /* 3D 舞台（鼠标惯性视差） */
    .stage-wrap { position: absolute; inset: 0; perspective: 1100px; pointer-events: none; }
    .stage {
      position: absolute; inset: 0;
      transform-style: preserve-3d;
      will-change: transform;
    }
    .orb {
      position: absolute;
      transform-style: preserve-3d;
      will-change: transform;
    }
    @keyframes bob {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-14px); }
    }
    .chip {
      padding: 10px 18px;
      font-size: 12px; letter-spacing: 2px; white-space: nowrap;
      color: var(--ink);
      background: var(--white);
      border: 1px solid rgba(232, 90, 79, 0.34);
      border-radius: 999px;
      box-shadow: 0 14px 36px rgba(232, 90, 79, 0.12);
      animation: bob 7s ease-in-out infinite;
    }
    .chip b { color: var(--coral); font-weight: 700; }
    /* 各悬浮体的空间位置（不同 Z 深度 → 旋转时产生天然视差） */
    .c1 { left: 12%; top: 26%;  transform: translateZ(160px); }
    .c2 { right: 10%; top: 32%; transform: translateZ(60px); }
    .c3 { right: 16%; bottom: 18%; transform: translateZ(200px); }
    .c2 { animation-delay: -2.4s; }
    .c3 { animation-delay: -5s; }

    /* Hero 文案 */
    .hero-copy { position: relative; text-align: center; z-index: 3; padding: 0 24px; }
    .hero-copy .eyebrow {
      display: inline-flex; align-items: center; gap: 10px;
      font-size: 13px; letter-spacing: 5px; color: var(--gold);
      margin-bottom: 30px;
    }
    .hero-copy .eyebrow::before, .hero-copy .eyebrow::after {
      content: ""; width: 36px; height: 1px;
      background: linear-gradient(90deg, transparent, var(--gold));
    }
    .hero-copy .eyebrow::after { transform: scaleX(-1); }
    .hero-copy h1 {
      font-family: var(--font-display);
      font-size: clamp(46px, 8.4vw, 96px);
      line-height: 1.16;
      font-weight: 900;
      letter-spacing: 6px;
      color: var(--ink);
    }
    .hero-copy h1 .hollow {
      color: transparent;
      -webkit-text-stroke: 1.5px rgba(24, 28, 41, 0.46);
    }
    .hero-copy h1 .free {
      position: relative; color: var(--coral); white-space: nowrap;
    }
    .hero-copy h1 .free::after {
      content: ""; position: absolute; left: 3%; right: 3%; bottom: 7px;
      height: 12px; background: rgba(232, 90, 79, 0.13);
      z-index: -1; border-radius: 2px;
    }
    .hero-copy .zero {
      font-family: var(--font-display);
      margin: 26px 0 10px;
      font-size: clamp(15px, 2vw, 19px);
      letter-spacing: 3px;
      color: var(--ink-dim);
    }
    .hero-copy .zero b {
      color: var(--coral); font-size: 1.5em; font-weight: 900;
      margin: 0 6px; vertical-align: -2px;
    }
    .hero-copy .lead {
      font-size: 15px; line-height: 2; letter-spacing: 1px;
      color: var(--ink-mute);
      max-width: 560px; margin: 0 auto 40px;
    }
    .actions { display: inline-flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
    .btn {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 16px 36px; border-radius: 999px;
      font-size: 14px; font-weight: 600; letter-spacing: 2px;
      text-decoration: none;
      transition: transform .3s var(--ease-out), box-shadow .3s, background .3s, color .3s, border-color .3s;
    }
    .btn-primary {
      background: var(--ink);
      color: #fff;
      box-shadow: 0 12px 32px rgba(24, 28, 41, 0.22);
    }
    .btn-primary:hover { transform: translateY(-3px); box-shadow: 0 18px 44px rgba(24, 28, 41, 0.3); background: var(--ink-soft); }
    .btn-ghost {
      color: var(--ink); border: 1px solid var(--line-strong);
      background: var(--white);
    }
    .btn-ghost:hover { border-color: var(--coral); color: var(--coral); transform: translateY(-3px); }
    .scroll-hint {
      position: absolute; left: 50%; bottom: 30px; transform: translateX(-50%);
      font-size: 11px; letter-spacing: 4px; color: var(--ink-mute);
      display: flex; flex-direction: column; align-items: center; gap: 10px;
      z-index: 3;
    }
    .scroll-hint::after {
      content: ""; width: 1px; height: 38px;
      background: linear-gradient(var(--ink-mute), transparent);
      animation: hintDrop 1.8s ease-in-out infinite;
    }
    @keyframes hintDrop {
      0% { transform: scaleY(0); transform-origin: top; }
      55% { transform: scaleY(1); transform-origin: top; }
      56% { transform-origin: bottom; }
      100% { transform: scaleY(0); transform-origin: bottom; }
    }

    /* ===== 水平跑马灯（细线收边，不倾斜） ===== */
    .band {
      position: relative; z-index: 2;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      background: var(--paper-2);
      overflow: hidden;
      padding: 15px 0;
    }
    .band .track {
      display: flex; gap: 0; white-space: nowrap;
      animation: slide 30s linear infinite;
      width: max-content;
    }
    .band span {
      font-family: var(--font-display);
      font-size: 14px; font-weight: 700; letter-spacing: 4px;
      color: var(--ink-dim);
      padding: 0 28px;
    }
    .band span i { font-style: normal; color: var(--coral); margin-right: 28px; font-weight: 400; }
    @keyframes slide { to { transform: translateX(-50%); } }

    /* ===== 区块通用 ===== */
    .section { position: relative; padding: 120px 0 0; z-index: 2; }
    .sec-head { margin-bottom: 56px; }
    .sec-head .no {
      font-family: var(--font-display);
      font-size: 13px; letter-spacing: 4px; color: var(--coral);
      display: flex; align-items: center; gap: 14px;
      margin-bottom: 18px;
    }
    .sec-head .no::after { content: ""; flex: 0 0 52px; height: 1px; background: var(--coral); opacity: .5; }
    .sec-head h2 {
      font-family: var(--font-display);
      font-size: clamp(30px, 4.4vw, 46px);
      font-weight: 900; letter-spacing: 3px; line-height: 1.3;
    }
    .sec-head .desc {
      margin-top: 14px; font-size: 14px; letter-spacing: 1px;
      line-height: 1.9; color: var(--ink-mute); max-width: 540px;
    }

    /* 3D 滚动入场 */
    .rv {
      opacity: 0;
      transform: perspective(1000px) rotateX(14deg) translateY(50px) translateZ(-50px);
      transform-origin: 50% 100%;
      transition: opacity .9s var(--ease-out), transform 1.15s var(--ease-out);
      transition-delay: var(--d, 0s);
      will-change: transform, opacity;
    }
    .rv.in { opacity: 1; transform: perspective(1000px) none; }

    /* ===== 数据带 ===== */
    .stats {
      display: grid; grid-template-columns: repeat(4, 1fr);
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow-soft);
    }
    .stat {
      padding: 46px 20px;
      text-align: center; position: relative;
    }
    .stat + .stat::before {
      content: ""; position: absolute; left: 0; top: 22%; bottom: 22%;
      width: 1px; background: var(--line);
    }
    .stat .num {
      font-family: var(--font-display);
      font-size: clamp(34px, 4.6vw, 52px); font-weight: 900;
      letter-spacing: 1px; line-height: 1;
      color: var(--ink);
    }
    .stat .num .unit { font-size: 0.42em; color: var(--ink-dim); margin-left: 4px; letter-spacing: 2px; }
    .stat .num.hot { color: var(--coral); }
    .stat .lbl { margin-top: 14px; font-size: 12px; letter-spacing: 3px; color: var(--ink-mute); }

    /* ===== 特性卡（3D 跟随倾斜 + 光泽） ===== */
    .features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; perspective: 1200px; }
    .feature {
      position: relative;
      padding: 40px 32px 36px;
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow-soft);
      transform-style: preserve-3d;
      transition: border-color .4s, box-shadow .4s;
      overflow: hidden;
      will-change: transform;
    }
    .feature::before {
      content: "";
      position: absolute; inset: 0; pointer-events: none;
      background: radial-gradient(420px circle at var(--mx, 50%) var(--my, 0%), rgba(232, 90, 79, 0.05), transparent 44%);
      opacity: 0; transition: opacity .4s;
    }
    .feature:hover { border-color: rgba(232, 90, 79, 0.32); box-shadow: var(--shadow-deep); }
    .feature:hover::before { opacity: 1; }
    .feature .f-no {
      position: absolute; right: 22px; top: 16px;
      font-family: var(--font-display); font-size: 60px; font-weight: 900;
      color: transparent;
      -webkit-text-stroke: 1px rgba(24, 28, 41, 0.1);
      transform: translateZ(30px);
    }
    .feature .icon {
      font-size: 32px; margin-bottom: 22px;
      width: 64px; height: 64px; border-radius: 16px;
      display: flex; align-items: center; justify-content: center;
      background: var(--coral-soft);
      border: 1px solid rgba(232, 90, 79, 0.2);
      transform: translateZ(40px);
    }
    .feature h3 {
      font-family: var(--font-display);
      font-size: 21px; font-weight: 700; letter-spacing: 2px;
      margin-bottom: 12px;
      transform: translateZ(28px);
    }
    .feature p {
      font-size: 13px; line-height: 2; letter-spacing: 0.5px;
      color: var(--ink-mute);
      transform: translateZ(16px);
    }

    /* ===== 品类 3D 旋转环（可拖拽 + 惯性） ===== */
    .ring-section { padding-bottom: 30px; }
    .ring-viewport {
      position: relative; height: 430px;
      perspective: 1300px;
      cursor: grab;
      touch-action: pan-y;
      -webkit-user-select: none; user-select: none;
    }
    .ring-viewport:active { cursor: grabbing; }
    .ring {
      position: absolute; left: 50%; top: 50%;
      transform-style: preserve-3d;
      will-change: transform;
    }
    .panel {
      position: absolute;
      width: 224px; height: 296px;
      left: -112px; top: -148px;
      padding: 30px 24px;
      display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px;
      text-align: center;
      background: var(--white);
      border: 1px solid var(--line);
      border-radius: 20px;
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
      box-shadow: var(--shadow-deep);
    }
    .panel::after {
      content: ""; position: absolute; left: 0; right: 0; top: 0; height: 3px;
      border-radius: 20px 20px 0 0;
      background: linear-gradient(90deg, var(--coral), var(--gold));
      opacity: .65;
      pointer-events: none;
    }
    .panel .ico { font-size: 52px; line-height: 1; }
    .panel .name { font-family: var(--font-display); font-size: 19px; font-weight: 700; letter-spacing: 2px; }
    .panel .meta { font-size: 11.5px; letter-spacing: 1.5px; color: var(--ink-mute); line-height: 1.8; }
    .panel .tag {
      margin-top: 4px; font-size: 11px; letter-spacing: 2px;
      color: var(--coral); border: 1px solid rgba(232, 90, 79, 0.36);
      border-radius: 999px; padding: 4px 14px;
      background: var(--coral-soft);
    }
    .ring-foot {
      text-align: center; margin-top: 8px;
      font-size: 11px; letter-spacing: 4px; color: var(--ink-mute);
    }

    /* ===== 4 步租用（壹贰叁肆） ===== */
    .steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
    .step {
      position: relative;
      padding: 80px 24px 32px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: var(--white);
      box-shadow: var(--shadow-soft);
      overflow: hidden;
      transition: border-color .4s, transform .5s var(--ease-out), box-shadow .4s;
    }
    .step:hover { border-color: rgba(176, 142, 87, 0.4); transform: translateY(-6px); box-shadow: var(--shadow-deep); }
    .step .cn {
      position: absolute; right: 8px; top: -26px;
      font-family: var(--font-display);
      font-size: 120px; font-weight: 900; line-height: 1;
      color: transparent;
      -webkit-text-stroke: 1px rgba(176, 142, 87, 0.28);
      pointer-events: none;
    }
    .step .k {
      display: inline-block;
      font-size: 11px; letter-spacing: 3px; color: var(--gold);
      border: 1px solid rgba(176, 142, 87, 0.36);
      border-radius: 999px; padding: 4px 12px;
      margin-bottom: 16px;
    }
    .step h4 { font-family: var(--font-display); font-size: 19px; font-weight: 700; letter-spacing: 2px; margin-bottom: 10px; }
    .step p { font-size: 12.5px; line-height: 2; letter-spacing: 0.5px; color: var(--ink-mute); }

    /* ===== 安全承诺（全页唯一深色块 + 旋转流光描边） ===== */
    .safety {
      position: relative;
      border-radius: 26px;
      padding: 1px;
      background: linear-gradient(var(--ink), var(--ink)) padding-box,
        conic-gradient(from var(--ga, 0deg), transparent 0 70%, rgba(232, 90, 79, 0.85) 82%, rgba(176, 142, 87, 0.9) 90%, transparent 100%) border-box;
      border: 1px solid transparent;
      box-shadow: 0 40px 90px rgba(24, 28, 41, 0.28);
    }
    @property --ga { syntax: "<angle>"; initial-value: 0deg; inherits: false; }
    @keyframes spinGlow { to { --ga: 360deg; } }
    .safety { animation: spinGlow 7s linear infinite; }
    .safety-in {
      border-radius: 25px;
      color: var(--cream);
      background:
        radial-gradient(60% 90% at 8% 0%, rgba(232, 90, 79, 0.12), transparent 60%),
        linear-gradient(160deg, #1d2233, var(--ink));
      padding: 60px 56px;
      display: grid; grid-template-columns: 1.1fr 1fr; gap: 48px; align-items: center;
    }
    .safety h2 {
      font-family: var(--font-display);
      font-size: clamp(26px, 3.6vw, 38px); font-weight: 900;
      letter-spacing: 3px; line-height: 1.4; margin-bottom: 18px;
    }
    .safety h2 em { font-style: normal; color: #ff8d80; }
    .safety .sp { font-size: 13.5px; line-height: 2.1; letter-spacing: 0.5px; color: rgba(243, 239, 230, 0.55); }
    .safety ul { list-style: none; display: flex; flex-direction: column; gap: 16px; }
    .safety li {
      display: flex; align-items: center; gap: 14px;
      font-size: 14px; letter-spacing: 1px;
      padding: 14px 18px;
      border: 1px solid rgba(243, 239, 230, 0.12);
      border-radius: 14px;
      background: rgba(243, 239, 230, 0.03);
      transition: border-color .3s, transform .3s var(--ease-out);
    }
    .safety li:hover { border-color: rgba(232, 90, 79, 0.5); transform: translateX(6px); }
    .safety li::before {
      content: "✓";
      flex-shrink: 0;
      width: 24px; height: 24px; border-radius: 50%;
      background: rgba(232, 90, 79, 0.2);
      color: #ff8d80;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 12px;
    }

    /* ===== 尾部 CTA ===== */
    .final {
      text-align: center;
      padding: 130px 0 110px;
    }
    .final .zh {
      font-family: var(--font-display);
      font-size: clamp(38px, 6.4vw, 72px); font-weight: 900;
      letter-spacing: 8px; line-height: 1.4;
      margin-bottom: 16px;
    }
    .final .zh b { color: var(--coral); }
    .final .sub { font-size: 14px; letter-spacing: 3px; color: var(--ink-mute); margin-bottom: 40px; }

    /* ===== Footer ===== */
    .footer {
      position: relative; z-index: 2;
      border-top: 1px solid var(--line);
      background: var(--paper-2);
      padding: 56px 0 30px;
    }
    .footer .cols {
      display: grid; grid-template-columns: 1.4fr 1fr 1fr;
      gap: 40px; padding-bottom: 32px;
      border-bottom: 1px solid var(--line);
    }
    .footer .brand-name {
      display: flex; align-items: center; gap: 12px;
      font-family: var(--font-display);
      font-size: 22px; font-weight: 900; letter-spacing: 4px;
      margin-bottom: 12px;
    }
    .footer .brand-name img {
      width: 42px; height: 42px;
      border-radius: 11px;
      border: 1px solid var(--line);
      background: var(--white);
      display: block;
    }
    .footer .brand-tag { font-size: 12.5px; letter-spacing: 1px; color: var(--ink-mute); line-height: 2; }
    .footer h5 { font-size: 12px; font-weight: 700; letter-spacing: 3px; color: var(--ink-dim); margin-bottom: 16px; }
    .footer ul { list-style: none; display: flex; flex-direction: column; gap: 10px; }
    .footer li { font-size: 12.5px; line-height: 1.9; letter-spacing: 0.5px; color: var(--ink-mute); }
    .footer li .k { color: rgba(24, 28, 41, 0.3); margin-right: 8px; }
    .footer .copy { margin-top: 26px; text-align: center; font-size: 11.5px; line-height: 2; letter-spacing: 1px; color: rgba(24, 28, 41, 0.32); }
    .footer .copy .company { color: var(--ink-mute); font-size: 12px; }

    /* ===== 响应式 ===== */
    @media (max-width: 880px) {
      .nav { padding: 14px 20px; }
      .hero { min-height: 92vh; }
      .halo { width: 760px; height: 760px; }
      .c3 { display: none; }
      .c1 { left: 5%; top: 13%; }
      .c2 { right: 4%; top: auto; bottom: 12%; }
      .hero-copy h1 { letter-spacing: 3px; }
      .stats { grid-template-columns: 1fr 1fr; }
      .stat { padding: 30px 12px; }
      .stat:nth-child(3)::before { display: none; }
      .stat:nth-child(n+3) { border-top: 1px solid var(--line); }
      .features { grid-template-columns: 1fr; }
      .ring-viewport { height: 360px; }
      .panel { width: 188px; height: 252px; left: -94px; top: -126px; }
      .panel .ico { font-size: 42px; }
      .steps { grid-template-columns: 1fr 1fr; }
      .safety-in { grid-template-columns: 1fr; padding: 40px 28px; gap: 30px; }
      .section { padding-top: 84px; }
      .footer .cols { grid-template-columns: 1fr; gap: 28px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation: none !important; transition-duration: .01s !important; }
      .rv { opacity: 1; transform: none; }
    }
  </style>
</head>
<body>
  <div class="mist"></div>
  <div class="progress" id="progress"></div>

  <nav class="nav">
    <div class="brand"><img src="/product/asset/landing/icon.png" alt="观澜数码" />观澜数码租赁</div>
    <a class="cta" href="alipays://platformapi/startapp?appId=__ALIPAY_APP_ID__">进入小程序</a>
  </nav>

  <!-- ================= Hero ================= -->
  <header class="hero">
    <div class="halo"></div>
    <div class="glow"></div>

    <div class="stage-wrap">
      <div class="stage" id="stage">
        <div class="orb chip c1"><b>¥0</b>&nbsp;押金 · 芝麻免押</div>
        <div class="orb chip c2"><b>48h</b>&nbsp;顺丰发货</div>
        <div class="orb chip c3">归还后信用<b>自动解冻</b></div>
      </div>
    </div>

    <div class="hero-copy">
      <div class="eyebrow">芝麻信用合作伙伴</div>
      <h1><span class="hollow">3C 数码</span><span class="free">免押租赁</span><br />让设备体验更轻盈</h1>
      <div class="zero">押金<b>¥0</b>· 信用即通行证</div>
      <p class="lead">
        芝麻信用 600 分以上即可免押租用 VR、智能手机、笔记本、摄影器材，
        全程支付宝一站式授权，归还后信用额度自动解冻。
      </p>
      <div class="actions">
        <a class="btn btn-primary" href="alipays://platformapi/startapp?appId=__ALIPAY_APP_ID__">进入支付宝小程序</a>
      </div>
    </div>

    <div class="scroll-hint">向下探索</div>
  </header>

  <!-- ================= 跑马灯 ================= -->
  <div class="band" aria-hidden="true">
    <div class="track" id="track">
      <span><i>◆</i>芝麻免押 · ¥0 押金</span><span><i>◆</i>48H 顺丰直达</span><span><i>◆</i>来去双重验机</span><span><i>◆</i>信用额度自动解冻</span><span><i>◆</i>7×24 客服响应</span>
    </div>
  </div>

  <main class="container">

    <!-- ================= 数据 ================= -->
    <section class="section">
      <div class="stats rv">
        <div class="stat">
          <div class="num hot">¥0</div>
          <div class="lbl">芝麻免押 · 无需冻结现金</div>
        </div>
        <div class="stat">
          <div class="num"><span data-count="48">0</span><span class="unit">小时</span></div>
          <div class="lbl">承诺发货时效</div>
        </div>
        <div class="stat">
          <div class="num">7×24</div>
          <div class="lbl">客服在线响应</div>
        </div>
        <div class="stat">
          <div class="num"><span data-count="360">0</span><span class="unit">天</span></div>
          <div class="lbl">最长授权周期</div>
        </div>
      </div>
    </section>

    <!-- ================= 特性 ================= -->
    <section class="section">
      <header class="sec-head rv">
        <div class="no">壹 / 为什么选我们</div>
        <h2>把租赁的麻烦<br />交给信用</h2>
        <p class="desc">用一次芝麻信用授权，跳过押金、押金退还、邮寄担保等所有繁琐环节。</p>
      </header>
      <div class="features">
        <div class="feature rv tilt" style="--d:.05s">
          <div class="f-no">01</div>
          <div class="icon">⚡</div>
          <h3>无押金租赁</h3>
          <p>芝麻分达标即可免押，下单 → 授权 → 收货一气呵成，无需冻结现金或刷卡。</p>
        </div>
        <div class="feature rv tilt" style="--d:.15s">
          <div class="f-no">02</div>
          <div class="icon">📦</div>
          <h3>顺丰直达</h3>
          <p>下单 48 小时内顺丰发货，超时自动赠送 3 天免租期，到货即享体验。</p>
        </div>
        <div class="feature rv tilt" style="--d:.25s">
          <div class="f-no">03</div>
          <div class="icon">🛡️</div>
          <h3>来去双验</h3>
          <p>发出前商家自检，归还后专业核验，定损标准透明公开，无隐藏扣费。</p>
        </div>
      </div>
    </section>

    <!-- ================= 品类 3D 环 ================= -->
    <section class="section ring-section">
      <header class="sec-head rv">
        <div class="no">贰 / 我们租什么</div>
        <h2>覆盖主流 3C 数码品类</h2>
        <p class="desc">从尝鲜到长期使用，按天计费，长租更优惠。拖拽下方展环查看。</p>
      </header>
      <div class="ring-viewport rv" id="ringViewport">
        <div class="ring" id="ring">
          <div class="panel"><div class="ico">🥽</div><div class="name">VR / 一体机</div><div class="meta">Quest · PICO<br/>Vision Pro</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">📱</div><div class="name">智能手机</div><div class="meta">iPhone · 华为<br/>小米</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">💻</div><div class="name">笔记本电脑</div><div class="meta">MacBook<br/>游戏本</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">📷</div><div class="name">微单相机</div><div class="meta">索尼 · 佳能<br/>富士</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">🎥</div><div class="name">运动相机</div><div class="meta">GoPro<br/>大疆 Action</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">🎙️</div><div class="name">直播声学</div><div class="meta">麦克风<br/>声卡套装</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">🎮</div><div class="name">游戏掌机</div><div class="meta">Switch<br/>Steam Deck</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">🛸</div><div class="name">稳定云台</div><div class="meta">大疆<br/>智云</div><div class="tag">芝麻免押</div></div>
          <div class="panel"><div class="ico">🎸</div><div class="name">吉他乐器</div><div class="meta">民谣 · 电吉他<br/>尤克里里</div><div class="tag">芝麻免押</div></div>
        </div>
      </div>
      <div class="ring-foot rv">— 按住拖动 · 松手惯性滑行 —</div>
    </section>

    <!-- ================= 步骤 ================= -->
    <section class="section">
      <header class="sec-head rv">
        <div class="no">叁 / 四步租用</div>
        <h2>简单到让你怀疑人生</h2>
        <p class="desc">小程序内全流程，平均 3 分钟完成下单到免押授权。</p>
      </header>
      <div class="steps">
        <div class="step rv" style="--d:.05s">
          <div class="cn">壹</div>
          <span class="k">STEP 1</span>
          <h4>选品下单</h4>
          <p>支付宝小程序内浏览商品，选择租期，预览总费用。</p>
        </div>
        <div class="step rv" style="--d:.13s">
          <div class="cn">贰</div>
          <span class="k">STEP 2</span>
          <h4>免押授权</h4>
          <p>实名认证 + 芝麻信用授权，无需冻结现金。</p>
        </div>
        <div class="step rv" style="--d:.21s">
          <div class="cn">叁</div>
          <span class="k">STEP 3</span>
          <h4>商家发货</h4>
          <p>48 小时内顺丰直达，运单号实时同步。</p>
        </div>
        <div class="step rv" style="--d:.29s">
          <div class="cn">肆</div>
          <span class="k">STEP 4</span>
          <h4>到期归还</h4>
          <p>填寄回快递信息，验机通过后信用额度自动解冻。</p>
        </div>
      </div>
    </section>

    <!-- ================= 安全 ================= -->
    <section class="section">
      <header class="sec-head rv">
        <div class="no">肆 / 安全承诺</div>
        <h2>安全 · 透明 · 可追溯</h2>
      </header>
      <div class="safety rv">
        <div class="safety-in">
          <div>
            <h2>每一笔资金<br />都走<em>支付宝原生</em>预授权</h2>
            <p class="sp">扣款 / 退款 / 解冻全程可在支付宝账单查询；定损标准、扣款明细、寄回物流号均在订单页公开，无任何隐藏条款。</p>
          </div>
          <ul>
            <li>实名认证 + 人脸活体校验</li>
            <li>支付宝预授权全程可追溯</li>
            <li>验机标准明示，无隐藏扣费</li>
            <li>客服 9:00–21:00 实时响应</li>
          </ul>
        </div>
      </div>
    </section>

    <!-- ================= 尾部 CTA ================= -->
    <section class="final">
      <div class="zh rv">信用<b>免押</b>，即刻开租</div>
      <div class="sub rv" style="--d:.1s">芝麻信用 600 分 · 3 分钟完成授权</div>
      <div class="actions rv" style="--d:.2s">
        <a class="btn btn-primary" href="alipays://platformapi/startapp?appId=__ALIPAY_APP_ID__">进入支付宝小程序</a>
        <a class="btn btn-ghost" href="tel:__SERVICE_PHONE__">联系客服</a>
      </div>
    </section>

  </main>

  <footer class="footer">
    <div class="container">
      <div class="cols">
        <div>
          <div class="brand-name"><img src="/product/asset/landing/icon.png" alt="观澜数码" />观澜数码租赁</div>
          <div class="brand-tag">3C 数码免押租赁服务平台<br />让数码设备触手可及</div>
        </div>
        <div>
          <h5>服务支持</h5>
          <ul>
            <li><span class="k">客服</span><a href="tel:__SERVICE_PHONE__" style="color:inherit;text-decoration:none">__SERVICE_PHONE__</a></li>
            <li><span class="k">时间</span>周一至周日 9:00-21:00</li>
            <li><span class="k">退换</span>到货 7 天内可申请取消</li>
          </ul>
        </div>
        <div>
          <h5>公司信息</h5>
          <ul>
            <li>__COMPANY_NAME__</li>
            <li><span class="k">地址</span>海南省海口市</li>
          </ul>
        </div>
      </div>
      <div class="copy">
        <div class="company">__COMPANY_NAME__</div>
        <div>© <span id="y"></span> your-domain.example.com · All rights reserved</div>
      </div>
    </div>
  </footer>

  <script>
  (function () {
    document.getElementById('y').textContent = new Date().getFullYear();

    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var finePointer = window.matchMedia('(pointer: fine)').matches;

    /* ---------- 跑马灯：复制一份实现无缝循环 ---------- */
    var track = document.getElementById('track');
    track.innerHTML += track.innerHTML;

    /* ---------- 滚动进度条 ---------- */
    var progress = document.getElementById('progress');
    function onScroll() {
      var h = document.documentElement;
      var p = h.scrollTop / (h.scrollHeight - h.clientHeight || 1);
      progress.style.width = (p * 100) + '%';
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    /* ---------- 3D 翻转入场 ---------- */
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          en.target.classList.add('in');
          io.unobserve(en.target);
        }
      });
    }, { threshold: 0.16, rootMargin: '0px 0px -6% 0px' });
    document.querySelectorAll('.rv').forEach(function (el) { io.observe(el); });

    /* ---------- 数字滚动（缓出三次方，非线性） ---------- */
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        cio.unobserve(en.target);
        var el = en.target, target = +el.getAttribute('data-count'), t0 = null;
        function tick(ts) {
          if (!t0) t0 = ts;
          var t = Math.min((ts - t0) / 1400, 1);
          el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
          if (t < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
      });
    }, { threshold: 0.6 });
    document.querySelectorAll('[data-count]').forEach(function (el) { cio.observe(el); });

    if (reduced) return;

    /* ---------- Hero 3D 舞台：鼠标惯性视差（lerp 弹性追踪） ---------- */
    var stage = document.getElementById('stage');
    if (stage && finePointer) {
      var tx = 0, ty = 0, cx = 0, cy = 0;
      window.addEventListener('pointermove', function (e) {
        tx = (e.clientX / window.innerWidth - 0.5);
        ty = (e.clientY / window.innerHeight - 0.5);
      }, { passive: true });
      (function loop() {
        cx += (tx - cx) * 0.045;
        cy += (ty - cy) * 0.045;
        stage.style.transform = 'rotateY(' + (cx * 13) + 'deg) rotateX(' + (-cy * 9) + 'deg)';
        requestAnimationFrame(loop);
      })();
    }

    /* ---------- 特性卡：3D 跟随倾斜 + 光泽 ---------- */
    if (finePointer) {
      document.querySelectorAll('.tilt').forEach(function (card) {
        card.addEventListener('pointermove', function (e) {
          var r = card.getBoundingClientRect();
          var px = (e.clientX - r.left) / r.width;
          var py = (e.clientY - r.top) / r.height;
          card.style.transform = 'perspective(900px) rotateY(' + ((px - 0.5) * 10) + 'deg) rotateX(' + ((0.5 - py) * 8) + 'deg) translateZ(6px)';
          card.style.setProperty('--mx', (px * 100) + '%');
          card.style.setProperty('--my', (py * 100) + '%');
        });
        card.addEventListener('pointerleave', function () {
          card.style.transform = 'perspective(900px) rotateY(0) rotateX(0)';
        });
      });
    }

    /* ---------- 品类 3D 环：自转 + 拖拽 + 惯性（非线性摩擦衰减） ---------- */
    var viewport = document.getElementById('ringViewport');
    var ring = document.getElementById('ring');
    if (viewport && ring) {
      var panels = ring.querySelectorAll('.panel');
      var N = panels.length;
      var R = window.innerWidth < 880 ? 285 : 365;
      panels.forEach(function (p, i) {
        p.style.transform = 'rotateY(' + (i * 360 / N) + 'deg) translateZ(' + R + 'px)';
      });
      var angle = 0, vel = 0, base = 0.07, dragging = false, lastX = 0;
      viewport.addEventListener('pointerdown', function (e) {
        dragging = true; lastX = e.clientX; vel = 0;
        viewport.setPointerCapture(e.pointerId);
      });
      viewport.addEventListener('pointermove', function (e) {
        if (!dragging) return;
        var dx = e.clientX - lastX; lastX = e.clientX;
        angle += dx * 0.32;
        vel = dx * 0.32;
      });
      function release() { dragging = false; }
      viewport.addEventListener('pointerup', release);
      viewport.addEventListener('pointercancel', release);
      (function spin() {
        if (!dragging) {
          /* 摩擦衰减 → 渐近回到匀速自转 */
          vel = vel * 0.955 + base * 0.045;
          angle += vel;
        }
        ring.style.transform = 'translateZ(-' + R + 'px) rotateY(' + angle + 'deg)';
        requestAnimationFrame(spin);
      })();
    }
  })();
  </script>
</body>
</html>
"""


@bp.get("/")
def home():
    # 公司名 / 客服电话 / 小程序 APPID 跟随后台设置（manager 设置页可改，无需发版）
    from app.settings import get as setting_get
    from markupsafe import escape

    html = (
        _PAGE
        .replace("__COMPANY_NAME__", str(escape(setting_get("company_name") or "")))
        .replace("__SERVICE_PHONE__", str(escape(setting_get("service_phone") or "")))
        .replace("__ALIPAY_APP_ID__", str(escape(setting_get("alipay_app_id") or "")))
    )
    # mimetype 不写 charset，Flask 会自动追加 charset=utf-8，避免双 charset
    return Response(html, mimetype="text/html")
