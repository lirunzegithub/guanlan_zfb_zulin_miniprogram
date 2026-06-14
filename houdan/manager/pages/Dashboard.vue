<template>
  <div v-if="loading" class="loading">加载中...</div>
  <template v-else>
    <div class="grid-4">
      <div class="stat">
        <div class="v">{{ s.product_total }}</div>
        <div class="k">商品总数</div>
      </div>
      <div class="stat green">
        <div class="v">{{ s.product_on_sale }}</div>
        <div class="k">在售商品</div>
      </div>
      <div class="stat gray">
        <div class="v">{{ s.banner_total }}</div>
        <div class="k">轮播图位</div>
      </div>
    </div>

    <div class="grid-4" style="margin-top:16px">
      <div class="stat">
        <div class="v">{{ s.category_total }}</div>
        <div class="k">分类数</div>
      </div>
      <div class="stat green">
        <div class="v">{{ s.stock_total }}</div>
        <div class="k">总库存</div>
      </div>
      <div class="stat orange">
        <div class="v">{{ s.sales_total }}</div>
        <div class="k">累计销量</div>
      </div>
      <div class="stat gray">
        <div class="v">{{ s.user_total }}</div>
        <div class="k">用户数</div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-h">
        <div class="card-title">近期商品</div>
        <span class="muted">按 updated_at 倒序</span>
      </div>
      <table class="table">
        <thead><tr><th style="width:80px">ID</th><th>商品名</th><th style="width:140px">最低日租 起</th><th style="width:120px">销量</th></tr></thead>
        <tbody>
          <tr v-for="p in s.recent_products" :key="p.id">
            <td>{{ p.id }}</td>
            <td>{{ p.name }}</td>
            <td>¥{{ p.min_price }} 起</td>
            <td>{{ p.sales }}</td>
          </tr>
          <tr v-if="!s.recent_products?.length"><td colspan="4" class="empty">暂无数据</td></tr>
        </tbody>
      </table>
    </div>
  </template>
</template>

<script>
const { ref, inject, onMounted } = Vue;
export default {
  setup() {
    const api = inject('api');
    const loading = ref(true);
    const s = ref({});
    const load = async () => {
      loading.value = true;
      try { s.value = await api.stats(); } finally { loading.value = false; }
    };
    onMounted(load);
    return { loading, s };
  }
};
</script>
