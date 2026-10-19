<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref, shallowRef } from 'vue'
import { AxiosError } from 'axios'
import { MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  createOutsourcingFactory,
  disableOutsourcingFactory,
  fetchOutsourcingFactories,
  fetchOutsourcingFactory,
  fetchOutsourcingFactoryOptions,
  updateOutsourcingFactory,
} from '@/api/outsourcing'
import FactoryFormDialog from '@/components/outsourcing/FactoryFormDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { OutsourcingCraftOption, OutsourcingFactory, OutsourcingFactoryInput } from '@/types/outsourcing'

const router = useRouter()
const auth = useAuthStore()
const rows = ref<OutsourcingFactory[]>([])
const crafts = ref<OutsourcingCraftOption[]>([])
const processingTypes = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const search = ref('')
const craftId = ref('')
const processingType = ref('')
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingFactory = ref<OutsourcingFactory | null>(null)
const editingEtag = ref('')
const disableDialogVisible = ref(false)
const disablingFactory = ref<OutsourcingFactory | null>(null)
const disabling = ref(false)
const hoveredCell = shallowRef<HTMLElement>()
const hoveredRemark = ref('')
const remarkVisible = ref(false)
const actionMenuVisible = ref(false)
let requestSequence = 0

const canCreate = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.add_outsourcingfactory'))
const canChange = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.change_outsourcingfactory'))
const canDisable = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.disable_outsourcingfactory'))

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) return fallback
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || fallback
}

function craftTone(name: string): string {
  return ({ 车缝: 'sewing', 裁剪: 'cutting', 喷塑: 'spray', 丝印: 'printing' } as Record<string, string>)[name] || 'neutral'
}

function formatOutput(row: OutsourcingFactory): string {
  if (row.estimated_output === null || row.estimated_output === '') return '—'
  const numeric = Number(row.estimated_output)
  return Number.isFinite(numeric) ? numeric.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : row.estimated_output
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false }).replaceAll('/', '-').replace(',', '')
}

async function loadOptions(): Promise<void> {
  try {
    const result = await fetchOutsourcingFactoryOptions()
    crafts.value = result.crafts
    processingTypes.value = result.processing_types
  } catch (error) {
    ElMessage.error(errorText(error, '加工厂筛选项加载失败。'))
  }
}

async function load(): Promise<void> {
  remarkVisible.value = false
  const current = ++requestSequence
  loading.value = true
  loadError.value = ''
  try {
    const result = await fetchOutsourcingFactories({
      page: page.value,
      page_size: pageSize.value,
      search: search.value.trim() || undefined,
      craft_id: craftId.value || undefined,
      processing_type: processingType.value || undefined,
    })
    if (current !== requestSequence) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (current !== requestSequence) return
    rows.value = []
    total.value = 0
    loadError.value = errorText(error, '加工厂列表加载失败，请稍后重试。')
  } finally {
    if (current === requestSequence) loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  search.value = ''
  craftId.value = ''
  processingType.value = ''
  applyFilters()
}

function openDetail(row: OutsourcingFactory): void {
  remarkVisible.value = false
  void router.push(`/workshop/outsourcing/factories/${row.id}`)
}

function showRemark(row: OutsourcingFactory, _column: unknown, cell: HTMLElement): void {
  hoveredCell.value = cell
  hoveredRemark.value = row.remark?.trim() || ''
  remarkVisible.value = !!hoveredRemark.value && !actionMenuVisible.value
}

function toggleActionMenu(visible: boolean): void {
  actionMenuVisible.value = visible
  remarkVisible.value = false
}

function openCreate(): void {
  dialogMode.value = 'create'
  editingFactory.value = null
  editingEtag.value = ''
  dialogVisible.value = true
}

async function openEdit(row: OutsourcingFactory): Promise<void> {
  try {
    const result = await fetchOutsourcingFactory(row.id)
    editingFactory.value = result.data
    editingEtag.value = result.etag
    dialogMode.value = 'edit'
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(errorText(error, '加工厂详情加载失败。'))
  }
}

async function save(payload: OutsourcingFactoryInput): Promise<void> {
  saving.value = true
  try {
    if (dialogMode.value === 'create') {
      await createOutsourcingFactory(payload)
      ElMessage.success('加工厂已新增。')
    } else if (editingFactory.value) {
      await updateOutsourcingFactory(editingFactory.value.id, payload, editingEtag.value)
      ElMessage.success('加工厂已更新。')
    }
    dialogVisible.value = false
    await Promise.all([load(), loadOptions()])
  } catch (error) {
    ElMessage.error(errorText(error, '加工厂保存失败，请检查后重试。'))
  } finally {
    saving.value = false
  }
}

function openDisable(row: OutsourcingFactory): void {
  disablingFactory.value = row
  disableDialogVisible.value = true
}

async function confirmDisable(): Promise<void> {
  const row = disablingFactory.value
  if (!row) return
  disabling.value = true
  try {
    const detail = await fetchOutsourcingFactory(row.id)
    await disableOutsourcingFactory(row.id, detail.etag)
    ElMessage.success('加工厂已停用。')
    disableDialogVisible.value = false
    disablingFactory.value = null
    await load()
  } catch (error) {
    ElMessage.error(errorText(error, '停用加工厂失败。'))
  } finally {
    disabling.value = false
  }
}

onMounted(() => {
  void Promise.all([load(), loadOptions()])
})
</script>

<template>
  <section class="outsourcing-page factory-list-page erp-glass-list" data-testid="factory-list-page">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="outsourcing-heading erp-list-heading">
      <div class="heading-title"><h1>加工厂管理</h1><span>共 {{ total }} 家</span></div>
    </header>

    <div class="outsourcing-filter-bar factory-filter-bar erp-list-filters">
      <ElInput v-model="search" :prefix-icon="Search" clearable placeholder="搜索加工厂名称、联系人、电话" @keyup.enter="applyFilters" @clear="applyFilters" />
      <ElSelect v-model="craftId" placeholder="外协工序：全部" clearable @change="applyFilters">
        <ElOption v-for="craft in crafts" :key="craft.id" :label="craft.name" :value="craft.id" />
      </ElSelect>
      <ElSelect v-model="processingType" placeholder="加工类型：全部" clearable @change="applyFilters">
        <ElOption v-for="item in processingTypes" :key="item" :label="item" :value="item" />
      </ElSelect>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="applyFilters">应用筛选</ElButton></div>
    </div>
    </section>

    <section class="erp-list-data">
    <div class="list-toolbar erp-list-toolbar">      <div class="heading-actions">
        <RouterLink class="secondary-action el-button erp-button-motion" to="/workshop/outsourcing">返回委外加工</RouterLink>
        <ElButton v-if="canCreate" class="erp-button-motion" :icon="Plus" type="primary" @click="openCreate">新增加工厂</ElButton>
      </div>
      <ElButton class="erp-button-motion factory-refresh" :icon="Refresh" :loading="loading" @click="load">刷新</ElButton>
    </div>
    <ElAlert v-if="loadError" :title="loadError" type="error" show-icon :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <div v-else class="outsourcing-table-card erp-list-table-frame">
      <ElTable v-loading="loading" :data="rows" border height="100%" row-key="id" empty-text="暂无加工厂资料" @row-click="openDetail" @cell-mouse-enter="showRemark" @cell-mouse-leave="remarkVisible = false" @mouseleave="remarkVisible = false">
        <ElTableColumn prop="name" label="加工厂名称" min-width="160" />
        <ElTableColumn label="外协工序" width="130"><template #default="{ row }"><div class="craft-stack"><span v-for="craft in row.crafts" :key="craft.id" class="craft-tag erp-list-tag" :class="[`craft-${craftTone(craft.name)}`, craftTone(craft.name) === 'sewing' ? 'erp-list-tag--brand' : craftTone(craft.name) === 'cutting' ? 'erp-list-tag--info' : craftTone(craft.name) === 'spray' ? 'erp-list-tag--success' : craftTone(craft.name) === 'printing' ? 'erp-list-tag--warning' : 'erp-list-tag--neutral']">{{ craft.name }}</span></div></template></ElTableColumn>
        <ElTableColumn prop="processing_type" label="加工类型" min-width="140" />
        <ElTableColumn label="预产量" width="110"><template #default="{ row }">{{ formatOutput(row) }}</template></ElTableColumn>
        <ElTableColumn prop="contact_name" label="联系人" width="110" />
        <ElTableColumn prop="contact_phone" label="联系电话" min-width="140" />
        <ElTableColumn prop="address" label="地址" min-width="175" show-overflow-tooltip />
        <ElTableColumn prop="remark" label="备注" min-width="180"><template #default="{ row }"><span class="factory-remark">{{ row.remark || '—' }}</span></template></ElTableColumn>
        <ElTableColumn prop="payment_cycle_display" label="付款周期" width="110" />
        <ElTableColumn label="更新时间" width="180"><template #default="{ row }">{{ formatDate(row.updated_at) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="94" fixed="right"><template #default="{ row }"><div class="factory-actions" @click.stop><ElDropdown trigger="click" @visible-change="toggleActionMenu"><ElButton text :icon="MoreFilled" aria-label="加工厂操作" /><template #dropdown><ElDropdownMenu><ElDropdownItem @click="openDetail(row)">查看详情</ElDropdownItem><ElDropdownItem v-if="canChange" @click="openEdit(row)">编辑</ElDropdownItem><ElDropdownItem v-if="canDisable && row.status === 'ACTIVE'" divided @click="openDisable(row)">停用</ElDropdownItem></ElDropdownMenu></template></ElDropdown></div></template></ElTableColumn>
      </ElTable>
      <ElTooltip virtual-triggering :virtual-ref="hoveredCell" :visible="remarkVisible" :content="hoveredRemark" effect="light" placement="top-start" popper-class="factory-remark-tooltip" />
    </div>
    <footer class="outsourcing-pagination erp-list-footer"><span>共 {{ total }} 家</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()" /></footer>
    </section>

    <FactoryFormDialog v-model="dialogVisible" :mode="dialogMode" :factory="editingFactory" :crafts="crafts" :saving="saving" @submit="save" />
    <AppWindowDialog v-model="disableDialogVisible" title="停用加工厂" :width="480" :height="236" class="outsourcing-confirm-dialog" destroy-on-close :close-on-click-modal="!disabling" :close-on-press-escape="!disabling" :show-close="!disabling">
      <p class="confirm-copy">停用“{{ disablingFactory?.name }}”后将不能用于新的外发分配，历史单据不会受影响。</p>
      <template #footer><ElButton :disabled="disabling" @click="disableDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="disabling" @click="confirmDisable">确认停用</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style lang="scss">@use '@/styles/outsourcing.scss';</style>

<style scoped lang="scss">
.heading-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; }
.heading-title > span { color: var(--erp-color-text-secondary); font-size: 12px; }
.heading-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.heading-actions > .secondary-action { text-decoration: none; }
.factory-filter-bar > .el-input { width: min(250px, 100%); max-width: 250px; flex: 0 1 250px; }
.factory-filter-bar > .el-select { width: 170px; flex: none; }
.factory-filter-bar > .el-select:last-of-type { width: 210px; }
.factory-list-page .list-toolbar > .factory-refresh { margin-left: auto; }
.factory-remark { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
:global(.factory-remark-tooltip) { max-width: min(360px, calc(100vw - 32px)); white-space: pre-wrap; overflow-wrap: anywhere; }
.craft-stack { display: flex; flex-wrap: wrap; gap: 4px; }
.craft-tag { min-width: 84px; }
.outsourcing-table-card :deep(.el-table__row) { cursor: pointer; }
</style>
