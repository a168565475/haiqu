<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import backIcon from '@/assets/procurement/create-back.svg'
import rightIcon from '@/assets/procurement/create-right.svg'
import { fetchPurchaseSheetOptions, generatePurchaseSheets } from '@/api/purchaseOrders'
import { useAuthStore } from '@/stores/auth'
import type { PurchaseSheetOptions } from '@/types/purchaseOrder'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const generating = ref(false)
const loadError = ref('')
const actionError = ref('')
const data = ref<PurchaseSheetOptions | null>(null)
const selections = reactive<Record<string, string>>({})
const canGenerate = computed(() => auth.user?.is_superuser || auth.moduleCan('access_control.generate_purchasesheets', 'procurement.add_purchaseorder'))
const templateIds = computed(() => new Set(data.value?.templates.map(item => item.version_id) || []))
const selectedCount = computed(() => data.value?.suppliers.filter(group => templateIds.value.has(selections[group.supplier_id] || '')).length || 0)
const emptyReason = computed(() => {
  if (!data.value || data.value.existing_sheet_count) return ''
  if (!data.value.suppliers.length) return '暂无可生成采购表的供应商，请返回确认采购明细。'
  if (!data.value.templates.length) return '暂无可用采购合同模板，请先管理模板。'
  return ''
})

function money(value: string | null): string {
  if (value === null || value.trim() === '') return '—'
  const amount = Number(value)
  return Number.isFinite(amount) ? amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) : '—'
}
function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const fieldError = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return fieldError || response?.data?.error?.message || response?.data?.detail || fallback
}
async function load(): Promise<void> {
  if (loading.value || generating.value) return
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  try {
    const result = await fetchPurchaseSheetOptions(String(route.params.id || ''))
    data.value = result
    for (const key of Object.keys(selections)) delete selections[key]
    for (const group of result.suppliers) {
      const recommended = group.recommended_template_version_id
      selections[group.supplier_id] = recommended && result.templates.some(item => item.version_id === recommended)
        ? recommended : result.templates[0]?.version_id || ''
    }
  } catch (error) {
    loadError.value = apiErrorMessage(error, '模板选择信息加载失败。')
  } finally {
    loading.value = false
  }
}
function backToConfirm(): void {
  void router.push({ name: 'purchase-order-confirm', params: { id: route.params.id } })
}
function openWorkbench(): void {
  if (data.value) void router.push({ name: 'supplier-purchase-sheets', query: { purchase_order_id: data.value.purchase_order.id } })
}
async function generate(): Promise<void> {
  if (!data.value || loading.value || generating.value || loadError.value || data.value.existing_sheet_count || !canGenerate.value) return
  actionError.value = ''
  if (emptyReason.value || selectedCount.value !== data.value.suppliers.length) {
    actionError.value = emptyReason.value || '请为每家供应商选择采购合同模板。'
    ElMessage.warning(actionError.value)
    return
  }
  generating.value = true
  try {
    await generatePurchaseSheets(data.value.purchase_order.id, data.value.suppliers.map(item => ({
      supplier_id: item.supplier_id, template_version_id: selections[item.supplier_id] || '',
    })))
    // 成功后立即切换到已生成状态，避免跳转完成前重复提交。
    data.value.existing_sheet_count = data.value.suppliers.length
    ElMessage.success('供应商采购表已生成。')
    openWorkbench()
  } catch (error) {
    actionError.value = apiErrorMessage(error, '采购表生成失败。')
    ElMessage.error(actionError.value)
  } finally {
    generating.value = false
  }
}
onMounted(() => void load())
</script>

<template>
  <section v-loading="loading" class="template-select-page" data-testid="purchase-template-page">
    <header class="page-heading">
      <div><h1>选择采购合同模板</h1><p>为每家供应商选择模板，生成独立采购表。</p></div>
      <ElButton class="back-button" :disabled="generating" @click="backToConfirm"><img :src="backIcon" alt="" class="purchase-icon" />返回确认</ElButton>
    </header>
    <section v-if="loadError" class="load-error" role="alert"><ElAlert :title="loadError" type="error" :closable="false" show-icon /><ElButton @click="load">重新加载</ElButton></section>
    <template v-else-if="data">
      <section class="order-bar">
        <div><span>采购单号</span><div class="order-identity"><strong :title="data.purchase_order.order_number">{{ data.purchase_order.order_number }}</strong><ElTag effect="dark" :class="{ 'is-completed': data.purchase_order.status === 'COMPLETED' }">{{ data.purchase_order.status_display }}</ElTag></div></div>
        <div><span>{{ data.purchase_order.source_type === 'SAMPLE' ? '打样单号' : '订单编号' }}</span><strong>{{ (data.purchase_order.source_type === 'SAMPLE' ? data.purchase_order.source_number : data.purchase_order.sales_order_number) || '—' }}</strong></div>
        <div><span>供应商</span><strong>{{ data.suppliers.length }} 家</strong></div>
        <div class="order-total"><span>采购总金额</span><strong>¥{{ money(data.purchase_order.total_amount) }}</strong></div>
      </section>
      <section class="supplier-section">
        <header><h2>供应商与合同模板</h2><span>共 {{ data.suppliers.length }} 家供应商</span></header>
        <div class="supplier-scroll">
          <ElAlert v-if="emptyReason" class="state-alert" type="warning" :closable="false" show-icon :title="emptyReason" />
          <div class="supplier-grid">
            <article v-for="group in data.suppliers" :key="group.supplier_id" class="supplier-card" :data-supplier-id="group.supplier_id">
              <header>
                <div class="supplier-identity"><strong :title="group.supplier_name">{{ group.supplier_name }}</strong><span>{{ group.supplier_number }}</span></div>
                <div class="supplier-total"><strong>¥{{ money(group.total_amount) }}</strong><span>{{ group.line_count }} 行采购明细</span></div>
              </header>
              <div class="template-field">
                <label :for="`template-${group.supplier_id}`">采购合同模板</label>
                <ElSelect :id="`template-${group.supplier_id}`" v-model="selections[group.supplier_id]" filterable clearable placeholder="请选择模板" :disabled="generating || !!data.existing_sheet_count || !canGenerate" :aria-label="`${group.supplier_name}的采购合同模板`">
                  <ElOption v-for="template in data.templates" :key="template.version_id" :label="`${template.template_name} · ${template.version_name}`" :value="template.version_id" />
                </ElSelect>
              </div>
            </article>
          </div>
          <p v-if="actionError" class="action-error" role="alert">{{ actionError }}</p>
        </div>
      </section>
      <footer class="action-bar">
        <div class="selection-summary">已选模板 <strong>{{ selectedCount }} / {{ data.suppliers.length }}</strong><span>·</span> 将按供应商分别生成。</div>
        <div class="footer-actions">
          <span v-if="!canGenerate && !data.existing_sheet_count" class="permission-hint">暂无生成采购表权限</span>
          <ElButton class="manage-button" :disabled="generating" @click="router.push({ name: 'purchase-contract-templates' })">管理模板</ElButton>
          <ElButton v-if="data.existing_sheet_count" type="primary" class="generate-button" @click="openWorkbench">进入采购表工作台</ElButton>
          <ElButton v-else type="primary" class="generate-button" data-testid="generate-sheets" :loading="generating" :disabled="!canGenerate || !!emptyReason" @click="generate">生成 {{ data.suppliers.length }} 张采购表<img :src="rightIcon" alt="" class="purchase-icon" /></ElButton>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as crm;
.template-select-page { height: calc(100dvh - 92px); min-width: 0; min-height: 0; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden; color: crm.$crm-text-primary; background: crm.$crm-color-page; font-family: crm.$crm-font-body; font-size: 13px; --el-color-primary: #{crm.$crm-primary}; --el-border-color: #{crm.$crm-border-default}; --el-fill-color-blank: #{crm.$crm-color-surface}; --el-text-color-regular: #{crm.$crm-text-primary}; --el-text-color-placeholder: #{crm.$crm-text-muted}; --el-border-radius-base: 5px; }
.purchase-icon { width: 16px; height: 16px; flex: none; }
.template-select-page :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 10px; }
.page-heading { flex: 0 0 46px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.page-heading > div { display: flex; align-items: center; gap: 20px; }
.page-heading h1 { margin: 0; font: 700 34px/44px crm.$crm-font-display; letter-spacing: -1px; }
.page-heading p { margin: 0; color: crm.$crm-text-secondary; font-size: 13px; }
.back-button { width: 110px; height: 32px; border-color: crm.$crm-primary; }
.order-bar { flex: 0 0 76px; display: grid; grid-template-columns: minmax(0,1.2fr) minmax(0,1fr) minmax(0,.7fr) minmax(0,1fr); box-shadow: inset 0 0 0 1px crm.$crm-border-default; border-radius: 5px; background: crm.$crm-color-surface; margin-bottom: 20px; }
.order-bar > div { display: flex; flex-direction: column; justify-content: flex-start; gap: 4px; margin: 12px 0; padding: 0 18px; border-right: 1px solid crm.$crm-border-subtle; min-width: 0; }
.order-bar > div:last-child { border: 0; }
.order-bar > div > span { color: crm.$crm-text-secondary; line-height: 22px; }
.order-bar strong { font-size: 16px; font-weight: 500; line-height: 26px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.order-identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.order-identity strong { min-width: 0; }
.order-identity :deep(.el-tag) { flex: none; min-width: 56px; height: 24px; padding: 0 8px; border: 0; border-radius: 999px; font: 500 12px/18px crm.$crm-font-body; background: var(--erp-tag-info-background); color: var(--erp-color-text-inverse); }
.order-identity :deep(.el-tag.is-completed) { background: var(--erp-tag-success-background); }
.order-total strong { color: crm.$crm-primary; font-size: 22px; }
.supplier-section { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.supplier-section > header { display: flex; align-items: center; justify-content: space-between; flex: 0 0 28px; margin-bottom: 12px; }
.supplier-section h2 { margin: 0; font-size: 18px; line-height: 28px; }
.supplier-section > header > span { padding-right: 0; color: crm.$crm-text-secondary; font-size: 14px; }
.supplier-scroll { flex: 1; min-height: 0; overflow-y: auto; padding-bottom: 12px; }
.supplier-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
.supplier-card { height: 124px; box-sizing: border-box; padding: 12px 16px; background: crm.$crm-color-surface; border-radius: 5px; box-shadow: inset 0 0 0 1px crm.$crm-border-default; }
.supplier-card > header { display: flex; justify-content: space-between; height: 48px; box-sizing: border-box; border-bottom: 1px solid crm.$crm-border-default; gap: 16px; }
.supplier-card header > div { display: flex; flex-direction: column; gap: 0; min-width: 0; }
.supplier-identity { flex: 1; }
.supplier-identity strong { font-size: 16px; line-height: 24px; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
.supplier-card header span { color: crm.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.supplier-total { flex: 0 0 auto; max-width: 40%; text-align: right; }
.supplier-total strong { font-size: 20px; font-weight: 500; line-height: 24px; color: crm.$crm-primary; white-space: nowrap; }
.template-field { display: flex; align-items: center; gap: 12px; padding-top: 12px; }
.template-field label { flex: 0 0 84px; font-size: 14px; color: crm.$crm-text-secondary; line-height: 22px; }
.template-field :deep(.el-select) { flex: 1; min-width: 0; }
.template-field :deep(.el-select__wrapper) { height: 32px; min-height: 32px; padding: 0 12px; background: var(--erp-input-surface); font-size: 13px; }
.template-field :deep(.el-select__wrapper.is-disabled) { background: var(--erp-color-disabled); box-shadow: 0 0 0 1px var(--erp-control-border) inset; }
.action-bar { flex: 0 0 64px; display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 0 -28px; padding: 0 28px; background: crm.$crm-color-surface; }
.selection-summary { display: flex; align-items: center; gap: 10px; font-size: 14px; white-space: nowrap; }
.selection-summary strong { color: crm.$crm-primary; font-weight: 500; min-width: 48px; }
.footer-actions { display: flex; align-items: center; gap: 18px; }
.footer-actions :deep(.el-button) { height: 32px; margin: 0; font-size: 13px; }
.manage-button { width: 116px; color: crm.$crm-primary; border-color: crm.$crm-primary; }
.generate-button { width: 176px; }
.permission-hint, .action-error { color: crm.$crm-danger; font-size: 14px; }
.state-alert { margin-bottom: 12px; padding: 8px 12px; }
.load-error { display: flex; align-items: center; gap: 20px; padding: 24px; background: crm.$crm-color-surface; }
</style>
