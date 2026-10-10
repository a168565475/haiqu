<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { fetchOutsourcingFactory, fetchOutsourcingFactoryOptions, updateOutsourcingFactory } from '@/api/outsourcing'
import { fetchUnifiedOutsourcingOrders, unifiedOutsourcingDetailPath } from '@/api/unifiedOutsourcing'
import FactoryFormDialog from '@/components/outsourcing/FactoryFormDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { OutsourcingCraftOption, OutsourcingFactory, OutsourcingFactoryInput } from '@/types/outsourcing'
import type { UnifiedOutsourcingOrder, UnifiedOutsourcingStatus } from '@/types/unifiedOutsourcing'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const factory = ref<OutsourcingFactory | null>(null)
const crafts = ref<OutsourcingCraftOption[]>([])
const etag = ref('')
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const dialogVisible = ref(false)
const relatedOrders = ref<UnifiedOutsourcingOrder[]>([])
const relatedLoading = ref(false)
const relatedError = ref('')
const relatedTotal = ref(0)
const relatedPage = ref(1)
const relatedPageSize = ref(20)
const factoryId = computed(() => String(route.params.factoryId || ''))
const canChange = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.change_outsourcingfactory'))
const canViewOrders = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.view_outsourcingorder') || auth.hasPermission('material_issues.view_metalprocessingsource'))
let relatedRequestSequence = 0

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) return fallback
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || fallback
}

function craftTone(name: string): string {
  return ({ 车缝: 'sewing', 裁剪: 'cutting', 喷塑: 'spray', 丝印: 'printing' } as Record<string, string>)[name] || 'neutral'
}

function statusTone(status: UnifiedOutsourcingStatus): string {
  return ({ PENDING_DISPATCH: 'pending', PENDING_HANDOFF: 'pending', PROCESSING: 'processing', PARTIAL_RETURN: 'partial', COMPLETED: 'completed', CLOSED: 'cancelled', CANCELLED: 'cancelled' })[status]
}

function formatOutput(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('zh-CN').replaceAll('/', '-')
}

async function load(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [detail, options] = await Promise.all([
      fetchOutsourcingFactory(factoryId.value),
      fetchOutsourcingFactoryOptions(),
    ])
    factory.value = detail.data
    etag.value = detail.etag
    crafts.value = options.crafts
    await loadRelatedOrders()
  } catch (error) {
    factory.value = null
    relatedOrders.value = []
    relatedTotal.value = 0
    errorMessage.value = errorText(error, '加工厂详情加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

async function loadRelatedOrders(): Promise<void> {
  if (!canViewOrders.value) return
  const current = ++relatedRequestSequence
  relatedLoading.value = true
  relatedError.value = ''
  try {
    const orders = await fetchUnifiedOutsourcingOrders({ factory_id: factoryId.value, page: relatedPage.value, page_size: relatedPageSize.value })
    if (current !== relatedRequestSequence) return
    relatedOrders.value = orders.data
    relatedTotal.value = orders.meta.total
  } catch (error) {
    if (current !== relatedRequestSequence) return
    relatedOrders.value = []
    relatedTotal.value = 0
    relatedError.value = errorText(error, '关联外发单加载失败。')
  } finally {
    if (current === relatedRequestSequence) relatedLoading.value = false
  }
}

async function save(payload: OutsourcingFactoryInput): Promise<void> {
  if (!factory.value) return
  saving.value = true
  try {
    const result = await updateOutsourcingFactory(factory.value.id, payload, etag.value)
    factory.value = result.data
    etag.value = result.etag
    dialogVisible.value = false
    ElMessage.success('加工厂已更新。')
    await load()
  } catch (error) {
    ElMessage.error(errorText(error, '加工厂保存失败，请刷新后重试。'))
  } finally {
    saving.value = false
  }
}

onMounted(() => { void load() })
</script>

<template>
  <section class="outsourcing-page factory-detail-page" data-testid="factory-detail-page">
    <div v-if="loading" class="page-loading"><ElSkeleton :rows="8" animated /></div>
    <ElResult v-else-if="errorMessage" icon="error" title="加工厂详情加载失败" :sub-title="errorMessage"><template #extra><ElButton @click="router.push('/workshop/outsourcing/factories')">返回列表</ElButton><ElButton type="primary" @click="load">重试</ElButton></template></ElResult>
    <template v-else-if="factory">
      <header class="outsourcing-heading detail-heading">
        <div class="detail-title"><ElButton @click="router.push('/workshop/outsourcing/factories')">返回</ElButton><h1>加工厂详情</h1></div>
        <ElButton v-if="canChange" type="primary" @click="dialogVisible = true">编辑</ElButton>
      </header>
      <section class="detail-card factory-information-card">
        <h2>加工厂信息</h2>
        <div class="factory-information-grid">
          <dl><div><dt>加工厂名称</dt><dd>{{ factory.name }}</dd></div><div><dt>外协工序</dt><dd><span v-for="craft in factory.crafts" :key="craft.id" class="craft-tag" :class="`craft-${craftTone(craft.name)}`">{{ craft.name }}</span></dd></div><div><dt>加工类型</dt><dd>{{ factory.processing_type }}</dd></div><div><dt>加工厂预产量</dt><dd>{{ formatOutput(factory.estimated_output) }}</dd></div><div><dt>联系人</dt><dd>{{ factory.contact_name }}</dd></div><div><dt>联系电话</dt><dd>{{ factory.contact_phone }}</dd></div></dl>
          <dl><div><dt>地址</dt><dd>{{ factory.address }}</dd></div><div><dt>付款周期</dt><dd>{{ factory.payment_cycle_display }}</dd></div><div><dt>备注</dt><dd>{{ factory.remark || '—' }}</dd></div><div><dt>创建时间</dt><dd>{{ formatDate(factory.created_at) }}</dd></div><div><dt>更新时间</dt><dd>{{ formatDate(factory.updated_at) }}</dd></div></dl>
        </div>
      </section>
      <section class="detail-card related-orders-card">
        <h2>关联外发单 <span>共 {{ relatedTotal }} 条</span></h2>
        <ElAlert v-if="!canViewOrders" title="暂无外发单查看权限，加工厂基础信息仍可查看。" type="info" :closable="false" />
        <ElAlert v-else-if="relatedError" :title="relatedError" type="error" :closable="false"><ElButton link type="primary" @click="loadRelatedOrders">重试</ElButton></ElAlert>
        <ElTable v-else v-loading="relatedLoading" :data="relatedOrders" border row-key="row_key" empty-text="暂无关联外发单">
          <ElTableColumn prop="order_number" label="外发单号" width="205" />
          <ElTableColumn prop="schedule_number" label="排产计划号" width="205" />
          <ElTableColumn label="产品信息" min-width="275"><template #default="{ row }"><div class="table-product"><div class="line-art-thumb" aria-hidden="true">◇</div><div><strong>{{ row.product.product_name || '—' }}<template v-if="row.product_count > 1"> 等 {{ row.product_count }} 款</template></strong><small>{{ row.product.item_number || row.product.product_number || '—' }} · {{ row.product.color_name || '—' }}</small></div></div></template></ElTableColumn>
          <ElTableColumn label="材料来源" width="125"><template #default="{ row }">{{ row.source_label }}</template></ElTableColumn>
          <ElTableColumn label="本厂发出数量" width="160"><template #default="{ row }"><div v-for="amount in row.dispatched_quantities" :key="amount.unit">{{ formatOutput(amount.quantity) }} {{ amount.unit }}</div><span v-if="!row.dispatched_quantities.length">未发出</span></template></ElTableColumn>
          <ElTableColumn label="本厂合格回货" width="160"><template #default="{ row }"><div v-for="amount in row.returned_quantities" :key="amount.unit">{{ formatOutput(amount.quantity) }} {{ amount.unit }}</div><span v-if="!row.returned_quantities.length">未回货</span></template></ElTableColumn>
          <ElTableColumn label="交货日期" width="125"><template #default="{ row }">{{ row.delivery_date || '—' }}</template></ElTableColumn>
          <ElTableColumn label="状态" width="145"><template #default="{ row }"><span class="status-tag" :class="`status-${statusTone(row.status)}`">{{ row.status_display }}</span></template></ElTableColumn>
          <ElTableColumn label="操作" width="96" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="router.push(unifiedOutsourcingDetailPath(row))">查看详情</ElButton></template></ElTableColumn>
        </ElTable>
        <footer v-if="canViewOrders" class="embedded-pagination"><span>共 {{ relatedTotal }} 条</span><ElPagination v-model:current-page="relatedPage" v-model:page-size="relatedPageSize" :total="relatedTotal" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @current-change="loadRelatedOrders" @size-change="relatedPage = 1; loadRelatedOrders()" /></footer>
      </section>
      <FactoryFormDialog v-model="dialogVisible" mode="edit" :factory="factory" :crafts="crafts" :saving="saving" @submit="save" />
    </template>
  </section>
</template>

<style lang="scss">@use '@/styles/outsourcing.scss';</style>
