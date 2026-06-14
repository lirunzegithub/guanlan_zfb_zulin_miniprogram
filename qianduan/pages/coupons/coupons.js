const { get, post } = require('../../utils/request.js');
const requireLogin = require('../../utils/login.js');

const TAB_KEYS = ['unused', 'used', 'expired'];

function fmt(n) {
  const v = Number(n) || 0;
  // 整数省略小数；带小数保留 2 位
  return Math.abs(v - Math.round(v)) < 0.005 ? String(Math.round(v)) : v.toFixed(2);
}

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}`;
}

function rangeText(start, end) {
  if (!start && !end) return '长期有效';
  if (start && end) return `${fmtDate(start)} - ${fmtDate(end)}`;
  if (start) return `${fmtDate(start)} 起`;
  return `至 ${fmtDate(end)}`;
}

Page({
  data: {
    tab: 'unused',
    tabs: [
      { key: 'unused',  name: '可用' },
      { key: 'used',    name: '已使用' },
      { key: 'expired', name: '已失效' },
    ],
    myList: [],
    centerList: [],
    loading: true,
  },

  onLoad() {},
  onShow() {
    this.loadAll();
  },

  async loadAll() {
    this.setData({ loading: true });
    await Promise.all([this.loadMy(), this.loadCenter()]);
    this.setData({ loading: false });
  },

  async loadMy() {
    try {
      const r = await get('/api/user/coupons', { status: this.data.tab }, { hideError: true });
      const list = (r && r.list ? r.list : []).map((it) => ({
        ...it,
        thresholdText: fmt(it.threshold),
        discountText: fmt(it.discount),
        rangeText: rangeText(it.start_at, it.end_at),
      }));
      this.setData({ myList: list });
    } catch (e) {
      this.setData({ myList: [] });
    }
  },

  async loadCenter() {
    try {
      const r = await get('/api/coupons', {}, { hideError: true });
      const list = (r && r.list ? r.list : []).map((it) => ({
        ...it,
        thresholdText: fmt(it.threshold),
        discountText: fmt(it.discount),
        rangeText: rangeText(it.start_at, it.end_at),
      }));
      this.setData({ centerList: list });
    } catch (e) {
      this.setData({ centerList: [] });
    }
  },

  onTabTap(e) {
    const tab = e.currentTarget.dataset.key;
    if (!tab || tab === this.data.tab) return;
    this.setData({ tab }, () => this.loadMy());
  },

  async onClaim(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    if (!(await requireLogin('领取优惠券需要先登录'))) return;
    try {
      await post(`/api/coupons/${id}/claim`, {});
      my.showToast({ content: '领取成功', type: 'success', duration: 1200 });
      // 同步刷新两个列表（已领数 +1；我的可用券新增一张）
      await Promise.all([this.loadMy(), this.loadCenter()]);
    } catch (e) {
      // request.js 已 toast 业务错误
    }
  },

  onGoShop() {
    my.switchTab({ url: '/pages/index/index' });
  },
});
