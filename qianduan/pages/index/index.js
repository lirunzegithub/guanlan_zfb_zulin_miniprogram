const { get } = require('../../utils/request.js');

Page({
  data: {
    hero: { title: 'Meta Quest 3', sub: '跳进游戏世界' },
    heroes: [],   // 后台配置的顶部 banner 全量（按 slot 排序），有图就走 swiper 轮播
    products: [],
    verified: false,   // 当前用户是否已实名（决定三宫格 q1 是否切到"已认证"绿色态）
  },
  onLoad() {
    this.loadAll();
  },
  // 从实名页 / 我的页返回时，verified 可能刚变，需要重新拉一次
  onShow() {
    this.loadVerified();
  },
  onPullDownRefresh() {
    this.loadAll().then(() => my.stopPullDownRefresh());
  },

  // 单独抽出来：静默拉一次用户实名状态。未登录时拉不到也无所谓，
  // q1 维持默认未认证态，hideError 不打扰用户。
  async loadVerified() {
    try {
      const u = await get('/api/user/profile', {}, { hideError: true });
      const v = !!(u && u.verified);
      if (v !== this.data.verified) this.setData({ verified: v });
    } catch (e) {
      if (this.data.verified) this.setData({ verified: false });
    }
  },
  async loadAll() {
    try {
      const [banners, list] = await Promise.all([
        get('/api/banners', {}, { hideError: true }),
        get('/api/products', { size: 20 })
      ]);
      // heroes 字段是新加的；兼容老后端没返回时退化用 hero 单值
      const heroes = Array.isArray(banners && banners.heroes)
        ? banners.heroes
        : ((banners && banners.hero && banners.hero.image_url) ? [banners.hero] : []);
      this.setData({
        hero: (banners && banners.hero) || this.data.hero,
        heroes,
        products: (list && list.list) || []
      });
      // 实名状态并入首屏：第一次进入小程序就显示正确颜色
      this.loadVerified();
    } catch (e) {
      // 错误已在 request 内 toast，这里兜底
    }
  },
  // 点击轮播图：按 link_type 跳转
  onBannerTap(e) {
    const id = e.currentTarget.dataset.id;
    const b = (this.data.heroes || []).find((x) => x.id === id);
    if (!b) return;
    const v = (b.link_value || '').trim();
    if (b.link_type === 'product' && v) {
      my.navigateTo({ url: '/pages/product/product?id=' + v });
    } else if (b.link_type === 'category' && v) {
      my.switchTab && my.switchTab({ url: '/pages/category/category' });
    } else if (b.link_type === 'page' && v) {
      my.navigateTo({ url: v.startsWith('/') ? v : '/' + v });
    } else if (b.link_type === 'external' && v) {
      // 小程序内打开外链需要 webview 页或调用 my.navigateToMiniProgram，这里只兜底复制
      my.setClipboard({
        text: v,
        success: () => my.showToast({ content: '链接已复制', type: 'success' }),
      });
    }
  },
  onCreditAuth() {
    my.navigateTo({ url: '/pages/identity/identity' });
  },
  onAftersale() {
    my.navigateTo({ url: '/pages/info/info?type=aftersale' });
  },
  onSafety() {
    my.navigateTo({ url: '/pages/info/info?type=safety' });
  },
  onGoods(e) {
    my.navigateTo({ url: '/pages/product/product?id=' + e.currentTarget.dataset.id });
  }
});
