<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { completeSchedule, fetchSchedules, fetchScheduleCompletionPreview, scheduleProductImageUrl } from '@/api/productionScheduling'
import { fetchScheduleProgressStatuses } from '@/api/workshopReporting'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import ScheduleCompletionDialog from '@/components/productionScheduling/ScheduleCompletionDialog.vue'
import ScheduleListStageProgress from '@/components/productionScheduling/ScheduleListStageProgress.vue'
import { useAuthStore } from '@/stores/auth'
import { scheduleProductSummary } from '@/utils/scheduleListDisplay'
import type { CompleteScheduleInput, CompleteScheduleResult, ProductionSchedule, ScheduleCompletionPreview } from '@/types/productionScheduling'
import type { ScheduleProgressStatus } from '@/types/workshopReporting'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const rows = ref<ProductionSchedule[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const search = ref('')
const createdRange = ref<[string, string] | []>([])
const errorMessage = ref('')
const progressBySchedule = ref<Record<string, ScheduleProgressStatus['progress']>>({})
const displayProgressBySchedule = ref<Record<string, ScheduleProgressStatus>>({})
const progressLoadFailed = ref(false)
let requestSequence = 0
const canCreate = computed(() => auth.user?.is_superuser || auth.hasPermission('production_scheduling.add_productionschedule'))
const canFinish = computed(() => auth.moduleCan('access_control.finish_productiontask', 'production_tasks.change_productiontask'))
const progressKeys = ['MATERIAL', 'METAL', 'SEWING', 'ASSEMBLY'] as const
const progressNames = { MATERIAL: '材料入库', METAL: '金工回货', SEWING: '车缝回货', ASSEMBLY: '成品入库' }
const preparingId = ref('')
const completionVisible = ref(false)
const completionSubmitting = ref(false)
const completionPreview = ref<ScheduleCompletionPreview | null>(null)
const completionResult = ref<CompleteScheduleResult | null>(null)
const completionUncertain = ref(false)
const completionError = ref('')

function errorText(error: unknown) {
  if (!(error instanceof AxiosError)) return '排产列表加载失败，请稍后重试。'
  const data = error.response?.data as { error?: { message?: string } } | undefined
  return data?.error?.message || (error.response?.status === 403 ? '当前账号没有查看排产计划的权限。' : '排产列表加载失败，请稍后重试。')
}
async function load() {
  const current = ++requestSequence
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSchedules({
      page: page.value, page_size: pageSize.value, search: search.value.trim() || undefined,
      created_from: createdRange.value[0] || undefined, created_to: createdRange.value[1] || undefined,
    })
    if (current !== requestSequence) return
    rows.value = result.data
    total.value = result.meta.total
    progressBySchedule.value = {}
    displayProgressBySchedule.value = {}
    progressLoadFailed.value = false
    if (result.data.length) {
      try {
        const progressRows = await fetchScheduleProgressStatuses({
          schedule_ids: result.data.map(item => item.id).join(','),
        })
        if (current !== requestSequence) return
        progressBySchedule.value = Object.fromEntries(progressRows.map(item => [item.schedule_id, item.progress]))
        displayProgressBySchedule.value = Object.fromEntries(progressRows.map(item => [item.schedule_id, item]))
      } catch {
        if (current !== requestSequence) return
        progressBySchedule.value = {}
        displayProgressBySchedule.value = {}
        progressLoadFailed.value = true
      }
    }
  } catch (error) {
    if (current === requestSequence) {
      rows.value = []; total.value = 0; progressBySchedule.value = {}; progressLoadFailed.value = false
      displayProgressBySchedule.value = {}
      errorMessage.value = errorText(error)
    }
  } finally { if (current === requestSequence) loading.value = false }
}
function applyFilters() { page.value = 1; void load() }
function imageUrl(row: ProductionSchedule, fileId: string) { return scheduleProductImageUrl(row.production_task_id, fileId) }
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}
function openDetail(row: ProductionSchedule) { void router.push(`/workshop/scheduling/${row.id}`) }
function completionDisabledReason(row: ProductionSchedule) {
  if (!canFinish.value) return '当前账号没有完成生产任务的权限。'
  if (row.record_status !== 'ACTIVE') return '排产计划已作废。'
  if (row.source_current_status !== 'IN_PRODUCTION') return `生产任务${row.source_current_status_display || '当前状态'}，仅生产中任务可完成。`
  if (progressLoadFailed.value) return '进度加载失败，请刷新后重试。'
  const progress = progressBySchedule.value[row.id]
  if (!progress) return '进度尚未加载完成。'
  const pending = progressKeys.filter(key => progress[key]?.percentage !== 100)
    .map(key => `${progressNames[key]} ${progress[key]?.display || '进度缺失'}`)
  return pending.length ? `以下进度未达到100%：${pending.join('、')}` : ''
}
function progressReady(row: ProductionSchedule) { return !completionDisabledReason(row) }
function completionErrorText(error: unknown) {
  if (error instanceof AxiosError) {
    const data = error.response?.data as { error?: { message?: string } } | undefined
    if (data?.error?.message) return data.error.message
  }
  return '完成订单失败，请稍后重试。'
}
async function completeRow(row: ProductionSchedule) {
  if (preparingId.value || completionSubmitting.value) return
  if (!progressReady(row)) {
    ElMessage.warning(completionDisabledReason(row))
    return
  }
  preparingId.value = row.id
  try {
    const preview = await fetchScheduleCompletionPreview(row.id)
    progressBySchedule.value[row.id] = preview.progress
    if (!progressReady(row)) { ElMessage.warning(completionDisabledReason(row)); return }
    if (preview.task.status !== 'IN_PRODUCTION') {
      ElMessage.warning(`生产任务${preview.task.status_display}，仅生产中任务可完成。`)
      return
    }
    if (!preview.schedule_etag || !preview.task.etag) { ElMessage.error('未取得排产或生产任务版本，请刷新后重试。'); return }
    completionPreview.value = preview
    completionResult.value = null
    completionUncertain.value = false
    completionError.value = ''
    completionVisible.value = true
  } catch (error) {
    ElMessage.error(completionErrorText(error))
  } finally { preparingId.value = '' }
}
async function submitCompletion(reason: string) {
  const preview = completionPreview.value
  if (!preview || completionSubmitting.value || completionResult.value || completionUncertain.value) return
  if (!canFinish.value || progressKeys.some(key => preview.progress[key]?.percentage !== 100)) {
    completionError.value = '完成权限或进度已变化，请刷新后重新核对。'
    return
  }
  if (!reason.trim() || reason.trim().length > 500) { completionError.value = '请填写500字以内的完成说明。'; return }
  const payload: CompleteScheduleInput = { task_etag: preview.task.etag, reason: reason.trim() }
  if (preview.sales_order.can_sync && preview.sales_order.etag) payload.sales_order_etag = preview.sales_order.etag
  completionSubmitting.value = true
  completionError.value = ''
  try {
    completionResult.value = await completeSchedule(preview.schedule_id, payload, preview.schedule_etag)
    await load()
  } catch (error) {
    // 断网或代理异常时可能已提交，不能宣称回滚或允许直接重发。
    completionUncertain.value = !(error instanceof AxiosError) || !error.response
      || ![400, 401, 403, 404, 409, 412, 428].includes(error.response.status)
    completionError.value = completionUncertain.value
      ? '未收到状态更新确认，请关闭弹窗并刷新列表核实结果，避免重复提交。'
      : completionErrorText(error)
  } finally { completionSubmitting.value = false }
}
function handleRowAction(command: string, row: ProductionSchedule) {
  if (command === 'view') openDetail(row)
  if (command === 'complete') void completeRow(row)
}
function overallPercentage(row: ProductionSchedule) { return displayProgressBySchedule.value[row.id]?.overall_percentage ?? null }
function listMoney(value: string | null | undefined) {
  if (value == null) return '—'
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'
}
onMounted(() => { void load() })
</script>

<template>
  <section class="schedule-page schedule-list erp-glass-list" data-testid="production-scheduling-list">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="schedule-heading erp-list-heading"><div class="erp-list-title-row"><h1>排产计划</h1></div></header>
    <div class="schedule-filter-bar erp-list-filters">
      <ElInput v-model="search" class="schedule-search" :prefix-icon="Search" clearable placeholder="搜索排产单号、生产任务单号、产品" @keyup.enter="applyFilters" @clear="applyFilters" />
      <div class="schedule-created-filter"><span>创建日期</span><ElDatePicker v-model="createdRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="applyFilters" /></div>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" :icon="Refresh" :loading="loading" @click="load">刷新</ElButton><ElButton class="erp-button-motion" @click="search=''; createdRange=[]; applyFilters()">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="applyFilters">应用筛选</ElButton></div>
    </div>
    </section>
    <section class="erp-list-data">
    <div class="erp-list-toolbar"><ElButton class="erp-button-motion" v-if="canCreate" type="primary" @click="router.push('/workshop/scheduling/new')">＋ 新增排产</ElButton></div>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false"><ElButton class="erp-button-motion" @click="load">重试</ElButton></ElAlert>
    <div v-else class="schedule-table-card schedule-main-table erp-list-table-frame">
      <ElTable height="100%" v-loading="loading" :data="rows" border row-key="id" empty-text="暂无排产计划">
        <ElTableColumn prop="schedule_number" label="排产单号" width="135" />
        <ElTableColumn label="生产任务单" width="120"><template #default="{ row }"><strong>{{ row.source.task_number }}</strong></template></ElTableColumn>
        <ElTableColumn label="产品" min-width="160"><template #default="{ row }">
          <ElPopover trigger="hover" placement="bottom-start" :width="640" :show-after="120" :hide-after="120" :persistent="false" :disabled="!row.products.length" popper-class="schedule-products-popover">
            <template #reference><button type="button" class="schedule-products-summary">{{ scheduleProductSummary(row.products) }}</button></template>
            <div class="schedule-products-content">
              <header>{{ scheduleProductSummary(row.products) }}</header>
              <div class="schedule-products-grid">
                <article v-for="product in row.products" :key="product.id" class="schedule-hover-product">
                  <img :src="product.image_file_id ? imageUrl(row, product.image_file_id) : productImagePlaceholder" :class="{ 'is-placeholder': !product.image_file_id }" :alt="`${product.product.product_name || '产品'}图片`" @error="useProductImageFallback" />
                  <div class="schedule-hover-product-info">
                    <strong>{{ product.product.product_name || '未命名产品' }}</strong>
                    <small>{{ product.product.item_number || product.product.product_number || '—' }}</small>
                    <dl>
                      <div><dt>颜色</dt><dd>{{ product.product.color_name || '—' }}</dd></div>
                      <div><dt>材质</dt><dd>{{ product.product.material || '—' }}</dd></div>
                      <div><dt>规格</dt><dd>{{ product.product.specification_display || product.product.specification || '—' }}</dd></div>
                      <div><dt>排产数量</dt><dd>{{ product.planned_quantity }} {{ product.unit_name }}</dd></div>
                    </dl>
                  </div>
                </article>
              </div>
            </div>
          </ElPopover>
        </template></ElTableColumn>
        <ElTableColumn label="计划开始" width="105"><template #default="{ row }">{{ row.source.planned_start_date || '—' }}</template></ElTableColumn>
        <ElTableColumn label="交货日期" width="105"><template #default="{ row }">{{ row.source.delivery_date || '—' }}</template></ElTableColumn>
        <ElTableColumn label="总进度" width="200"><template #default="{ row }">
          <div class="schedule-overall-progress" :title="progressLoadFailed ? '进度加载失败，请刷新重试' : overallPercentage(row) === null ? '部分工序进度暂不可用' : '四个环节各占25%'">
            <ElProgress v-if="overallPercentage(row) !== null" :percentage="overallPercentage(row)!" :stroke-width="14" :show-text="false" />
            <span v-else class="schedule-overall-unknown" />
            <span>{{ overallPercentage(row) === null ? '—' : `${overallPercentage(row)}%` }}</span>
          </div>
        </template></ElTableColumn>
        <ElTableColumn label="工序进度" min-width="374"><template #default="{ row }">
          <ScheduleListStageProgress :schedule="row" :progress="displayProgressBySchedule[row.id]" :failed="progressLoadFailed" />
        </template></ElTableColumn>
        <ElTableColumn label="总工价" width="110" align="right"><template #default="{ row }">{{ listMoney(row.list_amounts?.estimated_wage) }}</template></ElTableColumn>
        <ElTableColumn label="报工总额" width="110" align="right"><template #default="{ row }">{{ listMoney(row.list_amounts?.reported_amount) }}</template></ElTableColumn>
        <ElTableColumn label="工厂跟单员" width="110" show-overflow-tooltip><template #default="{ row }">{{ row.factory_follower_names?.join('、') || '—' }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="80" fixed="right"><template #default="{ row }"><ElDropdown trigger="click" placement="bottom-end" @command="handleRowAction($event, row)"><ElButton link type="primary" :loading="preparingId === row.id">更多</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem command="view">查看</ElDropdownItem><ElDropdownItem command="complete" :disabled="!progressReady(row) || Boolean(preparingId) || completionSubmitting" :title="completionDisabledReason(row)">完成订单</ElDropdownItem></ElDropdownMenu></template></ElDropdown></template></ElTableColumn>
      </ElTable>
    </div>
    <footer class="schedule-pagination erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()" /></footer>
    </section>
    <ScheduleCompletionDialog v-model="completionVisible" :preview="completionPreview" :submitting="completionSubmitting"
      :result="completionResult" :error="completionError" :uncertain="completionUncertain" @confirm="submitCompletion" />
  </section>
</template>

<style lang="scss">@use '@/styles/productionScheduling.scss';</style>
<style scoped lang="scss">
.schedule-products-summary { max-width: 100%; padding: 0; overflow: hidden; border: 0; background: transparent; color: var(--erp-color-brand); font: inherit; cursor: pointer; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.schedule-products-summary:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: 4px; border-radius: 2px; }
.schedule-overall-progress { display: flex; align-items: center; gap: 9px; width: 100%; font-size: 12px; font-variant-numeric: tabular-nums; }
.schedule-overall-progress .el-progress, .schedule-overall-unknown { flex: 1; min-width: 0; }
.schedule-overall-progress > span:last-child { min-width: 32px; text-align: right; }
.schedule-overall-unknown { height: 14px; border-radius: 7px; background: var(--el-fill-color); }
.schedule-products-content { color: var(--erp-color-text-primary); }
.schedule-products-content header { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid var(--erp-table-grid); font-size: 15px; font-weight: 600; }
.schedule-products-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; max-height: min(420px, 60vh); overflow-y: auto; }
.schedule-hover-product { min-width: 0; display: flex; align-items: center; gap: 12px; }
.schedule-hover-product > img { width: 76px; height: 100px; flex: 0 0 76px; border-radius: 4px; object-fit: contain; background: var(--erp-color-subtle); }
.schedule-hover-product > img.is-placeholder { box-sizing: border-box; padding: 6px; }
.schedule-hover-product-info { min-width: 0; flex: 1; }
.schedule-hover-product-info > strong { display: block; font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.schedule-hover-product-info > small { display: block; margin-top: 3px; color: var(--erp-color-text-secondary); font-size: 12px; }
.schedule-hover-product-info dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 10px; margin: 10px 0 0; }
.schedule-hover-product-info dl > div { min-width: 0; }
.schedule-hover-product-info dt { color: var(--erp-color-text-secondary); font-size: 12px; }
.schedule-hover-product-info dd { margin: 3px 0 0; font-size: 12px; overflow-wrap: anywhere; }
:global(.el-popper.el-popover.schedule-products-popover) { max-width: calc(100vw - 32px); box-sizing: border-box; padding: 16px; border: 1px solid var(--erp-table-grid); border-radius: 7px; background: var(--erp-color-surface); box-shadow: 0 8px 24px rgb(30 66 108 / 14%); }
@media (max-width: 620px) { .schedule-products-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
