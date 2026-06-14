/**
 * 登录门卫：在执行"需要登录的用户动作"前先确保有可用 token。
 *
 * 优先级：
 *   1) 本地已有 token → 直接放行（不验真伪；失败由 request.js 401 兜底）
 *   2) confirm 提示用户 → 同意则尝试 silentLogin（auth_base，无 UI）
 *   3) 静默失败（用户拒授权 / 网络挂）→ 跳显式登录页让用户手动一键登录
 *
 * 返回 Promise<boolean>：true = 已登录可继续；false = 未登录（已提示或已跳转）
 *
 * 用法：
 *   const ok = await requireLogin('收藏需要先登录');
 *   if (!ok) return;
 *   // ……继续业务
 */
module.exports = async function requireLogin(reason) {
  const app = (typeof getApp === 'function') ? getApp() : null;
  if (!app) return false;

  if (app.getToken && app.getToken()) return true;

  // 先静默试一次（多数情况用户授权过 auth_base，能直接拿到 code 换 token，零打扰）
  if (app.silentLogin) {
    const t = await app.silentLogin();
    if (t) return true;
  }

  // 静默不行才弹 confirm 走显式登录页
  return new Promise((resolve) => {
    my.confirm({
      title: '需要登录',
      content: reason || '该功能需要授权登录后才能使用',
      confirmButtonText: '一键登录',
      cancelButtonText: '稍后',
      success: (res) => {
        if (res.confirm) {
          const pages = (typeof getCurrentPages === 'function') ? getCurrentPages() : [];
          const cur = pages[pages.length - 1];
          const route = cur && cur.route ? ('/' + cur.route) : '';
          const url = '/pages/login/login' + (route ? ('?redirect=' + encodeURIComponent(route)) : '');
          my.navigateTo({ url });
        }
        resolve(false);
      },
      fail: () => resolve(false),
    });
  });
};
