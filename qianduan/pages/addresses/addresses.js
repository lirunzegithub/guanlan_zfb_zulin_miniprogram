const { get, post, request } = require('../../utils/request.js');

function maskPhone(p) {
  if (!p || p.length < 7) return p || '';
  return p.slice(0, 3) + '****' + p.slice(-4);
}

Page({
  data: { list: [], loaded: false },

  onShow() { this.load(); },

  async load() {
    try {
      const d = await get('/api/user/addresses');
      const list = (d.list || []).map((a) => ({ ...a, _phoneMasked: maskPhone(a.receiver_phone) }));
      this.setData({ list, loaded: true });
    } catch (e) {
      this.setData({ loaded: true });
    }
  },

  onAdd()  { my.navigateTo({ url: '/pages/address-edit/address-edit' }); },
  onEdit(e) {
    my.navigateTo({ url: '/pages/address-edit/address-edit?id=' + e.currentTarget.dataset.id });
  },

  async onSetDefault(e) {
    const id = e.currentTarget.dataset.id;
    try { await post(`/api/user/addresses/${id}/default`, {}); this.load(); }
    catch (err) { my.showToast({ content: err.message || '设置失败', type: 'fail' }); }
  },

  onDelete(e) {
    const id = e.currentTarget.dataset.id;
    my.confirm({
      title: '确认删除该地址？',
      content: '删除后无法恢复',
      success: async (r) => {
        if (!r.confirm) return;
        try {
          await request(`/api/user/addresses/${id}`, { method: 'DELETE' });
          my.showToast({ content: '已删除', type: 'success' });
          this.load();
        } catch (err) { my.showToast({ content: err.message || '删除失败', type: 'fail' }); }
      },
    });
  },

  noop() {},
});
