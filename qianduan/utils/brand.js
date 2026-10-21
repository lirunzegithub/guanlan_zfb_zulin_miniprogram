/**
 * 小程序名称：后台「系统设置 › 小程序名称」可改，导航栏标题、登录页、协议等处统一从这里取。
 *
 * 页面 json 的 defaultTitle 是编译期常量，改不了，只能在页面里 my.setNavigationBar 覆盖。
 * 上次拉到的名称存本地，冷启动先用缓存，避免每次都先闪一下旧名字。
 * 后台改名后要尽快生效，所以不做"一次启动只拉一次"，只合并同一时刻的并发请求。
 */
const { get } = require('./request.js');

const KEY = 'app_name_v1';
const FALLBACK = '观澜数码租赁';

let cached = '';
try {
  const r = my.getStorageSync({ key: KEY });
  if (r && r.data) cached = String(r.data);
} catch (e) {}

let pending = null;

function name() {
  return cached || FALLBACK;
}

/** 拉公开配置刷新名称；拉不到就沿用缓存 / 默认值 */
function load() {
  if (pending) return pending;
  pending = get('/api/service/config', {}, { hideError: true })
    .then((c) => {
      const n = String((c && c.app_name) || '').trim();
      if (n && n !== cached) {
        cached = n;
        try { my.setStorageSync({ key: KEY, data: n }); } catch (e) {}
      }
      return name();
    })
    .catch(() => name())
    .then((n) => { pending = null; return n; });
  return pending;
}

/** 用小程序名称作导航栏标题（首页 / 分类 / 客服 / 我的 这几个 tab 页），返回最新名称 */
function applyTitle() {
  my.setNavigationBar({ title: name() });
  return load().then((n) => {
    my.setNavigationBar({ title: n });
    return n;
  });
}

module.exports = { name, load, applyTitle };
