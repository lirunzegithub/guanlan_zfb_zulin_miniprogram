const { get } = require('../../utils/request.js');

Page({
  data: {
    idx: 1,
    cats: [],
    products: [],
    keyword: '',
    searching: false,
    searchKeyword: '',
    searchTotal: 0
  },
  onLoad(q) {
    if (q && q.cat) this.setData({ idx: parseInt(q.cat, 10) });
    this.loadCats().then(() => this.loadProducts(this.data.idx));
  },
  async loadCats() {
    try {
      const cats = await get('/api/categories');
      this.setData({ cats });
    } catch (e) {}
  },
  async loadProducts(catId) {
    try {
      const data = await get('/api/products', { cat_id: catId, size: 50 });
      this.setData({ products: data.list || [] });
    } catch (e) {}
  },
  onCat(e) {
    if (this.data.searching) this.exitSearch(false);
    const id = e.currentTarget.dataset.id;
    this.setData({ idx: id });
    this.loadProducts(id);
  },
  onGoods(e) {
    my.navigateTo({ url: '/pages/product/product?id=' + e.currentTarget.dataset.id });
  },

  onSearchInput(e) {
    this.setData({ keyword: e.detail.value });
  },
  onSearchConfirm() {
    this.runSearch();
  },
  onSearchTap() {
    this.runSearch();
  },
  async runSearch() {
    const kw = (this.data.keyword || '').trim();
    if (!kw) {
      if (this.data.searching) this.exitSearch(true);
      return;
    }
    try {
      const data = await get('/api/products', { keyword: kw, size: 50 });
      const list = data.list || [];
      this.setData({
        searching: true,
        searchKeyword: kw,
        searchTotal: typeof data.total === 'number' ? data.total : list.length,
        products: list
      });
    } catch (e) {}
  },
  onSearchCancel() {
    this.exitSearch(true);
  },
  exitSearch(reload) {
    this.setData({
      searching: false,
      keyword: '',
      searchKeyword: '',
      searchTotal: 0
    });
    if (reload) this.loadProducts(this.data.idx);
  }
});
