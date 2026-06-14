const { get, post } = require('../../utils/request.js');

/** 姓名脱敏：李 → 李；李四 → 李*；李小四 → 李*四；张三四五 → 张**五 */
function _maskName(name) {
  const s = String(name || '');
  if (s.length <= 1) return s;
  if (s.length === 2) return s[0] + '*';
  return s[0] + '*'.repeat(s.length - 2) + s[s.length - 1];
}
/** 手机号脱敏：138****1234 */
function _maskPhone(p) {
  const s = String(p || '');
  if (s.length < 7) return s;
  return s.slice(0, 3) + '****' + s.slice(-4);
}
/** 身份证脱敏：1234**********5678 */
function _maskIdCard(c) {
  const s = String(c || '');
  if (s.length <= 8) return s;
  return s.slice(0, 4) + '*'.repeat(s.length - 8) + s.slice(-4);
}

/**
 * 实名认证流程（支付宝官方"身份验证"产品，alipay.user.certify.open.*）：
 *   ① POST /api/alipay/certify/init        提交姓名+身份证，拿 certify_id
 *      └ 后端 biz_code=FACE；3 个月内同一身份会复用旧 certify_id
 *   ② my.startAPVerify({ certifyId })      唤起支付宝原生人脸活体页
 *      resultStatus: 9000 成功 / 6001 取消 / 4000 系统异常
 *   ③ POST /api/alipay/certify/query       服务端再 query 一次为准（前端 9000 不可全信）
 *      passed=true → 落库 verified=true
 */
Page({
  data: {
    verified: false,
    loaded: false,
    info: { name: '', phone: '', idcard: '' },
    form: { name: '', phone: '', idcard: '' },
    agree: false,
    canSubmit: false,
    submitting: false,
  },
  onShow() {
    this._loadProfile();
  },
  async _loadProfile() {
    try {
      const u = await get('/api/user/profile', {}, { hideError: true });
      console.log('[identity] profile=', u);
      if (u && u.verified) {
        this.setData({
          verified: true,
          loaded: true,
          info: {
            name: _maskName(u.real_name),
            phone: _maskPhone(u.phone),
            idcard: _maskIdCard(u.id_card),
          },
        });
      } else {
        this.setData({ verified: false, loaded: true });
      }
    } catch (e) {
      console.error('[identity] 加载 profile 失败', e);
      this.setData({ loaded: true });
    }
  },
  onInput(e) {
    const k = e.currentTarget.dataset.k;
    const form = { ...this.data.form, [k]: e.detail.value };
    this.setData({ form, canSubmit: this._can(form, this.data.agree) });
  },
  toggleAgree() {
    const agree = !this.data.agree;
    this.setData({ agree, canSubmit: this._can(this.data.form, agree) });
  },
  openPrivacy() {
    my.navigateTo({ url: '/pages/privacy/privacy' });
  },
  onBack() {
    my.navigateBack();
  },
  _can(form, agree) {
    return agree && form.name && /^1\d{10}$/.test(form.phone) && form.idcard.length >= 15;
  },

  /** my.startAPVerify 唤起人脸活体页。
   *  小程序 SDK 中此 API 名为 startAPVerify，部分版本上也叫 ap.startAPVerify。
   *  resultStatus 取支付宝 SDK 标准码：
   *    9000  认证通过；6001 用户取消；8000 处理中；4000 系统异常；6002 网络
   *  返回前端的"通过"只是 SDK 报的状态码，最终是否真通过必须以后端 certify_query 为准。
   */
  _runCertify(certifyId, url) {
    return new Promise((resolve) => {
      const verify = (my.ap && my.ap.startAPVerify) || my.startAPVerify;
      if (!verify) {
        console.error('[identity] my.startAPVerify 不可用 —— 当前不是真机/支付宝环境');
        my.alert({
          content: '实人认证仅支持支付宝真机；IDE 模拟器不支持，请扫码到真机预览',
        });
        resolve({ ok: false, code: 'NO_SDK' });
        return;
      }
      if (!url) {
        console.error('[identity] startAPVerify 缺少 url（后端 certify.open 没返回）');
        resolve({ ok: false, code: 'NO_URL' });
        return;
      }
      verify({
        url,
        certifyId,
        success: (res) => {
          console.log('[identity] startAPVerify success', res);
          const status = String(res && res.resultStatus || '');
          resolve({ ok: status === '9000', code: status, raw: res });
        },
        fail: (err) => {
          console.error('[identity] startAPVerify fail', err);
          resolve({ ok: false, code: 'FAIL', raw: err });
        },
      });
    });
  },

  async onSubmit() {
    if (!this.data.canSubmit) {
      console.warn('[identity][submit] 表单不完整，阻断');
      my.showToast({ content: '请完整填写并勾选同意', type: 'none' });
      return;
    }
    if (this.data.submitting) return;
    this.setData({ submitting: true });
    my.showLoading({ content: '处理中', mask: true });

    const { name, phone, idcard } = this.data.form;
    console.log('[identity][submit] 开始，表单=', { name, phone, idcard });
    try {
      // ① 初始化实人认证（后端会判断 3 个月内是否复用旧 certify_id）
      console.log('[identity][1/certify-init] req=', { name, id_card: idcard });
      const init = await post('/api/alipay/certify/init', { name, id_card: idcard });
      console.log('[identity][1/certify-init] resp=', init, 'reused=', init.reused);

      // ② 跳转人脸识别
      my.hideLoading();
      const r1 = await this._runCertify(init.certify_id, init.certify_url);
      console.log('[identity][2/runCertify] result=', r1);
      if (!r1.ok) {
        if (r1.code === '6001') {
          my.showToast({ content: '已取消身份验证', type: 'none' });
        } else if (r1.code !== 'NO_SDK') {
          my.alert({ content: `人脸识别未完成 (status=${r1.code})，请重试` });
        }
        return;
      }
      my.showLoading({ content: '识别中', mask: true });

      // ③ 服务端 query 取真实结果
      const r2 = await post('/api/alipay/certify/query', {
        certify_id: init.certify_id, name, id_card: idcard, phone,
      });
      console.log('[identity][3/certify-query] resp=', r2);
      my.hideLoading();
      if (!r2.passed) {
        my.alert({ content: `人脸识别未通过：${r2.fail_reason || '未通过'}` });
        return;
      }

      my.showToast({ content: '实名认证通过', type: 'success' });
      // 重新拉 profile 切到"已认证"视图（不立即返回，给用户一眼确认）
      await this._loadProfile();
    } catch (e) {
      my.hideLoading();
      console.error('[identity][submit] 异常 raw=', e);
      try {
        console.error('[identity][submit] 异常 JSON=', JSON.stringify(e, Object.getOwnPropertyNames(e || {})));
      } catch (_) {}
      // request.js 已对 401 / 业务错误 toast；这里只对纯 Error 兜底
      if (e && e.message && !/接口/.test(e.message)) {
        my.showToast({ content: e.message, type: 'fail' });
      }
    } finally {
      this.setData({ submitting: false });
    }
  },
});
