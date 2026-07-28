const { get, post, request, BASE_URL } = require('../../utils/request.js');
const requireLogin = require('../../utils/login.js');
// 计价 / 日期工具集中在 utils/pricing.js：本页（选租期）和确认订单页（算实付）
// 必须用同一份算法，否则两页显示的金额会对不上。
const pricing = require('../../utils/pricing.js');

const fmtAmount = pricing.fmtAmount;

/** 归一化 onLoad 参数：兼容两种入口
 *  ① 普通跳转：q = { id, days, review }
 *  ② 支付宝「小程序码」扫码：参数常被整串塞进 q.query（URL 编码，如 "id%3D9%26days%3D7"），
 *     需要 decode 后再拆出 id/days。
 *  返回 { id, days, review } 字符串/原值。 */
function _normalizeQuery(q) {
  q = q || {};
  const out = { id: q.id, days: q.days, review: q.review };
  // 小程序码场景：q.query 里是整串 query
  if (q.query) {
    try {
      const raw = decodeURIComponent(q.query);
      raw.split('&').forEach((kv) => {
        const idx = kv.indexOf('=');
        if (idx < 0) return;
        const k = kv.slice(0, idx);
        const v = kv.slice(idx + 1);
        if (out[k] === undefined || out[k] === '') out[k] = v;
      });
    } catch (e) {}
  }
  return out;
}

Page({
  data: {
    p: {},
    // SKU：后端只返回在售的。价格/押金/库存的真相都在这里，商品级同名字段只是兜底。
    // 只有 1 个时不渲染选择行（没得选），但下单照样带它的 sku_id。
    skus: [],
    skuIndex: 0,                 // 当前选中 SKU 在 skus 里的下标
    skuOptionName: 'SKU',        // 选择行标题，后台可改（如"容量"/"版本"/"成色"）
    commentModal: false,
    cmtSubmitting: false,
    cmtUploading: false,
    cmtForm: { stars: 5, content: '', images: [] },

    // 详情页展示的活动满减券（公共接口；含当前用户领取状态）
    // 只做营销展示与领取入口；「用哪张券」是确认订单页的事。
    coupons: [],

    // 规格 + 租期选择抽屉（日历版）
    rentSheet: false,
    // 日历是否展开：默认收起，点「自选租期」才出现。
    // 绝大多数用户用快捷天数就够了，日历常驻会把抽屉撑满、把规格挤出视野。
    calOpen: false,
    allowManualPick: true,       // 是否允许日历手选（运营在后台「系统设置」控制）
    SHIP_DAYS: 3,                // 物流期：起租日起前 3 天免租
    MIN_RENT_DAYS: 3,            // 最少用机天数（不含物流期）
    CAL_MONTHS: 4,               // 日历展示月份数（快捷档位最长 30 天，留足余量给自选租期）
    DEFAULT_RENT_DAYS: 15,       // 抽屉默认预选用机天数
    weekLabels: ['日', '一', '二', '三', '四', '五', '六'],
    calMonths: [],               // [{label, weeks: [[{day, ymd, status, priceText, isShip}, ...7], ...6]}]
    // 顶部快捷天数（用机天数；不含物流期）
    // 快捷租期档位。必须与后台 Products.vue 的 PREVIEW_DAYS 一致：
    // 后台按这些档位填总价反推各段单价，档位对不上会出现「后台定了价、
    // 用户却选不到那个天数」。更长的租期走「自选租期」日历。
    rentPresets: [3, 7, 10, 15, 20, 30],
    activePreset: 15,
    // 扫小程序码带来的预选租期天数（0 = 无预选，用 DEFAULT_RENT_DAYS）
    // 必须在 data 里，让框架托管生命周期 + setData 反应式；写在实例属性上
    // 跨 await（如 requireLogin 跳登录页回来）有丢失风险，且不利于排查。
    preferredRentDays: 0,
    rent: {
      startDate: '',             // YYYY-MM-DD，用户选的起租日
      endDate: '',               // YYYY-MM-DD，用户选的归还日
      startDateShort: '',
      endDateShort: '',
      days: 0,                   // 总天数（含物流）
      shipDays: 3,
      rentDays: 0,               // 用机天数 = days - shipDays
      pricePerDay: 0,
      total: 0,
      breakdown: [],
      deposit: 0,
      saved: 0,
    },
    // 抽屉内浮动提示卡（替代 toast，更视觉化）
    inlineTip: { show: false, kind: '', title: '', body: '' },
    // 分享抽屉
    shareSheet: false,
    // 海报：预览弹层 + 生成结果临时图路径
    posterModal: false,
    posterImg: '',
    posterBusy: false,
    // 定损标准：从 p.damage_standard 派生的视图模型（含 show 开关 + 表头兜底）
    damageStandard: { show: false, title: '定损标准', headers: {}, groups: [], notice: '' },
  },
  onLoad(q) {
    // 兼容普通跳转 + 小程序码扫码（参数可能在 q.query 里 URL 编码）
    const nq = _normalizeQuery(q);
    const id = parseInt(nq.id, 10);
    if (!id) {
      // 没拿到合法商品 id（不再默认 1，避免误显示"商品不存在"）
      my.showToast({ content: '商品参数缺失', type: 'none' });
      return;
    }
    this.loadDetail(id);
    this.loadCoupons();
    this.loadConfig();
    // 从订单详情「去评价」跳过来：?review=1 → 详情拉完后自动打开评价弹层
    if (nq.review === '1') this._autoOpenReview = true;
    // 扫小程序码带租期进来：?days=N → 仅"预选"，不自动弹抽屉
    // 等用户主动点立即租赁时再弹，届时已带预选；避免被打扰。
    const qd = parseInt(nq.days || 0, 10);
    if (qd > 0) this._pendingPreferred = qd;
  },

  /** 拉运营配置：物流免租期等。失败时静默回落到 data 里写死的默认值。 */
  async loadConfig() {
    try {
      const c = await get('/api/service/config', {}, { hideError: true });
      if (c && Number.isFinite(+c.ship_free_days)) {
        this.setData({ SHIP_DAYS: +c.ship_free_days });
      }
      // 默认允许；仅当后端明确返回 false 时关闭手选（兼容老后端无此字段）
      if (c && c.allow_manual_date_pick === false) {
        this.setData({ allowManualPick: false });
      }
    } catch (e) {}
  },

  /** 详情页活动满减券：在售可领或我已领的；按门槛升序展示前几张。
   *  接口公开，未登录也能看；已登录会带 user_held / user_unused / claimable。 */
  async loadCoupons() {
    try {
      const r = await get('/api/coupons', {}, { hideError: true });
      const items = (r && r.list ? r.list : []).map((it) => ({
        ...it,
        thresholdText: fmtAmount(it.threshold),
        discountText: fmtAmount(it.discount),
      }));
      this.setData({ coupons: items });
    } catch (e) {
      this.setData({ coupons: [] });
    }
  },

  openCouponCenter() {
    my.navigateTo({ url: '/pages/coupons/coupons' });
  },

  async onClaimFromDetail(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    if (!(await requireLogin('领取优惠券需要先登录'))) return;
    try {
      await post(`/api/coupons/${id}/claim`, {});
      my.showToast({ content: '领取成功', type: 'success', duration: 1200 });
      this.loadCoupons();
    } catch (err) {}
  },

  openAgreement() {
    my.navigateTo({ url: '/pages/agreement/agreement' });
  },
  async loadDetail(id) {
    try {
      const p = await get('/api/products/' + id);
      // 详情图：后台 real_shots 只保留真实 URL；初始 height=0 表示"还没量过"，
      // axml 退化为 widthFix 撑开占位，onDetailImgLoad 拿到原图比例后写回整数高度。
      if (Array.isArray(p.real_shots)) {
        p.detail_images = p.real_shots
          .map((s) => (s || '').trim())
          .filter((v) => /^(\/|https?:\/\/|data:)/.test(v))
          .map((v) => ({ value: v, height: 0 }));
      }
      // 容器宽 = 屏幕宽（.detail-imgs 横向贴边，没有 padding/margin）
      try {
        const sys = my.getSystemInfoSync();
        this._detailContainerW = Math.floor(Number(sys.windowWidth) || 0);
      } catch (e) { this._detailContainerW = 0; }
      // 默认选中第一个有货的 SKU；全都没货就选第一个（底部按钮会显示"已租罄"）
      const skus = Array.isArray(p.skus) ? p.skus : [];
      this._baseProduct = p;
      const firstIdx = skus.length
        ? Math.max(0, skus.findIndex((s) => (s.stock || 0) > 0))
        : 0;
      const merged = this._mergeSku(p, skus[firstIdx]);
      const damageStandard = this._buildDamageStandard(p && p.damage_standard);
      this.setData({
        p: merged,
        skus,
        skuIndex: firstIdx,
        skuOptionName: (p.sku_option_name || 'SKU'),
        damageStandard,
      });
      // 顺手把分享卡片预加载好，onShareAppMessage 必须同步返回，需要这份缓存
      this._preloadShare(id);
      // 订单详情「去评价」跳过来的，详情拉完后自动弹评价
      if (this._autoOpenReview) {
        this._autoOpenReview = false;
        this.openCommentModal();
      }
      // 扫码带租期进来的：把预选值写进响应式 data（不再自动弹抽屉）
      // 用户点「去免押租」时，_openRentSheet 读这个值预选 N 天
      if (this._pendingPreferred > 0) {
        this.setData({ preferredRentDays: this._pendingPreferred });
        this._pendingPreferred = 0;
      }
    } catch (e) {}
  },

  /** 详情图加载完毕：用原图宽高比 × 容器宽 算"整数 px"高度写回 inline style。
   *  关键：所有图都走同一种取整规则（round），相邻 image 的上下边界都落在
   *  整数物理像素，渲染层不会再因小数取舍切出 1px 缝。 */
  onDetailImgLoad(e) {
    const i = parseInt(e.currentTarget.dataset.i, 10);
    if (Number.isNaN(i)) return;
    const d = (e && e.detail) || {};
    const nw = Number(d.width) || 0;
    const nh = Number(d.height) || 0;
    const cw = this._detailContainerW || 0;
    if (!nw || !nh || !cw) return;
    const h = Math.round(cw * nh / nw);
    const imgs = (this.data.p && this.data.p.detail_images) || [];
    if (!imgs[i] || imgs[i].height === h) return;
    this.setData({ [`p.detail_images[${i}].height`]: h });
  },

  /** 后台 damage_standard → 详情页可直接渲染的视图模型。
   *  - 没配置 / enabled=false / 无 groups → show:false（前端整张卡不渲染）
   *  - "全额买下" 这类强调态走 *_highlight 字段，渲染红色高亮 */
  _buildDamageStandard(raw) {
    const empty = { show: false, title: '定损标准', headers: {}, groups: [], notice: '' };
    if (!raw || typeof raw !== 'object') return empty;
    if (raw.enabled === false) return empty;
    const groups = Array.isArray(raw.groups) ? raw.groups : [];
    const cleanedGroups = groups
      .map((g) => ({
        type: (g && g.type) || '',
        rows: Array.isArray(g && g.rows) ? g.rows.map((r) => ({
          degree: (r && r.degree) || '',
          depreciation: (r && r.depreciation) || '',
          insurance: (r && r.insurance) || '',
          depreciation_highlight: !!(r && r.depreciation_highlight),
          insurance_highlight: !!(r && r.insurance_highlight),
        })) : [],
      }))
      .filter((g) => g.rows.length);
    if (!cleanedGroups.length) return empty;
    const h = (raw.headers && typeof raw.headers === 'object') ? raw.headers : {};
    return {
      show: true,
      title: (raw.title || '定损标准').trim() || '定损标准',
      headers: {
        type: h.type || '磨损类型',
        degree: h.degree || '磨损程度',
        depreciation: h.depreciation || '折旧标准',
        insurance: h.insurance || '安心保标准',
      },
      groups: cleanedGroups,
      notice: (raw.notice || '').trim(),
    };
  },

  async _preloadShare(id) {
    try {
      this._shareInfo = await get('/api/share/products/' + id, {}, { hideError: true });
    } catch (e) {
      this._shareInfo = null;
    }
  },
  onSpec() {
    my.showToast({ content: '规格选择', type: 'none' });
  },
  /** 「去免押租」：只做本页能立刻判定的拦截（下架 / 无货），然后打开规格+租期抽屉。
   *  登录 / 实名 / 地址 / 协议全部下沉到确认订单页 —— 让用户先看清价格再被要求登录，
   *  少一层打断。这些校验后端建单时也各兜一层，前端放行不等于能下单成功。 */
  onRent() {
    const pid = this.data.p.id;
    if (!pid) return;

    // 下架优先于库存
    if ((this.data.p.status || 'on') !== 'on') {
      my.showToast({ content: '该商品已下架，无法下单', type: 'none' });
      return;
    }
    // p.stock 已经是"选中 SKU 的库存"（见 _mergeSku）
    if (!((this.data.p.stock || 0) > 0)) {
      my.showToast({
        content: (this.data.skus || []).length > 1
          ? `该${this.data.skuOptionName}库存不足，请换一个`
          : '该商品库存不足，暂时无法下单',
        type: 'none',
      });
      return;
    }
    this._openRentSheet();
  },

  /** 抽屉点「确认」后：把选定的规格 + 租期交给确认订单页。
   *  只传轻量标识和日期，价格由确认页按现价重新计算（防止抽屉停留期间改价）。 */
  _gotoConfirm(sel) {
    const pid = this.data.p.id;
    const curSku = (this.data.skus || [])[this.data.skuIndex];
    const q = [
      `product_id=${pid}`,
      `sku_id=${curSku ? curSku.id : 0}`,
      `start_date=${sel.startDate}`,
      `end_date=${sel.endDate}`,
      `ship_days=${sel.shipDays}`,
      `days=${sel.days}`,
    ].join('&');
    // 扫码带来的预选租期是一次性的，用过即清（下次进入回到默认天数）
    if (this.data.preferredRentDays) this.setData({ preferredRentDays: 0 });
    my.navigateTo({ url: `/pages/order-confirm/order-confirm?${q}` });
  },

  // ---------- 评价 ----------
  openCommentModal() {
    this.setData({
      commentModal: true,
      cmtForm: { stars: 5, content: '', images: [] },
    });
  },
  closeCommentModal() {
    if (this.data.cmtSubmitting || this.data.cmtUploading) return;
    this.setData({ commentModal: false });
  },
  noop() {},

  // ---------- 评价配图：选图 / 上传 / 移除 / 预览 ----------
  async onPickCmtImages() {
    if (this.data.cmtUploading) return;
    const cur = (this.data.cmtForm.images || []).slice();
    const remain = 9 - cur.length;
    if (remain <= 0) return;
    if (!(await requireLogin('上传图片需要先登录'))) return;

    const picked = await new Promise((resolve) => {
      my.chooseImage({
        count: remain,
        sourceType: ['album', 'camera'],
        success: (r) => resolve((r && (r.apFilePaths || r.tempFilePaths)) || []),
        fail: () => resolve([]),
      });
    });
    if (!picked.length) return;

    this.setData({ cmtUploading: true });
    const app = (typeof getApp === 'function') ? getApp() : null;
    const token = app && app.getToken && app.getToken();

    try {
      for (const filePath of picked) {
        const url = await new Promise((resolve, reject) => {
          my.uploadFile({
            url: BASE_URL + '/api/comments/upload',
            fileType: 'image',
            fileName: 'file',
            filePath,
            header: token ? { Authorization: 'Bearer ' + token } : {},
            success: (res) => {
              try {
                const body = typeof res.data === 'string' ? JSON.parse(res.data) : (res.data || {});
                if (body.code === 0 && body.data && body.data.url) resolve(body.data.url);
                else reject(new Error(body.msg || '上传失败'));
              } catch (e) { reject(new Error('上传响应异常')); }
            },
            fail: (err) => reject(new Error((err && err.errorMessage) || '上传失败')),
          });
        });
        cur.push(url);
        if (cur.length >= 9) break;
      }
      this.setData({ 'cmtForm.images': cur });
    } catch (e) {
      my.showToast({ content: e.message || '上传失败', type: 'fail' });
    } finally {
      this.setData({ cmtUploading: false });
    }
  },
  onRemovePickedImage(e) {
    const i = parseInt(e.currentTarget.dataset.i, 10);
    if (isNaN(i)) return;
    const arr = (this.data.cmtForm.images || []).slice();
    arr.splice(i, 1);
    this.setData({ 'cmtForm.images': arr });
  },
  onPreviewPickedImage(e) {
    const i = parseInt(e.currentTarget.dataset.i, 10) || 0;
    const urls = (this.data.cmtForm.images || []).slice();
    if (!urls.length) return;
    my.previewImage({ urls, current: urls[i] });
  },

  // 评价列表里点击配图 → 调起原生预览（支持滑动 / 保存）
  onPreviewCmtImage(e) {
    const { ci, i } = e.currentTarget.dataset;
    const cmts = (this.data.p && this.data.p.comments) || [];
    const cmt = cmts[parseInt(ci, 10)] || {};
    const urls = (cmt.images || []).slice();
    if (!urls.length) return;
    my.previewImage({ urls, current: urls[parseInt(i, 10) || 0] });
  },

  // ---------- 收藏 ----------
  async onFav() {
    const pid = this.data.p && this.data.p.id;
    if (!pid) return;
    if (this._favBusy) return;
    if (!(await requireLogin('收藏需要先登录'))) return;
    this._favBusy = true;

    // 乐观更新：先翻面 UI，失败再回滚，避免点击没反馈
    const prev = !!this.data.p.favorited;
    this.setData({ 'p.favorited': !prev });

    try {
      const r = await post(`/api/user/favorites/${pid}/toggle`);
      // 后端是真值来源，覆盖一次
      this.setData({ 'p.favorited': !!(r && r.favorited) });
      my.showToast({
        content: r && r.favorited ? '已收藏' : '已取消收藏',
        type: 'success',
        duration: 1200,
      });
    } catch (e) {
      this.setData({ 'p.favorited': prev });
    } finally {
      this._favBusy = false;
    }
  },

  // ---------- 分享 ----------
  /** 点击底部分享按钮：打开自定义抽屉。原生分享面板我们没法改样式，
   * 自己撸一个抽屉，给用户更整洁的目标列表（同时挂复制链接/海报这种小程序
   * 自带能力）。真正的"发到支付宝好友"还得靠 open-type=share 拉起原生流程，
   * 因此抽屉里那个 tile 自身仍是 button[open-type=share]。 */
  onShare() {
    const pid = this.data.p && this.data.p.id;
    if (!pid) return;
    this.setData({ shareSheet: true });
    request(`/api/share/products/${pid}`, {
      method: 'POST',
      data: { channel: 'alipay' },
      hideError: true,
    }).catch(() => {});
  },
  closeShareSheet() {
    if (this.data.shareSheet) this.setData({ shareSheet: false });
  },
  /** 点击 "支付宝好友" tile：button[open-type=share] 同步拉起原生分享，
   * 这里只负责把自家抽屉收起来，避免两层 UI 叠加。 */
  onShareToFriend() {
    this.setData({ shareSheet: false });
  },
  /** 复制链接：用 _shareInfo 里的 path/标题/描述拼一段人话 */
  onCopyLink() {
    const p = this.data.p || {};
    const cached = this._shareInfo || {};
    const title = cached.title || p.name || '观澜数码租赁';
    const desc = cached.desc || (p.min_price ? `¥${p.min_price}/天起` : '芝麻信用免押租赁');
    const path = cached.path || `/pages/product/product?id=${p.id || ''}`;
    const text = `${title}\n${desc}\n${path}`;
    my.setClipboard({
      text,
      success: () => my.showToast({ content: '已复制商品信息', type: 'success', duration: 1500 }),
      fail: () => my.showToast({ content: '复制失败', type: 'fail' }),
    });
    this.setData({ shareSheet: false });
  },
  /** 生成海报：拉分享文案 + 小程序码，离屏 canvas 绘制成图，弹预览供保存到相册。
   *  小程序码可选——拿不到（未上线/域名未白名单）就出"无码海报"，不阻断主流程。 */
  async onSharePoster() {
    if (this.data.posterBusy) return;
    const pid = this.data.p && this.data.p.id;
    if (!pid) {
      my.showToast({ content: '商品信息未加载', type: 'none' });
      return;
    }
    this.setData({ shareSheet: false, posterBusy: true, posterModal: true, posterImg: '' });
    my.showLoading({ content: '生成海报中', mask: true });
    // 行为上报（失败静默，不影响出图）
    request(`/api/share/products/${pid}`, {
      method: 'POST', data: { channel: 'poster' }, hideError: true,
    }).catch(() => {});

    try {
      // 分享文案：onShareAppMessage 已预加载到 _shareInfo；没有就兜底再拉一次
      if (!this._shareInfo) {
        try {
          this._shareInfo = await get('/api/share/products/' + pid, {}, { hideError: true });
        } catch (e) {}
      }
      // 小程序码（可选）
      try {
        const r = await get(`/api/share/products/${pid}/qrcode`, {}, { hideError: true });
        this._shareQrUrl = (r && r.qr_code_url) || '';
      } catch (e) { this._shareQrUrl = ''; }

      const img = await this._drawPoster();
      my.hideLoading();
      if (!img) {
        my.showToast({ content: '海报生成失败，请重试', type: 'none' });
        this.setData({ posterModal: false });
        return;
      }
      this.setData({ posterImg: img });
    } catch (e) {
      my.hideLoading();
      my.showToast({ content: '海报生成失败，请重试', type: 'none' });
      this.setData({ posterModal: false });
    } finally {
      this.setData({ posterBusy: false });
    }
  },

  closePoster() {
    if (this.data.posterModal) this.setData({ posterModal: false });
  },

  /** 保存海报到相册：兼容 saveImageToPhotosAlbum / 老版 saveImage；
   *  被拒授权时给可操作的提示。 */
  onSavePoster() {
    const img = this.data.posterImg;
    if (!img) return;
    const onOk = () => {
      my.showToast({ content: '已保存到相册', type: 'success', duration: 1500 });
      this.setData({ posterModal: false });
    };
    const onFail = () => {
      my.showToast({ content: '保存失败，请在系统设置中允许保存到相册', type: 'none', duration: 2200 });
    };
    if (my.saveImageToPhotosAlbum) {
      my.saveImageToPhotosAlbum({ filePath: img, success: onOk, fail: onFail });
    } else if (my.saveImage) {
      my.saveImage({ url: img, success: onOk, fail: onFail });
    } else {
      my.showToast({ content: '当前环境不支持保存图片', type: 'none' });
    }
  },

  /** 把相对路径补成绝对 URL；http(s)/data 原样返回（封面/小程序码可能两种都有）。 */
  _absUrl(u) {
    u = (u || '').trim();
    if (!u) return '';
    if (/^(https?:|data:)/.test(u)) return u;
    if (u.charAt(0) === '/') return BASE_URL + u;
    return u;
  },

  /** 下载远程图到本地（canvas.drawImage 只认本地路径），连带原图宽高一起返回，
   *  供等比裁剪用。失败返回 { path: '' }（降级占位）。 */
  _loadImage(src) {
    return new Promise((resolve) => {
      if (!src) { resolve({ path: '' }); return; }
      my.getImageInfo({
        src,
        success: (res) => resolve({
          path: (res && (res.path || res.src)) || '',
          width: (res && res.width) || 0,
          height: (res && res.height) || 0,
        }),
        fail: () => resolve({ path: '' }),
      });
    });
  },

  /** 取离屏 canvas 的 2D 节点（新版接口）。拿不到返回 null。 */
  _getPosterCanvasNode() {
    return new Promise((resolve) => {
      try {
        my.createSelectorQuery()
          .select('#posterCanvas')
          .node()
          .exec((res) => resolve((res && res[0] && res[0].node) || null));
      } catch (e) { resolve(null); }
    });
  },

  /** 把图源下成本地图，再转成 2D canvas 可绘制的 Image（带原始宽高，供等比裁剪）。
   *  失败返回 null（调用方走占位，不阻断出图）。 */
  async _loadCanvasImage(canvas, src) {
    const info = await this._loadImage(src);
    if (!info.path || !canvas || !canvas.createImage) return null;
    const img = await new Promise((resolve) => {
      let im;
      try { im = canvas.createImage(); } catch (e) { resolve(null); return; }
      im.onload = () => resolve(im);
      im.onerror = () => resolve(null);
      im.src = info.path;
    });
    if (!img) return null;
    return { img, width: info.width || img.width || 0, height: info.height || img.height || 0 };
  },

  /** 等比铺满式绘制（object-fit: cover）：图按比例缩放到刚好盖住目标框，
   *  居中放置，多出的部分靠调用方预先 clip 的路径裁掉。无宽高信息时退化为拉满。 */
  _drawImageCover(ctx, img, x, y, w, h) {
    const iw = img.width, ih = img.height;
    if (!iw || !ih) { ctx.drawImage(img.img, x, y, w, h); return; }
    const scale = Math.max(w / iw, h / ih);
    const dw = iw * scale;
    const dh = ih * scale;
    const dx = x + (w - dw) / 2;
    const dy = y + (h - dh) / 2;
    ctx.drawImage(img.img, dx, dy, dw, dh);
  },

  /** 等比内嵌式绘制（object-fit: contain）：图按比例缩放到刚好放进目标框、居中，
   *  不裁不拉伸 → 二维码保持正方、不变形。无宽高信息时退化为铺满目标框。 */
  _drawImageContain(ctx, img, x, y, w, h) {
    const iw = img.width, ih = img.height;
    if (!iw || !ih) { ctx.drawImage(img.img, x, y, w, h); return; }
    const scale = Math.min(w / iw, h / ih);
    const dw = iw * scale;
    const dh = ih * scale;
    const dx = x + (w - dw) / 2;
    const dy = y + (h - dh) / 2;
    ctx.drawImage(img.img, dx, dy, dw, dh);
  },

  /** 按容器宽折行；超出 maxLines 时末行加省略号。返回行数组。 */
  _wrapText(ctx, text, maxWidth, maxLines) {
    const chars = (text || '').split('');
    const lines = [];
    let cur = '';
    for (let i = 0; i < chars.length; i++) {
      const test = cur + chars[i];
      if (ctx.measureText(test).width > maxWidth && cur) {
        if (lines.length === maxLines - 1) {
          // 已是最后一行，余下字符放不下 → 截断 + 省略号
          cur = test;
          while (cur && ctx.measureText(cur + '…').width > maxWidth) cur = cur.slice(0, -1);
          cur += '…';
          break;
        }
        lines.push(cur);
        cur = chars[i];
      } else {
        cur = test;
      }
    }
    if (cur) lines.push(cur);
    return lines;
  },

  /** 在 ctx 上构建一条圆角矩形路径（不填充/描边，交给调用方 clip/fill）。 */
  _roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arc(x + w - r, y + r, r, -Math.PI / 2, 0);
    ctx.lineTo(x + w, y + h - r);
    ctx.arc(x + w - r, y + h - r, r, 0, Math.PI / 2);
    ctx.lineTo(x + r, y + h);
    ctx.arc(x + r, y + h - r, r, Math.PI / 2, Math.PI);
    ctx.lineTo(x, y + r);
    ctx.arc(x + r, y + r, r, Math.PI, Math.PI * 1.5);
    ctx.closePath();
  },

  /** 截 2D 画布为临时图，返回本地路径；失败返回 ''。
   *  画布缓冲已是「逻辑尺寸 × dpr」，直接整张导出即为高清，无需再放大。 */
  _canvasToTemp(canvas) {
    return new Promise((resolve) => {
      if (!canvas || !canvas.toTempFilePath) { resolve(''); return; }
      canvas.toTempFilePath({
        fileType: 'png', quality: 1,
        success: (res) => resolve((res && (res.apFilePath || res.tempFilePath || res.filePath)) || ''),
        fail: () => resolve(''),
      });
    });
  },

  /** 新版 2D 画布绘制海报。坐标系用逻辑像素，自上而下流式排版；
   *  画布缓冲设为「逻辑尺寸 × dpr」并 scale(dpr)，→ 真高清（旧 createCanvasContext 做不到）。
   *  先量文字算出实际高度，再定缓冲尺寸 → 无中部空白；二维码等比内嵌 → 不压扁。 */
  async _drawPoster() {
    const p = this.data.p || {};
    const info = this._shareInfo || {};
    const W = 375, PAD = 18;
    const cardW = W - PAD * 2;
    const lineH = 26;
    const coverY = PAD;
    const coverH = Math.round(cardW * 0.72);
    const qrSize = 90;
    const font = (px, bold) => (bold ? 'bold ' : '') + px + 'px sans-serif';

    // 拿 2D 画布节点（旧机型/低版本拿不到则失败，由调用方提示重试）
    const canvas = await this._getPosterCanvasNode();
    if (!canvas || !canvas.getContext) return '';
    const ctx = canvas.getContext('2d');

    // 封面 + 小程序码并行下载并转成 canvas Image（拿不到走占位）
    const coverSrc = info.image_url || p.cover_url || ((p.covers || [])[0]) || '';
    const [cover, qr] = await Promise.all([
      this._loadCanvasImage(canvas, this._absUrl(coverSrc)),
      this._loadCanvasImage(canvas, this._absUrl(this._shareQrUrl)),
    ]);

    // —— 第一步：量标题行数，推算实际内容高度 ——（设置缓冲尺寸会清空上下文，故先量）
    const title = (info.title || p.name || '好物推荐').trim();
    ctx.font = font(19);
    const lines = this._wrapText(ctx, title, cardW, 2);

    let h = coverY + coverH + 22;     // 封面下沿
    h += lines.length * lineH + 14;   // 标题
    h += 46;                          // 价格
    h += 26 + 22;                     // 徽章
    h += 20;                          // 分隔线
    const qrY = h;
    const contentH = qrY + qrSize + PAD;

    // —— 第二步：按 dpr 放大缓冲并缩放上下文 ——（此后坐标仍按逻辑像素）
    let dpr = 3;
    try {
      const sys = my.getSystemInfoSync && my.getSystemInfoSync();
      dpr = Math.min(Math.max((sys && sys.pixelRatio) || 3, 2), 3);
    } catch (e) {}
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(contentH * dpr);
    ctx.scale(dpr, dpr);

    // 背景
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, contentH);

    // 封面（圆角裁剪 + 等比铺满，溢出由 clip 裁掉，不拉伸变形）
    ctx.save();
    this._roundRect(ctx, PAD, coverY, cardW, coverH, 14);
    ctx.clip();
    if (cover) {
      this._drawImageCover(ctx, cover, PAD, coverY, cardW, coverH);
    } else {
      ctx.fillStyle = '#eef1f6';
      ctx.fillRect(PAD, coverY, cardW, coverH);
    }
    ctx.restore();

    let y = coverY + coverH + 22;

    // 商品名（最多两行）
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#1a1f2e';
    ctx.font = font(19);
    lines.forEach((ln, i) => ctx.fillText(ln, PAD, y + i * lineH));
    y += lines.length * lineH + 14;

    // 价格：¥ + 大数字 + /天起
    const price = fmtAmount(p.min_price || 0);
    ctx.fillStyle = '#ff4d4f';
    ctx.font = font(16);
    ctx.fillText('¥', PAD, y + 13);
    const symW = ctx.measureText('¥').width;
    ctx.font = font(30, true);
    ctx.fillText(price, PAD + symW + 2, y);
    const priceW = ctx.measureText(price).width;
    ctx.fillStyle = '#9aa4b2';
    ctx.font = font(13);
    ctx.fillText('/天起', PAD + symW + 2 + priceW + 4, y + 15);
    y += 46;

    // 品牌徽章：芝麻信用 · 免押金租赁
    const chipText = '芝麻信用 · 免押金租赁';
    ctx.font = font(12);
    const chipH = 26;
    const chipPadX = 12;
    const chipW = ctx.measureText(chipText).width + chipPadX * 2;
    this._roundRect(ctx, PAD, y, chipW, chipH, 13);
    ctx.fillStyle = '#fff6e9';
    ctx.fill();
    ctx.fillStyle = '#c87a18';
    ctx.textBaseline = 'middle';
    ctx.fillText(chipText, PAD + chipPadX, y + chipH / 2 + 1);
    ctx.textBaseline = 'top';
    y += chipH + 22;

    // 分隔线（紧跟内容，不再吊在底部）
    ctx.strokeStyle = '#eef1f6';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD, y);
    ctx.lineTo(W - PAD, y);
    ctx.stroke();
    y += 20;

    // 底部：右侧小程序码 + 左侧引导文案（同一行块，垂直居中）
    const qrX = W - PAD - qrSize;
    if (qr) {
      // 等比内嵌，保持二维码正方、不压扁
      this._drawImageContain(ctx, qr, qrX, y, qrSize, qrSize);
    } else {
      ctx.fillStyle = '#f4f7fb';
      ctx.fillRect(qrX, y, qrSize, qrSize);
      ctx.fillStyle = '#aab2c0';
      ctx.font = font(11);
      ctx.textAlign = 'center';
      ctx.fillText('小程序码', qrX + qrSize / 2, y + qrSize / 2 - 6);
      ctx.textAlign = 'left';
    }
    ctx.fillStyle = '#1a1f2e';
    ctx.font = font(15);
    ctx.fillText('长按识别小程序码', PAD, y + qrSize / 2 - 20);
    ctx.fillStyle = '#9aa4b2';
    ctx.font = font(12);
    const tip = this._wrapText(ctx, '扫码查看详情 · 芝麻信用免押租', qrX - PAD - 12, 2);
    tip.forEach((ln, i) => ctx.fillText(ln, PAD, y + qrSize / 2 + 4 + i * 18));

    // 2D 画布绘制是同步的，直接导出（已是高分缓冲，整张即高清）
    return this._canvasToTemp(canvas);
  },

  /** 支付宝小程序：右上角菜单 / open-type=share 触发，必须同步返回。
   *  _shareInfo 在 loadDetail 时已预加载；兜底用 p 自己拼一份。 */
  onShareAppMessage() {
    const p = this.data.p || {};
    const cached = this._shareInfo;
    if (cached && cached.title) {
      return {
        title: cached.title,
        desc: cached.desc,
        path: cached.path,
        imageUrl: cached.image_url,
      };
    }
    return {
      title: p.name || '观澜数码租赁',
      desc: p.min_price ? `¥${p.min_price}/天起` : '芝麻信用免押租赁',
      path: `/pages/product/product?id=${p.id || ''}`,
      imageUrl: p.cover_url || '',
    };
  },

  onPickStar(e) {
    const v = parseInt(e.currentTarget.dataset.v, 10) || 5;
    this.setData({ 'cmtForm.stars': v });
  },
  onCmtInput(e) {
    this.setData({ 'cmtForm.content': e.detail.value });
  },
  async submitComment() {
    if (this.data.cmtSubmitting) return;
    const pid = this.data.p && this.data.p.id;
    if (!pid) return;
    const content = (this.data.cmtForm.content || '').trim();
    if (!content) {
      my.showToast({ content: '请填写评价内容', type: 'none' });
      return;
    }
    if (!(await requireLogin('评价需要先登录'))) return;
    this.setData({ cmtSubmitting: true });
    try {
      await post('/api/comments', {
        product_id: pid,
        stars: this.data.cmtForm.stars,
        content,
        images: (this.data.cmtForm.images || []).slice(),
      });
      this.setData({ commentModal: false });
      my.showToast({ content: '已发布', type: 'success' });
      // 重新拉一次详情，把新评论 + total 刷上去
      await this.loadDetail(pid);
    } catch (e) {
      // request.js 已 toast，业务错就静默
    } finally {
      this.setData({ cmtSubmitting: false });
    }
  },

  // ---------- 规格 + 租期选择（日历抽屉） ----------
  /** 打开抽屉：渲染日历 + 默认按 DEFAULT_RENT_DAYS 天预选。
   *  抽屉只负责「选」，选完把结果交给确认订单页，不在这里建单、不在这里选券。 */
  _openRentSheet() {
    const p = this.data.p || {};
    // 扫码带来的预选租期优先（在 data 里，跨 await 不丢）；否则用默认天数
    const def = this.data.preferredRentDays || this.data.DEFAULT_RENT_DAYS;
    const sel = this._rangeForRentDays(def);
    this.setData({
      rentSheet: true,
      calOpen: false,               // 每次打开都从"快捷天数"态开始
      rent: this._calcRent(sel.start, sel.end, p),
      activePreset: def,
      calMonths: this._buildCalendar(p, sel.start, sel.end),
    });
  },

  /** 「自选租期」：展开 / 收起日历。
   *  展开时取消快捷天数的高亮，让用户清楚当前是在手选区间。
   *  运营关掉手选时日历只读，天数仍由快捷条决定，所以保留原高亮不清。 */
  onCustomRange() {
    if (this.data.calOpen) {
      this.setData({ calOpen: false });
      return;
    }
    this.setData(this.data.allowManualPick
      ? { calOpen: true, activePreset: 0 }
      : { calOpen: true });
  },

  /** 给定用机天数 → 一组起讫日（酒店式语义：end = 归还日，不计入用机/计费）
   *  起租=今天；归还日 = 今天 + 物流期 + 用机天数（即最后用机日的次日）。
   *  例：物流 3 天 + 用机 3 天 → 起租 D，用机 D+3~D+5，归还 D+6。 */
  _rangeForRentDays(rentDays) {
    return pricing.rangeForRentDays(rentDays, this.data.SHIP_DAYS);
  },

  /** 顶部快捷预设点击 */
  onPresetTap(e) {
    const d = parseInt(e.currentTarget.dataset.d, 10);
    if (!d) return;
    const p = this.data.p || {};
    const sel = this._rangeForRentDays(d);
    const rent = this._calcRent(sel.start, sel.end, p);
    this.setData({
      rent,
      activePreset: d,
      // 用快捷天数选定了区间，日历没必要再占着屏幕
      calOpen: false,
      calMonths: this._buildCalendar(p, sel.start, sel.end),
    });
  },

  /** 渲染 N 个月日历，从今天所在月起；start/end 是已选区间（可空） */
  _buildCalendar(p, start, end) {
    const N = this.data.CAL_MONTHS || 2;
    const today0 = new Date();
    today0.setHours(0, 0, 0, 0);
    const months = [];
    for (let i = 0; i < N; i++) {
      const base = new Date(today0.getFullYear(), today0.getMonth() + i, 1);
      months.push(this._buildMonth(base, today0, p, start, end));
    }
    return months;
  },

  _buildMonth(monthDate, today0, p, start, end) {
    const y = monthDate.getFullYear();
    const m = monthDate.getMonth();
    const firstWeek = new Date(y, m, 1).getDay();         // 0 = Sun
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const startD = start ? this._parseDate(start) : null;
    const endD = end ? this._parseDate(end) : null;
    const ship = this.data.SHIP_DAYS;
    const minRent = this.data.MIN_RENT_DAYS;
    // 待选归还日的最早允许时间戳：起租 + 物流 + 最少租期（归还日 = 最后用机日次日）
    const minEndTs = startD && !endD
      ? startD.getTime() + (ship + minRent) * 86400000
      : 0;
    const tiers = this._tiersOf(p);

    const slots = Math.ceil((firstWeek + daysInMonth) / 7) * 7;
    const cells = [];
    for (let i = 0; i < slots; i++) {
      const dayNum = i - firstWeek + 1;
      if (dayNum < 1 || dayNum > daysInMonth) {
        cells.push({ empty: true });
        continue;
      }
      const d = new Date(y, m, dayNum);
      const ymd = this._fmtDate(d);
      let status = d < today0 ? 'disabled' : 'normal';
      let priceText = '';
      let isShip = false;
      let endDisabled = false;
      if (status !== 'disabled' && startD) {
        const dt = d.getTime();
        if (dt === startD.getTime()) status = endD ? 'start' : 'start-only';
        else if (endD && dt === endD.getTime()) status = 'end';
        else if (endD && dt > startD.getTime() && dt < endD.getTime()) status = 'mid';
        // 价格/物流标在"持有日"上（起租 ~ 归还日前一天）；归还日(=endD)不计费不标价
        if (dt >= startD.getTime() && (!endD || dt < endD.getTime())) {
          const dayIndex = Math.round((dt - startD.getTime()) / 86400000) + 1;
          if (dayIndex <= ship) {
            priceText = '物流';
            isShip = true;
          } else {
            priceText = '¥' + this._unitPriceForRentDay(dayIndex - ship, tiers);
          }
        }
        // 等待用户选归还日：起租之后、但还不够 物流期 + 最少租期 的格子，禁用为归还日
        if (!endD && dt > startD.getTime() && dt < minEndTs) {
          endDisabled = true;
        }
      }
      // "最早可还"提示：未选归还日时，把恰好 = minEndTs 的那天标出来引导用户
      const isEarliestEnd = !!startD && !endD
        && status === 'normal'
        && d.getTime() === minEndTs;
      cells.push({ day: dayNum, ymd, status, priceText, isShip, endDisabled, isEarliestEnd });
    }
    const weeks = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
    return { label: `${y}年${m + 1}月`, weeks };
  },

  /** 商品 + 选中 SKU → 合并后的展示对象。
   *  把 SKU 的「价格 / 押金 / 库存 / 分段租金」盖到商品同名字段上，这样详情页
   *  原有的 p.min_price、p.deposit_amount、p.stock 绑定和 _calcRent / _tiersOf
   *  全部不用改，就自然按选中的 SKU 走。
   *  SKU 被全部下架的极端情况下原样返回商品，退回商品级兜底值。 */
  _mergeSku(base, sku) {
    if (!base || !sku) return base;
    return Object.assign({}, base, {
      price_tiers:    sku.price_tiers,
      min_price:      sku.min_price,
      deposit_amount: sku.deposit_amount,
      stock:          sku.stock,
    });
  },

  /** 切换 SKU：重算可读租金行 + 折线图；抽屉开着时连租金/押金/可用券一起刷新 */
  onSkuTap(e) {
    const i = parseInt(e.currentTarget.dataset.i, 10);
    const skus = this.data.skus || [];
    if (Number.isNaN(i) || !skus[i] || i === this.data.skuIndex) return;
    const merged = this._mergeSku(this._baseProduct, skus[i]);
    this.setData({ p: merged, skuIndex: i }, () => {
      if (!this.data.rentSheet) return;
      // 抽屉开着时换规格：租金/押金/日历标价都要跟着变
      const r = this.data.rent || {};
      this.setData({
        rent: this._calcRent(r.startDate, r.endDate, merged),
        calMonths: this._buildCalendar(merged, r.startDate, r.endDate),
      });
    });
  },

  // 以下几个是 utils/pricing.js 的薄转发：保留方法名让日历渲染等调用点不用改，
  // 同时保证算法只有一份（确认订单页用的是同一个模块）。
  _tiersOf(p) { return pricing.tiersOf(p); },
  _unitPriceForRentDay(rentDay, tiers) { return pricing.unitPriceForRentDay(rentDay, tiers); },

  /** 点击日历格子：第一次选起租日；第二次若晚于起租 → 归还日，否则重置为起租 */
  onCalDayTap(e) {
    // 运营关闭了"手动选择"时，日历仅展示，不响应点选
    if (!this.data.allowManualPick) {
      this._showInlineTip('info', '请使用上方快捷天数', '当前仅支持用顶部固定天数选择租期');
      return;
    }
    const ymd = e.currentTarget.dataset.ymd;
    if (!ymd) return;
    const p = this.data.p;
    const cur = this.data.rent;
    const ship = this.data.SHIP_DAYS;
    const minRent = this.data.MIN_RENT_DAYS;
    let start = cur.startDate, end = cur.endDate;
    if (!start || (start && end)) {
      // 第一次或已完成一次选择 → 重新开始
      start = ymd; end = '';
    } else {
      // 已选起租，未选归还
      const sd = this._parseDate(start).getTime();
      const cd = this._parseDate(ymd).getTime();
      if (cd <= sd) {
        start = ymd; end = '';
      } else {
        const minEndTs = sd + (ship + minRent) * 86400000;
        if (cd < minEndTs) {
          const earliest = this._addDays(start, ship + minRent);
          this._showInlineTip(
            'warn',
            '这天太早，不能作为归还日',
            `前 ${ship} 天是物流期免租，还需至少 ${minRent} 天用机；最早归还日是 ${this._formatDateShort(earliest)}`,
          );
          return;
        }
        end = ymd;
      }
    }
    // 日历只能从「自选租期」进入，所以点选期间一直保持自选态：
    // 不再把恰好等于某个预设的天数回高亮到快捷条上（那会让「自选租期」看起来没选中）
    this.setData({
      rent: this._calcRent(start, end, p),
      activePreset: 0,
      calMonths: this._buildCalendar(p, start, end),
    });
  },

  _fmtDate(d) { return pricing.fmtDate(d); },
  _parseDate(s) { return pricing.parseDate(s); },
  _addDays(start, days) { return pricing.addDays(start, days); },
  _formatDateShort(s) { return pricing.formatDateShort(s); },

  /** 起讫日 → 全套金额计算；前 SHIP_DAYS 天物流期免租，剩余按 tier 算。
   *  额外补一个 deliverShort 给抽屉底部的送达提示条用：物流期最后一天即签收日
   *  （次日开始计费），与确认订单页时间轴的「签收」是同一个日期。 */
  _calcRent(start, end, p) {
    const r = pricing.calcRent(start, end, p, this.data.SHIP_DAYS);
    r.deliverShort = (r.startDate && r.endDate && r.rentDays > 0)
      ? pricing.formatDateShort(pricing.addDays(r.startDate, Math.max(0, r.shipDays - 1)))
      : '';
    return r;
  },

  /** 抽屉内可视化提示：kind=warn|info；3.5s 后自动收起 */
  _showInlineTip(kind, title, body) {
    this.setData({ inlineTip: { show: true, kind, title, body } });
    if (this._tipTimer) clearTimeout(this._tipTimer);
    this._tipTimer = setTimeout(() => {
      this.setData({ 'inlineTip.show': false });
      this._tipTimer = null;
    }, 3500);
  },

  closeRentSheet() {
    if (!this.data.rentSheet) return;
    if (this._tipTimer) { clearTimeout(this._tipTimer); this._tipTimer = null; }
    this.setData({ rentSheet: false, calOpen: false, 'inlineTip.show': false });
  },
  confirmRentSheet() {
    const r = this.data.rent;
    const minRent = this.data.MIN_RENT_DAYS;
    const ship = this.data.SHIP_DAYS;
    // 抽屉内可以切换规格，可能切到无货的那个（无货项刻意保持可点，好让用户看到它的价格）。
    // 拦在这里，别让用户跑到确认页才被告知没货。
    if (!((this.data.p.stock || 0) > 0)) {
      this._showInlineTip(
        'warn',
        '该规格暂时无货',
        (this.data.skus || []).length > 1
          ? `请在上方换一个有货的${this.data.skuOptionName}`
          : '该商品库存不足，暂时无法下单',
      );
      return;
    }
    if (!r.startDate || !r.endDate) {
      this._showInlineTip(
        'info',
        r.startDate ? '还差归还日没选' : '请先选择起租日',
        r.startDate
          ? `已选起租 ${r.startDateShort}，请在日历上点选一个归还日`
          : '在下方日历上点选起租日，再点选归还日',
      );
      return;
    }
    if (r.rentDays < minRent) {
      // 自动算出"最早可还"日期，作为引导（归还日 = 最后用机日次日）
      const earliest = this._addDays(r.startDate, ship + minRent);
      this._showInlineTip(
        'warn',
        '租期太短',
        `物流期 ${ship} 天免租后，至少再租 ${minRent} 天；归还日请选 ${this._formatDateShort(earliest)} 起`,
      );
      return;
    }
    this.setData({ rentSheet: false, 'inlineTip.show': false });
    if (this._tipTimer) { clearTimeout(this._tipTimer); this._tipTimer = null; }
    this._gotoConfirm({
      days: r.rentDays,
      shipDays: r.shipDays,
      startDate: r.startDate,
      endDate: r.endDate,
    });
  }
});
