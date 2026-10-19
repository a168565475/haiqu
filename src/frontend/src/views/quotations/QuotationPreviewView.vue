<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Document, Promotion, Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { AxiosError } from 'axios'
import InquiryWangEditor from '@/components/InquiryWangEditor.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

import { fetchCustomerContacts } from '@/api/contacts'
import { fetchCustomerEntities, fetchEntityAddresses } from '@/api/customers'
import { acceptQuotation, confirmManualQuotationDispatch, downloadFormalQuotationDocument, downloadFormalQuotationXlsx, fetchQuotation, fetchQuotationEmailAttempts, fetchQuotationVersion, generateFormalQuotationPdf, issueQuotationVersion, lockQuotationVersion, quotationLineProductImageUrl, resolveQuotationEmailAttempt, sendQuotationEmail, uploadFormalQuotationDocument } from '@/api/quotations'
import { fetchQuotationOrderContext } from '@/api/salesOrders'
import type { ContactListItem } from '@/types/contact'
import type { CustomerAddress } from '@/types/customer'
import type { QuotationDetail, QuotationDispatchRecord, QuotationEmailDispatchAttempt, QuotationLine, QuotationPriceBasis, QuotationVersionDetail } from '@/types/quotation'
import { useAuthStore } from '@/stores/auth'
import QuotationWorkflowStatus from './components/QuotationWorkflowStatus.vue'
import QuotationEmailRecoveryDialog from './components/QuotationEmailRecoveryDialog.vue'
import QuotationStatusTag from './components/QuotationStatusTag.vue'
import { useQuotationWorkflow } from './workflow/quotationWorkflow'
import '@fontsource-variable/noto-sans-sc'
import '@fontsource-variable/noto-serif-sc'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const quotation = ref<QuotationDetail | null>(null)
const version = ref<QuotationVersionDetail | null>(null)
const quotationEtag = ref('')
const versionEtag = ref('')
const contacts = ref<ContactListItem[]>([])
const addresses = ref<CustomerAddress[]>([])
const loading = ref(true)
const actionLoading = ref(false)
const errorMessage = ref('')
const dependencyWarnings = ref<string[]>([])
const acceptDialogVisible = ref(false)
const emailEditorVisible = ref(false)
const emailBodyDraft = ref('')
const emailAttempts = ref<QuotationEmailDispatchAttempt[]>([])
const uncertainAttempt = ref<QuotationEmailDispatchAttempt | null>(null)
const processingAttempt = ref<QuotationEmailDispatchAttempt | null>(null)
const resolutionDialogVisible = ref(false)
const resolutionForm = reactive({ result: 'ACCEPTED' as 'ACCEPTED' | 'NOT_SENT', note: '' })
const activeEmailKey = ref('')
const workflowDetail = ref('')
const lockWorkflow = useQuotationWorkflow('F01-S01')
const documentWorkflow = useQuotationWorkflow('F02-S03')
const emailWorkflow = useQuotationWorkflow('F03-S01')
const manualWorkflow = useQuotationWorkflow('F04-S01')
const acceptanceWorkflow = useQuotationWorkflow('F05-S01')
const lockForm = reactive({ contactId: '', addressId: '' })
const sendForm = reactive({
  channel: 'EMAIL' as 'EMAIL' | 'MANUAL',
  priceBasisId: '',
  contactId: '',
  recipient: '',
  subject: '',
  body: '',
  evidenceNote: '',
  externalReference: '',
})
const acceptForm = reactive({ priceBasisId: '', contactId: '', acceptedAt: '', source: 'EMAIL' as 'EMAIL' | 'PHONE' | 'MEETING' | 'OTHER', note: '' })

const quotationId = computed(() => String(route.params.quotationId || ''))
const requestedVersionId = computed(() => String(route.query.version || ''))
const requestedAddressId = computed(() => String(route.query.addressId || ''))
const selectedBasis = computed(() => version.value?.price_bases.find((item) => item.id === sendForm.priceBasisId) || version.value?.price_bases.find((item) => item.is_default) || null)
const formalDocument = computed(() => version.value?.documents.find((item) => item.is_formal) || null)
const successfulDispatches = computed(() => version.value?.dispatches.filter((item) => !item.is_simulated) || [])
const simulatedDispatches = computed(() => version.value?.dispatches.filter((item) => item.is_simulated) || [])
const emailDispatches = computed(() => version.value?.dispatches
  .filter((item) => !item.is_simulated && item.channel === 'EMAIL')
  .slice()
  .sort((left, right) => new Date(right.dispatched_at).getTime() - new Date(left.dispatched_at).getTime()) || [])
const canDispatchPermission = computed(() => authStore.canFor('quotations.dispatch_quotation', version.value))
const canIssuePermission = computed(() => authStore.canFor('quotations.issue_quotation', version.value))
const canChangeVersionPermission = computed(() => authStore.canFor(authStore.user?.sales_access_enabled ? 'access_control.lock_quotationversion' : 'quotations.change_quotationversion', version.value))
const canViewDocumentPermission = computed(() => authStore.canFor('quotations.view_quotationdocument', version.value))
const canAcceptPermission = computed(() => authStore.canFor('quotations.accept_quotation', version.value))
const isOutcomeOpen = computed(() => quotation.value?.outcome_status === 'OPEN')
const isAccepted = computed(() => quotation.value?.outcome_status === 'WON')
const acceptedVersionId = computed(() => quotation.value?.accepted_version || quotation.value?.acceptance?.quotation_version_id || '')
const canManageFormalDocument = computed(() => Boolean(
  version.value && ['ISSUED', 'SENT'].includes(version.value.status) && canIssuePermission.value,
))
const canDownloadFormalXlsx = computed(() => Boolean(
  version.value && ['ISSUED', 'SENT'].includes(version.value.status) && canViewDocumentPermission.value,
))
const canSend = computed(() => Boolean(
  version.value
  && isOutcomeOpen.value
  && ['ISSUED', 'SENT'].includes(version.value.status)
  && selectedBasis.value
  && canDispatchPermission.value
  && !(sendForm.channel === 'EMAIL' && (uncertainAttempt.value || processingAttempt.value))
  && sendForm.recipient.trim()
  && (sendForm.channel === 'EMAIL'
    ? formalDocument.value && sendForm.subject.trim() && sendForm.body.trim()
    : sendForm.evidenceNote.trim() || sendForm.externalReference.trim()),
))
const sendBlocker = computed(() => {
  if (!isOutcomeOpen.value) return `报价结果已经${quotation.value?.outcome_status_display || '终结'}，不能再次发送。`
  if (!canDispatchPermission.value) return '当前账号没有发送报价权限，请联系管理员授权。'
  if (sendForm.channel === 'EMAIL' && processingAttempt.value) return '上一封邮件仍在处理中，请等待服务端返回最终结果后刷新页面。'
  if (sendForm.channel === 'EMAIL' && uncertainAttempt.value) return '上一封邮件结果待核对，请先确认已投递或未投递。'
  if (!version.value || !['ISSUED', 'SENT'].includes(version.value.status)) return '报价需要先完成锁定和签发。'
  if (!selectedBasis.value) return '请先设置并选择一个发送价格口径。'
  if (!sendForm.recipient.trim()) return sendForm.channel === 'EMAIL' ? '请填写收件邮箱。' : '请填写人工发送对象。'
  if (sendForm.channel === 'EMAIL' && !formalDocument.value) return '邮件发送前请先生成或上传正式报价文件。'
  if (sendForm.channel === 'EMAIL' && !sendForm.subject.trim()) return '请填写邮件主题。'
  if (sendForm.channel === 'EMAIL' && !sendForm.body.trim()) return '请填写邮件正文。'
  if (sendForm.channel === 'MANUAL' && !sendForm.evidenceNote.trim() && !sendForm.externalReference.trim()) return '人工发送必须填写发送证据说明或外部凭证号。'
  return ''
})
const lockBlocker = computed(() => {
  if (!version.value || !['DRAFT', 'LOCKED'].includes(version.value.status)) return ''
  if (!isOutcomeOpen.value) return `报价结果已经${quotation.value?.outcome_status_display || '终结'}，不能再次签发。`
  if (!canIssuePermission.value) return '当前账号没有签发报价权限。'
  if (version.value.status === 'DRAFT' && (!canChangeVersionPermission.value || (!authStore.user?.sales_access_enabled && !quotation.value?.allowed_actions.edit))) return '当前账号没有锁定此报价版本的权限。'
  if (!version.value.price_bases.length) return '请先返回编辑页设置至少一个价格口径。'
  if (version.value.status === 'DRAFT' && !lockForm.contactId) return '缺少可用联系人，暂时不能锁定。'
  if (version.value.status === 'DRAFT' && !lockForm.addressId) return '缺少交易主体地址，暂时不能锁定。'
  return ''
})
const lockRepairTarget = computed(() => {
  if (!version.value || version.value.status !== 'DRAFT') return null
  if (!version.value.price_bases.length) return { section: 'price-basis', label: '价格方案' }
  if (!lockForm.contactId) return { section: 'buyer-contact', label: '联系人' }
  if (!lockForm.addressId) return { section: 'buyer-address', label: '客户地址' }
  return null
})
const lockGuidance = computed(() => {
  if (lockBlocker.value) return lockBlocker.value
  if (version.value?.status === 'LOCKED') return '版本已锁定，请点击“锁定并签发”完成签发。'
  return '核对联系人、客户地址和价格方案后，即可锁定并签发。'
})
const isViewingAcceptedVersion = computed(() => Boolean(
  version.value && acceptedVersionId.value && version.value.id === acceptedVersionId.value,
))
const canCreateSample = computed(() => Boolean(
  version.value
  && (isAccepted.value ? isViewingAcceptedVersion.value : version.value.status === 'SENT' && quotation.value?.current_version?.id === version.value.id)
  && version.value.lines.length
  && authStore.hasPermission('samples.add_samplerequest')
  && authStore.canFor('quotations.view_quotationversion', version.value),
))
const canCreateSalesOrder = computed(() => Boolean(isAccepted.value && isViewingAcceptedVersion.value && (!authStore.user?.sales_access_enabled || authStore.canFor('sales_orders.add_salesorder', version.value))))
const selectedTotal = computed(() => {
  if (!version.value || !selectedBasis.value) return null
  return version.value.lines.reduce((total, line) => {
    const price = selectedBasis.value!.line_prices.find((item) => item.quotation_line_id === line.id)
    if (!price) return total
    return total + Number(line.quantity) * Number(price.unit_price) * (1 - Number(line.discount_rate))
  }, 0)
})
const templateConfig = computed<Record<string, unknown>>(() => {
  const snapshotConfig = version.value?.template_snapshot?.template_config
  return snapshotConfig && Object.keys(snapshotConfig).length
    ? snapshotConfig
    : version.value?.template_config || {}
})
const templateName = computed(() => version.value?.template_snapshot?.template_name || version.value?.template_name || '固定报价模板未建档')
const templateVersion = computed(() => version.value?.template_snapshot?.template_version || version.value?.template_version || null)
const templateLabel = computed(() => `${templateName.value}${templateVersion.value ? ` V${templateVersion.value}.0` : ''}`)
const templateBrand = computed(() => String(templateConfig.value.seller_company_name || templateConfig.value.brand_name || 'haiqu'))
const sellerProfileLines = computed(() => [
  [templateText('seller_contact_person', ''), templateText('seller_phone', ''), templateText('seller_email', '')].filter(Boolean).join(' · '),
  templateText('seller_address', ''),
  [templateText('seller_whatsapp', ''), templateText('seller_wechat', ''), templateText('seller_fax', '')].filter(Boolean).join(' · '),
  [templateText('seller_skype', ''), templateText('seller_qq', ''), templateText('seller_website', '')].filter(Boolean).join(' · '),
].filter(Boolean))
const containerTierRows = computed(() => version.value?.lines.flatMap((line) => (line.container_tiers || []).map((tier) => ({ line, tier }))) || [])
const paymentTerms = computed(() => String(version.value?.terms_snapshot.payment_terms || '未填写'))
const leadTime = computed(() => String(version.value?.terms_snapshot.lead_time || '未填写'))
const quotationDate = computed(() => version.value?.issued_at ? version.value.issued_at.slice(0, 10) : '待生成')
const buyerContactName = computed(() => snapshotText(version.value?.contact_snapshot, ['display_name', 'name', 'contact_name', 'full_name'], '联系人待选择'))
const buyerAddressText = computed(() => snapshotText(version.value?.address_snapshot, ['full_address', 'address', 'address_line', 'city', 'label'], '地址待选择'))
const canRegenerate = computed(() => Boolean(formalDocument.value && version.value?.status === 'ISSUED' && !successfulDispatches.value.length && canIssuePermission.value))
const emailBodyCharacterCount = computed(() => plainTextFromRichText(sendForm.body).length)
const sentPriceBases = computed(() => {
  if (!version.value) return []
  const sentBasisIds = new Set(successfulDispatches.value.map((record) => record.price_basis_id).filter(Boolean))
  return version.value.price_bases.filter((basis) => sentBasisIds.has(basis.id))
})
const canRecordAcceptance = computed(() => (
  quotation.value?.outcome_status === 'OPEN'
  && version.value?.status === 'SENT'
  && sentPriceBases.value.length > 0
  && canAcceptPermission.value
))

function formatMoney(value: number): string {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}

function lineAmount(line: QuotationLine): string {
  if (!selectedBasis.value) return '—'
  const price = selectedBasis.value.line_prices.find((item) => item.quotation_line_id === line.id)
  if (!price) return '—'
  return formatMoney(Number(line.quantity) * Number(price.unit_price) * (1 - Number(line.discount_rate)))
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function dispatchRecipient(record: QuotationDispatchRecord): string {
  const recipient = record.recipient_snapshot?.email
  return typeof recipient === 'string' && recipient.trim() ? recipient : '未记录收件邮箱'
}

function dispatchSender(record: QuotationDispatchRecord): string {
  const account = record.recipient_snapshot?.email_account
  if (!account || typeof account !== 'object') return '未记录发件邮箱'
  const sender = (account as Record<string, unknown>).sender_email
  return typeof sender === 'string' && sender.trim() ? sender : '未记录发件邮箱'
}

function dispatchSubject(record: QuotationDispatchRecord): string {
  const prefix = '邮件服务已接受投递；主题：'
  return record.notes?.startsWith(prefix) ? record.notes.slice(prefix.length) : '未记录主题'
}

function formatDispatchTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function acceptanceSourceLabel(source: string | undefined): string {
  return ({ EMAIL: '邮件', PHONE: '电话', MEETING: '会议', OTHER: '其他' } as Record<string, string>)[source || ''] || '未记录'
}

function templateText(key: string, fallback: string): string {
  const value = templateConfig.value[key]
  return typeof value === 'string' && value.trim() ? value : fallback
}

function snapshotText(snapshot: Record<string, unknown> | undefined, keys: string[], fallback: string): string {
  if (!snapshot) return fallback
  for (const key of keys) {
    const value = snapshot[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return fallback
}

function applyTemplateSendDefaults() {
  if (!quotation.value) return
  if (!sendForm.subject) {
    sendForm.subject = templateText('email_subject', 'Quotation {quotation_number} from haiqu')
      .replace('{quotation_number}', quotation.value.quotation_number)
  }
  if (!sendForm.body) {
    sendForm.body = toRichTextHtml(templateText('email_body', 'Dear Customer,\n\nPlease find our quotation attached.\n\nBest regards,\nhaiqu team'))
  }
}

function toRichTextHtml(value: string): string {
  const trimmedValue = value.trim()
  if (/<[a-z][\s\S]*>/i.test(trimmedValue)) return trimmedValue
  return trimmedValue
    .split(/\r?\n/)
    .map((line) => line ? `<p>${escapeHtml(line)}</p>` : '<p><br></p>')
    .join('')
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] || character)
}

function plainTextFromRichText(value: string): string {
  return value
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
}

function openEmailEditor() {
  emailBodyDraft.value = sendForm.body
  emailWorkflow.reset('F03-S02')
  emailEditorVisible.value = true
}

function saveEmailBody() {
  if (!plainTextFromRichText(emailBodyDraft.value)) {
    ElMessage.warning('请填写邮件正文。')
    return
  }
  sendForm.body = emailBodyDraft.value
  emailEditorVisible.value = false
  emailWorkflow.reset('F03-S03')
}

function readableError(error: unknown): string {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '操作失败，请稍后重试。'
  if (!error.response) return '网络异常，请检查连接后重试。'
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有报价操作权限。'
  if (error.response.status === 412) return '报价已被其他人更新，请重新加载后重试。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载后重试。'
  const payload = error.response.data as {
    detail?: string
    error?: { message?: string; details?: Record<string, string[] | string> }
    [key: string]: unknown
  }
  const details = payload.error?.details || payload
  const detailMessage = Object.entries(details)
    .filter(([key]) => !['error', 'detail'].includes(key))
    .flatMap(([, value]) => Array.isArray(value) ? value : typeof value === 'string' ? [value] : [])
    .find(Boolean)
  return payload.error?.message || payload.detail || detailMessage || '报价服务暂时异常，请稍后重试。'
}

function applyVersion(value: QuotationVersionDetail, etag: string) {
  version.value = value
  versionEtag.value = etag
  if (!sendForm.priceBasisId) sendForm.priceBasisId = value.price_bases.find((item) => item.is_default)?.id || value.price_bases[0]?.id || ''
}

function contactEmail(contactId: string): string {
  const contact = contacts.value.find((item) => item.id === contactId)
  return contact?.methods.find((item) => item.method_type === 'EMAIL' && item.is_primary)?.display_value
    || contact?.methods.find((item) => item.method_type === 'EMAIL')?.display_value
    || ''
}

function onContactChange(contactId: string) {
  sendForm.recipient = contactEmail(contactId)
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16)
    return (character === 'x' ? random : (random & 0x3) | 0x8).toString(16)
  })
}

function restoreAttemptForm(attempt: QuotationEmailDispatchAttempt) {
  activeEmailKey.value = attempt.idempotency_key
  sendForm.channel = 'EMAIL'
  sendForm.priceBasisId = attempt.price_basis_id
  sendForm.recipient = attempt.recipient
  sendForm.subject = attempt.subject
  sendForm.body = attempt.body_html
}

async function loadEmailAttempts(versionId: string) {
  if (!canDispatchPermission.value) {
    emailAttempts.value = []
    uncertainAttempt.value = null
    processingAttempt.value = null
    return
  }
  emailAttempts.value = await fetchQuotationEmailAttempts(versionId)
  uncertainAttempt.value = emailAttempts.value.find((attempt) => attempt.status === 'UNCERTAIN') || null
  processingAttempt.value = emailAttempts.value.find((attempt) => attempt.status === 'PROCESSING') || null
  const pendingAttempt = uncertainAttempt.value || processingAttempt.value
  if (pendingAttempt) {
    restoreAttemptForm(pendingAttempt)
    emailWorkflow.reset(processingAttempt.value ? 'F03-S04' : 'F03-S07')
  }
}

async function refreshServerState() {
  if (!version.value) return
  const [quoteResult, versionResult] = await Promise.all([
    fetchQuotation(quotationId.value),
    fetchQuotationVersion(version.value.id),
  ])
  quotation.value = quoteResult.data
  quotationEtag.value = quoteResult.etag
  applyVersion(versionResult.data, versionResult.etag)
  await loadEmailAttempts(versionResult.data.id)
}

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  dependencyWarnings.value = []
  try {
    const quoteResult = await fetchQuotation(quotationId.value)
    quotation.value = quoteResult.data
    quotationEtag.value = quoteResult.etag
    if (!quoteResult.data.current_version) throw new Error('该报价尚未创建版本。')
    const versionResult = await fetchQuotationVersion(requestedVersionId.value || quoteResult.data.current_version.id)
    if (versionResult.data.quotation !== quoteResult.data.id) {
      throw new Error('所选报价版本不属于当前报价，请返回报价列表后重新进入。')
    }
    applyVersion(versionResult.data, versionResult.etag)
    // 三组资料互不依赖，全部就绪后再开放原有签发和发送操作。
    await Promise.all([
      (async () => {
        try { await loadEmailAttempts(versionResult.data.id) }
        catch (error) {
          emailAttempts.value = []; uncertainAttempt.value = null; processingAttempt.value = null
          dependencyWarnings.value.push(`邮件尝试记录加载失败：${readableError(error)}`)
        }
      })(),
      (async () => {
        try {
          const result = await fetchCustomerContacts(quoteResult.data.customer_account, { page: 1, page_size: 100 })
          contacts.value = result.data.filter(item => item.status === 'ACTIVE')
        } catch (error) {
          contacts.value = []
          dependencyWarnings.value.push(`联系人加载失败：${readableError(error)}`)
        }
      })(),
      (async () => {
        try {
          const entities = await fetchCustomerEntities(quoteResult.data.customer_account)
          const entity = entities.find(item => item.id === quoteResult.data.transaction_entity)
          addresses.value = entity ? await fetchEntityAddresses(entity.id) : []
        } catch (error) {
          addresses.value = []
          dependencyWarnings.value.push(`客户地址加载失败：${readableError(error)}`)
        }
      })(),
    ])
    applyTemplateSendDefaults()
    lockForm.contactId ||= contacts.value.find((item) => item.is_primary_contact)?.id || contacts.value[0]?.id || ''
    lockForm.addressId ||= addresses.value.find((item) => item.id === requestedAddressId.value)?.id || addresses.value[0]?.id || ''
    sendForm.contactId ||= lockForm.contactId
    if (!sendForm.recipient) onContactChange(sendForm.contactId)
    applyTemplateSendDefaults()
  } catch (error) {
    errorMessage.value = readableError(error)
  } finally {
    loading.value = false
  }
}

async function lockAndIssue() {
  if (!version.value) return
  if (lockBlocker.value) return ElMessage.warning(lockBlocker.value)
  actionLoading.value = true
  workflowDetail.value = ''
  try {
    if (version.value.status === 'DRAFT') {
      lockWorkflow.setState('F01-S02')
      const basis = version.value.price_bases.find((item) => item.is_default) || version.value.price_bases[0]
      const locked = await lockQuotationVersion(version.value.id, {
        address_id: lockForm.addressId,
        contact_id: lockForm.contactId,
        tax_rate: String(version.value.terms_snapshot.tax_rate || '0'),
        terms: { incoterm_code: basis.incoterm_code, incoterm_label: basis.label, named_place: basis.named_place },
      }, versionEtag.value)
      applyVersion(locked.data, locked.etag)
    }
    if (version.value.status === 'LOCKED') {
      lockWorkflow.setState('F01-S03')
      const issued = await issueQuotationVersion(version.value.id, versionEtag.value)
      applyVersion(issued.data, issued.etag)
    }
    lockWorkflow.setState('F01-S04')
    await refreshServerState()
    ElMessage.success('报价版本已锁定并签发，可登记正式文件。')
  } catch (error) {
    workflowDetail.value = readableError(error)
    try {
      await refreshServerState()
    } catch {
      // 保留原错误；刷新失败不覆盖流程事实提示。
    }
    if (version.value?.status === 'ISSUED') lockWorkflow.reset('F01-S04')
    else if (version.value?.status === 'LOCKED') lockWorkflow.reset('F01-S05')
    else lockWorkflow.reset('F01-S01')
    ElMessage.error(workflowDetail.value)
  } finally {
    actionLoading.value = false
  }
}

async function handleLockAndIssue() {
  if (!lockBlocker.value) {
    await lockAndIssue()
    return
  }
  if (!lockRepairTarget.value) {
    ElMessage.warning(lockBlocker.value)
    return
  }
  try {
    await ElMessageBox.confirm(
      `${lockBlocker.value} 是否前往报价编辑补充${lockRepairTarget.value.label}？`,
      '签发条件未完成',
      {
        confirmButtonText: '前往补充',
        cancelButtonText: '暂不处理',
        confirmButtonClass: 'quotation-lock-guidance-dialog__primary',
        cancelButtonClass: 'quotation-lock-guidance-dialog__secondary',
        customClass: 'quotation-lock-guidance-dialog',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await router.push({
    name: 'quotation-edit',
    params: { quotationId: quotationId.value },
    query: { section: lockRepairTarget.value.section },
  })
}

async function generateFormalPdf() {
  if (!version.value) return
  if (!canIssuePermission.value) return ElMessage.warning('当前账号没有签发报价权限。')
  actionLoading.value = true
  documentWorkflow.reset(formalDocument.value ? 'F02-S07' : 'F02-S01')
  try {
    const result = await generateFormalQuotationPdf(version.value.id, versionEtag.value)
    applyVersion(result.data, result.etag)
    documentWorkflow.reset('F02-S02')
    await refreshServerState()
    ElMessage.success('固定模板 PDF 已生成并登记为当前版本正式文件。')
  } catch (error) {
    documentWorkflow.reset(formalDocument.value ? 'F02-S02' : 'F02-S01')
    workflowDetail.value = readableError(error)
    ElMessage.error(readableError(error))
  } finally {
    actionLoading.value = false
  }
}

async function downloadFormal() {
  if (!version.value || !formalDocument.value || !canViewDocumentPermission.value) return
  actionLoading.value = true
  try {
    const result = await downloadFormalQuotationDocument(version.value.id)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = result.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    documentWorkflow.reset('F02-S08')
  } catch (error) {
    ElMessage.error(readableError(error))
  } finally {
    actionLoading.value = false
  }
}

async function downloadFormalXlsxFile() {
  if (!version.value || !canDownloadFormalXlsx.value) return
  actionLoading.value = true
  try {
    const result = await downloadFormalQuotationXlsx(version.value.id)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = result.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    documentWorkflow.reset('F02-S08')
  } catch (error) {
    ElMessage.error(readableError(error))
  } finally {
    actionLoading.value = false
  }
}

async function uploadFormal(file: File) {
  if (!version.value) return
  documentWorkflow.reset('F02-S03')
  const validationError = await validateFormalFile(file)
  if (validationError) {
    documentWorkflow.reset('F02-S06')
    workflowDetail.value = validationError
    ElMessage.error(validationError)
    return
  }
  actionLoading.value = true
  documentWorkflow.reset('F02-S04')
  try {
    const result = await uploadFormalQuotationDocument(version.value.id, file, versionEtag.value)
    applyVersion(result.data, result.etag)
    documentWorkflow.reset('F02-S05')
    await refreshServerState()
    ElMessage.success('正式报价文件已校验并登记。')
  } catch (error) {
    documentWorkflow.reset('F02-S06')
    workflowDetail.value = readableError(error)
    ElMessage.error(readableError(error))
  } finally {
    actionLoading.value = false
  }
}

async function validateFormalFile(file: File): Promise<string> {
  if (file.size > 10 * 1024 * 1024) return '文件不能超过 10MB。'
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !['pdf', 'xlsx'].includes(extension)) return '仅支持 PDF 或 XLSX 文件。'
  const header = new Uint8Array(await file.slice(0, 8).arrayBuffer())
  const isPdf = header.length >= 5 && String.fromCharCode(...header.slice(0, 5)) === '%PDF-'
  const isXlsx = header.length >= 4 && header[0] === 0x50 && header[1] === 0x4b && header[2] === 0x03 && header[3] === 0x04
  if ((extension === 'pdf' && !isPdf) || (extension === 'xlsx' && !isXlsx)) return '文件扩展名与真实文件签名不一致。'
  return ''
}

function handleFormalChange(file: UploadFile) {
  if (file.raw) void uploadFormal(file.raw)
}

async function submitDispatch() {
  if (!version.value || !selectedBasis.value) return
  if (!sendForm.recipient.trim()) return ElMessage.warning('请填写收件人邮箱或人工发送对象。')
  if (sendBlocker.value) return ElMessage.warning(sendBlocker.value)
  if (sendForm.channel === 'EMAIL' && emailDispatches.value.length) {
    emailWorkflow.setState('F03-S06')
    try {
      await ElMessageBox.confirm(
        `该报价已通过邮件发送 ${emailDispatches.value.length} 次，仍要再次发送给 ${sendForm.recipient.trim()} 吗？`,
        '确认再次发送',
        { confirmButtonText: '再次发送', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  const channel = sendForm.channel
  if (channel === 'EMAIL') activeEmailKey.value = newIdempotencyKey()
  actionLoading.value = true
  if (channel === 'EMAIL') emailWorkflow.reset('F03-S04')
  else manualWorkflow.setState('F04-S02')
  try {
    const result = channel === 'EMAIL'
      ? await sendQuotationEmail(version.value.id, {
          idempotency_key: activeEmailKey.value,
          price_basis_id: selectedBasis.value.id,
          recipient: sendForm.recipient.trim(),
          subject: sendForm.subject.trim(),
          body: sendForm.body.trim(),
        }, versionEtag.value)
      : await confirmManualQuotationDispatch(version.value.id, {
          price_basis_id: selectedBasis.value.id,
          recipient_snapshot: { contact_id: sendForm.contactId || null, recipient: sendForm.recipient.trim() },
          evidence_note: sendForm.evidenceNote.trim(),
          external_reference: sendForm.externalReference.trim(),
        }, versionEtag.value)
    applyVersion(result.data, result.etag)
    if (channel === 'EMAIL') emailWorkflow.reset('F03-S05')
    else manualWorkflow.setState('F04-S03')
    activeEmailKey.value = ''
    await refreshServerState()
    ElMessage.success(channel === 'EMAIL'
      ? '邮件服务已接受投递，报价已标记为已发送。'
      : '人工发送证据已登记，报价已标记为已发送。')
  } catch (error) {
    workflowDetail.value = readableError(error)
    if (channel === 'EMAIL') {
      try {
        const attempts = activeEmailKey.value
          ? await fetchQuotationEmailAttempts(version.value.id, activeEmailKey.value)
          : []
        const attempt = attempts[0]
        if (attempt?.status === 'UNCERTAIN') {
          uncertainAttempt.value = attempt
          processingAttempt.value = null
          restoreAttemptForm(attempt)
          emailWorkflow.reset('F03-S07')
          resolutionDialogVisible.value = true
        } else if (attempt?.status === 'PROCESSING') {
          processingAttempt.value = attempt
          uncertainAttempt.value = null
          restoreAttemptForm(attempt)
          emailWorkflow.reset('F03-S04')
        } else if (attempt?.status === 'FAILED') {
          emailWorkflow.reset('F03-S07')
          activeEmailKey.value = ''
        } else if (error instanceof AxiosError && error.response?.status === 409) {
          emailWorkflow.reset('F03-S07')
        } else {
          emailWorkflow.reset('F03-S07')
        }
      } catch {
        emailWorkflow.reset('F03-S07')
      }
    } else {
      manualWorkflow.reset('F04-S04')
    }
    ElMessage.error(workflowDetail.value)
  } finally {
    actionLoading.value = false
  }
}

function openResolutionDialog() {
  if (!uncertainAttempt.value) return
  resolutionForm.result = 'ACCEPTED'
  resolutionForm.note = ''
  resolutionDialogVisible.value = true
}

async function closeResolutionDialog() {
  resolutionDialogVisible.value = false
  try {
    await refreshServerState()
  } catch (error) {
    ElMessage.error(readableError(error))
  }
}

async function resolveEmailAttempt() {
  if (!uncertainAttempt.value || !version.value) return
  if (resolutionForm.note.trim().length < 2) return ElMessage.warning('请填写至少 2 个字的核对说明。')
  actionLoading.value = true
  try {
    const result = await resolveQuotationEmailAttempt(
      uncertainAttempt.value.id,
      { result: resolutionForm.result, note: resolutionForm.note.trim() },
      versionEtag.value,
    )
    applyVersion(result.data, result.etag)
    const accepted = resolutionForm.result === 'ACCEPTED'
    emailWorkflow.reset(accepted ? 'F03-S05' : 'F03-S07')
    uncertainAttempt.value = null
    processingAttempt.value = null
    activeEmailKey.value = ''
    resolutionDialogVisible.value = false
    await refreshServerState()
    ElMessage.success(accepted ? '已确认邮件投递并登记发送记录。' : '已确认邮件未投递，可以重新发送。')
  } catch (error) {
    workflowDetail.value = readableError(error)
    ElMessage.error(workflowDetail.value)
    await refreshServerState().catch(() => undefined)
  } finally {
    actionLoading.value = false
  }
}

function openAcceptDialog() {
  if (!version.value) return
  acceptForm.priceBasisId = sentPriceBases.value.find((basis) => basis.id === selectedBasis.value?.id)?.id || sentPriceBases.value[0]?.id || ''
  acceptForm.contactId = sendForm.contactId
  acceptForm.acceptedAt = new Date().toISOString()
  acceptForm.note = ''
  acceptDialogVisible.value = true
  acceptanceWorkflow.reset('F05-S01')
}

async function submitAcceptance() {
  if (!quotation.value || !version.value || !acceptForm.priceBasisId) return
  actionLoading.value = true
  acceptanceWorkflow.setState('F05-S02')
  try {
    const result = await acceptQuotation(quotation.value.id, {
      accepted_version_id: version.value.id,
      price_basis_id: acceptForm.priceBasisId,
      customer_contact_id: acceptForm.contactId || null,
      accepted_at: acceptForm.acceptedAt,
      source: acceptForm.source,
      note: acceptForm.note.trim(),
    }, quotationEtag.value)
    quotation.value = result.data
    quotationEtag.value = result.etag
    acceptanceWorkflow.setState('F05-S03')
    acceptDialogVisible.value = false
    await refreshServerState()
    ElMessage.success('客户接受结果已登记，现在可以创建销售订单或样品。')
  } catch (error) {
    acceptanceWorkflow.reset('F05-S04')
    workflowDetail.value = readableError(error)
    ElMessage.error(readableError(error))
  } finally {
    actionLoading.value = false
  }
}

function basisPrice(line: QuotationLine, basis: QuotationPriceBasis | null): string {
  return basis?.line_prices.find((item) => item.quotation_line_id === line.id)?.unit_price || '—'
}

function createSampleFromQuotation() {
  const sourceId = isAccepted.value ? acceptedVersionId.value : version.value?.id
  if (!sourceId) return
  void router.push({ name: 'sample-new', query: { sourceType: 'quotation', sourceId } })
}

async function createSalesOrderFromQuotation() {
  if (!acceptedVersionId.value) return
  actionLoading.value = true
  try {
    const context = await fetchQuotationOrderContext(acceptedVersionId.value)
    if (!context.lines.some((line) => Number(line.remaining_quantity) > 0)) {
      ElMessage.info('当前报价已全部转为销售订单，没有剩余可转数量。')
      return
    }
    await router.push({
      name: 'sales-order-create',
      query: { source: 'QUOTATION', quotationVersionId: acceptedVersionId.value },
    })
  } catch (error) {
    ElMessage.error(readableError(error))
  } finally {
    actionLoading.value = false
  }
}

function refreshWhenVisible() {
  if (document.visibilityState === 'visible' && version.value && !actionLoading.value) {
    void refreshServerState().catch(() => undefined)
  }
}

onMounted(() => {
  void loadPage()
  document.addEventListener('visibilitychange', refreshWhenVisible)
})
onUnmounted(() => document.removeEventListener('visibilitychange', refreshWhenVisible))
</script>

<template>
  <section v-loading="loading" class="quotation-preview-page" aria-label="固定模板预览与发送">
    <template v-if="quotation && version">
      <header class="preview-header">
        <div><div class="preview-title"><h1>报价预览</h1><QuotationStatusTag v-if="isOutcomeOpen" tone="neutral">{{ version.status_display }}</QuotationStatusTag><QuotationStatusTag v-else :tone="isAccepted ? 'success' : 'danger'">{{ quotation.outcome_status_display }}</QuotationStatusTag></div><p>{{ quotation.quotation_number }} / V{{ version.version_number }} · {{ templateLabel }}</p></div>
        <div class="header-actions"><ElButton v-if="formalDocument" class="regenerate-button" text :icon="Refresh" :disabled="!canRegenerate" :title="canRegenerate ? '重新生成会保留旧文件记录' : '无签发权限或已发送版本不可重新生成'" @click="generateFormalPdf">重新生成</ElButton><ElButton :icon="Download" :disabled="!formalDocument || !canViewDocumentPermission" :title="canViewDocumentPermission ? '' : '当前账号没有查看正式文件权限'" @click="downloadFormal">下载 PDF</ElButton><ElButton :icon="Download" :disabled="!canDownloadFormalXlsx" @click="downloadFormalXlsxFile">下载 XLSX</ElButton></div>
      </header>

      <ElAlert v-for="warning in dependencyWarnings" :key="warning" class="dependency-alert" :title="warning" type="warning" :closable="false" show-icon />

      <div class="preview-layout">
        <ElCard class="document-card" shadow="never">
          <template #header>
            <div class="document-heading">
              <div><b>报价文件预览</b></div>
              <div class="document-heading__status"><QuotationStatusTag :tone="formalDocument ? 'success' : 'warning'">{{ formalDocument ? '正式文件已生成' : '草稿预览 · 未生成正式文件' }}</QuotationStatusTag><span>第 1 / 1 页</span></div>
            </div>
          </template>
          <section class="quotation-document">
            <header class="quotation-document__header">
              <div class="quotation-document__brand"><b>{{ templateBrand }}</b><span>{{ templateLabel }}</span></div>
              <div class="quotation-document__meta"><strong>QUOTATION / 报价单</strong><span>Quotation No. {{ quotation.quotation_number }}</span><span>Issue date&nbsp; {{ quotationDate }}</span><span>Valid until&nbsp; {{ version.valid_until || '未填写' }}</span></div>
            </header>

            <div class="quotation-document__divider" />

            <div class="quotation-document__parties">
              <section class="party-card">
                <small>SELLER / 卖方</small><b>{{ templateBrand }}</b>
                <span v-for="line in sellerProfileLines" :key="line">{{ line }}</span>
                <span v-if="!sellerProfileLines.length">卖方联系资料待维护</span>
              </section>
              <section class="party-card">
                <small>BUYER / 买方</small><b>{{ version.transaction_entity_snapshot.legal_name || quotation.customer_name }}</b>
                <span>Contact：{{ buyerContactName }}</span>
                <span>{{ buyerAddressText }}</span>
                <span>价格口径：{{ selectedBasis?.label || '尚未设置' }} · {{ version.currency_code }}</span>
              </section>
            </div>

            <section class="quotation-document__section">
              <div class="quotation-document__section-title"><b>PRODUCTS / 产品明细</b><span v-if="!selectedBasis">价格口径尚未设置，金额不在预览中虚构</span></div>
              <table class="quotation-lines-table"><thead><tr><th>Image / 图片</th><th>Product / 产品与规格</th><th>Qty / 数量</th><th>Unit price / 单价</th><th>Amount / 金额</th></tr></thead><tbody><tr v-for="item in version.lines" :key="item.id"><td><ElImage v-if="item.product_image" class="quotation-product-image" :src="quotationLineProductImageUrl(item.id)" :preview-src-list="[quotationLineProductImageUrl(item.id)]" preview-teleported fit="cover"/><span v-else class="quotation-image-placeholder">无图片</span></td><td class="quotation-product-info" :title="`${item.product_description_snapshot} · ${item.specification_snapshot || '—'}`"><b>{{ item.product_description_snapshot }}</b><span>{{ item.specification_snapshot || '—' }}</span></td><td class="quotation-number-cell"><b>{{ item.quantity }} {{ item.unit_code }}</b></td><td class="quotation-number-cell" :class="{ 'is-pending': basisPrice(item, selectedBasis) === '—' }"><b>{{ basisPrice(item, selectedBasis) === '—' ? '—' : `${version.currency_code} ${basisPrice(item, selectedBasis)}` }}</b><small v-if="basisPrice(item, selectedBasis) === '—'">待设置</small></td><td class="quotation-number-cell" :class="{ 'is-pending': lineAmount(item) === '—' }"><b>{{ lineAmount(item) === '—' ? `— ${version.currency_code}` : `${version.currency_code} ${lineAmount(item)}` }}</b></td></tr></tbody></table>
            </section>

            <section class="quotation-document__section">
              <div class="quotation-document__section-title"><b>CONTAINER TIERS / 装柜数量档</b><span>系统计算 · 可在配置页调整</span></div>
              <table v-if="containerTierRows.length" class="quotation-container-table"><thead><tr><th>产品</th><th>柜型</th><th>报价数量</th><th>装柜单价</th><th>装载系数</th><th>备注</th></tr></thead><tbody><tr v-for="row in containerTierRows" :key="row.tier.id"><td><b>{{ row.line.product_description_snapshot }}</b></td><td>{{ row.tier.container_type_code }}</td><td>{{ row.tier.final_quantity }} {{ row.line.unit_code }}</td><td>{{ version.currency_code }} {{ row.tier.unit_price }}</td><td>{{ (Number(row.tier.load_factor) * 100).toFixed(0) }}%</td><td>{{ row.tier.override_reason || '系统计算' }}</td></tr></tbody></table>
              <p v-else class="container-empty">当前报价未配置装柜数量档，固定模板不会写入示例柜型或示例数量。</p>
            </section>

            <div class="quotation-document__terms"><div><small>Payment / 付款</small><b>{{ paymentTerms }}</b></div><div><small>Lead time / 交期</small><b>{{ leadTime }}</b></div><div><small>Validity / 有效期</small><b>{{ version.valid_until || '未填写' }}</b></div></div>
            <div class="quotation-document__total"><b>TOTAL / 合计</b><strong :class="{ 'is-pending': selectedTotal === null }">{{ selectedTotal === null ? `— ${version.currency_code}` : `${version.currency_code} ${formatMoney(selectedTotal)}` }}</strong></div>
            <footer>价格口径设置完成后，将自动生成正式金额与可发送报价文件。</footer>
          </section>
        </ElCard>

        <div class="send-card-wrap">
        <ElCard class="send-card" shadow="never">
          <template #header><div class="card-heading"><b>{{ isAccepted ? '客户接受结果' : isOutcomeOpen ? '签发与文件' : '报价结果' }}</b><QuotationStatusTag :tone="isAccepted || formalDocument || version.status === 'SENT' ? 'success' : 'neutral'">{{ isAccepted ? '已接受' : formalDocument ? '文件已就绪' : version.status_display }}</QuotationStatusTag></div></template>
          <div v-if="formalDocument" class="file-block"><ElIcon><Document /></ElIcon><div><b>{{ formalDocument.original_name }}</b><small>{{ formalDocument.content_type.includes('sheet') ? 'XLSX' : 'PDF' }} · {{ formatFileSize(formalDocument.size_bytes) }} · {{ templateLabel }}</small></div><ElUpload v-if="canRegenerate" :auto-upload="false" :show-file-list="false" accept=".pdf,.xlsx" @change="handleFormalChange"><ElButton text :icon="Upload" :disabled="actionLoading">替换</ElButton></ElUpload><ElButton text :icon="Download" :loading="actionLoading" :disabled="!canViewDocumentPermission" @click="downloadFormal">下载</ElButton></div>
          <div v-else-if="isOutcomeOpen" class="document-actions">
            <ElButton class="black-button" :loading="actionLoading" :disabled="!canManageFormalDocument" :title="canManageFormalDocument ? '' : '请先完成版本锁定和签发'" @click="generateFormalPdf">生成固定模板 PDF</ElButton>
            <ElUpload :auto-upload="false" :show-file-list="false" accept=".pdf,.xlsx" :disabled="!canManageFormalDocument" @change="handleFormalChange"><ElButton :icon="Upload" :disabled="!canManageFormalDocument" :title="canManageFormalDocument ? '' : '请先完成版本锁定和签发'">上传已有文件</ElButton></ElUpload>
          </div>
          <QuotationWorkflowStatus v-if="documentWorkflow.current.value.phase !== 'INITIAL'" :state="documentWorkflow.current.value" />
          <template v-if="isOutcomeOpen">
          <QuotationWorkflowStatus v-if="lockWorkflow.current.value.phase !== 'INITIAL'" :state="lockWorkflow.current.value" />
          <ElAlert v-if="['DRAFT', 'LOCKED'].includes(version.status) && lockWorkflow.current.value.phase === 'INITIAL'" class="lock-guidance" :title="lockGuidance" type="warning" :closable="false" show-icon />
          <ElForm v-if="version.status === 'DRAFT'" label-position="top" class="lock-grid"><ElFormItem label="快照联系人 *"><ElSelect v-model="lockForm.contactId"><ElOption v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="客户地址 *"><ElSelect v-model="lockForm.addressId"><ElOption v-for="item in addresses" :key="item.id" :label="`${item.label || item.address_code} · ${item.city}`" :value="item.id" /></ElSelect></ElFormItem></ElForm>
          <ElButton v-if="version.status === 'DRAFT' || version.status === 'LOCKED'" class="black-button full-width" :class="{ 'is-guided-disabled': Boolean(lockBlocker) }" :loading="actionLoading" :data-guided-disabled="Boolean(lockBlocker)" :title="lockBlocker || '锁定当前快照并签发报价版本'" @click="handleLockAndIssue">锁定并签发</ElButton>
          <ElForm label-position="top" class="send-form">
            <ElFormItem label="发送价格口径 *"><ElSelect v-model="sendForm.priceBasisId"><ElOption v-for="item in version.price_bases" :key="item.id" :label="`${item.label}${item.is_default ? '（默认）' : ''}`" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="发送方式 *"><ElRadioGroup v-model="sendForm.channel"><ElRadioButton value="MANUAL">人工发送</ElRadioButton><ElRadioButton value="EMAIL">邮件发送</ElRadioButton></ElRadioGroup></ElFormItem>
            <ElFormItem label="联系人"><ElSelect v-model="sendForm.contactId" clearable @change="onContactChange"><ElOption v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem :label="sendForm.channel === 'EMAIL' ? '收件邮箱 *' : '人工发送对象 *'"><ElInput v-model="sendForm.recipient" :maxlength="sendForm.channel === 'EMAIL' ? 254 : 500" :placeholder="sendForm.channel === 'EMAIL' ? 'buyer@example.com' : '联系人、WhatsApp 或其他发送对象'" /></ElFormItem>
            <template v-if="sendForm.channel === 'EMAIL'"><ElFormItem label="邮件主题 *"><ElInput v-model="sendForm.subject" maxlength="250" show-word-limit /></ElFormItem><ElFormItem label="邮件正文 *"><div class="email-body-entry"><ElButton @click="openEmailEditor">{{ emailBodyCharacterCount ? '编辑邮件正文' : '填写邮件正文' }}</ElButton><small v-if="emailBodyCharacterCount">已填写 {{ emailBodyCharacterCount }} 个字符</small></div></ElFormItem></template>
            <div v-else class="manual-evidence-grid"><ElFormItem label="发送证据说明"><ElInput v-model="sendForm.evidenceNote" type="textarea" :rows="1" placeholder="例如：WhatsApp 截图已归档" /></ElFormItem><ElFormItem label="外部凭证号"><ElInput v-model="sendForm.externalReference" placeholder="两项至少填一项" /></ElFormItem></div>
          </ElForm>
          <QuotationWorkflowStatus v-if="(sendForm.channel === 'EMAIL' ? emailWorkflow.current.value : manualWorkflow.current.value).phase !== 'INITIAL'" :state="sendForm.channel === 'EMAIL' ? emailWorkflow.current.value : manualWorkflow.current.value" />
          <ElButton v-if="uncertainAttempt" class="review-attempt-button" @click="openResolutionDialog">核对上一封邮件结果</ElButton>
          <ElAlert v-if="sendBlocker && !['DRAFT', 'LOCKED'].includes(version.status)" :title="sendBlocker" type="warning" :closable="false" show-icon />
          <section v-if="emailDispatches.length" class="email-dispatch-history" aria-label="邮件发送记录">
            <div class="email-dispatch-history__heading"><b>邮件发送记录</b><span>已发送 {{ emailDispatches.length }} 次</span></div>
            <div v-for="record in emailDispatches" :key="record.id" class="email-dispatch-history__item">
              <b>{{ formatDispatchTime(record.dispatched_at) }}</b>
              <span>收件人：{{ dispatchRecipient(record) }}</span>
              <span>发件人：{{ dispatchSender(record) }}</span>
              <span>主题：{{ dispatchSubject(record) }}</span>
            </div>
          </section>
          <p class="send-log">已完成正式发送：{{ successfulDispatches.length }} 条 · 历史模拟发送：{{ simulatedDispatches.length }} 条</p>
          <ElButton class="black-button full-width" :icon="Promotion" :loading="actionLoading" :disabled="!canSend" @click="submitDispatch">{{ sendForm.channel === 'EMAIL' ? (emailDispatches.length ? '再次发送报价邮件' : '发送报价邮件') : '确认人工已发送' }}</ElButton>
          <div v-if="version.status === 'SENT'" class="post-send-actions">
            <ElButton
              :disabled="!canRecordAcceptance"
              :title="canRecordAcceptance ? '' : '仅可对已真实发送且仍待客户确认的版本登记接受'"
              @click="openAcceptDialog"
            >记录客户接受</ElButton>
            <ElButton v-if="canCreateSample" @click="createSampleFromQuotation">创建样品</ElButton>
          </div>
          </template>
          <section v-else-if="isAccepted" class="accepted-result">
            <QuotationWorkflowStatus :state="acceptanceWorkflow.current.value.phase === 'SUCCESS' ? acceptanceWorkflow.current.value : { ...acceptanceWorkflow.current.value, id: 'F05-S03', phase: 'SUCCESS', title: '客户接受已记录', description: '可按需创建样品或销售订单。' }" />
            <div><QuotationStatusTag tone="success">客户已接受报价</QuotationStatusTag><strong>接受版本：V{{ version.version_number }}</strong></div>
            <p>确认时间：{{ quotation.acceptance?.accepted_at ? formatDispatchTime(quotation.acceptance.accepted_at) : '未记录' }}</p>
            <p>确认依据：{{ acceptanceSourceLabel(quotation.acceptance?.source) }}<template v-if="quotation.acceptance?.note"> · {{ quotation.acceptance.note }}</template></p>
            <p class="responsibility-note">责任角色：业务员可直接创建销售订单或继续创建样品。</p>
            <div class="accepted-actions"><ElButton v-if="canCreateSample" @click="createSampleFromQuotation">创建样品</ElButton><ElButton v-if="canCreateSalesOrder" class="black-button" :loading="actionLoading" @click="createSalesOrderFromQuotation">创建销售订单</ElButton></div>
          </section>
          <ElAlert v-else :title="`报价结果已经${quotation.outcome_status_display}，不能继续发送。`" type="info" :closable="false" show-icon />
        </ElCard>
        </div>
      </div>

      <AppWindowDialog v-model="acceptDialogVisible" title="记录客户接受" :width="560" :height="720" :close-on-click-modal="false" @closed="refreshServerState().catch(() => undefined)">
        <QuotationWorkflowStatus :state="acceptanceWorkflow.current.value" />
        <ElAlert title="接受后报价结果更新为“已接受”；本阶段不自动创建订单或 PI。" type="warning" :closable="false" />
        <ElForm label-position="top" class="accept-form"><ElFormItem label="客户接受价格口径 *"><ElSelect v-model="acceptForm.priceBasisId"><ElOption v-for="item in sentPriceBases" :key="item.id" :label="item.label" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="确认联系人"><ElSelect v-model="acceptForm.contactId" clearable><ElOption v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="客户确认时间 *"><ElInput v-model="acceptForm.acceptedAt" /></ElFormItem><ElFormItem label="确认来源 *"><ElSelect v-model="acceptForm.source"><ElOption label="邮件" value="EMAIL"/><ElOption label="电话" value="PHONE"/><ElOption label="会议" value="MEETING"/><ElOption label="其他" value="OTHER"/></ElSelect></ElFormItem><ElFormItem label="备注"><ElInput v-model="acceptForm.note" type="textarea" :rows="3" maxlength="1000" /></ElFormItem></ElForm>
        <template #footer><ElButton @click="acceptDialogVisible = false">取消</ElButton><ElButton class="black-button" :disabled="!canRecordAcceptance" :loading="actionLoading" @click="submitAcceptance">确认接受</ElButton></template>
      </AppWindowDialog>
      <AppWindowDialog v-model="emailEditorVisible" title="编辑邮件正文" :width="860" :height="680" :close-on-click-modal="false" destroy-on-close>
        <InquiryWangEditor v-model="emailBodyDraft" upload-url="" upload-etag="" :show-upload-notice="false" :maxlength="10000" placeholder="请输入邮件正文。" />
        <template #footer><ElButton @click="emailEditorVisible = false">取消</ElButton><ElButton class="black-button" @click="saveEmailBody">确认正文</ElButton></template>
      </AppWindowDialog>
      <QuotationEmailRecoveryDialog :visible="resolutionDialogVisible" :attempt="uncertainAttempt" :state="emailWorkflow.current.value" :result="resolutionForm.result" :note="resolutionForm.note" :loading="actionLoading" @close="closeResolutionDialog" @submit="resolveEmailAttempt" @update:result="resolutionForm.result = $event" @update:note="resolutionForm.note = $event" />
    </template>
    <ElResult v-else-if="errorMessage" icon="error" title="报价预览加载失败" :sub-title="errorMessage"><template #extra><ElButton class="black-button" @click="loadPage">重新加载</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
.quotation-preview-page {
  --quotation-sans: 'Noto Sans SC Variable', sans-serif;
  --quotation-serif: 'Noto Serif SC Variable', serif;
  font-family: var(--erp-font-body);
  min-width: 0;
  max-width: none;
  margin: 0;
  padding: 0;
  font-size: 13px;
}
.quotation-document__brand b,.quotation-document__meta strong { font-family:var(--quotation-serif); }
.review-attempt-button{width:100%;margin:0;color:var(--erp-color-warning);border-color:var(--erp-color-warning-border);background:var(--erp-color-subtle)}
.quotation-preview-page{min-width:0;color:var(--erp-color-text-primary);--el-color-primary:var(--erp-color-brand);max-width: none;margin: 0;padding: 0;font-family: var(--erp-font-body);font-size: 13px}.preview-header{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:0;margin-bottom:14px;margin: 0 0 14px;flex-wrap: wrap}.back-link{display:flex;gap:4px;align-items:center;padding:0;border:0;color:var(--erp-color-text-primary);background:transparent;font-size:13px;cursor:pointer}.preview-header h1{margin:0;font-size:36px;line-height:44px;font-family: var(--erp-font-body);font-weight: 700}.preview-header p{margin:5px 0 0;color:var(--erp-color-text-regular);font-size:13px}.header-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;padding-top: 0}.black-button{--el-button-bg-color:var(--erp-button-primary-background)!important;--el-button-text-color:var(--erp-button-primary-text)!important;--el-button-border-color:var(--erp-button-primary-border) !important;--el-button-hover-bg-color:var(--erp-button-primary-hover-background)!important;--el-button-hover-text-color:var(--erp-button-primary-text)!important;--el-button-hover-border-color:var(--erp-button-primary-border) !important;color:var(--erp-button-primary-text)!important;border-color:var(--erp-button-primary-border) !important;background:var(--erp-button-primary-surface)!important}.black-button.is-disabled{--el-button-bg-color:var(--erp-color-disabled)!important;--el-button-text-color:var(--erp-color-text-disabled)!important;--el-button-border-color:var(--erp-color-border)!important;color:var(--erp-color-text-disabled)!important;border-color:var(--erp-color-border)!important;background:var(--erp-color-disabled)!important}.full-width{width:100%;margin:0}.dependency-alert{margin-bottom:10px}.preview-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,32%);gap:14px;align-items:start}.send-card-wrap{min-width:0}.document-card,.send-card{
  height: auto;
  max-height: none;
  min-height: 0;
  overflow: hidden}.document-card :deep(.el-card__header),.send-card :deep(.el-card__header){padding:0 16px;min-height: 48px;background: transparent}.card-heading{display:flex;align-items:center;gap:10px;min-height:47px}.card-heading span{margin-left:auto;color:var(--erp-color-text-regular);font-size:12px}.document-card :deep(.el-card__body){padding:0 16px 16px;height: auto;overflow: auto;background: transparent}.paper{color:#18181b;display:grid;gap:18px;min-height:638px;padding:24px;border:1px solid #d4d4d8;background:#fff}.paper-title,.paper-meta,.paper-parties,.paper-total{display:flex;justify-content:space-between;gap:16px}.paper-title b{font-size:24px}.paper-title strong{letter-spacing:.04em}.paper-meta{padding-bottom:12px;border-bottom:1px solid #d9d9d9;color:#52525b;font-size:12px}.paper-meta span:last-child,.paper-parties div:last-child{text-align:right}.paper-parties{font-size:12px}.paper-parties div{display:grid;gap:6px}.paper-parties small{color:#52525b;font-weight:700}.paper-table :deep(th){background:#f7f7f8}.product-image,.image-placeholder{width:54px;height:40px;border-radius:4px}.image-placeholder{display:inline-grid;place-items:center;color:#71717a;background:#f4f4f5;font-size:10px}.paper-total{justify-content:flex-end;padding-top:10px;border-top:1px solid #ddd}.paper-total strong{margin-left:48px}.paper footer{align-self:end;text-align:center;color:#71717a;font-size:11px}.send-card :deep(.el-card__body){display:grid;gap:14px;padding:0 16px 16px;height: auto;overflow: visible}.file-block{display:flex;align-items:center;gap:12px;padding:12px;border-radius:8px;background:var(--erp-glass-inner-background)}.file-block div{display:grid;min-width:0;flex:1;gap:4px}.file-block b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.document-actions{display:flex;gap:8px;flex-wrap:wrap}.file-block small,.send-log{color:var(--erp-color-text-regular);font-size:11px}.lock-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.manual-evidence-grid{display:grid;grid-template-columns:1.2fr 1fr;gap:8px}.post-send-actions{display:flex;gap:8px}.post-send-actions .el-button{flex:1;margin:0}.send-card :deep(.el-form-item){margin-bottom:6px}.send-card :deep(.el-select){width:100%}.send-card :deep(.el-radio-group){display:flex;width:100%}.send-card :deep(.el-radio-button){flex:1}.send-card :deep(.el-radio-button__inner){width:100%}@media(max-width:1200px){.preview-layout{grid-template-columns:minmax(0,1fr) 380px}.manual-evidence-grid{grid-template-columns:1fr}}@media(max-width:1100px){.preview-layout{grid-template-columns:1fr}.send-card{max-width:none}.manual-evidence-grid{grid-template-columns:1fr 1fr}}@media(max-width:700px){.preview-header{align-items:flex-start;flex-direction:column}.header-actions{width:100%;justify-content:flex-start}.paper{padding:20px}.paper-table{min-width:620px}.document-card :deep(.el-card__body){overflow-x:auto}.lock-grid,.manual-evidence-grid{grid-template-columns:1fr}}

/* QUO-04 confirmed Figma layout overrides. */
.quotation-preview-page{max-width:none;margin:0;min-width: 0;padding: 0;font-family: var(--erp-font-body);font-size: 13px}.preview-layout{grid-template-columns:minmax(0,1fr) minmax(340px,32%);gap:14px}.document-card,.send-card{height:auto;max-height:none;min-height:0;overflow:hidden}.document-card :deep(.el-card__header),.send-card :deep(.el-card__header){min-height:48px;padding: 0 16px;background: transparent}.document-card :deep(.el-card__body){height:auto;box-sizing:border-box;padding:0 16px 16px;overflow: auto;background: transparent}.send-card :deep(.el-card__body){height:auto;box-sizing:border-box;gap:14px;padding:0 16px 16px;overflow:visible}.paper{display:flex;height:100%;min-height:0;box-sizing:border-box;flex-direction:column;gap:12px;padding:28px 32px 18px}.paper-title>div{display:grid;gap:2px}.paper-title>div small{color:#71717a;font-size:10px;font-weight:400}.paper-title strong{font-size:18px}.paper-meta{font-size:10px;line-height:16px}.paper-parties{padding:0 0 10px;border-bottom:1px solid #e4e4e7}.paper-parties div span{color:#52525b;font-size:10px}.quote-lines-table,.container-table{width:100%;border-collapse:collapse;font-size:11px}.quote-lines-table th,.quote-lines-table td,.container-table th,.container-table td{padding:8px 9px;border-bottom:1px solid #e4e4e7;text-align:left;vertical-align:top}.quote-lines-table th,.container-table th{color:#52525b;background:#f4f4f5;font-size:10px;font-weight:700}.quote-lines-table th:nth-child(n+3),.quote-lines-table td:nth-child(n+3){text-align:right}.paper-total{padding:7px 8px 0;border-top:0;font-size:12px}.container-section{display:grid;gap:6px}.container-section h3{margin:0;font-size:11px}.container-section>p{margin:0;padding:9px;border:1px dashed #d4d4d8;color:#71717a;font-size:10px}.paper-terms{display:grid;gap:3px;color:#3f3f46;font-size:10px}.paper-terms small{color:#71717a}.paper footer{margin-top:auto}.virtual-sender{margin:-2px 0 4px;color:var(--erp-color-text-regular);font-size:11px}.send-warning{display:grid;gap:5px;padding:12px;border:1px solid var(--erp-color-warning-border);border-radius:6px;background:var(--erp-color-subtle)}.send-warning b{color:var(--erp-color-warning);font-size:13px}.send-warning span{color:var(--erp-color-text-primary);font-size:11px;line-height:18px}.send-card .file-block{min-height:68px;box-sizing:border-box}.send-form{display:grid}.send-card :deep(.el-form-item__label){padding-bottom:4px;font-size:12px}.regenerate-button{width:auto!important}
.quote-lines-table th:nth-child(n+4),.quote-lines-table td:nth-child(n+4){text-align:right}
@media(max-width:1500px){.quotation-preview-page{margin-top:0}.preview-header{min-height:91px;margin-bottom:14px}.preview-header h1{margin-top:0;font-size:26px;line-height:32px}.preview-header p{margin-top:5px;font-size:13px}.regenerate-button{display:none}.document-card,.send-card{height:auto;min-height:580px}.document-card :deep(.el-card__header),.send-card :deep(.el-card__header){min-height:48px}.card-heading{min-height:47px}.document-card :deep(.el-card__body){height:calc(100% - 48px);padding:0 16px 18px}.send-card :deep(.el-card__body){height:calc(100% - 48px);padding:12px 16px 14px}.paper{gap:11px;padding:24px}.send-card :deep(.el-form-item){margin-bottom:5px}.send-card :deep(.el-input__wrapper){min-height:30px}.send-card :deep(.el-textarea__inner){min-height:60px!important}.send-warning{padding:10px}.send-card .file-block{min-height:68px}.send-log{margin:2px 0}}
@media(max-width:1100px){.quotation-preview-page{margin-top:0}.preview-layout{grid-template-columns:1fr}.document-card,.send-card{height:auto;max-height:none;min-height:0}.document-card :deep(.el-card__body),.send-card :deep(.el-card__body){height:auto}.paper{min-height:620px}}

/* 报价文件预览：按已确认的 Figma 信息层级展示，发送设置卡片不受影响。 */.document-card :deep(.el-card__header){padding:0 16px;border-bottom:0;background:transparent}.document-card :deep(.el-card__body){overflow:auto;padding:0 16px 16px;background:transparent;height: auto}.document-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:48px;flex-wrap: wrap}.document-heading>div:first-child{display:grid;gap:2px}.document-heading b{font-size:17px;line-height:24px}.document-heading small,.document-heading span{color:var(--erp-color-text-regular);font-size:11px;line-height:16px}.document-heading__status{display:flex;align-items:center;gap:10px;white-space:nowrap}.quotation-document{color:#18181b;display:flex;min-width:820px;min-height:100%;box-sizing:border-box;flex-direction:column;gap:20px;padding:36px 38px 28px;border:1px solid #dde1e8;border-radius:8px;background:#fff}.quotation-document__header{display:flex;align-items:flex-start;justify-content:space-between;gap:32px}.quotation-document__brand{display:grid;gap:4px}.quotation-document__brand b{font-size:30px;line-height:38px;letter-spacing:-.02em}.quotation-document__brand span{color:#71717a;font-size:11px}.quotation-document__meta{display:grid;justify-items:end;gap:4px;color:#71717a;font-size:11px;line-height:16px;text-align:right}.quotation-document__meta strong{margin-bottom:2px;color:#1f2329;font-size:21px;line-height:28px;letter-spacing:.01em}.quotation-document__divider{height:1px;background:#d9dfe7}.quotation-document__parties{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.party-card{display:grid;gap:6px;min-height:118px;box-sizing:border-box;padding:16px 18px;border:1px solid #e3e8f0;border-radius:8px;background:#f7fafc}.party-card small{color:#71717a;font-size:10px;font-weight:700}.party-card b{font-size:15px;line-height:22px}.party-card span{color:#626975;font-size:11px;line-height:16px;overflow-wrap:anywhere}.quotation-document__section{display:grid;gap:9px}.quotation-document__section-title{display:flex;align-items:center;justify-content:space-between;gap:16px}.quotation-document__section-title b{font-size:13px;line-height:20px}.quotation-document__section-title span{color:#71717a;font-size:11px;line-height:16px;text-align:right}.quotation-lines-table,.quotation-container-table{width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed}.quotation-lines-table th,.quotation-container-table th{padding:9px 12px;color:#68707d;background:#f3f5f7;font-size:10px;font-weight:700;text-align:left}.quotation-lines-table td,.quotation-container-table td{padding:13px 12px;border-bottom:1px solid #e6e9ee;vertical-align:top}.quotation-lines-table th:nth-child(1){width:82px}.quotation-lines-table th:nth-child(2){width:auto}.quotation-lines-table th:nth-child(3){width:82px}.quotation-lines-table th:nth-child(4){width:120px}.quotation-lines-table th:nth-child(5){width:108px}.quotation-lines-table th:nth-child(n+3),.quotation-lines-table td:nth-child(n+3){text-align:right}.quotation-product-image,.quotation-image-placeholder{display:inline-grid;width:74px;height:74px;border-radius:6px;overflow:hidden}.quotation-image-placeholder{place-items:center;color:#8a919d;background:#f4f5f7;font-size:10px}.quotation-product-info{display:grid;gap:6px}.quotation-product-info b{font-size:14px;line-height:20px}.quotation-product-info span{color:#68707d;line-height:16px;white-space:pre-line;overflow-wrap:anywhere}.quotation-lines-table td:nth-child(n+3){display:table-cell;color:#2f3540;font-size:12px;line-height:18px}.quotation-lines-table td:nth-child(n+3) b,.quotation-lines-table td:nth-child(n+3) span{display:block}.quotation-lines-table .is-pending{color:#a1610d!important}.quotation-container-table th:nth-child(1){width:26%}.quotation-container-table th:nth-child(2){width:16%}.quotation-container-table th:nth-child(3){width:20%}.quotation-container-table th:nth-child(4){width:18%}.quotation-container-table th:nth-child(5){width:20%}.quotation-container-table td{padding-top:11px;padding-bottom:11px}.container-empty{margin:0;padding:10px 12px;border:1px dashed #d4d9e1;border-radius:6px;color:#71717a;font-size:11px}.quotation-document__terms{display:flex;gap:32px;padding:14px 16px;border-radius:8px;background:#fafafc}.quotation-document__terms div{display:grid;gap:3px;min-width:74px}.quotation-document__terms small{color:#71717a;font-size:10px}.quotation-document__terms b{font-size:13px;line-height:19px}.quotation-document__total{display:flex;align-items:center;justify-content:space-between;padding-top:4px}.quotation-document__total b{font-size:14px}.quotation-document__total strong{font-size:19px;line-height:28px}.quotation-document__total .is-pending{color:#a1610d}.quotation-document footer{margin-top:auto;color:#71717a;font-size:10px;line-height:16px}@media(max-width:700px){.document-heading{align-items:flex-start;flex-direction:column;padding:10px 0}.document-heading__status{width:100%;justify-content:space-between}.quotation-document{padding:28px 24px}.quotation-document__parties{grid-template-columns:1fr}.quotation-document__header{gap:18px}.quotation-document__terms{gap:18px}}
.email-body-entry{display:flex;align-items:center;gap:10px}.email-body-entry small{color:var(--erp-color-text-regular);font-size:12px}.email-dispatch-history{display:grid;gap:7px;padding:10px 12px}.email-dispatch-history__heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.email-dispatch-history__heading b{font-size:12px}.email-dispatch-history__heading span{color:var(--erp-color-success);font-size:11px}.email-dispatch-history__item{display:grid;grid-template-columns:132px minmax(0,1fr);column-gap:10px;row-gap:3px;color:var(--erp-color-text-regular);font-size:11px;line-height:16px}.email-dispatch-history__item b{grid-row:span 3;color:var(--erp-color-text-primary);font-weight:600}.email-dispatch-history__item span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.send-card :deep(.el-form-item){min-width:0}.send-card :deep(.inquiry-wang-editor__surface){border-radius:6px}.send-card :deep(.inquiry-wang-editor__surface .w-e-text-container),.send-card :deep(.inquiry-wang-editor__surface .w-e-text-container [data-slate-editor]){min-height:126px}.send-card :deep(.inquiry-wang-editor__surface .w-e-bar){min-height:34px}
.address-repair-button{width:100%;margin:0;color:var(--erp-color-warning);border-color:var(--erp-color-warning-border);background:var(--erp-color-subtle)}.accepted-result{display:grid;gap:12px;padding:15px}.accepted-result>div:first-child{display:flex;align-items:center;justify-content:space-between;gap:12px}.accepted-result strong{font-size:13px}.accepted-result p{margin:0;color:var(--erp-color-text-regular);font-size:12px;line-height:20px}.accepted-result .responsibility-note{padding-top:9px;border-top:1px solid var(--erp-color-border);color:var(--erp-color-text-regular)}.accepted-actions{display:grid!important;grid-template-columns:1fr 1.25fr;gap:10px}.accepted-actions :deep(.el-button){width:100%;margin:0}

/* QUO-V2-11 报价预览及 F01—F05 后续状态 */
.quotation-preview-page { max-width: none; min-width: 0; margin: 0; color: var(--erp-color-text-primary); --el-color-primary: var(--erp-color-brand); font-family: var(--erp-font-body); padding: 0; font-size: 13px; }
.preview-header { min-height: 0; align-items: flex-start; margin: 0 0 14px; gap: 14px; flex-wrap: wrap; }
.back-link { color: var(--erp-color-brand); }
.preview-title { display: flex; align-items: center; gap: 28px; margin-top: 0; }
.preview-header h1 { margin: 0; font-family: var(--erp-font-body); font-size: 36px; font-weight: 700; line-height: 44px; }
.preview-title :deep(.el-tag) { min-width: 72px; border: 0; border-radius: 999px; color: var(--erp-tag-neutral-text); background: var(--erp-tag-neutral-background); }
.preview-header p { margin-top: 2px; color: var(--erp-color-text-regular); font-size: 12px; }
.header-actions { gap: 8px; padding-top: 0; flex-wrap: wrap; }
.header-actions :deep(.el-button) { min-width: 142px; height: 32px; margin: 0; border-color: var(--erp-color-border); border-radius: 8px; }
.header-actions :deep(.el-button.is-disabled) { color: var(--erp-color-text-disabled); border-color: var(--erp-color-border); background: var(--erp-color-disabled); }
.black-button { --el-button-bg-color:var(--erp-button-primary-background)!important; --el-button-text-color:var(--erp-button-primary-text)!important; --el-button-border-color:var(--erp-button-primary-border) !important; --el-button-hover-bg-color:var(--erp-button-primary-hover-background)!important; --el-button-hover-border-color:var(--erp-button-primary-border) !important; color:var(--erp-button-primary-text)!important; border-color:var(--erp-button-primary-border) !important; background:var(--erp-button-primary-surface)!important; }
.black-button.is-disabled { --el-button-bg-color:var(--erp-color-disabled)!important; --el-button-text-color:var(--erp-color-text-disabled)!important; --el-button-border-color:var(--erp-color-border)!important; color:var(--erp-color-text-disabled)!important; border-color:var(--erp-color-border)!important; background:var(--erp-color-disabled)!important; }
.preview-layout { grid-template-columns: minmax(0,1fr) minmax(340px,32%); gap: 14px; }
.document-card,.send-card { @include detail.surface; height: auto; max-height: none; min-height: 0; overflow: hidden; }
.document-card :deep(.el-card__header),.send-card :deep(.el-card__header) { min-height: 48px; padding: 0 16px; border-bottom: 0; background: transparent; }
.document-heading { min-height: 48px; flex-wrap: wrap; gap: 8px; }
.document-heading b,.card-heading b { font-family: var(--erp-font-body); font-size: 20px; }
.document-heading__status :deep(.el-tag),.card-heading :deep(.el-tag) { min-width: 100px; border: 0; border-radius: 999px; color: var(--erp-tag-warning-text); background: var(--erp-tag-warning-background); }
.document-card :deep(.el-card__body) { height: auto; padding: 0 16px 16px; overflow: auto; background: transparent; }
.quotation-document { min-width: 780px; min-height: 100%; gap: 18px; padding: 36px 32px 24px; border-color: #ddd6c9; border-radius: 0; background: #fffefb; }
.quotation-document__brand b { color: #c84e28; font-size: 34px; }
.quotation-document__brand span,.quotation-document__meta { color: #6f6a61; }
.quotation-document__divider { background: #ddd6c9; }
.quotation-document__parties { gap: 48px; }
.party-card { min-height: 88px; padding: 0; border: 0; border-radius: 0; background: transparent; }
.party-card small,.party-card span { color: #6f6a61; }
.quotation-document__section-title b { font-size: 15px; }
.quotation-lines-table th,.quotation-container-table th { color: #6f6a61; background: #efe8dd; font-weight: 500; }
.quotation-lines-table td,.quotation-container-table td { border-bottom-color: #e7e0d5; }
.quotation-product-image,.quotation-image-placeholder { width: 58px; height: 58px; border-radius: 0; background: #f4f0e8; }
.quotation-document__terms { border-radius: 0; background: #efe8dd; }
.quotation-document__total { border-bottom: 1px solid #ddd6c9; padding: 4px 0 12px; }
.quotation-document__total strong { font-family: 'Noto Serif SC','STSong',serif; font-size: 22px; }
.send-card :deep(.el-card__header) { min-height: 48px; padding: 0 16px; }
.send-card .card-heading { min-height: 48px; }
.send-card :deep(.el-card__body) { height: auto; gap: 14px; padding: 0 16px 16px; overflow: visible; }
.send-card :deep(.el-form-item__label) { color: var(--erp-color-text-regular); }
.send-card :deep(.el-input__wrapper),.send-card :deep(.el-select__wrapper),.send-card :deep(.el-textarea__inner) { border-radius: 8px; background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-color-border) inset; }
.send-card :deep(.el-alert) { border: 0; border-radius: 4px; background: var(--erp-color-subtle); }
.file-block { border-radius: 8px; background: var(--erp-glass-inner-background); }
.document-actions :deep(.el-button) { height: 44px; border-radius: 5px; }
.full-width { min-height: 44px; }
.send-warning { border-color: var(--erp-color-warning-border); border-radius: 4px; background: var(--erp-color-subtle); }
.send-warning b { color: var(--erp-color-warning); }
.review-attempt-button,.address-repair-button { border-color: var(--erp-color-warning-border); border-radius: 8px; color: var(--erp-color-warning); background: var(--erp-color-subtle); }
.email-dispatch-history {
  @include detail.inset; }
.accepted-result {
  @include detail.inset; }
.black-button.is-guided-disabled {
  --el-button-bg-color: var(--erp-color-disabled) !important;
  --el-button-text-color: var(--erp-color-text-disabled) !important;
  --el-button-border-color: var(--erp-color-border) !important;
  --el-button-hover-bg-color: var(--erp-color-disabled) !important;
  --el-button-hover-text-color: var(--erp-color-text-disabled) !important;
  --el-button-hover-border-color: var(--erp-color-border) !important;
  color: var(--erp-color-text-disabled) !important;
  border-color: var(--erp-color-border) !important;
  background: var(--erp-color-disabled) !important;
  cursor: pointer;
}
.lock-guidance { min-height: 38px; }
.quotation-container-table th:nth-child(1) { width: 22%; }
.quotation-container-table th:nth-child(2) { width: 12%; }
.quotation-container-table th:nth-child(3) { width: 18%; }
.quotation-container-table th:nth-child(4) { width: 18%; }
.quotation-container-table th:nth-child(5) { width: 14%; }
.quotation-container-table th:nth-child(6) { width: 16%; }
.quotation-container-table th:nth-child(n+3),.quotation-container-table td:nth-child(n+3) { text-align: right; }
.quotation-container-table td:nth-child(n+2) { font-size: 10px; white-space: nowrap; }
.quotation-number-cell b { white-space: nowrap; }
.quotation-lines-table th:nth-child(3) { width: 100px; }
.document-heading__status > .quotation-status-tag.is-strong,
.card-heading > .quotation-status-tag.is-strong { color: var(--erp-tag-neutral-text); }

/* MessageBox 会挂载到 body，必须使用全局选择器才能继承报价模块的按钮规范。 */
:global(.quotation-lock-guidance-dialog .el-message-box__btns .el-button) {
  min-width: 88px;
  height: 32px;
  margin-left: 12px;
  border-radius: 5px;
}
:global(.quotation-lock-guidance-dialog__secondary) {
  color: var(--erp-color-text-primary);
  border-color: var(--erp-color-border);
  background: var(--erp-color-surface);
}
:global(.quotation-lock-guidance-dialog__secondary:hover) {
  color: var(--erp-color-brand-hover);
  border-color: var(--erp-color-brand-hover);
  background: var(--erp-color-hover);
}
:global(.quotation-lock-guidance-dialog__primary.el-button--primary) {
  color: var(--erp-button-primary-text);
  border-color: var(--erp-button-primary-border);
  background: var(--erp-button-primary-surface);
}
:global(.quotation-lock-guidance-dialog__primary.el-button--primary:hover) {
  color: var(--erp-button-primary-text);
  border-color: var(--erp-button-primary-border);
  background: var(--erp-button-primary-hover-surface);
}
:global(.quotation-lock-guidance-dialog__secondary:focus-visible),
:global(.quotation-lock-guidance-dialog__primary:focus-visible) {
  outline: 2px solid var(--erp-color-focus);
  outline-offset: 2px;
}

/* 1200—1500px 仍保持桌面双栏，但允许报价纸张真实收缩，避免横向裁切与右栏内部截断。 */
@media (max-width: 1500px) {
  .quotation-preview-page { min-width: 0; }
  .preview-layout { grid-template-columns: minmax(0, 1fr) minmax(360px, 38%); }
  .document-card,.send-card { height: auto; max-height: none; min-height: 0; overflow: visible; }
  .document-card :deep(.el-card__body),.send-card :deep(.el-card__body) { height: auto; overflow: visible; }
  .quotation-document { min-width: 0; min-height: 720px; padding: 28px 24px 22px; }
  .quotation-document__parties { gap: 24px; }
  .quotation-lines-table th:nth-child(1) { width: 62px; }
  .quotation-lines-table th:nth-child(3) { width: 100px; }
  .quotation-lines-table th:nth-child(4) { width: 106px; }
  .quotation-lines-table th:nth-child(5) { width: 112px; }
  .quotation-product-image,.quotation-image-placeholder { width: 48px; height: 48px; }
  .quotation-lines-table th,.quotation-lines-table td,.quotation-container-table th,.quotation-container-table td { padding-right: 8px; padding-left: 8px; }
  .quotation-lines-table td:nth-child(n+3) b { display: inline; white-space: nowrap; }
  .quotation-number-cell small { display: block; margin-top: 2px; font-size: 10px; line-height: 14px; }
  .quotation-container-table th:nth-child(1) { width: 22%; }
  .quotation-container-table th:nth-child(2) { width: 12%; }
  .quotation-container-table th:nth-child(3) { width: 18%; }
  .quotation-container-table th:nth-child(4) { width: 18%; }
  .quotation-container-table th:nth-child(5) { width: 14%; }
  .quotation-container-table th:nth-child(6) { width: 16%; }
  .quotation-container-table th:nth-child(n+3),.quotation-container-table td:nth-child(n+3) { text-align: right; }
}

@media (max-width: 1150px) {
  .preview-header { align-items: flex-start; flex-wrap: wrap; }
  .header-actions { padding-top: 0; }
  .preview-layout { grid-template-columns: 1fr; }
  .quotation-document { min-height: 680px; }
}
.quotation-lines-table tbody td:nth-child(n + 3) { padding-left: 4px !important; padding-right: 4px !important; }
.send-card :deep(.el-alert),
.lock-guidance { min-height: 0; padding: 8px 10px; }
.send-card :deep(.el-alert__icon),
.lock-guidance :deep(.el-alert__icon) { margin-right: 8px; font-size: 16px; }
.send-card :deep(.el-alert__title),
.lock-guidance :deep(.el-alert__title) { font-size: 12px; font-weight: 500; line-height: 18px; }
.send-card :deep(.el-alert__description),
.lock-guidance :deep(.el-alert__description) { margin-top: 1px; font-size: 11px; line-height: 16px; }
.send-card :deep(.workflow-status) { min-height: 56px; height: auto; align-self: start; box-sizing: border-box; }
</style>
