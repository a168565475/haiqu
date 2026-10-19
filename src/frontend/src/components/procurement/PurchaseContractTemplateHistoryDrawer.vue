<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElButton, ElIcon } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { Close, InfoFilled } from '@element-plus/icons-vue'
import { fetchPurchaseContractTemplate } from '@/api/purchaseOrders'
import type { PurchaseContractTemplate } from '@/types/purchaseOrder'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ visible: boolean; templateId: string }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()
const auth = useAuthStore()
const canView = computed(() => Boolean(auth.user?.is_superuser || auth.moduleCan('procurement.view_purchasecontracttemplate', 'procurement.view_purchaseorder')))
const record = ref<PurchaseContractTemplate | null>(null)
const loading = ref(false)
const loadError = ref('')
let requestNumber = 0
let disposed = false
const versions = computed(() => [...(record.value?.versions || [])].sort((a, b) => b.version_number - a.version_number))
const versionCount = computed(() => record.value ? versions.value.length : '—')
const currentNumber = computed(() => record.value?.current_version?.version_number ?? record.value?.current_version_number ?? null)

function validateRecord(data: PurchaseContractTemplate, id: string): void {
  if (!data || data.id !== id || typeof data.template_name !== 'string' || !Array.isArray(data.versions)) throw new Error('版本记录格式异常，请重新加载。')
  const ids = new Set<string>()
  const numbers = new Set<number>()
  for (const version of data.versions) {
    if (!version || typeof version.id !== 'string' || !version.id || !Number.isInteger(version.version_number) || version.version_number < 1 || ids.has(version.id) || numbers.has(version.version_number)) throw new Error('版本记录格式异常，请重新加载。')
    for (const value of [version.version_name, version.change_summary, version.created_by_name, version.created_at]) {
      if (value != null && typeof value !== 'string') throw new Error('版本记录格式异常，请重新加载。')
    }
    ids.add(version.id)
    numbers.add(version.version_number)
  }
  if (data.current_version != null && (!ids.has(data.current_version.id) || !data.versions.some(version => version.id === data.current_version?.id && version.version_number === data.current_version.version_number))) throw new Error('当前版本信息异常，请重新加载。')
  if (data.current_version_number != null && (!Number.isInteger(data.current_version_number) || data.current_version_number < 0 || (data.current_version_number > 0 && !numbers.has(data.current_version_number)))) throw new Error('当前版本信息异常，请重新加载。')
  if (data.current_version && data.current_version_number != null && data.current_version.version_number !== data.current_version_number) throw new Error('当前版本信息异常，请重新加载。')
}

async function load(): Promise<void> {
  const request = ++requestNumber
  record.value = null
  loadError.value = ''
  loading.value = false
  if (!props.visible || disposed) return
  if (!canView.value || !props.templateId.trim()) {
    loadError.value = canView.value ? '缺少模板编号，无法加载版本记录。' : '没有采购查看权限。'
    return
  }
  const id = props.templateId
  loading.value = true
  try {
    const result = await fetchPurchaseContractTemplate(id)
    if (disposed || request !== requestNumber) return
    validateRecord(result.data, id)
    record.value = result.data
  } catch (error) {
    if (disposed || request !== requestNumber) return
    const response = (error as { response?: { status?: number } })?.response
    loadError.value = response?.status === 403 ? '没有采购查看权限，请联系管理员。' : response?.status === 404 ? '该模板已不存在，请返回列表刷新。' : error instanceof Error && /^(版本记录格式异常|当前版本信息异常)/.test(error.message) ? error.message : '版本记录加载失败，请重新加载。'
  } finally {
    if (!disposed && request === requestNumber) loading.value = false
  }
}

function close(): void {
  requestNumber++
  record.value = null
  loading.value = false
  emit('update:visible', false)
}
function beforeClose(done: () => void): void { close(); done() }
function formatDateTime(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

watch(() => [props.visible, props.templateId, canView.value], () => { void load() }, { immediate: true })
onBeforeRouteLeave(() => { close(); return true })
onBeforeRouteUpdate(() => { close(); return true })
onBeforeUnmount(() => { disposed = true; requestNumber++ })
</script>

<template>
  <AppWindowDialog :model-value="visible" title="采购合同模板 · 版本记录" :width="1268" class="purchase-template-history-drawer" modal-class="purchase-template-history-overlay" :show-close="false" :close-on-click-modal="false" :before-close="beforeClose" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <template #header>
      <div class="template-history-heading">
        <h2>采购合同模板 · 版本记录</h2>
        <p><span class="template-history-name" :title="record?.template_name">{{ record?.template_name || (loading ? '正在加载…' : '—') }}</span><span> · 当前版本 {{ currentNumber ? `V${currentNumber}` : '—' }} · 共 {{ versionCount }} 个版本</span></p>
      </div>
      <ElButton class="template-history-close" link :icon="Close" aria-label="关闭版本记录" @click="close" />
    </template>
    <div v-loading="loading" class="template-history-content" :aria-busy="loading">
      <div v-if="loadError" class="template-history-error" role="alert">{{ loadError }}<ElButton @click="load">重新加载</ElButton></div>
      <div class="template-history-table-card">
        <table class="template-history-table" aria-label="采购合同模板版本记录">
          <colgroup><col v-for="width in [134, 214, 434, 162, 252]" :key="width" :style="{ width: width / 1196 * 100 + '%' }" /></colgroup>
          <thead><tr><th v-for="label in ['版本', '版本名称', '变更内容', '维护人', '版本创建时间']" :key="label" scope="col">{{ label }}</th></tr></thead>
          <tbody>
            <tr v-for="version in versions" :key="version.id" class="template-history-row" :class="{ 'is-current': version.version_number === currentNumber }">
              <td><strong class="template-history-number">V{{ version.version_number }}</strong><span v-if="version.version_number === currentNumber" class="template-history-current">当前</span></td>
              <td><strong>{{ version.version_name || '未命名版本' }}</strong></td>
              <td class="template-history-summary">{{ version.change_summary || '—' }}</td>
              <td>{{ version.created_by_name || '—' }}</td><td>{{ formatDateTime(version.created_at) }}</td>
            </tr>
            <tr v-if="!versions.length"><td colspan="5" class="template-history-empty">{{ loading ? '正在加载版本记录…' : loadError ? '记录加载失败' : '暂无版本记录' }}</td></tr>
          </tbody>
        </table>
      </div>
      <p class="template-history-count">共 {{ versionCount }} 个版本</p>
    </div>
    <template #footer>
      <p class="template-history-notice"><ElIcon><InfoFilled /></ElIcon><span>保存当前模板会更新当前记录；保存为新版本才会新增记录。<br>已生成采购表保留原内容。</span></p>
      <ElButton @click="close">关闭</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.purchase-template-history-overlay { background: color-mix(in srgb, var(--erp-overlay-scrim-color) 46%, transparent); }
.purchase-template-history-drawer {
  max-width: 100vw; box-shadow: none; background: token.$crm-color-surface; color: token.$crm-text-primary; font: 18px/28px 'Noto Sans SC Variable', token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary};
  .app-window-dialog__header { flex: 0 0 166px; box-sizing: border-box; padding: 30px 36px 0; margin: 0; align-items: flex-start; color: inherit; gap: 24px; }
  .template-history-heading { min-width: 0; flex: 1; }
  h2 { margin: 0; font: 700 36px/48px 'Noto Serif SC Variable', token.$crm-font-display; }
  .template-history-heading p { display: flex; margin: 8px 0 0; color: token.$crm-text-secondary; white-space: nowrap; }
  .template-history-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .template-history-heading p > span:last-child { flex-shrink: 0; white-space: pre; }
  .template-history-close.el-button { position: absolute; top: 30px; right: 24px; width: 30px; height: 32px; padding: 0; font-size: 26px; color: token.$crm-text-secondary; }
  .app-window-dialog__body { padding: 0 36px 24px; overflow-y: auto; }
  .template-history-content { min-height: 330px; }
  .template-history-table-card { border: 1px solid token.$crm-border-default; border-radius: 4px; overflow: hidden; }
  .template-history-table { width: 100%; table-layout: fixed; border-collapse: collapse; }
  th, td { box-sizing: border-box; padding: 16px 23px; text-align: left; vertical-align: middle; overflow-wrap: anywhere; }
  th { height: 71px; background: var(--erp-table-header-fill); font-weight: 400; }
  th + th, td + td { border-left: 1px solid var(--erp-table-grid); }
  tbody tr { height: 80px; border-top: 1px solid var(--erp-table-grid); }
  tbody tr.is-current { height: 98px; background: var(--erp-color-selected); }
  strong { font-weight: 700; }
  .template-history-number { display: block; font-size: 22px; line-height: 28px; }
  .template-history-current { display: block; width: 64px; height: 30px; margin-top: 4px; border-radius: 5px; background: var(--erp-color-subtle); color: token.$crm-primary; text-align: center; font-size: 16px; line-height: 30px; }
  .template-history-summary { white-space: pre-wrap; }
  .template-history-count { margin: 24px 0 0; color: token.$crm-text-secondary; }
  .template-history-empty { height: 178px; text-align: center; color: token.$crm-text-secondary; }
  .template-history-error { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; margin-bottom: 16px; background: token.$crm-color-subtle; color: token.$crm-primary; }
  .app-window-dialog__footer { box-sizing: border-box; flex: 0 0 116px; padding: 24px 36px; border-top: 1px solid token.$crm-border-default; display: flex; gap: 24px; align-items: center; text-align: left; }
  .template-history-notice { display: flex; align-items: center; gap: 20px; flex: 1; margin: 0; font-size: 16px; line-height: 24px; }
  .template-history-notice .el-icon { font-size: 24px; color: token.$crm-text-muted; }
  .app-window-dialog__footer .el-button { height: 60px; width: 132px; margin: 0; font: 500 16px 'Noto Sans SC Variable', token.$crm-font-body; }
}
</style>

