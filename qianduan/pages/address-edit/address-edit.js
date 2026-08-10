/** 新增 / 编辑收货地址
 *
 *  省市区走 my.multiLevelSelect + 后端下发的区划码表（utils/regions.js），
 *  用户不需要打字，也就不存在「格式对不对」的问题。同时存下三个区划码，
 *  文本字段保留作为展示和存量数据兼容。
 *
 *  两条降级路径，都必须留着：
 *    1. 码表拉不到（断网 / 接口挂）→ 那一栏退回手输，按空格拆省市区，码留空
 *    2. my.getAddress 导入的地址只有文本 → 按名字反查补码，查不到就留空
 *  所以**任何地方都不能假设区划码非空**。
 *
 *  层级不齐是常态，校验只要求省 + 市：仙桃/潜江/天门这类省直管县级市没有区县级。
 */
const { get, post, request } = require('../../utils/request.js');
const regions = require('../../utils/regions.js');

function joinPca(p, c, d) {
  return [p, c, d].filter(Boolean).join(' ');
}
function splitPca(s) {
  // 仅手输降级路径用：空格 / 中文逗号 / 顿号分隔，取前 3 段当 省/市/区
  // 只填两段是合法的（省直管县级市），district 留空
  const arr = (s || '').split(/[\s,，、]+/).filter(Boolean);
  return { province: arr[0] || '', city: arr[1] || '', district: arr[2] || '' };
}

const EMPTY_CODES = { province_code: '', city_code: '', district_code: '' };

Page({
  data: {
    form: {
      id: 0,
      receiver_name: '', receiver_phone: '',
      province: '', city: '', district: '',
      ...EMPTY_CODES,
      _pca: '',
      detail: '', zip_code: '',
      is_default: true,
      source: 'manual',
    },
    canSubmit: false,
    pcaFallback: false,   // true = 码表不可用，省市区退回手输
  },

  onLoad(q) {
    const id = q && parseInt(q.id || 0, 10);
    if (id) {
      my.setNavigationBar({ title: '编辑地址' });
      this.loadOne(id);
    }
    // 预热码表：进页面就后台拉，等用户点到省市区时通常已经就绪
    regions.load().catch(() => {});
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

  // ---- 省市区：选择器（主路径） ----
  async onPickRegion() {
    let doc;
    try {
      doc = await regions.load();
    } catch (e) {
      console.error('[address-edit] 区划码表加载失败，降级手输', e);
      this.setData({ pcaFallback: true });
      my.showToast({ content: '地区数据加载失败，请手动填写省市区', type: 'none' });
      return;
    }
    if (typeof my === 'undefined' || !my.multiLevelSelect) {
      this.setData({ pcaFallback: true });
      return;
    }

    // 只传 title + list：multiLevelSelect 的其余可选参数（如自定义字段名）语义
    // 各版本基础库不完全一致，传错会让整份 list 解析不出来。编辑地址时重选一次成本很低。
    my.multiLevelSelect({
      title: '请选择所在地区',
      list: doc.list,
      success: (res) => {
        const picked = (res && res.result) || [];
        if (!picked.length) return;
        const names = picked.map((x) => x && x.name).filter(Boolean);
        // 不依赖回调里带不带 code，一律按名字回查，行为稳定
        const hit = regions.lookupByNames(doc.list, names);
        const form = {
          ...this.data.form,
          province: names[0] || '',
          city:     names[1] || '',
          district: names[2] || '',
          province_code: (hit[0] && hit[0].code) || '',
          city_code:     (hit[1] && hit[1].code) || '',
          district_code: (hit[2] && hit[2].code) || '',
          _pca: joinPca(names[0], names[1], names[2]),
        };
        this.setData({ form, canSubmit: this._can(form) });
      },
      fail: (err) => {
        // 用户取消也会走这里，不打扰
        console.log('[address-edit] multiLevelSelect fail/cancel', err);
      },
    });
  },

  // ---- 省市区：手输（降级路径） ----
  onInputPca(e) {
    const v = e.detail.value;
    // 手输的地址没有可信的区划码，一并清掉，避免码和文本对不上
    const form = { ...this.data.form, ...EMPTY_CODES, ...splitPca(v), _pca: v };
    this.setData({ form, canSubmit: this._can(form) });
  },
  onBlurPca(e) {
    const s = splitPca(e.detail.value);
    const form = { ...this.data.form, ...s, _pca: joinPca(s.province, s.city, s.district) };
    this.setData({ form, canSubmit: this._can(form) });
  },

  toggleDefault() {
    const form = { ...this.data.form, is_default: !this.data.form.is_default };
    this.setData({ form });
  },

  _can(form) {
    if (!(form.receiver_name || '').trim()) return false;
    if (!/^1\d{10}$/.test(form.receiver_phone || '')) return false;
    // 只要省 + 市；区县允许为空（省直管县级市）
    if (!(form.province || '').trim() || !(form.city || '').trim()) return false;
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
          ...EMPTY_CODES,
          _pca:           joinPca(d.prov, d.city, d.area),
          detail:         d.address,
          zip_code:       d.postCode || '',
          source:         'alipay',
        };
        this.setData({ form, canSubmit: this._can(form) });
        my.showToast({ content: '已自动填入，请确认', type: 'success' });
        // 拿到的只有文本，顺带按名字反查补上区划码；查不到就保持为空
        regions.load().then((doc) => {
          const codes = regions.codesFromNames(doc.list, d.prov, d.city, d.area);
          if (!codes.province_code) return;
          const cur = this.data.form;
          if (cur.province !== d.prov || cur.city !== d.city) return;  // 用户已改动，别覆盖
          this.setData({ form: { ...cur, ...codes } });
        }).catch(() => {});
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
      my.showToast({ content: this._missingHint(), type: 'none' });
      return;
    }
    const f = this.data.form;
    const body = {
      receiver_name: f.receiver_name.trim(),
      receiver_phone: f.receiver_phone.trim(),
      province: (f.province || '').trim(),
      city: (f.city || '').trim(),
      district: (f.district || '').trim(),
      province_code: f.province_code || '',
      city_code: f.city_code || '',
      district_code: f.district_code || '',
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

  // 「请完整填写」太笼统，直接点出缺哪一项
  _missingHint() {
    const f = this.data.form;
    if (!(f.receiver_name || '').trim()) return '请填写收货人';
    if (!/^1\d{10}$/.test(f.receiver_phone || '')) return '请填写正确的 11 位手机号';
    if (!(f.province || '').trim() || !(f.city || '').trim()) {
      return this.data.pcaFallback ? '省市区请用空格分开，如：湖北省 仙桃市' : '请选择所在地区';
    }
    if (!(f.detail || '').trim()) return '请填写详细地址';
    return '请完整填写';
  },
});
