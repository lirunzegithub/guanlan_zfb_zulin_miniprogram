<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">商品评论（{{ total }}）</div>
      <div class="row" style="gap:8px">
        <select class="select" v-model.number="filterPid" style="width:200px" @change="fetch">
          <option :value="0">全部商品</option>
          <option v-for="p in products" :key="p.id" :value="p.id">
            {{ p.id }} · {{ p.name }}
          </option>
        </select>
        <button class="btn btn-ghost" @click="fetch">刷新</button>
        <button class="btn" @click="openNew">＋ 新增评论</button>
      </div>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:70px">ID</th>
          <th style="width:200px">商品</th>
          <th style="width:120px">用户</th>
          <th style="width:90px">评分</th>
          <th>内容 / 配图</th>
          <th style="width:160px">时间</th>
          <th style="width:90px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in list" :key="c.id">
          <td>{{ c.id }}</td>
          <td>
            <div>{{ c.product_name || '—' }}</div>
            <div class="muted">#{{ c.product_id }}</div>
          </td>
          <td>
            <div class="cmt-user">
              <span class="cmt-avatar" :style="{ background: c.avatar_color }"></span>
              <span>{{ c.user || '匿名' }}</span>
            </div>
          </td>
          <td>
            <span class="stars">
              <span v-for="n in 5" :key="n" :class="['star', n <= c.stars ? 'on' : '']">★</span>
            </span>
          </td>
          <td class="cmt-content">
            <div>{{ c.content }}</div>
            <div v-if="c.images && c.images.length" class="cmt-thumbs">
              <img
                v-for="(u, i) in c.images"
                :key="i"
                :src="u"
                class="cmt-thumb"
                @click="previewImage(u)"
              />
            </div>
          </td>
          <td><span class="muted">{{ c.time }}</span></td>
          <td>
            <button class="btn-link danger" @click="remove(c)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="7" class="empty">暂无评论</td></tr>
        <tr v-if="loading"><td colspan="7" class="loading">加载中…</td></tr>
      </tbody>
    </table>
  </div>

  <!-- 新增评论弹窗 -->
  <div v-if="modal" class="modal-mask" @click.self="closeModal">
    <div class="modal">
      <div class="modal-h">新增评论</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">商品</div>
          <select class="select" v-model.number="form.product_id">
            <option :value="0">请选择商品</option>
            <option v-for="p in products" :key="p.id" :value="p.id">
              {{ p.id }} · {{ p.name }}
            </option>
          </select>
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">用户名</div>
            <input class="input" v-model="form.user" placeholder="留空 = 匿名用户" />
          </div>
          <div class="field" style="width:200px">
            <div class="label">评分</div>
            <div class="stars-pick">
              <span
                v-for="n in 5" :key="n"
                :class="['star-pick', n <= form.stars ? 'on' : '']"
                @click="form.stars = n"
              >★</span>
              <span class="muted" style="margin-left:8px;font-size:12px">{{ form.stars }} 星</span>
            </div>
          </div>
        </div>
        <div class="field">
          <div class="label">评论内容</div>
          <textarea class="input" rows="4" v-model="form.content" placeholder="评论内容（最多 500 字）" maxlength="500"></textarea>
        </div>
        <div class="field">
          <div class="label">配图（最多 9 张）</div>
          <div class="shots-grid">
            <div v-for="(u, i) in (form.images || [])" :key="i" class="shot-cell">
              <div class="shot-thumb" :style="shotStyle(u)"></div>
              <div class="shot-bar">
                <span class="shot-idx">{{ i + 1 }}</span>
                <button type="button" class="btn-link danger" @click="removeImage(i)" title="移除">×</button>
              </div>
            </div>
            <label v-if="(form.images || []).length < 9" class="shot-add">
              <input type="file" accept="image/*" multiple hidden @change="onImagesPick" />
              <span v-if="imagesUploading">上传中…</span>
              <span v-else>＋ 添加图片</span>
            </label>
          </div>
        </div>
        <div class="field">
          <div class="label">评论时间</div>
          <input type="datetime-local" class="input" v-model="form.time" />
          <div class="muted" style="margin-top:4px;font-size:12px">
            留空 = 当前时间；可手动指定（用于补录历史好评）
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="closeModal">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, inject, onMounted } = Vue;

const _isUrlLike = (s) => typeof s === 'string' && /^(\/|https?:\/\/|data:)/.test(s.trim());
const _toBg = (s) => _isUrlLike(s)
  ? `url("${s}") center/cover no-repeat`
  : (s || '');

// 把当前时刻格式化为 datetime-local 默认值（不带 Z 时区，本地时区即可）
function _nowLocal() {
  const d = new Date();
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const products = ref([]);
    const total = ref(0);
    const loading = ref(true);
    const filterPid = ref(0);

    const modal = ref(false);
    const saving = ref(false);
    const imagesUploading = ref(false);
    const form = ref({
      product_id: 0, user: '', stars: 5, content: '', images: [], time: '',
    });

    const fetch = async () => {
      loading.value = true;
      try {
        const params = filterPid.value ? { product_id: filterPid.value } : null;
        const r = await api.list('comments', params);
        list.value = r.list;
        total.value = r.total;
      } finally { loading.value = false; }
    };

    const loadProducts = async () => {
      try {
        const r = await api.list('products');
        products.value = r.list || [];
      } catch (e) {}
    };

    const shotStyle = (u) => ({ background: _toBg(u) });

    const openNew = () => {
      form.value = {
        product_id: filterPid.value || (products.value[0] && products.value[0].id) || 0,
        user: '', stars: 5, content: '',
        images: [],
        time: _nowLocal(),
      };
      modal.value = true;
    };
    const closeModal = () => {
      if (saving.value || imagesUploading.value) return;
      modal.value = false;
    };

    const onImagesPick = async (e) => {
      const files = Array.from(e.target.files || []);
      e.target.value = '';
      if (!files.length) return;
      const remain = 9 - (form.value.images || []).length;
      if (remain <= 0) return;
      imagesUploading.value = true;
      try {
        const arr = (form.value.images || []).slice();
        for (const f of files.slice(0, remain)) {
          const r = await api.upload(f);
          arr.push(r.url);
        }
        form.value.images = arr;
      } catch (err) { alert(err.message || '上传失败'); }
      finally { imagesUploading.value = false; }
    };
    const removeImage = (i) => {
      const arr = (form.value.images || []).slice();
      arr.splice(i, 1);
      form.value.images = arr;
    };

    const save = async () => {
      const f = form.value;
      if (!f.product_id) { alert('请选择商品'); return; }
      const content = (f.content || '').trim();
      if (!content) { alert('请填写评论内容'); return; }
      saving.value = true;
      try {
        await api.create('comments', {
          product_id: f.product_id,
          stars: f.stars,
          content,
          user: (f.user || '').trim(),
          images: (f.images || []).slice(),
          // 后端会解析 datetime-local（YYYY-MM-DDTHH:MM）
          created_at: f.time || '',
        });
        modal.value = false;
        await fetch();
      } catch (e) {
        alert(e.message || '保存失败');
      } finally { saving.value = false; }
    };

    const remove = async (c) => {
      if (!confirm(`确认删除「${c.user || '匿名'}」对商品 #${c.product_id} 的评论？`)) return;
      try { await api.remove('comments', c.id); await fetch(); }
      catch (e) { alert(e.message); }
    };

    const previewImage = (u) => { if (u) window.open(u, '_blank'); };

    onMounted(async () => { await loadProducts(); await fetch(); });
    return {
      list, products, total, loading, filterPid, fetch, remove,
      modal, saving, imagesUploading, form,
      openNew, closeModal, onImagesPick, removeImage, save,
      shotStyle, previewImage,
    };
  },
};
</script>

<style>
.cmt-user { display: flex; align-items: center; gap: 6px; }
.cmt-avatar {
  width: 22px; height: 22px;
  border-radius: 50%;
  border: 1px solid var(--line);
}
.cmt-content {
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
  word-break: break-word;
}
.cmt-thumbs {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-top: 8px;
}
.cmt-thumb {
  width: 56px; height: 56px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--line);
  cursor: zoom-in;
  background: #f4f6fa;
}
.stars { letter-spacing: 1px; }
.stars .star { color: #d0d6e0; font-size: 14px; }
.stars .star.on { color: #ffb800; }

/* 弹窗内的评分选择 */
.stars-pick {
  display: inline-flex; align-items: center;
}
.star-pick {
  font-size: 24px;
  color: #d0d6e0;
  cursor: pointer;
  padding: 0 2px;
  user-select: none;
}
.star-pick.on { color: #ffb800; }
</style>
