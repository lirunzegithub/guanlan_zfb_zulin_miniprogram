const { get, request } = require('../../utils/request.js');

Page({
  data: {
    list: [],
    loaded: false,
    removing: {},  // {pid: true} 防止重复点击「取消收藏」
  },

  onShow() { this.load(); },

  async load() {
    try {
      const d = await get('/api/user/favorites');
      this.setData({ list: d.list || [], loaded: true });
    } catch (e) {
      this.setData({ loaded: true });
    }
  },

  onGoods(e) {
    const id = e.currentTarget.dataset.id;
    my.navigateTo({ url: '/pages/product/product?id=' + id });
  },

  onRemove(e) {
    const id = e.currentTarget.dataset.id;
    const name = e.currentTarget.dataset.name || '该商品';
    if (this.data.removing[id]) return;
    my.confirm({
      title: '取消收藏？',
      content: `「${name}」将从收藏列表移除`,
      confirmButtonText: '取消收藏',
      cancelButtonText: '再想想',
      success: async (r) => {
        if (!r.confirm) return;
        this.setData({ [`removing.${id}`]: true });
        try {
          await request(`/api/user/favorites/${id}`, { method: 'DELETE' });
          // 本地直接剔除，比 reload 更快
          const list = this.data.list.filter((x) => x.id !== id);
          this.setData({ list });
          my.showToast({ content: '已取消收藏', type: 'success' });
        } catch (err) {
          // request.js 已 toast 网络错；业务错也已经 toast
        } finally {
          this.setData({ [`removing.${id}`]: false });
        }
      },
    });
  },

  goShop() {
    my.switchTab({ url: '/pages/index/index' });
  },

  noop() {},
});
