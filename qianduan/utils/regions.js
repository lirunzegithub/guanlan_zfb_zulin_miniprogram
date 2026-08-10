/** 行政区划码表：加载 + 缓存 + 反查
 *
 *  数据由后端 /api/regions 下发（约 130KB，gzip 后 30KB），结构直接就是
 *  my.multiLevelSelect 要的 [{ name, code, subList: [...] }]。
 *
 *  缓存三层：
 *    内存      —— 同一次冷启动内只解析一次
 *    storage   —— 跨冷启动复用；写失败（超配额等）静默降级，不影响功能
 *    version   —— 每次 load 顺带异步校验一次 /api/regions/version，
 *                 对不上就后台悄悄更新缓存，下次进页面生效（不打断当前操作）
 *
 *  注意层级不齐是常态，任何调用方都不能假设一定有三级：
 *    - 省直管县级市（仙桃/潜江/天门…）只有省、市两级，区级为空
 *    - 不设区的地级市（东莞/中山/儋州/嘉峪关）区级位置是镇/街道，码是 9 位
 */
const { get } = require('./request.js');

const DATA_KEY = 'regions_data';
const VER_KEY = 'regions_version';

let _mem = null;        // { version, list }
let _loading = null;    // 并发 load 复用同一个 Promise
let _checked = false;   // 本次冷启动是否已校验过版本

function _readStorage() {
  try {
    const r = my.getStorageSync({ key: DATA_KEY });
    const d = r && r.data;
    if (d && d.list && d.list.length) return d;
  } catch (e) {}
  return null;
}

function _writeStorage(doc) {
  // 130KB 接近部分端上的单 key 上限，写不进去就算了，下次冷启动重拉即可
  try {
    my.setStorageSync({ key: DATA_KEY, data: doc });
    my.setStorageSync({ key: VER_KEY, data: doc.version });
  } catch (e) {
    console.warn('[regions] 缓存写入失败，降级为每次冷启动重拉', e);
  }
}

async function _fetch() {
  const d = await get('/api/regions', {}, { hideError: true });
  if (!d || !d.list || !d.list.length) throw new Error('区划数据为空');
  return { version: d.version || '', list: d.list };
}

// 后台校验版本：不 await，不影响当前这次选择
function _revalidate(current) {
  if (_checked) return;
  _checked = true;
  get('/api/regions/version', {}, { hideError: true })
    .then((r) => {
      const v = r && r.version;
      if (!v || v === current) return;
      console.log('[regions] 码表有更新', current, '->', v);
      return _fetch().then((doc) => { _mem = doc; _writeStorage(doc); });
    })
    .catch(() => {});
}

/** 拿整份码表；失败时 reject，调用方自行降级 */
function load() {
  if (_mem) { _revalidate(_mem.version); return Promise.resolve(_mem); }
  if (_loading) return _loading;

  const cached = _readStorage();
  if (cached) {
    _mem = cached;
    _revalidate(cached.version);
    return Promise.resolve(cached);
  }

  _loading = _fetch()
    .then((doc) => { _mem = doc; _writeStorage(doc); _checked = true; return doc; })
    .catch((e) => { throw e; })
    .then((doc) => { _loading = null; return doc; }, (e) => { _loading = null; throw e; });
  return _loading;
}

/** 按名字逐级回查，返回 [{name, code}, ...]；任一级对不上就返回已匹配到的部分 */
function lookupByNames(list, names) {
  const out = [];
  let nodes = list || [];
  for (const n of names) {
    if (!n) break;
    const hit = nodes.find((x) => x.name === n);
    if (!hit) break;
    out.push({ name: hit.name, code: hit.code });
    nodes = hit.subList || [];
  }
  return out;
}

/** 文本地址反查区划码（给 my.getAddress 导入的地址补码，匹配不上就留空） */
function codesFromNames(list, province, city, district) {
  const hit = lookupByNames(list, [province, city, district]);
  return {
    province_code: (hit[0] && hit[0].code) || '',
    city_code:     (hit[1] && hit[1].code) || '',
    district_code: (hit[2] && hit[2].code) || '',
  };
}

module.exports = { load, lookupByNames, codesFromNames };
