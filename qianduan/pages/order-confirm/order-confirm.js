/** 确认订单页
 *
 *  职责边界：商品详情页只负责「选规格 + 选租期」，选完把结果带到这里；
 *  凡是跟钱、跟履约有关的确认动作（地址、优惠券、备注、协议、下单）全部收拢在本页。
 *
 *  参数走 URL query 而不是 globalData：页面可刷新、返回栈异常也不丢，
 *  且从登录页/地址页回来时不需要上一页配合回填。
 *    ?product_id= &sku_id= &start_date= &end_date= &ship_days= &days=
 *
 *  金额口径：query 只带日期，价格一律用本页重新拉的商品/SKU 现价算，
 *  最终仍以后端建单时的计算为准（前端传什么金额后端都不认）。
 */
const { get, post } = require('../../utils/request.js');
const requireLogin = require('../../utils/login.js');
const requireRealName = require('../../utils/realname.js');
const pricing = require('../../utils/pricing.js');

const PICKED_ADDR_KEY = 'picked_address';

// district 可能为空（仙桃/潜江/天门等省直管县级市），拼接时过滤掉空段
function withFull(a) {
  if (!a) return a;
  return { ...a, _full: [a.province, a.city, a.district, a.detail].filter(Boolean).join(' ') };
}

Page({
  data: {
    loaded: false,
    fatal: '',                 // 致命错误文案（商品不存在/已下架/无库存）→ 禁止下单
    p: {},                     // 商品（已并入选中 SKU 的价格/押金/库存）
    sku: null,                 // 选中 SKU；单 SKU 商品也有值，无 SKU 的极端情况为 null
    cover: '',
    rent: {},                  // pricing.calcRent 结果
    timeline: null,            // 四点租赁日期时间轴
    addr: null,                // 收货地址（默认地址，或用户从地址页回选的）
    addrLoaded: false,

    couponList: [],
    pickedCoupon: {},
    couponSheet: false,

    remark: '',                // 用户备注（提交给商家）
    remarkSheet: false,
    remarkDraft: '',

    agreed: false,
    agreeSheet: false,         // 未勾协议点下单时弹出的确认层

    feeSheet: false,           // 底部实付明细展开
    submitting: false,

    freezeIncludesRent: true,  // 新订单固定：押金+租金一次综合授权
    depositNote: '',           // 押金卡说明，按冻结口径在 _recalcFee 里拼
    // 全部预格式化，axml 不做运算
    fee: {
      rentText: '0', discountText: '0', depositText: '0',
      payRentText: '0', freezeText: '0', savedText: '0',
    },
  },

  onLoad(q) {
    const nq = {
      product_id: parseInt((q && q.product_id) || 0, 10),
      sku_id:     parseInt((q && q.sku_id) || 0, 10),
      start_date: ((q && q.start_date) || '').trim(),
      end_date:   ((q && q.end_date) || '').trim(),
      ship_days:  parseInt((q && q.ship_days) || 0, 10),
      days:       parseInt((q && q.days) || 0, 10),
    };
    this._q = nq;
    if (!nq.product_id || !nq.start_date || !nq.end_date) {
      this.setData({ loaded: true, fatal: '订单参数缺失，请返回商品页重新选择租期' });
      return;
    }
    this.loadAll();
  },

  onShow() {
    // 从地址列表「选择模式」回来：读一次并立即清掉，避免下次进页面复用旧值
    let picked = null;
    try {
      const r = my.getStorageSync({ key: PICKED_ADDR_KEY });
      picked = (r && r.data) || null;
      if (picked) my.removeStorageSync({ key: PICKED_ADDR_KEY });
    } catch (e) {}
    if (picked && picked.id) {
      this.setData({ addr: withFull(picked), addrLoaded: true });
      return;
    }
    // 首屏由 loadAll 负责；之后每次回到本页都重拉地址
    // （用户可能去地址页新增/删除/改了默认地址）
    if (this.data.loaded) this.loadAddress();
  },

  async loadAll() {
    // 运营配置：只取展示口径，失败静默走默认值
    try {
      const c = await get('/api/service/config', {}, { hideError: true });
      this.setData({ freezeIncludesRent: true });
    } catch (e) {}

    if (!(await this.loadProduct())) {
      this.setData({ loaded: true });
      return;
    }
    this.setData({ loaded: true });
    // 地址 + 优惠券都需要登录，失败不阻断页面（用户仍能看清租期与价格），
    // 真正的登录拦截放在「确认下单」那一步，避免一进页面就弹窗打断。
    this.loadAddress();
    this.loadCoupons();
  },

  /** 拉商品 + 选中 SKU，重算租金。返回 false 表示出了不能下单的硬错误。 */
  async loadProduct() {
    const q = this._q;
    let p;
    try {
      p = await get('/api/products/' + q.product_id);
    } catch (e) {
      this.setData({ fatal: '商品信息加载失败，请返回重试' });
      return false;
    }
    if (!p || !p.id) {
      this.setData({ fatal: '商品不存在或已删除' });
      return false;
    }
    if ((p.status || 'on') !== 'on') {
      this.setData({ fatal: '该商品已下架，无法下单' });
      return false;
    }

    // SKU 归位：价格/押金/库存的真相在 SKU 层，与详情页 _mergeSku 同口径
    const skus = Array.isArray(p.skus) ? p.skus : [];
    let sku = null;
    if (skus.length) {
      sku = skus.find((s) => s.id === q.sku_id)
        || (skus.length === 1 ? skus[0] : null);
      if (!sku) {
        this.setData({ fatal: '所选规格已失效，请返回重新选择' });
        return false;
      }
    }
    const merged = sku ? Object.assign({}, p, {
      price_tiers:    sku.price_tiers,
      price_curve:    sku.price_curve,
      min_price:      sku.min_price,
      deposit_amount: sku.deposit_amount,
      stock:          sku.stock,
    }) : p;

    if (!((merged.stock || 0) > 0)) {
      this.setData({ fatal: skus.length > 1 ? '该规格库存不足，请返回换一个' : '该商品库存不足，暂时无法下单' });
      return false;
    }

    // 物流期用 query 带来的值（= 用户在详情页选租期时的口径）。
    // 若中途运营改了 ship_free_days，不应让用户在确认页看到金额突变；
    // 该值会随下单一起提交，后端落快照。
    const ship = q.ship_days;
    const rent = pricing.calcRent(q.start_date, q.end_date, merged, ship);
    const cover = (p.covers && p.covers.length ? p.covers[0] : '') || p.cover_url || '';

    this.setData({
      p: merged,
      sku,
      cover,
      rent,
      timeline: pricing.buildTimeline(q.start_date, q.end_date, ship),
    });
    this._recalcFee();
    return true;
  },

  async loadAddress() {
    try {
      const d = await get('/api/user/addresses', {}, { hideError: true });
      const list = (d && d.list) || [];
      // 与后端建单时的兜底一致：优先默认地址，否则第一条
      const addr = list.find((a) => a.is_default) || list[0] || null;
      this.setData({ addr: withFull(addr), addrLoaded: true });
    } catch (e) {
      this.setData({ addrLoaded: true });
    }
  },

  /** 按当前租金金额拉可用券，自动选抵扣最高的一张（后端已按抵扣降序返回） */
  async loadCoupons() {
    const amount = (this.data.rent && this.data.rent.total) || 0;
    if (!amount) return;
    let list = [];
    try {
      const r = await get('/api/user/coupons/match', { amount }, { hideError: true });
      list = ((r && r.list) || []).map((it) => ({
        ...it,
        thresholdText: pricing.fmtAmount(it.threshold),
        discountText: pricing.fmtAmount(it.discount_amount || it.discount),
      }));
    } catch (e) { list = []; }

    // 用户已手动选过就尊重其选择（金额没变，只是回到本页重拉）
    let picked = this.data.pickedCoupon || {};
    if (picked.id) {
      const still = list.find((x) => x.id === picked.id);
      picked = still ? { ...still } : {};
    } else if (list.length) {
      picked = { ...list[0] };
    }
    this.setData({ couponList: list, pickedCoupon: picked }, () => this._recalcFee());
  },

  /** 金额汇总：租金 - 券 = 实付租金；冻结额按运营口径 = 押金(+实付租金) */
  _recalcFee() {
    const rent = this.data.rent || {};
    const p = this.data.p || {};
    const picked = this.data.pickedCoupon || {};
    const round2 = (v) => Math.round(v * 100) / 100;

    const rentTotal = Number(rent.total) || 0;      // 已是整数（pricing.calcRent 取整）
    const discount = Number(picked.discount_amount) || 0;
    // 券面额可能带小数（满 300 减 5.5），扣完再取整一次，与后端 create_order 同规则
    const payRent = Math.max(0, pricing.roundYuan(rentTotal - discount));
    const deposit = Number(p.deposit_amount) || 0;  // 押金按后台配置原样用，不取整
    const freeze = round2(deposit + (this.data.freezeIncludesRent ? payRent : 0));

    // 押金卡的说明文案在这里拼好：冻结口径由运营配置决定，
    // includes_rent 打开时冻结的是「押金 + 租金」，只说"冻结押金"会漏掉一半金额。
    const depTxt = pricing.fmtAmount(deposit);
    const depositNote = this.data.freezeIncludesRent
      ? `将一次授权 ¥${pricing.fmtAmount(freeze)}（押金 ¥${depTxt} + 租金 ¥${pricing.fmtAmount(payRent)}）；授权成功后租金立即实付，押金部分按芝麻信用结果免押/冻结，归还后解除。`
      : `押金以预授权方式冻结 ¥${depTxt}，不会实际扣款；芝麻信用达标即可全额免押，归还后自动解冻。`;

    this.setData({
      depositNote,
      fee: {
        rentText:     pricing.fmtAmount(rentTotal),
        discountText: pricing.fmtAmount(discount),
        depositText:  depTxt,
        payRentText:  pricing.fmtAmount(payRent),
        freezeText:   pricing.fmtAmount(freeze),
        savedText:    pricing.fmtAmount(rent.saved || 0),
      },
    });
  },

  // ---------- 地址 ----------
  onPickAddress() {
    if (this.data.addr) {
      my.navigateTo({ url: '/pages/addresses/addresses?pick=1' });
    } else {
      // 一个地址都没有，直接去新增，少一次跳转
      my.navigateTo({ url: '/pages/address-edit/address-edit' });
    }
  },

  // ---------- 优惠券 ----------
  openCouponSheet() {
    if (!this.data.couponList.length) {
      my.showToast({ content: '当前订单暂无可用优惠券', type: 'none' });
      return;
    }
    this.setData({ couponSheet: true });
  },
  closeCouponSheet() { this.setData({ couponSheet: false }); },
  onPickCoupon(e) {
    const id = parseInt(e.currentTarget.dataset.id, 10);
    const item = this.data.couponList.find((x) => x.id === id);
    this.setData({ pickedCoupon: item ? { ...item } : {}, couponSheet: false }, () => this._recalcFee());
  },
  onUnpickCoupon() {
    this.setData({ pickedCoupon: {}, couponSheet: false }, () => this._recalcFee());
  },

  // ---------- 备注 ----------
  openRemark() {
    this.setData({ remarkSheet: true, remarkDraft: this.data.remark });
  },
  closeRemark() { this.setData({ remarkSheet: false }); },
  onRemarkInput(e) { this.setData({ remarkDraft: e.detail.value }); },
  saveRemark() {
    // 后端同样截断到 200，这里先截一刀让用户所见即所得
    this.setData({ remark: (this.data.remarkDraft || '').trim().slice(0, 200), remarkSheet: false });
  },

  // ---------- 费用明细展开 ----------
  toggleFeeSheet() { this.setData({ feeSheet: !this.data.feeSheet }); },
  closeFeeSheet() { this.setData({ feeSheet: false }); },

  // ---------- 协议 ----------
  toggleAgree() {
    // 只存内存，不落 storage：每次下单都必须由用户当次主动勾选
    this.setData({ agreed: !this.data.agreed });
  },
  openAgreement() { my.navigateTo({ url: '/pages/agreement/agreement' }); },
  closeAgreeSheet() {
    if (this.data.submitting) return;   // 提交中不让关，避免重复触发
    this.setData({ agreeSheet: false });
  },
  /** 弹窗里点「同意并下单」：等价于勾选协议 + 继续下单 */
  async onAgreeAndSubmit() {
    if (this.data.submitting) return;
    this.setData({ agreed: true });
    await this._doSubmit();
  },

  noop() {},

  // ---------- 下单 ----------
  async onSubmit() {
    if (this.data.submitting) return;
    if (this.data.fatal) {
      my.showToast({ content: this.data.fatal, type: 'none' });
      return;
    }
    // 没勾协议 → 弹确认层，由「同意并下单」接着走完流程
    if (!this.data.agreed) { this.setData({ agreeSheet: true }); return; }
    await this._doSubmit();
  },

  /** 真正的下单流程。onSubmit 与协议弹窗的「同意并下单」共用这一份，
   *  避免两条入口各写一遍校验、日后改漏一处。 */
  async _doSubmit() {
    if (this.data.submitting) return;
    if (!(await requireLogin('下单需要先登录'))) return;
    if (!(await requireRealName())) return;

    // 登录后地址可能才拉得到，这里补一次
    if (!this.data.addr) {
      await this.loadAddress();
      if (!this.data.addr) {
        my.confirm({
          title: '需要收货地址',
          content: '下单前请先添加一个收货地址',
          confirmButtonText: '去添加',
          cancelButtonText: '稍后',
          success: (r) => { if (r.confirm) my.navigateTo({ url: '/pages/address-edit/address-edit' }); },
        });
        return;
      }
    }

    const q = this._q;
    const rent = this.data.rent || {};
    this.setData({ submitting: true });
    my.showLoading({ content: '下单中', mask: true });
    try {
      const payload = {
        product_id: q.product_id,
        days: rent.rentDays,
        start_date: rent.startDate,
        end_date: rent.endDate,
        ship_days: rent.shipDays,
        address_id: this.data.addr.id,
      };
      if (this.data.sku) payload.sku_id = this.data.sku.id;
      if (this.data.pickedCoupon && this.data.pickedCoupon.id) {
        payload.user_coupon_id = this.data.pickedCoupon.id;
      }
      if (this.data.remark) payload.user_remark = this.data.remark;

      const o = await post('/api/orders', payload);
      my.hideLoading();
      this.setData({ agreeSheet: false });
      // redirect 而非 navigate：单已经建了，用户从订单详情返回时不该再回到确认页
      my.redirectTo({ url: `/pages/order-detail/order-detail?id=${o.id}&credit=1` });
    } catch (e) {
      my.hideLoading();
      // 失败时留在协议弹层上没意义，收起来让用户看到页面上的报错 toast
      this.setData({ submitting: false, agreeSheet: false });
    }
  },
});
