// 统一 API 封装：自动注入 token，401 → 清登录态 + 跳 /login
import { useAuth } from './auth.js';

const BASE = '/api/admin';
const _LS_TOKEN = 'manager_token';

const http = axios.create({ baseURL: BASE, timeout: 10000 });

http.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(_LS_TOKEN) || '';
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

http.interceptors.response.use(
  (res) => {
    const body = res.data || {};
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data;
      if (body.code === 401) {
        // 同时清掉响应式登录态，否则路由守卫仍认为已登录，会把 /login 跳回 /
        useAuth().clear();
        if (!location.hash.startsWith('#/login')) {
          location.hash = '/login';
        }
      }
      const err = new Error(body.msg || '接口错误');
      err.code = body.code;
      throw err;
    }
    return body;
  },
  (err) => Promise.reject(err),
);

export const api = {
  // 登录态
  login:    (username, password) => http.post('/auth/login', { username, password }),
  me:       () => http.get('/auth/me'),
  logout:   () => http.post('/auth/logout'),

  // 仪表盘
  stats:    () => http.get('/stats'),

  // 通用 CRUD
  list:     (res, params)          => http.get(`/${res}`, params ? { params } : undefined),
  get:      (res, id)              => http.get(`/${res}/${id}`),
  create:   (res, body)            => http.post(`/${res}`, body),
  update:   (res, id, body)        => http.put(`/${res}/${id}`, body),
  remove:   (res, id, params)      => http.delete(`/${res}/${id}`, params ? { params } : undefined),

  // 通知日志
  notifyLogs: (params = {}) => http.get('/notify-logs', { params }),
  clearLogs:  () => http.delete('/notify-logs'),

  // 订单的支付宝授权资金明细（alipay.fund.auth.operation.detail.query）
  orderAlipayDetail: (oid, opType = 'FREEZE') =>
    http.get(`/orders/${oid}/alipay-detail`, { params: { operation_type: opType } }),

  // 发货：自动识别快递公司（前端按 onInput 节流调用）
  identifyCourier: (no) =>
    http.get('/logistics/identify', { params: { no } }),
  // 支持的快递公司列表（下拉框）
  couriers: () => http.get('/logistics/couriers'),
  // 提交发货：{logistics_no, logistics_company?, huohao?}
  shipOrder: (oid, body) => http.post(`/orders/${oid}/ship`, body),
  // 光影库存系统：按货号查商品卡片（服务端代理）
  inventoryItem: (huohao) => http.get('/inventory/item', { params: { huohao } }),
  // 非敏感 UI 标志（货号必填开关、库存对接是否已配置），operator 可读
  uiConfig: () => http.get('/ui-config'),
  // 重试支付宝商家订单同步（alipay.merchant.order.sync）
  resyncOrder: (oid) => http.post(`/orders/${oid}/sync`),
  // 用户取消申请审核（pending_cancel 状态专用）
  approveOrderCancel: (oid) => http.post(`/orders/${oid}/cancel-approve`),
  rejectOrderCancel:  (oid, reason = '') => http.post(`/orders/${oid}/cancel-reject`, { reason }),
  // 用户归还核验（return_inspecting 状态专用）
  approveOrderReturn: (oid) => http.post(`/orders/${oid}/return-approve`),
  rejectOrderReturn:  (oid, reason = '') => http.post(`/orders/${oid}/return-reject`, { reason }),
  // 客服代用户填写寄回快递信息（using/return/overdue → return_inspecting）
  submitOrderReturnShip: (oid, body) => http.post(`/orders/${oid}/return-ship`, body),

  // 订单备注（仅工作人员可见的独立审计日志）
  listOrderNotes: (oid) => http.get(`/orders/${oid}/notes`),
  addOrderNote:   (oid, content) => http.post(`/orders/${oid}/notes`, { content }),

  // 预授权扣款（信用免押 方案 A）
  listCharges:   (oid) => http.get(`/orders/${oid}/charges`),
  chargeReasonTypes: () => http.get('/charges/reason-types'),
  createCharge:  (oid, body) => http.post(`/orders/${oid}/charges`, body),
  queryCharge:   (outTradeNo) => http.post(`/charges/${outTradeNo}/query`),
  closeCharge:   (outTradeNo) => http.post(`/charges/${outTradeNo}/close`),
  // 退款（alipay.trade.refund）
  refundCharge:  (outTradeNo, body) => http.post(`/charges/${outTradeNo}/refund`, body),
  // 退款状态查询（alipay.trade.fastpay.refund.query）
  queryRefund:   (outTradeNo, outRequestNo) =>
    http.post(`/charges/${outTradeNo}/refund/query`, { out_request_no: outRequestNo }),

  // 用户退款申请审核（PENDING → APPROVED / REJECTED）
  listRefundApplies: (status = 'pending') =>
    http.get('/refunds', { params: { status } }),
  approveRefundApply: (outTradeNo, body = {}) =>
    http.post(`/charges/${outTradeNo}/refund/approve`, body),
  rejectRefundApply: (outTradeNo, rejectReason) =>
    http.post(`/charges/${outTradeNo}/refund/reject`, { reject_reason: rejectReason }),

  // 系统设置（settings.json）
  getSettings:    () => http.get('/settings'),
  updateSettings: (patch) => http.put('/settings', patch),

  // 工作人员密码
  changePassword: (sid, oldPw, newPw) =>
    http.post(`/staffs/${sid}/password`, { old_password: oldPw, new_password: newPw }),

  // 商品分享小程序码：days 可选，带上则扫码后小程序自动选中该租期
  productQrcode: (pid, days) =>
    http.post(`/products/${pid}/qrcode`, days ? { days } : {}),

  // 用户收货地址（用户管理编辑弹窗展示）
  userAddresses: (uid) => http.get(`/users/${uid}/addresses`),

  // 文件上传：File/Blob → { url, name, size }
  upload: (file) => {
    const fd = new FormData();
    fd.append('file', file);
    return http.post('/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 30000,
    });
  },
};

export default api;
