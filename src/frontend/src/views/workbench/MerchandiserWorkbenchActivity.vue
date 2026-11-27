<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Calendar, OfficeBuilding, Wallet } from '@element-plus/icons-vue'
import { getMerchandiserActivity } from '@/api/merchandiserWorkbench'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { MerchandiserActivity, MerchandiserAmount, MerchandiserPeriod, MerchandiserSelection, MerchandiserSupplier } from '@/types/merchandiserWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import clipboard from '@/assets/purchase-workbench/unstarted.png'
import calendarBox from '@/assets/purchase-workbench/due-today.png'

const emit = defineEmits<{ select: [selection: MerchandiserSelection] }>()
const periods: { key: MerchandiserPeriod; label: string }[] = [
  { key: 'month', label: '本月' }, { key: 'quarter', label: '本季' }, { key: 'year', label: '本年' },
]
const period = ref<MerchandiserPeriod>('month')
const report = ref<MerchandiserActivity | null>(null), error = ref(''), retry = ref(0)
const directoryOpen = ref(false), expanded = ref(false), currency = ref('CNY')
watch([period, retry], async ([key], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  error.value = ''
  report.value = null
  directoryOpen.value = false
  expanded.value = false
  try {
    const data = await getMerchandiserActivity(key, request.signal)
    if (!request.signal.aborted) {
      report.value = data
      if (!data.amounts.some(total => total.currency === currency.value)) currency.value = data.amounts[0]?.currency ?? 'CNY'
    }
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载跟单汇总')
  }
}, { immediate: true })

const periodTitle = computed(() => periods.find(p => p.key === period.value)!.label)
const shortDate = (day: string) => day.slice(5).replace('-', '/')
const range = computed(() => report.value && [report.value.start_date, report.value.as_of].map(shortDate).join(' — '))
const money = (value: MerchandiserAmount) => {
  const [whole, decimal] = value.amount.split('.')
  const fraction = decimal?.replace(/0+$/, '')
  const number = whole!.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction ? '.' + fraction : '')
  return value.currency === 'CNY' ? '¥' + number : number + ' ' + (value.currency || '币种待核对')
}
const ranked = computed(() => (report.value?.suppliers ?? []).map(supplier => ({
  supplier, amount: supplier.amounts.find(a => a.currency === currency.value),
})).filter(row => row.amount || !row.supplier.amounts.length)
  .sort((a, b) => Number(b.amount?.amount ?? -1) - Number(a.amount?.amount ?? -1)))
const visible = computed(() => expanded.value ? ranked.value : ranked.value.slice(0, 5))
const total = computed(() => report.value?.amounts.find(a => a.currency === currency.value))
const largest = computed(() => Number(ranked.value[0]?.amount?.amount ?? 0))
function openSupplier(supplier: MerchandiserSupplier) {
  directoryOpen.value = false
  emit('select', { category: 'supplier', title: supplier.name + ' · ' + periodTitle.value + '已确认包材采购', period: period.value, supplier_id: supplier.id, unit: '行' })
}
</script>

<template>
  <section class="activity">
    <header class="section-head"><h2><Calendar />跟单汇总</h2>
      <div class="period-toggle" role="group" aria-label="跟单汇总周期">
        <button v-for="p in periods" :key="p.key" type="button" :aria-pressed="p.key === period" @click="period = p.key">{{ p.label }}</button>
      </div>
    </header>
    <p v-if="error" role="alert" class="glass load-state">{{ error }} <ElButton @click="retry++">重新加载</ElButton></p>
    <p v-else-if="!report" role="status" class="glass load-state">正在加载跟单汇总…</p>
    <div v-else class="metrics">
      <button class="metric glass" type="button" @click="emit('select', { category: 'period_tasks', period, title: periodTitle + '交期任务', unit: '张任务' })">
        <span class="task-art"><img :src="clipboard" alt=""><img :src="calendarBox" alt=""></span>
        <h3><Calendar />{{ periodTitle }}交期任务</h3><strong class="metric-value">{{ report.task_count }}<small>张</small></strong>
        <span class="metric-note"><span>{{ periodTitle }}到期</span><span>含已完成任务</span></span>
      </button>
      <button class="metric glass" type="button" :disabled="report.purchase_order_count === null" @click="emit('select', { category: 'period_purchases', period, title: periodTitle + '已确认包材采购', unit: '行' })">
        <small class="range">{{ range }}</small><Wallet class="metric-icon" />
        <h3><Wallet />已确认包材采购额</h3>
        <span v-if="report.amounts.length" class="quantities" :class="{ multiple: report.amounts.length > 1 }">
          <strong v-for="amount in report.amounts" :key="amount.currency" class="metric-value">{{ money(amount) }}</strong>
        </span>
        <strong v-else class="metric-value">{{ report.purchase_order_count === null ? '—' : report.unpriced_count ? '待计价' : '0' }}</strong>
        <span class="metric-note"><span>{{ report.purchase_order_count === null ? '无查看权限' : report.purchase_order_count + ' 张采购单' }}</span><span>按确认日期</span></span>
        <small v-if="report.unpriced_count || report.undated_count" class="missing">
          <span v-if="report.unpriced_count">{{ report.unpriced_count }} 行待计价</span>
          <span v-if="report.undated_count">{{ report.undated_count }} 行缺确认日期，未归入周期</span>
        </small>
      </button>
      <button class="metric glass" type="button" :disabled="report.supplier_count === null" @click="directoryOpen = true">
        <small class="range">{{ range }}</small><OfficeBuilding class="metric-icon" />
        <h3><OfficeBuilding />活跃包材供应商</h3><strong class="metric-value">{{ report.supplier_count ?? '—' }}<small v-if="report.supplier_count !== null">家</small></strong>
        <span class="metric-note"><span>{{ report.supplier_count === null ? '无查看权限' : '有已确认采购记录' }}</span><span>按供应商去重</span></span>
      </button>
    </div>
  </section>
  <div class="lower">
    <slot name="calendar" />
    <section class="glass panel factory-panel">
      <header class="panel-head"><h2><OfficeBuilding />包材供应商采购汇总</h2><small>{{ range }}</small></header>
      <div class="rank-subtitle"><p class="subtitle">按已确认包材采购金额排序</p>
        <select v-if="report && report.amounts.length > 1" v-model="currency" aria-label="供应商排名币种">
          <option v-for="a in report.amounts" :key="a.currency" :value="a.currency">{{ a.currency || '币种待核对' }}</option>
        </select>
      </div>
      <div v-if="ranked.length" class="ranks">
        <button v-for="{ supplier, amount } in visible" :key="supplier.id" type="button" class="rank" @click="openSupplier(supplier)">
          <span class="rank-head"><strong>{{ supplier.name || '供应商名称待核对' }}<small>{{ supplier.order_count }} 张采购单<span v-if="supplier.unpriced_count"> · {{ supplier.unpriced_count }} 行待计价</span></small></strong><b>{{ amount ? money(amount) : '待计价' }}</b></span>
          <span class="track"><i :style="{ width: (largest && amount ? Number(amount.amount) * 100 / largest : 0) + '%' }" /></span>
        </button>
      </div>
      <p v-else class="empty">{{ error ? '汇总加载失败' : !report ? '正在加载…' : report.supplier_count === null ? '无查看权限' : '本期暂无包材供应商采购记录' }}</p>
      <footer v-if="report && ranked.length" class="totals">
        <button v-if="ranked.length > 5" type="button" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起' : '查看其余 ' + (ranked.length - 5) + ' 家' }}</button>
        <span v-else>{{ report.unknown_supplier_count ? '已关联供应商' : report.unpriced_count ? '已计价合计' : '合计' }}</span>
        <b>{{ ranked.length }} 家<template v-if="!report.unknown_supplier_count"> · {{ total ? money(total) : '待计价' }}</template></b>
      </footer>
      <p v-if="report?.unknown_supplier_count" class="subtitle">{{ report.unknown_supplier_count }} 行采购未关联供应商，未计入排名</p>
    </section>
    <slot name="rail" />
  </div>
  <AppWindowDialog v-if="directoryOpen && report" :model-value="true" :title="periodTitle + '活跃包材供应商'" :width="680" :min-width="300" :minimizable="false" @update:model-value="directoryOpen = $event">
    <p v-if="!report.suppliers.length">本期暂无包材供应商采购记录。</p>
    <ul v-else class="directory">
      <li v-for="supplier in report.suppliers" :key="supplier.id">
        <button type="button" @click="openSupplier(supplier)"><strong>{{ supplier.name }}</strong><span>{{ supplier.order_count }} 张采购单</span><b>{{ supplier.amounts.map(money).join(' / ') || '待计价' }}</b></button>
      </li>
    </ul>
  </AppWindowDialog>
</template>

<style scoped>
.metric { color: inherit; font: inherit; text-align: left; cursor: pointer; }
.metric:disabled { cursor: default; }
.metric:not(:disabled):hover, .rank:hover { border-color: var(--erp-color-border); }
.task-art { position: absolute; right: 20px; top: 50%; width: 26%; height: 76%; max-width: 160px; transform: translateY(-50%); }
.task-art img { position: absolute; width: 67%; height: 85%; object-fit: contain; }
.task-art img:first-child { left: 0; top: 0; transform: rotate(-8deg); }
.task-art img:last-child { right: 0; bottom: 0; }
.rank-subtitle, .missing { display: flex; align-items: baseline; flex-wrap: wrap; gap: 10px; }
.missing { margin-top: 7px; }
.rank, .directory button { border: 0; background: transparent; padding: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.track { display: block; }
.rank-subtitle select { background: var(--erp-input-surface); color: inherit; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); }
.directory { list-style: none; max-height: 60vh; overflow: auto; padding: 0; margin: 0; }
.directory button { display: flex; flex-wrap: wrap; align-items: center; width: 100%; gap: 10px; padding: 12px 2px; border-bottom: 1px solid var(--erp-color-border-subtle); }
.directory strong { color: var(--erp-menu-accent); }
.directory b { margin-left: auto; }
</style>
