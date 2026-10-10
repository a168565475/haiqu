<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchSample } from '@/api/samples'
import { confirmSampleNoMaterials, fetchSampleMaterials, fetchSampleMaterialUnits, saveSampleMaterials } from '@/api/sampleMaterials'
import SampleMaterialApplicationInfo from '@/components/samples/SampleMaterialApplicationInfo.vue'
import SampleMaterialProgress from '@/components/samples/SampleMaterialProgress.vue'
import SampleMaterialEditor from '@/components/samples/SampleMaterialEditor.vue'
import SampleFullscreenHeader from '@/components/samples/SampleFullscreenHeader.vue'
import { useSampleFullscreen } from '@/composables/useSampleFullscreen'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import { validateSampleMaterials } from '@/utils/sampleMaterial'
import { sampleProductsLabel, sampleQuantityLabel } from '@/utils/samplePresentation'
import type { SampleDetail } from '@/types/sample'
import type { SampleMaterialDraft, SampleMaterialUnit, SampleMaterialLoadResult } from '@/types/sampleMaterial'
import { sampleMaterialError } from '@/utils/sampleMaterial'

const route = useRoute()
const router = useRouter()
const sample = ref<SampleDetail | null>(null)
const etag = ref('')
const loading = ref(true)
const saving = ref(false)
const canEdit = ref(false)
const root = ref<HTMLElement>()
const { fullscreen, toggleFullscreen } = useSampleFullscreen(root)
const errorMessage = ref('')
const unavailableMessage = ref('')
const actionError = ref('')
const unitError = ref('')
const units = ref<SampleMaterialUnit[]>([])
const draft = reactive<SampleMaterialDraft>({ lines: [], notes: '' })
const initialDraft = ref(JSON.stringify(draft))
const editorOpen = ref(false), editorDirty = ref(false)
const dirty = computed(() => editorDirty.value || JSON.stringify(draft) !== initialDraft.value)
useSampleUnsavedChanges(() => dirty.value, '离开材料填写页')

async function loadUnits() {
  unitError.value = ''
  try { units.value = await fetchSampleMaterialUnits() }
  catch { unitError.value = '材料单位加载失败，请重试。' }
}
async function loadPage() {
  canEdit.value = false
  etag.value = ''
  loading.value = true
  errorMessage.value = ''
  try {
    if (typeof route.params.sampleId !== 'string' || !route.params.sampleId) throw new Error('缺少申请编号。')
    const result = await fetchSample(route.params.sampleId)
    sample.value = result.data
    const materials = await fetchSampleMaterials(result.data.id)
    applyResult(materials)
    await loadUnits()
  } catch (error) {
    errorMessage.value = error instanceof AxiosError && error.response?.status === 403 ? '当前账号没有查看此申请的权限。' : error instanceof AxiosError && error.response?.status === 404 ? '未找到此打样申请。' : '材料需求加载失败，请重试。'
  } finally { loading.value = false }
}
function applyResult(materials: SampleMaterialLoadResult) {
  canEdit.value = materials.available && materials.canEdit
  if (!materials.available) { unavailableMessage.value = materials.reason; return }
  Object.assign(draft, materials.draft)
  initialDraft.value = JSON.stringify(draft)
  etag.value = materials.etag
  if (sample.value) { sample.value.status = materials.status; sample.value.status_display = materials.statusLabel }
  unavailableMessage.value = canEdit.value ? '' : '当前材料需求为只读，请在对应流程环节处理。'
}
async function submitMaterials() {
  if (!sample.value || loading.value || saving.value || editorOpen.value || !canEdit.value) return
  actionError.value = ''
  const message = validateSampleMaterials(draft, units.value)
  if (message) { actionError.value = message; return }
  saving.value = true
  try {
    const result = await saveSampleMaterials({ sampleId: sample.value.id, etag: etag.value, draft: structuredClone({ lines: draft.lines.map(line => ({ ...line })), notes: draft.notes }), submit: true })
    applyResult(result)
    ElMessage.success('材料需求已提交仓库。')
    if (result.available) await router.push({ name: 'sample-warehouse-review', params: { sampleId: sample.value.id } })
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
async function noMaterials() {
  if (!sample.value || !canEdit.value || saving.value || editorOpen.value) return
  try { await ElMessageBox.confirm('确认本次打样无需用料？确认后将跳过仓库及采购，直接允许生产。', '确认无需用料', { confirmButtonText: '确认无需用料', cancelButtonText: '取消' }) }
  catch { return }
  saving.value = true; actionError.value = ''
  try {
    const result = await confirmSampleNoMaterials(sample.value.id, etag.value)
    applyResult(result); editorDirty.value = false
    ElMessage.success('已确认无需用料，可进行生产和参数上传。')
    await router.push({ name: 'sample-detail', params: { sampleId: sample.value.id } })
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
onMounted(loadPage)
</script>

<template>
  <Teleport to="body" :disabled="!fullscreen">
    <section ref="root" class="material-request-page" :class="{ 'is-fullscreen': fullscreen }" :data-figma-node="fullscreen ? '1880:19771' : '1878:18504'" aria-label="填写材料需求">
      <SampleFullscreenHeader v-if="fullscreen" title="材料需求 · 全屏填写" :subtitle="`${sample?.request_number || '—'} · ${sample ? sampleProductsLabel(sample) : '—'} · 打样数量 ${sample ? sampleQuantityLabel(sample) : '—'}`" @exit="toggleFullscreen">
        <template #actions><ElButton v-if="canEdit" :disabled="loading || saving || editorOpen" @click="noMaterials">无需用料</ElButton><ElButton type="primary" class="submit-action" :loading="saving" :disabled="loading || saving || editorOpen || !canEdit" @click="submitMaterials">提交仓库</ElButton></template>
      </SampleFullscreenHeader>
      <div v-loading="loading" class="material-content">
        <header v-if="!fullscreen" class="material-page-heading"><div class="material-page-title-row"><h1>填写材料需求</h1><div class="material-heading-actions"><ElButton v-if="canEdit" :disabled="loading || saving || editorOpen" @click="noMaterials">无需用料</ElButton><ElButton v-if="!canEdit && sample?.status === 'MATERIAL_ISSUE_PENDING'" type="primary" @click="router.push({ name: 'sample-material-issue', params: { sampleId: sample.id } })">发起样品领料</ElButton><ElButton v-if="!canEdit && sample?.status === 'MATERIAL_ISSUE_REVIEW'" type="primary" @click="router.push({ name: 'sample-material-issue-confirm', params: { sampleId: sample.id } })">确认实际领料</ElButton><ElButton v-if="!canEdit && sample && ['METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'].includes(sample.status)" type="primary" @click="router.push({ name: 'sample-detail', params: { sampleId: sample.id } })">查看生产进度</ElButton><ElButton type="primary" class="submit-action" :loading="saving" :disabled="loading || saving || editorOpen || !canEdit" @click="submitMaterials">提交仓库</ElButton></div></div></header>
        <div v-if="errorMessage" role="alert" class="material-error"><p>{{ errorMessage }}</p><ElButton @click="loadPage">重新加载</ElButton></div>
        <template v-else-if="sample">
          <div v-if="actionError || unitError" role="alert" class="material-inline-message">
            <template v-if="actionError">{{ actionError }}</template>
            <template v-else>{{ unitError }} <ElButton link @click="loadUnits">重新加载单位</ElButton></template>
          </div>
          <SampleMaterialApplicationInfo v-show="!fullscreen" :sample="sample" />
          <SampleMaterialProgress v-if="!canEdit && !loading" :sample-id="sample.id" :version="etag" />
          <SampleMaterialEditor v-else v-model="draft.lines" :units="units" :fullscreen="fullscreen" :unavailable-message="unavailableMessage" :disabled="loading || saving || !canEdit" @toggle-fullscreen="toggleFullscreen" @editing-change="editorOpen = $event" @dirty-change="editorDirty = $event" />
          <div v-show="!fullscreen" class="material-notes"><label for="material-notes">需求备注（选填）</label><ElInput id="material-notes" v-model="draft.notes" maxlength="2000" :disabled="saving || !canEdit" placeholder="需要补充说明的材料要求" /></div>
        </template>
      </div>
    </section>
  </Teleport>
</template>

<style scoped lang="scss" src="./sampleMaterialRequest.scss"></style>
