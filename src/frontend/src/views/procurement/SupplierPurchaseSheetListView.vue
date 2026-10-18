<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref, watch } from 'vue'
import { VideoPlay, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { TableInstance } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import documentLockIcon from '@/assets/procurement/publish-document-lock.svg'
import {
  batchDownloadSupplierPurchaseSheets,
  batchPublishSupplierPurchaseSheets,
  downloadSupplierPurchaseSheetPdf,
  downloadSupplierPurchaseSheetXlsx,
  fetchSupplierPurchaseSheets,
} from '@/api/purchaseOrders'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { SupplierPurchaseSheet } from '@/types/purchaseOrder'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const downloading = ref(false)
const publishing = ref(false)
const publishConfirmVisible = ref(false)
const pendingPublishIds = ref<string[]>([])
const publishError = ref('')
const tableRef = ref<TableInstance>()
const rows = ref<SupplierPurchaseSheet[]>([])
const selected = ref<SupplierPurchaseSheet[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loadError = ref('')
const purchaseOrderId = computed(() => String(route.query.purchase_order_id || ''))
const publishedSelected = computed(() => selected.value.filter((item) => item.status === 'PUBLISHED'))
const draftSelected = computed(() => selected.value.filter((item) => item.status === 'DRAFT'))

const busy = computed(() => publishing.value || downloading.value || publishConfirmVisible.value)
const canPublish = computed(() => auth.user?.is_superuser || auth.moduleCan('procurement.publish_supplierpurchasesheet', 'procurement.submit_purchaseorder'))
const publishReady = computed(() => canPublish.value && !loading.value && !loadError.value && !busy.value && selected.value.length > 0 && selected.value.length <= 100 && draftSelected.value.length === selected.value.length)
const downloadReady = computed(() => !loading.value && !loadError.value && !busy.value && selected.value.length > 0 && publishedSelected.value.length === selected.value.length)
let loadSequence = 0

function updatedTime(value: string): string {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return '—'
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function money(value: string | null): string {
  if (value === null) return '待结算'
  if (!Number.isFinite(Number(value))) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
}

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const fieldError = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return fieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

async function load(): Promise<void> {
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = ''
  selected.value = []
  tableRef.value?.clearSelection()
  try {
    const result = await fetchSupplierPurchaseSheets({
      page: page.value,
      page_size: pageSize.value,
      purchase_order_id: purchaseOrderId.value || undefined,
      is_current: true,
    })
    if (sequence !== loadSequence) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (sequence !== loadSequence) return
    rows.value = []
    total.value = 0
    loadError.value = apiErrorMessage(error, '采购表加载失败。')
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function resetPageAndLoad(): void {
  if (busy.value) return
  page.value = 1
  void load()
}

function edit(row: SupplierPurchaseSheet): void {
  void router.push({ name: 'supplier-purchase-sheet-editor', params: { id: row.id } })
}

async function download(row: SupplierPurchaseSheet): Promise<void> {
  if (busy.value || row.status !== 'PUBLISHED') return
  downloading.value = true
  try {
    saveBlob(await downloadSupplierPurchaseSheetPdf(row.id), `${row.sheet_number}_V${row.version_number}.pdf`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'PDF 下载失败。'))
  } finally {
    downloading.value = false
  }
}

async function downloadXlsx(row: SupplierPurchaseSheet): Promise<void> {
  if (busy.value) return
  downloading.value = true
  try {
    saveBlob(await downloadSupplierPurchaseSheetXlsx(row.id), `${row.sheet_number}_V${row.version_number}.xlsx`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'Excel 下载失败。'))
  } finally {
    downloading.value = false
  }
}

async function batchDownload(): Promise<void> {
  if (!downloadReady.value) return
  if (!selected.value.length || publishedSelected.value.length !== selected.value.length) {
    ElMessage.warning('批量下载只能选择已发布采购表。')
    return
  }
  downloading.value = true
  try {
    saveBlob(await batchDownloadSupplierPurchaseSheets(publishedSelected.value.map((item) => item.id)), '供应商采购表.zip')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批量下载失败。'))
  } finally {
    downloading.value = false
  }
}

function openBatchPublish(): void {
  if (!publishReady.value) return
  pendingPublishIds.value = draftSelected.value.map((item) => item.id)
  publishError.value = ''
  publishConfirmVisible.value = true
}

function closePublishConfirm(): void {
  if (publishing.value) return
  publishConfirmVisible.value = false
  pendingPublishIds.value = []
  publishError.value = ''
}

function updatePublishConfirmVisible(value: boolean): void {
  if (!value) closePublishConfirm()
}

async function confirmBatchPublish(): Promise<void> {
  if (publishing.value || !pendingPublishIds.value.length) return
  const ids = [...pendingPublishIds.value]
  publishing.value = true
  publishError.value = ''
  try {
    const published = await batchPublishSupplierPurchaseSheets(ids)
    ElMessage.success(`已发布 ${published.length} 张供应商采购表。`)
    publishConfirmVisible.value = false
    pendingPublishIds.value = []
    await load()
  } catch (error) {
    publishError.value = apiErrorMessage(error, '批量发布失败，请检查采购表内容后重试。')
  } finally {
    publishing.value = false
  }
}

watch(purchaseOrderId, () => {
  page.value = 1
  void load()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="sheet-list-page erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="page-heading erp-list-heading">
      <h1>供应商采购表</h1>
      <span class="total-count">共 {{ total }} 张</span>
      <span class="heading-space" />
    </header>
    </section>

    <div v-if="loadError" class="load-error" role="alert"><span>{{ loadError }}</span><ElButton :disabled="loading || busy" @click="load">重新加载</ElButton></div>

    <section class="table-card erp-list-data">
      <div class="erp-list-toolbar">
      <div class="heading-actions">
        <ElButton class="manage-button erp-button-motion" :disabled="busy" @click="router.push({ name: 'purchase-contract-templates' })">模板管理</ElButton>
        <ElButton class="download-button erp-button-motion" data-testid="sheet-batch-download" :icon="Download" :loading="downloading" :disabled="!downloadReady" @click="batchDownload">批量下载</ElButton>
        <ElButton class="publish-button erp-button-motion" data-testid="sheet-batch-publish" type="primary" :icon="VideoPlay" :loading="publishing" :disabled="!publishReady" :title="canPublish ? '请选择1至100张草稿采购表' : '没有发布采购表权限'" @click="openBatchPublish">批量发布（{{ selected.length }}）</ElButton>
      </div>
        <div class="list-description"><h2>采购表清单</h2><span>{{ canPublish ? '草稿可编辑，发布后只读' : '当前账号没有发布权限' }}</span></div>
      </div>
      <div class="erp-list-table-frame">
      <ElTable ref="tableRef" v-loading="loading" :data="rows" height="100%" row-key="id" @selection-change="selected = $event">
        <ElTableColumn type="selection" width="46" align="center" header-align="center" :selectable="() => !busy && !loading" />
        <ElTableColumn label="采购表编号" width="214"><template #default="{ row }"><div class="stack"><strong>{{ row.sheet_number }}</strong><span>V{{ row.version_number }}</span></div></template></ElTableColumn>
        <ElTableColumn label="订单来源" width="160"><template #default="{ row }"><div class="stack"><strong>{{ row.content_snapshot?.order?.source_type === 'SAMPLE' ? row.content_snapshot.order.source_number : (row.is_historical_unlinked ? '历史未关联' : (row.sales_order_number || '—')) }}</strong><span>{{ row.content_snapshot?.order?.source_type === 'SAMPLE' ? '打样单' : (row.production_task_number || '—') }}</span></div></template></ElTableColumn>
        <ElTableColumn label="供应商" width="292"><template #default="{ row }"><div class="stack"><strong>{{ row.supplier_name_snapshot }}</strong><span>{{ row.supplier_number_snapshot }}</span></div></template></ElTableColumn>
        <ElTableColumn label="模板" width="210"><template #default="{ row }"><div class="stack"><strong>{{ row.template_name }}</strong><span>{{ row.template_version_name || '未命名版本' }}</span></div></template></ElTableColumn>
        <ElTableColumn label="金额" width="134" align="right" header-align="center"><template #default="{ row }"><strong>{{ money(row.total_amount) }}</strong></template></ElTableColumn>
        <ElTableColumn label="状态" width="112" align="center"><template #default="{ row }"><ElTag :class="{ published: row.status === 'PUBLISHED' }" :type="row.status === 'PUBLISHED' ? 'success' : 'info'">{{ row.status_display }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="更新信息" width="208"><template #default="{ row }"><div class="stack"><strong>{{ row.updated_by_name || '—' }}</strong><span>{{ updatedTime(row.updated_at) }}</span></div></template></ElTableColumn>
        <ElTableColumn label="操作" min-width="232" fixed="right" align="center"><template #default="{ row }"><ElButton :disabled="busy || loading" link type="primary" @click="edit(row)">{{ row.status === 'DRAFT' ? '编辑' : '查看' }}</ElButton><ElButton :disabled="busy || loading" link @click="downloadXlsx(row)">Excel</ElButton><ElButton v-if="row.status === 'PUBLISHED'" link @click="download(row)">PDF</ElButton></template></ElTableColumn>
        <template #empty><div class="empty"><strong>{{ loadError ? '采购表加载失败' : '暂无供应商采购表' }}</strong><span>{{ loadError ? '请重新加载后继续操作' : '请先确认采购订单并选择合同模板' }}</span></div></template>
      </ElTable>
      </div>
      <footer class="erp-list-footer"><span>已选择{{ selected.length }}张　·　草稿{{ draftSelected.length }}张　·　已发布{{ publishedSelected.length }}张</span><ElPagination :disabled="busy || loading" background v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="sizes, prev, pager, next" @current-change="load" @size-change="resetPageAndLoad" /></footer>
    </section>

    <AppWindowDialog
      :model-value="publishConfirmVisible"
      title="批量发布采购表"
      :width="560"
      :height="322"
      :close-on-click-modal="!publishing"
      :close-on-press-escape="!publishing"
      :show-close="!publishing"
      modal-class="supplier-purchase-batch-publish-overlay"
      class="batch-publish-dialog"
      destroy-on-close
      @update:model-value="updatePublishConfirmVisible"
    >
      <div class="batch-publish-dialog__body">
        <div class="batch-publish-dialog__count"><span>本次将发布</span><strong>{{ pendingPublishIds.length }}</strong><span>张供应商采购表</span></div>
        <div class="batch-publish-dialog__notice">
          <img :src="documentLockIcon" alt="" width="34" height="34" />
          <div><strong>发布后将生成正式 PDF</strong><p>当前版本将锁定为只读；如需修改，请创建新版本。</p></div>
        </div>
        <p v-if="publishError" class="batch-publish-dialog__error" role="alert">{{ publishError }}</p>
      </div>
      <template #footer>
        <div class="batch-publish-dialog__footer">
          <p>请确认数量无误后发布。</p>
          <div><ElButton :disabled="publishing" @click="closePublishConfirm">取消</ElButton><ElButton type="primary" :loading="publishing" :disabled="publishing || !pendingPublishIds.length" @click="confirmBatchPublish">确认发布</ElButton></div>
        </div>
      </template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as crm;
.total-count { color: var(--erp-color-text-secondary); white-space: nowrap; font-size: 12px; }
.heading-space { flex: 1; }
.heading-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.manage-button, .download-button { width: 110px; }
.publish-button { width: 176px; }
.load-error { padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; background: var(--erp-color-danger-soft); color: var(--erp-color-danger); flex: none; }
.list-description { display: flex; flex-wrap: wrap; align-items: center; margin-left: auto; gap: 12px; color: var(--erp-color-text-secondary); }
.list-description h2, .list-description span { margin: 0; font-size: 13px; font-weight: 400; }
.table-card :deep(.el-table-column--selection .cell) { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; padding: 0; }
.table-card :deep(.el-table-column--selection .el-checkbox) { display: inline-flex; align-items: center; justify-content: center; height: 100%; margin: 0; }
.stack { display: flex; flex-direction: column; gap: 0; line-height: 18px; }
.stack span { color: var(--erp-table-text); }
.table-card strong { font-weight: 500; }
.table-card :deep(.el-tag) { width: 68px; height: 24px; border-radius: var(--erp-radius-pill); font-size: 12px; }
.table-card :deep(.el-button.is-link) { font-size: 12px; }
.table-card :deep(.el-button.is-link + .el-button.is-link) { margin-left: 16px; }
.empty { min-height: 260px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--erp-color-text-secondary); }
.empty strong { color: var(--erp-color-text-primary); font-size: 20px; }
.batch-publish-dialog__body { display: flex; flex-direction: column; gap: 16px; }
.batch-publish-dialog__count { display: flex; height: 44px; align-items: baseline; gap: 8px; color: crm.$crm-text-regular; font-size: 14px; }
.batch-publish-dialog__count strong { color: crm.$crm-text-primary; font: 700 30px/40px crm.$crm-font-display; }
.batch-publish-dialog__notice { box-sizing: border-box; min-height: 82px; display: flex; align-items: center; gap: 16px; padding: 14px 16px; border: 1px solid crm.$crm-warning-border; border-radius: crm.$crm-radius-2; background: crm.$crm-warning-soft; }
.batch-publish-dialog__notice img { flex: none; width: 34px; height: 34px; }
.batch-publish-dialog__notice div { min-width: 0; }
.batch-publish-dialog__notice strong { color: crm.$crm-text-primary; font-size: 14px; line-height: 22px; }
.batch-publish-dialog__notice p, .batch-publish-dialog__error, .batch-publish-dialog__footer p { margin: 0; }
.batch-publish-dialog__notice p { margin-top: 2px; color: crm.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.batch-publish-dialog__error { color: crm.$crm-danger; font-size: 12px; line-height: 18px; overflow-wrap: anywhere; }
.batch-publish-dialog__footer { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.batch-publish-dialog__footer > p { color: crm.$crm-text-secondary; font-size: 12px; }
.batch-publish-dialog__footer > div { display: flex; gap: 10px; }
.batch-publish-dialog__footer :deep(.el-button) { min-width: 72px; margin: 0; }
</style>
