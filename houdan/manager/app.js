import { router, menu } from './router.js';
import { useAuth } from './auth.js';
import { api } from './api.js';

const { createApp, computed, ref, watch, onMounted } = Vue;

const App = {
  setup() {
    const auth = useAuth();
    const route = VueRouter.useRoute();
    const currentTitle = computed(() => route.meta?.title || '管理后台');
    const showChrome   = computed(() => !route.meta?.hideChrome);

    // 移动端侧栏抽屉：切换路由后自动收起
    const sidebarOpen = ref(false);
    watch(() => route.path, () => { sidebarOpen.value = false; });

    // 公司名 + LOGO：读公开配置（无需 admin 权限，operator 也能拿）
    const companyName = ref('海南光影曳动');
    const logoUrl = ref('');
    const _applyFavicon = (url) => {
      if (!url) return;
      let link = document.querySelector('link[rel="icon"]');
      if (!link) {
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
      }
      link.href = url;
    };
    onMounted(async () => {
      try {
        const r = await axios.get('/api/service/config');
        const body = r && r.data;
        const cfg = (body && body.code === 0) ? body.data : null;
        if (cfg && cfg.company_name) companyName.value = cfg.company_name;
        if (cfg && cfg.logo_url) {
          logoUrl.value = cfg.logo_url;
          _applyFavicon(cfg.logo_url);   // 浏览器标签页图标
        }
      } catch (e) {}
    });

    // 角色感知的侧栏菜单：adminOnly 的项目仅 admin 能看到
    const visibleMenu = computed(() =>
      menu.filter(m => !m.adminOnly || auth.state.staff?.role === 'admin')
    );

    const onLogout = async () => {
      try { await api.logout(); } catch (e) {}
      auth.clear();
      location.hash = '/login';
    };

    return { auth, menu: visibleMenu, currentTitle, showChrome, onLogout, companyName, logoUrl, sidebarOpen };
  },
  template: `
    <!-- 未登录页（login）不显示侧栏/顶栏 -->
    <router-view v-if="!showChrome" />

    <!-- 已登录页 -->
    <div v-else class="layout">
      <div v-if="sidebarOpen" class="sider-mask" @click="sidebarOpen = false"></div>
      <aside class="sider" :class="{ open: sidebarOpen }">
        <div class="sider-brand">
          <img v-if="logoUrl" :src="logoUrl" class="sider-logo" alt="logo" />
          观澜数码租赁
          <small>管理后台</small>
        </div>
        <nav class="sider-nav">
          <router-link
            v-for="m in menu"
            :key="m.path"
            :to="m.path"
            class="sider-item"
            active-class="active"
            exact-active-class="active">
            <span style="font-size:14px;width:18px;display:inline-block">{{ m.icon }}</span>
            <span>{{ m.title }}</span>
          </router-link>
        </nav>
        <div class="sider-foot">v0.1 · {{ companyName }}</div>
      </aside>
      <section class="main">
        <header class="topbar">
          <div class="topbar-left">
            <button class="menu-toggle" aria-label="打开菜单" @click="sidebarOpen = true">☰</button>
            <div class="topbar-title">{{ currentTitle }}</div>
          </div>
          <div class="topbar-user">
            <span style="margin-right:14px">
              <span class="muted hide-sm">已登录：</span>
              <strong>{{ auth.state.staff?.real_name || auth.state.staff?.username }}</strong>
              <span class="tag" style="margin-left:6px">{{ auth.state.staff?.role }}</span>
            </span>
            <button class="btn-link" @click="onLogout">登出</button>
          </div>
        </header>
        <main class="content">
          <router-view />
        </main>
      </section>
    </div>
  `,
};

const app = createApp(App);
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', err, info);
  if (window.__showErr) window.__showErr('[VUE] ' + (err && err.stack || err) + ' (' + info + ')');
};
app.use(router);
app.provide('api', api);
app.provide('auth', useAuth());

router.isReady().then(() => {
  app.mount('#app');
}).catch((e) => {
  console.error('[router]', e);
  if (window.__showErr) window.__showErr('[ROUTER] ' + (e && e.message || e));
});
