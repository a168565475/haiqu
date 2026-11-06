<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button as VanButton, Loading as VanLoading, Tag as VanTag } from 'vant'
import WorkPage from '@/components/WorkPage.vue'
import ProductionSectionTabs from '@/components/ProductionSectionTabs.vue'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { materialAttributes, quantityText } from '@/utils/materialQuantities'
import { fetchMaterialIssue, fetchMaterialIssues } from '@/api/materialIssues'
import type { MaterialIssue, MaterialIssueStatus } from '@/types/materialIssue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const query = (key: string) => typeof route.query[key] === 'string' ? route.query[key] as string : ''
const records = ref<MaterialIssue[]>([])
const detail = ref<MaterialIssue | null>(null)
const loading = ref(false)
const loadError = ref('')
const page = ref(1)
const total = ref(0)
const totalPages = ref(0)
const status = ref<MaterialIssueStatus | ''>('')
let generation = 0
let active = true
const statusLabels: Record<MaterialIssueStatus, string> = { DRAFT: '未提交', PENDING_REVIEW: '等待仓库发料', RETURNED: '仓库已退回', ISSUED: '仓库已发料' }
const statusType = (value: MaterialIssueStatus) => ({ DRAFT: 'default', PENDING_REVIEW: 'primary', RETURNED: 'danger', ISSUED: 'success' }[value]) as 'default' | 'primary' | 'danger' | 'success'
const scope = computed(() => Object.fromEntries(['production_task_id', 'product_line_id', 'workshop_id'].filter(key => query(key)).map(key => [key, query(key)])))
const allRecords = computed(() => !Object.keys(scope.value).length && !query('issue_id'))
const scopeText = computed(() => Object.keys(scope.value).length === 3 ? '当前生产单、产品与车间的申请记录'
  : Object.keys(scope.value).length ? '按所选条件筛选的申请记录' : '当前账号有权限查看的申请记录')
const canEdit = computed(() => detail.value && ['DRAFT', 'RETURNED'].includes(detail.value.status)
  && auth.hasPermission('material_issues.change_materialissue') && auth.hasPermission('material_issues.submit_materialissue'))
const returnReason = computed(() => [...(detail.value?.audit_events || [])].reverse().find(event => event.action === 'RETURNED')?.reason)
function dateText(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间无效' : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
async function load() {
  const run = ++generation
  loading.value = true; loadError.value = ''; detail.value = null; records.value = []
  try {
    if (query('issue_id')) {
      const result = await fetchMaterialIssue(query('issue_id'))
      if (!active || run !== generation) return
      const actual = { production_task_id: result.data.production_task?.id, product_line_id: result.data.product?.id, workshop_id: result.data.workshop?.id }
      if (Object.entries(scope.value).some(([key, value]) => actual[key as keyof typeof actual] !== value)) throw new Error('该领料记录与当前任务、产品或车间不一致，请返回记录列表重新选择。')
      detail.value = result.data
    } else {
      const result = await fetchMaterialIssues({ ...scope.value, page: page.value, page_size: 20, status: status.value || undefined, ordering: '-created_at' })
      if (!active || run !== generation) return
      records.value = result.data; total.value = result.meta.total; totalPages.value = result.meta.total_pages
    }
  } catch (error) { if (active && run === generation) loadError.value = errorMessage(error, '领料记录加载失败，请重试。') }
  finally { if (active && run === generation) loading.value = false }
}
function showList() {
  const nextQuery = { ...route.query }
  delete nextQuery.issue_id
  void router.replace({ path: '/issue-records', query: nextQuery })
}
function openDetail(record: MaterialIssue) { void router.push({ path: '/issue-records', query: { ...route.query, issue_id: record.id } }) }
function edit() {
  if (!detail.value) return
  void router.push({ path: '/issue', query: { ...route.query, issue_id: detail.value.id,
    production_task_id: detail.value.production_task?.id, product_line_id: detail.value.product?.id, workshop_id: detail.value.workshop?.id } })
}
function changePage(nextPage: number) { page.value = nextPage; void load() }
watch(status, () => { page.value = 1; void load() })
watch(() => route.fullPath, () => { page.value = 1; void load() }, { immediate: true })
onBeforeUnmount(() => { active = false; generation += 1 })
</script>

<template>
  <WorkPage :title="allRecords ? '生产领料' : query('issue_id') ? '领料申请详情' : '领料记录'" :subtitle="scopeText" section="issue" :home="allRecords" back-to="/">
    <ProductionSectionTabs v-if="allRecords" section="issue" :records="true" />
    <div class="page-stack issue-records-page">
      <button v-if="query('issue_id')" type="button" class="action-link back-to-records" @click="showList">返回领料记录列表</button>
      <section v-else class="section-card filter-card">
        <label class="field-label" for="issue-status">申请状态</label>
        <select id="issue-status" v-model="status" :disabled="loading"><option value="">全部状态</option><option v-for="(label, value) in statusLabels" :key="value" :value="value">{{ label }}</option></select>
      </section>
      <div v-if="loading" class="section-card loading-panel"><VanLoading vertical>正在读取领料记录</VanLoading></div>
      <div v-else-if="loadError" class="error-panel" role="alert"><p>{{ loadError }}</p><VanButton block @click="load">重新加载</VanButton></div>
      <template v-else-if="detail">
        <section class="section-card record-overview">
          <div class="record-heading"><h2>{{ detail.issue_number }}</h2><VanTag plain :type="statusType(detail.status)">{{ statusLabels[detail.status] || detail.status_display }}</VanTag></div>
          <h3>{{ detail.product?.product_name || '产品未记录' }}</h3>
          <p class="muted">{{ detail.product?.product_number }} · {{ detail.product?.specification_display || detail.product?.specification || '规格未记录' }}</p>
          <dl class="record-fields"><dt>生产单</dt><dd>{{ detail.production_task?.task_number || '未记录' }}</dd><dt>车间</dt><dd>{{ detail.workshop?.name || '未记录' }}</dd><dt>领料人</dt><dd>{{ detail.recipient?.name || '未记录' }}</dd><dt>领料时间</dt><dd>{{ dateText(detail.issue_at) }}</dd><dt>申请人</dt><dd>{{ detail.created_by.name }}</dd><dt>提交时间</dt><dd>{{ dateText(detail.submitted_at) }}</dd><dt>发料时间</dt><dd>{{ dateText(detail.issued_at) }}</dd></dl>
          <p v-if="detail.remark" class="record-remark">备注：{{ detail.remark }}</p>
        </section>
        <div v-if="detail.status === 'RETURNED'" class="error-panel" role="alert"><b>仓库退回原因</b><p>{{ returnReason || '未记录退回说明，请联系仓库。' }}</p></div>
        <p v-if="detail.status === 'PENDING_REVIEW'" class="muted pending-note">申请已提交，实际发料由仓库在 ERP 中确认。</p>
        <h2 class="section-title detail-section-title">申请材料</h2>
        <article v-for="line in detail.lines" :key="line.id" class="section-card line-card">
          <h3>{{ line.material_name }}</h3><p class="muted">{{ [line.specification, line.color, line.completed_craft].filter(Boolean).join(' · ') || '规格未记录' }}</p>
          <div class="summary-grid line-quantities"><span>申请 <b>{{ quantityText(line.requested_quantity) }} {{ line.unit }}</b></span><span>已发料 <b>{{ quantityText(line.issued_quantity) }} {{ line.unit }}</b></span></div>
          <details class="line-details"><summary>材料与数量详情</summary>
            <p v-for="attribute in materialAttributes(line)" :key="attribute.key">{{ attribute.label }}：{{ attribute.value }}</p>
            <p>需求 {{ quantityText(line.required_quantity) }} · 累计已领 {{ quantityText(line.internal_issued_quantity) }} · 已外发 {{ quantityText(line.outsourcing_issued_quantity) }} {{ line.unit }}</p>
            <p>待审核 {{ quantityText(line.pending_issue_quantity) }} · 可领 {{ quantityText(line.max_issue_quantity) }} {{ line.unit }}</p>
            <p v-if="line.bar_count || line.meters">实际折合 {{ quantityText(line.bar_count) }} 根／{{ quantityText(line.meters) }} 米</p>
            <p v-for="allocation in line.public_stock_allocations || []" :key="allocation.id">{{ allocation.warehouse_zone }}：{{ quantityText(allocation.stock_quantity) }} {{ allocation.stock_unit }}<template v-if="allocation.meter_quantity !== null">／{{ quantityText(allocation.meter_quantity) }} 米</template></p>
          </details>
        </article>
        <section class="section-card audit-card"><h3>处理记录</h3><p v-if="!detail.audit_events.length" class="muted">暂无处理记录</p><div v-for="event in detail.audit_events" :key="event.id" class="event-row"><b>{{ event.action_display }}</b><span>{{ event.actor.name }} · {{ dateText(event.created_at) }}</span><p v-if="event.reason">{{ event.reason }}</p></div></section>
      </template>
      <template v-else>
        <p v-if="!records.length" class="section-card empty-records">当前筛选范围内暂无领料申请。</p>
        <button v-for="record in records" :key="record.id" type="button" class="section-card record-button" @click="openDetail(record)">
          <div class="record-heading"><b>{{ record.issue_number }}</b><VanTag plain :type="statusType(record.status)">{{ statusLabels[record.status] || record.status_display }}</VanTag></div>
          <h3>{{ record.product?.product_name || '产品未记录' }}</h3><p>{{ record.production_task?.task_number || '生产单未记录' }} · {{ record.workshop?.name || '车间未记录' }}</p>
          <p class="muted">领料人 {{ record.recipient?.name || '未记录' }} · {{ record.line_count }} 项材料</p><div class="record-footer"><span class="muted">{{ dateText(record.created_at) }}</span><span class="view-detail">查看申请详情</span></div>
        </button>
        <div v-if="totalPages > 1" class="pagination"><VanButton :disabled="page <= 1" @click="changePage(page - 1)">上一页</VanButton><span>{{ page }} / {{ totalPages }} · 共 {{ total }} 条</span><VanButton :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</VanButton></div>
      </template>
    </div>
    <template #footer><VanButton v-if="canEdit && !loading && !loadError" block type="primary" @click="edit">修改并重新提交</VanButton></template>
  </WorkPage>
</template>

<style scoped>
.issue-records-page { color: var(--mobile-text); font-size: 16px; }
.issue-records-page p { margin: 8px 0; line-height: 1.6; overflow-wrap: anywhere; }
.issue-records-page h2, .issue-records-page h3 { margin: 0 0 8px; font-size: 18px; line-height: 1.5; overflow-wrap: anywhere; }
.issue-records-page .section-card { border-radius: 12px; background: var(--mobile-surface); }
.issue-records-page .muted { color: var(--mobile-muted); }
.back-to-records { justify-self: start; min-height: 48px; padding-left: 0; color: var(--mobile-primary); }
.loading-panel { padding: 36px 16px; }
.filter-card { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 16px; }
.filter-card .field-label { margin: 0; color: var(--mobile-text); font-weight: 600; }
.filter-card select { width: 100%; min-width: 0; min-height: 48px; padding: 10px 12px; border: 1px solid var(--mobile-border); border-radius: 8px; background: var(--mobile-surface); font: inherit; color: var(--mobile-text); }
.filter-card select:disabled { background: var(--mobile-canvas); color: var(--mobile-muted); }
.filter-card select:focus-visible, .record-button:focus-visible, .line-details summary:focus-visible { outline: 2px solid var(--mobile-primary); outline-offset: 2px; }
.record-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 12px; margin-bottom: 14px; }
.record-heading b, .record-heading h2 { min-width: 0; margin: 0; color: var(--mobile-muted); font-size: 14px; font-weight: 500; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.record-heading :deep(.van-tag) { flex-shrink: 0; max-width: 100%; white-space: normal; padding: 4px 8px; border-radius: 4px; font-size: 13px; line-height: 20px; }
.record-button { width: 100%; min-width: 0; text-align: left; font: inherit; color: var(--mobile-text); cursor: pointer; }
.record-button:active { background: var(--mobile-primary-soft); }
.record-button > p, .record-overview > .muted, .line-card > .muted { font-size: 14px; }
.record-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--mobile-border); font-size: 13px; }
.record-footer .muted { font-variant-numeric: tabular-nums; }
.record-button .view-detail { color: var(--mobile-primary); font-size: 14px; font-weight: 500; }
.record-fields { display: grid; grid-template-columns: 5em minmax(0, 1fr); gap: 12px 14px; margin: 18px 0 0; padding-top: 16px; border-top: 1px solid var(--mobile-border); font-size: 16px; line-height: 1.5; }
.record-fields dt { color: var(--mobile-muted); }
.record-fields dd { min-width: 0; margin: 0; color: var(--mobile-text); overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.record-overview .record-remark { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--mobile-border); font-size: 14px; }
.issue-records-page .pending-note { margin: 0; padding: 12px 14px; border-radius: 8px; background: var(--mobile-primary-soft); color: var(--mobile-primary); font-size: 14px; }
.issue-records-page .detail-section-title { margin: 4px 2px 0; }
.line-quantities { gap: 16px; margin: 16px 0 0; padding: 14px 0; border-top: 1px solid var(--mobile-border); border-bottom: 1px solid var(--mobile-border); }
.line-quantities > span { display: flex; min-width: 0; flex-direction: column; gap: 6px; color: var(--mobile-muted); font-size: 14px; }
.line-quantities b { color: var(--mobile-text); font-size: 18px; font-weight: 600; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.line-quantities > span:first-child b { color: var(--mobile-primary); }
.line-details { margin-top: 4px; font-size: 14px; color: var(--mobile-muted); }
.line-details summary { box-sizing: border-box; min-height: 48px; padding: 12px 0; cursor: pointer; color: var(--mobile-primary); }
.line-details summary::marker { color: var(--mobile-primary); }
.audit-card h3 { margin-bottom: 16px; }
.event-row { padding: 14px 0; border-top: 1px solid var(--mobile-border); }
.event-row:last-child { padding-bottom: 0; }
.event-row b { color: var(--mobile-text); font-size: 16px; font-weight: 600; }
.event-row span { display: block; margin-top: 6px; color: var(--mobile-muted); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.event-row p { color: var(--mobile-text); font-size: 14px; }
.issue-records-page .empty-records { margin: 0; padding: 36px 20px; text-align: center; color: var(--mobile-muted); }
.pagination { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.pagination span { text-align: center; font-size: 13px; color: var(--mobile-muted); }
.pagination .van-button { min-height: 48px; }
@media (max-width: 359px) { .filter-card { grid-template-columns: 1fr; gap: 10px; } }
</style>
