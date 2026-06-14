const { post } = require('../../utils/request.js');

const TAB_PATHS = [
  '/pages/index/index',
  '/pages/category/category',
  '/pages/service/service',
  '/pages/mine/mine',
];

Page({
  data: {
    loading: false,
    redirect: ''
  },
  onLoad(q) {
    const redirect = (q && q.redirect) ? decodeURIComponent(q.redirect) : '';
    this.setData({ redirect });
  },

  // auth_base 静默换 user_id（不弹任何 UI；本应用未开通"获取会员基础信息"，
  // 头像昵称留空，mine 页用 user_id mask 兜底）
  onLogin() {
    if (this.data.loading) return;
    this.setData({ loading: true });
    my.getAuthCode({
      scopes: ['auth_base'],
      success: (res) => {
        const code = res && res.authCode;
        if (!code) {
          my.showToast({ content: '授权失败', type: 'fail' });
          this.setData({ loading: false });
          return;
        }
        this._exchange(code);
      },
      fail: (e) => {
        console.error('[login] getAuthCode fail', e);
        my.showToast({ content: '授权失败', type: 'fail' });
        this.setData({ loading: false });
      }
    });
  },

  async _exchange(authCode) {
    try {
      const r = await post('/api/auth/login', { auth_code: authCode });
      const app = getApp();
      if (app && app.setToken) app.setToken(r && r.token);
      my.showToast({ content: '登录成功', type: 'success' });
      this._gotoNext();
    } catch (e) {
      // request.js 已 toast
    } finally {
      this.setData({ loading: false });
    }
  },

  _gotoNext() {
    const target = this.data.redirect || '/pages/index/index';
    if (TAB_PATHS.indexOf(target.split('?')[0]) >= 0) {
      my.switchTab({ url: target });
    } else {
      my.reLaunch({ url: target });
    }
  },

  onSkip() {
    my.switchTab({ url: '/pages/index/index' });
  }
});
