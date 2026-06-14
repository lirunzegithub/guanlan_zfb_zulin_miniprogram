// vue3-sfc-loader 选项 + loadVue 工厂
const { loadModule } = window['vue3-sfc-loader'];

const sfcOptions = {
  moduleCache: { vue: Vue },
  async getFile(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} ${url}`);
    return await res.text();
  },
  addStyle(textContent) {
    const style = document.createElement('style');
    style.textContent = textContent;
    document.head.appendChild(style);
  },
  log(type, ...args) {
    console[type === 'error' ? 'error' : 'log']('[sfc]', ...args);
  },
};

export function loadVue(path) {
  return Vue.defineAsyncComponent(() => loadModule(path, sfcOptions));
}
