<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'

import { fetchSample } from '@/api/samples'
import { fetchSampleMaterials, fetchSampleProcurementMaterialContext } from '@/api/sampleMaterials'
import SampleSection from '@/components/samples/SampleSection.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import { useAuthStore } from '@/stores/auth'
import type { SampleDetail } from '@/types/sample'
import type { SampleMaterialCategory, SampleMaterialLoadResult, SampleMaterialProgress, SampleProcurementMaterialContext } from '@/types/sampleMaterial'
import { sampleMaterialCategories } from '@/types/sampleMaterial'
import { sampleProductFieldLabel, sampleProductsLabel, sampleQuantityLabel } from '@/utils/samplePresentation'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const sample = ref<SampleDetail | null>(null)
const procurementSample = ref<SampleProcurementMaterialContext['sample'] | null>(null)
const headingSample = computed(() => sample.value || procurementSample.value)
const progress = ref<SampleMaterialProgress | null>(null)
const materialResult = ref<Extract<SampleMaterialLoadResult, { available: true }> | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const categoryFilter = ref<'all' | SampleMaterialCategory>('all')

const sampleId = computed(() => String(route.params.sampleId || ''))
const canCreatePurchase = computed(() => Boolean(
  materialResult.value?.procurementRequest?.id
  && progress.value?.status === 'PROCUREMENT_PENDING'
  && progress.value.label === '等待采购'
  && (authStore.user?.is_superuser || authStore.hasPermission('procurement.add_purchaseorder')),
))
const categoryTabs = computed(() => {
  const counts = new Map<string, number>()
  progress.value?.lines.forEach((line) => counts.set(line.category, (counts.get(line.category) || 0) + 1))
  const available = sampleMaterialCategories.filter((category) => counts.has(category.key))
  return available.map((category) => ({ key: category.key, label: category.label, count: counts.get(category.key) || 0 }))
})
const visibleLines = computed(() => {
  const lines = progress.value?.lines || []
  return categoryFilter.value === 'all' ? lines : lines.filter((line) => line.category === categoryFilter.value)
})
const tagStatus = computed(() => {
  const status = progress.value?.status
  if (status === 'MATERIALS_ISSUED') return 'MATERIALS_READY'
  return status || sample.value?.status || 'DRAFT'
})
const colorLabel = computed(() => {
  const colors = (sample.value?.products || []).flatMap((product) => product.details || [])
    .map((detail) => [detail.color_name, detail.color_card, detail.color_code].filter(Boolean).join(' / '))
    .filter(Boolean)
  return colors.join('；') || '—'
})
const contextFields = computed(() => procurementSample.value ? [
  { label: '客户', value: procurementSample.value.customer_name || '—' },
  { label: '产品名称', value: procurementSample.value.product_name || '—' },
  { label: '规格', value: procurementSample.value.specification || '—' },
  { label: '颜色', value: procurementSample.value.color || '—' },
  { label: '打样数量', value: procurementSample.value.quantity_label || '—' },
  { label: '申请日期', value: procurementSample.value.requested_at?.slice(0, 10) || '—' },
] : [
  { label: '客户', value: sample.value?.customer_name || '—' },
  { label: '产品名称', value: sample.value ? sampleProductsLabel(sample.value) : '—' },
  { label: '规格', value: sample.value ? sampleProductFieldLabel(sample.value, 'specification') : '—' },
  { label: '颜色', value: colorLabel.value },
  { label: '打样数量', value: sample.value ? sampleQuantityLabel(sample.value) : '—' },
  { label: '申请日期', value: sample.value?.requested_at?.slice(0, 10) || '—' },
])

function errorText(error: unknown) {
  if (error instanceof AxiosError && error.response?.status === 403) return '当前账号没有查看此材料需求的权限。'
  if (error instanceof AxiosError && error.response?.status === 404) return '未找到此打样申请。'
  return '材料需求加载失败，请重试。'
}

function applyDefaultCategory(value: SampleMaterialProgress | null) {
  if (!value?.lines.length) { categoryFilter.value = 'all'; return }
  const first = categoryTabs.value[0]?.key
  categoryFilter.value = first || 'all'
}

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  try {
    if (!sampleId.value) throw new Error('缺少申请编号。')
    let materialResponse: SampleMaterialLoadResult
    if (!authStore.hasPermission('samples.view_samplerequest') && authStore.hasPermission('samples.view_sample_procurement')) {
      const context = await fetchSampleProcurementMaterialContext(sampleId.value)
      procurementSample.value = context.sample
      sample.value = null
      materialResponse = context.materials
    } else {
      const [sampleResponse, materials] = await Promise.all([fetchSample(sampleId.value), fetchSampleMaterials(sampleId.value)])
      sample.value = sampleResponse.data
      procurementSample.value = null
      materialResponse = materials
    }
    if (!materialResponse.available) {
      errorMessage.value = materialResponse.reason
      return
    }
    materialResult.value = materialResponse
    progress.value = materialResponse.progress || null
    applyDefaultCategory(progress.value)
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

function openPurchase() {
  const procurementId = materialResult.value?.procurementRequest?.id
  if (!procurementId) return
  void router.push({
    name: 'purchase-order-create-details',
    query: { source_type: 'SAMPLE', source_id: procurementId },
  })
}

onMounted(loadPage)
</script>

<template>
  <section v-loading="loading" class="sample-material-detail-page" aria-label="样品用料需求详情">
    <header class="material-detail-heading">
      <div class="heading-copy">
        <div class="heading-main"><h1>样品用料需求详情</h1><SampleStatusTag v-if="headingSample" :status="headingSample.status" :label="headingSample.status_display" /></div>
        <p>申请编号 {{ headingSample?.request_number || '—' }}</p>
      </div>
      <div class="material-detail-heading-actions">
        <ElButton @click="router.push({ name: 'samples' })">返回列表</ElButton>
        <ElButton v-if="canCreatePurchase" type="primary" @click="openPurchase">去创建采购单</ElButton>
      </div>
    </header>

    <div v-if="errorMessage" role="alert" class="material-detail-error"><span>{{ errorMessage }}</span><ElButton @click="loadPage">重新加载</ElButton></div>

    <template v-else-if="headingSample">
      <section class="material-detail-context" aria-label="申请与样品信息">
        <div v-for="field in contextFields" :key="field.label" class="context-field">
          <label>{{ field.label }}</label><strong :title="field.value">{{ field.value }}</strong>
        </div>
      </section>

      <SampleSection title="用料需求与进度" class="material-detail-surface">
        <template #actions><SampleStatusTag v-if="progress" :status="tagStatus" :label="progress.label" /></template>
        <p class="surface-intro">采购到货继续由采购模块跟踪；本页展示材料需求、仓库供料、采购到货和样品领料记录。</p>
        <nav v-if="categoryTabs.length > 1" class="material-detail-tabs" aria-label="材料分类">
          <button type="button" :class="{ active: categoryFilter === 'all' }" @click="categoryFilter = 'all'">全部材料 {{ progress?.lines.length || 0 }}</button>
          <button v-for="tab in categoryTabs" :key="tab.key" type="button" :class="{ active: categoryFilter === tab.key }" @click="categoryFilter = tab.key">{{ tab.label }} {{ tab.count }}</button>
        </nav>
        <div v-if="progress?.lines.length" class="material-detail-table-wrap">
          <table class="material-detail-table">
            <thead><tr><th>材料分类</th><th>材料名称</th><th>规格</th><th>材质</th><th>颜色 / 色卡 / 色号</th><th>需求数量</th><th>仓库可供</th><th>需采购</th><th>已到货</th><th>实际领料</th><th>未领缺口</th><th>单位</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="line in visibleLines" :key="line.key">
                <td>{{ sampleMaterialCategories.find((category) => category.key === line.category)?.label || line.category || '—' }}</td>
                <td class="primary-text">{{ line.name || '—' }}</td><td class="specification">{{ line.specification || '—' }}</td><td>{{ line.material || '—' }}</td><td>{{ line.color || '—' }}</td>
                <td>{{ line.quantity }}</td><td>{{ line.supplyQuantity }}</td><td>{{ line.procurementQuantity ?? '—' }}</td><td>{{ line.arrivedQuantity }}</td><td>{{ line.issuedQuantity ?? '—' }}</td><td>{{ line.shortageQuantity ?? '—' }}</td><td>{{ line.unitLabel || '—' }}</td>
                <td><SampleStatusTag :status="tagStatus" :label="progress?.label || '—'" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty-detail">{{ progress?.label === '无需用料' ? '打样部已确认无需用料，可进行生产和参数上传。' : '尚未提交用料需求。' }}</p>
        <p v-if="progress?.status === 'PROCUREMENT_PENDING'" class="progress-note">{{ progress.label === '采购中' ? '采购订单已创建，等待采购到货。' : '仓库已提交缺料需求，等待采购创建订单。' }}</p>
        <p v-else-if="progress?.status === 'MATERIAL_ISSUE_PENDING'" class="progress-note">材料已有可供数量，请由打样部发起样品领料。</p>
        <p v-else-if="progress?.status === 'MATERIAL_ISSUE_REVIEW'" class="progress-note">打样部已发起领料，等待仓库确认实际领料数量。</p>
        <p v-else-if="progress?.status === 'MATERIALS_ISSUED'" class="progress-note">已记录实际领料数量，不足部分不补料。</p>
      </SampleSection>
    </template>

  </section>
</template>

<style scoped lang="scss" src="./sampleMaterialDetail.scss"></style>
