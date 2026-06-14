const CONTENT = {
  aftersale: {
    title: '售后无忧',
    subtitle: '租赁全程，您的设备由我们负责',
    navTitle: '售后无忧',
    items: [
      '非人为损害不需要承担责任',
      '来回快递不需要承担责任',
      '有小磕碰明码标价，不夸大损失',
      '人为损坏仅收成本维修费用',
      '租赁期间可以换机'
    ]
  },
  safety: {
    title: '流程安全',
    subtitle: '全程可追溯，让每一笔订单都清清楚楚',
    navTitle: '流程安全',
    items: [
      '办公室全程监控可提供',
      '来回开箱视频可提供',
      '视频内会严格验收',
      '视频外如果发现其他问题，也不会找客户负责'
    ]
  }
};

Page({
  data: {
    type: 'aftersale',
    title: '',
    subtitle: '',
    items: []
  },
  onLoad(q) {
    const type = (q && q.type === 'safety') ? 'safety' : 'aftersale';
    const c = CONTENT[type];
    my.setNavigationBar({ title: c.navTitle });
    this.setData({ type, title: c.title, subtitle: c.subtitle, items: c.items });
  },
  onCall() {
    my.makePhoneCall({ number: '400-000-0000' });
  }
});
