const { get, post, request } = require('../../utils/request.js');

function joinPca(p, c, d) {
  return [p, c, d].filter(Boolean).join(' ');
}
function splitPca(s) {
  // 用户手输：以空格 / 中文逗号 / 顿号分隔，取前 3 段当 省/市/区
  const arr = (s || '').split(/[\s,，、]+/).filter(Boolean);
  return { province: arr[0] || '', city: arr[1] || '', district: arr[2] || '' };
}

Page({
  data: {
    form: {
      id: 0,
      receiver_name: '', receiver_phone: '',
      province: '', city: '', district: '',
      _pca: '',
      detail: '', zip_code: '',
      is_default: true,
      source: 'manual',
    },
    canSubmit: false,
  },

  onLoad(q) {
    const id = q && parseInt(q.id || 0, 10);
    if (id) {
      my.setNavigationBar({ title: '编辑地址' });
      this.loadOne(id);
    }
  },

  async loadOne(id) {
    try {
      const a = await get('/api/user/addresses/' + id);
      const form = {
        ...this.data.form,
        ...a,
        _pca: joinPca(a.province, a.city, a.district),
      };
      this.setData({ form, canSubmit: this._can(form) });
    } catch (e) {}
  },

  onInput(e) {
    const k = e.currentTarget.dataset.k;
    const form = { ...this.data.form, [k]: e.detail.value };
    this.setData({ form, canSubmit: this._can(form) });
  },
  onInputPca(e) {
    const form = { ...this.data.form, _pca: e.detail.value };
    this.setData({ form, canSubmit: this._can(form) });
  },
  onBlurPca(e) {
    const split = splitPca(e.detail.value);
    const form = { ...this.data.form, ...split, _pca: joinPca(split.province, split.city, split.district) };
    this.setData({ form, canSubmit: this._can(form) });
  },

  toggleDefault() {
    const form = { ...this.data.form, is_default: !this.data.form.is_default };
    this.setData({ form });
  },

  _can(form) {
    if (!(form.receiver_name || '').trim()) return false;
    if (!/^1\d{10}$/.test(form.receiver_phone || '')) return false;
    const s = splitPca(form._pca);
    if (!s.province || !s.city || !s.district) return false;
    if (!(form.detail || '').trim()) return false;
    return true;
  },

  // 调支付宝原生选地址 API
  // 正确的 API 是 my.getAddress（支付宝小程序原生），不是 my.chooseAddress（那是微信的）
  // 文档返回字段：fullname, mobilePhone, country, prov, city, area, street, address
  // 限制：仅支持真机预览（IDE / 真机调试都不支持）；通常还需要在小程序后台开通"获取会员收货地址"能力
  onPickFromAlipay() {
    if (typeof my === 'undefined' || !my.getAddress) {
      my.showToast({ content: '当前环境不支持 my.getAddress，建议手动填写', type: 'none' });
      return;
    }
    my.getAddress({
      success: (res) => {
        console.log('[address-edit] my.getAddress raw=', JSON.stringify(res));
        if (String(res.resultStatus) !== '9000') {
          my.showToast({ content: '未拿到地址（status=' + res.resultStatus + '）', type: 'none' });
          return;
        }
        const d = res.result;
        const form = {
          ...this.data.form,
          receiver_name:  d.fullname,
          receiver_phone: d.mobilePhone,
          province:       d.prov,
          city:           d.city,
          district:       d.area,
          _pca:           joinPca(d.prov, d.city, d.area),
          detail:         d.address,
          zip_code:       d.postCode || '',
          source:         'alipay',
        };
        this.setData({ form, canSubmit: this._can(form) });
        my.showToast({ content: '已自动填入，请确认', type: 'success' });
      },
      fail: (err) => {
        console.error('[address-edit] my.getAddress fail', err);
        const code = err && (err.error || err.errorCode);
        const msg  = (err && err.errorMessage) || '';
        if (String(code) === '11' || /cancel|取消/i.test(msg)) {
          my.showToast({ content: '已取消', type: 'none' });
        } else if (String(code) === '4' || /权限|permission/i.test(msg)) {
          my.alert({
            title: '无权限',
            content: '小程序未开通"获取会员收货地址"能力（或用户拒绝授权）。可到支付宝开放平台 → 小程序 → 添加功能 申请开通，或直接手动填写地址。',
          });
        } else {
          my.showToast({ content: msg || '读取失败，请手动填写', type: 'none' });
        }
      },
    });
  },

  async onSubmit() {
    if (!this.data.canSubmit) {
      my.showToast({ content: '请完整填写', type: 'none' });
      return;
    }
    const f = this.data.form;
    const body = {
      receiver_name: f.receiver_name.trim(),
      receiver_phone: f.receiver_phone.trim(),
      ...splitPca(f._pca),
      detail: f.detail.trim(),
      zip_code: (f.zip_code || '').trim(),
      is_default: !!f.is_default,
      source: f.source || 'manual',
    };
    my.showLoading({ content: '保存中', mask: true });
    try {
      if (f.id) {
        await request(`/api/user/addresses/${f.id}`, { method: 'PUT', data: body });
      } else {
        await post('/api/user/addresses', body);
      }
      my.hideLoading();
      my.showToast({ content: '已保存', type: 'success' });
      setTimeout(() => my.navigateBack(), 600);
    } catch (e) {
      my.hideLoading();
    }
  },
});
