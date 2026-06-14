const { get } = require('../../utils/request.js');

Page({
  data: {
    phone: '400-000-0000',
    faqs: []           // 每条来自后端 {id, q, a}；本地额外注入 _expanded 控制展开
  },
  onLoad() {
    this.loadInfo();
    this.loadFaqs();
  },
  async loadInfo() {
    try {
      const info = await get('/api/service/info', {}, { hideError: true });
      if (info && info.phone) this.setData({ phone: info.phone });
    } catch (e) {}
  },
  async loadFaqs() {
    try {
      const raw = await get('/api/service/faqs', {}, { hideError: true });
      const faqs = (raw || []).map(f => ({ ...f, _expanded: false }));
      this.setData({ faqs });
    } catch (e) {}
  },
  onPhone() {
    my.makePhoneCall({ number: this.data.phone });
  },
  // 点击 FAQ 项展开/收起答案
  onToggleFaq(e) {
    const idx = Number(e.currentTarget.dataset.idx);
    const faqs = (this.data.faqs || []).slice();
    if (Number.isNaN(idx) || !faqs[idx]) return;
    faqs[idx] = { ...faqs[idx], _expanded: !faqs[idx]._expanded };
    this.setData({ faqs });
  }
});
