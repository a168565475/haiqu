<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkPage from '@/components/WorkPage.vue'
import { fetchReportingContext, fetchWorkReports } from '@/api/reporting'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { quantityText, reportingRecordScope, reportTime } from '@/utils/reporting'
import type { ReportingContext, WorkReport } from '@/types/reporting'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const scope = computed(() => reportingRecordScope(route.query))
const context = ref<ReportingContext | null>(null)
const records = ref<WorkReport[]>([])
const loading = ref(false)
const loadError = ref('')
const page = ref(1)
const totalPages = ref(0)
const total = ref(0)
const expanded = ref<string[]>([])
let requestSequence = 0
let controller: AbortController | null = null
const product = computed(() => context.value?.schedule_product)
const workshop = computed(() => context.value?.workshops.find(item => item.id === scope.value?.workshop_id))
const craft = computed(() => context.value?.crafts.find(item => item.id === scope.value?.craft_id))
const canCreate = computed(() => auth.hasPermission('workshop_reporting.add_workreport') && auth.hasPermission('workshop_reporting.view_workreport'))

async function load(targetPage = 1) {
  controller?.abort()
  controller = new AbortController()
  const current = ++requestSequence
  const selected = scope.value
  records.value = []; expanded.value = []; loadError.value = ''
  total.value = 0; totalPages.value = 0
  if (!selected) {
    context.value = null
    loadError.value = '缺少有效的生产任务或车间，请返回任务列表重新选择。'
    return
  }
  loading.value = true
  try {
    const [reportContext, result] = await Promise.all([
      fetchReportingContext(selected.schedule_product_id, controller.signal),
      fetchWorkReports(selected, targetPage, controller.signal),
    ])
    if (current !== requestSequence) return
    const selectedCraft = reportContext.crafts.find(item => item.id === selected.craft_id)
    if (reportContext.schedule_product?.id !== selected.schedule_product_id
      || !reportContext.workshops.some(item => item.id === selected.workshop_id)
      || (selectedCraft && selectedCraft.workshop_id !== selected.workshop_id)) {
      throw new Error('生产任务范围已经变化，请返回任务列表重新选择。')
    }
    context.value = reportContext
    records.value = result.data
    page.value = result.meta.page
    total.value = result.meta.total
    totalPages.value = result.meta.total_pages
  }
  catch (error) {
    if (current === requestSequence) loadError.value = errorMessage(error, '报工记录加载失败，请重试。')
  }
  finally { if (current === requestSequence) loading.value = false }
}

function toggleRecord(id: string) {
  expanded.value = expanded.value.includes(id) ? expanded.value.filter(value => value !== id) : [...expanded.value, id]
}
function newReport() {
  if (!scope.value) return
  void router.push(scope.value.craft_id
    ? { path: '/report', query: { ...route.query } }
    : { path: '/plan', query: { ...route.query, action: 'report' } })
}
watch(() => route.fullPath, () => { context.value = null; page.value = 1; void load() }, { immediate: true })
onBeforeUnmount(() => { requestSequence++; controller?.abort() })
</script>

<template>
  <WorkPage title="报工记录" :subtitle="workshop ? `${workshop.name} · ${craft?.name || (scope?.craft_id ? '指定工艺' : '本计划全部工艺')}` : '查看这项生产任务的报工'">
    <div class="page-stack report-records">
      <section v-if="product" class="section-card records-context">
        <h2 class="section-title">{{ product.product_name }}</h2>
        <p class="muted records-product-identity">{{ product.task_number }} · {{ product.product_code || product.product_number }}</p>
        <p class="records-product-specification">{{ [product.product_specification, product.product_color].filter(Boolean).join(' · ') }}</p>
        <div class="records-toolbar"><span>共 <strong>{{ total }}</strong> 笔报工</span><button type="button" class="action-link" :disabled="loading" @click="load(page)"><van-icon name="replay" aria-hidden="true" />刷新记录</button></div>
      </section>

      <div v-if="loading" class="records-loading" role="status"><van-loading size="26">正在读取报工记录…</van-loading></div>
      <section v-else-if="loadError" class="error-panel" role="alert">
        <p>{{ loadError }}</p>
        <van-button v-if="scope" block @click="load(page)">重新加载</van-button>
        <van-button v-else block @click="router.push('/')">返回任务列表</van-button>
      </section>
      <van-empty v-else-if="!records.length" description="这项任务暂时没有报工记录" />

      <article v-for="record in records" :key="record.id" class="section-card records-card">
        <div class="records-heading"><h2>{{ record.production_date }}</h2><van-tag v-if="record.completed_plan" type="success" plain>本笔完成计划</van-tag></div>
        <p class="muted records-number">{{ record.report_number }}</p>
        <p class="record-craft">{{ record.workshop.name }} · {{ record.scope_craft.name }}</p>
        <dl class="summary-grid records-summary">
          <div><dt>报工明细</dt><dd>{{ record.lines.length }} 条</dd></div>
          <div><dt>报工金额</dt><dd>{{ quantityText(record.total_amount) }} 元</dd></div>
          <div><dt>记录人</dt><dd>{{ record.recorder }}</dd></div>
          <div><dt>提交时间</dt><dd>{{ reportTime(record.created_at) }}</dd></div>
        </dl>
        <p v-if="!expanded.includes(record.id)" class="records-preview">{{ record.lines.slice(0, 2).map(line => `${line.employee_name}：${line.operation_name} ${quantityText(line.quantity)} 次`).join('；') }}{{ record.lines.length > 2 ? '…' : '' }}</p>
        <button type="button" class="records-expand" :aria-expanded="expanded.includes(record.id)" :aria-controls="`report-detail-${record.id}`" @click="toggleRecord(record.id)">{{ expanded.includes(record.id) ? '收起报工明细' : '查看全部报工明细' }}<van-icon :name="expanded.includes(record.id) ? 'arrow-up' : 'arrow-down'" /></button>
        <div v-if="expanded.includes(record.id)" :id="`report-detail-${record.id}`" class="records-detail">
          <section v-for="line in record.lines" :key="line.id" class="record-line">
            <div class="record-line-heading"><strong>{{ line.employee_name || '员工资料已变更' }}</strong><strong>{{ quantityText(line.quantity) }} 次</strong></div>
            <p class="record-operation">{{ line.display_name }} · {{ line.operation_name }}</p>
            <p class="muted">工艺：{{ line.craft_name || record.scope_craft.name }}</p>
            <p v-if="line.production_line" class="muted">装配 {{ line.production_line }} 线</p>
            <dl class="summary-grid">
              <div><dt>需完成次数</dt><dd>{{ quantityText(line.required_quantity) }}</dd></div>
              <div><dt>当前累计已报</dt><dd>{{ quantityText(line.cumulative_quantity) }}</dd></div>
              <div><dt>工价快照</dt><dd>{{ quantityText(line.unit_price) }} 元 / 次</dd></div>
              <div><dt>本条金额</dt><dd>{{ quantityText(line.amount) }} 元</dd></div>
            </dl>
          </section>
          <p class="muted">工价第 {{ record.scheme_version }} 版；记录金额按当时报工保存。</p>
          <p v-if="record.updated_at !== record.created_at" class="muted">最近修改：{{ record.updated_by }} · {{ reportTime(record.updated_at) }}</p>
        </div>
      </article>

      <div v-if="!loading && !loadError && totalPages > 1" class="records-pagination">
        <van-button :disabled="page <= 1" @click="load(page - 1)">上一页</van-button>
        <span>{{ page }} / {{ totalPages }}</span>
        <van-button :disabled="page >= totalPages" @click="load(page + 1)">下一页</van-button>
      </div>
    </div>
    <template v-if="scope && context && canCreate" #footer><van-button type="primary" block @click="newReport">{{ scope.craft_id ? '填写新的报工' : '选择工艺并报工' }}</van-button></template>
  </WorkPage>
</template>

<style scoped>
.report-records { color: var(--mobile-text, #172b4d); }
.report-records p { margin: 8px 0; overflow-wrap: anywhere; }
.report-records .section-card { border-radius: 12px; }
.report-records .section-title { margin-bottom: 8px; font-size: 18px; line-height: 1.5; }
.records-product-identity { font-size: 13px; font-variant-numeric: tabular-nums; }
.records-product-specification { font-size: 14px; color: var(--mobile-muted, #64748b); }
.records-loading { padding: 32px 16px; text-align: center; }
.records-toolbar, .records-heading, .record-line-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.records-toolbar { margin-top: 16px; padding-top: 4px; border-top: 1px solid var(--mobile-border, #e2e8f0); color: var(--mobile-muted, #64748b); font-size: 14px; }
.records-toolbar strong { color: var(--mobile-text, #172b4d); font-variant-numeric: tabular-nums; }
.records-toolbar .action-link { display: inline-flex; align-items: center; gap: 6px; min-height: 48px; padding-right: 0; font-weight: 500; }
.records-heading { flex-wrap: wrap; }
.records-heading h2 { margin: 0; font-size: 18px; font-weight: 650; font-variant-numeric: tabular-nums; }
.records-heading .van-tag { padding: 3px 6px; font-size: 12px; border-radius: 4px; }
.records-card .records-number { margin-top: 4px; font-size: 13px; font-variant-numeric: tabular-nums; }
.records-card .record-craft { margin: 14px 0; color: var(--mobile-primary, #2563eb); font-size: 15px; font-weight: 500; }
.records-summary { margin: 0; gap: 12px 16px; }
.records-summary dd { font-size: 15px; line-height: 1.6; font-weight: 500; }
.records-summary > div:last-child dd { font-size: 14px; }
.records-card .records-preview { margin: 16px 0 4px; color: var(--mobile-muted, #64748b); font-size: 14px; line-height: 1.7; }
.records-expand { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 48px; padding: 14px 0 2px; margin-top: 14px; border: 0; border-top: 1px solid var(--mobile-border, #e2e8f0); background: transparent; color: var(--mobile-primary, #2563eb); font: inherit; font-size: 14px; font-weight: 500; text-align: left; cursor: pointer; }
.records-expand:focus-visible { outline: 2px solid var(--mobile-primary, #2563eb); outline-offset: 2px; }
.records-detail { padding-top: 8px; }
.record-line { padding: 16px 0; border-bottom: 1px solid var(--mobile-border, #e2e8f0); }
.record-line-heading { align-items: flex-start; }
.record-line-heading strong { min-width: 0; overflow-wrap: anywhere; font-size: 16px; font-weight: 600; }
.record-line-heading strong:last-child { color: var(--mobile-primary, #2563eb); font-variant-numeric: tabular-nums; }
.record-line .record-operation { margin: 8px 0 4px; font-size: 15px; }
.record-line .muted { margin: 4px 0; font-size: 13px; }
.record-line .summary-grid { margin: 12px 0 0; gap: 10px 16px; font-size: 14px; }
.record-line .summary-grid dd { font-weight: 500; }
.records-detail > .muted { margin: 12px 0 0; font-size: 13px; line-height: 1.65; }
.records-pagination { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.records-pagination > span { color: var(--mobile-muted, #64748b); font-size: 14px; font-variant-numeric: tabular-nums; }
.records-pagination .van-button { min-width: 96px; min-height: 48px; }
</style>
