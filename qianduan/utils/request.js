const { BASE_URL } = require('./config.js');

// 同时只发起一次 reLaunch 到登录页，避免多个并发请求都被拦时重复跳
let _redirectingToLogin = false;

function _gotoLogin() {
  if (_redirectingToLogin) return;
  _redirectingToLogin = true;
  // 把当前页带回 redirect=，登录后回到原页
  const pages = (typeof getCurrentPages === 'function') ? getCurrentPages() : [];
  const cur = pages[pages.length - 1];
  const route = cur && cur.route ? ('/' + cur.route) : '';
  // 已经在登录页就别再跳了
  if (route === '/pages/login/login') { _redirectingToLogin = false; return; }
  const url = '/pages/login/login' + (route ? ('?redirect=' + encodeURIComponent(route)) : '');
  my.reLaunch({ url, complete: () => { _redirectingToLogin = false; } });
}

/**
 * 单次请求；不在这里 toast，全部交给外层 request 决定。
 * @returns Promise<data>  失败时 reject 一个带 __auth401 或 __network 标记的对象
 */
function _send(path, opts, app) {
  const { method = 'GET', data = {} } = opts;
  const headers = { 'Content-Type': 'application/json' };
  const token = app && app.getToken && app.getToken();
  if (token) headers['Authorization'] = 'Bearer ' + token;

  const tag = `[req] ${method} ${path}`;
  console.log(tag, 'send', { data, hasToken: !!token });
  return new Promise((resolve, reject) => {
    my.request({
      url: BASE_URL + path,
      method,
      data,
      headers,
      dataType: 'json',
      timeout: 8000,
      success: (res) => {
        console.log(tag, 'resp', { status: res && res.status, body: res && res.data });
        const body = res.data || {};
        if (res.status === 401 || body.code === 401) {
          reject({ __auth401: true, code: 401, msg: '未登录或登录已过期' });
          return;
        }
        if (body.code === 0) {
          resolve(body.data);
        } else {
          reject({ code: body.code, msg: body.msg || '接口异常' });
        }
      },
      fail: (err) => {
        console.error(tag, 'fail', err);
        // 在支付宝小程序里，部分版本会把 401 当成网络错误回 fail；
        // 这里不直接 toast，留给外层判断是否要先尝试静默重登。
        reject({ __network: true, raw: err });
      },
    });
  });
}

function request(path, opts = {}) {
  const { loading = false, _retry = false, hideError = false } = opts;
  if (loading) my.showLoading({ content: '加载中', mask: true });

  const app = (typeof getApp === 'function') ? getApp() : null;
  const hadToken = !!(app && app.getToken && app.getToken());

  const cleanup = () => { if (loading) my.hideLoading(); };

  return _send(path, opts, app).then(
    (data) => { cleanup(); return data; },
    async (err) => {
      const isAuth = err && err.__auth401;
      const isNet  = err && err.__network;

      // 401，或带 token 时碰到 fail（疑似 401 被当成网络错误）：触发 ensureLogin 重登一次
      if (!_retry && app && app.ensureLogin && (isAuth || (isNet && hadToken))) {
        const t = await app.ensureLogin();
        if (t) {
          return _send(path, { ...opts, _retry: true }, app).then(
            (data) => { cleanup(); return data; },
            (err2) => {
              cleanup();
              if (err2 && err2.__auth401) {
                if (app.clearToken) app.clearToken();
                _gotoLogin();
                throw { code: 401, msg: '未登录或登录已过期' };
              }
              if (err2 && err2.__network && !hideError) {
                my.showToast({ content: '网络异常，请检查后端', type: 'fail' });
              } else if (err2 && !err2.__network && !hideError) {
                my.showToast({ content: err2.msg || '接口异常', type: 'fail' });
              }
              throw err2;
            }
          );
        }
      }

      cleanup();
      if (isAuth) {
        if (app && app.clearToken) app.clearToken();
        _gotoLogin();
        throw { code: 401, msg: '未登录或登录已过期' };
      }
      if (isNet) {
        if (!hideError) my.showToast({ content: '网络异常，请检查后端', type: 'fail' });
        throw err;
      }
      // 业务错误（code != 0 且非 401）
      if (!hideError) my.showToast({ content: err && err.msg || '接口异常', type: 'fail' });
      throw err;
    }
  );
}

const get  = (path, data, opts = {}) => request(path, { ...opts, method: 'GET',  data });
const post = (path, data, opts = {}) => request(path, { ...opts, method: 'POST', data });

module.exports = { request, get, post, BASE_URL };
