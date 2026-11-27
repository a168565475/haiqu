<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Box, Calendar, Checked, OfficeBuilding, Van } from '@element-plus/icons-vue'
import { getSewingActivity } from '@/api/sewingOutsourcingWorkbench'
import type { SewingPeriod, SewingWorkbenchActivity } from '@/types/sewingOutsourcingWorkbench'
import type { OutsourcingQuantitySummary } from '@/types/unifiedOutsourcing'
import { workbenchErrorMessage } from '@/utils/workbench'
import sewingMachine from '@/assets/workbench-icons/sewing-machine.svg'

const periods: { key: SewingPeriod; label: string }[] = [
  { key: 'month', label: '本月' }, { key: 'quarter', label: '本季' }, { key: 'year', label: '本年' },
]
const period = ref<SewingPeriod>('month')
const report = ref<SewingWorkbenchActivity | null>(null)
const error = ref(''), retry = ref(0), expanded = ref(false)
watch([period, retry], async ([key], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  error.value = ''
  report.value = null
  expanded.value = false
  try {
    const data = await getSewingActivity(key, request.signal)
    if (!request.signal.aborted) report.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载外发与回货汇总')
  }
}, { immediate: true })

const title = computed(() => periods.find(p => p.key === period.value)!.label)
const range = computed(() => report.value && [report.value.start_date, report.value.end_date].map(d => d.slice(5).replace('-', '/')).join(' — '))
const displayQuantity = (value: string) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const quantities = (rows: OutsourcingQuantitySummary[]) => rows.map(row => `${displayQuantity(row.quantity)} ${row.unit}`).join(' / ')
const multipleUnits = computed(() => (report.value?.quantities.length ?? 0) > 1)
// 条形宽度沿用接口的排序口径，混合单位时按有回货的单数比较。
function rankValue(factory: SewingWorkbenchActivity['factories'][number]) {
  return multipleUnits.value ? factory.order_count : Number(factory.quantities[0]?.quantity ?? 0)
}
const ranks = computed(() => report.value?.factories ?? [])
const visibleRanks = computed(() => expanded.value ? ranks.value : ranks.value.slice(0, 5))
</script>

<template>
  <section class="activity" :aria-busy="!report && !error">
    <header class="section-head"><h2><Calendar />外发与回货汇总</h2>
      <div class="period-toggle" role="group" aria-label="外发与回货统计周期">
        <button v-for="p in periods" :key="p.key" type="button" :aria-pressed="period === p.key" @click="period = p.key">{{ p.label }}</button>
      </div>
    </header>
    <p v-if="error" role="alert" class="glass load-state">{{ error }} <ElButton @click="retry++">重新加载</ElButton></p>
    <p v-else-if="!report" role="status" class="glass load-state">正在加载汇总…</p>
    <div v-else class="metrics">
      <article class="metric glass"><img :src="sewingMachine" class="machine-art" alt="">
        <h3><Van />{{ title }}实际发料</h3>
        <strong class="metric-value">{{ report.dispatch_orders }}<small>张总单</small></strong>
        <p class="metric-note"><span>{{ report.dispatch_factories }} 家加工厂</span><span>按实际发料日</span></p>
      </article>
      <article class="metric glass"><small class="range">{{ range }}</small><Box class="metric-icon" />
        <h3><Box />{{ title }}有回货的外协单</h3>
        <strong class="metric-value">{{ report.receipt_orders }}<small>张总单</small></strong>
        <p class="metric-note"><span>{{ report.receipt_factories }} 家加工厂</span><span>同一总单只计一次</span></p>
      </article>
      <article class="metric glass"><small class="range">{{ range }}</small><Checked class="metric-icon" />
        <h3><Checked />{{ title }}实收车缝部位</h3>
        <div v-if="report.quantities.length" class="quantities" :class="{ multiple: multipleUnits }">
          <strong v-for="q in report.quantities" :key="q.unit" class="metric-value">{{ displayQuantity(q.quantity) }}<small>{{ q.unit }}</small></strong>
        </div>
        <strong v-else class="metric-value">{{ report.receipt_events ? '—' : '0' }}</strong>
        <p class="metric-note"><span>{{ report.receipt_events }} 次回货</span><span>按实际入库日</span></p>
      </article>
    </div>
  </section>
  <div class="lower">
    <section class="glass panel factory-panel">
      <header class="panel-head"><h2><OfficeBuilding />加工厂回货</h2><small>{{ range }}</small></header>
      <p class="subtitle">按实际回货日期统计，{{ multipleUnits ? '按有回货的总单数排序' : '按部位实收数量排序' }}</p>
      <div v-if="ranks.length" class="ranks">
        <div v-for="factory in visibleRanks" :key="factory.id" class="rank">
          <div class="rank-head"><strong>{{ factory.name }}<small>{{ factory.order_count }} 张总单</small></strong><b>{{ quantities(factory.quantities) || '数量待核对' }}</b></div>
          <div class="track"><i :style="{ width: (rankValue(ranks[0]!) > 0 ? 100 * rankValue(factory) / rankValue(ranks[0]!) : 0) + '%' }" /></div>
        </div>
      </div>
      <p v-else class="empty">{{ error ? '汇总加载失败' : report ? '本期暂无加工厂回货' : '正在加载…' }}</p>
      <footer v-if="report && ranks.length" class="totals">
        <button v-if="ranks.length > 5" type="button" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起' : '查看其余 ' + (ranks.length - 5) + ' 家' }}</button><span v-else>合计</span>
        <b>{{ report.receipt_orders }} 张总单<span v-if="report.quantities.length"> · {{ quantities(report.quantities) }}</span></b>
      </footer>
    </section>
    <slot />
  </div>
</template>
