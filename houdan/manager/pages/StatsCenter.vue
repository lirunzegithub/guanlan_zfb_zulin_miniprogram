<template>
  <div v-if="loading" class="loading">加载中...</div>
  <template v-else>
    <!-- KPI 行 -->
    <div class="grid-4">
      <div class="stat">
        <div class="v">{{ s.in_rent?.total || 0 }}</div>
        <div class="k">在租订单</div>
      </div>
      <div class="stat green">
        <div class="v">{{ fmtNum(s.in_rent?.age?.avg) }}</div>
        <div class="k">在租用户平均年龄</div>
      </div>
      <div class="stat orange">
        <div class="v">{{ fmtNum(s.lease?.contract_avg_days) }}</div>
        <div class="k">平均租期（合同）</div>
      </div>
      <div class="stat gray">
        <div class="v">{{ s.lease?.actual_avg_days == null ? '—' : fmtNum(s.lease.actual_avg_days) }}</div>
        <div class="k">平均实际占用（已归还）</div>
      </div>
    </div>

    <!-- 年龄分布 -->
    <div class="card" style="margin-top:16px">
      <div class="card-h">
        <div>
          <div class="card-title">在租订单年龄分布</div>
          <div class="muted" style="margin-top:4px">
            口径：租赁中 / 待归还 / 已逾期，共 {{ s.in_rent?.total || 0 }} 单；
            其中 {{ s.in_rent?.age?.known || 0 }} 单可由身份证推算年龄<template
              v-if="s.in_rent?.age?.unknown">，{{ s.in_rent.age.unknown }} 单未实名或号码异常未计入</template>
          </div>
        </div>
        <button class="btn-link" @click="tableView.age = !tableView.age">
          {{ tableView.age ? '图表' : '表格' }}
        </button>
      </div>

      <table v-if="tableView.age" class="table">
        <thead><tr><th>年龄段</th><th style="width:120px">订单数</th><th style="width:120px">占比</th></tr></thead>
        <tbody>
          <tr v-for="b in ageBuckets" :key="b.label">
            <td>{{ b.label }}</td>
            <td class="num">{{ b.count }}</td>
            <td class="num">{{ pctText(b.count, ageKnown) }}</td>
          </tr>
          <tr v-if="!ageKnown"><td colspan="3" class="empty">暂无可统计的在租订单</td></tr>
        </tbody>
      </table>

      <div v-else-if="!ageKnown" class="empty">暂无可统计的在租订单</div>

      <div v-else class="chart">
        <div class="chart-body" :style="{ height: PLOT_H + 'px' }">
          <div class="yaxis">
            <div v-for="t in ageScale.ticks" :key="t" class="ytick"
                 :style="{ bottom: (t / ageScale.yMax * 100) + '%' }">{{ t }}</div>
          </div>
          <div class="plot">
            <div v-for="t in ageScale.ticks" :key="'g' + t" class="gridline"
                 :class="{ base: t === 0 }"
                 :style="{ bottom: (t / ageScale.yMax * 100) + '%' }"></div>
            <div class="cols">
              <div v-for="(b, i) in ageBuckets" :key="b.label" class="col" tabindex="0"
                   @mouseenter="showTip($event, b.label + '：' + b.count + ' 单 · ' + pctText(b.count, ageKnown))"
                   @mousemove="moveTip"
                   @focus="showTipAt($event.target, b.label + '：' + b.count + ' 单 · ' + pctText(b.count, ageKnown))"
                   @mouseleave="tip = null" @blur="tip = null">
                <div class="col-cap" v-if="i === ageMaxIdx"
                     :style="{ bottom: 'calc(' + barPct(b.count, ageScale.yMax) + ' + 6px)' }">{{ b.count }}</div>
                <div class="col-bar" :style="{ height: barPct(b.count, ageScale.yMax) }"></div>
              </div>
            </div>
          </div>
        </div>
        <div class="xaxis">
          <div class="ygutter"></div>
          <div class="xlabs">
            <span v-for="b in ageBuckets" :key="b.label" class="xlab">{{ b.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 性别分布 -->
    <div class="card">
      <div class="card-h">
        <div>
          <div class="card-title">在租订单性别分布</div>
          <div class="muted" style="margin-top:4px">按身份证顺序码推算（奇男偶女）；未实名订单计入「未知」</div>
        </div>
        <button class="btn-link" @click="tableView.gender = !tableView.gender">
          {{ tableView.gender ? '图表' : '表格' }}
        </button>
      </div>

      <table v-if="tableView.gender" class="table">
        <thead><tr><th>性别</th><th style="width:120px">订单数</th><th style="width:120px">占比</th></tr></thead>
        <tbody>
          <tr v-for="g in genderRows" :key="g.key">
            <td>{{ g.label }}</td>
            <td class="num">{{ g.count }}</td>
            <td class="num">{{ pctText(g.count, genderTotal) }}</td>
          </tr>
          <tr v-if="!genderTotal"><td colspan="3" class="empty">暂无可统计的在租订单</td></tr>
        </tbody>
      </table>

      <div v-else-if="!genderTotal" class="empty">暂无可统计的在租订单</div>

      <div v-else>
        <div class="sbar">
          <div v-for="g in genderRows.filter(r => r.count)" :key="g.key"
               class="sbar-seg" :style="{ width: (g.count / genderTotal * 100) + '%', background: g.color }"
               @mouseenter="showTip($event, g.label + '：' + g.count + ' 单 · ' + pctText(g.count, genderTotal))"
               @mousemove="moveTip" @mouseleave="tip = null">
            <span v-if="g.count / genderTotal >= 0.14" class="sbar-lab" :style="{ color: g.ink }">
              {{ pctText(g.count, genderTotal) }}
            </span>
          </div>
        </div>
        <div class="legend">
          <div v-for="g in genderRows" :key="g.key" class="legend-item">
            <span class="swatch" :style="{ background: g.color }"></span>
            <span>{{ g.label }}</span>
            <span class="legend-v">{{ g.count }} 单 · {{ pctText(g.count, genderTotal) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 分商品租赁时间 -->
    <div class="card">
      <div class="card-h">
        <div>
          <div class="card-title">分商品租赁时间</div>
          <div class="muted" style="margin-top:4px">
            条形为平均合同租期，按时长倒序；已取消订单不计入，共 {{ s.lease?.order_total || 0 }} 单。
            实际占用基于 {{ s.lease?.actual_samples || 0 }} 单已归还订单<template
              v-if="s.lease?.actual_excluded">，另有 {{ s.lease.actual_excluded }} 单占用不足 1 天（判为测试单 / 误操作）已剔除</template>
          </div>
        </div>
        <button class="btn-link" @click="tableView.product = !tableView.product">
          {{ tableView.product ? '图表' : '表格' }}
        </button>
      </div>

      <table v-if="tableView.product" class="table">
        <thead>
          <tr>
            <th>商品</th>
            <th style="width:100px">订单数</th>
            <th style="width:130px">平均合同租期</th>
            <th style="width:150px">平均实际占用</th>
            <th style="width:120px">累计租赁天数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in products" :key="p.product_id">
            <td>{{ p.product_name }}</td>
            <td class="num">{{ p.orders }}</td>
            <td class="num">{{ fmtNum(p.contract_avg_days) }} 天</td>
            <td class="num">
              <template v-if="p.actual_avg_days == null">—</template>
              <template v-else>{{ fmtNum(p.actual_avg_days) }} 天（{{ p.actual_samples }} 单）</template>
            </td>
            <td class="num">{{ p.contract_total_days }}</td>
          </tr>
          <tr v-if="!products.length"><td colspan="5" class="empty">暂无数据</td></tr>
        </tbody>
      </table>

      <div v-else-if="!products.length" class="empty">暂无数据</div>

      <div v-else class="pbars">
        <div v-for="p in products" :key="p.product_id" class="pbar-row"
             @mouseenter="showTip($event, p.product_name + '：合同 ' + fmtNum(p.contract_avg_days) + ' 天 · '
                            + p.orders + ' 单 · 实际 ' + (p.actual_avg_days == null ? '样本不足'
                            : fmtNum(p.actual_avg_days) + ' 天'))"
             @mousemove="moveTip" @mouseleave="tip = null">
          <div class="pbar-name" :title="p.product_name">{{ p.product_name }}</div>
          <div class="pbar-track">
            <div class="pbar-inner">
              <div class="pbar-fill" :style="{ width: barPct(p.contract_avg_days, productMax) }"></div>
              <span class="pbar-v" :style="{ left: barPct(p.contract_avg_days, productMax) }">
                {{ fmtNum(p.contract_avg_days) }} 天
              </span>
            </div>
          </div>
          <div class="pbar-sub">
            {{ p.orders }} 单 ·
            实际 {{ p.actual_avg_days == null ? '—' : fmtNum(p.actual_avg_days) + ' 天' }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="tip" class="viz-tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">{{ tip.text }}</div>
  </template>
</template>

<script>
const { ref, computed, inject, onMounted } = Vue;

const PLOT_H = 180;

// 轴刻度：步长取 1/2/5/10… 里第一个能把刻度压到 4 条以内的，
// 并且上界永远严格大于最大值，给柱顶的直标留出余量。
const niceScale = (max) => {
  const target = Math.max(1, max) * 1.15;
  const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000];
  let step = steps[steps.length - 1];
  for (const st of steps) { if (Math.ceil(target / st) <= 4) { step = st; break; } }
  const yMax = step * Math.max(1, Math.ceil(target / step));
  const ticks = [];
  for (let v = 0; v <= yMax + 1e-9; v += step) ticks.push(v);
  return { yMax, ticks };
};

export default {
  setup() {
    const api = inject('api');
    const loading = ref(true);
    const s = ref({});
    const tip = ref(null);
    const tableView = ref({ age: false, gender: false, product: false });

    const load = async () => {
      loading.value = true;
      try { s.value = await api.statsCenter(); }
      catch (e) { alert(e.message); }
      finally { loading.value = false; }
    };

    const ageBuckets = computed(() => s.value.in_rent?.age?.buckets || []);
    const ageKnown   = computed(() => s.value.in_rent?.age?.known || 0);
    const ageScale   = computed(() => niceScale(Math.max(0, ...ageBuckets.value.map(b => b.count))));
    const ageMaxIdx  = computed(() => {
      let idx = -1, best = 0;
      ageBuckets.value.forEach((b, i) => { if (b.count > best) { best = b.count; idx = i; } });
      return idx;
    });

    // 男=蓝 女=橙（校验过 CVD 分离度）；未知走中性灰，不占分类色位
    const genderRows = computed(() => {
      const g = s.value.in_rent?.gender || {};
      return [
        { key: 'male',    label: '男',   count: g.male || 0,    color: '#2b7cff', ink: '#fff' },
        { key: 'female',  label: '女',   count: g.female || 0,  color: '#eb6834', ink: '#fff' },
        { key: 'unknown', label: '未知', count: g.unknown || 0, color: '#c9d2e0', ink: '#1a1f2e' },
      ];
    });
    const genderTotal = computed(() => genderRows.value.reduce((n, g) => n + g.count, 0));

    const products   = computed(() => s.value.lease?.by_product || []);
    const productMax = computed(() =>
      niceScale(Math.max(0, ...products.value.map(p => p.contract_avg_days))).yMax);

    const fmtNum = (n) => {
      if (n == null) return '—';
      return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
    };
    const pctText = (n, total) => (total ? Math.round(n / total * 1000) / 10 + '%' : '0%');
    const barPct  = (v, max) => (max ? (v / max * 100) + '%' : '0%');

    const showTip = (ev, text) => { tip.value = { text, x: ev.clientX + 12, y: ev.clientY + 14 }; };
    const moveTip = (ev) => { if (tip.value) { tip.value.x = ev.clientX + 12; tip.value.y = ev.clientY + 14; } };
    const showTipAt = (el, text) => {
      const r = el.getBoundingClientRect();
      tip.value = { text, x: r.left, y: r.bottom + 6 };
    };

    onMounted(load);
    return {
      loading, s, tip, tableView, PLOT_H,
      ageBuckets, ageKnown, ageScale, ageMaxIdx,
      genderRows, genderTotal, products, productMax,
      fmtNum, pctText, barPct, showTip, moveTip, showTipAt,
    };
  },
};
</script>

<style scoped>
.num { font-variant-numeric: tabular-nums; }
/* 窄屏下副标题会把「表格」挤成两行 */
.card-h .btn-link { white-space: nowrap; flex-shrink: 0; margin-left: 16px; }

/* ---------- 柱状图 ---------- */
.chart { padding-top: 4px; }
.chart-body { display: flex; }
.yaxis {
  position: relative;
  width: 34px;
  flex-shrink: 0;
  border-right: 1px solid #e1e5ec;
}
.ytick {
  position: absolute;
  right: 8px;
  transform: translateY(50%);
  font-size: 11px;
  color: #9aa4b2;
  font-variant-numeric: tabular-nums;
}
.plot { position: relative; flex: 1; }
.gridline {
  position: absolute; left: 0; right: 0;
  height: 1px;
  background: #eef1f6;
}
.gridline.base { background: #d8dee8; }
.cols { position: absolute; inset: 0; display: flex; }
.col {
  flex: 1;
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  cursor: default;
  outline: none;
}
.col:hover .col-bar, .col:focus .col-bar { background: #1a5fd1; }
.col:focus { background: rgba(43, 124, 255, 0.06); }
.col-bar {
  width: 100%;
  max-width: 24px;
  background: #2b7cff;
  border-radius: 4px 4px 0 0;
  transition: background 0.12s;
}
.col-cap {
  position: absolute;
  left: 0; right: 0;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: #1a1f2e;
  font-variant-numeric: tabular-nums;
}
.xaxis { display: flex; margin-top: 8px; }
.ygutter { width: 34px; flex-shrink: 0; }
.xlabs { flex: 1; display: flex; }
.xlab {
  flex: 1;
  text-align: center;
  font-size: 11px;
  color: #6b7280;
}

/* ---------- 性别堆叠条 ---------- */
.sbar {
  display: flex;
  height: 22px;
  /* 段间 2px 白缝：用底色打断，而不是给每段描边。
     不加 overflow:hidden —— 圆角由首尾段各自负责，避免裁掉段内标签 */
  gap: 2px;
}
.sbar-seg {
  display: flex; align-items: center; justify-content: center;
  min-width: 2px;
  cursor: default;
}
.sbar-seg:first-child { border-radius: 4px 0 0 4px; }
.sbar-seg:last-child  { border-radius: 0 4px 4px 0; }
.sbar-lab { font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
.legend { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 14px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #1a1f2e; }
.swatch { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.legend-v { color: #6b7280; font-size: 12px; font-variant-numeric: tabular-nums; }

/* ---------- 分商品横向条 ---------- */
.pbars { display: flex; flex-direction: column; gap: 14px; }
.pbar-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  grid-template-areas: "name track" "name sub";
  align-items: center;
  gap: 2px 14px;
  cursor: default;
}
.pbar-name {
  grid-area: name;
  font-size: 13px;
  color: #1a1f2e;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* 数值跟在条形末端：右侧留出 60px 让满格条的标签也放得下。
   条宽和标签位置都按 .pbar-inner（无 padding）取百分比，两者必然对齐。 */
.pbar-track { grid-area: track; padding-right: 60px; }
.pbar-inner { position: relative; }
.pbar-v {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  margin-left: 8px;
  font-size: 12px;
  color: #1a1f2e;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.pbar-fill {
  height: 14px;
  background: #2b7cff;
  border-radius: 0 4px 4px 0;
  min-width: 2px;
  transition: background 0.12s;
}
.pbar-row:hover .pbar-fill { background: #1a5fd1; }
.pbar-sub { grid-area: sub; font-size: 11px; color: #9aa4b2; }

/* ---------- 悬浮提示 ---------- */
.viz-tip {
  position: fixed;
  z-index: 900;
  pointer-events: none;
  background: #1c2533;
  color: #fff;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 4px;
  white-space: nowrap;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
}

@media (max-width: 700px) {
  .pbar-row { grid-template-columns: 110px 1fr; }
}
</style>
