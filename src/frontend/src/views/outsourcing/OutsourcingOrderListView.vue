<script setup lang="ts">
import { formatOutsourcingMoney } from '@/utils/outsourcingPrices'
import { computed, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { MoreFilled, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { deleteOutsourcingOrder, fetchOutsourcingOrder, revokeDispatchedOutsourcingOrder } from '@/api/outsourcing'
import { fetchUnifiedOutsourcingOptions, fetchUnifiedOutsourcingOrders, unifiedOutsourcingDetailPath } from '@/api/unifiedOutsourcing'
import OutsourcingPrintDialog from '@/components/outsourcing/OutsourcingPrintDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import MetalProcessingP4View from './MetalProcessingP4View.vue'
import { useAuthStore } from '@/stores/auth'
import type { UnifiedOutsourcingOptions, UnifiedOutsourcingOrder, UnifiedOutsourcingStatus } from '@/types/unifiedOutsourcing'
import type { OutsourcingPrintKind } from '@/types/outsourcingPrint'
import { createClientUuid } from '@/utils/clientUuid'
import { unifiedProductAttribute, unifiedQuantityText } from '@/utils/unifiedOutsourcingDisplay'

const rows = ref<UnifiedOutsourcingOrder[]>([])
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const hasPermission = (permission: string) => Boolean(auth.user?.is_superuser || auth.hasPermission(permission))
const warehouseWorkspace = computed(() => route.meta?.outsourcingWorkspace === 'warehouse')
const canViewWarehouse = computed(() => ['outsourcing.confirm_dispatch_outsourcingorder', 'outsourcing.confirm_return_outsourcingorder', 'outsourcing.return_raw_outsourcingorder', 'material_issues.confirm_metalprocessingexternalreturn'].some(hasPermission))
const canViewSources = computed(() => !warehouseWorkspace.value && hasPermission('material_issues.view_metalprocessingsource'))
const canViewRegularOrders = computed(() => hasPermission('outsourcing.view_outsourcingorder'))
const canViewList = computed(() => warehouseWorkspace.value ? canViewWarehouse.value : canViewRegularOrders.value)
const canViewOrders = computed(() => canViewSources.value || canViewList.value)
const canCreateOriginal = computed(() => !warehouseWorkspace.value && hasPermission('outsourcing.add_outsourcingorder'))
const canViewFactories = computed(() => !warehouseWorkspace.value && hasPermission('outsourcing.view_outsourcingfactory'))
const options = ref<UnifiedOutsourcingOptions | null>(null)
const activeTab = computed(() => {
  if (warehouseWorkspace.value) return 'orders'
  if (route.query.tab === 'sources' && canViewSources.value) return 'sources'
  if (!canViewRegularOrders.value && canViewSources.value) return 'sources'
  return 'orders'
})
const total = ref<number | null>(null)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const actingOrderId = ref('')
const printRequest = ref<{ row: UnifiedOutsourcingOrder; kind: OutsourcingPrintKind } | null>(null)
const loadError = ref('')
const accessDenied = ref(false)
const search = ref('')
const status = ref('')
const craftId = ref('')
const factoryId = ref('')
const sourceKind = ref('')
const appliedFactoryId = ref('')
let requestSequence = 0

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) return fallback
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || fallback
}

function craftTone(name: string): string {
  return ({ 车缝: 'sewing', 裁剪: 'cutting', 喷塑: 'spray', 丝印: 'printing' } as Record<string, string>)[name] || 'neutral'
}

function statusTone(value: UnifiedOutsourcingStatus): string {
  return ({ PENDING_DISPATCH: 'pending', PENDING_HANDOFF: 'pending', PROCESSING: 'processing', PARTIAL_RETURN: 'partial', COMPLETED: 'completed', CLOSED: 'cancelled', CANCELLED: 'cancelled' })[value]
}

function sourceLabel(row: UnifiedOutsourcingOrder): string {
  return row.source_kind === 'RAW' ? '原材料' : row.source_label
}

function productName(row: UnifiedOutsourcingOrder): string {
  const name = row.product.product_name || '—'
  return row.product_count > 1 ? `${name}等${row.product_count}款` : name
}

function factoryName(row: UnifiedOutsourcingOrder): string {
  const name = row.factory_names[0] || '—'
  return row.factory_count > 1 ? `${name}等${row.factory_count}家` : name
}

function hasShortage(row: UnifiedOutsourcingOrder): boolean {
  return row.record_type === 'TUBE' && row.receipt_state === 'RECORDED' && Boolean(row.shortage_quantities?.some(amount => Number(amount.quantity) > 0))
}

function openTubeCreate(category?: 'cutting'): void {
  if (canCreateOriginal.value && canViewOrders.value && !accessDenied.value) void router.push(category === 'cutting' ? '/workshop/outsourcing/tube/new?category=cutting' : '/workshop/outsourcing/tube/new')
}

function switchTab(tab: 'orders' | 'sources'): void {
  if (tab === 'orders' && !canViewRegularOrders.value) return
  if (tab === 'sources' && !canViewSources.value) return
  const query = { ...route.query }
  if (tab === 'sources') query.tab = 'sources'
  else delete query.tab
  void router.replace({ path: '/workshop/outsourcing', query })
}

async function loadOptions(): Promise<void> {
  if (activeTab.value !== 'orders' || !canViewList.value) return
  try {
    options.value = await fetchUnifiedOutsourcingOptions(warehouseWorkspace.value)
  } catch (error) {
    ElMessage.error(errorText(error, '委外筛选项加载失败。'))
  }
}

async function load(): Promise<void> {
  if (activeTab.value !== 'orders' || !canViewList.value) return
  const current = ++requestSequence
  loading.value = true
  loadError.value = ''
  accessDenied.value = false
  rows.value = []
  total.value = null
  appliedFactoryId.value = factoryId.value
  try {
    const result = await fetchUnifiedOutsourcingOrders({
      page: page.value,
      page_size: pageSize.value,
      search: search.value.trim() || undefined,
      status: status.value || undefined,
      craft_id: craftId.value || undefined,
      factory_id: factoryId.value || undefined,
      source_group: sourceKind.value || undefined,
      warehouse_stage: warehouseWorkspace.value ? 'all' : undefined,
    })
    if (current !== requestSequence) return
    rows.value = result.data
    total.value = result.meta.total
    const lastPage = Math.max(1, Math.ceil(result.meta.total / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; await load() }
  } catch (error) {
    if (current !== requestSequence) return
    rows.value = []
    total.value = null
    accessDenied.value = error instanceof AxiosError && error.response?.status === 403
    loadError.value = errorText(error, '外发单列表加载失败，请稍后重试。')
  } finally {
    if (current === requestSequence) loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  search.value = ''; status.value = ''; craftId.value = ''; factoryId.value = ''; sourceKind.value = ''
  applyFilters()
}

function openDetail(row: UnifiedOutsourcingOrder): void {
  void router.push(unifiedOutsourcingDetailPath(row, warehouseWorkspace.value))
}

function openWarehouseAction(row: UnifiedOutsourcingOrder, action: 'dispatch' | 'return'): void {
  if (!warehouseWorkspace.value || loading.value || accessDenied.value || !row.warehouse_actions?.includes(action)) return
  const target = unifiedOutsourcingDetailPath(row, true)
  if (action === 'return' && row.record_type === 'TUBE') {
    void router.push(`${target}/return`)
    return
  }
  void router.push(`${target}${target.includes('?') ? '&' : '?'}action=${action}`)
}

function canPrintRow(row: UnifiedOutsourcingOrder): boolean {
  return canViewList.value && (row.record_type === 'TUBE' || (row.record_type === 'ORIGINAL' && row.detail_access === 'REGULAR'))
}

function canPrintSpray(row: UnifiedOutsourcingOrder): boolean {
  return canPrintRow(row) && row.record_type === 'TUBE' && ['RAW_PIPE', 'PUBLIC_SEMI', 'TUBE_METAL'].includes(row.source_kind)
}

function openPrint(row: UnifiedOutsourcingOrder, kind: OutsourcingPrintKind): void {
  if (loading.value || accessDenied.value || printRequest.value || !canPrintRow(row) || (kind === 'spray' && !canPrintSpray(row))) return
  printRequest.value = { row, kind }
}

function canRemoveRow(row: UnifiedOutsourcingOrder): boolean {
  return row.record_type === 'ORIGINAL' && row.detail_access === 'REGULAR' && !row.direct_handoff && row.source_kind !== 'METAL' && (warehouseWorkspace.value ? row.can_revoke_dispatched : row.can_delete)
}

function handleRowCommand(command: string, row: UnifiedOutsourcingOrder): void {
  if (command === 'detail') openDetail(row)
  if (command === 'print-processing') openPrint(row, 'processing')
  if (command === 'print-spray') openPrint(row, 'spray')
  if (command === 'remove' && canRemoveRow(row)) void removeRow(row)
}

async function removeRow(row: UnifiedOutsourcingOrder): Promise<void> {
  if (loading.value || actingOrderId.value || !canRemoveRow(row)) return
  actingOrderId.value = row.id
  try {
    const latest = await fetchOutsourcingOrder(row.id, warehouseWorkspace.value)
    if (latest.data.direct_handoff || !latest.etag || (warehouseWorkspace.value ? !latest.data.can_revoke_dispatched : !latest.data.can_delete)) {
      ElMessage.warning('当前外发单已不能删除，请核对最新状态。')
      await load()
      return
    }
    if (!warehouseWorkspace.value && latest.data.can_delete) {
      await ElMessageBox.confirm('删除后外发单及其产品、加工分配和材料计划将永久移除，无法恢复。', '删除外发单', {
        confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning', customClass: 'outsourcing-confirm-dialog',
      })
      await deleteOutsourcingOrder(row.id, latest.etag)
      ElMessage.success('外发单已永久删除，加工额度已释放。')
    } else {
      const { value } = await ElMessageBox.prompt(
        latest.data.stock_mode === 'PUBLIC_V2'
          ? '仅未投入、未损耗、未回货的外发单可撤销。未用原料将退回原库区的公共库存，并恢复本订单可外发数量。请填写撤销原因。'
          : '仅未投入、未损耗、未回货的外发单可撤销。确认后将未用原料退回原发料批次与库区；单据保留为已取消。请填写撤销原因。',
        '撤销已发料外发单',
        {
          confirmButtonText: '确认撤销并退料', cancelButtonText: '取消', type: 'warning',
          inputType: 'textarea', inputPlaceholder: '请输入撤销原因',
          inputValidator: input => input.trim().length > 0 && input.trim().length <= 500 || '撤销原因须为 1 至 500 字。',
          customClass: 'outsourcing-confirm-dialog',
        },
      )
      await revokeDispatchedOutsourcingOrder(row.id, value.trim(), createClientUuid(), latest.etag)
      ElMessage.success(latest.data.stock_mode === 'PUBLIC_V2' ? '外发单已撤销，原料已退回原库区公共库存。' : '外发单已撤销，原料已退回原批次库存。')
    }
    await load()
    if (!loadError.value && page.value > Math.max(1, Math.ceil((total.value ?? 0) / pageSize.value))) {
      page.value = Math.max(1, Math.ceil((total.value ?? 0) / pageSize.value))
      await load()
    }
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, '操作结果未确认，请刷新列表核对状态，勿重复提交。'))
  } finally {
    actingOrderId.value = ''
  }
}

watch([activeTab, warehouseWorkspace], ([value]) => { page.value = 1; if (value === 'orders') void Promise.all([load(), loadOptions()]) }, { immediate: true })
</script>

<template>
  <section class="outsourcing-page outsourcing-order-list-page erp-glass-list" data-testid="outsourcing-order-list-page">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="outsourcing-heading erp-list-heading">
      <div class="heading-title"><h1>{{ warehouseWorkspace ? '委外管理' : '委外加工' }}</h1><span>{{ warehouseWorkspace ? '办理发料、回货入库，跟踪委外状态' : '统一查看外发与回货' }}</span></div>
      <div v-if="activeTab === 'sources'" class="heading-actions"><RouterLink v-if="canViewFactories" class="secondary-action el-button erp-button-motion" to="/workshop/outsourcing/factories">加工厂管理</RouterLink><ElButton class="erp-button-motion" v-if="canCreateOriginal" type="primary" :disabled="!canViewOrders || accessDenied" @click="openTubeCreate()">新建管材外发单</ElButton><ElButton class="erp-button-motion" v-if="canCreateOriginal" type="primary" :disabled="!canViewOrders || accessDenied" @click="openTubeCreate('cutting')">新建裁片外发单</ElButton></div>
    </header>
    <nav v-if="!warehouseWorkspace" class="unified-outsourcing-tabs erp-list-tabs" role="tablist" aria-label="委外加工内容">
      <button v-if="canViewRegularOrders" id="outsourcing-orders-tab" role="tab" :aria-selected="activeTab === 'orders'" aria-controls="outsourcing-orders-panel" :class="{ 'is-active': activeTab === 'orders' }" @click="switchTab('orders')">外发单</button>
      <button v-if="canViewSources" id="outsourcing-sources-tab" role="tab" :aria-selected="activeTab === 'sources'" aria-controls="outsourcing-sources-panel" :class="{ 'is-active': activeTab === 'sources' }" @click="switchTab('sources')">待外发材料</button>
    </nav>
    <div v-if="activeTab === 'orders' && canViewList" class="outsourcing-filter-bar order-filter-bar unified-order-filter-bar erp-list-filters">
      <ElInput v-model="search" clearable aria-label="搜索外发单" placeholder="外发单号、任务单、产品名称、品号、货号" :disabled="!canViewOrders || accessDenied" @keyup.enter="applyFilters" />
      <ElSelect v-model="sourceKind" placeholder="全部材料来源" clearable aria-label="材料来源" :disabled="!canViewOrders || accessDenied || !options"><ElOption v-for="item in options?.source_groups || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="status" placeholder="全部状态" clearable aria-label="状态" :disabled="!canViewOrders || accessDenied || !options"><ElOption v-for="item in options?.statuses || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="craftId" placeholder="全部工艺" clearable aria-label="加工工艺" :disabled="!canViewOrders || accessDenied || !options"><ElOption v-for="item in options?.crafts || []" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
      <ElSelect v-model="factoryId" class="factory-picker" placeholder="全部加工厂" clearable filterable aria-label="加工厂" :disabled="!canViewOrders || accessDenied || !options"><ElOption v-for="item in options?.factories || []" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" :disabled="loading || !canViewOrders || accessDenied" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" :disabled="loading || !canViewOrders || accessDenied" @click="applyFilters">应用筛选</ElButton></div>
    </div>
    </section>
    <section v-if="activeTab === 'sources'" id="outsourcing-sources-panel" class="outsourcing-source-workspace outsourcing-page" role="tabpanel" aria-labelledby="outsourcing-sources-tab">
      <MetalProcessingP4View mode="sources" embedded @updated="load" />
    </section>
    <section v-else-if="canViewList" id="outsourcing-orders-panel" class="erp-list-data" :role="warehouseWorkspace ? undefined : 'tabpanel'" :aria-labelledby="warehouseWorkspace ? undefined : 'outsourcing-orders-tab'">
    <div class="list-toolbar erp-list-toolbar"><div class="heading-actions"><RouterLink v-if="canViewFactories" class="secondary-action el-button erp-button-motion" to="/workshop/outsourcing/factories">加工厂管理</RouterLink><ElButton class="erp-button-motion" v-if="canCreateOriginal" type="primary" :disabled="!canViewOrders || accessDenied" @click="openTubeCreate()">新建管材外发单</ElButton><ElButton class="erp-button-motion" v-if="canCreateOriginal" type="primary" :disabled="!canViewOrders || accessDenied" @click="openTubeCreate('cutting')">新建裁片外发单</ElButton></div><div class="list-description"><small v-if="appliedFactoryId">数量仅含所选加工厂 · 状态仍为整单</small></div><ElButton class="erp-button-motion" :icon="Refresh" :disabled="loading || !canViewOrders" @click="load">刷新</ElButton></div>
      <div class="d4-list-table-area erp-list-table-frame"><ElTable :data="rows" border height="100%" row-key="row_key" class="d4-list-table" @row-click="openDetail">
        <ElTableColumn prop="order_number" label="外发单号" width="170" show-overflow-tooltip><template #default="{ row }"><RouterLink class="order-number-link" :to="unifiedOutsourcingDetailPath(row, warehouseWorkspace)" @click.stop>{{ row.order_number }}</RouterLink></template></ElTableColumn>
        <ElTableColumn label="生产任务单" width="130" show-overflow-tooltip><template #default="{ row }">{{ row.production_task_number || '—' }}</template></ElTableColumn>
        <ElTableColumn label="产品名称" min-width="155" show-overflow-tooltip><template #default="{ row }"><span class="table-product">{{ productName(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="产品材质" width="95" class-name="outsourcing-product-material" show-overflow-tooltip><template #default="{ row }">{{ unifiedProductAttribute(row, 'material') }}</template></ElTableColumn>
        <ElTableColumn label="货号" width="85" show-overflow-tooltip><template #default="{ row }">{{ unifiedProductAttribute(row, 'item_number') }}</template></ElTableColumn>
        <ElTableColumn label="订单颜色" width="96" show-overflow-tooltip><template #default="{ row }">{{ unifiedProductAttribute(row, 'color_name') }}</template></ElTableColumn>
        <ElTableColumn label="材料来源" width="150"><template #default="{ row }"><span class="unified-source-tag erp-list-tag" :class="row.source_kind === 'RAW' ? 'erp-list-tag--info' : row.source_kind === 'METAL' ? 'erp-list-tag--success' : 'erp-list-tag--warning'" :title="sourceLabel(row)">{{ sourceLabel(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="加工工艺" width="96"><template #default="{ row }"><span v-if="row.craft.name" class="craft-tag erp-list-tag" :class="[`craft-${craftTone(row.craft.name)}`, row.craft.name === '车缝' ? 'erp-list-tag--brand' : row.craft.name === '裁剪' ? 'erp-list-tag--info' : row.craft.name === '喷塑' ? 'erp-list-tag--success' : row.craft.name === '丝印' ? 'erp-list-tag--warning' : 'erp-list-tag--neutral']">{{ row.craft.name }}</span><span v-else>—</span></template></ElTableColumn>
        <ElTableColumn label="加工厂" width="135" show-overflow-tooltip><template #default="{ row }"><span :title="row.factory_names.join('、')">{{ factoryName(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="计划加工金额（元）" width="155" align="right" class-name="outsourcing-planned-amount num"><template #default="{ row }">{{ row.detail_access === 'METAL' ? '—' : formatOutsourcingMoney(row.planned_amount) }}</template></ElTableColumn>
        <ElTableColumn label="发出数量" width="95" align="right" class-name="num" show-overflow-tooltip><template #default="{ row }">{{ unifiedQuantityText(row, 'sent') }}</template></ElTableColumn>
        <ElTableColumn label="回货数量" width="95" align="right" class-name="num" show-overflow-tooltip><template #header><ElTooltip content="新管材按最终实收支数；其他外发沿用原合格回货口径。" placement="top"><span>回货数量</span></ElTooltip></template><template #default="{ row }"><ElTooltip v-if="row.receipt_state === 'MISSING'" content="已结束，但最终凭证尚无法核对；不当作0回货。" placement="top"><span>—</span></ElTooltip><span v-else>{{ unifiedQuantityText(row, 'received') }}</span></template></ElTableColumn>
        <ElTableColumn label="管材差额" width="90" align="right" class-name="num" show-overflow-tooltip><template #header><ElTooltip content="只显示新管材最终登记后的实发减实收。面料等不同单位不相减。" placement="top"><span>管材差额</span></ElTooltip></template><template #default="{ row }"><span :class="{ brand: hasShortage(row) }">{{ unifiedQuantityText(row, 'shortage') }}</span></template></ElTableColumn>
        <ElTableColumn label="预计回货日" width="110" show-overflow-tooltip><template #default="{ row }">{{ row.delivery_date || '—' }}</template></ElTableColumn>
        <ElTableColumn label="状态" width="90"><template #default="{ row }"><span class="status-tag erp-list-tag" :class="[`status-${statusTone(row.status)}`, row.status === 'COMPLETED' ? 'erp-list-tag--success' : row.status === 'PROCESSING' ? 'erp-list-tag--info' : row.status === 'PARTIAL_RETURN' ? 'erp-list-tag--warning' : 'erp-list-tag--neutral']">{{ row.status_display }}</span></template></ElTableColumn>
        <ElTableColumn label="操作" :width="warehouseWorkspace ? 180 : 72" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions" @click.stop>
            <ElButton v-if="warehouseWorkspace && row.warehouse_actions?.includes('dispatch')" link type="primary" :disabled="loading || accessDenied" @click.stop="openWarehouseAction(row, 'dispatch')">发料</ElButton>
            <ElButton v-if="warehouseWorkspace && row.warehouse_actions?.includes('return')" link type="primary" :disabled="loading || accessDenied" @click.stop="openWarehouseAction(row, 'return')">入库</ElButton>
            <ElButton v-if="warehouseWorkspace" link @click.stop="openDetail(row)">详情</ElButton>
              <ElDropdown v-if="!warehouseWorkspace || canPrintRow(row) || canRemoveRow(row)" :persistent="false" trigger="click" placement="bottom-end" @command="(command: string) => handleRowCommand(command, row)">
                <ElButton link class="row-more-button" :icon="MoreFilled" :aria-label="`${row.order_number} 更多操作`" />
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem v-if="!warehouseWorkspace" command="detail">查看详情</ElDropdownItem>
                    <ElDropdownItem v-if="canPrintRow(row)" command="print-processing" :aria-label="`${row.order_number} 加工单打印`" :disabled="loading || Boolean(printRequest)">加工单打印</ElDropdownItem>
                    <ElDropdownItem v-if="canPrintSpray(row)" command="print-spray" :aria-label="`${row.order_number} 管材喷塑打印`" :disabled="loading || Boolean(printRequest)">管材喷塑打印</ElDropdownItem>
                    <ElDropdownItem v-if="canRemoveRow(row)" command="remove" :disabled="loading || Boolean(actingOrderId)" divided>{{ warehouseWorkspace ? '撤销并退料' : '删除' }}</ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
            </div>
          </template>
        </ElTableColumn>
        <template #empty><div class="d4-list-empty"><template v-if="!canViewOrders || accessDenied"><strong>{{ warehouseWorkspace ? '暂无委外管理操作权限' : '暂无委外加工查看权限' }}</strong><span>请联系管理员核对权限</span></template><template v-else-if="loading"><ElIcon class="is-loading"><Refresh/></ElIcon><strong>正在读取外发单</strong><span>读取完成后显示数量与状态</span></template><template v-else-if="loadError"><strong>外发单读取失败</strong><span>{{ loadError }}</span><ElButton class="erp-button-motion" @click="load">重新读取</ElButton></template><template v-else><strong>{{ search || sourceKind || status || craftId || factoryId ? '没有符合条件的外发单' : '暂无外发单' }}</strong><span>{{ warehouseWorkspace ? '可调整筛选条件；新建外发单后在此办理发料和入库' : '可调整筛选条件或新建管材、裁片外发单' }}</span></template></div></template>
      </ElTable></div>
      <footer class="outsourcing-pagination erp-list-footer"><span>{{ total === null ? '数量待读取' : `共 ${total} 条` }}</span><div v-if="total !== null" class="pagination"><ElSelect v-model="pageSize" class="page-size-picker" aria-label="每页条数" @change="page = 1; load()"><ElOption :value="20" label="20 条 / 页"/><ElOption :value="50" label="50 条 / 页"/></ElSelect><ElPagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" background @current-change="load" /></div><span v-else>页数 —</span></footer>
    </section>
    <ElResult v-if="!canViewOrders" icon="warning" :title="warehouseWorkspace ? '暂无委外管理操作权限' : '暂无委外加工查看权限'" />
    <OutsourcingPrintDialog v-if="printRequest" :record="printRequest.row" :kind="printRequest.kind" :warehouse="warehouseWorkspace" @close="printRequest = null" />
  </section>
</template>

<style lang="scss">@use '@/styles/outsourcing.scss'; @use '@/styles/unifiedOutsourcingList.scss';</style>
<style scoped lang="scss">
.row-actions { display: flex; align-items: center; justify-content: center; gap: 8px; }
.row-actions > .el-button + .el-button { margin-left: 0; }
.row-more-button { color: var(--erp-table-text); width: 36px; height: 32px; }
</style>
