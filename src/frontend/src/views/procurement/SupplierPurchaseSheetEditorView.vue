<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, Delete, Document, Download, Picture, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  createSupplierPurchaseSheetVersion,
  deleteSupplierPurchaseSheetLineImage,
  deleteSupplierPurchaseSheetSealImage,
  downloadSupplierPurchaseSheetXlsx,
  fetchSupplierPurchaseSheet,
  fetchSupplierPurchaseSheetPreview,
  publishSupplierPurchaseSheet,
  saveSupplierPurchaseSheet,
  supplierPurchaseSheetLineImageUrl,
  supplierPurchaseSheetSealImageUrl,
  uploadSupplierPurchaseSheetLineImage,
  uploadSupplierPurchaseSheetSealImage,
} from '@/api/purchaseOrders'
import { useAuthStore } from '@/stores/auth'
import PurchaseSheetPublishConfirm from '@/components/procurement/PurchaseSheetPublishConfirm.vue'
import PurchaseSheetOriginalPreview from '@/components/procurement/PurchaseSheetOriginalPreview.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import publishedLock from '@/assets/procurement/published-lock.svg'
import { purchaseSheetPageStatus } from '@/composables/purchaseSheetPageStatus'
import type { PurchaseSheetPreview, SupplierPurchaseSheet, SupplierPurchaseSheetContent, SupplierPurchaseSheetLine } from '@/types/purchaseOrder'
import { formatPurchaseSheetNumber, purchaseSheetLineDisplay, purchaseSheetSourceFields } from '@/utils/purchaseSheetLineDisplay'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const publishing = ref(false)
const publishVisible = ref(false)
const publishError = ref('')
const publishBlocked = ref(false)
const loadError = ref('')
const sheet = ref<SupplierPurchaseSheet | null>(null)
const content = ref<SupplierPurchaseSheetContent | null>(null)
const etag = ref('')
const qualityStandardsText = ref('')
const termOptions = [
  { key: 'payment_and_delivery', label: '二、支付方式和交期' },
  { key: 'quality_standards', label: '三、产品质量标准' },
  { key: 'delivery_handover', label: '四、送货交接' },
  { key: 'special_instructions', label: '五、特别说明' },
  { key: 'dispute_resolution', label: '六、争议解决' },
  { key: 'effectiveness', label: '七、合同生效' },
] as const
type TermKey = typeof termOptions[number]['key']
const showOriginal = ref(true)
const originalPreview = ref<PurchaseSheetPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
let previewRequest = 0
let previewTimer: ReturnType<typeof setTimeout> | undefined
function markOriginalEdit(key: TermKey | 'title'): void {
  if (autoSeal.value && content.value) content.value.original_template_edits = [...new Set([...(content.value.original_template_edits || []), key])]
}
async function refreshOriginalPreview(fromSaved = false): Promise<void> {
  if (!sheet.value || !content.value || !autoSeal.value) return
  const request = ++previewRequest
  previewLoading.value = true
  previewError.value = ''
  try {
    const result = await fetchSupplierPurchaseSheetPreview(sheet.value.id, fromSaved || !editable.value ? undefined : JSON.parse(JSON.stringify(content.value)))
    if (request !== previewRequest) return
    originalPreview.value = result
    if (fromSaved) {
      Object.assign(content.value, result.terms)
      qualityStandardsText.value = content.value.quality_standards.join('\n')
    }
  } catch (error) {
    if (request === previewRequest) previewError.value = apiErrorMessage(error, '原版预览加载失败，请重试。')
  } finally {
    if (request === previewRequest) previewLoading.value = false
  }
}
watch([content, showOriginal], () => {
  clearTimeout(previewTimer)
  if (!loading.value && autoSeal.value && showOriginal.value) {
    previewTimer = setTimeout(() => void refreshOriginalPreview(), 400)
  }
}, { deep: true })
const editingTerm = ref<TermKey | null>(null)
const termDraft = ref('')
const termTitle = computed(() => termOptions.find(item => item.key === editingTerm.value)?.label || '修改条款')
const canvasArea = ref<HTMLElement>()
const canvasZoom = ref(1)
let canvasObserver: ResizeObserver | undefined
function fitCanvas(): void {
  if (!canvasArea.value) return
  const pageWidth = isPublished.value ? 953 : 892
  canvasZoom.value = Math.min(1, Math.max(0.5, (canvasArea.value.clientWidth - 24) / pageWidth))
}
watch(canvasArea, element => {
  canvasObserver?.disconnect()
  if (element && typeof ResizeObserver !== 'undefined') {
    canvasObserver = new ResizeObserver(fitCanvas)
    canvasObserver.observe(element)
    fitCanvas()
  }
})
function openTerm(key: TermKey): void {
  if (!editable.value || busy.value || !content.value) return
  const original = autoSeal.value && !content.value.original_template_edits?.includes(key) ? originalPreview.value?.terms[key] : undefined
  termDraft.value = original !== undefined ? (Array.isArray(original) ? original.join('\n') : original) : (key === 'quality_standards' ? qualityStandardsText.value : content.value[key])
  editingTerm.value = key
}
function applyTerm(): void {
  if (!editable.value || busy.value || !content.value || !editingTerm.value) return
  markOriginalEdit(editingTerm.value)
  if (editingTerm.value === 'quality_standards') {
    qualityStandardsText.value = termDraft.value
    syncQualityStandards()
  } else content.value[editingTerm.value] = termDraft.value
  editingTerm.value = null
}
const legalBasisText = '根据《中华人民共和国民法典》《中华人民共和国产品质量法》等国家和地方政府部门有关法律法规，双方经过充分友好协商，本着诚实守信的原则，就采购方向供货方购买产品一事，达成以下约定：'

const activeAction = ref(false)
const busy = computed(() => activeAction.value || saving.value || publishing.value || loading.value)
const canEdit = computed(() => auth.user?.is_superuser || auth.moduleCan('procurement.change_supplierpurchasesheet', 'procurement.add_purchaseorder'))
const canNewVersion = computed(() => auth.moduleCan('procurement.add_supplierpurchasesheet', 'procurement.add_purchaseorder'))
const canPublish = computed(() => auth.user?.is_superuser || auth.moduleCan('procurement.publish_supplierpurchasesheet', 'procurement.submit_purchaseorder'))
const editable = computed(() => sheet.value?.status === 'DRAFT' && canEdit.value)
const isPublished = computed(() => sheet.value?.status === 'PUBLISHED')
watch(sheet, value => { purchaseSheetPageStatus.value = value ? { id: value.id, status: value.status } : null })

// 将保存、附件和发布弹框串行处理，避免同一版本并发写入。
async function runAction(action: () => Promise<unknown>): Promise<void> {
  if (busy.value || publishVisible.value || !sheet.value || loadError.value) return
  activeAction.value = true
  try { await action() } finally { activeAction.value = false }
}
const qualityStandards = computed(() => qualityStandardsText.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean))
const autoSeal = computed(() => content.value?.order.source_type !== 'SAMPLE'
  && ['FABRIC', 'FOAM_CUTTING', 'AUXILIARY', 'PLASTIC_PART', 'WEBBING_ACTUAL_WEIGHT'].includes(sheet.value?.template_code || ''))
const totalAmount = computed(() => {
  if (!content.value || content.value.settlement_mode === 'ACTUAL_WEIGHT') return null
  if (isPublished.value) return sheet.value?.total_amount == null ? null : Number(sheet.value.total_amount)
  return content.value.lines.reduce((sum, line) => {
    const quantity = Number(line.quantity)
    const price = Number(line.unit_price)
    return sum + (Number.isFinite(quantity) && Number.isFinite(price) ? quantity * price : 0)
  }, 0)
})
const imageLineIds = computed(() => new Set(
  (sheet.value?.line_images || []).map((item) => item.source_purchase_order_line_id),
))
const representativeImageLine = computed<SupplierPurchaseSheetLine | null>(() => {
  const lines = content.value?.lines || []
  return lines.find((line) => imageLineIds.value.has(line.source_purchase_order_line_id)) || lines[0] || null
})
const hasRepresentativeImage = computed(() => (
  representativeImageLine.value
    ? imageLineIds.value.has(representativeImageLine.value.source_purchase_order_line_id)
    : false
))
const signingDate = computed(() => formatContractDate(content.value?.purchase_date || ''))

function formatContractDate(value: string): string {
  const matched = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!matched) return value || '—'
  return `${matched[1]}.${Number(matched[2])}.${Number(matched[3])}`
}

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { status?: number; data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  if (response?.status === 412) return '采购表已被其他人修改，请刷新后再编辑。'
  const fieldError = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return fieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

function money(value: number | string | null): string {
  if (value === null) return '待结算'
  return `¥${formatPurchaseSheetNumber(typeof value === 'number' ? value.toFixed(4) : value)}`
}

function syncCalculatedAmounts(): void {
  if (!content.value) return
  for (const line of content.value.lines) {
    if (content.value.settlement_mode === 'ACTUAL_WEIGHT') {
      line.amount = ''
      continue
    }
    const quantity = Number(line.quantity)
    const price = Number(line.unit_price)
    line.amount = Number.isFinite(quantity) && Number.isFinite(price)
      ? (quantity * price).toFixed(4).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
      : ''
  }
  content.value.total_amount = totalAmount.value === null ? null : String(totalAmount.value)
}

function syncQualityStandards(): void {
  if (!content.value) return
  content.value.quality_standards = qualityStandardsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function normalizeContent(snapshot: SupplierPurchaseSheetContent): SupplierPurchaseSheetContent {
  const legacyTerms = ((snapshot as unknown as { terms?: string[] }).terms || []).filter(Boolean)
  // 已发布版本保留归档文本，不用当前默认条款填充历史合同。
  if (isPublished.value) return { ...snapshot, quality_standards: snapshot.quality_standards || legacyTerms }
  return {
    ...snapshot,
    lines: snapshot.lines.map(line => ({ ...line, quantity: formatPurchaseSheetNumber(line.quantity, line.quantity), unit_price: formatPurchaseSheetNumber(line.unit_price, line.unit_price) })),
    payment_and_delivery: snapshot.payment_and_delivery || '乙方应在约定采购交期前将货物送达甲方指定地点；付款方式以双方最终确认内容为准。',
    quality_standards: snapshot.quality_standards?.length ? snapshot.quality_standards : (legacyTerms.slice(0, 2).length ? legacyTerms.slice(0, 2) : ['产品应符合双方确认的规格、样品及质量要求。']),
    delivery_handover: snapshot.delivery_handover || '乙方送货至甲方指定地点并按约定完成验收交接。',
    special_instructions: snapshot.special_instructions || '',
    dispute_resolution: snapshot.dispute_resolution || '双方先友好协商；协商不成，向甲方所在地有管辖权的人民法院起诉。',
    effectiveness: snapshot.effectiveness || '本采购表自双方签字或盖章之日起生效。',
    seal_status: sheet.value?.seal_image ? 'UPLOADED' : 'NOT_UPLOADED',
  }
}

async function load(): Promise<void> {
  editingTerm.value = null
  previewRequest++
  clearTimeout(previewTimer)
  originalPreview.value = null
  previewError.value = ''
  showOriginal.value = true
  loading.value = true
  loadError.value = ''
  sheet.value = null
  content.value = null
  etag.value = ''
  try {
    const result = await fetchSupplierPurchaseSheet(String(route.params.id || ''))
    sheet.value = result.data
    content.value = normalizeContent(structuredClone(result.data.content_snapshot))
    qualityStandardsText.value = content.value.quality_standards.join('\n')
    etag.value = result.etag
    await refreshOriginalPreview(true)
  } catch (error) {
    loadError.value = apiErrorMessage(error, '采购表加载失败。')
  } finally {
    loading.value = false
  }
}

async function save(showMessage = true): Promise<boolean> {
  if (!sheet.value || !content.value || !editable.value || saving.value) return false
  saving.value = true
  syncQualityStandards()
  syncCalculatedAmounts()
  try {
    const result = await saveSupplierPurchaseSheet(sheet.value.id, content.value, etag.value)
    sheet.value = result.data
    content.value = normalizeContent(structuredClone(result.data.content_snapshot))
    qualityStandardsText.value = content.value.quality_standards.join('\n')
    etag.value = result.etag
    if (showMessage) ElMessage.success('采购表草稿已保存。')
    return true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '采购表保存失败。'))
    return false
  } finally {
    saving.value = false
  }
}

async function publish(): Promise<void> {
  if (!sheet.value || sheet.value.status !== 'DRAFT' || !canPublish.value) return
  if (editable.value && !(await save(false))) return
  publishError.value = ''
  publishBlocked.value = false
  publishVisible.value = true
}

async function confirmPublish(): Promise<void> {
  if (!publishVisible.value || publishing.value || publishBlocked.value || !canPublish.value || sheet.value?.status !== 'DRAFT') return
  publishing.value = true
  publishError.value = ''
  try {
    const result = await publishSupplierPurchaseSheet(sheet.value.id, etag.value)
    sheet.value = result.data
    content.value = normalizeContent(structuredClone(result.data.content_snapshot))
    etag.value = result.etag
    publishVisible.value = false
    ElMessage.success('采购表已发布，当前版本已锁定为只读。')
  } catch (error) {
    publishError.value = apiErrorMessage(error, '采购表发布失败，请重试。')
    const status = (error as { response?: { status?: number } })?.response?.status
    publishBlocked.value = status === 412 || status === 403
  } finally {
    publishing.value = false
  }
}

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

async function downloadXlsx(): Promise<void> {
  if (!sheet.value) return
  if (editable.value && !(await save(false))) return
  try {
    saveBlob(await downloadSupplierPurchaseSheetXlsx(sheet.value.id), `${sheet.value.sheet_number}_V${sheet.value.version_number}.xlsx`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'Excel 下载失败。'))
  }
}

async function newVersion(): Promise<void> {
  if (!sheet.value || sheet.value.status !== 'PUBLISHED' || !canNewVersion.value) return
  try {
    const result = await createSupplierPurchaseSheetVersion(sheet.value.id, etag.value)
    ElMessage.success(`已创建 V${result.data.version_number} 草稿。`)
    await router.replace({ name: 'supplier-purchase-sheet-editor', params: { id: result.data.id } })
    await nextTick()
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '新版本创建失败。'))
  }
}

function validateImage(file: File): boolean {
  if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type)) {
    ElMessage.warning('采购表图片仅支持 JPG、PNG、GIF 或 WebP。')
    return false
  }
  if (file.size <= 0 || file.size > 5 * 1024 * 1024) {
    ElMessage.warning('采购表图片必须大于 0 字节且不超过 5MB。')
    return false
  }
  return true
}

function lineImageUrl(lineId: string): string {
  if (!sheet.value) return ''
  return supplierPurchaseSheetLineImageUrl(sheet.value.id, lineId, sheet.value.updated_at)
}

function sealImageUrl(): string {
  if (!sheet.value?.seal_image) return ''
  return supplierPurchaseSheetSealImageUrl(sheet.value.id, sheet.value.updated_at)
}

async function uploadLineImage(line: SupplierPurchaseSheetLine, file: UploadFile): Promise<void> {
  if (!sheet.value || !file.raw || !editable.value || !validateImage(file.raw)) return
  try {
    const result = await uploadSupplierPurchaseSheetLineImage(
      sheet.value.id,
      line.source_purchase_order_line_id,
      file.raw,
      etag.value,
    )
    sheet.value = result.data
    etag.value = result.etag
    ElMessage.success('采购表图片已上传并登记。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '采购表图片上传失败。'))
  }
}

async function removeLineImage(line: SupplierPurchaseSheetLine): Promise<void> {
  if (!sheet.value || !editable.value) return
  try {
    await ElMessageBox.confirm('确认移除这条采购明细的图片吗？', '移除图片', {
      type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteSupplierPurchaseSheetLineImage(
      sheet.value.id,
      line.source_purchase_order_line_id,
      etag.value,
    )
    sheet.value = result.data
    etag.value = result.etag
    ElMessage.success('采购表图片已移除。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '采购表图片移除失败。'))
  }
}

async function uploadRepresentativeImage(file: UploadFile): Promise<void> {
  if (!representativeImageLine.value) {
    ElMessage.warning('当前采购表没有可绑定图片的采购明细。')
    return
  }
  await uploadLineImage(representativeImageLine.value, file)
}

async function removeRepresentativeImage(): Promise<void> {
  if (!representativeImageLine.value) return
  await removeLineImage(representativeImageLine.value)
}

async function uploadSealImage(file: UploadFile): Promise<void> {
  if (!sheet.value || !file.raw || !editable.value || !validateImage(file.raw)) return
  try {
    const result = await uploadSupplierPurchaseSheetSealImage(sheet.value.id, file.raw, etag.value)
    sheet.value = result.data
    etag.value = result.etag
    if (content.value) content.value.seal_status = 'UPLOADED'
    ElMessage.success('甲方盖章图片已上传并登记。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盖章图片上传失败。'))
  }
}

async function removeSealImage(): Promise<void> {
  if (!sheet.value || !editable.value || !sheet.value.seal_image) return
  try {
    await ElMessageBox.confirm('确认移除当前版本的甲方盖章图片吗？', '移除盖章图片', {
      type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    const result = await deleteSupplierPurchaseSheetSealImage(sheet.value.id, etag.value)
    sheet.value = result.data
    etag.value = result.etag
    if (content.value) content.value.seal_status = 'NOT_UPLOADED'
    ElMessage.success('甲方盖章图片已移除。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盖章图片移除失败。'))
  }
}

onMounted(() => void load())
onBeforeUnmount(() => { previewRequest++; clearTimeout(previewTimer); canvasObserver?.disconnect(); purchaseSheetPageStatus.value = null })
</script>

<template>
  <section v-loading="loading" class="editor-page erp-glass-form" :class="{ 'is-published': isPublished }" :aria-busy="busy">
    <div v-if="loadError" class="load-error" role="alert"><span>{{ loadError }}</span><ElButton :disabled="loading" @click="load">重新加载</ElButton></div>
    <div v-if="isPublished" class="published-notice"><img :src="publishedLock" alt=""><strong>正式内容已锁定</strong><span>当前 V{{ sheet?.version_number }} 为只读版本，如需修改请创建新版本。</span></div>

    <div v-if="sheet && content" class="editor-layout" :inert="publishVisible || undefined">
      <aside v-if="isPublished" class="published-info" aria-label="采购表只读信息">
        <ElButton class="panel-back-button" :icon="ArrowLeft" circle aria-label="返回供应商采购表" :disabled="busy" @click="router.push({ name: 'supplier-purchase-sheets', query: { purchase_order_id: sheet.purchase_order_id || undefined } })" />
        <h2>采购表信息</h2>
        <dl class="published-fields">
          <div><dt>采购表编号</dt><dd>{{ sheet.sheet_number }}</dd></div>
          <div><dt>当前版本</dt><dd class="published-status">V{{ sheet.version_number }} · 已发布</dd></div>
          <div><dt>合同模板</dt><dd>{{ sheet.template_name || '—' }}</dd></div>
          <div><dt>{{ content.order.source_type === 'SAMPLE' ? '打样单号' : '关联订单' }}</dt><dd>{{ (content.order.source_type === 'SAMPLE' ? content.order.source_number : content.order.sales_order_number) || '—' }}</dd></div>
          <div><dt>采购日期</dt><dd>{{ content.purchase_date || '—' }}</dd></div>
          <div><dt>结算方式</dt><dd>{{ content.settlement_mode === 'ACTUAL_WEIGHT' ? '按实际重量结算' : '按数量和单价结算' }}</dd></div>
          <div><dt>采购金额</dt><dd class="published-amount">{{ money(totalAmount) }} （共{{ content.lines.length }}项明细）</dd></div>
          <div><dt>税率</dt><dd>{{ content.tax_rate ? `${formatPurchaseSheetNumber(content.tax_rate)}%` : '—' }}</dd></div>
          <div><dt>运费承担方</dt><dd>{{ content.freight_bearer ? `${content.freight_bearer}承担` : '—' }}</dd></div>
        </dl>
        <div class="published-parties"><h2>甲方信息</h2><p>{{ content.buyer.name || '—' }}</p><h2>乙方信息</h2><p>{{ content.seller.name || '—' }}</p></div>
        <div class="published-other"><h2>其他信息</h2><dl><div><dt>甲方盖章</dt><dd>{{ autoSeal ? '原版 Excel 自动带章' : (sheet.seal_image ? '已上传' : '未上传') }}</dd></div></dl></div>
        <div class="panel-actions">
          <ElButton :icon="Download" :disabled="busy" @click="runAction(downloadXlsx)">导出 Excel</ElButton>
          <ElButton type="primary" :disabled="busy || !canNewVersion" @click="runAction(newVersion)">创建新版本</ElButton>
        </div>
      </aside>
      <aside v-else class="property-panel">
        <div class="panel-nav">
          <ElButton class="panel-back-button" :icon="ArrowLeft" circle aria-label="返回供应商采购表" :disabled="busy" @click="router.push({ name: 'supplier-purchase-sheets', query: { purchase_order_id: sheet.purchase_order_id || undefined } })" />
        </div>
        <section class="settings-section"><h2>采购表设置</h2>
          <label>合同标题<ElInput v-model="content.title" aria-label="设置合同标题" :disabled="!editable || busy" @input="markOriginalEdit('title')" /></label>
          <label>采购日期<ElDatePicker v-model="content.purchase_date" value-format="YYYY-MM-DD" :clearable="false" aria-label="采购日期" :disabled="!editable || busy" /></label>
          <label>结算方式<ElSelect v-model="content.settlement_mode" :disabled="!editable || busy" @change="syncCalculatedAmounts"><ElOption label="按数量和单价结算" value="NORMAL" /><ElOption label="按实际重量结算" value="ACTUAL_WEIGHT" :disabled="content.lines.some(line => line.measurement_kind === 'PIPE')" /></ElSelect></label>
          <div class="two-fields"><label>税率（%）<ElInput v-model="content.tax_rate" aria-label="税率" :disabled="!editable || busy" /></label><label>运费承担方<ElSelect v-model="content.freight_bearer" allow-create filterable :disabled="!editable || busy"><ElOption label="甲方" value="甲方" /><ElOption label="乙方" value="乙方" /></ElSelect></label></div>
        </section>
        <section class="party-section"><h2>甲方信息</h2>
          <ElInput v-model="content.buyer.name" aria-label="甲方名称" :disabled="!editable || busy" />
        </section>
        <section class="party-section"><h2>乙方信息</h2>
          <ElInput v-model="content.seller.name" aria-label="乙方名称" :disabled="!editable || busy" />
        </section>
        <section class="terms-section"><h2>第二至第七条</h2>
          <div class="term-buttons"><ElButton v-for="term in termOptions" :key="term.key" :disabled="!editable || busy" @click="openTerm(term.key)">{{ term.label }}</ElButton></div>
        </section>
        <section class="seal-section"><h2>甲方盖章图片</h2>
          <div class="seal-editor">
            <ElImage v-if="sheet.seal_image" :src="sealImageUrl()" :preview-src-list="[sealImageUrl()]" fit="contain" />
            <span v-else>{{ autoSeal ? '下载原版 Excel 时自动带甲方章' : '暂未上传盖章图片' }}</span>
            <div v-if="editable && !autoSeal" class="seal-actions">
              <ElUpload :auto-upload="false" :show-file-list="false" accept="image/png,image/jpeg,image/gif,image/webp" :disabled="busy" @change="(file: UploadFile) => runAction(() => uploadSealImage(file))">
                <ElButton :disabled="busy">{{ sheet.seal_image ? '替换图片' : '上传图片' }}</ElButton>
              </ElUpload>
              <ElButton v-if="sheet.seal_image" type="danger" plain :icon="Delete" :disabled="busy" @click="runAction(removeSealImage)">移除</ElButton>
            </div>
          </div>
          <div class="panel-actions">
            <ElButton :icon="Download" :disabled="busy" @click="runAction(downloadXlsx)">导出 Excel</ElButton>
            <ElButton :icon="Document" :loading="saving" :disabled="busy || !editable" @click="runAction(() => save())">保存草稿</ElButton>
            <ElButton type="primary" :icon="VideoPlay" :loading="publishing" :disabled="busy || !canPublish" @click="runAction(publish)">发布</ElButton>
          </div>
        </section>
      </aside>

      <main ref="canvasArea" class="canvas-area">
        <div v-if="autoSeal" class="preview-toolbar">
          <ElButton :type="showOriginal ? 'primary' : 'default'" @click="showOriginal = true">原版预览</ElButton>
          <ElButton v-if="editable" :type="!showOriginal ? 'primary' : 'default'" @click="showOriginal = false">编辑明细</ElButton>
          <span>{{ previewLoading ? '正在更新预览…' : editable ? '修改后请保存草稿' : '与下载 Excel 使用同一原版' }}</span>
        </div>
        <div v-if="autoSeal && showOriginal" class="preview-content" :aria-busy="previewLoading">
          <div v-if="previewError" class="preview-error" role="alert">{{ previewError }}<ElButton :disabled="previewLoading" @click="refreshOriginalPreview()">重试</ElButton></div>
          <PurchaseSheetOriginalPreview v-else-if="originalPreview" :preview="originalPreview" />
          <p v-else>正在加载原版合同…</p>
        </div>
        <article v-else class="a4-canvas" :style="{ zoom: canvasZoom }">
          <div class="contract-sheet">
            <div class="contract-title-row">
              <ElInput v-if="editable" v-model="content.title" :disabled="busy" aria-label="合同标题" @input="markOriginalEdit('title')" />
              <strong v-else>{{ content.title }}</strong>
              <span>（订单编号 <b>{{ (content.order.source_type === 'SAMPLE' ? content.order.source_number : content.order.production_task_number) || '—' }}</b>）</span>
            </div>
            <div class="party-row">
              <p>采购单号：{{ sheet.sheet_number }}</p>
              <p><strong>甲方（采购方）：</strong>{{ content.buyer.name || '—' }}</p>
              <p><strong>乙方（供货方）：</strong>{{ content.seller.name || '—' }}</p>
            </div>
            <p class="legal-row">{{ legalBasisText }}</p>
            <div class="section-heading">一、采购产品名称、规格、数量、单价及金额</div>
            <table class="reference-contract-table">
              <colgroup><col class="col-product"><col class="col-spec"><col class="col-attributes"><col class="col-color"><col class="col-quantity"><col class="col-price"><col class="col-amount"></colgroup>
              <thead><tr><th>产品名称</th><th>产品规格</th><th>物料属性</th><th>颜色</th><th>数量</th><th>含税单价<br>（元）</th><th>金额<br>（元）</th></tr></thead>
              <tbody>
                <tr v-for="line in content.lines" :key="line.source_purchase_order_line_id">
                  <td><span v-if="isPublished" class="readonly-value">{{ line.part_name || '—' }}</span><ElInput v-else v-model="line.part_name" :disabled="!editable || busy" aria-label="产品名称" /></td>
                  <td>
                    <span v-if="isPublished" class="readonly-value">{{ purchaseSheetLineDisplay(line, content.order.source_type === 'SAMPLE').specification || '—' }}</span>
                    <ElInput v-else v-model="line.specification" type="textarea" autosize :disabled="!editable || busy" aria-label="产品规格" />
                  </td>
                  <td>
                    <span v-if="isPublished" class="readonly-value">{{ purchaseSheetLineDisplay(line, content.order.source_type === 'SAMPLE').attributes || '—' }}</span>
                    <div v-else class="line-attribute-editor">
                      <label><span>材质</span><ElInput v-model="line.material" type="textarea" autosize :disabled="!editable || busy" aria-label="产品材质" /></label>
                      <span v-if="purchaseSheetSourceFields(line, content.order.source_type === 'SAMPLE').attributes.length">{{ purchaseSheetSourceFields(line, content.order.source_type === 'SAMPLE').attributes.map(field => `${field.label}：${field.value}`).join('；') }}</span>
                      <ElInput v-if="content.order.source_type !== 'SAMPLE'" v-model="line.remark" type="textarea" autosize :disabled="!editable || busy" aria-label="补充要求" placeholder="补充要求" />
                    </div>
                  </td>
                  <td>
                    <ElInput v-if="!isPublished && content.order.source_type === 'SAMPLE'" v-model="line.remark" type="textarea" autosize :disabled="!editable || busy" aria-label="样品颜色" placeholder="颜色" />
                    <span v-else class="readonly-value">{{ purchaseSheetLineDisplay(line, content.order.source_type === 'SAMPLE').color || '—' }}</span>
                  </td>
                  <td><span v-if="isPublished || line.measurement_kind === 'PIPE'" class="readonly-value center-cell"><template v-if="line.measurement_kind === 'PIPE'">{{ line.actual_bar_count == null ? '根数未记录' : `${formatPurchaseSheetNumber(line.actual_bar_count)} 根` }}<small style="display:block">{{ formatPurchaseSheetNumber(line.quantity) }} 米 · {{ formatPurchaseSheetNumber(line.raw_bar_length_m) }} 米/根</small></template><template v-else>{{ formatPurchaseSheetNumber(line.quantity) }} {{ line.unit }}</template></span><div v-else class="quantity-editor"><ElInput v-model="line.quantity" :disabled="!editable || busy" aria-label="数量" @input="syncCalculatedAmounts" /><span>{{ line.unit }}</span></div></td>
                  <td><span v-if="isPublished || line.measurement_kind === 'PIPE'" class="readonly-value center-cell">{{ line.unit_price ? money(line.unit_price).replace('¥', '') : '—' }}{{ line.measurement_kind === 'PIPE' ? ' 元/米' : '' }}</span><ElInput v-else v-model="line.unit_price" :disabled="!editable || busy" aria-label="含税单价" @input="syncCalculatedAmounts" /></td>
                  <td class="amount-cell">{{ content.settlement_mode === 'ACTUAL_WEIGHT' ? '待结算' : money(line.amount).replace('¥', '') }}</td>
                </tr>
                <tr v-if="!content.lines.length"><td colspan="7" class="empty-lines">暂无采购明细，请重新加载或核对来源采购订单。</td></tr>
              </tbody>
            </table>
                <div class="media-total-row" :class="{ 'without-image': isPublished && !hasRepresentativeImage }">
                  <div v-if="!autoSeal && (!isPublished || hasRepresentativeImage)" class="contract-image-cell">
                    <ElImage v-if="representativeImageLine && hasRepresentativeImage" :src="lineImageUrl(representativeImageLine.source_purchase_order_line_id)" :preview-src-list="[lineImageUrl(representativeImageLine.source_purchase_order_line_id)]" fit="contain" />
                    <span v-else class="image-empty"><ElIcon><Picture /></ElIcon>暂无图片</span>
                    <div v-if="editable" class="representative-image-actions">
                      <ElUpload :auto-upload="false" :show-file-list="false" accept="image/png,image/jpeg,image/gif,image/webp" :disabled="busy" @change="(file: UploadFile) => runAction(() => uploadRepresentativeImage(file))"><ElButton :disabled="!representativeImageLine || busy">{{ hasRepresentativeImage ? '替换图片' : '上传图片' }}</ElButton></ElUpload>
                      <ElButton v-if="hasRepresentativeImage" link type="danger" :icon="Delete" :disabled="busy" @click="runAction(removeRepresentativeImage)">删除</ElButton>
                    </div>
                    <small v-if="!isPublished">{{ content.order.source_type === 'SAMPLE' ? '可上传样品采购参考图' : 'BOM 有图时自动带入' }}</small>
                  </div>
                  <div class="contract-remark-cell"><strong>备注：</strong><p v-if="isPublished" class="readonly-remark">{{ content.remark }}</p><ElInput v-else v-model="content.remark" type="textarea" :rows="2" :disabled="!editable || busy" aria-label="合同备注" /><small v-if="!isPublished">税率 {{ formatPurchaseSheetNumber(content.tax_rate) }}% · 运费由{{ content.freight_bearer || '—' }}承担</small></div>
                  <div class="total-label">合计</div>
                  <div class="total-value">{{ money(totalAmount).replace('¥', '') }}</div>
                </div>
            <div class="clause-row"><strong>二、支付方式和交期</strong><p>{{ content.payment_and_delivery }}</p></div>
            <div class="clause-row"><strong>三、产品质量标准</strong><p v-for="(standard, index) in qualityStandards" :key="index">{{ index + 1 }}. {{ standard }}</p></div>
            <div class="clause-row"><strong>四、送货交接</strong><p>{{ content.delivery_handover }}</p></div>
            <div class="clause-row"><strong>五、特别说明</strong><p>{{ content.special_instructions || '—' }}</p></div>
            <div class="clause-row"><strong>六、争议解决</strong><p>{{ content.dispute_resolution }}</p></div>
            <div class="clause-row"><strong>七、合同生效</strong><p>{{ content.effectiveness }}</p></div>
            <div class="signature-label-row"><strong>甲方</strong><span></span></div>
            <div class="signature-stamp-row"><div><ElImage v-if="sheet.seal_image" :src="sealImageUrl()" fit="contain" /></div><div aria-label="乙方签章留白"></div></div>
            <div class="signature-date-row"><span>请确认无误盖章回传</span><span>签订日期：{{ signingDate }}</span></div>
          </div>
        </article>
      </main>
    </div>

    <AppWindowDialog :model-value="editingTerm !== null" :title="termTitle" :width="780" :height="520" destroy-on-close @update:model-value="value => { if (!value) editingTerm = null }">
      <div class="term-dialog-body">
        <p v-if="editingTerm === 'quality_standards'">每行填写一条质量标准。</p>
        <ElInput v-model="termDraft" type="textarea" :rows="15" :aria-label="termTitle" :disabled="!editable || busy" />
      </div>
      <template #footer><div class="term-dialog-footer"><span>确认后请保存草稿。</span><ElButton @click="editingTerm = null">取消</ElButton><ElButton type="primary" :disabled="!editable || busy" @click="applyTerm">确认</ElButton></div></template>
    </AppWindowDialog>

    <PurchaseSheetPublishConfirm v-if="sheet" v-model="publishVisible" :sheet-number="sheet.sheet_number"
      :version="sheet.version_number" :supplier-name="sheet.supplier_name_snapshot" :template-name="sheet.template_name"
      :amount="money(sheet.total_amount)" :line-count="sheet.content_snapshot.lines.length" :has-seal="!!sheet.seal_image" :auto-seal="autoSeal"
      :publishing="publishing" :error="publishError" :blocked="publishBlocked" @confirm="confirmPublish" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as crm;
@use '@/styles/theme/detail' as detail;
.editor-page { box-sizing: border-box; height: 100%; min-width: 0; min-height: 0; overflow: hidden; padding: 0; display: flex; flex-direction: column; color: crm.$crm-text-primary; background: transparent; font: 16px/24px crm.$crm-font-body; --el-color-primary: #{crm.$crm-primary}; --el-border-color: #{crm.$crm-border-default}; --el-fill-color-blank: #{crm.$crm-color-surface}; --el-text-color-regular: #{crm.$crm-text-primary}; --el-text-color-placeholder: #{crm.$crm-text-muted}; --el-border-radius-base: 4px; }
.editor-page > :is(.editor-layout, .load-error) { min-width: 0; }

.load-error { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 20px; background: crm.$crm-danger-soft; color: crm.$crm-danger; }
.editor-layout { min-height: 0; flex: 1; display: grid; grid-template-columns: 300px minmax(0,1fr); gap: 14px; }
.property-panel,.canvas-area { @include detail.surface; min-height: 0; overflow: auto; scrollbar-gutter: stable; }
.panel-nav { box-sizing: border-box; height: 44px; padding: 6px 12px; border-bottom: 1px solid crm.$crm-border-subtle; }
.panel-back-button { width: 32px; height: 32px; min-height: 32px; padding: 0; margin: 0; color: crm.$crm-text-secondary; }
// 保留原12px尺寸，颜色交由全局WebKit伪元素规则提供。
@supports selector(::-webkit-scrollbar) {
  .property-panel,.canvas-area { scrollbar-color: auto; }
}
.property-panel::-webkit-scrollbar,.canvas-area::-webkit-scrollbar { width: 12px; height: 12px; }
.property-panel::-webkit-scrollbar-thumb,.canvas-area::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 6px; background-clip: padding-box; }
.property-panel section { box-sizing: border-box; padding: 10px 12px; border-bottom: 1px solid crm.$crm-border-subtle; }
.property-panel section:last-child { border-bottom: none; }
.property-panel h2 { margin: 0 0 8px; font-size: 15px; line-height: 22px; font-weight: 700; }
.property-panel label { display: flex; flex-direction: column; gap: 2px; margin-top: 8px; color: crm.$crm-text-secondary; font-size: 13px; line-height: 18px; }
.property-panel h2 + label { margin-top: 0; }
.property-panel .settings-section { padding-top: 10px; padding-bottom: 10px; }
.property-panel .party-section { padding-top: 8px; padding-bottom: 8px; }
.property-panel .party-section h2 { margin-bottom: 4px; }
.property-panel .terms-section { padding-top: 10px; }
.property-panel .seal-section { padding-top: 10px; }
.property-panel :deep(.el-date-editor),.property-panel :deep(.el-select) { width: 100%; }
.property-panel :deep(.el-date-editor) { height: 28px; }
.property-panel :deep(.el-input__wrapper),.property-panel :deep(.el-select__wrapper) { height: 28px; min-height: 28px; box-sizing: border-box; padding: 0 8px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: 0 0 0 1px var(--erp-input-border) inset; font-size: 13px; }
.property-panel :deep(.el-input__inner),.property-panel :deep(.el-select__selected-item) { color: crm.$crm-text-secondary; font-size: 13px; }
.property-panel :deep(.el-textarea__inner) { padding: 4px 12px; min-height: 54px; border-radius: var(--erp-radius-control); box-shadow: 0 0 0 1px var(--erp-input-border) inset; font: 16px/24px crm.$crm-font-body; color: crm.$crm-text-secondary; background: var(--erp-input-surface); resize: vertical; }

.term-buttons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.term-buttons :deep(.el-button) { width: 100%; height: 30px; margin: 0; padding: 0 4px; font-size: 12px; }
.term-dialog-body { display: grid; gap: 8px; }
.term-dialog-body p { margin: 0; font-size: 13px; color: crm.$crm-text-secondary; }
.term-dialog-footer { display: flex; align-items: center; gap: 8px; width: 100%; }
.term-dialog-footer > span { margin-right: auto; color: crm.$crm-text-secondary; font-size: 12px; }
.term-dialog-footer :deep(.el-button) { margin-left: 0; }
.two-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.seal-editor { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; color: crm.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.seal-editor :deep(.el-image) { width: 150px; height: 110px; border: 1px solid crm.$crm-border-default; }
.seal-actions { display: flex; gap: 8px; }
.seal-actions :deep(.el-button) { height: 32px; min-width: 112px; }
.panel-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.panel-actions :deep(.el-button) { width: 100%; height: 32px; min-height: 32px; margin: 0; padding: 0 10px; }
.panel-actions :deep(.el-icon) { margin-right: 6px; }
.canvas-area { padding: 12px 0 32px; }
.preview-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 0 12px 8px; }
.preview-toolbar .el-button + .el-button { margin-left: 0; }
.preview-toolbar span { font-size: 12px; color: var(--el-text-color-secondary); }
.preview-error { padding: 16px; color: var(--el-color-danger); }
.preview-error .el-button { margin-left: 8px; }
.a4-canvas { box-sizing: border-box; width: 892px; min-height: 1271px; margin: 0 auto; padding: 28px 30px 30px; background: #fff; }
.contract-sheet { box-sizing: border-box; border: 1px solid crm.$crm-text-primary; font: 16px/24px crm.$crm-font-body; overflow-wrap: anywhere; }
.contract-title-row { box-sizing: border-box; min-height: 65px; padding: 6px 10px; display: flex; gap: 20px; align-items: center; justify-content: center; border-bottom: 1px solid crm.$crm-text-primary; font: 700 28px/36px crm.$crm-font-display; }
.contract-title-row > :deep(.el-input) { width: 168px; flex: none; }
.contract-title-row > span { font-size: 24px; }
.contract-title-row :deep(.el-input__inner) { height: 42px; font: 700 28px/36px crm.$crm-font-display; text-align: center; }
.party-row,.legal-row,.section-heading,.clause-row { box-sizing: border-box; margin: 0; border-bottom: 1px solid crm.$crm-text-primary; }
.party-row { min-height: 92px; padding: 8px 16px 5px; }
.party-row p { margin: 0; line-height: 26px; }
.party-row strong { font-weight: 400; }
.legal-row { min-height: 64px; padding: 8px 16px; font-size: 14px; line-height: 22px; }
.section-heading { min-height: 39px; padding: 7px 16px; font-weight: 700; }
.reference-contract-table { width: 100%; border-spacing: 0; border-collapse: collapse; table-layout: fixed; }
.reference-contract-table th,.reference-contract-table td { box-sizing: border-box; border-right: 1px solid crm.$crm-text-primary; border-bottom: 1px solid crm.$crm-text-primary; padding: 0; vertical-align: middle; }
.reference-contract-table th:last-child,.reference-contract-table td:last-child { border-right: 0; }
.reference-contract-table th { height: 52px; padding: 3px; text-align: center; font-size: 14px; line-height: 22px; }
.reference-contract-table td { height: 38px; font-size: 14px; line-height: 20px; }
.col-product { width: 14%; }.col-spec { width: 23%; }.col-attributes { width: 24%; }.col-color { width: 12%; }.col-quantity,.col-price,.col-amount { width: 9%; }
.center-cell,.amount-cell { text-align: center; }
.contract-sheet :deep(.el-input__wrapper),.contract-sheet :deep(.el-textarea__inner) { padding: 4px 12px; border-radius: 0; box-shadow: none; background: transparent; font: 16px/24px crm.$crm-font-body; }
.contract-sheet :deep(.el-input__inner) { color: crm.$crm-text-primary; font-size: 16px; }
.reference-contract-table :deep(.el-input__wrapper) { box-sizing: border-box; height: 37px; }
.reference-contract-table :deep(.el-input__inner) { height: 28px; }
.contract-sheet :deep(.el-textarea__inner) { min-height: 36px !important; resize: none; color: crm.$crm-text-primary; }
.contract-sheet :deep(.el-input__wrapper.is-focus),.contract-sheet :deep(.el-textarea__inner:focus) { box-shadow: inset 0 0 0 1px crm.$crm-primary; }
.contract-title-row :deep(.el-input__inner) { font: 700 28px/36px crm.$crm-font-display; }
.contract-title-row :deep(.el-input__wrapper) { padding: 0; }
.contract-sheet :deep(.is-disabled .el-input__inner),.contract-sheet :deep(.is-disabled .el-textarea__inner) { -webkit-text-fill-color: crm.$crm-text-primary; }
.quantity-editor { display: flex; align-items: center; justify-content: center; gap: 4px; padding: 0 10px; }
.quantity-editor :deep(.el-input) { width: 56px; }
.quantity-editor :deep(.el-input__wrapper) { padding: 4px 0; }
.quantity-editor :deep(.el-input__inner) { text-align: right; }
.quantity-editor span { white-space: nowrap; }
.reference-contract-table td:nth-child(6) :deep(.el-input__inner) { text-align: center; }
.media-total-row { display: grid; grid-template-columns: 24% 58% 9% 9%; min-height: 170px; border-bottom: 1px solid crm.$crm-text-primary; box-sizing: border-box; }
.media-total-row > div { box-sizing: border-box; border-right: 1px solid crm.$crm-text-primary; }
.media-total-row > div:last-child { border-right: none; }
.contract-image-cell { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 12px 8px; text-align: center; }
.contract-image-cell :deep(.el-image),.contract-image-cell .image-empty { width: 146px; height: 84px; flex: none; box-sizing: border-box; object-fit: contain; }
.image-empty { display: flex; flex-direction: column; gap: 8px; align-items: center; justify-content: center; color: crm.$crm-text-secondary; background: crm.$crm-color-page; border: 1px dashed crm.$crm-border-default; border-radius: 4px; font-size: 14px; }
.image-empty .el-icon { font-size: 18px; }
.contract-image-cell small { color: crm.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.representative-image-actions { display: flex; align-items: center; justify-content: center; gap: 5px; }
.representative-image-actions :deep(.el-button) { height: 28px; padding: 0 8px; font-size: 13px; min-width: 94px; }
.representative-image-actions :deep(.el-button.is-link) { min-width: 0; }
.contract-remark-cell { padding: 10px 16px; display: flex; flex-direction: column; gap: 10px; }
.contract-remark-cell :deep(.el-textarea__inner) { height: 80px; box-shadow: 0 0 0 1px crm.$crm-border-default inset; border-radius: 4px; }
.contract-remark-cell small { font-size: 14px; line-height: 22px; }
.total-label,.total-value { display: grid; place-items: center; font-weight: 700; }
.clause-row { min-height: 68px; padding: 8px 16px; }
.clause-row p { margin: 4px 0 0; white-space: pre-wrap; font-size: 14px; line-height: 22px; }
.signature-label-row { padding: 12px 16px 0; min-height: 36px; box-sizing: border-box; }
.signature-stamp-row { height: 96px; padding: 16px; box-sizing: border-box; display: grid; grid-template-columns: 1fr 1fr; }
.signature-stamp-row :deep(.el-image) { width: 116px; height: 64px; }
.signature-date-row { display: flex; justify-content: space-between; gap: 16px; padding: 0 16px 14px; font-size: 14px; line-height: 24px; }
.empty-lines { padding: 24px !important; text-align: center; color: crm.$crm-text-secondary; }

.published-notice { flex: 0 0 52px; box-sizing: border-box; display: flex; align-items: center; gap: 18px; padding: 0 24px; margin-bottom: 14px; border-radius: 6px; background: crm.$crm-success-soft; color: crm.$crm-text-secondary; }
.published-notice img { width: 22px; height: 24px; flex: none; }
.published-notice strong { font-size: 20px; color: crm.$crm-success; }
.is-published .editor-layout { grid-template-columns: 422px minmax(0,1fr); gap: 11px; }
.published-info { box-sizing: border-box; min-height: 0; overflow: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; @include detail.surface; font-size: 14px; line-height: 22px; overflow-wrap: anywhere; scrollbar-width: thin; scrollbar-color: var(--erp-scrollbar-thumb) var(--erp-scrollbar-track); }
.published-info > * { flex: none; }
.published-info > .panel-back-button { align-self: flex-start; }
.published-info h2 { margin: 0; font-size: 16px; line-height: 24px; }
.published-info dl { margin: 0; }
.published-info dl > div { display: grid; grid-template-columns: 112px minmax(0,1fr); min-height: 30px; align-items: center; }
.published-info dt { color: crm.$crm-text-secondary; }
.published-info dd { margin: 0; min-width: 0; }
.published-info .published-status { color: crm.$crm-success; }
.published-info .published-amount { font-size: 14px; }
.published-info .panel-actions { margin-top: 12px; }
.published-parties { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid crm.$crm-border-default; padding-top: 12px; }
.published-parties p { margin: 0; color: crm.$crm-text-secondary; }
.published-other { border-top: 1px solid crm.$crm-border-default; padding-top: 12px; }
.published-other h2 { margin-bottom: 8px; }
.published-other dl > div { align-items: start; }
.is-published .canvas-area { padding: 11px 0 32px; }
.is-published .a4-canvas { width: 953px; min-height: 1317.15px; margin: 0 auto; padding: 29.85px 32.15px 34.44px; box-shadow: 0 2px 12px color-mix(in srgb, var(--erp-shadow-color) 3.137%, transparent); }
.is-published .contract-sheet { font-size: 17.09px; line-height: 25.636px; }
.is-published .contract-title-row { min-height: 70.04px; gap: 22.96px; padding: 6px 10px; font-size: 34px; line-height: 44px; flex-wrap: wrap; }
.is-published .contract-title-row > span { font-size: 30px; }
.is-published .party-row { min-height: 98.75px; padding: 8.54px 17.09px 5px; }
.is-published .party-row p { line-height: 28.55px; }
.is-published .legal-row { min-height: 73.48px; padding: 6.4px 17.09px; font-size: 14.954px; line-height: 23.5px; }
.is-published .section-heading { min-height: 39.04px; padding: 6.7px 17.09px; }
.is-published .reference-contract-table th { height: 44px; font-size: 14px; line-height: 20px; }
.is-published .reference-contract-table td { height: 40px; }
.readonly-value { display: block; padding: 4px 8px; white-space: pre-wrap; }
.line-attribute-editor { display: grid; gap: 2px; padding: 4px 8px; }
.line-attribute-editor label { display: grid; grid-template-columns: 28px minmax(0,1fr); align-items: center; gap: 4px; }
.line-attribute-editor :deep(.el-textarea__inner) { padding: 2px 4px; min-height: 24px !important; font-size: 14px; line-height: 20px; }
.is-published .media-total-row { min-height: 126.3px; }
.is-published .media-total-row.without-image { grid-template-columns: 82% 9% 9%; }
.is-published .contract-remark-cell { padding: 9.19px 20px 12px 17.09px; gap: 6.89px; }
.readonly-remark { box-sizing: border-box; min-height: 71.19px; margin: 0; padding: 8px 12px; border: 1px solid crm.$crm-border-default; border-radius: 3.45px; white-space: pre-wrap; }
.is-published .clause-row { min-height: 73.48px; padding: 8.54px 17.09px; }
.is-published .clause-row p { margin-top: 4.27px; font-size: 14.954px; line-height: 23.5px; }
.is-published .signature-label-row { min-height: 38.45px; padding: 12.82px 17.09px 0; }
.is-published .signature-stamp-row { height: 102.54px; padding: 17.09px; }
.is-published .signature-date-row { padding: 0 17.09px 14px; font-size: 14.954px; line-height: 25.636px; }
</style>
