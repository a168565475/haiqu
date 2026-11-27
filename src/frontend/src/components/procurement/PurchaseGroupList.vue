<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { deletePurchaseGroup, fetchPurchaseGroupFilterOptions, fetchPurchaseGroups, fetchVersionedPurchaseGroup } from '@/api/purchaseGroups'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import type { PurchaseGroup, PurchaseGroupFilterOptions, PurchaseGroupProgress } from '@/types/purchaseGroup'
import { groupProductSummary, purchaseGroupBatchCount } from '@/views/procurement/purchaseGroupDisplay'
import { confirmPurchaseGroupDeletion, purchaseGroupDeletionBlock } from '@/views/procurement/purchaseGroupDeletion'

const props = defineProps<{ canAdd: boolean; canDelete?: boolean; packaging?: boolean }>()
const router = useRouter()
const rows = ref<PurchaseGroup[]>([])
const tasks = ref<PurchaseGroupFilterOptions['production_tasks']>([])
const taskId = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const optionsError = ref('')
const deletingId = ref('')
const deleteError = ref('')
let requestVersion = 0
const statusLabels = { PENDING: '待采购', PURCHASING: '采购中', COMPLETED: '采购完成', UNKNOWN: '来源待核对' }
const displayRows = computed(() => rows.value.map(row => ({
  row, products: groupProductSummary(row), totalPercent: totalPurchaseProgress(row.progress),
  batchCount: purchaseGroupBatchCount(row), hasConfirmedBatch: row.batches.some(batch => batch.status !== 'DRAFT'),
  deletionBlock: purchaseGroupDeletionBlock(row),
})))

function totalPurchaseProgress(progress: PurchaseGroupProgress): number | null {
  if (progress.status === 'UNKNOWN' || !progress.lines.length || progress.lines.length !== progress.line_count) return null
  const percentages = progress.lines.map(line => line.progress_percent !== null && /^\d+(?:\.\d+)?$/.test(line.progress_percent)
    ? Number(line.progress_percent) : NaN)
  if (percentages.some(value => !Number.isFinite(value))) return null
  const satisfied = progress.lines.filter(line => line.is_satisfied).length
  if (satisfied !== progress.satisfied_line_count || (progress.status === 'COMPLETED') !== (satisfied === progress.line_count)) return null
  const average = percentages.reduce((sum, value) => sum + Math.min(value, 100), 0) / progress.line_count
  // 逐项百分比已四舍五入，只有原始数量全部达标才显示100%。
  return satisfied === progress.line_count ? 100 : Math.min(Math.round(average * 10) / 10, 99.9)
}

async function load(): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchPurchaseGroups(
      { page: page.value, page_size: pageSize.value, ...(taskId.value ? { production_task_id: taskId.value } : {}) },
      ...(props.packaging ? [true] as const : []),
    )
    if (version !== requestVersion) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (version !== requestVersion) return
    rows.value = []
    total.value = 0
    errorMessage.value = (error as { response?: { data?: { error?: { message?: string } } } }).response?.data?.error?.message || '采购需求加载失败，请重试。'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}
function search(): void { page.value = 1; void load() }
function handleRowAction(command: string, row: PurchaseGroup): void {
  if (command === 'view') {
    void router.push({ name: props.packaging ? 'packaging-purchase-detail' : 'purchase-group-detail', params: { id: row.id } })
  } else if (command === 'remove') {
    void removeGroup(row)
  } else if (command === 'sheets') {
    void router.push({ name: 'supplier-purchase-sheets', query: { purchase_group_id: row.id, ...(props.packaging ? { purchase_scope: 'PACKAGING' } : {}) } })
  }
}
async function removeGroup(row: PurchaseGroup): Promise<void> {
  if (!props.canDelete || deletingId.value || purchaseGroupDeletionBlock(row)) return
  const version = requestVersion
  deletingId.value = row.id
  deleteError.value = ''
  try {
    const latest = await (props.packaging ? fetchVersionedPurchaseGroup(row.id, undefined, true) : fetchVersionedPurchaseGroup(row.id))
    if (version !== requestVersion) return
    rows.value = rows.value.map(item => item.id === row.id ? latest.data : item)
    await confirmPurchaseGroupDeletion(latest)
    if (version !== requestVersion || !props.canDelete) return
    await deletePurchaseGroup(row.id, latest.etag, ...(props.packaging ? [true] as const : []))
    if (version !== requestVersion) return
    ElMessage.success('采购需求及未确认草稿批次已删除。')
    if (page.value > 1 && rows.value.length === 1) page.value--
    await load()
  } catch (error) {
    if (version !== requestVersion || error === 'cancel' || error === 'close') return
    const response = (error as { response?: { status?: number; data?: { error?: { message?: string } } } }).response
    deleteError.value = response?.data?.error?.message || (error instanceof Error ? error.message : '采购需求删除失败，请刷新后重试。')
    if (response?.status === 412 || response?.status === 409 || response?.status === 404) await load()
  } finally { deletingId.value = '' }
}
async function loadOptions(): Promise<void> {
  optionsError.value = ''
  try { tasks.value = (await fetchPurchaseGroupFilterOptions(...(props.packaging ? [true] as const : []))).production_tasks }
  catch { optionsError.value = '生产订单筛选选项加载失败。' }
}
onMounted(() => { void load(); void loadOptions() })
onBeforeUnmount(() => { requestVersion++ })
</script>

<template>
  <section class="group-list" data-testid="purchase-group-list">
    <div class="group-toolbar">
      <ElSelect v-model="taskId" filterable clearable placeholder="全部生产订单" aria-label="采购需求按生产订单筛选" @change="search">
        <ElOption v-for="task in tasks" :key="task.id" :value="task.id" :label="`${task.task_number} · ${task.order_number}`" />
      </ElSelect>
      <ElButton @click="load">刷新</ElButton>
      <span>共 {{ total }} 条采购需求</span>
      <ElButton v-if="canAdd" type="primary" @click="router.push({ name: packaging ? 'packaging-purchase-create' : 'purchase-order-create' })">{{ packaging ? '新建包材采购' : '新建采购需求' }}</ElButton>
    </div>
    <ElAlert v-if="optionsError" type="warning" :title="optionsError" :closable="false"><ElButton link @click="loadOptions">重试选项</ElButton></ElAlert>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" :closable="false"><ElButton link @click="load">重新加载</ElButton></ElAlert>
    <ElAlert v-if="deleteError" type="error" :title="deleteError" @close="deleteError = ''" />
    <div v-loading="loading" v-horizontal-overflow class="group-table-frame scroll-actions-container">
      <table class="group-table">
        <colgroup>
          <col style="width: 160px"><col style="width: 150px"><col style="width: 180px"><col style="width: 160px">
          <col style="width: 170px"><col style="width: 110px"><col style="width: 100px"><col style="width: 115px">
          <col style="width: 170px"><col style="width: 130px"><col style="width: 65px"><col style="width: 110px"><col style="width: 72px">
        </colgroup>
        <thead><tr><th>生产任务单号</th><th>采购需求单号</th><th>产品</th><th>规格</th><th>颜色</th><th>材质</th><th>订单量</th><th>订单交期</th><th>总采购进度</th><th>材料进度</th><th>批次</th><th>状态</th><th class="scroll-actions-cell">操作</th></tr></thead>
        <tbody><tr v-for="{ row, products, totalPercent, batchCount, hasConfirmedBatch, deletionBlock } in displayRows" :key="row.id">
          <td><strong>{{ row.production_task_number_snapshot || '—' }}</strong></td>
          <td>{{ row.group_number }}<small v-if="row.combined_into_group_id">已并入合并需求</small></td>
          <td class="product-values">{{ products.name }}</td>
          <td class="product-values">{{ products.specification }}</td>
          <td class="product-values">{{ products.color }}</td>
          <td class="product-values">{{ products.material }}</td>
          <td class="product-values">{{ products.quantity }}</td>
          <td>{{ row.order_delivery_date || '—' }}</td>
          <td data-testid="purchase-group-total-progress"><div v-if="totalPercent !== null" class="total-progress"><ElProgress :percentage="totalPercent" :show-text="false" :stroke-width="10" :status="row.progress.status === 'COMPLETED' ? 'success' : undefined" :aria-label="`总采购进度 ${totalPercent}%`" /><span>{{ totalPercent }}%</span></div><span v-else class="unknown">待核对</span></td>
          <td>{{ row.progress.satisfied_line_count }} / {{ row.progress.line_count }} 项达标</td><td>{{ batchCount }}</td>
            <td>{{ statusLabels[row.display_status ?? row.progress.status] }}</td>
          <td class="scroll-actions-cell"><div class="group-actions">
            <ElDropdown trigger="click" placement="bottom-end" :persistent="false" @command="handleRowAction($event, row)">
              <ElButton link class="row-more-button" data-testid="group-more" :aria-label="`${row.group_number}的更多操作`" :loading="deletingId === row.id">
                更多<ElIcon><ArrowDown /></ElIcon>
              </ElButton>
              <template #dropdown><ElDropdownMenu>
                <ElDropdownItem command="view" data-testid="group-view">查看</ElDropdownItem>
                <ElDropdownItem command="sheets" data-testid="group-sheets" :disabled="!hasConfirmedBatch" :title="hasConfirmedBatch ? undefined : '确认采购批次后可查看采购表格'">采购表格</ElDropdownItem>
                <ElDropdownItem v-if="canDelete" command="remove" data-testid="group-remove" divided
                  :disabled="Boolean(deletionBlock || deletingId)" :title="deletionBlock || undefined">删除</ElDropdownItem>
              </ElDropdownMenu></template>
            </ElDropdown>
          </div></td>
        </tr><tr v-if="!loading && !rows.length"><td colspan="13" class="empty">{{ errorMessage ? '未能加载采购需求' : '暂无采购需求' }}</td></tr></tbody>
      </table>
    </div>
    <ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="search" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/procurementGroups';
@use '@/styles/theme/detail' as detail;
.product-values { white-space: pre-line; }
.group-list { @include detail.surface; padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 14px; min-height: 0; }
.group-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.group-toolbar .el-select { width: 280px; }
.group-toolbar > span { flex: 1; color: var(--erp-color-text-secondary); font-size: 12px; }
.group-table { min-width: 1692px; width: 100%; }
.group-table .scroll-actions-cell { padding-inline: 8px; text-align: center; }
.group-actions { display: flex; justify-content: center; }
.row-more-button { height: 32px; color: var(--erp-table-text); }
.row-more-button .el-icon { margin-left: 3px; }
.total-progress { display: grid; grid-template-columns: 80px 44px; align-items: center; gap: 8px; }
.total-progress > span { text-align: right; font-variant-numeric: tabular-nums; }
</style>
