<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { actOnProductionTaskImport, fetchImportSources, fetchProductionTaskImport, importImageUrl, importSourceUrl, reviewProductionTaskImport, uploadProductionTaskImport } from '@/api/productionTaskImports'
import type { ImportPayload, ImportReview, ProductionTaskImport, VersionedImport } from '@/types/productionTaskImport'
import { reviewRows } from '@/utils/productionTaskImport'

const props = defineProps<{ payload: ImportPayload; appliedId: string; hasEdits: boolean; busy?: boolean; displayValue: (key: string, value: unknown) => string }>()
const emit = defineEmits<{ apply: [record: ProductionTaskImport]; clear: [] }>()
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const snapshot = ref<VersionedImport | null>(null)
const record = computed(() => snapshot.value?.data)
const working = ref(false), error = ref(''), selectedFile = ref<File | null>(null)
const requestId = ref(crypto.randomUUID())
const confirmed = ref<string[]>([]), resolutions = ref<ImportReview['issues']>({}), selectedImages = ref<ImportReview['selected_images']>({})
const sourceOpen = ref(false), sourceText = ref('')
const rows = computed(() => record.value ? reviewRows(record.value, props.payload) : [])
const importId = computed(() => typeof route.query.import_id === 'string' ? route.query.import_id : '')
let timer: ReturnType<typeof setTimeout> | undefined, controller: AbortController | undefined, sequence = 0
let contextVersion = 0
const currentContext = () => { const version = contextVersion; return () => version === contextVersion }
const stateNames: Record<string, string> = { CHECKING: '等待检查', SCANNING: '安全检查中', QUEUED: '等待 Codex', PARSING: '解析中', NEEDS_SELECTION: '请选择任务/版本', REVIEW: '等待核对', FAILED: '导入失败', CANCELED: '已取消', SAVED: '已保存', EXPIRED: '资料已过期' }
function message(cause: unknown) { const data = (cause as { response?: { data?: { error?: { message?: string; code?: string; field_errors?: Record<string, string[]> } } } }).response?.data?.error; return data?.field_errors ? Object.values(data.field_errors).flat().join('；') : data?.message || (cause instanceof Error ? cause.message : '请求失败，请重试。') }
function stop() { sequence++; clearTimeout(timer); controller?.abort() }
async function load() {
  if (!importId.value) return
  stop(); const run = sequence
  controller = new AbortController()
  try {
    const result = await fetchProductionTaskImport(importId.value, controller.signal)
    if (run !== sequence) return
    snapshot.value = result; error.value = ''
    if (['CHECKING', 'SCANNING', 'QUEUED', 'PARSING'].includes(result.data.state)) timer = setTimeout(load, 2000)
  } catch (cause) { if (run === sequence) error.value = message(cause) }
}
watch(importId, () => { contextVersion++; stop(); working.value = false; snapshot.value = null; sourceOpen.value = false; sourceText.value = ''; confirmed.value = []; resolutions.value = {}; selectedImages.value = {}; error.value = ''; void load() }, { immediate: true })
watch(() => auth.identityGeneration, () => { contextVersion++; stop(); working.value = false; snapshot.value = null; sourceOpen.value = false; sourceText.value = ''; confirmed.value = []; resolutions.value = {}; selectedImages.value = {}; emit('clear') }, { flush: 'sync' })
watch(() => rows.value.map(row => [row.key, JSON.stringify(row.value)] as const), (current, previous) => {
  const before = new Map(previous || [])
  const changed = new Set(current.filter(([key, value]) => before.get(key) !== value).map(([key]) => key))
  confirmed.value = confirmed.value.filter(key => !changed.has(key))
}, { flush: 'sync' })
onBeforeUnmount(() => { contextVersion++; stop() })
function chooseFile(event: Event) { selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null; requestId.value = crypto.randomUUID() }
async function upload() {
  const current = currentContext()
  const file = selectedFile.value
  if (!file || !/\.xlsx$/i.test(file.name) || file.name.startsWith('~$') || file.size <= 0 || file.size > 25 * 1024 * 1024) { error.value = '请选择 25 MiB 以内的 XLSX 文件。'; return }
  working.value = true; error.value = ''
  try {
    const result = await uploadProductionTaskImport(file, requestId.value)
    if (!current()) return
    await router.replace({ query: { ...route.query, import_id: result.data.id } })
  } catch (cause) { if (current()) error.value = message(cause) } finally { if (current()) working.value = false }
}
async function action(name: 'select' | 'cancel' | 'retry' | 'rematch', payload: object = {}) {
  if (!snapshot.value || working.value) return
  const current = currentContext()
  const target = snapshot.value
  if ((name === 'select' || name === 'retry') && props.appliedId) {
    try { await ElMessageBox.confirm('重新解析会清空本次已填表单和核对记录，是否继续？', '重新解析', { type: 'warning' }) } catch { return }
    if (!current()) return
    emit('clear')
  }
  working.value = true; stop()
  try {
    const result = await actOnProductionTaskImport(target.data.id, name, target.etag, payload)
    if (!current()) return
    snapshot.value = result
    if (result.data.id !== importId.value) { emit('clear'); await router.replace({ query: { ...route.query, import_id: result.data.id } }) }
    else if (['QUEUED', 'PARSING', 'SCANNING', 'CHECKING'].includes(result.data.state)) timer = setTimeout(load, 1000)
    error.value = ''
  } catch (cause) { if (current()) error.value = message(cause) } finally { if (current()) working.value = false }
}
async function apply() {
  if (!record.value) return
  const current = currentContext(), target = record.value
  if (props.hasEdits) { try { await ElMessageBox.confirm('将用本次导入内容替换当前未保存表单。请确认已保留需要的手工内容。', '填入创建页', { type: 'warning' }) } catch { return } }
  if (!current()) return
  emit('apply', target)
  await nextTick()
  if (!current()) return
  confirmed.value = [...(target.review.confirmed_fields || [])]
  resolutions.value = JSON.parse(JSON.stringify(target.review.issues || {}))
  selectedImages.value = { ...(target.review.selected_images || {}) }
}
async function saveReview(complete = false) {
  const current = currentContext()
  if (!snapshot.value || record.value?.state !== 'REVIEW' || props.appliedId !== record.value.id) throw new Error('请先将本次导入填入表单，再核对。')
  if (complete && rows.value.some(row => !confirmed.value.includes(row.key))) throw new Error('请逐项确认任务和产品字段；未识别字段需要人工补齐或明确确认。')
  if (complete && record.value.issues.some(issue => !resolutions.value[issue.id]?.note.trim() || (issue.blocking && resolutions.value[issue.id]?.status !== 'RESOLVED'))) throw new Error('请完成关键冲突处理，并为待办填写说明。')
  const result = await reviewProductionTaskImport(record.value.id, { payload: props.payload, confirmed_fields: confirmed.value, issues: resolutions.value, selected_images: selectedImages.value }, snapshot.value.etag)
  if (!current()) throw new Error('页面或 ERP 身份已变化，请重新进入当前账号的导入记录。')
  snapshot.value = result
  return result
}
async function persist() {
  const current = currentContext()
  working.value = true
  try { await saveReview(); if (current()) { ElMessage.success('核对稿已保存，可通过当前链接继续。手工选择的本地图片刷新后需重新选择。'); error.value = '' } }
  catch (cause) { if (current()) error.value = message(cause) } finally { if (current()) working.value = false }
}
function setResolution(id: string, value: Partial<{ status: 'RESOLVED' | 'TODO'; note: string }>) { resolutions.value[id] = { ...(resolutions.value[id] || { status: 'TODO', note: '' }), ...value } }
async function showSource(ids: string[] = []) {
  const current = currentContext()
  if (!record.value) return
  working.value = true
  try {
    const manifest = await fetchImportSources(record.value.id)
    if (!current()) return
    if (!ids.length) sourceText.value = JSON.stringify(manifest, null, 2)
    else {
      const index = manifest.source_index as Record<string, unknown>
      const sheets = manifest.sheets as { cells: { source_id: string }[]; comments: { source_id: string }[]; pictures: { source_id: string }[] }[]
      const entries = sheets.flatMap(sheet => [...sheet.cells, ...sheet.comments, ...sheet.pictures])
      sourceText.value = JSON.stringify(ids.map(id => ({ source_id: id, location: index[id], content: entries.find(entry => entry.source_id === id) })), null, 2)
    }
    sourceOpen.value = true
  } catch (cause) { if (current()) error.value = message(cause) } finally { if (current()) working.value = false }
}
async function leave() {
  const current = currentContext()
  try { await ElMessageBox.confirm('将清空当前表单并退出本次导入。已保存的核对稿仍可通过原链接继续。', '结束本次导入', { type: 'warning' }) } catch { return }
  if (!current()) return
  stop(); emit('clear'); selectedFile.value = null; requestId.value = crypto.randomUUID()
  const query = { ...route.query }; delete query.import_id
  await router.replace({ query })
}
function clearSelectedImage(key: string) { selectedImages.value[key] = null }
defineExpose({ saveReview, clearSelectedImage })
</script>

<template>
  <section class="task-import-panel" aria-label="生产任务单 AI 导入" :aria-busy="working">
    <div class="import-heading"><div><h2>从文件预填生产任务单</h2><p>上传 XLSX → 选择任务和版本 → 核对原创建表单 → 保存草稿。未保存资料保留 7 天。</p></div><el-button v-if="importId" :disabled="working || busy" @click="leave">结束本次导入</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="!importId" class="import-actions"><input type="file" accept=".xlsx" aria-label="选择生产任务 XLSX" :disabled="working || busy" @change="chooseFile"/><el-button type="primary" :loading="working" :disabled="!selectedFile || busy" @click="upload">上传并解析</el-button></div>
    <template v-else-if="record">
      <div class="import-actions"><strong>{{ record.original_name }}</strong><el-tag>{{ stateNames[record.state] || record.state }} · {{ record.phase === 'discovery' ? '识别任务' : '提取内容' }}</el-tag><el-button :disabled="working || busy" @click="load">刷新状态</el-button><el-button v-if="record.scan_status === 'CLEAN' && record.state !== 'EXPIRED'" :disabled="working" @click="showSource()">查看来源</el-button><a v-if="record.scan_status === 'CLEAN' && record.state !== 'EXPIRED'" :href="importSourceUrl(record.id)" target="_blank" rel="noopener">下载原件</a></div>
      <p v-if="record.error_code || record.blocked_reason" role="alert">{{ record.error_code || record.blocked_reason }}：请处理提示后再继续；需要时联系 Codex 连接管理员。</p>
      <div class="import-actions"><el-button v-if="['FAILED', 'CANCELED'].includes(record.state)" :disabled="working || busy" @click="action('retry')">重试</el-button><el-button v-if="!['SAVED', 'EXPIRED', 'CANCELED'].includes(record.state)" :disabled="working || busy" @click="action('cancel')">取消本次解析</el-button></div>
      <el-alert v-if="record.state === 'EXPIRED'" title="未保存资料已过期，请重新上传原文件。" type="warning" :closable="false"/>
      <el-alert v-if="record.state === 'SAVED'" :title="`已保存为 ${record.saved_task_number}，重复提交不会再次建单。`" type="success" :closable="false"/>
      <router-link v-if="record.state === 'SAVED' && record.saved_task_id" :to="{ name: 'production-task-detail', params: { taskId: record.saved_task_id } }">打开已保存草稿</router-link>
      <template v-if="record.state === 'NEEDS_SELECTION'">
        <p>请按产品、工作表及版本选择一个任务。BOM 仅作为参考资料；不确定的归组必须人工确认。</p>
        <div v-for="candidate in record.candidates" :key="candidate.object_id" class="import-candidate"><strong>{{ candidate.task_number_original || '编号未识别' }} · {{ candidate.product_summary }}</strong><p>{{ candidate.version_description || '版本未标明' }} · {{ candidate.sheets.map(sheet => `${sheet.name}${sheet.state !== 'visible' ? '（隐藏）' : ''}`).join('、') }}</p><p v-if="candidate.grouping_uncertain">待确认：{{ candidate.uncertainty_reason }}</p><el-button :disabled="working || busy" @click="action('select', { object_id: candidate.object_id })">确认此任务/版本</el-button></div>
      </template>
      <p v-if="record.duplicates.length">此文件已有其他导入记录，选择相同对象时会复用原记录；不同版本可以分别创建。</p>
      <template v-if="record.state === 'REVIEW'">
        <div class="import-actions"><el-button type="primary" :disabled="working || busy" @click="apply">{{ record.review.payload ? '恢复已保存核对稿' : '填入当前创建表单' }}</el-button><el-button :disabled="working || busy" @click="action('rematch')">重新匹配基础资料</el-button><el-button :disabled="working || busy || appliedId !== record.id" @click="persist">暂存核对稿</el-button></div>
        <p>修改下方原表单后，在这里逐项确认。未识别和冲突值不会直接预填；产品匹配结果只供选择，不会新增产品或 BOM。</p>
        <p>订单币种 CNY 来自现有表单规则，不代表文件已识别为人民币。外币金额不会自动换算，人民币单价须核对后填写。</p>
        <div v-for="(match, lineKey) in record.matching.products" :key="lineKey" class="match-note">产品 {{ lineKey }}：{{ { MATCHED: '找到一个候选', AMBIGUOUS: '多个候选，需人工选择', UNMATCHED: '未匹配，请在原编辑器选择或填写' }[match.status] || match.status }}<span v-for="candidate in match.candidates" :key="candidate.id"> · {{ candidate.name }} / {{ candidate.specification }}</span></div>
        <el-collapse v-if="appliedId === record.id"><el-collapse-item title="字段核对（全部确认后才能保存草稿）" name="fields"><el-table :data="rows" max-height="460"><el-table-column label="字段" prop="label" min-width="160"/><el-table-column label="识别结果" min-width="190"><template #default="{ row }"><span>{{ row.source?.status === 'EXTRACTED' ? String(row.source.value) : row.source?.status === 'CONFLICT' ? '冲突，请处置' : '未识别，请人工核对' }}</span><el-button v-if="row.source?.source_ids.length" link @click="showSource(row.source.source_ids)">来源</el-button></template></el-table-column><el-table-column label="当前表单" min-width="160"><template #default="{ row }">{{ displayValue(row.key, row.value) }}</template></el-table-column><el-table-column label="人工确认" width="105"><template #default="{ row }"><el-checkbox :model-value="confirmed.includes(row.key)" :disabled="working || busy" :aria-label="`确认${row.label}`" @change="(value: boolean | string | number) => { confirmed = value ? [...confirmed, row.key] : confirmed.filter(key => key !== row.key) }">已核对</el-checkbox></template></el-table-column></el-table></el-collapse-item></el-collapse>
        <div v-for="issue in record.issues" :key="issue.id" class="import-issue"><strong>{{ issue.blocking ? '必须解决' : '可留待办' }} · {{ issue.message }}</strong><el-button v-if="issue.source_ids.length" link @click="showSource(issue.source_ids)">来源</el-button><el-select :model-value="resolutions[issue.id]?.status || 'TODO'" :disabled="working || busy" @update:model-value="(value: 'RESOLVED' | 'TODO') => setResolution(issue.id, { status: value })"><el-option label="待办" value="TODO"/><el-option label="已解决" value="RESOLVED"/></el-select><el-input :model-value="resolutions[issue.id]?.note || ''" type="textarea" maxlength="2000" placeholder="填写处理结果或后续待办" :disabled="working || busy" @update:model-value="(value: string) => setResolution(issue.id, { note: value })"/></div>
        <div v-for="(item, index) in record.extraction.unmapped_content" :key="index" class="import-issue"><span>未映射内容：{{ item.summary }}</span><el-button link @click="showSource(item.source_ids)">查看来源</el-button></div>
        <div v-if="record.extraction.image_candidates?.length" class="import-images"><div v-for="image in record.extraction.image_candidates" :key="image.image_id"><img :src="importImageUrl(record.id, image.image_id)" :alt="image.note || image.image_id" loading="lazy"/><p>{{ image.note || '请核对图片用途' }}</p></div></div>
        <div v-for="(product, index) in record.extraction.products" :key="product.line_key" class="import-actions"><label :for="`import-image-${product.line_key}`">产品 {{ index + 1 }} 的主图</label><el-select :id="`import-image-${product.line_key}`" v-model="selectedImages[product.line_key]" clearable :disabled="working || busy" @clear="selectedImages[product.line_key] = null"><el-option v-for="image in record.extraction.image_candidates" :key="image.image_id" :value="image.image_id" :label="`${image.image_id} · ${image.note || '未标明用途'}`"/></el-select><small>不选则不附图；生产/包装图片继续保留在来源中。</small></div>
      </template>
    </template>
    <div v-else class="import-actions"><span>正在读取导入记录…</span><el-button :disabled="working" @click="load">重新读取</el-button></div>
    <el-dialog v-model="sourceOpen" title="原文件来源" width="min(900px, 92vw)"><pre class="source-text">{{ sourceText }}</pre></el-dialog>
  </section>
</template>

<style scoped>
.task-import-panel { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 18px; margin-bottom: 20px; background: var(--el-bg-color); }
.import-heading, .import-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.import-heading { justify-content: space-between; }.import-heading h2 { font-size: 17px; margin: 0 0 6px; }.task-import-panel p { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.import-candidate, .import-issue { padding: 12px; margin: 10px 0; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }.import-issue .el-select { width: 110px; margin: 8px; }.import-images { display: flex; gap: 16px; flex-wrap: wrap; }.import-images > div { max-width: 200px; }.import-images img { width: 160px; height: 120px; object-fit: contain; }.match-note { font-size: 13px; padding: 6px 0; }.source-text { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 60vh; overflow: auto; }
</style>
