const { get, post } = require('../../utils/request.js');
const requireRealName = require('../../utils/realname.js');

const STATUS_TEXT = {
  pay: '待支付', audit: '待免押',
  send: '待发货', pending_cancel: '取消审核中',
  recv: '待收货', using: '租赁中',
  return: '待归还', overdue: '已逾期',
  return_inspecting: '核验中',
  done: '已归还',
  cancelled: '已取消',
};

// 按状态决定卡片上的主操作按钮
// 注：audit（待免押）刻意不提供主操作——免押是下单时一气呵成的，
// 中途退出/失败的 audit 订单 15 分钟内会被 scheduler 自动取消，无需重试入口
function actionFor(status) {
  if (status === 'audit')          return { key: 'detail', label: '查看详情', primary: false };
  if (status === 'send')           return { key: 'detail', label: '查看物流', primary: false };
  if (status === 'pending_cancel') return { key: 'detail', label: '查看进度', primary: false };
  if (status === 'using')          return { key: 'detail', label: '查看订单', primary: false };
  return null;
}

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const z = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

function shortName(name) {
  if (!name) return '';
  const m = name.match(/(Pocket|Action|Quest|PICO|Vision|Switch|HomePod|H3S|Z6X|Z8X|C1|C2)\s*[\dA-Z]*/i);
  return m ? m[0] : name.split(' ')[0];
}

Page({
  data: {
    cur: 'all',
    tabs: [],
    list: [],
    loaded: false,
  },
  onLoad(q) {
    if (q && q.key) {
      const map = { pay: 'pay', send: 'send', recv: 'recv', using: 'using', all: 'all' };
      this.setData({ cur: map[q.key] || q.key });
    }
    this.loadTabs().then(() => this.loadList());
  },
  onShow() {
    if (this.data.loaded) this.loadList();
  },
  async loadTabs() {
    try {
      const tabs = await get('/api/orders/tabs');
      this.setData({
        tabs: [{ key: 'all', name: '全部' }, ...tabs],
      });
    } catch (e) {}
  },
  async loadList() {
    try {
      const data = await get('/api/orders', { status: this.data.cur });
      const list = (data.list || []).map((o) => {
        const days = o.days || 0;
        return {
          ...o,
          _statusText: o.status_label || STATUS_TEXT[o.status] || o.status,
          _startDate: fmtDate(o.created_at),
          _endDate: fmtDate(o.created_at + days * 86400),
          _amountText: (o.amount || 0).toFixed(2),
          _shortName: shortName(o.product_name) + ' 租赁',
          _action: actionFor(o.status),
          _canCancel: ['audit', 'pay'].includes(o.status),
        };
      });
      this.setData({ list, loaded: true });
    } catch (e) {
      this.setData({ loaded: true });
    }
  },
  onTab(e) {
    this.setData({ cur: e.currentTarget.dataset.key, list: [], loaded: false });
    this.loadList();
  },
  goHome() {
    my.switchTab({ url: '/pages/index/index' });
  },
  goDetail(e) {
    my.navigateTo({ url: '/pages/order-detail/order-detail?id=' + e.currentTarget.dataset.id });
  },
  noop() {},
  async onCancel(e) {
    const id = e.currentTarget.dataset.id;
    my.confirm({
      title: '确认取消订单？',
      content: '取消后无法恢复',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await post(`/api/orders/${id}/cancel`, {});
          my.showToast({ content: '已取消', type: 'success' });
          this.loadList();
        } catch (err) {
          my.showToast({ content: err.message || '取消失败', type: 'fail' });
        }
      },
    });
  },
  async onCredit(e) {
    const id = e.currentTarget.dataset.id;
    const ok = await requireRealName();
    if (!ok) return;
    my.navigateTo({ url: '/pages/order-detail/order-detail?id=' + id + '&credit=1' });
  },
  onAction(e) {
    const { id, key } = e.currentTarget.dataset;
    // 所有动作都跳详情页，详情页根据 status 自处理（人脸/免押/物流）
    my.navigateTo({ url: '/pages/order-detail/order-detail?id=' + id + (key === 'credit' ? '&credit=1' : '') });
  },
});
