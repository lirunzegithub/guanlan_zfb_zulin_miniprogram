const { get } = require('./request.js');

/**
 * 复刻 IMG_8447 的"温馨提示：当前尚未实名"前置弹窗。
 * 真实链路：调 /api/user/profile 拿当前 verified 状态，未实名则确认跳转实名页。
 *
 * @returns {Promise<boolean>} true=已实名可继续；false=未实名/用户取消
 */
module.exports = async function requireRealName() {
  let verified = false;
  try {
    const u = await get('/api/user/profile', {}, { hideError: true });
    verified = !!(u && u.verified);
  } catch (e) {}

  if (verified) return true;

  return new Promise((resolve) => {
    my.confirm({
      title: '温馨提示',
      content: '当前尚未实名，请前往实名！',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      success: (res) => {
        if (res.confirm) {
          my.navigateTo({ url: '/pages/identity/identity' });
        }
        resolve(false);
      },
    });
  });
};
