const { get, post } = require('../../utils/request.js');

const STATUS_TEXT = {
  pay: '待支付', audit: '待免押',
  send: '待发货', pending_cancel: '取消审核中',
  recv: '待收货', using: '租赁中',
  return: '待归还', overdue: '已逾期',
  return_inspecting: '核验中',
  done: '已归还',
  cancelled: '已取消',
};

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const z = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function fmtDateTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const z = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`;
}
function shortName(name) {
  if (!name) return '';
  const m = name.match(/(Pocket|Action|Quest|PICO|Vision|Switch|HomePod|H3S|Z6X|Z8X|C1|C2)\s*[\dA-Z]*/i);
  return m ? m[0] + ' 租赁' : name.split(' ')[0];
}
// 商家承诺发货时长（秒）
const SHIP_PROMISE_SECONDS = 48 * 3600;
// 客服电话（与 onMore() 保持一致）
const SERVICE_PHONE = '400-000-0000';
// 快递公司编码 → 中文名（与后端 app/logistics 表对齐）
const COURIER_NAMES = {
  SF: '顺丰速运',
  JD: '京东物流',
};

// 起租日 + N 天 → 触发强制违约扣款的截止日（业务硬约束 350 天）
const FORCE_BREACH_DAYS = 350;
// 实时累计租金允许显示的订单状态（计费已开始 / 进行中 / 待归还 / 已逾期 / 核验中）
const RENT_CARD_STATUS = new Set(['recv', 'using', 'return', 'overdue', 'return_inspecting']);

// "YYYY-MM-DD" → Date（本地零点），非法返回 null
function parseYMD(s) {
  if (!s) return null;
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(s).trim());
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3]);
}
function ymd(d) {
  if (!d) return '';
  const z = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function addDays(d, n) {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}
function daysDiff(d1, d2) {
  // d2 - d1，按本地零点对齐
  const a = new Date(d1); a.setHours(0, 0, 0, 0);
  const b = new Date(d2); b.setHours(0, 0, 0, 0);
  return Math.round((b - a) / 86400000);
}

// 分段计费 tiers 清洗 + 规范化（镜像后端 normalize_tiers / calc_amount 语义）
function normalizeTiers(raw, fallbackPrice) {
  const tiers = [];
  if (Array.isArray(raw)) {
    for (const t of raw) {
      const f = parseInt(t && t.from, 10);
      const p = Number(t && t.price);
      if (!isNaN(f) && f >= 1 && !isNaN(p) && p >= 0) tiers.push({ from: f, price: p });
    }
  }
  if (!tiers.length) {
    const p = Number(fallbackPrice);
    if (!isNaN(p) && p >= 0) tiers.push({ from: 1, price: p });
  }
  if (!tiers.length) return null;
  tiers.sort((a, b) => a.from - b.from);
  if (tiers[0].from !== 1) tiers[0] = { from: 1, price: tiers[0].price };
  return tiers;
}
function calcRent(days, tiers) {
  days = Math.max(0, parseInt(days, 10) || 0);
  if (!days || !tiers || !tiers.length) return 0;
  let total = 0;
  for (let i = 0; i < tiers.length; i++) {
    const seg = tiers[i];
    if (seg.from > days) break;
    const segEndRaw = (i + 1 < tiers.length) ? (tiers[i + 1].from - 1) : days;
    const segEnd = Math.min(segEndRaw, days);
    total += (segEnd - seg.from + 1) * seg.price;
  }
  return Math.round(total * 100) / 100;
}
function tierLines(tiers) {
  if (!tiers || !tiers.length) return [];
  return tiers.map((cur, i) => {
    const next = tiers[i + 1];
    const range = next ? `第 ${cur.from}–${next.from - 1} 天` : `第 ${cur.from} 天起`;
    return { range, price: cur.price.toFixed(2) };
  });
}

Page({
  data: {
    o: {}, freezing: false, charges: [], chargeTotalText: '',
    // 寄回归还表单状态
    couriers: [],       // /api/orders/couriers 返回的列表
    rsCompany: '',      // 选中的快递公司编码（SF/JD）
    rsNo: '',           // 用户输入的运单号
    rsSubmitting: false,
    // 实时租金累计卡（show=false 时整张卡不渲染）
    rent: { show: false },
  },

  onLoad(q) {
    const id = q && q.id;
    if (!id) return;
    this._orderId = id;
    this.loadOrder(id).then(() => {
      if (q && q.credit === '1' && this.data.o.status === 'audit') this.onCreditFreeze();
    });
    this.loadCouriers();
  },

  onUnload() { this._stopShipTimer(); this._stopRentTimer(); },
  onHide()   { this._stopShipTimer(); this._stopRentTimer(); },
  onShow()   {
    // 从客服电话等场景返回时，立即重算一次（避免 1s 跳变），然后按需重启计时器
    if (this._orderId && this.data.o && this.data.o.status === 'send') {
      const o = { ...this.data.o };
      this._applyShipCountdown(o);
      this.setData({
        'o._shipHH': o._shipHH,
        'o._shipMM': o._shipMM,
        'o._shipSS': o._shipSS,
        'o._shipOverdue': o._shipOverdue,
      });
      if (!o._shipOverdue && !this._shipTimer) this._startShipTimer();
    }
    // 实时租金卡：onShow 立即重算，跨午夜回来天数才不会卡在昨天
    if (this._orderId && this.data.o && RENT_CARD_STATUS.has(this.data.o.status)) {
      this._refreshRent();
      if (!this._rentTimer) this._startRentTimer();
    }
    // 从子页（如退款申请页）返回时刷新扣款列表，让 refund_apply 状态
    // 从 ''→PENDING / REJECTED→PENDING 等变化立即反映到 UI；
    // 守卫 o.id 防止初次挂载时与 loadOrder 内部的 loadCharges 竞争。
    if (this._orderId && this.data.o && this.data.o.id) {
      this.loadCharges();
    }
  },

  async loadOrder(id) {
    try {
      const o = await get('/api/orders/' + id);
      const days = o.days || 0;
      // 每日租金按"未抵扣前的原价 / 天数"显示，避免抵扣后看起来日租金被打折
      const baseForDaily = o.original_amount || o.amount || 0;
      const daily = days ? (baseForDaily / days) : 0;
      o._statusText = o.status_label || STATUS_TEXT[o.status] || o.status;
      o._startDate = fmtDate(o.created_at);
      o._endDate   = fmtDate(o.created_at + days * 86400);
      o._createdText = fmtDateTime(o.created_at);
      o._amountText  = (o.amount || 0).toFixed(2);
      o._originalText = (o.original_amount || o.amount || 0).toFixed(2);
      o._discountText = (o.discount_amount || 0).toFixed(2);
      o._dailyText   = daily.toFixed(2);
      // 冻结金额展示：优先用后端落库的 freeze_amount，兼容历史订单按"押金+租金"兜底
      o._freezeIncludesRent = o.freeze_includes_rent !== false;
      const freezeAmt = Number(o.freeze_amount || 0)
        || (Number(o.deposit_freeze || 0) + (o._freezeIncludesRent ? Number(o.amount || 0) : 0));
      o._freezeText = freezeAmt.toFixed(2);
      o._shortName   = shortName(o.product_name);
      // 物流字段渲染
      const lc = (o.logistics_company || '').toUpperCase();
      o._logiCompanyName = COURIER_NAMES[lc] || lc || '快递';
      o._shippedAtText = o.shipped_at ? fmtDateTime(o.shipped_at) : '';
      this._applyShipCountdown(o);
      this.setData({ o });
      // 启动 / 停止 48h 发货倒计时
      if (o.status === 'send' && !o._shipOverdue) this._startShipTimer();
      else this._stopShipTimer();
      // 实时租金累计卡：仅在计费期相关状态下显示并启动 1 分钟刷新
      this._refreshRent();
      if (RENT_CARD_STATUS.has(o.status)) this._startRentTimer();
      else this._stopRentTimer();
      // 并行拉历史扣款记录（拉不到也不阻塞主流程）
      this.loadCharges();
    } catch (e) {}
  },

  // -------------------- 实时租金累计 --------------------
  // 拼一份当前的 rent 视图模型
  //
  // 时间轴语义（创建订单时落库）：
  //   start_date                       物理时间轴起点（包裹离开商家那天）
  //   start_date + ship_days           ← 真正开始计费的"起租日"，前 ship_days 天免租
  //   end_date                         预计归还日（= billingStart + days - 1）
  //   billingStart + 350 天            强制违约扣款日
  _buildRent(o) {
    if (!o || !RENT_CARD_STATUS.has(o.status)) return { show: false };
    const physicalStart = parseYMD(o.start_date);
    if (!physicalStart) return { show: false };

    const tiers = normalizeTiers(o.price_tiers, o.price_per_day);
    if (!tiers) return { show: false };

    // 物流免租期：订单上下单时锁定的天数（兜底取系统默认 3 天）
    const shipDays = Math.max(0, parseInt(o.ship_days, 10) || 0);
    const billingStart = addDays(physicalStart, shipDays);  // 真正起租日

    const today0 = new Date();
    today0.setHours(0, 0, 0, 0);
    const physicalStart0 = new Date(physicalStart);
    physicalStart0.setHours(0, 0, 0, 0);
    const billingStart0 = new Date(billingStart);
    billingStart0.setHours(0, 0, 0, 0);

    // 三段状态：未发货前 / 物流免租期内 / 已开始计费
    const notStarted     = today0 < physicalStart0;
    const inShipPeriod   = !notStarted && today0 < billingStart0;
    const inBilling      = today0 >= billingStart0;

    // 累计天数（计费第 1 天 = billingStart 当天）
    const billingDays = inBilling ? (daysDiff(billingStart0, today0) + 1) : 0;
    const accumulated = calcRent(billingDays, tiers);

    // 物流期内已走了几天（用于显示 "物流期 X / Y 天"）
    const shipUsed = inShipPeriod ? (daysDiff(physicalStart0, today0) + 1)
                                  : (inBilling ? shipDays : 0);

    // o.end_date 现在就是"归还日"（酒店式语义：归还日不计入用机/计费），
    // 由下单日历 _rangeForRentDays / _calcRent 统一产出，这里直接用即可。
    const returnDate = parseYMD(o.end_date);
    const breachDate = addDays(billingStart, FORCE_BREACH_DAYS);

    return {
      show: true,
      notStarted,
      inShipPeriod,
      // 归还日当天不算逾期；超过归还日（次日起）才标"已超归还日"
      overhold: !!(returnDate && today0 > returnDate),
      shipDays,
      shipUsed,
      currentDays: billingDays,
      accumulated: accumulated.toFixed(2),
      // 时间轴上的几个关键日期
      physicalStartText: ymd(physicalStart),     // 包裹出库日 = 物流期第 1 天
      billingStartText: ymd(billingStart),       // 实际起租 / 开始计费日
      endDateText: returnDate ? ymd(returnDate) : '',  // 预计归还日 = 最后用机日 + 1
      breachDateText: ymd(breachDate),
      tierLines: tierLines(tiers),
    };
  },
  _refreshRent() {
    const rent = this._buildRent(this.data.o);
    // 只在数值真的变了才 setData，避免无谓 diff
    const cur = this.data.rent || {};
    if (
      cur.show !== rent.show ||
      cur.accumulated !== rent.accumulated ||
      cur.currentDays !== rent.currentDays ||
      cur.shipUsed !== rent.shipUsed ||
      cur.inShipPeriod !== rent.inShipPeriod ||
      cur.overhold !== rent.overhold ||
      cur.notStarted !== rent.notStarted
    ) {
      this.setData({ rent });
    }
  },
  _startRentTimer() {
    this._stopRentTimer();
    // 1 分钟刷一次足够：累计金额按天阶跃，1 分钟内最多差一次跨日
    this._rentTimer = setInterval(() => this._refreshRent(), 60 * 1000);
  },
  _stopRentTimer() {
    if (this._rentTimer) { clearInterval(this._rentTimer); this._rentTimer = null; }
  },

  // 历史扣款记录（押金被扣的真实流水）
  async loadCharges() {
    const id = this._orderId;
    if (!id) return;
    try {
      const r = await get(`/api/orders/${id}/charges`);
      this.setData({
        charges: r.list || [],
        chargeTotalText: r.total_amount_text || '',
      });
    } catch (e) {
      // 静默：未授权 / 网络问题都不打断详情主体
    }
  },

  // -------------------- 寄回归还 --------------------
  async loadCouriers() {
    try {
      const r = await get('/api/orders/couriers');
      this.setData({ couriers: r.list || [] });
    } catch (e) {}
  },
  onRsCompany(e) {
    const code = e.currentTarget.dataset.code;
    if (code) this.setData({ rsCompany: code });
  },
  onRsNoInput(e) {
    // 去空白 + 大写，与后端 logistics.normalize_no 对齐
    const v = (e.detail.value || '').replace(/\s+/g, '').toUpperCase();
    this.setData({ rsNo: v });
  },
  // 一键从剪贴板填入运单号
  onPasteRsNo() {
    my.getClipboard({
      success: (r) => {
        const v = ((r && r.text) || '').replace(/\s+/g, '').toUpperCase();
        if (!v) { my.showToast({ content: '剪贴板为空', type: 'none' }); return; }
        this.setData({ rsNo: v });
        my.showToast({ content: '已粘贴', type: 'success', duration: 1000 });
      },
      fail: () => my.showToast({ content: '无法读取剪贴板', type: 'fail' }),
    });
  },
  onClearRsNo() {
    this.setData({ rsNo: '' });
  },
  async onSubmitReturn() {
    const { rsCompany, rsNo, rsSubmitting } = this.data;
    if (rsSubmitting) return;
    if (!rsCompany) { my.showToast({ content: '请选择快递公司', type: 'none' }); return; }
    if (!rsNo)      { my.showToast({ content: '请填写运单号',   type: 'none' }); return; }
    // 用户点选的 segment 文字，原样带给后端落库供展示——避免后端再做 code→name 映射
    const rsCompanyName = (this.data.couriers.find(c => c.code === rsCompany) || {}).name || rsCompany;
    my.confirm({
      title: '确认提交寄回信息？',
      content: `快递公司：${rsCompanyName}\n运单号：${rsNo}`,
      success: async (res) => {
        if (!res.confirm) return;
        this.setData({ rsSubmitting: true });
        try {
          await post(`/api/orders/${this._orderId}/return-ship`, {
            logistics_company:      rsCompany,
            logistics_company_name: rsCompanyName,
            logistics_no:           rsNo,
          });
          my.showToast({ content: '已提交，等商家核验', type: 'success' });
          this.setData({ rsCompany: '', rsNo: '' });
          this.loadOrder(this._orderId);
        } catch (err) {
          my.showToast({ content: err.message || '提交失败', type: 'fail' });
        } finally {
          this.setData({ rsSubmitting: false });
        }
      },
    });
  },

  // -------------------- 48h 发货倒计时 --------------------
  _applyShipCountdown(o) {
    // 兜底：旧数据没有 send_at，用 updated_at 或 created_at 推断起点
    const base = o.send_at || o.updated_at || o.created_at || 0;
    const deadline = base + SHIP_PROMISE_SECONDS;
    const now = Math.floor(Date.now() / 1000);
    const remain = deadline - now;
    if (remain <= 0) {
      o._shipOverdue = true;
      o._shipHH = '00'; o._shipMM = '00'; o._shipSS = '00';
      return;
    }
    o._shipOverdue = false;
    const z = (n) => (n < 10 ? '0' + n : '' + n);
    o._shipHH = z(Math.floor(remain / 3600));
    o._shipMM = z(Math.floor((remain % 3600) / 60));
    o._shipSS = z(remain % 60);
  },
  _startShipTimer() {
    this._stopShipTimer();
    this._shipTimer = setInterval(() => {
      const o = { ...this.data.o };
      this._applyShipCountdown(o);
      this.setData({
        'o._shipHH': o._shipHH,
        'o._shipMM': o._shipMM,
        'o._shipSS': o._shipSS,
        'o._shipOverdue': o._shipOverdue,
      });
      if (o._shipOverdue) this._stopShipTimer();
    }, 1000);
  },
  _stopShipTimer() {
    if (this._shipTimer) { clearInterval(this._shipTimer); this._shipTimer = null; }
  },

  // 倒计时超时区域的"联系客服电话"按钮
  onCallService() {
    my.makePhoneCall({ number: SERVICE_PHONE });
  },

  // 复制运单号到剪贴板
  onCopyLogisticsNo() {
    const no = (this.data.o && this.data.o.logistics_no) || '';
    if (!no) return;
    my.setClipboard({
      text: no,
      success: () => my.showToast({ content: '运单号已复制', type: 'success' }),
    });
  },

  // 复制订单编号到剪贴板
  onCopyOrderId() {
    const id = (this.data.o && this.data.o.id) || '';
    if (!id) return;
    my.setClipboard({
      text: id,
      success: () => my.showToast({ content: '订单编号已复制', type: 'success' }),
    });
  },

  // 已归还订单的"去评价"：跳商品详情页并通过 ?review=1 触发自动弹评价层
  onGoReview() {
    const pid = this.data.o && this.data.o.product_id;
    if (!pid) {
      my.showToast({ content: '商品已下架，无法评价', type: 'none' });
      return;
    }
    my.navigateTo({ url: `/pages/product/product?id=${pid}&review=1` });
  },

  // 点击扣款条目的"对此扣款有疑问？申请退款"按钮：跳到退款申请页
  onOpenRefundApply(e) {
    const otn = e.currentTarget.dataset.id;
    const oid = this._orderId;
    if (!otn || !oid) return;
    my.navigateTo({
      url: `/pages/refund-apply/refund-apply?oid=${oid}&otn=${otn}`,
    });
  },

  // -------------------- 预授权（audit 状态触发） --------------------
  // 单次不指定渠道：分流全部交给支付宝。后端已注入 serviceId + category，
  // 够格用户在原生页看到「芝麻信用免押」授权（不冻资金），不够格则同页自动切
  // 余额/花呗/银行卡冻结押金——一步到位，不再出现"评估不通过/请选其他支付工具"的
  // 中间态。免押与押金在后端走同一状态机（都进待发货），仅 payment_method 落库不同。
  async onCreditFreeze() {
    const o = this.data.o;
    if (!o || !o.id || this.data.freezing) return;
    if (!my.tradePay) {
      my.alert({ content: '预授权支付仅支持支付宝真机；IDE 模拟器不支持，请扫码到真机预览' });
      return;
    }
    this.setData({ freezing: true });

    try {
      // 冻结金额由后端在下单时根据系统设置算好（押金 or 押金+租金），存在 o.freeze_amount。
      // 历史订单无该字段则按"押金+租金"兜底（与下单时硬编码逻辑一致）。
      const includesRent = o.freeze_includes_rent !== false;
      const freezeAmount = Number(o.freeze_amount || 0)
        || (Number(o.deposit_freeze || 0) + (includesRent ? Number(o.amount || 0) : 0));
      const titleSuffix  = includesRent ? ' - 押金+租金' : ' - 押金';

      // out_order_no 只传裸订单号；支付宝授权订单按它唯一，用户取消后重试需换号，
      // 换号与 out_request_no 由后端按"已发起次数"统一生成（首次裸号，重试 _A2…），
      // 避免复用同号被支付宝拒"授权订单已存在"。
      // 不传 enable_pay_channels → 后端不设该字段 → 支付宝按用户实际能力自动分流。
      my.showLoading({ content: '创建订单', mask: true });
      const r = await post('/api/alipay/credit/freeze', {
        out_order_no: o.id,
        order_title:  (o.product_name || '租赁订单') + titleSuffix,
        amount: freezeAmount,
      });
      my.hideLoading();

      const paid = await this._tradePay(r.order_str);
      if (!paid) { my.showToast({ content: '已取消', type: 'none' }); return; }

      // 确认结果：后端按支付宝返回的 payment_method 判定免押/押金并落库，
      // 两者都从 audit 推进到 send（待发货），无二次人脸认证环节。
      my.showLoading({ content: '确认结果', mask: true });
      const q = await post('/api/alipay/credit/query', { out_order_no: o.id });
      my.hideLoading();
      my.alert({
        title: (q && q.is_credit) ? '免押成功' : '押金冻结成功',
        content: '订单已进入待发货，将尽快安排出库',
      });
      this.loadOrder(o.id);
    } catch (e) {
      my.hideLoading();
    } finally {
      this.setData({ freezing: false });
    }
  },
  _tradePay(orderStr) {
    return new Promise((resolve) => {
      my.tradePay({
        orderStr,
        success: (r) => {
          // 全打出来：r.resultCode / r.memo / r.result (含 subCode/subMsg)
          console.log('[freeze][tradePay success]', JSON.stringify(r));
          resolve(r && (r.resultCode === '9000' || r.resultCode === '6004'));
        },
        fail: (err) => {
          console.error('[freeze][tradePay fail]', JSON.stringify(err));
          resolve(false);
        },
      });
    });
  },
  // -------------------- 底部按钮 --------------------
  onUrgeAudit() {
    my.showToast({ content: '已提醒商家加急审核', type: 'success' });
  },
  onMore() {
    my.showActionSheet({
      items: ['联系客服'],
      success: (r) => { if (r.index === 0) my.makePhoneCall({ number: SERVICE_PHONE }); },
    });
  },
  onCancel() {
    const id = this.data.o.id;
    my.confirm({
      title: '确认取消订单？',
      content: '取消后无法恢复',
      success: async (r) => {
        if (!r.confirm) return;
        try {
          await post(`/api/orders/${id}/cancel`, {});
          my.showToast({ content: '已取消', type: 'success' });
          this.loadOrder(id);
        } catch (e) {}
      },
    });
  },

  // send 状态申请取消（不立即解冻，需要商家审核）
  onRequestCancel() {
    const id = this.data.o.id;
    my.prompt({
      title: '申请取消订单',
      message: '商家会在 24 小时内核实是否已发货。\n通过后将自动解冻信用额度。',
      placeholder: '取消原因（选填，如：不想要了 / 选错型号）',
      align: 'left',
      okButtonText: '提交申请',
      cancelButtonText: '再想想',
      success: async (res) => {
        if (!res.ok) return;
        try {
          this._stopShipTimer();
          await post(`/api/orders/${id}/cancel`, { reason: res.inputValue || '' });
          my.alert({ title: '已提交', content: '商家审核通过后会自动解冻信用额度' });
          this.loadOrder(id);
        } catch (e) {}
      },
    });
  },
});
