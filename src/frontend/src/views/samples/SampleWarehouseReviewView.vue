<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { fetchSample } from '@/api/samples'
import { fetchSampleWarehouseReview, saveSampleWarehouseReview } from '@/api/sampleWarehouse'
import SampleMaterialProgress from '@/components/samples/SampleMaterialProgress.vue'
import SampleWarehouseComparison from '@/components/samples/SampleWarehouseComparison.vue'
import SampleInventoryLookup from '@/components/samples/SampleInventoryLookup.vue'
import SampleReadonlyField from '@/components/samples/SampleReadonlyField.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import { sampleProductsLabel, sampleQuantityLabel } from '@/utils/samplePresentation'
import { sampleShortageLines, sampleSupplyResult, validateSampleWarehouse } from '@/utils/sampleWarehouse'
import type { SampleDetail } from '@/types/sample'
import type { SampleWarehouseDraft, SampleWarehouseLoadResult, SampleWarehouseLine } from '@/types/sampleWarehouse'
import { sampleMaterialError } from '@/utils/sampleMaterial'

const route = useRoute(), router = useRouter()
const sample = ref<SampleDetail | null>(null)
const loading = ref(true), saving = ref(false), available = ref(false)
const etag = ref(''), errorMessage = ref(''), materialsError = ref(''), actionError = ref('')
const canEdit = ref(false)
const inventoryOpen = ref(false), inventoryLineKey = ref('')
function openInventory(key = '') { inventoryLineKey.value = key; inventoryOpen.value = true }
function applyInventory(lines: SampleWarehouseLine[]) { if (canEdit.value && !saving.value) draft.lines = lines }
const draft = reactive<SampleWarehouseDraft>({ lines: [], notes: '' })
const initialDraft = ref(JSON.stringify(draft))
useSampleUnsavedChanges(() => initialDraft.value !== JSON.stringify(draft), '离开仓库核对页')
const shortageLines = computed(() => sampleShortageLines(draft))
const checkedCount = computed(() => draft.lines.filter(line => sampleSupplyResult(line.quantity, line.supplyQuantity).valid).length)
const fullCount = computed(() => draft.lines.filter(line => sampleSupplyResult(line.quantity, line.supplyQuantity).result === 'full').length)
const submitLabel = computed(() => '确认采购')
const fields = computed(() => sample.value ? [
  { label: '客户', value: sample.value.customer_name }, { label: '样品', value: sampleProductsLabel(sample.value) },
  { label: '打样数量', value: sampleQuantityLabel(sample.value) }, { label: '期望完成', value: sample.value.sample_due_date || sample.value.requested_due_at?.slice(0, 10) },
] : [])
async function loadMaterials() {
  if (!sample.value) return
  canEdit.value = false
  etag.value = ''
  try {
    const result = await fetchSampleWarehouseReview(sample.value.id)
    applyResult(result)
  } catch { materialsError.value = '材料需求读取失败，请重试。'; available.value = false }
}
function applyResult(result: SampleWarehouseLoadResult) {
  available.value = result.available
  canEdit.value = result.available && result.canEdit
  if (!result.available) { materialsError.value = result.reason; return }
  Object.assign(draft, result.draft)
  draft.lines = draft.lines.map(line => ({ ...line, inventoryAllocations: line.inventoryAllocations || [] }))
  initialDraft.value = JSON.stringify(draft)
  etag.value = result.etag
  if (sample.value) { sample.value.status = result.status; sample.value.status_display = result.statusLabel }
  materialsError.value = ''
}
async function loadPage() {
  loading.value = true
  available.value = false
  canEdit.value = false
  errorMessage.value = ''
  try {
    if (typeof route.params.sampleId !== 'string' || !route.params.sampleId) throw new Error('缺少申请编号。')
    const result = await fetchSample(route.params.sampleId)
    sample.value = result.data
    await loadMaterials()
  } catch (error) {
    errorMessage.value = error instanceof AxiosError && error.response?.status === 403 ? '当前账号没有查看此申请的权限。' : error instanceof AxiosError && error.response?.status === 404 ? '未找到此打样申请。' : '申请加载失败，请重试。'
  } finally { loading.value = false }
}
async function submitReview() {
  if (!sample.value || !available.value || saving.value || loading.value || !canEdit.value) return
  actionError.value = ''
  const validation = validateSampleWarehouse(draft)
  if (validation) { actionError.value = validation; return }
  saving.value = true
  try {
    const result = await saveSampleWarehouseReview({ sampleId: sample.value.id, etag: etag.value, draft: { lines: draft.lines.map(line => ({ ...line })), notes: draft.notes }, submit: true })
    applyResult(result)
    ElMessage.success('供料核对已提交。')
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
onMounted(loadPage)
</script>

<template>
    <section class="warehouse-review-page" aria-label="仓库核对材料需求">
      <div v-loading="loading" class="warehouse-content">
        <header class="warehouse-page-heading">
          <div class="warehouse-heading-row">
            <div class="warehouse-heading-copy">
              <div class="warehouse-heading-main"><h1>仓库核对材料需求</h1><SampleStatusTag v-if="sample" appearance="page" :status="sample.status" :label="sample.status_display" /></div>
              <p>申请编号 {{ sample?.request_number || '—' }}</p>
            </div>
            <div class="warehouse-heading-actions">
              <ElButton v-if="!canEdit && sample?.status === 'MATERIAL_ISSUE_PENDING'" type="primary" @click="router.push({ name: 'sample-material-issue', params: { sampleId: sample.id } })">发起样品领料</ElButton>
              <ElButton v-if="!canEdit && sample?.status === 'MATERIAL_ISSUE_REVIEW'" type="primary" @click="router.push({ name: 'sample-material-issue-confirm', params: { sampleId: sample.id } })">确认实际领料</ElButton>
              <ElButton v-if="!canEdit && sample && ['METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'].includes(sample.status)" @click="router.push({ name: 'sample-detail', params: { sampleId: sample.id } })">查看生产进度</ElButton>
              <ElButton type="primary" class="submit-action" :loading="saving" :disabled="loading || saving || !canEdit" @click="submitReview">{{ submitLabel }}</ElButton>
            </div>
          </div>
        </header>
        <div v-if="errorMessage" role="alert" class="warehouse-error"><p>{{ errorMessage }}</p><ElButton @click="loadPage">重新加载</ElButton></div>
        <template v-else-if="sample">
          <div v-if="actionError" role="alert" class="warehouse-inline-message">{{ actionError }}</div>
          <section class="warehouse-application"><SampleReadonlyField v-for="field in fields" :key="field.label" :label="field.label" :value="field.value" /><ElButton link @click="router.push({ name: sample.application_actions?.is_application ? 'sample-director-review' : 'sample-detail', params: { sampleId: sample.id } })">查看原申请</ElButton></section>
          <section class="warehouse-statistics" aria-label="材料核对统计"><div><span>需求材料</span><strong>{{ available ? `${draft.lines.length} 项` : '—' }}</strong></div><div><span>已核对</span><strong>{{ available ? `${checkedCount} / ${draft.lines.length} 项` : '—' }}</strong></div><div><span>全额可供</span><strong class="success">{{ available ? `${fullCount} 项` : '—' }}</strong></div><div><span>需采购</span><strong class="shortage">{{ available ? `${shortageLines.length} 项` : '—' }}</strong></div></section>
          <SampleMaterialProgress v-if="!canEdit && available && sample.status !== 'WAREHOUSE_PENDING'" :sample-id="sample.id" :version="etag" />
          <SampleWarehouseComparison v-else v-model="draft.lines" :available="available" :fullscreen="false" :error-message="materialsError" :disabled="saving || !canEdit" @retry="loadMaterials" @lookup="openInventory" />
          <div class="warehouse-notes"><label for="warehouse-notes">仓库备注（选填）</label><ElInput id="warehouse-notes" v-model="draft.notes" :disabled="!canEdit || saving" maxlength="2000" placeholder="填写供料安排或需要采购注意的事项" /></div>
        </template>
      </div>
    </section>
  <SampleInventoryLookup v-if="sample" v-model="inventoryOpen" :sample-id="sample.id" :lines="draft.lines" :active-line-key="inventoryLineKey" @apply="applyInventory" />
</template>

<style scoped lang="scss" src="./sampleWarehouseReview.scss"></style>
