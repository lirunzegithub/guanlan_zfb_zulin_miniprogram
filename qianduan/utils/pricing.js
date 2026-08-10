/** 租金计算 + 日期工具：商品详情页（选租期）与确认订单页（算实付）的唯一真相源。
 *
 *  为什么要抽出来：这两页展示的必须是同一个数字。各写一份的话，任何一处
 *  改了分段规则或物流期口径，另一处就会静默算出不同的金额，而用户是在
 *  确认页看到价格、在详情页做的决定。
 *
 *  注意：这里算的只是「展示价」。真正扣钱的金额由后端 app/pricing.py 重新计算，
 *  前端传什么金额后端都不认，只认 product_id / sku_id / days。
 *
 *  租期语义（酒店式）：
 *    start_date ──物流期 shipDays 天(免租)── 起租计费 ──用机 rentDays 天── end_date
 *    end_date = 归还日，当天不计费、不算持有。
 *    持有天数 days = end - start = shipDays + rentDays
 */

/** 金额显示：整数不带小数，否则保留两位。¥75 而不是 ¥75.00 */
function fmtAmount(n) {
  const v = Number(n) || 0;
  return Math.abs(v - Math.round(v)) < 0.005 ? String(Math.round(v)) : v.toFixed(2);
}

/** 金额四舍五入到「元」（half-up）：用户看到和实付的租金一律是整数。
 *
 *  先归到分再取整：分段租金是逐段浮点累加的，3.82*30 会得到
 *  114.59999999999999，直接取整会少 1 元。归到分消除累加误差后再取整到元。
 *
 *  必须与后端 app/pricing.py 的 round_yuan()、管理后台 Products.vue 的
 *  roundYuan() 保持同一规则——后端那边不能用 Python 内置 round()，
 *  它是银行家舍入（round(114.5)=114），和这里的 half-up 对不上。
 */
function roundYuan(x) {
  const cents = Math.round((Number(x) || 0) * 100);
  return Math.round(cents / 100);
}

function fmtDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** ios safari / 小程序 webview 对 'YYYY-MM-DD' 解析不一致，用 '/' 分隔更稳 */
function parseDate(s) {
  return new Date((s || '').replace(/-/g, '/'));
}

function addDays(start, days) {
  const d = parseDate(start);
  d.setDate(d.getDate() + days);
  return fmtDate(d);
}

/** 2026-07-28 → "7月28日" */
function formatDateShort(s) {
  const d = parseDate(s);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 2026-07-28 → "07.28"（确认页租赁日期时间轴用） */
function formatDateDot(s) {
  const d = parseDate(s);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${m}.${day}`;
}

/** 商品/SKU 的分段租金表；没配置时退化为单段 0 元（调用方会被后端拒单） */
function tiersOf(p) {
  return (p && p.price_tiers && p.price_tiers.length)
    ? p.price_tiers.slice().sort((a, b) => Number(a.from) - Number(b.from))
    : [{ from: 1, price: 0 }];
}

/** 用机第 N 天的单价（按 tiers 落段） */
function unitPriceForRentDay(rentDay, tiers) {
  let unit = 0;
  for (const t of tiers) {
    if (rentDay >= Number(t.from)) unit = Number(t.price) || 0;
  }
  return unit;
}

/** 分段计费：按 N 天落到的段逐段累加，总额四舍五入到元。
 *  取整只在累加完成后做一次，不逐段取整（逐段会把每段最多 0.5 元的误差累积起来）。
 *  breakdown 各段 subtotal 保持精确值——它说明的是"这段本来多少钱"，
 *  各段相加与取整后的 total 可能差几毛，属正常。 */
function calcTieredAmount(days, tiers) {
  days = Math.max(0, parseInt(days, 10) || 0);
  if (!days || !Array.isArray(tiers) || !tiers.length) return { total: 0, breakdown: [] };
  const segs = tiers.slice().sort((a, b) => Number(a.from) - Number(b.from));
  let total = 0;
  const breakdown = [];
  for (let i = 0; i < segs.length; i++) {
    const segFrom = Number(segs[i].from);
    if (segFrom > days) break;
    const next = segs[i + 1];
    const segEndRaw = next ? Number(next.from) - 1 : days;
    const segEnd = Math.min(segEndRaw, days);
    const segDays = segEnd - segFrom + 1;
    const segPrice = Number(segs[i].price) || 0;
    const subtotal = segDays * segPrice;
    total += subtotal;
    breakdown.push({
      from: segFrom, to: segEnd, days: segDays, price: segPrice,
      subtotal: Math.round(subtotal * 100) / 100,
      label: `第${segFrom}-${segEnd}天 ¥${segPrice}×${segDays}天`,
    });
  }
  return { total: roundYuan(total), breakdown };
}

function emptyRent(p, shipDays) {
  return {
    startDate: '', endDate: '',
    startDateShort: '', endDateShort: '',
    days: 0, shipDays: shipDays || 0, rentDays: 0,
    pricePerDay: 0, total: 0, breakdown: [], saved: 0,
    deposit: (p && p.deposit_amount) || 0,
  };
}

/** 起讫日 → 全套金额；前 shipDays 天物流期免租，剩余按 tier 分段算。
 *  只传 start 不传 end 时返回半成品（详情页日历"已选起租日"的中间态）。 */
function calcRent(start, end, p, shipDays) {
  const ship = shipDays || 0;
  if (!start) return emptyRent(p, ship);
  const tiers = tiersOf(p);
  const firstPrice = Number(tiers[0].price) || 0;
  const deposit = (p && p.deposit_amount) || 0;

  if (!end) {
    return {
      startDate: start, endDate: '',
      startDateShort: formatDateShort(start), endDateShort: '',
      days: 0, shipDays: ship, rentDays: 0,
      pricePerDay: 0, total: 0, breakdown: [], saved: 0,
      deposit,
    };
  }

  const sd = parseDate(start);
  const ed = parseDate(end);
  // end = 归还日（不计入持有），持有天数 = end - start = 物流期 + 用机天数
  const totalDays = Math.round((ed - sd) / 86400000);
  const rentDays = Math.max(0, totalDays - ship);
  const { total, breakdown } = calcTieredAmount(rentDays, tiers);
  // 原价同样按元取整后再相减，否则省下的钱会冒出小数尾巴
  const saved = Math.max(0, roundYuan(firstPrice * rentDays) - total);
  const pricePerDay = rentDays ? Math.round((total / rentDays) * 100) / 100 : 0;
  return {
    startDate: start, endDate: end,
    startDateShort: formatDateShort(start),
    endDateShort: formatDateShort(end),
    days: totalDays, shipDays: ship, rentDays,
    pricePerDay, total, breakdown, saved, deposit,
  };
}

/** 给定用机天数 → 一组起讫日，起租日 = 今天。
 *  归还日 = 今天 + 物流期 + 用机天数（即最后用机日的次日）。 */
function rangeForRentDays(rentDays, shipDays) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = fmtDate(today);
  const totalDays = (shipDays || 0) + Math.max(1, rentDays);
  return { start, end: addDays(start, totalDays) };
}

/** 起讫日 → 确认订单页的四点时间轴。
 *  物流期覆盖 start ~ start+ship-1，故签收 = 物流期最后一天，次日开始计费。
 *  ship=0（无物流期）时签收即起租日，四点退化为三点，展示上不冲突。 */
function buildTimeline(start, end, shipDays) {
  if (!start || !end) return null;
  const ship = Math.max(0, shipDays || 0);
  const receiveDay = addDays(start, Math.max(0, ship - 1));   // 签收
  const rentStart  = addDays(start, ship);                     // 起租日（开始计费）
  const expireDay  = addDays(end, -1);                         // 到期日（最后用机日）
  return {
    receive:   formatDateDot(receiveDay),
    rentStart: formatDateDot(rentStart),
    expire:    formatDateDot(expireDay),
    giveBack:  formatDateDot(end),
  };
}

module.exports = {
  fmtAmount,
  roundYuan,
  fmtDate,
  parseDate,
  addDays,
  formatDateShort,
  formatDateDot,
  tiersOf,
  unitPriceForRentDay,
  calcTieredAmount,
  emptyRent,
  calcRent,
  rangeForRentDays,
  buildTimeline,
};
