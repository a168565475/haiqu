<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { fetchSchedule, scheduleProductImageUrl, voidSchedule } from '@/api/productionScheduling'
import { fetchScheduleExecutionSummary } from '@/api/scheduleExecution'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ScheduleExecutionOverview from '@/components/productionScheduling/ScheduleExecutionOverview.vue'
import ProductionTimeline from '@/components/productionScheduling/ProductionTimeline.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProductionSchedule, ScheduleProduct } from '@/types/productionScheduling'
import type { ScheduleExecutionSummary } from '@/types/scheduleExecution'
import { formatScheduleMoney } from '@/utils/scheduleExecution'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const scheduleId = computed(() => String(route.params.scheduleId || ''))
const loading = ref(true)
const schedule = ref<ProductionSchedule | null>(null)
const activeProductId = ref('')
const etag = ref('')
const errorMessage = ref('')
const executionSummary = ref<ScheduleExecutionSummary | null>(null)
const executionLoading = ref(false)
const executionError = ref('')
let loadSequence = 0
let executionSequence = 0
const executionByProduct = computed(() => new Map(executionSummary.value?.products.map(product => [product.schedule_product_id, product]) || []))
const voidDialogVisible = ref(false)
const voidReason = ref('')
const voidReasonError = ref('')
const voiding = ref(false)
const canEdit = computed(() => schedule.value?.record_status === 'ACTIVE'
  && schedule.value.source_current_status === 'READY'
  && !schedule.value.source_is_archived
  && (auth.user?.is_superuser || auth.hasPermission('production_scheduling.change_productionschedule')))
const canVoid = computed(() => schedule.value?.record_status === 'ACTIVE' && (auth.user?.is_superuser || auth.hasPermission('production_scheduling.void_productionschedule')))
function errorText(error: unknown) {
  if (!(error instanceof AxiosError)) return '排产详情加载失败。'
  const data = error.response?.data as { error?: { message?: string } } | undefined
  return data?.error?.message || '排产详情加载失败。'
}
async function load() {
  const current = ++loadSequence
  executionSequence += 1
  loading.value = true
  schedule.value = null
  executionSummary.value = null
  executionError.value = ''
  errorMessage.value = ''
  try {
    const result = await fetchSchedule(scheduleId.value)
    if (current !== loadSequence) return
    schedule.value = result.data
    etag.value = result.etag
    void loadExecutionSummary()
  } catch (error) { if (current === loadSequence) errorMessage.value = errorText(error) }
  finally { if (current === loadSequence) loading.value = false }
}
async function loadExecutionSummary() {
  const current = ++executionSequence
  const id = scheduleId.value
  executionLoading.value = true
  executionSummary.value = null
  executionError.value = ''
  try {
    const result = await fetchScheduleExecutionSummary(id)
    if (current !== executionSequence || id !== scheduleId.value) return
    executionSummary.value = result
  } catch (error) {
    if (current !== executionSequence || id !== scheduleId.value) return
    const message = error instanceof AxiosError
      ? (error.response?.data as { error?: { message?: string } } | undefined)?.error?.message : ''
    executionError.value = message || '内部作业、外发及领料信息加载失败，金额汇总暂不可用。'
  } finally { if (current === executionSequence) executionLoading.value = false }
}
function formatDate(value: string) { return value ? value.slice(0, 10) : '—' }
function craftTagTone(craft: ScheduleProduct['crafts'][number]) {
  if (craft.craft_type === 'EXTERNAL' || craft.plan_category === 'SEWING') return 'brand'
  if (craft.plan_category === 'CUTTING') return 'info'
  return 'success'
}
function openVoidDialog() {
  voidReason.value = ''
  voidReasonError.value = ''
  voidDialogVisible.value = true
}
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}
async function submitVoid() {
  const reason = voidReason.value.trim()
  if (reason.length < 2) {
    voidReasonError.value = '作废原因至少 2 个字。'
    return
  }
  if (voiding.value) return
  voiding.value = true
  voidReasonError.value = ''
  try {
    const result = await voidSchedule(scheduleId.value, reason, etag.value)
    schedule.value = result.data
    etag.value = result.etag
    voidDialogVisible.value = false
    ElMessage.success('排产计划已作废')
    void loadExecutionSummary()
  } catch (error) {
    voidReasonError.value = errorText(error)
  } finally {
    voiding.value = false
  }
}
watch(() => schedule.value?.products, products => {
  if (!products?.some(product => product.id === activeProductId.value)) {
    activeProductId.value = products?.[0]?.id || ''
  }
})
watch(scheduleId, () => { void load() }, { immediate: true })
</script>

<template>
  <section v-loading="loading" class="schedule-page schedule-detail erp-glass-detail" data-testid="production-scheduling-detail">
    <header class="schedule-heading detail-heading"><div><h1>排产计划详情</h1></div><div><ElButton v-if="canVoid" @click="openVoidDialog">整单作废</ElButton><ElButton v-if="canEdit" type="primary" @click="router.push(`/workshop/scheduling/${scheduleId}/edit`)">编辑排产</ElButton></div></header>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <template v-if="schedule">
      <section class="schedule-section detail-basic">
        <header><h2>基本信息</h2></header>
        <dl>
          <div><dt>排产计划号</dt><dd>{{ schedule.schedule_number }}</dd></div>
          <div><dt>生产任务单</dt><dd>{{ schedule.source.task_number }}</dd></div>
          <div><dt>创建日期</dt><dd>{{ formatDate(schedule.created_at) }}</dd></div>
          <div><dt>创建人</dt><dd>{{ schedule.created_by.name }}</dd></div>
          <div><dt>交货日期</dt><dd>{{ formatDate(schedule.source.delivery_date) }}</dd></div>
          <div><dt>状态</dt><dd><span class="erp-list-tag" :class="schedule.record_status === 'ACTIVE' ? 'erp-list-tag--info' : 'erp-list-tag--neutral'">{{ schedule.record_status_display }}</span></dd></div>
          <div class="detail-basic__amount"><dt>报工总价（预计）</dt><dd data-testid="schedule-estimated-total">{{ executionLoading ? '加载中…' : formatScheduleMoney(executionSummary?.totals.estimated_wage) }}</dd></div>
          <div class="detail-basic__amount"><dt>已报工金额</dt><dd data-testid="schedule-reported-total">{{ executionLoading ? '加载中…' : formatScheduleMoney(executionSummary?.totals.reported_amount) }}</dd></div>
          <div class="detail-basic__amount"><dt>可见关联外发计划金额</dt><dd data-testid="schedule-outsourcing-total">{{ executionLoading ? '加载中…' : formatScheduleMoney(executionSummary?.totals.outsourcing_planned_amount) }}</dd></div>
        </dl>
        <ElAlert v-if="executionError" type="warning" :title="executionError" show-icon :closable="false"><ElButton link type="primary" @click="loadExecutionSummary">重试关联信息</ElButton></ElAlert>
      </section>
      <section class="schedule-section detail-products"><header><h2>产品排产明细 <span>共 {{ schedule.products.length }} 个产品</span></h2></header>
        <ElTabs v-if="schedule.products.length" v-model="activeProductId" type="card" class="detail-product-tabs" :class="{ 'is-single-product': schedule.products.length === 1 }">
          <ElTabPane v-for="product in schedule.products" :key="product.id" :name="product.id" :label="`${product.product.product_name || '未命名产品'}${product.product.color_name ? ` · ${product.product.color_name}` : ''}`" lazy>
        <article v-if="activeProductId === product.id" class="schedule-product-card" :data-schedule-product-id="product.id">
          <div class="schedule-product-card__body">
            <div class="detail-product-main"><img :src="product.image_file_id ? scheduleProductImageUrl(schedule.production_task_id, product.image_file_id) : productImagePlaceholder" :class="{ 'is-placeholder': !product.image_file_id }" :alt="`${product.product.product_name || '产品'}图片`" @error="useProductImageFallback" /><dl><div><dt>产品号</dt><dd>{{ product.product.item_number || product.product.product_number || '—' }}</dd></div><div><dt>产品名称</dt><dd>{{ product.product.product_name || '未命名产品' }}</dd></div><div><dt>规格</dt><dd data-field="specification">{{ (product.product.specification_display ?? product.product.specification) || '—' }}</dd></div><div><dt>颜色</dt><dd data-field="color">{{ product.product.color_name || '—' }}</dd></div><div><dt>材质</dt><dd data-field="material">{{ product.product.material || '—' }}</dd></div></dl></div>
            <dl class="detail-quantities"><div><dt>订单数量</dt><dd>{{ product.source_quantity.toLocaleString('zh-CN') }} {{ product.unit_name }}</dd></div><div><dt>排产数量</dt><dd>{{ product.planned_quantity.toLocaleString('zh-CN') }} {{ product.unit_name }}</dd></div></dl>
            <section class="detail-dates"><h3>计划关键日期</h3><dl><div><dt>材料入库时间</dt><dd>{{ formatDate(product.material_inbound_date) }}</dd></div><div><dt>金工回货时间</dt><dd>{{ formatDate(product.metal_return_date) }}</dd></div><div><dt>车缝回货时间</dt><dd>{{ formatDate(product.sewing_return_date) }}</dd></div><div><dt>成品入库时间</dt><dd>{{ formatDate(product.finished_inbound_date) }}</dd></div></dl></section>
            <div class="detail-crafts"><h3>工艺选择</h3><div><span>厂内工艺</span><p><span v-for="craft in product.crafts.filter(item => item.craft_type === 'INTERNAL')" :key="craft.id" class="erp-list-tag" :class="`erp-list-tag--${craftTagTone(craft)}`" :title="craft.name">{{ craft.name }}</span><em v-if="!product.crafts.some(item => item.craft_type === 'INTERNAL')">—</em></p></div><div><span>厂外工艺</span><p><span v-for="craft in product.crafts.filter(item => item.craft_type === 'EXTERNAL')" :key="craft.id" class="erp-list-tag" :class="`erp-list-tag--${craftTagTone(craft)}`" :title="craft.name">{{ craft.name }}</span><em v-if="!product.crafts.some(item => item.craft_type === 'EXTERNAL')">—</em></p></div></div>
          </div>
          <ScheduleExecutionOverview :schedule-id="schedule.id" :production-task-id="schedule.production_task_id" :product-line-id="product.product_line_id" :summary="executionByProduct.get(product.id) || null" :loading="executionLoading" :failed="Boolean(executionError)" :active="schedule.record_status === 'ACTIVE'" />
        </article>
          </ElTabPane>
        </ElTabs>
      </section>
      <ProductionTimeline :schedule-id="schedule.id" :revision="schedule.version" />
    </template>
    <AppWindowDialog v-model="voidDialogVisible" title="整单作废" :width="520" :height="300" class="schedule-void-dialog" destroy-on-close :close-on-click-modal="!voiding" :close-on-press-escape="!voiding" :show-close="!voiding">
      <p>作废后该计划保留历史，可为同一生产任务单重新建立有效计划。</p>
      <ElInput v-model="voidReason" type="textarea" :rows="3" maxlength="200" show-word-limit placeholder="请输入作废原因" :disabled="voiding" @input="voidReasonError = ''" />
      <span v-if="voidReasonError" class="schedule-field-error">{{ voidReasonError }}</span>
      <template #footer><ElButton :disabled="voiding" @click="voidDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="voiding" @click="submitVoid">确认作废</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style lang="scss">@use '@/styles/productionScheduling.scss';</style>
