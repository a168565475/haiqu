<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAxiosError } from 'axios'
import { Document, Refresh, Setting, Upload, View, Hide } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import {
  aiImportErrorMessage, clearAiOpenAiConfig, createAiProductionBoms, createAiProductionTaskDraft,
  deleteAiProductionImport, fetchAiOpenAiConfig, fetchAiProductionImport, listAiProductionImports,
  saveAiImportReview, saveAiOpenAiConfig, uploadAiProductionImport, remapAiProductionImport, matchAiProductionMaterials,
  selectAiImportTask,
  restoreAiImportReview,
} from '@/api/aiProductionImport'
import type { AiImportReasoningSettings, AiImportRecordSummary, AiOpenAiConfig, AiProductionImportRecord, AiProductionImportResponse } from '@/types/aiProductionImport'
import AiImportTaskForm from '@/components/production/AiImportTaskForm.vue'
import AiImportBomForm from '@/components/production/AiImportBomForm.vue'

const route = useRoute()
const router = useRouter()
const config = ref<AiOpenAiConfig | null>(null)
const configId = ref('')
const configEtag = ref('')
const configLoading = ref(false)
const configSaving = ref(false)
const configEditing = ref(false)
const configError = ref('')
const label = ref('生产任务导入')
const provider = ref('openai')
const model = ref('gpt-6.1-sol')
const reasoning = ref<AiImportReasoningSettings>({ document_reasoning_effort: 'auto', material_reasoning_effort: 'auto' })
const reasoningSteps = [
  { field: 'document_reasoning_effort', label: '读表推理强度', gpt6Default: '很高' },
  { field: 'material_reasoning_effort', label: '对应 ERP 材料推理强度', gpt6Default: '中' },
] as const
const effortLabels = { low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' }
const isGpt6 = computed(() => model.value.trim().startsWith('gpt-6'))
const baseUrl = ref('')
const apiKey = ref('')
const showApiKey = ref(false)
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadError = ref('')
const record = ref<AiProductionImportRecord | null>(null)
const recordRevision = ref(0)
const importEtag = ref('')
const refreshing = ref(false)
const taskDraft = ref<Record<string, unknown> | null>(null)
const bomDraft = ref<Array<Record<string, unknown>> | null>(null)
const taskForm = ref<InstanceType<typeof AiImportTaskForm>>()
const bomForm = ref<InstanceType<typeof AiImportBomForm>>()
const taskWriting = ref(false)
const bomWriting = ref(false)
const remapping = ref(false)
const matchingMaterials = ref(false)
const saving = ref(false)
const switchingTask = ref(false)
const saveError = ref('')
const savedSignature = ref('')
const historyOpen = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const historyRows = ref<AiImportRecordSummary[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
let saveTimer: ReturnType<typeof setTimeout> | undefined
let savePromise: Promise<boolean> | null = null

const isConfigured = computed(() => Boolean(config.value?.key_configured ?? config.value?.configured))
const hasResult = computed(() => Boolean(record.value && Object.keys(record.value.result || {}).length))
const activeTaskKey = computed(() => record.value?.active_task_key || 'main')
const activeResult = computed<Record<string, unknown>>(() => {
  const result = record.value?.result || {}
  if (activeTaskKey.value === 'main') return result
  const tasks = Array.isArray(result.additional_tasks) ? result.additional_tasks as Array<Record<string, unknown>> : []
  return { ...(tasks.find(item => item.task_key === activeTaskKey.value) || {}), recognition_meta: result.recognition_meta }
})
const draftSignature = computed(() => JSON.stringify({ task_key: activeTaskKey.value, task_payload: taskDraft.value, bom_plans: bomDraft.value }))
const dirty = computed(() => hasResult.value && draftSignature.value !== savedSignature.value)
const canCreateTask = computed(() => hasResult.value && record.value?.state === 'REVIEW' && !record.value.task_id)
const canCreateBoms = computed(() => Boolean(record.value?.task_id && ['READY', 'IN_PRODUCTION'].includes(record.value.task_status || '') && !record.value.bom_ids?.length))
const busy = computed(() => uploading.value || refreshing.value || taskWriting.value || bomWriting.value || remapping.value || matchingMaterials.value || switchingTask.value)
const productQuantities = computed(() => Object.fromEntries(
  (Array.isArray(taskDraft.value?.products) ? taskDraft.value.products : []).map((item: Record<string, unknown>) => [String(item.client_key), String(item.quantity || '')]),
))
function stateLabel(state: string) {
  return ({ REVIEW: '待核对', FAILED: '识别失败', RECOGNIZING: '正在识别', TASK_DRAFT: '任务草稿已创建', BOM_PENDING: 'BOM 已创建' } as Record<string, string>)[state] || state
}
function dateText(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function showError(error: unknown, fallback: string) {
  return error instanceof Error && !('isAxiosError' in error) ? error.message : aiImportErrorMessage(error, fallback)
}

function applyConfig(data: AiOpenAiConfig, etag: string) {
  config.value = data
  configId.value = data.id || ''
  configEtag.value = etag
  label.value = data.label || label.value
  provider.value = data.provider || provider.value
  model.value = data.model || model.value
  reasoning.value = {
    document_reasoning_effort: data.document_reasoning_effort ?? 'auto',
    material_reasoning_effort: data.material_reasoning_effort ?? 'auto',
  }
  baseUrl.value = data.base_url || ''
}

async function loadConfig() {
  configLoading.value = true
  configError.value = ''
  try {
    const response = await fetchAiOpenAiConfig()
    applyConfig(response.data, response.etag)
  } catch {
    configError.value = 'OpenAI 配置读取失败，请检查服务端接口。'
  } finally {
    configLoading.value = false
  }
}

function beginConfigEdit() {
  if (config.value) applyConfig(config.value, configEtag.value)
  if (config.value) configError.value = ''
  configEditing.value = true
  apiKey.value = ''
  showApiKey.value = false
}
function closeConfig(done?: () => void) {
  if (configSaving.value) return
  configEditing.value = false
  done?.()
}
watch(configEditing, value => {
  if (!value) { apiKey.value = ''; showApiKey.value = false }
})

async function submitConfig() {
  if (!label.value.trim() || !provider.value.trim() || !model.value.trim()) {
    configError.value = '请填写 Key 标签、服务商和模型。'
    return
  }
  if (!apiKey.value.trim() && !isConfigured.value) {
    configError.value = '首次配置必须输入完整 API Key。'
    return
  }
  configSaving.value = true
  configError.value = ''
  try {
    const response = await saveAiOpenAiConfig({
      label: label.value.trim(), provider: provider.value.trim(), model: model.value.trim(),
      ...reasoning.value, base_url: baseUrl.value.trim(), api_key: apiKey.value.trim(),
    }, configEtag.value, configId.value)
    applyConfig(response.data, response.etag)
    configEditing.value = false
    apiKey.value = ''
    ElMessage.success('OpenAI 配置已保存。')
  } catch {
    configError.value = 'OpenAI 配置保存失败，当前输入仍保留。'
  } finally {
    configSaving.value = false
  }
}

async function removeConfig() {
  if (!configId.value) return
  try {
    await ElMessageBox.confirm('清除后，新识别任务将无法调用 OpenAI。确认清除当前配置吗？', '清除 OpenAI 配置', { type: 'warning' })
  } catch {
    return
  }
  configSaving.value = true
  try {
    await clearAiOpenAiConfig(configId.value, configEtag.value)
    config.value = { id: '', label: '', provider: 'openai', model: 'gpt-6-astra', key_configured: false, key_last4: '', key_fingerprint: '', updated_at: null }
    configId.value = ''
    configEditing.value = false
    ElMessage.success('OpenAI 配置已清除。')
  } catch {
    configError.value = 'OpenAI 配置清除失败。'
  } finally {
    configSaving.value = false
  }
}


function applyRecord(response: AiProductionImportResponse, resetDraft = false) {
  const changed = record.value?.id !== response.data.id
  record.value = response.data
  importEtag.value = response.etag || ''
  if (changed || resetDraft) {
    recordRevision.value++
    taskDraft.value = response.data.review_draft?.task_payload || null
    bomDraft.value = response.data.review_draft?.bom_plans || null
    savedSignature.value = draftSignature.value
    saveError.value = ''
  }
}
async function saveDraft(): Promise<boolean> {
  if (saveTimer) clearTimeout(saveTimer)
  if (savePromise) {
    const success = await savePromise
    return success && dirty.value ? saveDraft() : success
  }
  if (!record.value || !dirty.value) return true
  const id = record.value.id
  const signature = draftSignature.value
  saving.value = true
  saveError.value = ''
  savePromise = (async () => {
    try {
      const response = await saveAiImportReview(id, JSON.parse(signature), importEtag.value)
      if (record.value?.id === id) {
        record.value = response.data
        importEtag.value = response.etag || ''
        savedSignature.value = signature
      }
      return true
    } catch (error) {
      saveError.value = showError(error, '修改未保存，请重试。当前表单仍保留。')
      return false
    } finally {
      saving.value = false
      savePromise = null
    }
  })()
  return savePromise
}
watch(draftSignature, () => {
  if (saveTimer) clearTimeout(saveTimer)
  if (dirty.value && !busy.value) saveTimer = setTimeout(() => { void saveDraft() }, 900)
})
watch(busy, value => { if (!value && dirty.value) saveTimer = setTimeout(() => { void saveDraft() }, 900) })

async function switchRecognizedTask(taskKey: string) {
  if (!record.value || busy.value || taskKey === activeTaskKey.value) return
  switchingTask.value = true
  try {
    if (!(await saveDraft())) return
    applyRecord(await selectAiImportTask(record.value.id, taskKey, importEtag.value), true)
  } catch (error) {
    saveError.value = showError(error, '切换任务失败，当前核对内容仍保留。')
  } finally { switchingTask.value = false }
}

async function restorePreviousReview() {
  if (!record.value || busy.value || record.value.has_created_tasks) return
  switchingTask.value = true
  try {
    if (!(await saveDraft())) return
    applyRecord(await restoreAiImportReview(record.value.id, importEtag.value), true)
    ElMessage.success('已恢复上一版识别结果及核对稿。')
  } catch (error) {
    saveError.value = showError(error, '恢复失败，当前核对稿仍保留。')
  } finally { switchingTask.value = false }
}

function selectFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  selectedFile.value = file
  uploadError.value = ''
  if (file && !/\.(xlsx|xls)$/i.test(file.name)) {
    selectedFile.value = null
    uploadError.value = '只支持 XLSX 或 XLS 文件。'
  }
}
async function startRecognition() {
  if (busy.value) return
  if (!selectedFile.value) { uploadError.value = '请先选择一个任务文件。'; return }
  if (!isConfigured.value) { uploadError.value = '请先配置 OpenAI Key。'; return }
  uploading.value = true
  uploadError.value = ''
  try {
    if (!(await saveDraft())) return
    const response = await uploadAiProductionImport(selectedFile.value, crypto.randomUUID())
    applyRecord(response, true)
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
    await router.replace({ query: { ...route.query, importId: response.data.id } })
    ElMessage.success('识别结果已保存。')
  } catch (error) {
    uploadError.value = showError(error, '识别失败，未创建生产任务或 BOM。可在识别记录中查看。')
    const rawId = isAxiosError(error) ? error.response?.data?.error?.field_errors?.record_id : undefined
    const savedId = Array.isArray(rawId) ? rawId.find(value => typeof value === 'string') : rawId
    if (typeof savedId === 'string' && savedId) {
      selectedFile.value = null
      if (fileInput.value) fileInput.value.value = ''
      try {
        applyRecord(await fetchAiProductionImport(savedId), true)
        await router.replace({ query: { ...route.query, importId: savedId } })
      } catch {
        saveError.value = '表格识别结果已保存，但读取失败；请从识别记录继续核对，无需重新上传。'
        uploadError.value += ' 表格结果已保存，请从识别记录继续，无需重新上传。'
      }
    }
  } finally { uploading.value = false }
}
async function openRecord(id: string) {
  if (busy.value) return
  refreshing.value = true
  uploadError.value = ''
  try {
    if (!(await saveDraft())) return
    applyRecord(await fetchAiProductionImport(id), true)
    historyOpen.value = false
    await router.replace({ query: { ...route.query, importId: id } })
  } catch (error) {
    uploadError.value = showError(error, '识别记录读取失败。')
  } finally { refreshing.value = false }
}
async function refresh() {
  if (!record.value || busy.value) return
  refreshing.value = true
  try {
    if (!(await saveDraft())) return
    const firstResult = !hasResult.value
    applyRecord(await fetchAiProductionImport(record.value.id), firstResult)
  } catch (error) { uploadError.value = showError(error, '读取状态失败。') }
  finally { refreshing.value = false }
}
async function remapFields() {
  if (!record.value || busy.value || record.value.has_created_tasks || record.value.task_id) return
  const recordId = record.value.id
  try {
    await ElMessageBox.confirm('使用已保存的表格文字重新调用 OpenAI，对应 ERP 字段？会产生 API 用量，并以新结果重新填写核对表单；上一版资料会保留。', '重新对应 ERP 字段', { confirmButtonText: '开始对应', cancelButtonText: '取消' })
  } catch { return }
  if (busy.value || record.value?.id !== recordId) return
  remapping.value = true
  uploadError.value = ''
  try {
    if (!(await saveDraft())) return
    applyRecord(await remapAiProductionImport(recordId, importEtag.value), true)
    ElMessage.success('已重新对应 ERP 字段，请核对表单。')
  } catch (error) {
    uploadError.value = showError(error, '重新对应失败，原结果和核对稿仍保留。')
    try { applyRecord(await fetchAiProductionImport(recordId)) }
    catch { saveError.value = '状态读取失败，重试前请刷新状态。' }
  } finally { remapping.value = false }
}
async function matchMaterials() {
  if (!record.value || busy.value || !hasResult.value) return
  const id = record.value.id
  matchingMaterials.value = true
  uploadError.value = ''
  try {
    if (!(await saveDraft())) return
    applyRecord(await matchAiProductionMaterials(id, importEtag.value))
    saveError.value = ''
    await nextTick()
    bomForm.value?.applyLatestMatches(activeResult.value)
  } catch (error) {
    uploadError.value = showError(error, 'ERP 材料对应失败，当前核对稿已保留，请重试。')
    try { applyRecord(await fetchAiProductionImport(id)) }
    catch { saveError.value = '最新状态读取失败，请刷新状态后重试材料对应。当前核对稿仍保留。' }
  } finally { matchingMaterials.value = false }
}
async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    const response = await listAiProductionImports((historyPage.value - 1) * 20)
    historyRows.value = response.results
    historyTotal.value = response.count
  } catch (error) { historyError.value = showError(error, '识别记录读取失败。') }
  finally { historyLoading.value = false }
}
async function showHistory() { historyOpen.value = true; await loadHistory() }
async function removeRecord(row: AiImportRecordSummary) {
  try {
    await ElMessageBox.confirm('删除“' + row.original_name + '”的识别记录及核对表单？已创建的生产任务和 BOM 会保留。', '删除识别记录', { type: 'warning', confirmButtonText: '删除记录', cancelButtonText: '取消' })
  } catch { return }
  if (row.id === record.value?.id && !(await saveDraft())) return
  try {
    const current = await fetchAiProductionImport(row.id)
    await deleteAiProductionImport(row.id, current.etag || '')
    if (record.value?.id === row.id) {
      record.value = null
      taskDraft.value = null
      bomDraft.value = null
      const query = { ...route.query }; delete query.importId
      await router.replace({ query })
    }
    if (historyRows.value.length === 1 && historyPage.value > 1) historyPage.value--
    await loadHistory()
    ElMessage.success('识别记录已删除。')
  } catch (error) { historyError.value = showError(error, '删除失败，记录仍保留。') }
}
async function createTaskDraft() {
  if (!record.value || !taskForm.value || !canCreateTask.value || busy.value) return
  taskWriting.value = true
  uploadError.value = ''
  try {
    if (!(await saveDraft())) return
    const payload = await taskForm.value.buildPayload()
    applyRecord(await createAiProductionTaskDraft(record.value.id, payload, importEtag.value, activeTaskKey.value))
    ElMessage.success('生产任务草稿已创建。')
  } catch (error) { uploadError.value = showError(error, '任务创建失败，请检查表单。') }
  finally { taskWriting.value = false }
}
async function createBoms() {
  if (!record.value || !bomForm.value || !canCreateBoms.value || busy.value) return
  bomWriting.value = true
  uploadError.value = ''
  try {
    if (!(await saveDraft())) return
    const plans = bomForm.value.buildPlans()
    applyRecord(await createAiProductionBoms(record.value.id, plans, importEtag.value, activeTaskKey.value))
    ElMessage.success('BOM 已创建，等待确认。')
  } catch (error) { uploadError.value = showError(error, 'BOM 创建失败，请检查材料和用量。') }
  finally { bomWriting.value = false }
}
function openTaskImages() {
  if (record.value?.task_id) void router.push({ name: 'production-task-edit', params: { taskId: record.value.task_id } })
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(async () => await saveDraft())
onMounted(async () => {
  window.addEventListener('beforeunload', beforeUnload)
  await loadConfig()
  const id = route.query.importId
  if (typeof id === 'string' && id) await openRecord(id)
})
onBeforeUnmount(() => { if (saveTimer) clearTimeout(saveTimer); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <section class="ai-production-import-page">
    <header class="page-heading">
      <h1>AI 生产任务导入</h1>
      <div class="heading-actions">
        <el-button :icon="Setting" :loading="configLoading" @click="beginConfigEdit">OpenAI 配置</el-button>
        <el-button @click="showHistory">识别记录</el-button>
        <el-button type="primary" :icon="Upload" :disabled="busy" @click="fileInput?.click()">上传表格</el-button>
      </div>
    </header>
    <input ref="fileInput" class="file-input" type="file" accept=".xlsx,.xls" aria-label="生产任务文件" :disabled="busy" @change="selectFile" />
    <el-alert v-if="configError && !configEditing" type="error" :closable="false" :title="configError" />
    <div v-if="selectedFile" class="card selected-file">
      <div class="file-name"><el-icon><Document /></el-icon><strong>{{ selectedFile.name }}</strong><span class="muted">待识别</span></div>
      <el-button type="primary" :loading="uploading" :disabled="busy || configLoading" @click="startRecognition">{{ uploading ? '正在识别…' : '开始识别' }}</el-button>
    </div>
    <p v-if="uploading" class="recognition-progress" role="status">正在识别，完成后自动保存记录，请勿重复提交。</p>
    <el-alert v-if="uploadError" class="page-error" type="error" :closable="false" :title="uploadError" />
    <div v-if="record" class="card record-toolbar">
      <div class="file-context">
        <div class="file-name"><el-icon><Document /></el-icon><strong>{{ record.original_name }}</strong><el-tag size="small">{{ stateLabel(record.state) }}</el-tag></div>
        <div v-if="(record.task_choices?.length || 0) > 1" class="task-tabs" role="tablist" aria-label="本次处理任务">
          <span class="muted">本次处理任务</span>
          <button v-for="item in record.task_choices" :key="item.task_key" type="button" role="tab" :data-task-key="item.task_key" :aria-selected="activeTaskKey === item.task_key" :class="{ active: activeTaskKey === item.task_key }" :disabled="busy || saving" @click="switchRecognizedTask(item.task_key)">{{ item.task_number }}<span v-if="item.state !== 'REVIEW'"> · {{ stateLabel(item.state) }}</span></button>
        </div>
      </div>
      <div class="file-actions">
        <el-button v-if="record.has_previous_recognition && !record.has_created_tasks" link :disabled="busy || saving" @click="restorePreviousReview">恢复上次核对稿</el-button>
        <el-button v-if="!record.task_id && !record.has_created_tasks" link :loading="remapping" :disabled="busy" @click="remapFields">重新对应 ERP 字段</el-button>
        <el-button :icon="Refresh" :loading="refreshing" :disabled="busy" @click="refresh">刷新状态</el-button>
      </div>
    </div>
    <el-alert v-if="record?.error_code" type="error" :closable="false" :title="record.issues[0]?.message || '识别未完成，可在识别记录中保留或删除。'" />
    <template v-if="record && hasResult">
      <section v-loading="remapping" class="card task-block">
        <div v-if="record.task_id" class="section-heading"><h2>生产任务单</h2><el-button @click="openTaskImages">打开任务 / 上传图片</el-button></div>
        <AiImportTaskForm v-if="!record.task_id" :key="`${record.id}:${recordRevision}`" ref="taskForm" v-model="taskDraft" :result="activeResult" :disabled="busy" />
        <p v-else>已创建任务 {{ record.task_number }}。任务信息请在现有任务表单中修改。</p>
      </section>
      <section v-loading="remapping || bomWriting || matchingMaterials" class="card bom-block">
        <p v-if="record.bom_ids?.length" class="created-boms">已创建 {{ record.bom_ids.length }} 个 BOM</p>
        <AiImportBomForm :key="`${record.id}:${recordRevision}`" ref="bomForm" v-model="bomDraft" :result="activeResult" :task-products="record.task_products || []" :product-quantities="productQuantities" :disabled="busy || saving" :matching-materials="matchingMaterials" @match-materials="matchMaterials" />
      </section>
      <details v-if="record.issues.length" class="review-notes"><summary>其他待核对说明（{{ record.issues.length }}）</summary><ul><li v-for="issue in record.issues" :key="issue.id || issue.message">{{ issue.message }}</li></ul></details>
      <footer class="card page-footer">
        <span role="status" class="save-status" :class="{ 'save-error': saveError }">{{ saveError || (saving ? '正在保存…' : dirty ? '有未保存修改' : '已保存') }}</span>
        <div class="footer-actions">
          <el-button :loading="saving" :disabled="!dirty || busy" @click="saveDraft">保存修改</el-button>
          <el-button v-if="!record.task_id" type="primary" :loading="taskWriting" :disabled="!canCreateTask || busy" @click="createTaskDraft">确认创建生产任务草稿</el-button>
          <el-button :loading="bomWriting" :disabled="!canCreateBoms || busy" @click="createBoms">确认创建 BOM</el-button>
          <span v-if="!canCreateBoms && !record.bom_ids?.length" class="muted bom-disabled-reason">任务经 PMC 确认后可创建 BOM</span>
        </div>
      </footer>
    </template>
    <div v-else-if="!record && !uploading && !refreshing" class="card empty-workspace">
      <el-icon class="empty-icon"><Document /></el-icon>
      <h2>上传一个生产任务表格</h2>
      <p>或从识别记录继续核对</p>
      <el-button type="primary" :icon="Upload" :disabled="busy" @click="fileInput?.click()">选择表格</el-button>
      <p class="muted">支持 XLSX、XLS；图片不发送给 OpenAI。</p>
      <el-button v-if="!isConfigured && !configLoading" link type="primary" @click="beginConfigEdit">先配置 OpenAI</el-button>
    </div>
    <AppWindowDialog v-model="configEditing" title="OpenAI 配置" :width="680" class="ai-import-config-dialog" :before-close="closeConfig" :close-on-click-modal="false" :close-on-press-escape="!configSaving" :show-close="!configSaving" destroy-on-close>
      <p class="config-intro">配置按当前账号保存。支持的推理强度取决于所选模型。</p>
      <el-alert v-if="configError" class="config-error" type="error" :closable="false" :title="configError" />
      <el-form class="config-form" label-position="top" :disabled="configSaving" @submit.prevent="submitConfig">
        <el-form-item class="full" label="配置名称"><el-input v-model="label" placeholder="生产任务导入" aria-label="Key 标签" /></el-form-item>
        <el-form-item label="服务商"><el-input v-model="provider" placeholder="openai" aria-label="服务商" /></el-form-item>
        <el-form-item label="模型"><el-input v-model="model" placeholder="模型" aria-label="模型" /></el-form-item>
        <el-form-item v-for="step in reasoningSteps" :key="step.field" :label="step.label">
          <el-select v-model="reasoning[step.field]" :aria-label="step.label">
            <el-option value="auto" :label="`自动（${isGpt6 ? step.gpt6Default : '模型默认'}）`" />
            <el-option v-for="(name, value) in effortLabels" :key="value" :value="value" :label="name" />
          </el-select>
        </el-form-item>
        <el-form-item class="full" label="API Key">
          <el-input v-model="apiKey" :type="showApiKey ? 'text' : 'password'" autocomplete="new-password" placeholder="输入新的 Key；留空则保留已保存的 Key" aria-label="完整 API Key">
            <template #suffix><button class="key-visibility" type="button" :disabled="configSaving" :aria-label="showApiKey ? '隐藏 Key' : '显示 Key'" @click="showApiKey = !showApiKey"><el-icon><Hide v-if="showApiKey" /><View v-else /></el-icon></button></template>
          </el-input>
          <div class="key-note"><span>{{ isConfigured ? '已保存；留空保留当前 Key' : '首次配置请输入完整 Key' }}</span><span v-if="isConfigured">当前 Key：••••{{ config?.key_last4 }}</span></div>
        </el-form-item>
      </el-form>
      <details class="config-advanced"><summary>高级设置<span class="muted">自定义 API 地址</span></summary><label>API 地址<el-input v-model="baseUrl" :disabled="configSaving" placeholder="可选：自定义 API 地址" aria-label="API 地址" /></label></details>
      <template #footer><div class="config-actions"><el-button v-if="isConfigured" link type="danger" :disabled="configSaving" @click="removeConfig">清除配置</el-button><span class="action-spacer" /><el-button :disabled="configSaving" @click="closeConfig()">取消</el-button><el-button type="primary" :loading="configSaving" @click="submitConfig">保存配置</el-button></div></template>
    </AppWindowDialog>
    <el-drawer v-model="historyOpen" title="识别记录" size="min(900px, 95vw)">
      <el-alert v-if="historyError" type="error" :closable="false" :title="historyError" />
      <el-table v-loading="historyLoading" :data="historyRows" empty-text="暂无识别记录">
        <el-table-column prop="original_name" label="文件" min-width="240" />
        <el-table-column label="状态" width="145"><template #default="{ row }">{{ stateLabel(row.state) }}</template></el-table-column>
        <el-table-column label="保存时间" width="175"><template #default="{ row }">{{ dateText(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="135"><template #default="{ row }"><el-button link type="primary" :disabled="busy" @click="openRecord(row.id)">打开</el-button><el-button link type="danger" :disabled="busy" @click="removeRecord(row)">删除</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="historyPage" class="history-pagination" :page-size="20" :total="historyTotal" layout="prev, pager, next, total" @current-change="loadHistory" />
    </el-drawer>
  </section>
</template>

<style scoped lang="scss">
.ai-production-import-page { display: flex; flex-direction: column; gap: 14px; min-height: calc(100dvh - 76px); min-width: 0; color: var(--erp-color-text-primary); }
.page-heading, .section-heading, .heading-actions, .selected-file, .record-toolbar, .file-name, .file-actions, .footer-actions, .page-footer, .config-actions { display: flex; align-items: center; gap: 10px; }
.page-heading, .section-heading, .selected-file, .record-toolbar, .page-footer { justify-content: space-between; }
.page-heading { min-height: 44px; flex-wrap: wrap; }
h1 { margin: 0; font-family: var(--erp-font-display); font-size: 34px; font-weight: 600; line-height: 44px; }
h2 { margin: 0; font-size: 18px; line-height: 26px; }
.heading-actions, .file-actions, .footer-actions { flex-wrap: wrap; }
.heading-actions :deep(.el-button + .el-button), .file-actions :deep(.el-button + .el-button), .footer-actions :deep(.el-button + .el-button), .config-actions :deep(.el-button + .el-button) { margin-left: 0; }
.file-input { display: none; }
.card { border: 1px solid var(--erp-glass-border); border-radius: 16px; background: var(--erp-glass-background); box-shadow: var(--erp-glass-shadow); backdrop-filter: var(--erp-glass-backdrop); min-width: 0; }
.record-toolbar { min-height: 78px; padding: 8px 16px; flex-wrap: wrap; }
.file-context { min-width: 0; flex: 1; }
.file-name { min-height: 27px; min-width: 0; }
.file-name strong { font-size: 13px; font-weight: 550; overflow-wrap: anywhere; }
.file-name .el-icon { font-size: 20px; color: var(--erp-color-primary); flex-shrink: 0; }
.file-name .el-tag { flex-shrink: 0; }
.task-tabs { display: flex; align-items: center; gap: 12px; min-height: 30px; flex-wrap: wrap; }
.task-tabs button { position: relative; min-height: 30px; padding: 0 13px; border: 0; border-radius: 0; background: transparent; color: var(--erp-color-text-secondary); font: inherit; font-size: 13px; cursor: pointer; }
.task-tabs button:hover:not(:disabled) { background: var(--erp-glass-inner-background); }
.task-tabs button.active { color: var(--el-color-primary); font-weight: 600; }
.task-tabs button.active::after { content: ''; position: absolute; bottom: -3px; left: 10px; right: 10px; height: 3px; border-radius: 3px; background: var(--el-color-primary); }
.task-tabs button:disabled { cursor: not-allowed; opacity: .6; }
.selected-file { padding: 12px 16px; }
.recognition-progress { margin: 0; font-size: 13px; }
.task-block { padding: 0 16px 8px; }
.section-heading { min-height: 44px; }
.bom-block { flex: 1; padding: 0 16px 12px; }
.created-boms { margin: 8px 0 0; font-size: 12px; }
.muted, .save-status { color: var(--erp-color-text-secondary); font-size: 12px; }
.save-error { color: var(--el-color-danger); }
.review-notes { padding: 0 16px; color: var(--erp-color-text-secondary); font-size: 12px; }
.review-notes summary { cursor: pointer; line-height: 20px; }
.review-notes li { margin: 6px 0; line-height: 1.6; }
.page-footer { position: sticky; bottom: 0; z-index: 2; min-height: 52px; padding: 9px 16px; gap: 16px; }
.save-status { min-width: 60px; max-width: 440px; }
.footer-actions { justify-content: flex-end; }
.empty-workspace { display: flex; flex: 1; min-height: 360px; align-items: center; justify-content: center; flex-direction: column; padding: 32px; }
.empty-workspace h2 { margin-top: 16px; }
.empty-workspace p { font-size: 13px; color: var(--erp-color-text-secondary); }
.empty-icon { font-size: 40px; color: var(--erp-color-primary); }
.config-intro { margin: 0 0 18px; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 18px; }
.config-error { margin-bottom: 16px; }
.config-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.config-form .full { grid-column: 1 / -1; }
.config-form :deep(.el-form-item) { margin: 0; }
.config-form :deep(.el-form-item__label) { margin: 0; padding-bottom: 6px; font-size: 13px; line-height: 20px; }
.key-visibility { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; padding: 0; border: 0; background: transparent; cursor: pointer; color: var(--erp-color-text-secondary); }
.key-note { width: 100%; display: flex; justify-content: space-between; gap: 8px; margin-top: 4px; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.config-advanced { border-top: 1px solid var(--erp-color-border-subtle); margin-top: 20px; padding-top: 14px; }
.config-advanced summary { cursor: pointer; font-size: 13px; }
.config-advanced summary .muted { float: right; }
.config-advanced label { display: block; margin-top: 16px; font-size: 13px; }
.config-advanced .el-input { margin-top: 6px; }
.config-actions { width: 100%; }
.action-spacer { flex: 1; }
.config-actions > .el-button:not(.is-link) { min-width: 80px; }
.history-pagination { margin-top: 16px; }
@media(max-width: 1100px) { .page-heading, .page-footer { align-items: flex-start; } .page-footer { flex-wrap: wrap; } .record-toolbar { gap: 14px; } .file-actions { margin-left: auto; } }
@media(max-width: 650px) { h1 { font-size: 28px; } .config-form { grid-template-columns: 1fr; } .page-footer { position: static; } .key-note { flex-wrap: wrap; } }
</style>

<style lang="scss">
// 窗口挂载到 body，限定此弹窗覆盖共享组件的默认间距。
.ai-import-config-dialog.app-window-dialog.el-dialog { border-radius: 5px; }
.ai-import-config-dialog.app-window-dialog.el-dialog .el-dialog__title { font-family: var(--erp-font-body) !important; font-size: 16px; font-weight: 600; }
.ai-import-config-dialog.app-window-dialog.el-dialog > .app-window-dialog__body { padding: 16px; }
</style>
