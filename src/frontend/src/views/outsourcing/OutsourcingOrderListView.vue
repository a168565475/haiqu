<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ArrowDown, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { deleteOutsourcingOrder, fetchOutsourcingOrder, revokeDispatchedOutsourcingOrder } from '@/api/outsourcing'
import { fetchP4Source, fetchP4Sources } from '@/api/metalProcessingP4'
import { fetchUnifiedOutsourcingOptions, fetchUnifiedOutsourcingOrders, unifiedOutsourcingDetailPath } from '@/api/unifiedOutsourcing'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import MetalProcessingP4View from './MetalProcessingP4View.vue'
import { useAuthStore } from '@/stores/auth'
import type { P4Rework, P4Source } from '@/types/metalProcessingP4'
import type { UnifiedOutsourcingOptions, UnifiedOutsourcingOrder, UnifiedOutsourcingStatus } from '@/types/unifiedOutsourcing'
import { createClientUuid } from '@/utils/clientUuid'
import { unifiedProductAttribute, unifiedQuantityText } from '@/utils/unifiedOutsourcingDisplay'

const rows = ref<UnifiedOutsourcingOrder[]>([])
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const hasPermission = (permission: string) => Boolean(auth.user?.is_superuser || auth.hasPermission(permission))
const canViewSources = computed(() => hasPermission('material_issues.view_metalprocessingsource'))
const canViewRegularOrders = computed(() => hasPermission('outsourcing.view_outsourcingorder'))
const canViewOrders = computed(() => canViewSources.value || canViewRegularOrders.value)
const canCreateOriginal = computed(() => hasPermission('outsourcing.add_outsourcingorder'))
const canCreateRework = computed(() => canViewSources.value && hasPermission('material_issues.create_metalprocessingexternalorder'))
const canCreate = computed(() => canCreateOriginal.value || canCreateRework.value)
const canViewFactories = computed(() => hasPermission('outsourcing.view_outsourcingfactory'))
const options = ref<UnifiedOutsourcingOptions | null>(null)
const activeTab = computed(() => {
  if (route.query.tab === 'sources' && canViewSources.value) return 'sources'
  if (!canViewRegularOrders.value && canViewSources.value) return 'sources'
  return 'orders'
})
const total = ref<number | null>(null)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const actingOrderId = ref('')
const loadError = ref('')
const accessDenied = ref(false)
const search = ref('')
const status = ref('')
const craftId = ref('')
const factoryId = ref('')
const sourceKind = ref('')
const appliedFactoryId = ref('')
const createVisible = ref(false)
const createSourceKind = ref<'RAW' | 'METAL' | 'REWORK'>('RAW')
const createSources = ref<P4Source[]>([])
const createSourceId = ref('')
const createSource = ref<P4Source | null>(null)
const createReworkId = ref('')
const sourceLoading = ref(false)
const sourceDetailLoading = ref(false)
const sourceError = ref('')
let requestSequence = 0
let sourceRequestSequence = 0
let sourceDetailSequence = 0
const selectableSources = computed(() => createSources.value.filter(item => createSourceKind.value !== 'METAL' || (item.status !== 'CLOSED' && item.available_pieces > 0)))
const selectableReworks = computed(() => (createSource.value?.original_handoffs || []).flatMap(handoff =>
  (handoff.unsprayed_returns || []).flatMap(returned => (returned.reworks || [])
    .filter(rework => rework.remaining_allocatable_pieces > 0)
    .map(rework => ({ ...rework, return_date: returned.return_date, returned_pieces: returned.returned_pieces }))),
))
const selectedRework = computed(() => selectableReworks.value.find(item => item.id === createReworkId.value))
const canContinueCreate = computed(() => {
  if (createSourceKind.value === 'RAW') return canCreateOriginal.value
  if (sourceLoading.value || sourceDetailLoading.value) return false
  if (!createSource.value || sourceError.value) return false
  if (createSourceKind.value === 'METAL') return canCreateOriginal.value && canViewSources.value && createSource.value.status !== 'CLOSED' && createSource.value.available_pieces > 0
  return canCreateRework.value && Boolean(selectedRework.value)
})

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

function openTubeCreate(): void {
  if (canCreateOriginal.value && canViewOrders.value && !accessDenied.value) void router.push('/workshop/outsourcing/tube/new')
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
  try {
    options.value = await fetchUnifiedOutsourcingOptions()
  } catch (error) {
    ElMessage.error(errorText(error, '委外筛选项加载失败。'))
  }
}

async function load(): Promise<void> {
  if (!canViewOrders.value) return
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
  void router.push(unifiedOutsourcingDetailPath(row))
}

function canRemoveRow(row: UnifiedOutsourcingOrder): boolean {
  return row.record_type === 'ORIGINAL' && row.detail_access === 'REGULAR' && !row.direct_handoff && row.source_kind !== 'METAL' && (row.can_delete || row.can_revoke_dispatched)
}

function handleRowCommand(command: string, row: UnifiedOutsourcingOrder): void {
  if (command === 'detail') openDetail(row)
  if (command === 'remove' && canRemoveRow(row)) void removeRow(row)
}

async function removeRow(row: UnifiedOutsourcingOrder): Promise<void> {
  if (loading.value || actingOrderId.value || !canRemoveRow(row)) return
  actingOrderId.value = row.id
  try {
    const latest = await fetchOutsourcingOrder(row.id)
    if (latest.data.direct_handoff || !latest.etag || (!latest.data.can_delete && !latest.data.can_revoke_dispatched)) {
      ElMessage.warning('当前外发单已不能删除，请核对最新状态。')
      await load()
      return
    }
    if (latest.data.can_delete) {
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

async function openCreate(): Promise<void> {
  if (!canCreate.value) return
  createSourceKind.value = canCreateOriginal.value ? 'RAW' : 'REWORK'
  createSourceId.value = ''; createSource.value = null; createReworkId.value = ''; sourceError.value = ''
  createVisible.value = true
  if (canViewSources.value) await loadCreateSources()
}

async function loadCreateSources(): Promise<void> {
  const current = ++sourceRequestSequence
  sourceLoading.value = true; sourceError.value = ''; createSources.value = []
  try {
    const results: P4Source[] = []
    let sourcePage = 1
    let totalSources = 0
    do {
      const result = await fetchP4Sources({ page: sourcePage, page_size: 100 })
      if (current !== sourceRequestSequence) return
      results.push(...result.data)
      totalSources = result.meta.total
      if (!result.data.length) break
      sourcePage += 1
    } while (results.length < totalSources)
    createSources.value = results
  } catch (error) {
    if (current === sourceRequestSequence) sourceError.value = errorText(error, '材料来源加载失败，请重试。')
  } finally {
    if (current === sourceRequestSequence) sourceLoading.value = false
  }
}

async function selectCreateSource(id: string): Promise<void> {
  const current = ++sourceDetailSequence
  createSource.value = null; createReworkId.value = ''; sourceError.value = ''
  if (!id) { sourceDetailLoading.value = false; return }
  sourceDetailLoading.value = true
  try {
    const result = await fetchP4Source(id)
    if (current === sourceDetailSequence) createSource.value = result
  } catch (error) {
    if (current === sourceDetailSequence) sourceError.value = errorText(error, '所选材料来源读取失败，请重新选择。')
  } finally {
    if (current === sourceDetailSequence) sourceDetailLoading.value = false
  }
}

function reworkLabel(rework: P4Rework & { return_date: string; returned_pieces: number }): string {
  return `退回 ${rework.return_date} · ${rework.returned_pieces} 支 / 加工 ${rework.completion_date} · 可分配 ${rework.remaining_allocatable_pieces} 支`
}

function continueCreate(): void {
  if (!canContinueCreate.value) return
  createVisible.value = false
  if (createSourceKind.value === 'RAW') {
    void router.push('/workshop/outsourcing/new')
  } else if (createSourceKind.value === 'METAL' && createSource.value) {
    void router.push({ path: '/workshop/outsourcing/new', query: { source_kind: 'METAL', source_issue_line_id: createSource.value.issue_line_id } })
  } else if (createSource.value && selectedRework.value) {
    void router.push({ path: '/workshop/outsourcing', query: { tab: 'sources', source_issue_line_id: createSource.value.issue_line_id, source_action: 'rework', rework_id: selectedRework.value.id } })
  }
}

watch(createSourceKind, () => {
  sourceDetailSequence += 1
  sourceDetailLoading.value = false
  createSourceId.value = ''; createSource.value = null; createReworkId.value = ''
})
watch(() => activeTab.value, value => { if (value === 'orders') void load() })
onMounted(() => { if (canViewRegularOrders.value) void Promise.all([load(), loadOptions()]) })
</script>

<template>
  <section class="outsourcing-page outsourcing-order-list-page erp-glass-list" data-testid="outsourcing-order-list-page">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="outsourcing-heading erp-list-heading">
      <div class="heading-title"><h1>委外加工</h1><span>统一查看外发与回货</span></div>
      <div v-if="activeTab === 'sources'" class="heading-actions"><RouterLink v-if="canViewFactories" class="secondary-action el-button erp-button-motion" to="/workshop/outsourcing/factories">加工厂管理</RouterLink><ElButton class="erp-button-motion" v-if="canCreate" :disabled="!canViewOrders || accessDenied" @click="openCreate">新建外发单</ElButton><ElButton class="erp-button-motion" v-if="canCreateOriginal" type="primary" :disabled="!canViewOrders || accessDenied" @click="openTubeCreate">新建管材外发单</ElButton></div>
    </header>
    <nav class="unified-outsourcing-tabs erp-list-tabs" role="tablist" aria-label="委外加工内容">
      <button v-if="canViewRegularOrders" id="outsourcing-orders-tab" role="tab" :aria-selected="activeTab === 'orders'" aria-controls="outsourcing-orders-panel" :class="{ 'is-active': activeTab === 'orders' }" @click="switchTab('orders')">外发单 <small>{{ total ?? '—' }}</small></button>
      <button v-if="canViewSources" id="outsourcing-sources-tab" role="tab" :aria-selected="activeTab === 'sources'" aria-controls="outsourcing-sources-panel" :class="{ 'is-active': activeTab === 'sources' }" @click="switchTab('sources')">待外发材料</button>
    </nav>
    <div v-if="activeTab === 'orders' && canViewRegularOrders" class="outsourcing-filter-bar order-filter-bar unified-order-filter-bar erp-list-filters">
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
    <section v-else-if="canViewRegularOrders" id="outsourcing-orders-panel" class="erp-list-data" role="tabpanel" aria-labelledby="outsourcing-orders-tab">
    <div class="list-toolbar erp-list-toolbar"><div class="heading-actions"><RouterLink v-if="canViewFactories" class="secondary-action el-button erp-button-motion" to="/workshop/outsourcing/factories">加工厂管理</RouterLink><ElButton class="erp-button-motion" v-if="canCreate" :disabled="!canViewOrders || accessDenied" @click="openCreate">新建外发单</ElButton><ElButton class="erp-button-motion" v-if="canCreateOriginal" type="primary" :disabled="!canViewOrders || accessDenied" @click="openTubeCreate">新建管材外发单</ElButton></div><div class="list-description"><small v-if="appliedFactoryId">数量仅含所选加工厂 · 状态仍为整单</small></div><ElButton class="erp-button-motion" :icon="Refresh" :disabled="loading || !canViewOrders" @click="load">刷新</ElButton></div>
      <div class="d4-list-table-area erp-list-table-frame"><ElTable :data="rows" border height="100%" row-key="row_key" class="d4-list-table" @row-click="openDetail">
        <ElTableColumn prop="order_number" label="外发单号" width="170" show-overflow-tooltip><template #default="{ row }"><RouterLink class="order-number-link" :to="unifiedOutsourcingDetailPath(row)" @click.stop>{{ row.order_number }}</RouterLink></template></ElTableColumn>
        <ElTableColumn label="生产任务单" width="130" show-overflow-tooltip><template #default="{ row }">{{ row.production_task_number || '—' }}</template></ElTableColumn>
        <ElTableColumn label="产品名称" min-width="155" show-overflow-tooltip><template #default="{ row }"><span class="table-product">{{ productName(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="品号" width="95" show-overflow-tooltip><template #default="{ row }">{{ unifiedProductAttribute(row, 'product_number') }}</template></ElTableColumn>
        <ElTableColumn label="货号" width="85" show-overflow-tooltip><template #default="{ row }">{{ unifiedProductAttribute(row, 'item_number') }}</template></ElTableColumn>
        <ElTableColumn label="订单颜色" width="96" show-overflow-tooltip><template #default="{ row }">{{ unifiedProductAttribute(row, 'color_name') }}</template></ElTableColumn>
        <ElTableColumn label="材料来源" width="125"><template #default="{ row }"><span class="unified-source-tag erp-list-tag" :class="row.source_kind === 'RAW' ? 'erp-list-tag--info' : row.source_kind === 'METAL' ? 'erp-list-tag--success' : 'erp-list-tag--warning'" :title="sourceLabel(row)">{{ sourceLabel(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="加工工艺" width="96"><template #default="{ row }"><span v-if="row.craft.name" class="craft-tag erp-list-tag" :class="[`craft-${craftTone(row.craft.name)}`, row.craft.name === '车缝' ? 'erp-list-tag--brand' : row.craft.name === '裁剪' ? 'erp-list-tag--info' : row.craft.name === '喷塑' ? 'erp-list-tag--success' : row.craft.name === '丝印' ? 'erp-list-tag--warning' : 'erp-list-tag--neutral']">{{ row.craft.name }}</span><span v-else>—</span></template></ElTableColumn>
        <ElTableColumn label="加工厂" width="135" show-overflow-tooltip><template #default="{ row }"><span :title="row.factory_names.join('、')">{{ factoryName(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="发出数量" width="95" align="right" class-name="num" show-overflow-tooltip><template #default="{ row }">{{ unifiedQuantityText(row, 'sent') }}</template></ElTableColumn>
        <ElTableColumn label="回货数量" width="95" align="right" class-name="num" show-overflow-tooltip><template #header><ElTooltip content="新管材按最终实收支数；其他外发沿用原合格回货口径。" placement="top"><span>回货数量</span></ElTooltip></template><template #default="{ row }"><ElTooltip v-if="row.receipt_state === 'MISSING'" content="已结束，但最终凭证尚无法核对；不当作0回货。" placement="top"><span>—</span></ElTooltip><span v-else>{{ unifiedQuantityText(row, 'received') }}</span></template></ElTableColumn>
        <ElTableColumn label="管材差额" width="90" align="right" class-name="num" show-overflow-tooltip><template #header><ElTooltip content="只显示新管材最终登记后的实发减实收。面料等不同单位不相减。" placement="top"><span>管材差额</span></ElTooltip></template><template #default="{ row }"><span :class="{ brand: hasShortage(row) }">{{ unifiedQuantityText(row, 'shortage') }}</span></template></ElTableColumn>
        <ElTableColumn label="预计回货日" width="110" show-overflow-tooltip><template #default="{ row }">{{ row.delivery_date || '—' }}</template></ElTableColumn>
        <ElTableColumn label="状态" width="90"><template #default="{ row }"><span class="status-tag erp-list-tag" :class="[`status-${statusTone(row.status)}`, row.status === 'COMPLETED' ? 'erp-list-tag--success' : row.status === 'PROCESSING' ? 'erp-list-tag--info' : row.status === 'PARTIAL_RETURN' ? 'erp-list-tag--warning' : 'erp-list-tag--neutral']">{{ row.status_display }}</span></template></ElTableColumn>
        <ElTableColumn label="操作" width="70" fixed="right">
          <template #default="{ row }">
            <span class="cell-actions" @click.stop>
              <ElButton v-if="row.record_type === 'TUBE'" link type="primary" :aria-label="`${row.order_number} 查看`" @click="openDetail(row)">查看</ElButton>
              <ElDropdown v-else :persistent="false" trigger="click" placement="bottom-end" @command="(command: string) => handleRowCommand(command, row)">
                <ElButton link type="primary" :aria-label="`${row.order_number} 更多操作`">更多<ElIcon><ArrowDown/></ElIcon></ElButton>
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem command="detail">查看详情</ElDropdownItem>
                    <ElDropdownItem v-if="canRemoveRow(row)" command="remove" :disabled="loading || Boolean(actingOrderId)" divided>{{ row.can_delete ? '删除' : '撤销并退料' }}</ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
            </span>
          </template>
        </ElTableColumn>
        <template #empty><div class="d4-list-empty"><template v-if="!canViewOrders || accessDenied"><strong>暂无委外加工查看权限</strong><span>请联系管理员核对权限</span></template><template v-else-if="loading"><ElIcon class="is-loading"><Refresh/></ElIcon><strong>正在读取外发单</strong><span>读取完成后显示数量与状态</span></template><template v-else-if="loadError"><strong>外发单读取失败</strong><span>{{ loadError }}</span><ElButton class="erp-button-motion" @click="load">重新读取</ElButton></template><template v-else><strong>{{ search || sourceKind || status || craftId || factoryId ? '没有符合条件的外发单' : '暂无外发单' }}</strong><span>可调整筛选条件或新建外发单</span></template></div></template>
      </ElTable></div>
      <footer class="outsourcing-pagination erp-list-footer"><span>{{ total === null ? '数量待读取' : `共 ${total} 条` }}</span><div v-if="total !== null" class="pagination"><ElSelect v-model="pageSize" class="page-size-picker" aria-label="每页条数" @change="page = 1; load()"><ElOption :value="20" label="20 条 / 页"/><ElOption :value="50" label="50 条 / 页"/></ElSelect><ElPagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" background @current-change="load" /></div><span v-else>页数 —</span></footer>
    </section>
    <ElResult v-if="!canViewOrders" icon="warning" title="暂无委外加工查看权限" />
    <AppWindowDialog v-model="createVisible" title="新建外发单 · 选择材料来源" :width="760" class="unified-source-dialog">
      <ElForm label-position="top">
        <ElFormItem label="材料来源">
          <ElRadioGroup v-model="createSourceKind"><ElRadioButton v-if="canCreateOriginal" value="RAW">仓库原料</ElRadioButton><ElRadioButton v-if="canCreateOriginal && canViewSources" value="METAL">金工加工件</ElRadioButton><ElRadioButton v-if="canCreateRework" value="REWORK">重加工件</ElRadioButton></ElRadioGroup>
        </ElFormItem>
        <p v-if="createSourceKind === 'RAW'" class="create-source-note">在下一步选择排产计划和具体材料，确认发料时按实际单位扣减仓库原料。面料按米发出，裁片半成品按套回货。</p>
        <template v-else>
          <ElFormItem label="来源领料单 / 加工部位" required>
            <ElSelect v-model="createSourceId" :loading="sourceLoading" filterable clearable placeholder="选择实际材料来源" @change="selectCreateSource"><ElOption v-for="item in selectableSources" :key="item.issue_line_id" :value="item.issue_line_id" :label="`${item.issue_number} · ${item.part_name} · ${createSourceKind === 'METAL' ? `可外发 ${item.available_pieces} 支` : '查看退回重加工记录'}`" /></ElSelect>
          </ElFormItem>
          <ElAlert v-if="sourceError" :title="sourceError" type="error" :closable="false" show-icon><ElButton link type="primary" @click="loadCreateSources">重新加载来源</ElButton></ElAlert>
          <ElSkeleton v-else-if="sourceDetailLoading" :rows="2" animated />
          <template v-else-if="createSource">
            <div class="create-source-summary"><strong>{{ createSource.issue_number }} · {{ createSource.part_name }}</strong><span>已完成加工 {{ createSource.completed_pieces }} 支 · 首次可外发 {{ createSource.available_pieces }} 支</span></div>
            <ElFormItem v-if="createSourceKind === 'REWORK'" label="具体退回 / 重加工记录" required>
              <ElSelect v-model="createReworkId" placeholder="选择尚有可分配数量的重加工记录"><ElOption v-for="item in selectableReworks" :key="item.id" :value="item.id" :label="reworkLabel(item)" /></ElSelect>
            </ElFormItem>
            <p v-if="createSourceKind === 'REWORK' && !selectableReworks.length" class="create-source-note">此来源暂无可分配的重加工记录，请在“待外发材料”查看退回记录并登记加工完成。</p>
            <p class="create-source-note">{{ createSourceKind === 'METAL' ? '按具体来源创建首次外发单，后续按支登记交接。' : '下一步按所选重加工记录分配数量并创建新外发单。' }}原料已在领料时扣除，交接不重复扣减原料。</p>
          </template>
          <p v-else-if="!sourceLoading && !selectableSources.length" class="create-source-note">暂无可选材料，请先在“待外发材料”核对来源与加工完成数量。</p>
        </template>
      </ElForm>
      <template #footer><ElButton v-if="canViewSources && createSourceKind !== 'RAW'" @click="createVisible = false; switchTab('sources')">前往待外发材料</ElButton><ElButton @click="createVisible = false">取消</ElButton><ElButton type="primary" :disabled="!canContinueCreate" @click="continueCreate">下一步</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style lang="scss">@use '@/styles/outsourcing.scss'; @use '@/styles/unifiedOutsourcingList.scss';</style>
<style scoped lang="scss">
.create-source-note { margin: 12px 0; color: var(--erp-color-text-regular); font-size: 13px; line-height: 1.8; }
.create-source-summary { display: grid; gap: 7px; margin-bottom: 16px; padding: 14px; border: 1px solid var(--erp-color-border); border-radius: 4px; background: var(--erp-color-subtle); font-size: 13px; }
.create-source-summary span { color: var(--erp-color-text-secondary); }
.unified-source-dialog .el-select { width: 100%; }
</style>
