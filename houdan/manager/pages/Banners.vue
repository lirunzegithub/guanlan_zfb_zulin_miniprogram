<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">轮播图与三宫格</div>
      <button class="btn" @click="openNew">＋ 新增</button>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:60px">ID</th>
          <th style="width:90px">位置</th>
          <th style="width:60px">序</th>
          <th>标题 / 副标题</th>
          <th style="width:120px">角标</th>
          <th style="width:110px">主图</th>
          <th style="width:160px">跳转</th>
          <th style="width:160px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="b in list" :key="b.id">
          <td>{{ b.id }}</td>
          <td><span class="tag">{{ b.position }}</span></td>
          <td>{{ b.slot }}</td>
          <td>
            <div>{{ b.title }}</div>
            <div class="muted">{{ b.subtitle }}</div>
          </td>
          <td>
            <span v-if="b.tag" :class="['tag', tagCls(b.tag_style)]">{{ b.tag }}</span>
            <span v-else class="muted">-</span>
          </td>
          <td>
            <div class="banner-row-bg">
              <span class="swatch" :style="rowSwatchStyle(b)"></span>
              <span v-if="!b.image_url" class="muted-mini">未上传</span>
            </div>
          </td>
          <td><span class="muted">{{ b.link_type }}: {{ b.link_value || '-' }}</span></td>
          <td>
            <button class="btn-link" @click="openEdit(b)">编辑</button>
            <button class="btn-link danger" @click="remove(b)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="8" class="empty">暂无数据</td></tr>
        <tr v-if="loading"><td colspan="8" class="loading">加载中...</td></tr>
      </tbody>
    </table>
  </div>

  <!-- 编辑弹窗 -->
  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal">
      <div class="modal-h">{{ form.id ? '编辑轮播图' : '新增轮播图' }}</div>
      <div class="modal-body">
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">位置 position</div>
            <select class="select" v-model="form.position">
              <option value="hero">hero（顶部大图轮播）</option>
            </select>
            <div class="muted" style="margin-top:4px;font-size:12px">
              首页三宫格（免押认证/售后无忧/流程安全）为内置入口，不在此处配置
            </div>
          </div>
          <div class="field" style="width:120px">
            <div class="label">槽位 slot</div>
            <input type="number" class="input" v-model.number="form.slot" />
          </div>
          <div class="field" style="width:120px">
            <div class="label">排序 sort</div>
            <input type="number" class="input" v-model.number="form.sort" />
          </div>
        </div>
        <div class="field">
          <div class="label">标题</div>
          <input class="input" v-model="form.title" />
        </div>
        <div class="field">
          <div class="label">副标题</div>
          <input class="input" v-model="form.subtitle" />
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">角标文字</div>
            <input class="input" v-model="form.tag" placeholder="留空表示无" />
          </div>
          <div class="field" style="width:180px">
            <div class="label">角标风格</div>
            <select class="select" v-model="form.tag_style">
              <option value="">无</option>
              <option value="red">red</option>
              <option value="yellow">yellow</option>
              <option value="gradient">gradient</option>
            </select>
          </div>
        </div>
        <div class="field">
          <div class="label">主图</div>
          <div class="shots-grid">
            <div v-if="form.image_url" class="shot-cell">
              <div class="shot-thumb" :style="shotStyle(form.image_url)">
                <span class="cover-main-tag">主图</span>
              </div>
              <div class="shot-bar">
                <span class="shot-idx">1</span>
                <button type="button" class="btn-link danger" @click="removeImage" title="移除">×</button>
              </div>
            </div>
            <label v-else class="shot-add">
              <input type="file" accept="image/*" hidden @change="onImagePick" />
              <span v-if="imageUploading">上传中…</span>
              <span v-else>＋ 上传主图</span>
            </label>
          </div>
          <input
            class="input"
            style="margin-top:8px"
            v-model="form.image_url"
            placeholder="或手动填写图片 URL"
          />
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="width:160px">
            <div class="label">跳转类型</div>
            <select class="select" v-model="form.link_type">
              <option value="none">none</option>
              <option value="page">page</option>
              <option value="product">product</option>
              <option value="category">category</option>
              <option value="external">external</option>
            </select>
          </div>
          <div class="field" style="flex:1">
            <div class="label">跳转值 link_value</div>
            <input class="input" v-model="form.link_value" />
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
const { ref, inject, onMounted } = Vue;

// 与 Products.vue 一致的取值规则：URL/路径 → url() center/cover；否则按 CSS 用
const _isUrlLike = (s) => typeof s === 'string' && /^(\/|https?:\/\/|data:)/.test(s.trim());
const _toBg = (s) => _isUrlLike(s)
  ? `url("${s}") center/cover no-repeat`
  : (s || '');

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const loading = ref(true);
    const modal = ref(null);
    const form = ref({});
    const saving = ref(false);
    const imageUploading = ref(false);

    const fetch = async () => {
      loading.value = true;
      try { const r = await api.list('banners'); list.value = r.list; }
      finally { loading.value = false; }
    };

    const tagCls = (style) => style === 'red' ? 'tag-red' : style === 'yellow' ? 'tag-orange' : '';
    const shotStyle = (s) => ({ background: _toBg(s) });
    // 列表里那一格：只看 image_url；没图就显示中性灰占位
    const rowSwatchStyle = (b) => ({ background: _toBg(b.image_url) || '#eef0f4' });

    const onImagePick = async (e) => {
      const f = (e.target.files || [])[0];
      e.target.value = '';
      if (!f) return;
      imageUploading.value = true;
      try {
        const r = await api.upload(f);
        form.value.image_url = r.url;
      } catch (err) { alert(err.message || '上传失败'); }
      finally { imageUploading.value = false; }
    };
    const removeImage = () => { form.value.image_url = ''; };

    const openNew = () => {
      form.value = {
        position: 'hero', slot: 0, title: '', subtitle: '',
        tag: '', tag_style: '', image_url: '',
        link_type: 'none', link_value: '', sort: 0,
      };
      modal.value = true;
    };
    const openEdit = (b) => { form.value = { ...b }; modal.value = true; };

    const save = async () => {
      saving.value = true;
      try {
        if (form.value.id) await api.update('banners', form.value.id, form.value);
        else await api.create('banners', form.value);
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    const remove = async (b) => {
      if (!confirm(`确认删除轮播图 #${b.id}「${b.title}」？`)) return;
      try { await api.remove('banners', b.id); await fetch(); }
      catch (e) { alert(e.message); }
    };

    onMounted(fetch);
    return {
      list, loading, modal, form, saving, imageUploading,
      openNew, openEdit, save, remove,
      tagCls, shotStyle, rowSwatchStyle, onImagePick, removeImage,
    };
  }
};
</script>

<style scoped>
.banner-row-bg { display: inline-flex; align-items: center; gap: 6px; }
.muted-mini { font-size: 12px; color: #9aa4b2; }
</style>
