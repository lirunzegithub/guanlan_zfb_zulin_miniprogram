// 路由：hash 模式；每个页面单独 .vue
import { loadVue } from './sfc.js';
import { useAuth } from './auth.js';

const { createRouter, createWebHashHistory } = VueRouter;

export const menu = [
  { path: '/',              name: 'dashboard',     title: '首页',       icon: '◉' },
  { path: '/banners',       name: 'banners',       title: '轮播图',     icon: '▦' },
  { path: '/categories',    name: 'categories',    title: '分类设置',   icon: '☷' },
  { path: '/products',      name: 'products',      title: '商品管理',   icon: '⬚' },
  { path: '/orders',        name: 'orders',        title: '订单管理',   icon: '☰' },
  { path: '/refunds',       name: 'refunds',       title: '退款审核',   icon: '↺' },
  { path: '/coupons',       name: 'coupons',       title: '优惠券',     icon: '◆' },
  { path: '/comments',      name: 'comments',      title: '商品评论',   icon: '✎' },
  { path: '/faqs',          name: 'faqs',          title: '常见问题',   icon: '？' },
  { path: '/users',         name: 'users',         title: '用户管理',   icon: '◐' },
  { path: '/staffs',        name: 'staffs',        title: '工作人员',   icon: '☻' },
  { path: '/notifications', name: 'notifications', title: '回调日志',   icon: '⇄' },
  { path: '/gateway-logs',  name: 'gateway-logs',  title: '网关消息',   icon: '◇' },
  { path: '/settings',      name: 'settings',      title: '系统设置',   icon: '⚙', adminOnly: true },
];

export const router = createRouter({
  // 不写死 base：hash 路由取当前 pathname 为基准，/manager 与别名路径下均可工作
  history: createWebHashHistory(),
  routes: [
    { path: '/login',         component: loadVue('/manager-assets/pages/Login.vue'),         meta: { requiresAuth: false, hideChrome: true, title: '登录' } },
    { path: '/',              component: loadVue('/manager-assets/pages/Dashboard.vue'),     meta: { requiresAuth: true, title: '首页' } },
    { path: '/banners',       component: loadVue('/manager-assets/pages/Banners.vue'),       meta: { requiresAuth: true, title: '轮播图' } },
    { path: '/categories',    component: loadVue('/manager-assets/pages/Categories.vue'),    meta: { requiresAuth: true, title: '分类设置' } },
    { path: '/products',      component: loadVue('/manager-assets/pages/Products.vue'),      meta: { requiresAuth: true, title: '商品管理' } },
    { path: '/orders',        component: loadVue('/manager-assets/pages/Orders.vue'),        meta: { requiresAuth: true, title: '订单管理' } },
    { path: '/refunds',       component: loadVue('/manager-assets/pages/Refunds.vue'),       meta: { requiresAuth: true, title: '退款审核' } },
    { path: '/coupons',       component: loadVue('/manager-assets/pages/Coupons.vue'),       meta: { requiresAuth: true, title: '优惠券' } },
    { path: '/comments',      component: loadVue('/manager-assets/pages/Comments.vue'),      meta: { requiresAuth: true, title: '商品评论' } },
    { path: '/faqs',          component: loadVue('/manager-assets/pages/Faqs.vue'),          meta: { requiresAuth: true, title: '常见问题' } },
    { path: '/users',         component: loadVue('/manager-assets/pages/Users.vue'),         meta: { requiresAuth: true, title: '用户管理' } },
    { path: '/staffs',        component: loadVue('/manager-assets/pages/Staffs.vue'),        meta: { requiresAuth: true, title: '工作人员' } },
    { path: '/notifications', component: loadVue('/manager-assets/pages/Notifications.vue'), meta: { requiresAuth: true, title: '回调日志' } },
    { path: '/gateway-logs',  component: loadVue('/manager-assets/pages/GatewayLogs.vue'),   meta: { requiresAuth: true, title: '网关消息' } },
    { path: '/settings',      component: loadVue('/manager-assets/pages/Settings.vue'),      meta: { requiresAuth: true, adminOnly: true, title: '系统设置' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});

router.beforeEach((to, _from, next) => {
  document.title = `${to.meta.title || '管理后台'} · 观澜数码租赁`;
  const auth = useAuth();
  if (to.meta.requiresAuth !== false && !auth.isLogged()) {
    return next({ path: '/login', query: { from: to.fullPath } });
  }
  if (to.path === '/login' && auth.isLogged()) {
    return next('/');
  }
  // 仅 admin 角色可进的页面：非 admin 拦回首页并提示
  if (to.meta.adminOnly && auth.state.staff?.role !== 'admin') {
    alert('该页面仅 admin 角色可访问');
    return next('/');
  }
  next();
});
