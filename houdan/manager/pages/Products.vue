<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">商品管理</div>
      <div class="row" style="gap:8px">
        <input class="input kw-input" v-model="kw" placeholder="搜索商品名" />
        <select class="select cat-select" v-model="filterCat">
          <option :value="0">全部分类</option>
          <option v-for="c in cats" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
        <button class="btn" @click="openNew">＋ 新增</button>
      </div>
    </div>

    <table class="table prod-table">
      <thead>
        <tr>
          <th style="width:60px">ID</th>
          <th style="width:70px">封面</th>
          <th>商品名</th>
          <th style="width:120px">分类</th>
          <th style="width:90px">押金</th>
          <th style="width:90px">销量</th>
          <th style="width:140px">库存</th>
          <th style="width:80px">状态</th>
          <th style="width:160px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in filtered" :key="p.id">
          <td>{{ p.id }}</td>
          <td>
            <span class="swatch" :style="rowCoverStyle(p)"></span>
          </td>
          <td>
            <div>{{ p.name }}</div>
            <div class="muted">{{ p.subtitle }}</div>
          </td>
          <td>{{ catName(p.cat_id) }}</td>
          <td>¥{{ p.deposit_amount || 0 }}</td>
          <td>{{ p.sales }}</td>
          <td>
            <div class="stock-edit">
              <input
                type="number"
                min="0"
                class="input stock-input"
                v-model.number="p.stock"
                :disabled="!!stockSaving[p.id]"
                @change="saveStock(p)"
                @keyup.enter="saveStock(p)"
              />
              <span v-if="stockSaving[p.id]" class="stock-flag saving">保存中</span>
              <span v-else-if="stockOk[p.id]" class="stock-flag ok">✓ 已存</span>
            </div>
          </td>
          <td>
            <span :class="['tag', statusCls(p)]">{{ statusText(p) }}</span>
          </td>
          <td>
            <button class="btn-link" @click="openEdit(p)">编辑</button>
            <button class="btn-link danger" @click="remove(p)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !filtered.length"><td colspan="9" class="empty">暂无数据</td></tr>
        <tr v-if="loading"><td colspan="9" class="loading">加载中...</td></tr>
      </tbody>
    </table>

    <!-- 移动端：卡片式商品列表（与上方表格互斥显示） -->
    <div class="prod-cards">
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else-if="!filtered.length" class="empty">暂无数据</div>
      <div v-for="p in filtered" :key="'m-' + p.id" class="prod-card">
        <div class="pc-head">
          <span class="muted">#{{ p.id }} · {{ catName(p.cat_id) }}</span>
          <span :class="['tag', statusCls(p)]">{{ statusText(p) }}</span>
        </div>

        <div class="pc-main">
          <span class="pc-cover" :style="rowCoverStyle(p)"></span>
          <div class="pc-info">
            <div class="pc-name">{{ p.name }}</div>
            <div class="muted" v-if="p.subtitle">{{ p.subtitle }}</div>
            <div class="pc-meta">
              <span>押金 <b>¥{{ p.deposit_amount || 0 }}</b></span>
              <span>销量 <b>{{ p.sales }}</b></span>
            </div>
          </div>
        </div>

        <div class="pc-foot">
          <div class="stock-edit">
            <span class="muted">库存</span>
            <input
              type="number"
              min="0"
              class="input stock-input"
              v-model.number="p.stock"
              :disabled="!!stockSaving[p.id]"
              @change="saveStock(p)"
              @keyup.enter="saveStock(p)"
            />
            <span v-if="stockSaving[p.id]" class="stock-flag saving">保存中</span>
            <span v-else-if="stockOk[p.id]" class="stock-flag ok">✓ 已存</span>
          </div>
          <div class="pc-actions">
            <button class="btn-link" @click="openEdit(p)">编辑</button>
            <button class="btn-link danger" @click="remove(p)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 编辑弹窗（含主要字段；高级字段直接给 JSON 编辑） -->
  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal" style="width:680px">
      <div class="modal-h">{{ form.id ? '编辑商品' : '新增商品' }}</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">商品名 *</div>
          <input class="input" v-model="form.name" />
        </div>
        <div class="field">
          <div class="label">副标题</div>
          <input class="input" v-model="form.subtitle" />
        </div>
        <div class="field">
          <div class="label">分类</div>
          <select class="select" v-model.number="form.cat_id">
            <option :value="0">未分类</option>
            <option v-for="c in cats" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>

        <!-- 价格分段（tiered pricing）：连续多段，每段「第 N 天起 ¥X/天」 -->
        <div class="field">
          <div class="label">价格分段 price_tiers</div>
          <div class="tiers-help">
            连续多段计费：第一段必须从「第 1 天起」；每段单价 = 该天起的每日租金。
            租 N 天总价 = 各段在 N 天内覆盖的天数 × 该段单价之和。
          </div>
          <table class="tiers-table">
            <thead>
              <tr>
                <th style="width:50px">#</th>
                <th>第 N 天起</th>
                <th>¥/天</th>
                <th style="width:90px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(t, i) in (form.price_tiers || [])" :key="i">
                <td>{{ i + 1 }}</td>
                <td>
                  <input
                    type="number"
                    class="input"
                    :value="t.from"
                    :disabled="i === 0"
                    :min="i === 0 ? 1 : ((form.price_tiers[i-1]?.from || 0) + 1)"
                    @input="onTierFromInput(i, $event.target.value)"
                  />
                </td>
                <td>
                  <input
                    type="number"
                    class="input"
                    :value="t.price"
                    min="0"
                    step="0.01"
                    @input="onTierPriceInput(i, $event.target.value)"
                  />
                </td>
                <td>
                  <button
                    type="button"
                    class="btn-link danger"
                    :disabled="(form.price_tiers || []).length <= 1 || i === 0"
                    @click="removeTier(i)"
                  >删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div style="margin-top:8px">
            <button type="button" class="btn btn-sm" @click="addTier">＋ 增加一段</button>
            <span v-if="tierError" class="tier-error">{{ tierError }}</span>
          </div>
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="width:120px">
            <div class="label">库存</div>
            <input type="number" class="input" v-model.number="form.stock" />
          </div>
          <div class="field" style="width:120px">
            <div class="label">销量</div>
            <input type="number" class="input" v-model.number="form.sales" />
          </div>
          <div class="field" style="width:140px">
            <div class="label">押金 *</div>
            <input
              type="number"
              class="input"
              min="1"
              step="1"
              v-model.number="form.deposit_amount"
              placeholder="如 3000"
            />
          </div>
        </div>
        <div class="field">
          <div class="label">封面图片（covers，第 1 张为主图，详情页轮播展示）</div>
          <div class="shots-grid">
            <div v-for="(item, i) in (form.covers || [])" :key="i" class="shot-cell">
              <div class="shot-thumb" :style="shotStyle(item)">
                <span v-if="i === 0" class="cover-main-tag">主图</span>
              </div>
              <div class="shot-bar">
                <button type="button" class="btn-link" :disabled="i === 0" @click="moveCover(i, -1)" title="左移">←</button>
                <span class="shot-idx">{{ i + 1 }}</span>
                <button type="button" class="btn-link" :disabled="i === (form.covers.length - 1)" @click="moveCover(i, 1)" title="右移">→</button>
                <button type="button" class="btn-link danger" @click="removeCover(i)" title="移除">×</button>
              </div>
            </div>
            <label class="shot-add">
              <input type="file" accept="image/*" multiple hidden @change="onCoversPick" />
              <span v-if="coversUploading">上传中…</span>
              <span v-else>＋ 添加封面</span>
            </label>
          </div>
          <div class="muted" style="margin-top:6px">支持多选；第 1 张作为列表卡封面 / 详情轮播首屏；左右调整顺序，× 移除。</div>
        </div>

        <div class="field">
          <div class="label">详情图片（real_shots，按当前顺序展示）</div>
          <div class="shots-grid">
            <div v-for="(item, i) in (form.real_shots || [])" :key="i" class="shot-cell">
              <div class="shot-thumb" :style="shotStyle(item)"></div>
              <div class="shot-bar">
                <button type="button" class="btn-link" :disabled="i === 0" @click="moveShot(i, -1)" title="左移">←</button>
                <span class="shot-idx">{{ i + 1 }}</span>
                <button type="button" class="btn-link" :disabled="i === (form.real_shots.length - 1)" @click="moveShot(i, 1)" title="右移">→</button>
                <button type="button" class="btn-link danger" @click="removeShot(i)" title="移除">×</button>
              </div>
            </div>
            <label class="shot-add">
              <input type="file" accept="image/*" multiple hidden @change="onShotsPick" />
              <span v-if="shotsUploading">上传中…</span>
              <span v-else>＋ 添加图片</span>
            </label>
          </div>
          <div class="muted" style="margin-top:6px">支持多选；左右箭头调整顺序；× 移除。</div>
        </div>

        <div class="field">
          <div class="label">顶部红色提示 tip</div>
          <input class="input" v-model="form.tip" />
        </div>
        <div class="field">
          <div class="label">发货说明 shipping_note</div>
          <textarea class="textarea" v-model="form.shipping_note"></textarea>
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">芝麻 serviceId</div>
            <input class="input" v-model="form.service_id" />
          </div>
          <div class="field" style="width:140px">
            <div class="label">状态</div>
            <select class="select" v-model="form.status">
              <option value="on">on 上架</option>
              <option value="off">off 下架</option>
              <option value="draft">draft 草稿</option>
            </select>
          </div>
        </div>

        <!-- 分享 · 小程序码（仅已保存商品可生成）-->
        <div class="field share-block" v-if="form.id">
          <div class="label">分享 · 小程序码</div>
          <div class="share-body">
            <div class="share-qr">
              <img v-if="qrUrl" :src="qrUrl" alt="小程序码" />
              <div v-else-if="qrLoading" class="share-qr-ph">生成中…</div>
              <div v-else class="share-qr-ph clickable" @click="genQrcode(qrDays)">
                {{ qrError ? '重试生成' : '点击生成' }}
              </div>
            </div>
            <div class="share-right">
              <div class="muted share-tip">
                扫码（支付宝扫一扫）进入该商品详情页{{ qrDays ? '，并自动选中 ' + qrDays + ' 天租期' : '' }}。
              </div>
              <div class="share-presets">
                <button
                  type="button"
                  :class="['share-preset', { on: qrDays === 0 }]"
                  @click="genQrcode(0)"
                >默认</button>
                <button
                  v-for="d in sharePresets"
                  :key="d"
                  type="button"
                  :class="['share-preset', { on: qrDays === d }]"
                  @click="genQrcode(d)"
                >{{ d }}天</button>
              </div>
              <div class="share-actions" v-if="qrUrl">
                <button type="button" class="share-dl" @click="downloadQr">下载二维码</button>
              </div>
              <div v-if="qrError" class="tier-error">{{ qrError }}</div>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="modal = null">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, computed, inject, onMounted } = Vue;

// 把单个 real_shots 项渲染为 CSS background 值：
// - 看着像 URL（/...、http(s)://、data:）→ wrap 成 url() center/cover
// - 否则当作 CSS 直接用（兼容老数据里的 linear-gradient）
const _isUrlLike = (s) => typeof s === 'string' && /^(\/|https?:\/\/|data:)/.test(s.trim());
const _toBg = (s) => _isUrlLike(s)
  ? `url("${s}") center/cover no-repeat`
  : (s || '');

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const cats = ref([]);
    const loading = ref(true);
    const kw = ref('');
    const filterCat = ref(0);
    const modal = ref(null);
    const form = ref({});
    const saving = ref(false);
    const coversUploading = ref(false);
    const shotsUploading = ref(false);

    const filtered = computed(() => {
      let arr = list.value;
      if (filterCat.value) arr = arr.filter(p => p.cat_id === filterCat.value);
      if (kw.value.trim()) {
        const k = kw.value.toLowerCase();
        arr = arr.filter(p => (p.name || '').toLowerCase().includes(k));
      }
      return arr;
    });

    const catName = (cid) => (cats.value.find(c => c.id === cid) || {}).name || '-';
    const statusText = (p) => p.status === 'on' ? '上架' : p.status === 'off' ? '下架' : '草稿';
    const statusCls  = (p) => p.status === 'on' ? 'tag-green' : p.status === 'off' ? 'tag-orange' : 'tag-gray';

    // ---- 封面（多图） / 详情图片 ----
    const _firstCover = (p) => {
      const arr = Array.isArray(p.covers) ? p.covers : [];
      return arr[0] || p.cover_url || '';
    };
    const rowCoverStyle = (p) => ({ background: _toBg(_firstCover(p)) || p.bg || '' });
    const shotStyle = (item) => ({ background: _toBg(item) });

    const onCoversPick = async (e) => {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      if (!files.length) return;
      coversUploading.value = true;
      try {
        const arr = Array.isArray(form.value.covers) ? form.value.covers.slice() : [];
        for (const f of files) {
          const r = await api.upload(f);
          arr.push(r.url);
        }
        form.value.covers = arr;
      } catch (err) { alert(err.message || '上传失败'); }
      finally { coversUploading.value = false; }
    };
    const moveCover = (i, delta) => {
      const arr = (form.value.covers || []).slice();
      const j = i + delta;
      if (j < 0 || j >= arr.length) return;
      [arr[i], arr[j]] = [arr[j], arr[i]];
      form.value.covers = arr;
    };
    const removeCover = (i) => {
      const arr = (form.value.covers || []).slice();
      arr.splice(i, 1);
      form.value.covers = arr;
    };

    const onShotsPick = async (e) => {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      if (!files.length) return;
      shotsUploading.value = true;
      try {
        // 串行上传，保留用户选择顺序
        const arr = Array.isArray(form.value.real_shots) ? form.value.real_shots.slice() : [];
        for (const f of files) {
          const r = await api.upload(f);
          arr.push(r.url);
        }
        form.value.real_shots = arr;
      } catch (err) { alert(err.message || '上传失败'); }
      finally { shotsUploading.value = false; }
    };

    const moveShot = (i, delta) => {
      const arr = (form.value.real_shots || []).slice();
      const j = i + delta;
      if (j < 0 || j >= arr.length) return;
      [arr[i], arr[j]] = [arr[j], arr[i]];
      form.value.real_shots = arr;
    };
    const removeShot = (i) => {
      const arr = (form.value.real_shots || []).slice();
      arr.splice(i, 1);
      form.value.real_shots = arr;
    };

    const fetch = async () => {
      loading.value = true;
      try {
        const [pr, cr] = await Promise.all([api.list('products'), api.list('categories')]);
        list.value = pr.list;
        cats.value = cr.list;
      } finally { loading.value = false; }
    };

    // 商品分享小程序码（编辑弹窗底部）
    const sharePresets = [3, 7, 10, 15, 20, 30, 60, 90];
    const qrUrl = ref('');
    const qrDays = ref(0);          // 当前二维码编码的租期；0 = 默认无租期
    const qrLoading = ref(false);
    const qrError = ref('');
    const resetQr = () => { qrUrl.value = ''; qrDays.value = 0; qrError.value = ''; qrLoading.value = false; };
    const genQrcode = async (days) => {
      if (!form.value.id) return;   // 仅已保存商品可生成
      qrDays.value = days || 0;
      qrLoading.value = true;
      qrError.value = '';
      try {
        const r = await api.productQrcode(form.value.id, qrDays.value);
        qrUrl.value = r.qr_code_url || '';
        if (!qrUrl.value) qrError.value = '未返回二维码';
      } catch (e) {
        qrUrl.value = '';
        qrError.value = e.message || '生成失败';
      } finally {
        qrLoading.value = false;
      }
    };

    // 下载小程序码图片：优先 fetch 成 blob 触发浏览器下载（带正确文件名）；
    // 跨域被 CORS 拦截时退化为新标签打开图片，用户可右键另存。
    const downloadQr = async () => {
      if (!qrUrl.value) return;
      const safeName = String(form.value.name || form.value.id || 'product')
        .replace(/[\\/:*?"<>|]/g, '_').slice(0, 40);
      const fileName = `小程序码_${safeName}${qrDays.value ? '_' + qrDays.value + '天' : ''}.png`;
      try {
        const resp = await fetch(qrUrl.value, { mode: 'cors' });
        if (!resp.ok) throw new Error('下载失败');
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (e) {
        // CORS / 网络异常：兜底打开图片，用户可右键另存为
        window.open(qrUrl.value, '_blank');
      }
    };

    // 列表页内联快改库存：input 失焦/回车即触发，调 PUT 只更新 stock 一个字段
    const stockSaving = ref({});   // { [id]: true } 保存中
    const stockOk = ref({});       // { [id]: true } 刚保存成功的短暂标记
    const saveStock = async (p) => {
      let v = parseInt(p.stock, 10);
      if (isNaN(v) || v < 0) v = 0;
      p.stock = v;                 // 规整非法输入
      if (stockSaving.value[p.id]) return;
      stockSaving.value = { ...stockSaving.value, [p.id]: true };
      try {
        await api.update('products', p.id, { stock: v });
        // 成功后闪 1.5s "已存"
        stockOk.value = { ...stockOk.value, [p.id]: true };
        setTimeout(() => {
          const m = { ...stockOk.value }; delete m[p.id]; stockOk.value = m;
        }, 1500);
      } catch (e) {
        alert(e.message || '库存保存失败');
        await fetch();             // 失败回滚到服务端真实值
      } finally {
        const m = { ...stockSaving.value }; delete m[p.id]; stockSaving.value = m;
      }
    };

    const openNew = () => {
      form.value = {
        name: '', subtitle: '', cat_id: 0,
        stock: 1, sales: 0,
        // 押金默认 2000、日租金默认 20，避免漏配置导致 0 元租赁风险
        deposit_amount: 2000,
        covers: [],
        tip: '', shipping_note: '',
        service_id: '', status: 'on',
        real_shots: [],
        price_tiers: [{ from: 1, price: 20 }],
      };
      tierError.value = '';
      resetQr();          // 新建商品还没 id，分享区不可用
      modal.value = true;
    };
    const openEdit = (p) => {
      // 深拷贝 covers / real_shots / price_tiers，避免编辑过程中改到列表里的引用；
      // 没 covers 的旧数据用 cover_url 兜底。
      const tiers = Array.isArray(p.price_tiers) && p.price_tiers.length
        ? p.price_tiers.map(t => ({ from: Number(t.from), price: Number(t.price) }))
        : [{ from: 1, price: 20 }];
      const covers = Array.isArray(p.covers) && p.covers.length
        ? p.covers.slice()
        : (p.cover_url ? [p.cover_url] : []);
      form.value = {
        // damage_standard 已无后台编辑入口，随 ...p 原样透传，保存时不动既有数据
        ...p,
        covers,
        real_shots: Array.isArray(p.real_shots) ? p.real_shots.slice() : [],
        price_tiers: tiers,
      };
      // 旧数据可能还残留这些字段；不让它们随保存请求回传给后端。
      delete form.value.price;
      delete form.value.promo_label;
      delete form.value.activity;
      delete form.value.amount;       // 已废弃的"额度卡面额"字段
      tierError.value = '';
      resetQr();
      modal.value = true;
      // 打开已有商品时自动生成"默认（无租期）"小程序码
      genQrcode(0);
    };

    // ---- 分段租金编辑 ----
    const tierError = ref('');

    const validateTiers = (tiers) => {
      if (!Array.isArray(tiers) || !tiers.length) return '至少需要一段租金';
      let lastFrom = 0;
      for (let i = 0; i < tiers.length; i++) {
        const t = tiers[i];
        const f = Number(t.from), p = Number(t.price);
        if (!Number.isFinite(f) || !Number.isFinite(p)) return `第 ${i + 1} 段：起始天/单价必须是数字`;
        if (p < 0) return `第 ${i + 1} 段：单价不能为负`;
        if (i === 0 && f !== 1) return '第一段必须从第 1 天起';
        if (f <= lastFrom) return `第 ${i + 1} 段：起始天必须大于上一段（当前 ${f} ≤ ${lastFrom}）`;
        lastFrom = f;
      }
      return '';
    };

    const onTierFromInput = (i, v) => {
      const tiers = (form.value.price_tiers || []).slice();
      tiers[i] = { ...tiers[i], from: parseInt(v, 10) || 0 };
      form.value.price_tiers = tiers;
      tierError.value = validateTiers(tiers);
    };
    const onTierPriceInput = (i, v) => {
      const tiers = (form.value.price_tiers || []).slice();
      tiers[i] = { ...tiers[i], price: parseFloat(v) || 0 };
      form.value.price_tiers = tiers;
      tierError.value = validateTiers(tiers);
    };
    const addTier = () => {
      const tiers = (form.value.price_tiers || []).slice();
      const last = tiers[tiers.length - 1] || { from: 0, price: 0 };
      tiers.push({ from: (Number(last.from) || 0) + 1, price: Number(last.price) || 0 });
      form.value.price_tiers = tiers;
      tierError.value = validateTiers(tiers);
    };
    const removeTier = (i) => {
      if (i === 0) return; // 第一段不允许删
      const tiers = (form.value.price_tiers || []).slice();
      tiers.splice(i, 1);
      form.value.price_tiers = tiers;
      tierError.value = validateTiers(tiers);
    };

    const save = async () => {
      if (!form.value.name?.trim()) { alert('商品名必填'); return; }
      const deposit = Number(form.value.deposit_amount);
      if (!Number.isFinite(deposit) || deposit <= 0) {
        alert('押金必填且必须大于 0');
        return;
      }
      const err = validateTiers(form.value.price_tiers);
      if (err) { tierError.value = err; alert('价格分段配置无效：' + err); return; }
      saving.value = true;
      try {
        if (form.value.id) await api.update('products', form.value.id, form.value);
        else await api.create('products', form.value);
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    const remove = async (p) => {
      if (!confirm(`确认删除商品「${p.name}」？`)) return;
      try { await api.remove('products', p.id); await fetch(); }
      catch (e) { alert(e.message); }
    };

    onMounted(fetch);
    return {
      list, cats, loading, kw, filterCat, filtered,
      modal, form, saving, coversUploading, shotsUploading,
      stockSaving, stockOk, saveStock,
      sharePresets, qrUrl, qrDays, qrLoading, qrError, genQrcode, downloadQr,
      catName, statusText, statusCls,
      rowCoverStyle, shotStyle,
      onCoversPick, moveCover, removeCover,
      onShotsPick, moveShot, removeShot,
      openNew, openEdit, save, remove,
      tierError, onTierFromInput, onTierPriceInput, addTier, removeTier,
    };
  }
};
</script>

<style scoped>
/* 分享 · 小程序码 */
.share-block { border-top: 1px dashed var(--line, #e5e8ee); padding-top: 12px; }
.share-body { display: flex; gap: 16px; align-items: flex-start; }
.share-qr {
  width: 120px; height: 120px; flex-shrink: 0;
  border: 1px solid var(--line, #e5e8ee); border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden; background: #fafbfd;
}
.share-qr img { width: 100%; height: 100%; object-fit: contain; }
.share-qr-ph { font-size: 12px; color: #9aa4b2; }
.share-qr-ph.clickable { cursor: pointer; color: #2b7cff; }
.share-right { flex: 1; min-width: 0; }
.share-tip { font-size: 12px; line-height: 1.6; margin-bottom: 10px; }
.share-presets { display: flex; flex-wrap: wrap; gap: 8px; }
.share-preset {
  padding: 4px 14px; font-size: 13px;
  border: 1px solid var(--line, #d6dbe3); border-radius: 999px;
  background: #fff; color: #4a5060; cursor: pointer;
}
.share-preset.on {
  border-color: #2b7cff; background: rgba(43,124,255,0.08); color: #2b7cff; font-weight: 600;
}
.share-actions { margin-top: 12px; }
.share-dl {
  padding: 6px 18px; font-size: 13px;
  border: 1px solid #2b7cff; border-radius: 999px;
  background: #2b7cff; color: #fff; cursor: pointer;
}
.share-dl:hover { background: #1f6fff; }

/* 列表页内联快改库存 */
.stock-edit { display: flex; align-items: center; gap: 6px; }
.stock-input {
  width: 72px;
  padding: 4px 8px;
  text-align: center;
}
.stock-flag { font-size: 12px; white-space: nowrap; }
.stock-flag.saving { color: #9aa4b2; }
.stock-flag.ok { color: #18b07b; font-weight: 600; }

.tiers-help {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
  margin-bottom: 8px;
}
.tiers-table {
  width: 100%;
  border-collapse: collapse;
}
.tiers-table th,
.tiers-table td {
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid #eef0f4;
  font-size: 13px;
}
.tiers-table input.input { width: 100%; }
.tier-error {
  margin-left: 12px;
  color: #e94545;
  font-size: 12px;
}

/* ---------- 列表：搜索框 / 移动端卡片 ---------- */
.kw-input { width: 200px; }
.cat-select { width: 140px; }
.prod-cards { display: none; }

.prod-card {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  background: #fff;
}
.pc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
}
.pc-main { display: flex; gap: 12px; align-items: flex-start; }
.pc-cover {
  width: 56px; height: 56px;
  flex-shrink: 0;
  border-radius: 8px;
  border: 1px solid var(--line);
  background-color: #f7f9fc;
  background-size: cover;
  background-position: center;
}
.pc-info { flex: 1; min-width: 0; }
.pc-name { font-weight: 500; word-break: break-all; }
.pc-meta {
  display: flex;
  gap: 16px;
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-2);
}
.pc-meta b { color: var(--text); font-weight: 600; }
.pc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}
.pc-actions { display: flex; gap: 4px; }
.pc-actions .btn-link { padding: 6px 8px; }

@media (max-width: 768px) {
  /* 列表切换：隐藏宽表格，显示卡片 */
  .prod-table { display: none; }
  .prod-cards { display: flex; flex-direction: column; gap: 10px; }

  /* 工具条垂直堆叠：标题一行，搜索 + 分类 + 新增一行 */
  .toolbar { flex-direction: column; align-items: stretch; gap: 8px; }
  .toolbar > .row { width: 100%; flex-wrap: nowrap; }
  .kw-input { flex: 1; width: auto; min-width: 0; }
  .cat-select { width: 110px; flex-shrink: 0; }
}
</style>
