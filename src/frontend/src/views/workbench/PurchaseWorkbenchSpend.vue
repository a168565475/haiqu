<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Calendar, DataAnalysis, DataLine, InfoFilled, OfficeBuilding, Wallet } from '@element-plus/icons-vue'
import { getPurchaseWorkbenchSpend } from '@/api/purchaseWorkbench'
import type { PurchaseWorkbenchSpend, SpendPeriod } from '@/types/purchaseWorkbench'
import fabric from '@/assets/purchase-workbench/fabric.png'
import PurchaseSpendTrend from './PurchaseSpendTrend.vue'

const props = defineProps<{ asOf: string }>()
const periods = [
  { key: 'month', name: '本月', short: '本月' }, { key: 'quarter', name: '本季度', short: '本季' },
  { key: 'year', name: '本年度', short: '本年' },
] as const
const reports = ref<Partial<Record<SpendPeriod, PurchaseWorkbenchSpend>>>({})
const failed = ref<SpendPeriod[]>([])
const attempt = ref(0)
const active = ref<SpendPeriod>('month')
const expanded = ref(false)
const selectedCurrency = ref('CNY')
watch([() => props.asOf, attempt], ([date], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  reports.value = {}
  failed.value = []
  for (const period of periods) {
    getPurchaseWorkbenchSpend(period.key, date, request.signal).then(data => {
      if (!request.signal.aborted) reports.value[period.key] = data
    }).catch(() => { if (!request.signal.aborted) failed.value.push(period.key) })
  }
}, { immediate: true })
const currencies = computed(() => [...new Set(Object.values(reports.value).flatMap(r => r.currencies.map(c => c.currency)))].sort())
const currency = computed(() => currencies.value.includes(selectedCurrency.value) || !currencies.value.length
  ? selectedCurrency.value : currencies.value[0]!)
const values = computed(() => Object.fromEntries(Object.entries(reports.value).map(([key, report]) =>
  [key, report.currencies.find(c => c.currency === currency.value)])) as Record<SpendPeriod, PurchaseWorkbenchSpend['currencies'][number] | undefined>)
const divisor = computed(() => Math.max(...Object.values(values.value).map(v => Number(v?.amount || 0))) >= 10_000 ? 10_000 : 1)
const currencyLabel = computed(() => currency.value === 'CNY' ? '人民币' : currency.value || '币种待核对')
const unit = computed(() => (divisor.value === 10_000 ? '万' : '') + (currency.value === 'CNY' ? '元' : currencyLabel.value))
const formatMoney = (value: string | number) => (Number(value) / divisor.value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const current = computed(() => values.value[active.value])
const suppliers = computed(() => current.value?.suppliers ?? [])
const visibleSuppliers = computed(() => expanded.value ? suppliers.value : suppliers.value.slice(0, 5))
const others = computed(() => suppliers.value.slice(5).reduce((a, s) => a + Number(s.amount), 0))
const dateRange = (report?: PurchaseWorkbenchSpend) => report ? [report.start_date, report.end_date].map(d => d.slice(5).replace('-', '/')).join(' — ') : ''
const stateLabel = (key: SpendPeriod) => failed.value.includes(key) ? '加载失败' : !reports.value[key] ? '加载中…' : ''
function amountStatus(key: SpendPeriod) {
  const group = values.value[key]
  if (!group?.line_count && reports.value[key]?.unknown_date_count) return '暂无可归期金额'
  if (group?.line_count && group.unpriced_count === group.line_count) return '本期采购尚未计价'
  return ''
}
watch([active, currency], () => { expanded.value = false })
</script>

<template>
  <section class="spend-overview">
    <header class="sectionhead"><h2><Wallet />我的采购汇总</h2><span class="money-rule"><InfoFilled />本岗可见普通采购 · 按采购确认日统计已计价金额（{{ currencyLabel }}）
      <select v-if="currencies.length > 1" :value="currency" aria-label="采购汇总币种" @change="selectedCurrency = ($event.target as HTMLSelectElement).value"><option v-for="c in currencies" :key="c" :value="c">{{ c || '待核对' }}</option></select>
    </span></header>
    <div class="periods">
      <article v-for="p in periods" :key="p.key" :class="['period', p.key]">
        <img v-if="p.key === 'month'" class="fabric" :src="fabric" alt="">
        <template v-else><span class="range">{{ dateRange(reports[p.key]) }}</span><span class="periodicon"><component :is="p.key === 'quarter' ? Calendar : DataAnalysis" /></span></template>
        <div class="periodbody"><h3><Calendar />{{ p.name }}采购额</h3>
          <strong class="periodmoney" :title="!amountStatus(p.key) && values[p.key] ? values[p.key]!.amount + ' ' + currency : undefined">{{ reports[p.key] && !amountStatus(p.key) ? formatMoney(values[p.key]?.amount ?? 0) : '—' }}<small>{{ unit }}</small></strong>
          <div v-if="amountStatus(p.key)" class="periodbottom">{{ amountStatus(p.key) }}</div>
          <div v-else-if="reports[p.key]" class="periodbottom"><span>{{ values[p.key]?.supplier_count ?? 0 }} 家供应商</span><i /><span>{{ values[p.key]?.order_count ?? 0 }} 个采购批次</span></div>
          <span v-else class="periodbottom">{{ stateLabel(p.key) }} <button v-if="failed.includes(p.key)" @click="attempt++">重试</button></span>
          <small v-if="values[p.key]?.unpriced_count" class="warning">{{ values[p.key]!.unpriced_count }} 项未计价</small>
        </div>
      </article>
    </div>
    <small v-if="reports.year?.unknown_date_count" class="warning">{{ reports.year.unknown_date_count }} 项采购明细确认日期待核对，未计入期间汇总</small>
  </section>
  <div class="lower">
    <section class="glass panel">
      <header class="panelhead"><h2><OfficeBuilding />供应商采购额</h2>
        <div class="period-toggle" role="group" aria-label="供应商统计周期"><button v-for="p in periods" :key="p.key" type="button" :aria-pressed="active === p.key" @click="active = p.key">{{ p.short }}</button></div>
      </header>
      <p v-if="reports[active]" class="subtitle">{{ dateRange(reports[active]) }}<template v-if="!amountStatus(active)"> · {{ current?.supplier_count ?? 0 }} 家供应商<span v-if="suppliers.length"> · {{ expanded ? '按金额从高到低' : '金额前五家' }}</span></template></p>
      <div v-if="suppliers.length" class="ranks">
        <div v-for="supplier in visibleSuppliers" :key="supplier.supplier_id ?? supplier.supplier_name" class="rank">
          <div class="rankline"><strong>{{ supplier.supplier_name || '供应商待核对' }}<small>{{ supplier.supplier_category }}</small></strong><b>{{ supplier.unpriced_count === supplier.line_count ? '待计价' : formatMoney(supplier.amount) + ' ' + unit }}</b></div>
          <div class="bar"><i :style="{ width: (Number(suppliers[0]?.amount) > 0 ? Math.min(100, Number(supplier.amount) / Number(suppliers[0]!.amount) * 100) : 0) + '%' }" /></div>
        </div>
      </div>
      <p v-else class="empty">{{ stateLabel(active) || amountStatus(active) || '本期暂无供应商采购记录' }}</p>
      <footer v-if="reports[active] && (!amountStatus(active) || suppliers.length > 5)" class="rankfoot">
        <button v-if="suppliers.length > 5" :aria-expanded="expanded" @click="expanded = !expanded"><template v-if="expanded">收起至前五家</template><template v-else>查看其余 {{ suppliers.length - 5 }} 家<span v-if="suppliers.slice(5).some(s => s.unpriced_count < s.line_count)"> · {{ formatMoney(others) }} {{ unit }}</span> ›</template></button>
        <b v-if="!amountStatus(active)">{{ (current?.unpriced_count || reports[active]?.unknown_date_count) ? '已统计' : '全部合计' }} {{ formatMoney(current?.amount ?? 0) }} {{ unit }}</b>
      </footer>
    </section>
    <section class="glass panel"><header class="panelhead"><h2><DataLine />本年采购走势</h2><small>{{ asOf.slice(0, 4) }} 年</small></header>
      <p class="subtitle">每月已确认的采购金额</p>
      <PurchaseSpendTrend v-if="values.year && !amountStatus('year')" :trend="values.year.trend" :as-of="asOf" :divisor="divisor" :unit="unit" />
      <p v-else class="empty">{{ stateLabel('year') || amountStatus('year') || '本年暂无采购记录' }}</p>
    </section>
    <aside class="rail"><slot /></aside>
  </div>
</template>

<style scoped>
.sectionhead,.panelhead,.rankline,.rankfoot { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.sectionhead { margin-bottom:9px; flex-wrap:wrap; }
.money-rule,.periodbody h3 { display:flex; align-items:center; gap:6px; }
.money-rule,.subtitle,.panelhead small,.rankline small,.empty,.warning { font-size:12px; color:var(--erp-color-text-secondary); }
.money-rule svg { width:14px; }.money-rule select { background:var(--erp-input-surface); border:1px solid var(--erp-color-border); border-radius:var(--erp-radius-control); color:inherit; font:inherit; }
.periods { display:grid; grid-template-columns:1.17fr 1fr 1fr; gap:14px; }
.period { position:relative; overflow:hidden; min-height:157px; padding:18px 23px; border:1px solid var(--erp-glass-border); border-radius:14px; background:var(--erp-glass-surface); box-shadow:var(--erp-glass-shadow); }
.month .periodmoney { color:var(--erp-menu-accent); }
.periodbody { position:relative; }.periodbody h3 { margin:0; font-size:15px; font-weight:600; }.periodbody h3 svg { width:18px; height:18px; }
.periodmoney { display:block; margin-top:8px; font:600 clamp(28px,2.8vw,40px)/1.17 "Segoe UI",sans-serif; letter-spacing:-.03em; }
.periodmoney small { margin-left:8px; font:400 13px var(--erp-font-body); letter-spacing:0; }
.periodbottom { display:flex; gap:14px; align-items:center; margin-top:13px; font-size:13px; color:var(--erp-color-text-secondary); }.periodbottom i { height:13px; border-left:1px solid currentColor; opacity:.45; }
.warning { display:block; margin-top:6px; }
.range { position:absolute; right:20px; top:18px; color:var(--erp-color-text-secondary); font-size:12px; }
.periodicon { position:absolute; right:20px; bottom:20px; width:44px; height:44px; border-radius:11px; display:grid; place-items:center; background:#e1edf5; color:#4f7c98; }.year .periodicon { background:#dff0ed; color:#418776; }.periodicon svg { width:24px; }
.fabric { position:absolute; right:10px; top:50%; transform:translateY(-50%); width:36%; max-height:95%; object-fit:contain; }
.lower { display:grid; grid-template-columns:minmax(0,1.04fr) minmax(0,1.09fr) minmax(220px,.73fr); gap:14px; align-items:stretch; }.panel { padding:20px 23px; min-width:0; }
.period-toggle { display:flex; flex-wrap:wrap; gap:6px; }
.period-toggle button { min-height:30px; border:1px solid transparent; background:transparent; border-radius:var(--erp-radius-control); padding:0 9px; color:var(--erp-color-text-secondary); font:inherit; font-size:12px; cursor:pointer; }
.period-toggle button:hover { background:var(--erp-menu-hover-background); }
.period-toggle button[aria-pressed=true] { background:var(--erp-menu-selected-background); color:var(--erp-menu-accent); font-weight:600; }
.subtitle { margin:6px 0 0; }.ranks { display:grid; gap:14px; margin-top:18px; }.rankline { align-items:baseline; }.rankline strong,.rankline b { font-size:14px; font-weight:600; overflow-wrap:anywhere; }.rankline b { white-space:nowrap; }.rankline small { margin-left:4px; font-weight:400; }
.bar { height:6px; background:var(--erp-color-subtle); border-radius:6px; margin-top:6px; overflow:hidden; }.bar i { display:block; background:#64a7b2; height:100%; border-radius:inherit; }.rank:first-child .bar i { background:#216c80; }
.rankfoot { border-top:1px solid var(--erp-color-border-subtle); margin-top:15px; padding-top:11px; flex-wrap:wrap; font-size:12px; }.rankfoot b { margin-left:auto; }.rankfoot button,.periodbottom button { color:var(--erp-color-brand); padding:0; background:none; border:0; cursor:pointer; font:inherit; }
.empty { margin:28px 0; }.rail { display:grid; gap:12px; align-content:start; min-width:0; }
@media (min-width:1700px) { .period { min-height:171px; padding:21px 25px; }.panel { padding:22px 25px; }.ranks { gap:17px; } }
@media (max-width:1350px) { .lower { grid-template-columns:minmax(0,1fr) minmax(0,1.05fr); }.rail { grid-column:1/-1; grid-template-columns:repeat(2,minmax(0,1fr)); }.range { display:none; } }
@media (max-width:930px) { .panel,.period { padding:14px; }.periodicon { display:none; }.panelhead { flex-wrap:wrap; }.periodbottom { gap:7px; } }
@media (max-width:680px) { .lower,.rail { grid-template-columns:1fr; }.periods { grid-template-columns:1fr 1fr; gap:8px; }.period.month { grid-column:1/-1; }.period { min-height:115px; }.periodbottom { font-size:11px; } }
</style>
