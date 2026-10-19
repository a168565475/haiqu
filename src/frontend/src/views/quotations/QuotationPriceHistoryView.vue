<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Download, Search } from '@element-plus/icons-vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { fetchQuotationPriceHistory } from '@/api/quotations'
import type { QuotationPriceHistory } from '@/types/quotation'

const router = useRouter()
const data = ref<QuotationPriceHistory | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const errorStatus = ref<number | null>(null)
const filters = ref({ customer_account_id: '', product: '', container_type_code: '', currency_code: '', period_months: 12 })
const palette = ['var(--erp-chart-series-1)', 'var(--erp-chart-series-2)', 'var(--erp-chart-series-3)', 'var(--erp-chart-series-4)', 'var(--erp-chart-series-5)']

function readableError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '加载失败，请稍后重试。'
  if (!error.response) return '网络异常，请检查连接后重试。'
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看报价历史的权限。'
  return (error.response.data as { error?: { message?: string } }).error?.message || '报价历史服务暂时异常，请稍后重试。'
}

async function loadHistory() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchQuotationPriceHistory(filters.value)
    // 单价均值不能跨客户、产品或币种混算；首次进入时选用最新真实记录作为默认范围。
    if (!filters.value.customer_account_id && !filters.value.product && !filters.value.currency_code && result.records[0]) {
      filters.value.customer_account_id = result.records[0].customer_id
      filters.value.product = result.records[0].product
      filters.value.currency_code = result.records[0].currency_code
      filters.value.container_type_code = result.records[0].container_types[0] || ''
      data.value = await fetchQuotationPriceHistory(filters.value)
    } else data.value = result
  } catch (error) { errorStatus.value = error instanceof AxiosError ? error.response?.status || null : null; errorMessage.value = readableError(error) } finally { loading.value = false }
}
function resetFilters() { filters.value = { customer_account_id: '', product: '', container_type_code: '', currency_code: '', period_months: 12 }; void loadHistory() }
function money(value: string | null) { return value === null ? '—' : `${data.value?.records[0]?.currency_code || ''} ${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })}`.trim() }
const values = computed(() => data.value?.series.flatMap(item => item.points.map(point => Number(point.unit_price))) || [])
const chartBounds = computed(() => {
  if (!values.value.length) return { min: 0, max: 1 }
  const minValue = Math.min(...values.value)
  const maxValue = Math.max(...values.value)
  const padding = maxValue === minValue ? Math.max(Math.abs(maxValue) * 0.05, 1) : (maxValue - minValue) * 0.12
  return { min: minValue - padding, max: maxValue + padding }
})
const chartTicks = computed(() => Array.from({ length: 5 }, (_, index) => chartBounds.value.max - ((chartBounds.value.max - chartBounds.value.min) / 4) * index))
function pointX(index: number, count: number) { return 50 + index * (650 / Math.max(count - 1, 1)) }
function pointY(value: string) { const { min, max } = chartBounds.value; return 190 - ((Number(value) - min) / (max - min || 1)) * 160 }
function polyline(points: Array<{ date: string; unit_price: string }>) { return points.map((point, index) => `${pointX(index, points.length)},${pointY(point.unit_price)}`).join(' ') }
function exportTrend() { if (!data.value?.records.length) return ElMessage.info('当前筛选没有可导出的真实报价记录。'); const rows = [['日期','版本','客户','产品','档位','数量','单价','币种','贸易条款','状态'], ...data.value.records.map(item => [item.date, `V${item.version_number}`, item.customer_name, item.product, item.container_types.join('、') || '未配置', item.quantity, item.unit_price, item.currency_code, item.incoterm, item.status_label])]; const blob = new Blob([`\ufeff${rows.map(row => row.map(cell => `"${String(cell).replaceAll('"','""')}"`).join(',')).join('\n')}`], { type: 'text/csv;charset=utf-8' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'quotation-price-history.csv'; link.click(); URL.revokeObjectURL(link.href) }
const insight = computed(() => { const latest = Number(data.value?.metrics.latest_quote_price || 0); const avg = Number(data.value?.metrics.average_quote_price || 0); if (!avg) return '暂无足够的真实报价快照用于趋势判断。'; const percentage = ((latest - avg) / avg * 100).toFixed(1); return latest <= avg ? `最新报价较周期均价低 ${Math.abs(Number(percentage))}%` : `最新报价较周期均价高 ${percentage}%` })
const errorTitle = computed(() => errorStatus.value === 403 ? '历史价格无权限' : '历史价格趋势加载失败')
onMounted(() => { void loadHistory() })
</script>

<template>
  <section v-loading="loading" class="price-history-page" aria-label="历史报价趋势">
    <template v-if="data">
      <header><div><p class="crumb">报价管理 / 历史价格趋势</p><div class="heading"><h1>历史价格趋势</h1><span>追踪同一客户与产品的报价变化，辅助报价决策</span></div></div><ElButton :icon="Download" @click="exportTrend">导出趋势</ElButton></header>
      <ElCard class="filter-card" shadow="never"><div class="filters"><label>客户<ElSelect v-model="filters.customer_account_id" clearable placeholder="全部客户"><ElOption v-for="item in data.filters.customers" :key="item.value" v-bind="item" /></ElSelect></label><label>产品<ElSelect v-model="filters.product" clearable placeholder="全部产品"><ElOption v-for="item in data.filters.products" :key="item.value" v-bind="item" /></ElSelect></label><label>装柜档位<ElSelect v-model="filters.container_type_code" clearable placeholder="全部档位"><ElOption v-for="item in data.filters.container_types" :key="item.value" v-bind="item" /></ElSelect></label><label>币种<ElSelect v-model="filters.currency_code" clearable placeholder="全部币种"><ElOption v-for="item in data.filters.currencies" :key="item.value" v-bind="item" /></ElSelect></label><label>时间范围<ElSelect v-model="filters.period_months"><ElOption v-for="item in data.filters.periods" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></label><div class="filter-actions"><ElButton class="black-button" :icon="Search" @click="loadHistory">查询</ElButton><ElButton @click="resetFilters">重置</ElButton></div></div></ElCard>
      <ElAlert v-if="data.calculation_warning" class="calculation-warning" :title="data.calculation_warning" type="warning" :closable="false" show-icon />
      <div class="metric-row"><ElCard shadow="never"><small>最新报价单价</small><b>{{ money(data.metrics.latest_quote_price) }}</b><span>真实报价快照</span></ElCard><ElCard shadow="never"><small>周期最低报价单价</small><b>{{ money(data.metrics.minimum_quote_price) }}</b><span>当前筛选范围</span></ElCard><ElCard shadow="never"><small>平均报价单价</small><b>{{ money(data.metrics.average_quote_price) }}</b><span>含 {{ data.records.length }} 条报价行</span></ElCard><ElCard shadow="never"><small>价格波动</small><b>{{ data.metrics.price_volatility_percent === null ? '—' : `${data.metrics.price_volatility_percent}%` }}</b><span>最高与最低报价差</span></ElCard></div>
      <div class="main-row"><ElCard class="chart-card" shadow="never"><template #header><div><b>历史单价趋势</b><small>{{ filters.currency_code || '单一币种' }} / {{ data.unit_codes.join('、') || '单一单位' }}</small></div><div class="legend"><span v-for="(line,index) in data.series" :key="line.name" :style="{ color: palette[index % palette.length] }">{{ line.name }}</span></div></template><div v-if="data.series.length" class="chart"><svg viewBox="0 0 720 220" role="img" aria-label="历史报价单价折线图"><g v-for="(tick,index) in chartTicks" :key="index"><line x1="50" x2="700" :y1="30 + index * 40" :y2="30 + index * 40" stroke="var(--erp-color-border-subtle)"/><text x="5" :y="34 + index * 40" fill="var(--erp-color-text-muted)" font-size="10">{{ tick.toFixed(2) }}</text></g><g v-for="(line,lineIndex) in data.series" :key="line.name"><polyline :points="polyline(line.points)" fill="none" :stroke="palette[lineIndex % palette.length]" stroke-width="2"/><circle v-for="(point,pointIndex) in line.points" :key="`${line.name}-${pointIndex}`" :cx="pointX(pointIndex, line.points.length)" :cy="pointY(point.unit_price)" r="3" :fill="palette[lineIndex % palette.length]"/></g><text x="50" y="212" fill="var(--erp-color-text-muted)" font-size="11">{{ data.series[0].points[0]?.date }}</text><text x="610" y="212" fill="var(--erp-color-text-muted)" font-size="11">{{ data.series[0].points.at(-1)?.date }}</text></svg></div><ElEmpty v-else :description="data.calculation_warning || '当前筛选没有真实报价趋势'" :image-size="62" /></ElCard><ElCard class="insight-card" shadow="never"><template #header><b>趋势洞察</b></template><div class="insight success"><b>{{ Number(data.metrics.latest_quote_price || 0) <= Number(data.metrics.average_quote_price || 0) ? '报价回落' : '报价上升' }}</b><span>{{ insight }}</span></div><div class="insight warning"><b>数据范围</b><span>仅包含您有权限查看的 {{ data.records.length }} 条正式报价行快照。</span></div><div class="insight info"><b>数据提示</b><span>{{ data.source_label }}</span></div></ElCard></div>
      <ElCard class="records-card" shadow="never"><template #header><div class="records-head"><b>历史报价记录</b><span>{{ data.source_label }}</span></div></template><ElTable :data="data.records" empty-text="当前筛选没有真实报价记录" size="small"><ElTableColumn prop="date" label="日期" width="105"/><ElTableColumn label="版本" width="72"><template #default="{ row }">V{{ row.version_number }}</template></ElTableColumn><ElTableColumn prop="customer_name" label="客户" min-width="140" show-overflow-tooltip/><ElTableColumn prop="product" label="产品" min-width="160" show-overflow-tooltip/><ElTableColumn label="档位" min-width="100"><template #default="{ row }">{{ row.container_types.join('、') || '未配置' }}</template></ElTableColumn><ElTableColumn label="数量" width="90"><template #default="{ row }">{{ row.quantity }} {{ row.unit_code }}</template></ElTableColumn><ElTableColumn label="单价" width="112"><template #default="{ row }"><b>{{ row.currency_code }} {{ row.unit_price }}</b></template></ElTableColumn><ElTableColumn prop="incoterm" label="贸易条款" width="105"/><ElTableColumn label="状态" width="88"><template #default="{ row }"><ElTag size="small">{{ row.status_label }}</ElTag></template></ElTableColumn><ElTableColumn label="操作" width="82" fixed="right"><template #default="{ row }"><ElButton size="small" @click="router.push({ name: 'quotation-preview', params: { quotationId: row.quotation_id }, query: { version: row.version_id } })">查看</ElButton></template></ElTableColumn></ElTable></ElCard>
    </template><ElResult v-else-if="errorMessage" :icon="errorStatus === 403 ? 'warning' : 'error'" :title="errorTitle" :sub-title="errorMessage"><template #extra><ElButton v-if="errorStatus === 403" @click="router.push({ name: 'quotations' })">返回报价列表</ElButton><ElButton v-else class="black-button" @click="loadHistory">重新加载</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail';

.price-history-page { min-width: 0; width: 100%; max-width: 1600px; color: var(--erp-color-text-primary); --el-color-primary: var(--erp-color-brand); }
.price-history-page header { display: flex; justify-content: space-between; align-items: end; gap: 14px; margin-bottom: 14px; }
.crumb { margin: 0 0 6px; color: var(--erp-color-text-secondary); font-size: 12px; }
.heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px; }
.heading h1 { margin: 0; font: 700 36px/44px var(--erp-font-body); }
.heading span { color: var(--erp-color-text-secondary); font-size: 13px; }
.filter-card, .metric-row :deep(.el-card), .chart-card, .insight-card, .records-card { @include detail.surface; }
.filter-card :deep(.el-card__body) { padding: 14px 16px; }
.filters { display: grid; grid-template-columns: 1.35fr 1.35fr .82fr .72fr 1fr auto; gap: 12px; align-items: end; }
.filters label { display: grid; min-width: 0; gap: 5px; color: var(--erp-color-text-secondary); font-size: 12px; }
.filters :deep(.el-input__wrapper), .filters :deep(.el-select__wrapper) { height: 32px; min-height: 32px; padding: 0 12px; border-radius: var(--erp-radius-control); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.filters :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.filter-actions { display: flex; gap: 10px; }
.filter-actions :deep(.el-button + .el-button) { margin-left: 0; }
.black-button { color: var(--erp-button-primary-text); border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); box-shadow: var(--erp-button-primary-shadow); }
.black-button:hover { background: var(--erp-button-primary-hover-surface); }
.metric-row { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; margin: 14px 0; }
.metric-row :deep(.el-card__body) { display: grid; gap: 6px; padding: 14px 16px; }
.metric-row small, .metric-row span { color: var(--erp-color-text-secondary); font-size: 12px; }
.metric-row b { font-size: 20px; }
.main-row { display: grid; grid-template-columns: minmax(0,2fr) minmax(300px,1fr); gap: 14px; }
.chart-card :deep(.el-card__header), .insight-card :deep(.el-card__header), .records-card :deep(.el-card__header) { padding: 14px 16px; border-bottom: 1px solid var(--erp-glass-border); }
.chart-card :deep(.el-card__header) > div { display: flex; justify-content: space-between; align-items: center; }
.chart-card :deep(.el-card__body) { padding: 14px; }
.chart-card small { display: block; margin-top: 4px; color: var(--erp-color-text-secondary); font-size: 12px; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; }
.chart { height: 192px; }
.chart svg { width: 100%; height: 100%; }
.chart-card :deep(.el-empty) { min-height: 192px; }
.insight-card :deep(.el-card__body) { display: grid; gap: 12px; padding: 12px 16px 16px; }
.insight { @include detail.inset; display: grid; gap: 5px; padding: 11px 12px; font-size: 12px; }
.insight b { font-size: 13px; }
.success { color: var(--erp-color-success); }
.warning { color: var(--erp-color-warning); }
.info { color: var(--erp-color-info); }
.insight span { color: var(--erp-color-text-primary); }
.records-card { margin-top: 14px; }
.records-head { display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; align-items: center; }
.records-head span { color: var(--erp-color-text-secondary); font-size: 12px; }
.records-card :deep(.el-card__body) { padding: 0 16px 14px; }
.records-card :deep(.el-table th.el-table__cell) { background: var(--erp-table-header-background); color: var(--erp-table-text); }
.records-card :deep(.el-table__row td) { height: 40px; }
.calculation-warning { margin-top: 14px; }
@media (min-width: 1700px) { .chart { height: 254px; } }
@media (max-width: 1240px) { .filters { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 900px) { .main-row { grid-template-columns: minmax(0,1fr); } .metric-row { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 640px) { .price-history-page header { align-items: flex-start; flex-direction: column; } .filters { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
