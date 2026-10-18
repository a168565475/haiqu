<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { Refresh, Search } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { fetchSchedules, scheduleProductImageUrl } from '@/api/productionScheduling'
import { fetchScheduleProgressStatuses } from '@/api/workshopReporting'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import { useAuthStore } from '@/stores/auth'
import type { ProductionSchedule } from '@/types/productionScheduling'
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
const progressLoadFailed = ref(false)
let requestSequence = 0
const canCreate = computed(() => auth.user?.is_superuser || auth.hasPermission('production_scheduling.add_productionschedule'))

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
    progressLoadFailed.value = false
    if (result.data.length) {
      try {
        const progressRows = await fetchScheduleProgressStatuses({
          schedule_ids: result.data.map(item => item.id).join(','),
        })
        if (current !== requestSequence) return
        progressBySchedule.value = Object.fromEntries(progressRows.map(item => [item.schedule_id, item.progress]))
      } catch {
        if (current !== requestSequence) return
        progressBySchedule.value = {}
        progressLoadFailed.value = true
      }
    }
  } catch (error) {
    if (current === requestSequence) {
      rows.value = []; total.value = 0; progressBySchedule.value = {}; progressLoadFailed.value = false
      errorMessage.value = errorText(error)
    }
  } finally { if (current === requestSequence) loading.value = false }
}
function applyFilters() { page.value = 1; void load() }
function dateRange(row: ProductionSchedule, key: string) {
  const value = row.date_ranges[key]
  if (!value?.from) return '—'
  return value.from === value.to ? value.from : `${value.from} ～ ${value.to}`
}
function imageUrl(row: ProductionSchedule, fileId: string) { return scheduleProductImageUrl(row.production_task_id, fileId) }
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}
function openDetail(row: ProductionSchedule) { void router.push(`/workshop/scheduling/${row.id}`) }
function progressDisplay(row: ProductionSchedule, key: 'MATERIAL' | 'METAL' | 'SEWING' | 'ASSEMBLY') {
  if (key === 'MATERIAL') return '100%'
  if (progressLoadFailed.value) return '加载失败'
  return progressBySchedule.value[row.id]?.[key]?.display || '—'
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
        <ElTableColumn prop="schedule_number" label="排产单号" width="175" />
        <ElTableColumn label="生产任务单" width="190"><template #default="{ row }"><strong>{{ row.source.task_number }}</strong></template></ElTableColumn>
        <ElTableColumn label="产品概览" min-width="394"><template #default="{ row }"><div class="product-strip"><article v-for="product in row.products" :key="product.id" class="product-mini"><img :src="product.image_file_id ? imageUrl(row, product.image_file_id) : productImagePlaceholder" :class="{ 'is-placeholder': !product.image_file_id }" :alt="`${product.product.product_name || '产品'}图片`" @error="useProductImageFallback" /><div><strong>{{ product.product.product_name || '未命名产品' }}</strong><small>{{ product.product.item_number || product.product.product_number }} · {{ product.product.color_name || '—' }}</small><b>{{ product.planned_quantity }} {{ product.unit_name }}</b></div></article></div></template></ElTableColumn>
        <ElTableColumn label="计划日期范围" width="282"><template #default="{ row }"><div class="date-stack"><p><span class="date-mark material erp-list-tag erp-list-tag--warning">材料入库</span><span>{{ dateRange(row, 'material_inbound_date') }}</span></p><p><span class="date-mark metal erp-list-tag erp-list-tag--success">金工回货</span><span>{{ dateRange(row, 'metal_return_date') }}</span></p><p><span class="date-mark sewing erp-list-tag erp-list-tag--brand">车缝回货</span><span>{{ dateRange(row, 'sewing_return_date') }}</span></p><p><span class="date-mark finished erp-list-tag erp-list-tag--info">成品入库</span><span>{{ dateRange(row, 'finished_inbound_date') }}</span></p></div></template></ElTableColumn>
        <ElTableColumn label="进度" width="128"><template #default="{ row }"><div class="progress-stack"><p>{{ progressDisplay(row, 'MATERIAL') }}</p><p>{{ progressDisplay(row, 'METAL') }}</p><p>{{ progressDisplay(row, 'SEWING') }}</p><p>{{ progressDisplay(row, 'ASSEMBLY') }}</p></div></template></ElTableColumn>
        <ElTableColumn label="创建人" width="112"><template #default="{ row }">{{ row.created_by.name }}</template></ElTableColumn>
        <ElTableColumn prop="created_at" label="创建时间" width="175"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="122" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openDetail(row)">查看</ElButton></template></ElTableColumn>
      </ElTable>
    </div>
    <footer class="schedule-pagination erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()" /></footer>
    </section>
  </section>
</template>

<style lang="scss">@use '@/styles/productionScheduling.scss';</style>
<style scoped lang="scss">
.progress-stack { display: flex; flex-direction: column; gap: 4px; justify-content: center; }
.progress-stack p { min-height: 24px; margin: 0; display: flex; align-items: center; color: var(--erp-table-text); font-size: 13px; white-space: nowrap; }
</style>
