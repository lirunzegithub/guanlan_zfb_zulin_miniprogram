const { get, post } = require('../../utils/request.js');

// 客服电话（与 order-detail 保持一致）
const SERVICE_PHONE = '400-000-0000';

Page({
  data: {
    oid: '',
    otn: '',
    loaded: false,
    submitting: false,
    reason: '',
    // 扣款明细（从 /api/orders/{oid}/charges 里挑出来的对应一条）
    t: {},
  },

  onLoad(q) {
    const oid = q && q.oid;
    const otn = q && q.otn;
    if (!oid || !otn) {
      my.showToast({ content: '参数缺失', type: 'fail' });
      setTimeout(() => my.navigateBack(), 800);
      return;
    }
    this.setData({ oid, otn });
    this.loadCharge();
  },

  async loadCharge() {
    const { oid, otn } = this.data;
    try {
      const r = await get(`/api/orders/${oid}/charges`);
      const list = r.list || [];
      const t = list.find((x) => x.id === otn);
      if (!t) {
        my.alert({
          title: '未找到扣款记录',
          content: '该扣款可能已被删除或不属于此订单',
          buttonText: '返回',
          success: () => my.navigateBack(),
        });
        return;
      }
      // 给金额加个 _refundable_text 方便模板显示
      t._refundable_text = (Number(t.refundable_amount) || 0).toFixed(2);
      this.setData({ t, loaded: true });
    } catch (e) {
      my.showToast({ content: e.message || '加载失败', type: 'fail' });
      setTimeout(() => my.navigateBack(), 1000);
    }
  },

  onReasonInput(e) {
    this.setData({ reason: (e.detail.value || '').slice(0, 500) });
  },

  onCallService() {
    my.makePhoneCall({ number: SERVICE_PHONE });
  },

  async onSubmit() {
    const { oid, otn, reason, submitting, t } = this.data;
    if (submitting) return;
    if (reason.length < 5) {
      my.showToast({ content: '退款理由至少 5 个字', type: 'none' });
      return;
    }
    if (!(Number(t.refundable_amount) > 0)) {
      my.showToast({ content: '该扣款已无可退金额', type: 'none' });
      return;
    }
    const ok = await new Promise((resolve) => {
      my.confirm({
        title: '确认发起退款？',
        content:
          `本次申请退款 ¥${t._refundable_text}\n` +
          `审核需 2 个工作日内完成；通过后将原路退回。`,
        confirmButtonText: '确认提交',
        cancelButtonText: '再想想',
        success: (r) => resolve(!!r.confirm),
      });
    });
    if (!ok) return;

    this.setData({ submitting: true });
    try {
      const r = await post(`/api/orders/${oid}/charges/${otn}/refund-apply`, { reason });
      my.alert({
        title: '已提交退款申请',
        content: r.review_hint || '商家将在 2 个工作日内审核',
        buttonText: '返回订单',
        success: () => my.navigateBack(),
      });
    } catch (e) {
      my.showToast({ content: e.message || '提交失败', type: 'fail' });
    } finally {
      this.setData({ submitting: false });
    }
  },
});
