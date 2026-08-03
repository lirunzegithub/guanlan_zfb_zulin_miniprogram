const { get, post } = require('../../utils/request.js');
const pricing = require('../../utils/pricing.js');

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

// 顶部进度条的五个阶段。10 种订单状态收敛到这 5 段展示，
// 用户不需要理解 return_inspecting 和 overdue 的区别，只需要知道走到哪一步了。
const STEPS = ['付租金/免押', '商家发货', '签收使用', '归还/续租', '订单完成'];
const STATUS_STEP = {
  audit: 0, pay: 0,
  send: 1, pending_cancel: 1,
  recv: 2, using: 2,
  return: 3, overdue: 3, return_inspecting: 3,
  done: 4,
};
// 状态副标题：告诉用户"现在轮到谁做什么"，比只写状态名有用
const STATUS_SUB = {
  audit:  '租金已支付，请继续完成押金免押',
  pay:    '订单待支付租金，支付后再进行押金免押',
  send:   '商家正在备货，承诺 48 小时内发货',
  pending_cancel: '取消申请审核中，商家同意后将自动解冻',
  recv:   '商家已发货，请注意查收',
  using:  '设备使用中，到期前可归还或续租',
  return: '租期即将到期，请及时安排归还',
  overdue:'已超过预计归还日，请尽快寄回',
  return_inspecting: '已收到寄回信息，等待商家签收核验',
  done:   '订单已完成，感谢使用',
  cancelled: '订单已取消',
};

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
// 支付宝 picker 在不同基础库/端上可能回传字符串、数组、
// {year,month,day} 或时间戳。统一归一为 YYYY-MM-DD，避免合法日期被误判。
function normalizePickerDate(raw, fallbackYear) {
  if (raw === undefined || raw === null || raw === '') return '';
  if (Array.isArray(raw) && raw.length >= 3) {
    return ymd(new Date(Number(raw[0]), Number(raw[1]) - 1, Number(raw[2])));
  }
  if (typeof raw === 'object') {
    if (raw.value !== undefined) return normalizePickerDate(raw.value, fallbackYear);
    const yy = Number(raw.year || raw.y || 0);
    const mm = Number(raw.month || raw.m || 0);
    const dd = Number(raw.day || raw.d || raw.date || 0);
    if (yy && mm && dd) return ymd(new Date(yy, mm - 1, dd));
  }
  if (typeof raw === 'number' || /^\d{10,13}$/.test(String(raw))) {
    let ts = Number(raw);
    if (ts < 1e12) ts *= 1000;
    const d = new Date(ts);
    return isNaN(d.getTime()) ? '' : ymd(d);
  }
  const s = String(raw).trim();
  const isoHead = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$/.exec(s);
  if (isoHead) return ymd(new Date(Number(isoHead[1]), Number(isoHead[2]) - 1, Number(isoHead[3])));
  let m = /^(\d{4})[-\/.\u5e74](\d{1,2})[-\/.\u6708](\d{1,2})(?:\u65e5)?$/.exec(s);
  if (m) return ymd(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  m = /^(\d{1,2})[-\/.\u6708](\d{1,2})(?:\u65e5)?$/.exec(s);
  if (m && fallbackYear) return ymd(new Date(Number(fallbackYear), Number(m[1]) - 1, Number(m[2])));
  return '';
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

Page({
  data: {
    o: {}, payingRent: false, freezing: false, charges: [], chargeTotalText: '',
    renewal: {
      show: false, selected: 3, custom: false, customDate: '', minDate: '', maxDate: '',
      quote: null, quoting: false, paying: false, maxExtendDays: 60, unavailableMsg: '',
      options: [{ days: 3 }, { days: 7 }, { days: 15 }, { days: 30 }],
    },
    // 寄回归还表单状态
    couriers: [],       // /api/orders/couriers 返回的列表
    rsCompany: '',      // 选中的快递公司编码（SF/JD）
    rsNo: '',           // 用户输入的运单号
    rsSubmitting: false,
    // 已付租金卡（show=false 时整张卡不渲染）
    rent: { show: false },
    steps: STEPS,
    infoOpen: false,          // 订单信息「展开更多」
    // 物流轨迹。supported=false 时卡片退化成"公司 + 运单号"，不显示时间轴
    logi: {
      loading: false, loaded: false, supported: false,
      routes: [], latest: null, signedAt: '', error: '', expanded: false,
    },
  },

  onLoad(q) {
    const id = q && q.id;
    if (!id) return;
    this._orderId = id;
    this.loadOrder(id).then(() => {
      if (q && q.rent === '1' && this.data.o.status === 'pay') this.onRentPay(true);
      else if (q && q.credit === '1' && this.data.o.status === 'audit') this.onCreditFreeze();
    });
    this.loadCouriers();
  },

  onUnload() { this._stopShipTimer(); },
  onHide()   { this._stopShipTimer(); },
  onShow()   {
    // 从续租页返回时刷新新的归还日和租金。首次 onShow 交给 onLoad，
    // 避免同一订单并发拉两次。
    if (this._shownOnce && this._orderId) this.loadOrder(this._orderId);
    this._shownOnce = true;
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
      // 顶部进度 + 副标题
      o._stepIndex = STATUS_STEP[o.status];
      if (o._stepIndex === undefined) o._stepIndex = -1;   // cancelled：不画进度条
      o._statusSub = STATUS_SUB[o.status] || '';
      if (o.status === 'audit' && o.alipay_auth_no && !o.rent_paid_at) {
        o._statusSub = '综合授权已成功，正在自动结算租金，结算前不会发货';
      }
      o._cancelled = o.status === 'cancelled';
      // 租期时间轴：与下单时同一套算法（utils/pricing），四个日期口径一致
      o._tl = pricing.buildTimeline(o.start_date, o.end_date, Number(o.ship_days) || 0);
      // 物流字段渲染
      const lc = (o.logistics_company || '').toUpperCase();
      o._logiCompanyName = COURIER_NAMES[lc] || lc || '快递';
      o._shippedAtText = o.shipped_at ? fmtDateTime(o.shipped_at) : '';
      this._applyShipCountdown(o);
      this.setData({ o });
      // 启动 / 停止 48h 发货倒计时
      if (o.status === 'send' && !o._shipOverdue) this._startShipTimer();
      else this._stopShipTimer();
      // 已付租金卡只按订单快照构建，金额不随时间变化。
      this._refreshRent();
      // 并行拉历史扣款记录 / 物流轨迹（拉不到也不阻塞主流程）
      this.loadCharges();
      this.loadLogistics();
      this._prepareRenewalCard(o);
      // 待免押且发起过冻结的订单：进页面主动向支付宝对账一次。
      // 用户付完款没等到结果就退出/异步通知丢失时，凭这次 query 就能把订单
      // 推进到待发货，而不是一直停在"待免押"。只对账一次，避免 loadOrder 循环。
      if (o.status === 'audit' && Number(o.alipay_freeze_attempts || 0) > 0
          && !this._auditReconciled) {
        this._auditReconciled = true;
        try {
          const q = await post('/api/alipay/credit/query', { out_order_no: o.id });
          // await 刷新完再返回：onLoad 的 credit=1 自动拉起支付读取的是刷新后的
          // 状态，已付款的订单不会再被拉起一次多余的收银台
          if (q && q.is_frozen) await this.loadOrder(o.id);
        } catch (err) {}
      }
      // 付款后关闭小程序或异步回调丢失时，进页主动对账一次。
      if (o.status === 'pay' && o.rent_out_trade_no && !this._rentReconciled) {
        this._rentReconciled = true;
        try {
          const q = await post(`/api/orders/${o.id}/rent/query`, {});
          if (q && q.is_paid) await this.loadOrder(o.id);
        } catch (err) {}
      }
    } catch (e) {}
  },

  toggleInfo() { this.setData({ infoOpen: !this.data.infoOpen }); },
  onOpenAgreement() { my.navigateTo({ url: '/pages/agreement/agreement' }); },
  onDepositHelp() {
    const includesRent = !!((this.data.o || {})._freezeIncludesRent);
    my.alert({
      title: '押金说明',
      content: includesRent
        ? '押金与租金一次授权。授权成功后，租金立即完成支付，剩余押金作为信用担保；归还验收通过后，押金授权将自动解除。'
        : '租金已在下单时支付。芝麻信用免押仅用于押金担保；归还验收通过后，押金授权将自动解除。',
      buttonText: '我知道了',
    });
  },

  // -------------------- 物流轨迹 --------------------
  // 后端已按订单缓存（在途 30 分钟 / 已签收 24 小时），这里只管取和渲染。
  // 未配顺丰、非顺丰单、还没发货，接口都回 supported=false，卡片退化成
  // 原来的"公司 + 运单号"两行，不报错也不留空白。

  /** 轨迹时间戳 'YYYY-MM-DD HH:MM:SS' → 拆成 {d:'10-03', t:'07:55'} 两列展示 */
  _fmtRouteTime(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s || '');
    return m ? { d: `${m[2]}-${m[3]}`, t: `${m[4]}:${m[5]}` } : { d: s || '', t: '' };
  },

  async loadLogistics(force) {
    const o = this.data.o;
    if (!o || !o.logistics_no) return;
    if (this.data.logi.loading) return;
    this.setData({ 'logi.loading': true });
    try {
      const r = await get(`/api/orders/${o.id}/logistics${force ? '?refresh=1' : ''}`);
      const routes = (r.routes || []).map((x) => {
        const tm = this._fmtRouteTime(x.time);
        return { ...x, _d: tm.d, _t: tm.t };
      });
      this.setData({
        logi: {
          loading:  false,
          loaded:   true,
          supported: !!r.supported,
          routes,
          latest:   routes[0] || null,
          signedAt: r.signed_at || '',
          error:    r.error || '',
          expanded: this.data.logi.expanded,
        },
      });
    } catch (e) {
      this.setData({ 'logi.loading': false, 'logi.loaded': true });
    }
  },

  toggleLogi() { this.setData({ 'logi.expanded': !this.data.logi.expanded }); },

  /** 手动刷新：绕过缓存回源。用户主动触发，频次可控 */
  async onRefreshLogistics() {
    if (this.data.logi.loading) return;
    await this.loadLogistics(true);
    my.showToast({ content: '已刷新', duration: 1200 });
  },

  // -------------------- 已付租金 --------------------
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

    // 物流免租期：订单上下单时锁定的天数（兜底取系统默认 3 天）
    const shipDays = Math.max(0, parseInt(o.ship_days, 10) || 0);
    const billingStart = addDays(physicalStart, shipDays);  // 真正起租日

    const today0 = new Date();
    today0.setHours(0, 0, 0, 0);
    // o.end_date 现在就是"归还日"（酒店式语义：归还日不计入用机/计费），
    // 由下单日历 _rangeForRentDays / _calcRent 统一产出，这里直接用即可。
    const returnDate = parseYMD(o.end_date);

    return {
      show: true,
      // 归还日当天不算逾期；超过归还日（次日起）才标"已超归还日"
      overhold: !!(returnDate && today0 > returnDate),
      shipDays,
      paidAmount: Number(o.amount || 0).toFixed(2),
      // 时间轴上的几个关键日期
      physicalStartText: ymd(physicalStart),     // 包裹出库日 = 物流期第 1 天
      billingStartText: ymd(billingStart),       // 实际起租 / 开始计费日
      endDateText: returnDate ? ymd(returnDate) : '',  // 预计归还日 = 最后用机日 + 1
    };
  },
  _refreshRent() {
    const rent = this._buildRent(this.data.o);
    this.setData({ rent });
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

  // -------------------- 详情页内续租卡片 --------------------
  _prepareRenewalCard(o) {
    const show = !!(o && ['using', 'return'].includes(o.status) && parseYMD(o.end_date));
    if (!show) {
      if (this.data.renewal.show) this.setData({ 'renewal.show': false });
      return;
    }
    // 归还日变了（初次加载/续租成功）才重置，普通刷新不打断用户选择。
    if (this._renewalBaseEnd === o.end_date) return;
    this._renewalBaseEnd = o.end_date;
    const end = parseYMD(o.end_date);
    const minDate = ymd(addDays(end, 1));
    // 单次最多 60 天；同时必须在押金授权到期日前 10 天归还。
    const singleMax = addDays(end, 60);
    const authStartTs = Number(o.send_at || o.created_at || 0);
    const authDeadline = authStartTs ? new Date((authStartTs + 350 * 86400) * 1000) : null;
    if (authDeadline) authDeadline.setHours(0, 0, 0, 0);
    const maxEnd = authDeadline && authDeadline < singleMax ? authDeadline : singleMax;
    const maxExtendDays = Math.max(0, daysDiff(end, maxEnd));
    const maxDate = ymd(maxEnd);
    const presetDays = [3, 7, 15, 30];
    const options = presetDays.map(days => ({ days, disabled: days > maxExtendDays }));
    const defaultDays = presetDays.find(days => days <= maxExtendDays) || 0;
    const unavailableMsg = maxExtendDays < 1
      ? `当前归还日已接近押金授权截止日 ${maxDate}，无法续租`
      : '';
    this.setData({
      renewal: {
        show: true, selected: defaultDays, custom: defaultDays === 0, customDate: minDate,
        minDate, maxDate, maxExtendDays, unavailableMsg,
        quote: null, quoting: false, paying: false, options,
      },
    });
    if (defaultDays) this._loadRenewalQuote(ymd(addDays(end, defaultDays)), defaultDays);
    else if (maxExtendDays >= 1) this._loadRenewalQuote(minDate, 0);
  },

  onRenewalPreset(e) {
    const days = Number(e.currentTarget.dataset.days || 0);
    const end = parseYMD((this.data.o || {}).end_date);
    if (!end || ![3, 7, 15, 30].includes(days) || days > Number(this.data.renewal.maxExtendDays || 0)) return;
    this.setData({ 'renewal.selected': days, 'renewal.custom': false, 'renewal.quote': null });
    this._loadRenewalQuote(ymd(addDays(end, days)), days);
  },

  onRenewalCustomTap() {
    if (Number(this.data.renewal.maxExtendDays || 0) < 1) return;
    this.setData({ 'renewal.selected': 0, 'renewal.custom': true });
  },

  onRenewalDateChange(e) {
    const oldEnd = parseYMD((this.data.o || {}).end_date);
    const detail = (e && e.detail) || {};
    const raw = detail.value !== undefined ? detail.value
      : (detail.date !== undefined ? detail.date : detail);
    const value = normalizePickerDate(raw, oldEnd && oldEnd.getFullYear());
    const picked = parseYMD(value);
    console.log('[renewal-date]', JSON.stringify({ raw, value, oldEnd: (this.data.o || {}).end_date }));
    if (!picked || !oldEnd || picked <= oldEnd) {
      my.showToast({ content: '请选择有效的新归还日期', type: 'none' });
      return;
    }
    const days = daysDiff(oldEnd, picked);
    const maxDays = Number(this.data.renewal.maxExtendDays || 0);
    if (days < 1 || days > maxDays || days > 60) {
      my.showToast({ content: `单次最多续租 60 天，且需在押金授权到期前 10 天归还`, type: 'none' });
      return;
    }
    this.setData({
      'renewal.selected': 0, 'renewal.custom': true,
      'renewal.customDate': value, 'renewal.quote': null,
    });
    this._loadRenewalQuote(value, 0);
  },

  async _loadRenewalQuote(newEndDate, selected) {
    const oid = this._orderId;
    if (!oid || !/^\d{4}-\d{2}-\d{2}$/.test(newEndDate || '')) return;
    const seq = (this._renewalQuoteSeq || 0) + 1;
    this._renewalQuoteSeq = seq;
    this.setData({ 'renewal.quoting': true });
    try {
      // hideError：报价失败不弹通用 toast，改把后端文案常驻在卡片上。
      // 0 元租金（租押分离）单每次报价都会失败，一闪而过的 toast 等于没提示。
      const quote = await get(
        `/api/orders/${oid}/renewal/quote`, { new_end_date: newEndDate }, { hideError: true },
      );
      if (seq !== this._renewalQuoteSeq) return;
      this.setData({
        'renewal.quote': quote, 'renewal.quoting': false,
        'renewal.selected': selected, 'renewal.unavailableMsg': '',
      });
    } catch (e) {
      if (seq === this._renewalQuoteSeq) {
        this.setData({
          'renewal.quote': null, 'renewal.quoting': false,
          // 网络错误没有业务文案，退回通用提示，不要显示空白
          'renewal.unavailableMsg': (e && e.msg) || '暂时无法获取续租报价，请稍后重试',
        });
      }
    }
  },

  async onRenewalPay() {
    const rn = this.data.renewal || {};
    const quote = rn.quote;
    if (rn.paying || !quote || !quote.new_end_date) return;
    if (!my.tradePay) { my.alert({ content: '续租支付请使用支付宝真机' }); return; }
    this.setData({ 'renewal.paying': true });
    try {
      const renewal = await post(`/api/orders/${this._orderId}/renewals`, {
        new_end_date: quote.new_end_date,
      });
      const pay = await post(`/api/orders/renewals/${renewal.id}/pay`, {});
      if (pay.completed) { await this._renewalDone(quote.new_end_date); return; }
      const returned = await this._tradePay(pay.trade_no);
      if (!returned) return;
      my.showLoading({ content: '确认续租支付', mask: true });
      const result = await post(`/api/orders/renewals/${renewal.id}/query`, {});
      my.hideLoading();
      if (result.completed) await this._renewalDone(quote.new_end_date);
      else my.alert({ title: '支付结果确认中', content: '如已扣款，系统会通过支付宝通知自动完成续租。' });
    } catch (e) {
      my.hideLoading();
    } finally {
      this.setData({ 'renewal.paying': false });
    }
  },

  async _renewalDone(newEndDate) {
    my.showToast({ content: '续租成功', type: 'success' });
    this._renewalBaseEnd = '';
    await this.loadOrder(this._orderId);
    my.alert({ title: '续租成功', content: `新归还日期：${newEndDate}` });
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

  // -------------------- 首期租金（pay 状态触发） --------------------
  async onRentPay(continueToCredit = false) {
    const o = this.data.o;
    if (!o || !o.id || o.status !== 'pay' || this.data.payingRent) return;
    if (!my.tradePay) {
      my.alert({ content: '租金支付仅支持支付宝真机；IDE 模拟器不支持' });
      return;
    }
    this.setData({ payingRent: true });
    try {
      my.showLoading({ content: '创建租金支付', mask: true });
      const r = await post(`/api/orders/${o.id}/rent/pay`, {});
      my.hideLoading();
      if (r.already_paid) {
        await this.loadOrder(o.id);
        if (this.data.o.status === 'audit') this.onCreditFreeze();
        return;
      }
      const returned = await this._tradePay(r.trade_no);
      if (!returned) {
        my.showToast({ content: '已取消租金支付，可稍后继续', type: 'none' });
        return;
      }
      my.showLoading({ content: '确认租金支付结果', mask: true });
      const q = await post(`/api/orders/${o.id}/rent/query`, {});
      my.hideLoading();
      if (!q || !q.is_paid) {
        my.alert({ title: '支付结果确认中', content: '如已付款，请稍后下拉刷新，系统不会重复收款。' });
        return;
      }
      await this.loadOrder(o.id);
      my.showToast({ content: '租金支付成功', type: 'success' });
      // 从确认页进来时连续完成两阶段；用户中途退出后也可在详情页单独继续。
      if (continueToCredit === true && this.data.o.status === 'audit') this.onCreditFreeze();
    } catch (e) {
      my.hideLoading();
    } finally {
      this.setData({ payingRent: false });
    }
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
      // 已发起过授权的订单先对账。授权已成功但租金转支付暂时失败时，
      // 只重试后端结算，绝不再给用户创建第二笔押金授权。
      if (Number(o.alipay_freeze_attempts || 0) > 0) {
        my.showLoading({ content: '核对授权与租金', mask: true });
        const existing = await post('/api/alipay/credit/query', { out_order_no: o.id });
        my.hideLoading();
        if (existing && existing.is_frozen) {
          if (existing.rent_captured) {
            my.alert({ title: '下单成功', content: '租金已支付，押金授权已生效，订单已进入待发货' });
          } else {
            my.alert({ title: '授权已成功', content: '租金仍在自动结算中，系统不会重复授权，结算前不会发货。' });
          }
          await this.loadOrder(o.id);
          return;
        }
      }
      // 方案 A：新订单一次授权“押金+租金”；授权成功后后端会
      // 立即把租金转为实际支付，只保留押金担保，用户无需第二次验证。
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

      const paid = await this._tradePay(r.order_str, true);
      if (!paid) { my.showToast({ content: '已取消', type: 'none' }); return; }

      // 确认结果：后端按支付宝返回的 payment_method 判定免押/押金并落库，
      // 两者都从 audit 推进到 send（待发货），无二次人脸认证环节。
      my.showLoading({ content: '确认结果', mask: true });
      const q = await post('/api/alipay/credit/query', { out_order_no: o.id });
      my.hideLoading();
      // tradePay 的 9000/6004 只代表收银台关闭，不代表冻结成功（无免押额度的
      // 用户可能授权失败退出）；以后端对账出的 is_frozen 为准
      if (q && q.is_frozen && q.rent_captured) {
        my.alert({
          title: q.is_credit ? '免押成功' : '押金冻结成功',
          content: '租金已支付，押金授权已生效，订单已进入待发货',
        });
      } else if (q && q.is_frozen) {
        my.alert({
          title: '授权已成功',
          content: '租金正在从授权额度中结算，暂不会发货。系统将自动对账，请稍后刷新。',
        });
      } else {
        my.alert({
          title: '未完成授权',
          content: '尚未确认到押金冻结成功。如已完成支付请稍后下拉刷新；否则请重新发起免押/押金支付',
        });
      }
      this.loadOrder(o.id);
    } catch (e) {
      my.hideLoading();
    } finally {
      this.setData({ freezing: false });
    }
  },
  _tradePay(payToken, isAuthOrder = false) {
    return new Promise((resolve) => {
      const opts = {
        success: (r) => {
          // 全打出来：r.resultCode / r.memo / r.result (含 subCode/subMsg)
          console.log('[freeze][tradePay success]', JSON.stringify(r));
          resolve(r && (r.resultCode === '9000' || r.resultCode === '6004'));
        },
        fail: (err) => {
          console.error('[freeze][tradePay fail]', JSON.stringify(err));
          resolve(false);
        },
      };
      // 普通小程序支付用 tradeNO；押金预授权 freeze 仍是支付宝
      // 返回的签名 orderStr，两种凭证不能混用。
      if (isAuthOrder) opts.orderStr = payToken;
      else opts.tradeNO = payToken;
      my.tradePay(opts);
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
