const TOKEN_KEY = 'user_token_v1';
const { BASE_URL } = require('./utils/config.js');

App({
  globalData: {
    brand: '观澜数码租赁',
    primary: '#2b7cff',
    token: ''
  },
  onLaunch() {
    try {
      const r = my.getStorageSync({ key: TOKEN_KEY });
      if (r && r.data) this.globalData.token = r.data;
    } catch (e) {}
    // auth_base 是静默授权，不弹任何框；冷启动主动跑一次，避免首屏"我的/收藏"
    // 等接口先 401 再 ensureLogin 再 retry 的多余往返。
    if (!this.globalData.token) this.ensureLogin();
  },
  // 给 utils/request.js / 登录页 / 我的页用
  getToken() { return this.globalData.token || ''; },
  setToken(t) {
    this.globalData.token = t || '';
    try { my.setStorageSync({ key: TOKEN_KEY, data: t || '' }); } catch (e) {}
  },
  clearToken() {
    this.globalData.token = '';
    try { my.removeStorageSync({ key: TOKEN_KEY }); } catch (e) {}
  },

  /** 静默登录：scope=auth_base 不弹任何 UI 框，仅换 user_id；适合冷启动 + 401 自愈。
   *  并发去重：同一进程内只发一次飞行中的请求。
   *  返回 token 字符串或空串。 */
  silentLogin() { return this.ensureLogin(); },
  ensureLogin() {
    if (this._loginPromise) return this._loginPromise;
    this._loginPromise = new Promise((resolve) => {
      my.getAuthCode({
        scopes: ['auth_base'],
        success: (res) => {
          const code = res && res.authCode;
          if (!code) { resolve(''); return; }
          // 直接走 my.request，不依赖 utils/request.js 以免 401 触发递归
          my.request({
            url: BASE_URL + '/api/auth/login',
            method: 'POST',
            data: { auth_code: code },
            headers: { 'Content-Type': 'application/json' },
            dataType: 'json',
            timeout: 8000,
            success: (r) => {
              const body = r && r.data;
              const t = body && body.code === 0 && body.data && body.data.token;
              if (t) { this.setToken(t); resolve(t); }
              else { resolve(''); }
            },
            fail: () => resolve(''),
          });
        },
        fail: () => resolve(''),
      });
    }).then((t) => { this._loginPromise = null; return t; },
            (e) => { this._loginPromise = null; return ''; });
    return this._loginPromise;
  }
});
