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
          <th style="width:200px">操作</th>
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
          <td>{{ depositText(p) }}</td>
          <td>{{ p.sku_count > 0 ? p.sku_sales : p.sales }}</td>
          <td>
            <!-- 库存的真相在 SKU 层：展示各 SKU 汇总，点进去逐个改 -->
            <span v-if="p.sku_count > 0" class="muted stock-bysku" @click="openSkus(p)">
              {{ p.sku_stock }} 件 · {{ p.sku_count }} SKU ›
            </span>
            <div v-else class="stock-edit">
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
            <button class="btn-link" @click="openSkus(p)" title="管理该商品的 SKU">
              SKU{{ p.sku_count ? '(' + p.sku_count + ')' : '' }}
            </button>
            <button class="btn-link" @click="openClone(p)" title="复制全部配置为一个新商品">克隆</button>
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
              <span>押金 <b>{{ depositText(p) }}</b></span>
              <span>销量 <b>{{ p.sku_count > 0 ? p.sku_sales : p.sales }}</b></span>
            </div>
          </div>
        </div>

        <div class="pc-foot">
          <div v-if="p.sku_count > 0" class="stock-edit">
            <span class="muted">库存</span>
            <span class="muted stock-bysku" @click="openSkus(p)">
              {{ p.sku_stock }} 件 · {{ p.sku_count }} SKU ›
            </span>
          </div>
          <div v-else class="stock-edit">
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
            <button class="btn-link" @click="openSkus(p)">SKU{{ p.sku_count ? '(' + p.sku_count + ')' : '' }}</button>
            <button class="btn-link" @click="openClone(p)">克隆</button>
            <button class="btn-link danger" @click="remove(p)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 编辑弹窗（含主要字段；高级字段直接给 JSON 编辑） -->
  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal" style="width:680px">
      <div class="modal-h">{{ form.id ? '编辑商品' : (cloneSrc ? '克隆商品' : '新增商品') }}</div>
      <div class="modal-body">
        <div v-if="cloneSrc" class="clone-tip">
          正在克隆 <b>#{{ cloneSrc.id }} {{ cloneSrc.name }}</b>：已复制全部配置，销量已清零、状态默认「下架」。
          <template v-if="cloneSrc.sku_count">它的 {{ cloneSrc.sku_count }} 个 SKU 会在保存后一并复制过来。</template>
          保存后会生成一个全新商品，请先改好<b>标题和分类</b>，价格押金到 SKU 里改，确认无误再上架。
        </div>
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

        <!-- 单一数据源：价格 / 押金 / 库存 / 销量只存在于 SKU 层。
             已有 SKU 的商品这里不再提供第二个入口，避免两处能改价、互相打架。 -->
        <div v-if="formSkuCount > 0" class="sku-owned">
          <div class="sku-owned-h">价格 · 押金 · 库存 · 销量 由 SKU 维护</div>
          <div class="sku-owned-b">
            该商品有 <b>{{ formSkuCount }}</b> 个 SKU，这四项已下沉到每个 SKU 各自配置，
            商品层不再保存也不参与下单。
          </div>
          <button class="btn btn-sm" @click="openSkusFromForm">管理 SKU ›</button>
        </div>

        <template v-else>
        <div v-if="!form.id" class="sku-owned sku-owned-new">
          下面填的价格 / 押金 / 库存，保存后会自动成为该商品的第一个 SKU（{{ DEFAULT_SKU_NAME }}）。
          之后要加档位或改价，都在「SKU」里维护。
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
                    type="text"
                    inputmode="numeric"
                    class="input"
                    :value="t.from"
                    :disabled="i === 0"
                    @input="onTierFromInput(i, $event.target.value)"
                    @blur="onTierFromBlur(i)"
                  />
                </td>
                <td>
                  <input
                    type="text"
                    inputmode="decimal"
                    class="input"
                    placeholder="如 9.9"
                    :value="t.price"
                    @input="onTierPriceInput(i, $event.target.value)"
                    @blur="onTierPriceBlur(i)"
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
        </template>
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
          <div class="field" style="width:150px">
            <div class="label">SKU 选择行标题</div>
            <input class="input" v-model="form.sku_option_name" placeholder="SKU" />
            <div class="muted" style="margin-top:4px;font-size:12px">小程序里的叫法，可填 容量 / 版本 / 成色</div>
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

  <!-- SKU 管理弹窗：上半列表 + 下半编辑表单，不再往下嵌弹窗 -->
  <div v-if="skuModal" class="modal-mask" @click.self="closeSkus">
    <div class="modal" style="width:820px">
      <div class="modal-h">SKU 管理 · {{ skuProduct.name }}</div>
      <div class="modal-body">
        <div class="sku-tip">
          <b>价格、押金、库存、销量的唯一来源就是这里</b>，商品本身不再保存这几项。
          配了 2 个以上 SKU 时，小程序详情页会出现「{{ skuProduct.sku_option_name || 'SKU' }}」选择行；
          只有 1 个时不显示选择行，用户直接按它的价格下单。
        </div>

        <div class="sku-order-tip">
          拖动左侧 <span class="drag-dots">⠿</span> 可调整顺序，小程序详情页的规格就按这个顺序展示。
          <span v-if="skuOrderDirty" class="sku-order-actions">
            <button class="btn btn-sm btn-primary" :disabled="skuOrderSaving" @click="saveSkuOrder">
              {{ skuOrderSaving ? '保存中…' : '保存顺序' }}
            </button>
            <button class="btn btn-sm" :disabled="skuOrderSaving" @click="loadSkus">撤销</button>
          </span>
        </div>

        <table class="table sku-table">
          <thead>
            <tr>
              <th style="width:34px"></th>
              <th style="width:64px">顺序</th>
              <th>SKU</th>
              <th style="width:100px">押金</th>
              <th style="width:100px">起价</th>
              <th style="width:80px">库存</th>
              <th style="width:80px">销量</th>
              <th style="width:70px">状态</th>
              <th style="width:110px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(s, i) in skuList"
              :key="s.id"
              :class="{
                'sku-row-on': skuForm && skuForm.id === s.id,
                'sku-row-dragging': skuDragFrom === i,
                'sku-row-over': skuDragOver === i && skuDragFrom !== i,
              }"
              draggable="true"
              @dragstart="onSkuDragStart(i, $event)"
              @dragover.prevent="skuDragOver = i"
              @dragleave="skuDragOver === i && (skuDragOver = -1)"
              @drop.prevent="onSkuDrop(i)"
              @dragend="onSkuDragEnd"
            >
              <td class="drag-cell" title="按住拖动排序"><span class="drag-dots">⠿</span></td>
              <td>
                <!-- 触屏/精确微调的兜底：HTML5 拖拽在触屏上不触发 -->
                <button class="btn-move" :disabled="i === 0" title="上移" @click="moveSku(i, -1)">▲</button>
                <button class="btn-move" :disabled="i === skuList.length - 1" title="下移" @click="moveSku(i, 1)">▼</button>
              </td>
              <td>
                <span class="swatch" :style="shotStyle(s.cover_url)"></span>
                {{ s.name }}
              </td>
              <td>¥{{ s.deposit_amount || 0 }}</td>
              <td>¥{{ s.min_price || 0 }}/天</td>
              <td :class="{ 'stock-zero': !(s.stock > 0) }">{{ s.stock }}</td>
              <td>{{ s.sales || 0 }}</td>
              <td>
                <span :class="['tag', s.status === 'on' ? 'tag-green' : 'tag-gray']">
                  {{ s.status === 'on' ? '在售' : '下架' }}
                </span>
              </td>
              <td>
                <button class="btn-link" @click="editSku(s)">编辑</button>
                <button class="btn-link danger" @click="removeSku(s)">删除</button>
              </td>
            </tr>
            <tr v-if="skuLoading"><td colspan="9" class="loading">加载中...</td></tr>
            <tr v-else-if="!skuList.length">
              <td colspan="9" class="empty">还没有 SKU。点下方「＋ 新增 SKU」开始配置。</td>
            </tr>
          </tbody>
        </table>

        <div style="margin-top:10px">
          <button class="btn btn-sm" @click="newSku">＋ 新增 SKU</button>
        </div>

        <!-- SKU 编辑表单 -->
        <div v-if="skuForm" class="sku-edit">
          <div class="sku-edit-h">{{ skuForm.id ? '编辑 SKU #' + skuForm.id : '新增 SKU' }}</div>

          <div class="row" style="gap:12px">
            <div class="field" style="flex:1">
              <div class="label">SKU 名称 *</div>
              <input class="input" v-model="skuForm.name" placeholder="如：128G 深空灰" />
            </div>
            <div class="field" style="width:120px">
              <div class="label">库存</div>
              <input type="number" min="0" class="input" v-model.number="skuForm.stock" />
            </div>
            <div class="field" style="width:120px">
              <div class="label">销量</div>
              <input type="number" min="0" class="input" v-model.number="skuForm.sales" />
            </div>
            <div class="field" style="width:140px">
              <div class="label">押金 *</div>
              <input type="number" min="0" step="0.01" class="input" v-model.number="skuForm.deposit_amount" />
            </div>
            <div class="field" style="width:110px">
              <div class="label">状态</div>
              <select class="select" v-model="skuForm.status">
                <option value="on">在售</option>
                <option value="off">下架</option>
              </select>
            </div>
          </div>

          <div class="field">
            <div class="label">SKU 封面（可选）</div>
            <div class="shots-grid">
              <div v-if="skuForm.cover_url" class="shot-cell">
                <div class="shot-thumb" :style="shotStyle(skuForm.cover_url)"></div>
                <div class="shot-bar">
                  <button type="button" class="btn-link danger" @click="skuForm.cover_url = ''" title="移除">×</button>
                </div>
              </div>
              <label class="shot-add">
                <input type="file" accept="image/*" hidden @change="onSkuCoverPick" />
                <span v-if="skuCoverUploading">上传中…</span>
                <span v-else>{{ skuForm.cover_url ? '＋ 更换' : '＋ 上传' }}</span>
              </label>
            </div>
            <div class="muted" style="margin-top:6px">
              留空则沿用商品主图。配了独立图会单独上传一份支付宝素材，订单中心显示该 SKU 的图。
            </div>
          </div>

          <div class="field">
            <div class="label">价格分段 price_tiers</div>
            <div class="tiers-help">
              规则与商品一致：第一段必须从「第 1 天起」，每段单价 = 该天起的每日租金。
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
                <tr v-for="(t, i) in (skuForm.price_tiers || [])" :key="i">
                  <td>{{ i + 1 }}</td>
                  <td>
                    <input
                      type="text"
                      inputmode="numeric"
                      class="input"
                      :value="t.from"
                      :disabled="i === 0"
                      @input="onSkuTierFromInput(i, $event.target.value)"
                      @blur="onSkuTierFromBlur(i)"
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      inputmode="decimal"
                      class="input"
                      placeholder="如 9.9"
                      :value="t.price"
                      @input="onSkuTierPriceInput(i, $event.target.value)"
                      @blur="onSkuTierPriceBlur(i)"
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      class="btn-link danger"
                      :disabled="(skuForm.price_tiers || []).length <= 1 || i === 0"
                      @click="removeSkuTier(i)"
                    >删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div style="margin-top:8px">
              <button type="button" class="btn btn-sm" @click="addSkuTier">＋ 增加一段</button>
              <span v-if="skuTierError" class="tier-error">{{ skuTierError }}</span>
              <span v-else-if="skuTierRising" class="rent-warn">{{ skuTierRising }}</span>
            </div>

            <!-- 常用租期速览：双向。改上面的分段这里实时跟着变；
                 反过来改这里的总价，可以倒解出各段单价写回上面。 -->
            <div class="rent-preview" :class="{ 'rent-preview-stale': skuTierError && !rentDirty }">
              <div class="rent-preview-h">
                常用租期租金<span class="muted">（可直接改总价反推分段，不含优惠券）</span>
                <span v-if="skuTierError && !rentDirty" class="rent-warn">分段未填完，结果仅供参考</span>
              </div>
              <div class="rent-preview-list">
                <div
                  v-for="(r, i) in rentCells"
                  :key="r.days"
                  class="rent-cell"
                  :class="{ 'rent-cell-changed': r.changed }"
                >
                  <div class="rent-days">{{ r.days }} 天</div>
                  <div class="rent-total-in">
                    <span class="rent-cny">¥</span>
                    <input
                      type="text"
                      inputmode="decimal"
                      class="rent-input"
                      :value="r.raw"
                      @input="onRentTargetInput(i, $event.target.value)"
                    />
                  </div>
                  <div class="rent-unit">折合 ¥{{ r.perDay }}/天</div>
                </div>
              </div>

              <div class="rent-solve-bar">
                <template v-if="rentDirty">
                  <button
                    type="button"
                    class="btn btn-sm"
                    :disabled="!!rentSolveError"
                    @click="applyRentTargets"
                  >↑ 按这些总价反推分段</button>
                  <button type="button" class="btn btn-ghost btn-sm" @click="resetRentTargets">还原</button>
                  <span v-if="rentSolveError" class="tier-error">{{ rentSolveError }}</span>
                  <span v-else class="muted">
                    会按「第 {{ PREVIEW_FROMS.join(' / ') }} 天起」重建分段（同价相邻段自动合并），
                    你手填的起始天将被覆盖
                  </span>
                </template>
                <span v-else class="muted">改任意一格总价即可反推各段单价；未改的档位价格保持不变</span>
              </div>

              <div v-if="rentSolveNote && rentSolveNote.length" class="rent-solve-note">
                单价取整到分后有零头，实际总价：
                <b v-for="n in rentSolveNote" :key="n.days">
                  {{ n.days }} 天 ¥{{ n.actual }}（{{ n.diff > 0 ? '+' : '' }}{{ n.diff }}）
                </b>
              </div>
            </div>
          </div>

          <div class="sku-edit-f">
            <button class="btn btn-ghost btn-sm" @click="skuForm = null">取消</button>
            <button class="btn btn-sm" :disabled="skuSaving" @click="saveSku">
              {{ skuSaving ? '保存中…' : (skuForm.id ? '保存 SKU' : '创建 SKU') }}
            </button>
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn" @click="closeSkus">完成</button>
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

// 常用租期速览的天数档位。
// 必须与小程序详情页的快捷租期（qianduan/pages/product/product.js 的 rentPresets）
// 保持一致：这里每个档位既是「填总价反推单价」的输入格，也决定了分段的边界，
// 两边不一致会出现「后台按 15 天定的价，用户在小程序里选不到 15 天」。
const PREVIEW_DAYS = [3, 7, 10, 15, 20, 30];
// 反推时生成的段起始天：每段接在上一档的次日开始（首段固定第 1 天）
const PREVIEW_FROMS = PREVIEW_DAYS.map((d, i) => (i === 0 ? 1 : PREVIEW_DAYS[i - 1] + 1));

// 下面两个函数是 app/pricing.py 的 normalize_tiers / calc_amount 的前端镜像，
// 只用于编辑时的实时预览；下单金额一律以后端为准，两边算法必须保持一致。
// 编辑态里 from/price 可能还是字符串（"9." 这种半成品），一律 Number() 兜底。
// Python 的 int()/float() 遇到 "" 或 "9.5" 这类串会抛异常、整段被丢弃，
// 而 JS 的 Number("") 是 0、parseInt("9.5") 是 9 —— 差异会让预览算出与后端
// 不同的金额，所以这里严格照搬 Python 的解析语义，解析不了一律返回 null。
const _pyInt = (v) => {
  if (typeof v === 'number') return Number.isFinite(v) ? Math.trunc(v) : null;
  const s = String(v ?? '').trim();
  return /^[+-]?\d+$/.test(s) ? parseInt(s, 10) : null;
};
const _pyFloat = (v) => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const s = String(v ?? '').trim();
  return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(s) ? Number(s) : null;
};

const normalizeTiers = (raw) => {
  const out = [];
  for (const t of (raw || [])) {
    if (!t || typeof t !== 'object') continue;
    const f = _pyInt(t.from);
    const p = _pyFloat(t.price);
    if (f === null || p === null) continue;
    if (f < 1 || p < 0) continue;
    out.push({ from: f, price: p });
  }
  out.sort((a, b) => a.from - b.from);

  const dedup = [];                       // from 重复时保留后者
  for (const t of out) {
    if (dedup.length && dedup[dedup.length - 1].from === t.from) dedup[dedup.length - 1] = t;
    else dedup.push(t);
  }
  const folded = [];                      // 折叠相邻同价段
  for (const t of dedup) {
    if (folded.length && folded[folded.length - 1].price === t.price) continue;
    folded.push(t);
  }
  if (!folded.length) return [{ from: 1, price: 0 }];
  if (folded[0].from !== 1) folded[0] = { from: 1, price: folded[0].price };
  return folded;
};

/** 金额四舍五入到「元」（half-up）：用户看到和实付的租金一律是整数。
 *  先归到分再取整，消除逐段浮点累加的误差（3.82*30 = 114.59999999999999）。
 *  与 app/pricing.py 的 round_yuan()、小程序 utils/pricing.js 的 roundYuan()
 *  必须同规则——后端那边不能用 Python 内置 round()（银行家舍入）。 */
const roundYuan = (x) => {
  const cents = Math.round((Number(x) || 0) * 100);
  return Math.round(cents / 100);
};

/** 按分段累加 N 天总额，四舍五入到元（累加完成后取整一次，不逐段取整）。
 *  这里算出来的就是用户下单时会看到、也会实付的数，必须与后端一致。 */
const calcAmount = (days, tiers) => {
  const n = Math.max(0, parseInt(days, 10) || 0);
  if (!n) return 0;
  const segs = normalizeTiers(tiers);
  let total = 0;
  for (let i = 0; i < segs.length; i++) {
    const segFrom = segs[i].from;
    if (segFrom > n) break;
    const segEnd = Math.min(i + 1 < segs.length ? segs[i + 1].from - 1 : n, n);
    total += (segEnd - segFrom + 1) * segs[i].price;
  }
  return roundYuan(total);
};

const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;

// ---- 反推：由「各档位目标总价」倒解各段单价 ----
// 预览里的总价 T(d) 就是日租金曲线的累积面积，所以相邻两档之间的平均日租金
// 正好是那一段该收的单价：
//     p_i = (T[d_i] - T[d_{i-1}]) / (d_i - d_{i-1})，  段起点 from_i = d_{i-1} + 1
// 下三角方程组，从前往后逐段代入即得唯一解，不需要拟合或迭代。
// 代价是段边界被钉死在档位上（PREVIEW_FROMS），原来手工设的 from 会被覆盖。
const solveTiersFromTotals = (targets) => {
  const tiers = [];
  let prevDay = 0;
  let prevTotal = 0;
  for (const { days, total } of targets) {
    tiers.push({
      from: prevDay + 1,
      price: round2((total - prevTotal) / (days - prevDay)),
    });
    prevDay = days;
    prevTotal = total;
  }
  return tiers;
};

// T(d) 是累积额，必须严格递增：后一档 ≤ 前一档会解出 ≤0 的单价。
const validateRentTargets = (raws) => {
  let prevDay = 0;
  let prevTotal = 0;
  for (let i = 0; i < PREVIEW_DAYS.length; i++) {
    const d = PREVIEW_DAYS[i];
    const s = String(raws[i] ?? '').trim();
    if (s === '') return `${d} 天总价不能为空`;
    const v = _pyFloat(s);
    if (v === null) return `${d} 天总价不是有效数字`;
    if (v < 0) return `${d} 天总价不能为负`;
    if (i > 0 && v <= prevTotal) {
      return `${d} 天总价（¥${v}）必须大于 ${prevDay} 天（¥${prevTotal}），否则第 ${i + 1} 段单价会 ≤ 0`;
    }
    prevDay = d;
    prevTotal = v;
  }
  return '';
};

// 金额展示：整数不拖 .00，小数最多两位
const money = (n) => {
  const v = Math.round((Number(n) || 0) * 100) / 100;
  return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0$/, '');
};

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
    // 押金现在挂在 SKU 上，各 SKU 可能不同 → 列表显示区间
    const depositText = (p) => {
      if (!(p.sku_count > 0)) return `¥${p.deposit_amount || 0}`;
      const lo = p.sku_deposit_min || 0;
      const hi = p.sku_deposit_max || 0;
      return lo === hi ? `¥${lo}` : `¥${lo} ~ ${hi}`;
    };
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
    // 与 PREVIEW_DAYS / 小程序 rentPresets 同档位：扫码带进来的租期必须是
    // 用户在详情页快捷条上能选中的天数，否则扫码后那个档位不高亮、显得没生效
    const sharePresets = [3, 7, 10, 15, 20, 30];
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

    const cloneSrc = ref(null);   // 克隆来源商品（仅用于弹窗标题提示）
    // 当前编辑的商品有几个 SKU：>0 时商品弹窗隐藏价格/押金/库存/销量（单一数据源）
    const formSkuCount = ref(0);
    const DEFAULT_SKU_NAME = '标准版';   // 与后端 repos.DEFAULT_SKU_NAME 对齐，仅用于文案

    const openNew = () => {
      cloneSrc.value = null;
      formSkuCount.value = 0;
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
    // 把列表里的商品记录拷成一份可编辑的表单（编辑 / 克隆共用）。
    // 深拷贝 covers / real_shots / price_tiers，避免编辑过程中改到列表里的引用；
    // 没 covers 的旧数据用 cover_url 兜底。
    const _formFromProduct = (p) => {
      const tiers = Array.isArray(p.price_tiers) && p.price_tiers.length
        ? p.price_tiers.map(t => ({ from: Number(t.from), price: Number(t.price) }))
        : [{ from: 1, price: 20 }];
      const covers = Array.isArray(p.covers) && p.covers.length
        ? p.covers.slice()
        : (p.cover_url ? [p.cover_url] : []);
      const f = {
        // damage_standard 已无后台编辑入口，随 ...p 原样透传，保存时不动既有数据
        ...p,
        covers,
        real_shots: Array.isArray(p.real_shots) ? p.real_shots.slice() : [],
        price_tiers: tiers,
      };
      // 旧数据可能还残留这些字段；不让它们随保存请求回传给后端。
      delete f.price;
      delete f.promo_label;
      delete f.activity;
      delete f.amount;       // 已废弃的"额度卡面额"字段
      // 列表接口注入的 SKU 聚合值，只用于渲染，不能回传给后端（会被白名单丢弃并报"已忽略字段"）
      delete f.sku_count;
      delete f.sku_stock;
      delete f.sku_sales;
      delete f.sku_deposit_min;
      delete f.sku_deposit_max;
      return f;
    };

    const openEdit = (p) => {
      form.value = _formFromProduct(p);
      formSkuCount.value = Number(p.sku_count) || 0;
      cloneSrc.value = null;
      tierError.value = '';
      resetQr();
      modal.value = true;
      // 打开已有商品时自动生成"默认（无租期）"小程序码
      genQrcode(0);
    };

    // 一键克隆：复制全部配置后走"新增"分支（后端 POST 会重新校验、重新上传支付宝素材）。
    // 用途：同一台机器复制成"专拍押金"与"实际租赁"两个商品，只改分组 / 标题 / 价格即可。
    const openClone = (p) => {
      const f = _formFromProduct(p);
      delete f.id;                       // 没 id → save() 走 create
      delete f.created_at;
      delete f.updated_at;
      delete f.alipay_image_material_id; // 新商品保存后会自动重新上传封面素材
      delete f.alipay_image_source;
      f.name = `${p.name || ''} - 副本`;
      f.sales = 0;                       // 销量 / 累计租出不跟着复制
      f.rented_count = 0;
      f.status = 'off';                  // 默认下架，防止没改价就被下单
      form.value = f;
      cloneSrc.value = { id: p.id, name: p.name, sku_count: Number(p.sku_count) || 0 };
      // 克隆体保存后会把来源的 SKU 全部复制过来，所以按"已有 SKU"渲染，隐藏价格三件套
      formSkuCount.value = Number(p.sku_count) || 0;
      tierError.value = '';
      resetQr();                         // 还没 id，分享区不可用
      modal.value = true;
    };

    // ---- 分段租金编辑 ----
    const tierError = ref('');

    // 输入过程中把用户敲的原文留在 state 里（"12."、"0."、"" 都是合法中间态）。
    // 若在 @input 里直接 parseFloat 回写，:value 会把刚敲的小数点刷掉，
    // 单价就永远只能输整数——所以这里只做字符清洗，数值化推迟到 blur / 保存。
    const sanitizeDecimal = (v) => {
      let s = String(v ?? '').replace(/[^\d.]/g, '');
      const dot = s.indexOf('.');
      if (dot >= 0) s = s.slice(0, dot + 1) + s.slice(dot + 1).replace(/\./g, '');
      return s.replace(/^(\d*\.\d{0,2}).*$/, '$1');   // 金额最多两位小数
    };
    const sanitizeInt = (v) => String(v ?? '').replace(/\D/g, '');
    // 提交前把编辑态的字符串统一成数字，别把 "9.9" 这种文本发给后端
    const numericTiers = (tiers) => (tiers || []).map(t => ({
      ...t,
      from: parseInt(t.from, 10) || 0,
      price: round2(t.price),
    }));

    const validateTiers = (tiers) => {
      if (!Array.isArray(tiers) || !tiers.length) return '至少需要一段租金';
      let lastFrom = 0;
      for (let i = 0; i < tiers.length; i++) {
        const t = tiers[i];
        if (String(t.from ?? '').trim() === '') return `第 ${i + 1} 段：请填写起始天`;
        if (String(t.price ?? '').trim() === '') return `第 ${i + 1} 段：请填写单价`;
        const f = Number(t.from), p = Number(t.price);
        if (!Number.isFinite(f) || !Number.isFinite(p)) return `第 ${i + 1} 段：起始天/单价必须是数字`;
        if (p < 0) return `第 ${i + 1} 段：单价不能为负`;
        if (i === 0 && f !== 1) return '第一段必须从第 1 天起';
        if (f <= lastFrom) return `第 ${i + 1} 段：起始天必须大于上一段（当前 ${f} ≤ ${lastFrom}）`;
        lastFrom = f;
      }
      return '';
    };

    const patchTier = (i, patch) => {
      const tiers = (form.value.price_tiers || []).slice();
      tiers[i] = { ...tiers[i], ...patch };
      form.value.price_tiers = tiers;
      tierError.value = validateTiers(tiers);
    };
    const onTierFromInput = (i, v) => patchTier(i, { from: sanitizeInt(v) });
    const onTierPriceInput = (i, v) => patchTier(i, { price: sanitizeDecimal(v) });
    const onTierFromBlur = (i) => {
      patchTier(i, { from: parseInt(form.value.price_tiers[i]?.from, 10) || 0 });
    };
    const onTierPriceBlur = (i) => {
      patchTier(i, { price: round2(form.value.price_tiers[i]?.price) });
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

    // ---- SKU 管理 ----
    const skuModal = ref(false);
    const skuProduct = ref({});      // 当前正在配 SKU 的商品
    const skuList = ref([]);
    const skuForm = ref(null);       // null = 未在编辑
    const skuLoading = ref(false);
    const skuSaving = ref(false);
    const skuTierError = ref('');
    const skuCoverUploading = ref(false);

    // ---- SKU 拖拽排序 ----
    // 拖动只改本地数组，攒够了点「保存顺序」再一次性提交整个 id 序列。
    // 每拖一次就发一个请求的话，中途失败会留下半新半旧的顺序。
    const skuDragFrom = ref(-1);     // 正在拖的行下标
    const skuDragOver = ref(-1);     // 当前悬停的行下标（画落点高亮）
    const skuOrderDirty = ref(false);
    const skuOrderSaving = ref(false);

    const loadSkus = async (pid) => {
      // 模板里「撤销」按钮直接绑的本函数，会把事件对象当参数传进来
      const id = (typeof pid === 'number' || typeof pid === 'string')
        ? pid : (skuProduct.value && skuProduct.value.id);
      if (!id) return;
      skuLoading.value = true;
      try {
        const r = await api.listSkus(id);
        skuList.value = r.list || [];
        skuOrderDirty.value = false;
      } catch (e) { alert(e.message || 'SKU 加载失败'); }
      finally { skuLoading.value = false; }
    };

    const onSkuDragStart = (i, ev) => {
      skuDragFrom.value = i;
      // Firefox 不设 dataTransfer 就不会触发 drop
      try {
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', String(i));
      } catch (e) {}
    };
    const onSkuDrop = (to) => {
      const from = skuDragFrom.value;
      skuDragFrom.value = -1;
      skuDragOver.value = -1;
      if (from < 0 || from === to) return;
      const arr = skuList.value.slice();
      arr.splice(to, 0, arr.splice(from, 1)[0]);
      skuList.value = arr;
      skuOrderDirty.value = true;
    };
    const onSkuDragEnd = () => { skuDragFrom.value = -1; skuDragOver.value = -1; };

    /** 上移 / 下移一位：触屏上 HTML5 拖拽不触发，这是兜底入口 */
    const moveSku = (i, delta) => {
      const to = i + delta;
      if (to < 0 || to >= skuList.value.length) return;
      const arr = skuList.value.slice();
      [arr[i], arr[to]] = [arr[to], arr[i]];
      skuList.value = arr;
      skuOrderDirty.value = true;
    };

    const saveSkuOrder = async () => {
      if (skuOrderSaving.value || !skuOrderDirty.value) return;
      const pid = skuProduct.value && skuProduct.value.id;
      if (!pid) return;
      skuOrderSaving.value = true;
      try {
        const r = await api.reorderSkus(pid, skuList.value.map(s => s.id));
        // 用服务端返回的列表覆盖，确保本地顺序与落库结果完全一致
        if (r && r.list) skuList.value = r.list;
        skuOrderDirty.value = false;
      } catch (e) {
        alert(e.message || '排序保存失败');
        await loadSkus(pid);   // 失败就拉回服务端的真实顺序，别让页面停在假象上
      } finally { skuOrderSaving.value = false; }
    };

    const openSkus = async (p) => {
      skuProduct.value = p;
      skuList.value = [];
      skuForm.value = null;
      skuTierError.value = '';
      skuDragFrom.value = -1;
      skuDragOver.value = -1;
      skuOrderDirty.value = false;
      skuModal.value = true;
      await loadSkus(p.id);
    };

    const closeSkus = async () => {
      // 拖完没点保存就关窗 = 白拖，这里拦一下
      if (skuOrderDirty.value &&
          !confirm('SKU 顺序已调整但还没保存，关闭将丢失改动。确定关闭？')) return;
      skuOrderDirty.value = false;
      skuModal.value = false;
      skuForm.value = null;
      // SKU 增删会改变列表页的「SKU(N)」和库存/押金列，关弹窗时刷一次
      await fetch();
    };

    const newSku = () => {
      skuForm.value = {
        name: '', cover_url: '',
        stock: 1, sales: 0,
        // 押金/租金默认继承商品，改一改就能用，避免每个 SKU 从零填
        deposit_amount: Number(skuProduct.value.deposit_amount) || 2000,
        price_tiers: (skuProduct.value.price_tiers || []).length
          ? skuProduct.value.price_tiers.map(t => ({ from: Number(t.from), price: Number(t.price) }))
          : [{ from: 1, price: 20 }],
        status: 'on',
      };
      skuTierError.value = '';
      resetRentTargets();
    };

    const editSku = (s) => {
      skuForm.value = {
        id: s.id,
        name: s.name || '',
        cover_url: s.cover_url || '',
        stock: Number(s.stock) || 0,
        sales: Number(s.sales) || 0,
        deposit_amount: Number(s.deposit_amount) || 0,
        price_tiers: (Array.isArray(s.price_tiers) && s.price_tiers.length)
          ? s.price_tiers.map(t => ({ from: Number(t.from), price: Number(t.price) }))
          : [{ from: 1, price: 20 }],
        status: s.status || 'on',
      };
      skuTierError.value = '';
      resetRentTargets();
    };

    const onSkuCoverPick = async (e) => {
      const f = (e.target.files || [])[0];
      e.target.value = '';
      if (!f) return;
      skuCoverUploading.value = true;
      try {
        const r = await api.upload(f);
        if (r && r.url) skuForm.value.cover_url = r.url;
      } catch (err) { alert(err.message || '上传失败'); }
      finally { skuCoverUploading.value = false; }
    };

    // SKU 的分段租金编辑：规则与商品完全一致，复用同一个 validateTiers
    const patchSkuTier = (i, patch) => {
      const tiers = (skuForm.value.price_tiers || []).slice();
      tiers[i] = { ...tiers[i], ...patch };
      skuForm.value.price_tiers = tiers;
      skuTierError.value = validateTiers(tiers);
      resetRentTargets();     // 正向改了分段 → 预览格回到跟随态，别卡在旧目标价上
    };
    const onSkuTierFromInput = (i, v) => patchSkuTier(i, { from: sanitizeInt(v) });
    const onSkuTierPriceInput = (i, v) => patchSkuTier(i, { price: sanitizeDecimal(v) });
    const onSkuTierFromBlur = (i) => {
      patchSkuTier(i, { from: parseInt(skuForm.value.price_tiers[i]?.from, 10) || 0 });
    };
    const onSkuTierPriceBlur = (i) => {
      patchSkuTier(i, { price: round2(skuForm.value.price_tiers[i]?.price) });
    };
    // 常用租期速览：跟着分段实时重算，方便对着目标价调单价
    const skuRentPreview = computed(() => {
      const tiers = (skuForm.value && skuForm.value.price_tiers) || [];
      return PREVIEW_DAYS.map((d) => {
        const total = calcAmount(d, tiers);
        return { days: d, total, totalText: money(total), perDay: money(total / d) };
      });
    });

    // ---- 反推：改预览里的总价，倒解分段 ----
    // rentTargets = null 表示「跟随分段」（正向），一旦用户动了任一格就切成数组，
    // 存用户敲的原文（sanitizeDecimal 后的半成品串也要留住，理由同 tier 输入框）。
    const rentTargets = ref(null);
    const rentSolveNote = ref(null);   // 反推后目标价与实际算出来的零头差
    const rentDirty = computed(() => rentTargets.value !== null);

    const rentCells = computed(() => skuRentPreview.value.map((r, i) => {
      const raw = rentDirty.value ? rentTargets.value[i] : r.totalText;
      const num = _pyFloat(raw);
      return {
        days: r.days,
        raw,
        // 折合单价跟着输入框走，边改边看每天多少钱
        perDay: num === null ? '—' : money(num / r.days),
        changed: rentDirty.value && _pyFloat(raw) !== r.total,
      };
    }));

    const rentSolveError = computed(() => (
      rentDirty.value ? validateRentTargets(rentTargets.value) : ''
    ));

    const onRentTargetInput = (i, v) => {
      const arr = rentDirty.value
        ? rentTargets.value.slice()
        : skuRentPreview.value.map(r => r.totalText);
      arr[i] = sanitizeDecimal(v);
      rentTargets.value = arr;
      rentSolveNote.value = null;
    };
    const resetRentTargets = () => {
      rentTargets.value = null;
      rentSolveNote.value = null;
    };

    const applyRentTargets = () => {
      if (!rentDirty.value || rentSolveError.value) return;
      const targets = PREVIEW_DAYS.map((d, i) => ({
        days: d,
        total: _pyFloat(rentTargets.value[i]),
      }));
      // 相邻档位单价撞在一起时会解出 {1,10} {4,10} 这种冗余段（后端 normalize
      // 反正也会折叠）。写回前先折一次，表格里看到的就是最终存下去的样子。
      const tiers = normalizeTiers(solveTiersFromTotals(targets));
      skuForm.value.price_tiers = tiers;
      skuTierError.value = validateTiers(tiers);
      // 单价 round 到分之后总价会差几个零头（最坏 0.005×段天数）。
      // 用同一套 calcAmount 重算真实值摊开给人看，别假装精确命中了。
      rentSolveNote.value = targets
        .map((t) => {
          const actual = calcAmount(t.days, tiers);
          return { days: t.days, actual: money(actual), diff: round2(actual - t.total) };
        })
        .filter(x => x.diff !== 0);
      rentTargets.value = null;
    };

    // 软提示：租越久单价越贵一般是配错了，但不阻断——真要这么定价也随他
    const skuTierRising = computed(() => {
      const segs = (skuForm.value && skuForm.value.price_tiers) || [];
      for (let i = 1; i < segs.length; i++) {
        const a = _pyFloat(segs[i - 1].price);
        const b = _pyFloat(segs[i].price);
        if (a !== null && b !== null && b > a) {
          return `第 ${i + 1} 段 ¥${money(b)}/天 比上一段 ¥${money(a)}/天 还贵，租越久越贵，确认？`;
        }
      }
      return '';
    });

    const addSkuTier = () => {
      const tiers = (skuForm.value.price_tiers || []).slice();
      const last = tiers[tiers.length - 1] || { from: 0, price: 0 };
      tiers.push({ from: (Number(last.from) || 0) + 1, price: Number(last.price) || 0 });
      skuForm.value.price_tiers = tiers;
      skuTierError.value = validateTiers(tiers);
      resetRentTargets();
    };
    const removeSkuTier = (i) => {
      if (i === 0) return;
      const tiers = (skuForm.value.price_tiers || []).slice();
      tiers.splice(i, 1);
      skuForm.value.price_tiers = tiers;
      skuTierError.value = validateTiers(tiers);
      resetRentTargets();
    };

    const saveSku = async () => {
      const f = skuForm.value;
      if (!f.name?.trim()) { alert('SKU 名称必填'); return; }
      if (!(Number(f.deposit_amount) > 0)) { alert('押金必填且必须大于 0'); return; }
      const err = validateTiers(f.price_tiers);
      if (err) { skuTierError.value = err; alert('价格分段配置无效：' + err); return; }
      skuSaving.value = true;
      try {
        const body = {
          name: f.name.trim(),
          cover_url: f.cover_url || '',
          stock: parseInt(f.stock, 10) || 0,
          sales: parseInt(f.sales, 10) || 0,
          deposit_amount: Number(f.deposit_amount),
          price_tiers: numericTiers(f.price_tiers),
          status: f.status,
        };
        if (f.id) await api.updateSku(f.id, body);
        else await api.createSku(skuProduct.value.id, body);
        skuForm.value = null;
        await loadSkus(skuProduct.value.id);
      } catch (e) { alert(e.message); }
      finally { skuSaving.value = false; }
    };

    const removeSku = async (s) => {
      if (!confirm(`确认删除 SKU「${s.name}」？`)) return;
      try {
        await api.removeSku(s.id);
        if (skuForm.value && skuForm.value.id === s.id) skuForm.value = null;
        await loadSkus(skuProduct.value.id);
      } catch (e) { alert(e.message); }
    };

    const save = async () => {
      if (!form.value.name?.trim()) { alert('商品名必填'); return; }
      const ownedBySku = formSkuCount.value > 0;
      const body = { ...form.value };
      if (ownedBySku) {
        // 已有 SKU 的商品：这四项的真相在 SKU 层，编辑时既不校验也不回传，
        // 免得商品层留一份会误导人的旧值。
        // 新建（克隆）走 else-if 不到的分支：此时还没有商品记录，服务端仍要求
        // 带上这几项作为种子值，原样提交即可（后面 default_sku=0 不会真去建标准版）。
        if (body.id) {
          delete body.price_tiers;
          delete body.deposit_amount;
          delete body.stock;
          delete body.sales;
        }
      } else {
        const deposit = Number(body.deposit_amount);
        if (!Number.isFinite(deposit) || deposit <= 0) {
          alert('押金必填且必须大于 0');
          return;
        }
        const err = validateTiers(body.price_tiers);
        if (err) { tierError.value = err; alert('价格分段配置无效：' + err); return; }
      }
      if (Array.isArray(body.price_tiers)) body.price_tiers = numericTiers(body.price_tiers);
      saving.value = true;
      try {
        if (body.id) {
          await api.update('products', body.id, body);
        } else {
          // 克隆：来源商品的 SKU 会被逐个复制过来，别让后端再建一个空壳「标准版」
          const cloningSkus = !!(cloneSrc.value && cloneSrc.value.sku_count);
          const created = await api.create(
            'products', body, cloningSkus ? { default_sku: 0 } : undefined,
          );
          if (cloningSkus && created && created.id) {
            await cloneSkusTo(cloneSrc.value.id, created.id);
          }
        }
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    // 商品弹窗里点「管理 SKU」：关掉商品弹窗，直接打开 SKU 管理
    const openSkusFromForm = () => {
      const p = list.value.find(x => x.id === form.value.id);
      if (!p) return;
      modal.value = null;
      openSkus(p);
    };

    // 逐个复制 SKU：后端没有批量接口，这里串行调用，单个失败不影响其余，最后汇总报错
    const cloneSkusTo = async (srcPid, newPid) => {
      let src = [];
      try {
        src = (await api.listSkus(srcPid)).list || [];
      } catch (e) {
        alert('SKU 复制失败（商品已创建，可手动补）：' + (e.message || ''));
        return;
      }
      const failed = [];
      for (const s of src) {
        try {
          await api.createSku(newPid, {
            name: s.name,
            cover_url: s.cover_url || '',
            stock: Number(s.stock) || 0,
            sales: 0,                       // 销量不跟着克隆
            deposit_amount: Number(s.deposit_amount) || 0,
            price_tiers: s.price_tiers,
            status: s.status || 'on',
          });
        } catch (e) {
          failed.push(`${s.name}：${e.message || '失败'}`);
        }
      }
      if (failed.length) {
        alert(`以下 SKU 复制失败，请手动补：\n${failed.join('\n')}`);
      }
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
      openNew, openEdit, openClone, cloneSrc, save, remove,
      tierError, onTierFromInput, onTierPriceInput, addTier, removeTier,
      onTierFromBlur, onTierPriceBlur,
      skuModal, skuProduct, skuList, skuForm, skuLoading, skuSaving,
      skuTierError, skuCoverUploading,
      skuDragFrom, skuDragOver, skuOrderDirty, skuOrderSaving,
      onSkuDragStart, onSkuDrop, onSkuDragEnd, moveSku, saveSkuOrder, loadSkus,
      openSkus, closeSkus, newSku, editSku, saveSku, removeSku, onSkuCoverPick,
      openSkusFromForm, formSkuCount, DEFAULT_SKU_NAME, depositText,
      onSkuTierFromInput, onSkuTierPriceInput, addSkuTier, removeSkuTier,
      onSkuTierFromBlur, onSkuTierPriceBlur, skuRentPreview, skuTierRising,
      PREVIEW_FROMS, rentCells, rentDirty, rentSolveError, rentSolveNote,
      onRentTargetInput, resetRentTargets, applyRentTargets,
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

/* 商品弹窗里「价格已下沉到 SKU」的提示块 */
.sku-owned {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid #cfe0ff;
  border-radius: 8px;
  background: #f5f9ff;
}
.sku-owned-h { font-size: 13px; font-weight: 600; color: #2f5d9e; margin-bottom: 4px; }
.sku-owned-b { font-size: 12px; line-height: 1.7; color: #4a5060; margin-bottom: 10px; }
.sku-owned-new {
  border-color: #ffe3a3;
  background: #fff8e6;
  font-size: 12px;
  line-height: 1.7;
  color: #8a5a00;
}

/* SKU 管理弹窗 */
.sku-tip {
  margin-bottom: 12px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.7;
  color: #2f5d9e;
  background: #eef4ff;
  border: 1px solid #cfe0ff;
  border-radius: 6px;
}
.sku-table td { vertical-align: middle; }

/* ---- SKU 拖拽排序 ---- */
.sku-order-tip {
  display: flex; align-items: center; gap: 10px;
  margin: 8px 0 10px;
  font-size: 12px; color: var(--muted, #888);
}
.sku-order-actions { display: flex; gap: 6px; margin-left: auto; }
.drag-cell { cursor: grab; text-align: center; user-select: none; }
.drag-cell:active { cursor: grabbing; }
.drag-dots { color: #b9c0cc; font-size: 15px; letter-spacing: 1px; }
.sku-table tr[draggable="true"] { transition: background .12s, opacity .12s; }
.sku-row-dragging > td { opacity: .45; }
/* 落点提示：拖到哪一行，哪一行顶部画条主色线 */
.sku-row-over > td { box-shadow: inset 0 2px 0 0 var(--primary, #2b7cff); }
.btn-move {
  border: 1px solid var(--line, #e5e7eb);
  background: #fff;
  border-radius: 4px;
  width: 22px; height: 20px;
  line-height: 1;
  font-size: 9px; color: #6b7280;
  cursor: pointer;
  padding: 0;
}
.btn-move + .btn-move { margin-left: 2px; }
.btn-move:disabled { opacity: .35; cursor: not-allowed; }
.btn-move:not(:disabled):hover { border-color: var(--primary, #2b7cff); color: var(--primary, #2b7cff); }
.sku-table .swatch { margin-right: 8px; vertical-align: middle; }
.sku-row-on > td { background: #f2f7ff; }
.stock-zero { color: #e0483a; font-weight: 600; }
.stock-bysku { cursor: pointer; font-size: 12px; }
.stock-bysku:hover { color: #2b7cff; }
.sku-edit {
  margin-top: 14px;
  padding: 14px;
  border: 1px solid var(--line, #e5e8ee);
  border-radius: 8px;
  background: #fafbfd;
}
.sku-edit-h {
  font-size: 14px; font-weight: 600;
  margin-bottom: 10px;
}
.sku-edit-f {
  display: flex; justify-content: flex-end; gap: 8px;
  margin-top: 12px;
}

/* 克隆弹窗顶部提示条 */
.clone-tip {
  margin-bottom: 12px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.7;
  color: #8a5a00;
  background: #fff8e6;
  border: 1px solid #ffe3a3;
  border-radius: 6px;
}

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

/* ---------- 常用租期速览 ---------- */
.rent-preview {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--line, #e5e8ee);
}
.rent-preview-h {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 8px;
}
.rent-preview-h .muted { font-size: 12px; }
.rent-preview-list {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
}
.rent-cell {
  background: #fff;
  border: 1px solid var(--line, #e5e8ee);
  border-radius: 6px;
  padding: 8px 10px;
  text-align: center;
}
.rent-days { font-size: 12px; color: #6b7280; }
/* 总价格是输入框，但平时要长得像纯文本，别让一排框子抢了视线 */
.rent-total-in {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 1px;
  margin: 2px 0 1px;
}
.rent-cny { font-size: 13px; font-weight: 600; color: #1a1f2e; }
.rent-input {
  width: 100%;
  min-width: 0;
  border: 0;
  background: transparent;
  padding: 0;
  font: inherit;
  font-size: 17px;
  font-weight: 600;
  color: #1a1f2e;
  text-align: left;
  outline: none;
  border-bottom: 1px dashed transparent;
}
.rent-input:hover { border-bottom-color: #cbd3de; }
.rent-input:focus { border-bottom-color: #2b7cff; }
.rent-cell-changed { border-color: #2b7cff; background: #f5f9ff; }
.rent-unit { font-size: 11px; color: #9aa4b2; }
/* 分段填了一半时，后端会丢弃不完整的段，试算结果可能跳变 —— 弱化并标注 */
.rent-preview-stale .rent-preview-list { opacity: 0.5; }
.rent-warn { margin-left: 8px; color: #ff8a00; }
.rent-solve-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 12px;
}
.rent-solve-bar .tier-error { margin-left: 0; }
.rent-solve-note {
  margin-top: 8px;
  font-size: 12px;
  color: #8a6d3b;
  background: #fff8e6;
  border: 1px solid #ffe2a8;
  border-radius: 6px;
  padding: 6px 10px;
}
.rent-solve-note b { font-weight: 600; margin-right: 10px; }
@media (max-width: 640px) {
  .rent-preview-list { grid-template-columns: repeat(3, 1fr); }
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
