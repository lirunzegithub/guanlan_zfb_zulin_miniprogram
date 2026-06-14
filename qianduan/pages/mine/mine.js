const { get } = require('../../utils/request.js');
const requireLogin = require('../../utils/login.js');

// "进行中的订单" 卡片要隐藏的终态
const HIDDEN_ORDER_STATUS = new Set(['cancelled', 'done']);

const STATUS_TEXT = {
  pay: '待支付', audit: '待免押',
  send: '待发货', pending_cancel: '取消审核中',
  recv: '待收货', using: '租赁中',
  return: '待归还', overdue: '已逾期',
  return_inspecting: '核验中',
};
// 状态色：与列表/详情页保持一致
const STATUS_CLS = {
  audit: 'st-warn', send: 'st-warn', pending_cancel: 'st-warn',
  pay: 'st-warn',
  recv: 'st-primary', using: 'st-success', return: 'st-primary',
  return_inspecting: 'st-primary',
  overdue: 'st-danger',
};
// 商家承诺发货时长（与订单详情页保持一致）
const SHIP_PROMISE_SECONDS = 48 * 3600;

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const z = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function shortName(name) {
  if (!name) return '';
  const m = String(name).match(/(Pocket|Action|Quest|PICO|Vision|Switch|HomePod|H3S|Z6X|Z8X|C1|C2)\s*[\dA-Z]*/i);
  return m ? m[0] : String(name).split(' ')[0];
}
// 给 send 状态算一行倒计时副标（"剩余 12:34:56" 或 "发货超时"）
function shipCountdownText(o) {
  if (o.status !== 'send') return { text: '', overdue: false };
  const base = o.send_at || o.updated_at || o.created_at || 0;
  if (!base) return { text: '', overdue: false };
  const remain = base + SHIP_PROMISE_SECONDS - Math.floor(Date.now() / 1000);
  if (remain <= 0) return { text: '发货超时·待催促', overdue: true };
  const z = (n) => (n < 10 ? '0' + n : '' + n);
  const hh = z(Math.floor(remain / 3600));
  const mm = z(Math.floor((remain % 3600) / 60));
  const ss = z(remain % 60);
  return { text: `发货倒计时 ${hh}:${mm}:${ss}`, overdue: false };
}

/** 姓名脱敏：李 → 李；李四 → 李*；李小四 → 李*四；张三四五 → 张**五 */
function _maskName(name) {
  const s = String(name || '');
  if (s.length <= 1) return s;
  if (s.length === 2) return s[0] + '*';
  return s[0] + '*'.repeat(s.length - 2) + s[s.length - 1];
}
/** 手机号脱敏：138****1234 */
function _maskPhone(p) {
  const s = String(p || '');
  if (s.length < 7) return s;
  return s.slice(0, 3) + '****' + s.slice(-4);
}

/** 顶部主标题：已实名 → 脱敏真实姓名；否则昵称 / 兜底 */
function _displayName(u) {
  if (!u) return '尊敬的用户';
  if (u.verified && u.real_name) return _maskName(u.real_name);
  if (u.nickname) return u.nickname;
  const id = String(u.id || '');
  return id ? '支付宝用户 ' + id.slice(-4) : '尊敬的用户';
}
/** 副标题：已实名 → "已实名 · 138****1234"；否则欢迎语 */
function _displaySub(u) {
  if (!u || !u.verified) return '';
  const parts = ['已实名'];
  if (u.phone) parts.push(_maskPhone(u.phone));
  return parts.join(' · ');
}

Page({
  data: {
    user: {
      id: '',
      nickname: '',
      verified: false,
    },
    displayName: '尊敬的用户',
    displaySub: '',
    orderTabs: [
      { key: 'pay',  name: '待支付', cls: 'pay'   },
      { key: 'send', name: '待发货', cls: 'send'  },
      { key: 'recv', name: '待收货', cls: 'recv'  },
      { key: 'using',name: '租赁中', cls: 'using' },
      { key: 'all',  name: '全部订单', cls: 'all' }
    ],
    funcs: [
      { key: 'realname', name: '实名认证', cls: 'realname' },
      { key: 'fav',      name: '我的收藏', cls: 'fav' },
      { key: 'addr',     name: '我的地址', cls: 'addr' },
      { key: 'coupon',   name: '优惠券中心', cls: 'coupon' }
    ],
    activeOrders: [],
    companyName: '',   // 公司名（后台系统设置可改），底部展示
    logoUrl: '',       // 软件 LOGO（后台系统设置可改），头像处展示
  },
  onLoad() {
    // 公司名 + LOGO 走公开配置，无需登录；拉不到就保持空
    this.loadAppConfig();
  },
  async loadAppConfig() {
    try {
      const c = await get('/api/service/config', {}, { hideError: true });
      const patch = {};
      if (c && c.company_name) patch.companyName = c.company_name;
      if (c && c.logo_url) patch.logoUrl = c.logo_url;
      if (Object.keys(patch).length) this.setData(patch);
    } catch (e) {}
  },
  onShow() {
    console.log('[mine] onShow');
    this.ensureLoginThenLoad();
  },
  onHide()   { this._stopShipTimer(); },
  onUnload() { this._stopShipTimer(); },

  async ensureLoginThenLoad() {
    const app = getApp();
    const hasToken = !!(app && app.getToken && app.getToken());
    console.log('[mine] ensureLoginThenLoad hasToken=', hasToken);
    if (!hasToken) {
      console.log('[mine] 无 token，尝试静默登录');
      if (app && app.ensureLogin) {
        const t = await app.ensureLogin();
        console.log('[mine] 静默登录结果 token=', !!t);
        if (!t) {
          console.log('[mine] 静默登录失败，跳转登录页');
          my.navigateTo({ url: '/pages/login/login?redirect=' + encodeURIComponent('/pages/mine/mine') });
          return;
        }
      }
    }
    this.loadUser();
  },

  async loadUser() {
    console.log('[mine] loadUser → GET /api/user/profile');
    try {
      const u = await get('/api/user/profile', {}, { hideError: true });
      console.log('[mine] profile=', u);
      if (u) this.setData({
        user: u,
        displayName: _displayName(u),
        displaySub: _displaySub(u),
      });
      this.loadActiveOrders();
    } catch (e) {
      console.error('[mine] loadUser 异常', e);
    }
  },

  async loadActiveOrders() {
    try {
      const data = await get('/api/orders', { status: 'all' }, { hideError: true });
      const raw = (data && data.list) || [];
      const list = raw
        .filter((o) => !HIDDEN_ORDER_STATUS.has(o.status))
        .map((o) => {
          const days = o.days || 0;
          const { text: cdText, overdue } = shipCountdownText(o);
          return {
            ...o,
            _statusText: o.status_label || STATUS_TEXT[o.status] || o.status,
            _statusCls:  STATUS_CLS[o.status] || 'st-primary',
            _startDate:  fmtDate(o.created_at),
            _endDate:    fmtDate(o.created_at + days * 86400),
            _amountText: (o.amount || 0).toFixed(2),
            _shortName:  shortName(o.product_name),
            _cdText:     cdText,
            _cdOverdue:  overdue,
          };
        });
      this.setData({ activeOrders: list });
      // 至少有一单在 send 倒计时中 → 启动 1s 计时器；否则停掉
      if (list.some((o) => o.status === 'send' && !o._cdOverdue)) this._startShipTimer();
      else this._stopShipTimer();
    } catch (e) {
      console.error('[mine] loadActiveOrders 异常', e);
    }
  },

  _startShipTimer() {
    this._stopShipTimer();
    this._shipTimer = setInterval(() => {
      const list = this.data.activeOrders || [];
      let stillTicking = false;
      const patch = {};
      list.forEach((o, i) => {
        if (o.status !== 'send') return;
        const { text, overdue } = shipCountdownText(o);
        patch[`activeOrders[${i}]._cdText`] = text;
        patch[`activeOrders[${i}]._cdOverdue`] = overdue;
        if (!overdue) stillTicking = true;
      });
      if (Object.keys(patch).length) this.setData(patch);
      if (!stillTicking) this._stopShipTimer();
    }, 1000);
  },
  _stopShipTimer() {
    if (this._shipTimer) { clearInterval(this._shipTimer); this._shipTimer = null; }
  },

  onOrderDetail(e) {
    my.navigateTo({ url: '/pages/order-detail/order-detail?id=' + e.currentTarget.dataset.id });
  },

  async onOrder(e) {
    if (!(await requireLogin('查看订单需要先登录'))) return;
    my.navigateTo({ url: '/pages/order-list/order-list?key=' + e.currentTarget.dataset.key });
  },
  async onAllOrder() {
    if (!(await requireLogin('查看订单需要先登录'))) return;
    my.navigateTo({ url: '/pages/order-list/order-list?key=all' });
  },
  async onFunc(e) {
    const k = e.currentTarget.dataset.key;
    if (k === 'realname' || k === 'addr' || k === 'fav' || k === 'coupon') {
      if (!(await requireLogin('该功能需要先登录'))) return;
    }
    if (k === 'realname') {
      my.navigateTo({ url: '/pages/identity/identity' });
    } else if (k === 'addr') {
      my.navigateTo({ url: '/pages/addresses/addresses' });
    } else if (k === 'fav') {
      my.navigateTo({ url: '/pages/favorites/favorites' });
    } else if (k === 'coupon') {
      my.navigateTo({ url: '/pages/coupons/coupons' });
    } else {
      my.showToast({ content: k, type: 'none' });
    }
  }
});
