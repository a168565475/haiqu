<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { Box, Check, EditPen, Plus, Upload, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { fetchQuotationInquiryImages, selectQuotationInquiryImage, type QuotationInquiryImage } from '@/api/quotations'
import { AxiosError } from 'axios'

import { fetchCustomerEntity, fetchEntityAddresses } from '@/api/customers'
import { createQuotationLine, deleteQuotationLine, deleteQuotationLineProductImage, fetchQuotation, fetchQuotationVersion, quotationLineProductImageUrl, saveQuotationPriceMatrix, updateQuotation, updateQuotationLine, updateQuotationVersion, uploadQuotationLineProductImage } from '@/api/quotations'
import { fetchAllMasterDataRecords } from '@/api/referenceData'
import type { CustomerAddress, CustomerEntity } from '@/types/customer'
import type { QuotationDetail, QuotationLine, QuotationLinePayload, QuotationPriceBasisPayload, QuotationTemplate, QuotationVersionDetail } from '@/types/quotation'
import type { Currency, Incoterm } from '@/types/referenceData'
import { useAuthStore } from '@/stores/auth'
import BuyerMasterDataDialog from '@/components/business/BuyerMasterDataDialog.vue'
import SellerProfileDialog from '@/components/business/SellerProfileDialog.vue'
import SellerSubjectCard from '@/components/business/SellerSubjectCard.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

interface PriceBasisDraft {
  key: string
  label: string
  incoterm_code: string
  named_place: string
  currency_code: string
  is_default: boolean
  notes: string
  prices: Record<string, string>
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const quotation = ref<QuotationDetail | null>(null)
const version = ref<QuotationVersionDetail | null>(null)
const quotationEtag = ref('')
const versionEtag = ref('')
const loading = ref(true)
const sourceImages=ref<QuotationInquiryImage[]>([])
const sourceImageVisible=ref(false), sourceImagesLoading=ref(false), sourceImageSaving=ref(false), sourceImageError=ref('')
const sourceImageLine=ref<QuotationLine | null>(null)
async function openSourceImages(line: QuotationLine) {
  if(!editable.value || !quotation.value?.source_inquiry)return
  sourceImageLine.value=line;sourceImageVisible.value=true;sourceImagesLoading.value=true;sourceImageError.value='';sourceImages.value=[]
  try{sourceImages.value=await fetchQuotationInquiryImages(quotationId.value)}catch(error){sourceImageError.value=getErrorMessage(error)}finally{sourceImagesLoading.value=false}
}
async function reloadSourceImages() {
  if(!sourceImageLine.value || !version.value || sourceImagesLoading.value || sourceImageSaving.value)return
  if(hasUnsavedChanges.value){
    try{
      await ElMessageBox.confirm('重新加载报价将丢弃本页尚未保存的修改，并读取其他人的最新修改。是否继续？','重新加载报价',{type:'warning',confirmButtonText:'重新加载',cancelButtonText:'保留当前输入'})
    }catch{return}
  }
  sourceImagesLoading.value=true;sourceImageError.value=''
  try{
    await loadEditor()
    if(errorMessage.value){sourceImageError.value=errorMessage.value;return}
    const currentLine=version.value.lines.find(line=>line.id===sourceImageLine.value?.id)
    if(!currentLine || !editable.value){sourceImageError.value='该产品已被移除或报价版本已锁定，请关闭后查看最新报价。';return}
    sourceImageLine.value=currentLine
    sourceImages.value=await fetchQuotationInquiryImages(quotationId.value)
  }catch(error){sourceImageError.value=getErrorMessage(error)}finally{sourceImagesLoading.value=false}
}
async function useSourceImage(imageId:string) {
  if(!sourceImageLine.value||!editable.value||sourceImageSaving.value)return
  sourceImageSaving.value=true;sourceImageError.value=''
  try{
    const result=await selectQuotationInquiryImage(sourceImageLine.value.id,imageId,versionEtag.value)
    versionEtag.value=result.etag
    if(version.value) version.value.lines=version.value.lines.map(line=>line.id===result.data.id?result.data:line)
    sourceImageVisible.value=false
    ElMessage.success('已选用询盘图片，可继续上传新图替换。')
  }catch(error){sourceImageError.value=getErrorMessage(error)}finally{sourceImageSaving.value=false}
}
const saving = ref(false)
const errorMessage = ref('')
const originalPayload = ref('')
const form = reactive({
  subject: '',
  currency_code: '',
  valid_until: '',
  payment_terms: '',
  deposit_percent: '',
  lead_time: '',
  notes: '',
})
const lineDialogVisible = ref(false)
const lineSaving = ref(false)
const editingLine = ref<QuotationLine | null>(null)
const pendingProductImage = ref<UploadFile | null>(null)
const pendingProductImageUrl = ref('')
const priceDialogVisible = ref(false)
const priceSaving = ref(false)
const priceBasisDrafts = ref<PriceBasisDraft[]>([])
const currencies = ref<Currency[]>([])
const incoterms = ref<Incoterm[]>([])
const referenceLoading = ref(false)
const lineForm = reactive<QuotationLinePayload>({ product_description_snapshot: '', specification_snapshot: '', quantity: '1', unit_code: 'PCS', unit_price: '0', discount_rate: '0', notes: '' })
const sellerDialogVisible = ref(false)
const buyerDialogVisible = ref(false)
const buyerDialogTab = ref<'entity' | 'address' | 'contact'>('entity')
const buyerEntity = ref<CustomerEntity | null>(null)
const buyerAddresses = ref<CustomerAddress[]>([])
const selectedBuyerAddressId = ref('')

const quotationId = computed(() => String(route.params.quotationId || ''))
const canChangeVersion = computed(() => authStore.canFor('quotations.change_quotationversion', version.value))
const editable = computed(() => Boolean(quotation.value?.allowed_actions.edit && canChangeVersion.value && version.value?.status === 'DRAFT'))
const isDraftVersion = computed(() => version.value?.status === 'DRAFT')
const canEditSellerTemplate = computed(() => authStore.hasPermission('quotations.change_quotationtemplate'))
const canEditBuyerEntity = computed(() => authStore.canFor('customers.change_customertransactionentity', version.value))
const canEditBuyerAddress = computed(() => authStore.canFor('customers.change_customerentityaddress', version.value))
const canEditBuyerContact = computed(() => authStore.canFor('customers.change_customercontact', version.value))
const canEditBuyerMaster = computed(() => canEditBuyerEntity.value || canEditBuyerAddress.value || canEditBuyerContact.value)
const missingPriceLines = computed(() => version.value?.lines.filter((line) => line.unit_price === null) || [])
const totalAmount = computed(() => !version.value ? '—' : missingPriceLines.value.length ? '待录入单价后计算' : `${version.value.currency_code} ${Number(version.value.total_amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`)
const hasUnsavedChanges = computed(() => originalPayload.value !== JSON.stringify(form))
const defaultPriceBasis = computed(() => version.value?.price_bases.find((item) => item.is_default) || null)
const quotationDate = computed(() => version.value?.created_at ? version.value.created_at.slice(0, 10) : '—')
const defaultTradeTerm = computed(() => defaultPriceBasis.value?.label || String(version.value?.terms_snapshot.incoterm_label || '未设置'))
const nextPackagingLine = computed(() => version.value?.lines[0] || null)
const sellerConfig = computed<Record<string, unknown>>(() => {
  const snapshotConfig = version.value?.template_snapshot?.template_config
  if (!isDraftVersion.value && snapshotConfig && Object.keys(snapshotConfig).length) return snapshotConfig
  return version.value?.template_config || {}
})
const sellerCardSnapshot = computed<Record<string, unknown>>(() => ({ template_config: sellerConfig.value }))
const buyerDisplayName = computed(() => {
  if (isDraftVersion.value && buyerEntity.value?.legal_name) return buyerEntity.value.legal_name
  return version.value?.transaction_entity_snapshot.legal_name || quotation.value?.customer_name || '未关联买方主体'
})
const buyerDisplaySummary = computed(() => {
  if (isDraftVersion.value && buyerEntity.value) return `${buyerEntity.value.entity_type_display} · ${buyerEntity.value.registration_country_code || '地区待维护'}`
  return isDraftVersion.value ? '客户主体资料加载中' : '已锁定版本使用买方快照'
})
const currencyChoices = computed(() => {
  const active = currencies.value.map((item) => ({
    code: item.code,
    label: `${item.code} · ${item.chinese_name || item.english_name}`,
    disabled: false,
  }))
  const currentCode = form.currency_code.trim().toUpperCase()
  if (currentCode && !active.some((item) => item.code === currentCode)) {
    active.push({ code: currentCode, label: `${currentCode}（历史停用值）`, disabled: true })
  }
  return active
})
const validationItems = computed(() => [
  { ok: Boolean(quotation.value?.customer_name && buyerDisplayName.value), text: isDraftVersion.value ? '基本信息与买方主体完整' : '基本信息与主体快照完整' },
  { ok: Boolean(buyerAddresses.value.length), text: '客户交易主体地址已维护' },
  { ok: Boolean(version.value?.lines.length && !missingPriceLines.value.length), text: '行数量、单位与单价有效' },
  { ok: Boolean(form.payment_terms && form.lead_time), text: '付款条款与交期已填写' },
  { ok: Boolean(version.value?.lines.length && version.value.lines.every((line) => line.packaging)), text: '产品包装档完整' },
])

function snapshotText(key: string): string {
  const value = version.value?.terms_snapshot?.[key]
  return value === undefined || value === null ? '' : String(value)
}

function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络异常，当前输入已保留，请检查连接后重试。'
  const payload = error.response.data as { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有编辑报价的权限。'
  if (error.response.status === 412) return '报价已被其他人更新，请重新加载后再保存。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载后重试。'
  if (error.response.status >= 500) return '报价服务暂时异常，请稍后重试。'
  const fields = payload.error?.field_errors
  return fields ? Object.values(fields).flat().join('；') : payload.error?.message || payload.detail || '保存失败，请检查输入。'
}

function incotermChoices(currentCode: string) {
  const active = incoterms.value.map((item) => ({
    code: item.code,
    label: `${item.code} · ${item.chinese_name || item.english_name}`,
    disabled: false,
  }))
  const normalized = currentCode.trim().toUpperCase()
  if (normalized && !active.some((item) => item.code === normalized)) {
    active.push({ code: normalized, label: `${normalized}（历史停用值）`, disabled: true })
  }
  return active
}

async function loadReferenceOptions() {
  referenceLoading.value = true
  try {
    const [currencyRows, incotermRows] = await Promise.all([
      fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' }),
      fetchAllMasterDataRecords<Incoterm>('incoterms', { status: 'ACTIVE' }),
    ])
    currencies.value = currencyRows
    incoterms.value = incotermRows
  } catch (error) {
    ElMessage.warning(`币种或贸易术语加载失败：${getErrorMessage(error)}`)
  } finally {
    referenceLoading.value = false
  }
}

function applyDetail(value: QuotationDetail, etag: string) {
  quotation.value = value
  quotationEtag.value = etag
}

function applyVersion(value: QuotationVersionDetail, etag: string) {
  version.value = value
  versionEtag.value = etag
  Object.assign(form, {
    subject: quotation.value?.subject || '',
    currency_code: value.currency_code || '',
    valid_until: value.valid_until || '',
    payment_terms: snapshotText('payment_terms'),
    deposit_percent: snapshotText('deposit_percent'),
    lead_time: snapshotText('lead_time'),
    notes: value.notes || '',
  })
  originalPayload.value = JSON.stringify(form)
}

async function loadEditor() {
  if (!quotationId.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const detail = await fetchQuotation(quotationId.value)
    applyDetail(detail.data, detail.etag)
    const current = detail.data.current_version
    if (!current) {
      errorMessage.value = '该报价尚未创建版本，不能进入编辑器。'
      return
    }
    const currentVersion = await fetchQuotationVersion(current.id)
    applyVersion(currentVersion.data, currentVersion.etag)
    await refreshBuyerEntitySummary()
    if (route.query.section === 'buyer-address') {
      openBuyerDialog('address')
    } else if (route.query.section === 'buyer-contact') {
      openBuyerDialog('contact')
    } else if (route.query.section === 'price-basis') {
      openPriceMatrix()
    }
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    loading.value = false
  }
}

async function saveDraft() {
  if (!quotation.value || !version.value || !editable.value) return
  if (!form.subject.trim()) {
    ElMessage.warning('请填写报价主题。')
    return
  }
  const depositPercent = form.deposit_percent.trim()
  if (depositPercent && (Number.isNaN(Number(depositPercent)) || Number(depositPercent) < 0 || Number(depositPercent) > 100)) {
    ElMessage.warning('订金比例必须是 0 到 100 之间的数字。')
    return
  }
  saving.value = true
  try {
    const quoteResult = await updateQuotation(quotation.value.id, { subject: form.subject.trim() }, quotationEtag.value)
    applyDetail(quoteResult.data, quoteResult.etag)
    const versionResult = await updateQuotationVersion(version.value.id, {
      currency_code: form.currency_code.trim().toUpperCase(),
      valid_until: form.valid_until || null,
      terms_snapshot: {
        payment_terms: form.payment_terms.trim(),
        deposit_percent: depositPercent,
        lead_time: form.lead_time.trim(),
        incoterm_code: defaultPriceBasis.value?.incoterm_code || '',
        incoterm_label: defaultPriceBasis.value?.label || '',
      },
      notes: form.notes.trim(),
    }, versionEtag.value)
    applyVersion(versionResult.data, versionResult.etag)
    ElMessage.success('草稿已保存，并已写入审计记录。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function refreshVersion() {
  if (!version.value) return
  const result = await fetchQuotationVersion(version.value.id)
  applyVersion(result.data, result.etag)
}

function resetLineForm(line?: QuotationLine) {
  clearPendingProductImage()
  editingLine.value = line || null
  Object.assign(lineForm, line ? {
    product_description_snapshot: line.product_description_snapshot,
    specification_snapshot: line.specification_snapshot,
    quantity: line.quantity,
    unit_code: line.unit_code,
    unit_price: line.unit_price || '0',
    discount_rate: line.discount_rate,
    notes: line.notes,
  } : { product_description_snapshot: '', specification_snapshot: '', quantity: '1', unit_code: 'PCS', unit_price: '0', discount_rate: '0', notes: '' })
  lineDialogVisible.value = true
}

function clearPendingProductImage() {
  if (pendingProductImageUrl.value) URL.revokeObjectURL(pendingProductImageUrl.value)
  pendingProductImage.value = null
  pendingProductImageUrl.value = ''
}

function validateProductImage(file: File): boolean {
  const validTypes = new Set(['image/jpeg', 'image/png', 'image/webp'])
  if (!validTypes.has(file.type)) {
    ElMessage.warning('产品主图仅支持 JPG、PNG 或 WebP 格式。')
    return false
  }
  if (file.size <= 0 || file.size > 5 * 1024 * 1024) {
    ElMessage.warning('产品主图必须大于 0 字节且不超过 5MB。')
    return false
  }
  return true
}

function handlePendingProductImageChange(file: UploadFile) {
  if (!file.raw || !validateProductImage(file.raw)) return
  clearPendingProductImage()
  pendingProductImage.value = file
  pendingProductImageUrl.value = URL.createObjectURL(file.raw)
}

async function openPackaging(line: QuotationLine) {
  await router.push({ name: 'quotation-packaging', params: { quotationId: quotationId.value, lineId: line.id } })
}

async function goToNextPackaging() {
  if (!nextPackagingLine.value) {
    ElMessage.warning('请先添加至少一个报价产品，再进入包装配置。')
    return
  }
  await openPackaging(nextPackagingLine.value)
}

async function openSourceInquiry() {
  if (!quotation.value?.source_inquiry) {
    ElMessage.info('当前报价未关联来源询盘。')
    return
  }
  await router.push({ name: 'inquiry-detail', params: { inquiryId: quotation.value.source_inquiry } })
}

function packagingSummary(line: QuotationLine): string {
  if (!line.packaging) return '待配置'
  const item = line.packaging
  return `${item.length_cm} × ${item.width_cm} × ${item.height_cm} cm · ${item.carton_count} 箱`
}

async function saveLine() {
  if (!version.value || !editable.value) return
  if (!lineForm.product_description_snapshot.trim()) {
    ElMessage.warning('请填写产品或描述。')
    return
  }
  lineSaving.value = true
  try {
    const payload = {
      ...lineForm,
      product_description_snapshot: lineForm.product_description_snapshot.trim(),
      specification_snapshot: lineForm.specification_snapshot?.trim(),
      unit_code: lineForm.unit_code.trim().toUpperCase(),
      notes: lineForm.notes?.trim(),
    }
    const lineResult = editingLine.value
      ? await updateQuotationLine(editingLine.value.id, payload, versionEtag.value)
      : await createQuotationLine(version.value.id, payload, versionEtag.value)
    versionEtag.value = lineResult.etag
    const imageFile = pendingProductImage.value?.raw
    if (imageFile) {
      try {
        const imageResult = await uploadQuotationLineProductImage(lineResult.data.id, imageFile, versionEtag.value)
        versionEtag.value = imageResult.etag
      } catch (imageError) {
        await refreshVersion()
        lineDialogVisible.value = false
        clearPendingProductImage()
        ElMessage.warning(`产品已保存，但主图上传失败：${getErrorMessage(imageError)}。可在产品列表中重试。`)
        return
      }
    }
    await refreshVersion()
    lineDialogVisible.value = false
    clearPendingProductImage()
    ElMessage.success(editingLine.value ? '产品明细已更新。' : '产品明细已新增。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    lineSaving.value = false
  }
}

async function removeLine(line: QuotationLine) {
  if (!version.value || !editable.value) return
  try {
    await ElMessageBox.confirm(`确定删除“${line.product_description_snapshot}”吗？该操作会写入审计记录。`, '删除产品明细', { type: 'warning' })
    versionEtag.value = await deleteQuotationLine(line.id, versionEtag.value)
    await refreshVersion()
    ElMessage.success('产品明细已删除。')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  }
}

async function removeEditingLine() {
  if (!editingLine.value) return
  await removeLine(editingLine.value)
  lineDialogVisible.value = false
}

async function uploadProductImage(line: QuotationLine, file: File) {
  if (!version.value || !editable.value) return
  if (!validateProductImage(file)) return
  try {
    const result = await uploadQuotationLineProductImage(line.id, file, versionEtag.value)
    versionEtag.value = result.etag
    await refreshVersion()
    ElMessage.success('产品主图已上传并通过安全扫描。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function handleProductImageChange(line: QuotationLine, file: UploadFile) {
  if (file.raw) void uploadProductImage(line, file.raw)
}

async function removeProductImage(line: QuotationLine) {
  if (!version.value || !editable.value) return
  try {
    versionEtag.value = await deleteQuotationLineProductImage(line.id, versionEtag.value)
    await refreshVersion()
    ElMessage.success('产品主图已移除。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

function openSellerDialog() {
  if (!version.value?.quotation_template) {
    ElMessage.warning('当前报价尚未关联固定报价模板。')
    return
  }
  if (!canEditSellerTemplate.value) {
    ElMessage.warning('当前账号没有编辑固定报价模板的权限。')
    return
  }
  sellerDialogVisible.value = true
}

async function handleSellerSaved(_template: QuotationTemplate) {
  await refreshVersion()
}

async function refreshBuyerEntitySummary() {
  if (!quotation.value || !isDraftVersion.value) return
  try {
    const result = await fetchCustomerEntity(quotation.value.transaction_entity)
    buyerEntity.value = result.data
  } catch {
    buyerEntity.value = null
  }
  try {
    buyerAddresses.value = await fetchEntityAddresses(quotation.value.transaction_entity)
    if (!buyerAddresses.value.some((item) => item.id === selectedBuyerAddressId.value)) {
      selectedBuyerAddressId.value = buyerAddresses.value.length === 1 ? buyerAddresses.value[0]!.id : ''
    }
  } catch {
    buyerAddresses.value = []
    selectedBuyerAddressId.value = ''
  }
}

function openBuyerDialog(tab: 'entity' | 'address' | 'contact' = 'entity') {
  if (!canEditBuyerMaster.value) {
    ElMessage.warning('当前账号没有编辑客户主体、地址或联系人的权限。')
    return
  }
  buyerDialogTab.value = tab
  buyerDialogVisible.value = true
}

function handleBuyerAddressSelected(address: CustomerAddress | null) {
  selectedBuyerAddressId.value = address?.id || ''
}

async function handleBuyerAddressSaved(address: CustomerAddress) {
  selectedBuyerAddressId.value = address.id
  await refreshBuyerEntitySummary()
}

async function previewQuotation() {
  await router.push({
    name: 'quotation-preview',
    params: { quotationId: quotationId.value },
    query: selectedBuyerAddressId.value ? { addressId: selectedBuyerAddressId.value } : undefined,
  })
}

function priceForBasis(line: QuotationLine, basisId: string): string {
  return line.basis_prices?.find((item) => item.price_basis_id === basisId)?.unit_price || '—'
}

function addPriceBasis() {
  if (!version.value) return
  priceBasisDrafts.value.push({
    key: `new-${Date.now()}-${priceBasisDrafts.value.length}`,
    label: '',
    incoterm_code: '',
    named_place: '',
    currency_code: version.value.currency_code,
    is_default: priceBasisDrafts.value.length === 0,
    notes: '',
    prices: Object.fromEntries(version.value.lines.map((line) => [line.id, line.unit_price || '0'])),
  })
}

function openPriceMatrix() {
  if (!version.value) return
  priceBasisDrafts.value = version.value.price_bases.map((basis) => ({
    key: basis.id,
    label: basis.label,
    incoterm_code: basis.incoterm_code,
    named_place: basis.named_place,
    currency_code: basis.currency_code,
    is_default: basis.is_default,
    notes: basis.notes,
    prices: Object.fromEntries(version.value!.lines.map((line) => [line.id, priceForBasis(line, basis.id) === '—' ? '0' : priceForBasis(line, basis.id)])),
  }))
  if (!priceBasisDrafts.value.length) addPriceBasis()
  priceDialogVisible.value = true
}

function setDefaultBasis(target: PriceBasisDraft) {
  priceBasisDrafts.value.forEach((item) => { item.is_default = item.key === target.key })
}

function removePriceBasis(target: PriceBasisDraft) {
  priceBasisDrafts.value = priceBasisDrafts.value.filter((item) => item.key !== target.key)
  if (target.is_default && priceBasisDrafts.value[0]) priceBasisDrafts.value[0].is_default = true
}

async function savePriceMatrix() {
  if (!version.value || !editable.value) return
  if (!priceBasisDrafts.value.length) return ElMessage.warning('至少保留一个价格口径。')
  if (priceBasisDrafts.value.some((item) => !item.label.trim() || !item.incoterm_code.trim() || !item.named_place.trim())) return ElMessage.warning('请完整填写价格口径名称、贸易术语和地点。')
  if (priceBasisDrafts.value.filter((item) => item.is_default).length !== 1) return ElMessage.warning('必须且只能设置一个默认价格口径。')
  if (priceBasisDrafts.value.some((item) => version.value!.lines.some((line) => item.prices[line.id] === '' || Number(item.prices[line.id]) < 0))) return ElMessage.warning('请为每个价格口径的全部产品填写有效单价。')
  const payload: QuotationPriceBasisPayload[] = priceBasisDrafts.value.map((item) => ({
    label: item.label.trim(),
    incoterm_code: item.incoterm_code.trim().toUpperCase(),
    named_place: item.named_place.trim(),
    currency_code: item.currency_code.trim().toUpperCase(),
    is_default: item.is_default,
    notes: item.notes.trim(),
    line_prices: version.value!.lines.map((line) => ({ quotation_line_id: line.id, unit_price: item.prices[line.id] })),
  }))
  priceSaving.value = true
  try {
    const result = await saveQuotationPriceMatrix(version.value.id, payload, versionEtag.value)
    applyVersion(result.data, result.etag)
    priceDialogVisible.value = false
    ElMessage.success('多价格口径已保存，默认口径已同步报价总额。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    priceSaving.value = false
  }
}

async function confirmLeaveEditorIfDirty(destination: string): Promise<boolean> {
  if (!hasUnsavedChanges.value) return true
  try {
    await ElMessageBox.confirm(`当前编辑内容尚未保存，${destination}后这些输入将丢失。是否继续？`, '未保存修改', {
      type: 'warning',
      confirmButtonText: '放弃修改并继续',
      cancelButtonText: '继续编辑',
    })
    return true
  } catch {
    return false
  }
}

function warnBeforeBrowserLeave(event: BeforeUnloadEvent) {
  if (!hasUnsavedChanges.value) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(async () => confirmLeaveEditorIfDirty('离开编辑页'))

onMounted(() => {
  window.addEventListener('beforeunload', warnBeforeBrowserLeave)
  void Promise.all([loadEditor(), loadReferenceOptions()])
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnBeforeBrowserLeave)
})
</script>

<template>
  <section v-loading="loading" class="quotation-editor-page" aria-label="报价编辑器">
    <template v-if="quotation && version">
      <header class="editor-header">
        <div>
          <div class="editor-title"><h1>编辑报价</h1><strong>{{ quotation.quotation_number }}</strong><ElTag size="small">{{ version.status_display }}</ElTag></div>
          <p>{{ version.lines.length ? `共 ${version.lines.length} 项产品，产品明细已保存。` : '新草稿，尚未添加产品。' }}</p>
        </div>
        <div class="editor-actions"><ElButton @click="previewQuotation">预览报价</ElButton><ElButton class="black-button" :loading="saving" :disabled="!editable" @click="saveDraft">保存草稿</ElButton></div>
      </header>

      <section class="editor-steps" aria-label="报价编辑步骤">
        <div class="step is-done"><b><ElIcon><Check /></ElIcon></b><span>基本信息</span></div>
        <div class="step is-active"><b>2</b><span>产品明细</span></div>
        <div class="step"><b>3</b><span>条款与费用</span></div>
        <div class="step"><b>4</b><span>预览并发送</span></div>
      </section>

      <div class="editor-layout">
        <main class="editor-main">
          <ElCard class="editor-card" shadow="never">
            <template #header><div class="card-heading"><b>基本信息</b><span>带 * 字段用于生成正式报价文件</span></div></template>
            <ElForm label-position="top" class="basic-grid">
              <ElFormItem label="报价主题"><ElInput v-model="form.subject" :disabled="!editable" maxlength="250" /></ElFormItem>
          <ElFormItem label="币种 *"><ElSelect v-model="form.currency_code" filterable :loading="referenceLoading" :disabled="!editable"><ElOption v-for="item in currencyChoices" :key="item.code" :label="item.label" :value="item.code" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="报价日期 *"><ElInput :model-value="quotationDate" disabled /></ElFormItem>
              <ElFormItem label="有效期至 *"><ElDatePicker v-model="form.valid_until" type="date" value-format="YYYY-MM-DD" :disabled="!editable" placeholder="选择日期" /></ElFormItem>
              <ElFormItem label="贸易条款 *" class="trade-term-field"><ElInput :model-value="defaultTradeTerm" :suffix-icon="EditPen" readonly title="点击管理多价格口径" @click="editable && openPriceMatrix()" /></ElFormItem>
            </ElForm>
          </ElCard>

          <ElCard class="editor-card" shadow="never">
            <template #header><div class="card-heading"><b>买卖方资料</b></div></template>
            <div class="snapshot-panels">
              <SellerSubjectCard :snapshot="sellerCardSnapshot" :editable="canEditSellerTemplate" title="卖方主体" @edit="openSellerDialog" />
              <section class="snapshot-panel" :class="{ 'is-editable': canEditBuyerMaster }" @click="canEditBuyerMaster && openBuyerDialog()">
                <div><span>{{ isDraftVersion ? '买方主数据' : '买方快照' }}</span><button v-if="canEditBuyerMaster" type="button" @click.stop="openBuyerDialog()">编辑客户资料</button></div>
                <strong>{{ buyerDisplayName }}</strong><small>{{ buyerDisplaySummary }}</small>
              </section>
            </div>
          </ElCard>

          <ElCard class="editor-card product-card" shadow="never">
            <template #header><div class="card-heading"><b>产品明细</b><small>{{ version.lines.length }} 项</small><button class="price-basis-link" type="button" :disabled="!editable" @click="openPriceMatrix">管理价格方案</button><ElButton v-if="editable" size="small" :icon="Plus" @click="resetLineForm()">添加产品</ElButton></div></template>
            <ElTable :data="version.lines" empty-text="暂无报价产品，请先添加产品。">
              <ElTableColumn label="产品 / 图片" min-width="190"><template #default="{ row }"><div class="product-with-image"><ElUpload v-if="editable" class="product-thumb-upload" :auto-upload="false" :show-file-list="false" accept="image/png,image/jpeg,image/webp" @change="handleProductImageChange(row, $event)"><div class="product-thumb"><ElImage v-if="row.product_image" :src="quotationLineProductImageUrl(row.id)" :preview-src-list="[quotationLineProductImageUrl(row.id)]" preview-teleported fit="cover" @click.stop/><ElIcon v-else><Box /></ElIcon><span class="product-thumb-action">{{ row.product_image ? '替换' : '上传' }}</span></div></ElUpload><div v-else class="product-thumb"><ElImage v-if="row.product_image" :src="quotationLineProductImageUrl(row.id)" :preview-src-list="[quotationLineProductImageUrl(row.id)]" preview-teleported fit="cover"/><ElIcon v-else><Box /></ElIcon></div><div class="product-cell"><b>{{ row.product_description_snapshot }}</b><small>{{ row.source_inquiry_item ? '来源询盘产品' : `行 ${row.line_number}` }}</small></div></div></template></ElTableColumn>
              <ElTableColumn label="规格" min-width="150"><template #default="{ row }">{{ row.specification_snapshot || '未维护' }}</template></ElTableColumn>
              <ElTableColumn prop="quantity" label="数量" width="82" />
              <ElTableColumn prop="unit_code" label="单位" width="66" />
              <ElTableColumn label="单价" width="112"><template #default="{ row }">{{ version.currency_code }} {{ formatMoney(row.unit_price) }}</template></ElTableColumn>
              <ElTableColumn label="金额" width="120"><template #default="{ row }"><b>{{ version.currency_code }} {{ formatMoney(row.line_total) }}</b></template></ElTableColumn>
              <ElTableColumn label="包装摘要" min-width="150"><template #default="{ row }"><span>{{ packagingSummary(row) }}</span><small v-if="row.packaging" class="packaging-ready">包装已配置</small></template></ElTableColumn>
              <ElTableColumn label="操作" width="240" fixed="right"><template #default="{ row }"><div class="line-action-buttons"><ElButton size="small" :disabled="!editable" @click="openPackaging(row)">配置</ElButton><ElButton v-if="editable && quotation?.source_inquiry" size="small" @click="openSourceImages(row)">选择询盘图片</ElButton><ElButton v-if="row.product_image && editable" size="small" type="danger" plain @click="removeProductImage(row)">移除图片</ElButton></div></template></ElTableColumn>
            </ElTable>
            <div v-if="missingPriceLines.length" class="table-footnote warning-note"><ElIcon><Warning /></ElIcon> 有 {{ missingPriceLines.length }} 行尚未录入单价，报价总额暂不完整。</div>
            <div v-else class="table-footnote">行金额按数量 × 默认口径单价计算 · 商品小计 {{ version.currency_code }} {{ formatMoney(version.subtotal_amount) }}</div>
          </ElCard>

          <ElCard class="editor-card terms-card" shadow="never">
            <template #header><div class="card-heading"><b>条款与备注</b></div></template>
            <ElForm label-position="top" class="terms-grid">
              <ElFormItem label="付款条款 *"><ElInput v-model="form.payment_terms" :disabled="!editable" maxlength="200" placeholder="例如：30% 订金 / 70% 余款" /></ElFormItem>
              <ElFormItem label="订金比例 (%)"><ElInput v-model="form.deposit_percent" :disabled="!editable" inputmode="decimal" maxlength="6" placeholder="例如：30" /></ElFormItem>
              <ElFormItem label="交期 *"><ElInput v-model="form.lead_time" :disabled="!editable" maxlength="200" placeholder="例如：收到订金后 35 天" /></ElFormItem>
              <ElFormItem label="固定报价模板"><ElInput model-value="haiqu 品牌中英文固定模板 V1.0" disabled /></ElFormItem>
            </ElForm>
            <ElInput v-model="form.notes" type="textarea" :rows="2" :disabled="!editable" maxlength="2000" show-word-limit placeholder="备注：正式发送前校验包装、装柜数量档、付款条款和有效期；已发送版本不可覆盖。" />
          </ElCard>
        </main>

        <aside class="editor-summary">
          <h2>报价汇总</h2>
          <ElCard class="summary-card summary-version" shadow="never"><strong>V{{ version.version_number }} · {{ version.status_display }}</strong></ElCard>
          <ElCard class="summary-card" shadow="never"><h3>金额计算</h3><p><span>商品小计</span><b>{{ version.currency_code }} {{ formatMoney(version.subtotal_amount) }}</b></p><p><span>订金（{{ version.payment_breakdown?.deposit_percent || '未设置' }}<template v-if="version.payment_breakdown">%</template>）</span><b class="deposit">{{ version.payment_breakdown ? `${version.currency_code} ${formatMoney(version.payment_breakdown.deposit_amount)}` : '—' }}</b></p><p><span>余款（{{ version.payment_breakdown?.balance_percent || '未设置' }}<template v-if="version.payment_breakdown">%</template>）</span><b class="balance">{{ version.payment_breakdown ? `${version.currency_code} ${formatMoney(version.payment_breakdown.balance_amount)}` : '—' }}</b></p><div class="total"><span>报价总额</span><strong>{{ totalAmount }}</strong></div><small>金额使用服务端计算；人工调整需填写原因</small></ElCard>
          <ElCard class="summary-card" shadow="never"><h3>发送前校验 <ElTag size="small" type="warning">{{ validationItems.filter((item) => !item.ok).length }} 项待完善</ElTag></h3><p v-for="item in validationItems" :key="item.text" class="validation" :class="{ warning: !item.ok }"><ElIcon><Check v-if="item.ok"/><EditPen v-else/></ElIcon>{{ item.text }}</p></ElCard>
          <ElCard class="summary-card source-card" shadow="never"><h3>来源与附件</h3><button type="button" @click="openSourceInquiry">询盘：{{ quotation.source_inquiry_number || '未关联' }}</button><p><span>客户</span><b>{{ quotation.customer_name }}</b></p><small>正式报价附件将在预览与发送步骤生成</small></ElCard>
          <div class="summary-actions"><ElButton class="black-button" :disabled="!nextPackagingLine" @click="goToNextPackaging">下一步：包装配置</ElButton></div>
          <small class="next-help">为已添加的产品配置包装信息。</small>
        </aside>
      </div>
      <AppWindowDialog v-model="sourceImageVisible" title="选择询盘产品图片" :width="720" :height="620" :close-on-click-modal="!sourceImageSaving" :close-on-press-escape="!sourceImageSaving" :show-close="!sourceImageSaving">
        <p>为“{{ sourceImageLine?.product_description_snapshot }}”选择图片。点击缩略图可放大查看，再点击“选用此图”。</p>
        <ElAlert v-if="sourceImageError" :title="sourceImageError" type="error" :closable="false" />
        <div v-loading="sourceImagesLoading || sourceImageSaving" class="source-images-grid">
          <article v-for="(image, index) in sourceImages" :key="image.id">
            <ElImage :src="image.url" :alt="`询盘图片 ${index + 1}`" fit="contain" :preview-src-list="sourceImages.map(item => item.url)" :initial-index="index" preview-teleported><template #error><span>图片加载失败</span></template></ElImage>
            <div><span>图片 {{ index + 1 }}</span><ElButton :disabled="sourceImagesLoading || sourceImageSaving" @click="useSourceImage(image.id)">选用此图</ElButton></div>
          </article>
          <ElEmpty v-if="!sourceImagesLoading && !sourceImages.length" description="暂无可用的询盘产品图片，可直接上传新图。"/>
        </div>
        <template #footer><ElButton v-if="sourceImageError && sourceImageLine" :disabled="sourceImagesLoading || sourceImageSaving" @click="reloadSourceImages">重新加载</ElButton><ElButton :disabled="sourceImageSaving" @click="sourceImageVisible=false">关闭</ElButton></template>
      </AppWindowDialog>
      <AppWindowDialog v-model="lineDialogVisible" class="quotation-product-dialog" :title="editingLine ? '编辑产品' : '添加产品'" :width="820" :height="720" :close-on-click-modal="false">
        <p class="product-dialog-lead">录入产品信息，保存后添加至当前报价。</p>
        <ElForm label-position="top" class="line-form">
          <ElFormItem v-if="editingLine" label="产品主图">
            <div class="dialog-image-tools"><ElImage v-if="editingLine.product_image" :src="quotationLineProductImageUrl(editingLine.id)" fit="cover" class="dialog-product-image"/><span v-else class="dialog-image-empty">暂无图片</span><ElUpload v-if="editable" :auto-upload="false" :show-file-list="false" accept="image/png,image/jpeg,image/webp" @change="handleProductImageChange(editingLine!, $event)"><ElButton :icon="Upload">上传图片</ElButton></ElUpload><ElButton v-if="editable && editingLine.product_image" text type="danger" @click="removeProductImage(editingLine)">移除</ElButton></div>
          </ElFormItem>
          <ElFormItem v-else label="产品主图">
            <div class="dialog-image-tools"><ElImage v-if="pendingProductImageUrl" :src="pendingProductImageUrl" fit="cover" class="dialog-product-image"/><span v-else class="dialog-image-empty">可选主图</span><ElUpload :auto-upload="false" :show-file-list="false" accept="image/png,image/jpeg,image/webp" @change="handlePendingProductImageChange"><ElButton :icon="Upload">选择图片</ElButton></ElUpload><ElButton v-if="pendingProductImage" text type="danger" @click="clearPendingProductImage">移除</ElButton></div>
            <p class="image-field-help">仅支持 JPG、PNG、WebP，单张不超过 5MB。保存产品后自动上传。</p>
          </ElFormItem>
          <ElFormItem label="产品 / 描述 *"><ElInput v-model="lineForm.product_description_snapshot" maxlength="500" /></ElFormItem>
          <ElFormItem label="规格"><ElInput v-model="lineForm.specification_snapshot" maxlength="2000" placeholder="请输入规格、材质或尺寸" /></ElFormItem>
          <div class="line-form__numbers"><ElFormItem label="数量 *"><ElInput v-model="lineForm.quantity" inputmode="decimal" /></ElFormItem><ElFormItem label="单位 *"><ElInput v-model="lineForm.unit_code" maxlength="30" /></ElFormItem><ElFormItem label="单价 *"><ElInput v-model="lineForm.unit_price" inputmode="decimal" /></ElFormItem><ElFormItem label="折扣率"><ElInput v-model="lineForm.discount_rate" inputmode="decimal" /></ElFormItem></div>
          <ElFormItem label="备注"><ElInput v-model="lineForm.notes" type="textarea" :rows="2" maxlength="2000" show-word-limit /></ElFormItem>
        </ElForm>
        <template #footer><ElButton v-if="editingLine" type="danger" text @click="removeEditingLine">删除</ElButton><ElButton @click="lineDialogVisible = false">取消</ElButton><ElButton class="black-button" :loading="lineSaving" @click="saveLine">保存产品</ElButton></template>
      </AppWindowDialog>
      <SellerProfileDialog v-model="sellerDialogVisible" :template-id="version.quotation_template" context-name="报价" @saved="handleSellerSaved" />
      <BuyerMasterDataDialog
        v-model="buyerDialogVisible"
        :customer-id="quotation.customer_account"
        :entity-id="quotation.transaction_entity"
        :selected-address-id="selectedBuyerAddressId"
        :initial-tab="buyerDialogTab"
        context-name="报价"
        :can-edit-entity="canEditBuyerEntity"
        :can-edit-address="canEditBuyerAddress"
        :can-edit-contact="canEditBuyerContact"
        @address-selected="handleBuyerAddressSelected"
        @address-saved="handleBuyerAddressSaved"
        @entity-updated="buyerEntity = $event"
      />
      <AppWindowDialog v-model="priceDialogVisible" class="quotation-price-dialog" title="价格方案管理" :width="1000" :height="780" :close-on-click-modal="false">
        <p class="price-dialog-subtitle">{{ quotation.quotation_number }} / V{{ version.version_number }} · 币种 {{ version.currency_code }}</p>
        <ElAlert title="同一报价版本可同时维护多个价格口径；默认口径用于报价汇总，发送和客户接受时仍会单独选择并留痕。" type="info" :closable="false" show-icon />
        <div class="basis-section-heading"><b>方案设置</b><span>{{ priceBasisDrafts.length }} 个方案</span><ElButton :icon="Plus" @click="addPriceBasis">新增方案</ElButton></div>
        <div class="basis-editor-list">
          <section v-for="(basis, basisIndex) in priceBasisDrafts" :key="basis.key" class="basis-editor-item">
            <header><b>方案 {{ basisIndex + 1 }}</b><ElTag type="warning" round>{{ basis.key.startsWith('new-') ? '未保存' : '已保存' }}</ElTag><span></span><ElRadio :model-value="basis.is_default" :label="true" @change="setDefaultBasis(basis)">默认方案</ElRadio><ElButton type="danger" text :disabled="priceBasisDrafts.length === 1" @click="removePriceBasis(basis)">删除</ElButton></header>
            <div class="basis-form-grid"><label><span>方案名称 *</span><ElInput v-model="basis.label" placeholder="如：FOB 宁波" maxlength="120" /></label><label><span>贸易术语 *</span><ElSelect v-model="basis.incoterm_code" filterable :loading="referenceLoading" placeholder="请选择贸易术语"><ElOption v-for="item in incotermChoices(basis.incoterm_code)" :key="item.code" :label="item.label" :value="item.code" :disabled="item.disabled" /></ElSelect></label><label><span>地点 / 港口 *</span><ElInput v-model="basis.named_place" placeholder="请输入地点或港口" maxlength="180" /></label><label class="currency-field"><span>币种</span><ElInput v-model="basis.currency_code" disabled maxlength="3" /></label></div>
          </section>
        </div>
        <div class="product-price-heading"><b>产品报价</b><span>共 {{ version.lines.length }} 项产品</span></div>
        <ElTable :data="version.lines" class="price-matrix-table" max-height="380">
          <ElTableColumn label="产品 / 规格" min-width="210"><template #default="{ row }"><div class="product-cell"><b>{{ row.product_description_snapshot }}</b><small>{{ row.specification_snapshot || '未维护规格' }}</small></div></template></ElTableColumn>
          <ElTableColumn prop="quantity" label="数量" width="90" />
          <ElTableColumn v-for="basis in priceBasisDrafts" :key="basis.key" :label="basis.label || '未命名口径'" min-width="170"><template #default="{ row }"><ElInput v-model="basis.prices[row.id]" inputmode="decimal"><template #prepend>{{ basis.currency_code }}</template></ElInput></template></ElTableColumn>
        </ElTable>
        <template #footer><ElButton @click="priceDialogVisible = false">取消</ElButton><ElButton class="black-button" :loading="priceSaving" @click="savePriceMatrix">保存价格方案</ElButton></template>
      </AppWindowDialog>
    </template>
    <ElResult v-else-if="errorMessage" icon="error" title="报价编辑器加载失败" :sub-title="errorMessage"><template #extra><ElButton class="black-button" @click="loadEditor">重新加载</ElButton><ElButton @click="router.push('/quotations')">返回列表</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss">
.source-images-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; min-height:180px; max-height:60vh; overflow-y:auto; margin-top:16px; article { padding:10px; background:#fff; border:1px solid #dedbd4; border-radius:6px; } .el-image { width:100%; height:170px; cursor:zoom-in; } article > div:last-child { display:flex; align-items:center; justify-content:space-between; margin-top:10px; } .el-empty { grid-column:1/-1; } }
.quotation-editor-page { min-width:0; color:#24272d; --el-color-primary:#0877e1; }
.editor-header { display:flex; min-height:82px; align-items:center; justify-content:space-between; gap:24px; }
.back-link { display:flex; align-items:center; gap:4px; padding:0; border:0; color:#0877e1; background:transparent; font-size:12px; cursor:pointer; }
.editor-title { display:flex; align-items:center; gap:20px; margin-top:6px; }
.editor-title h1 { margin:0; font-size:24px; line-height:32px; }
.editor-header p { margin:1px 0 0; color:#8a8f99; font-size:11px; }
.editor-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
.editor-actions :deep(.el-button) { height:32px; }
.black-button { color:#fff!important; border-color:#18181b!important; background:#18181b!important; }
.editor-steps { display:grid; grid-template-columns:repeat(4,1fr); padding:0 28px; margin-bottom:12px; border:1px solid #e1e4e8; border-radius:8px; background:#fff; }
.step { position:relative; display:flex; align-items:center; justify-content:center; gap:8px; height:64px; color:#9aa0aa; font-size:12px; }
.step:not(:last-child)::after { position:absolute; top:23px; left:calc(50% + 22px); width:calc(100% - 44px); height:1px; background:#d7dbe1; content:""; }
.step b { z-index:1; display:grid; width:26px; height:26px; place-items:center; border:1px solid #d4d8de; border-radius:50%; background:#fff; font-size:12px; }
.step span { position:absolute; top:39px; }
.step.is-active,.step.is-done { color:#0877e1; }
.step.is-active b { border-color:#0877e1; color:#0877e1; }
.step.is-done b { border-color:#0877e1; color:#fff; background:#0877e1; }
.step.is-done::after { background:#0877e1; }
.editor-layout { display:grid; grid-template-columns:minmax(0,2.18fr) minmax(340px,1fr); gap:16px; }
.editor-main { display:grid; gap:12px; min-width:0; }
.editor-card,.summary-card { border:1px solid #dfe2e7; border-radius:8px; box-shadow:none; }
.editor-card :deep(.el-card__header) { min-height:48px; padding:0 18px; }
.editor-card :deep(.el-card__body) { padding:14px 18px; }
.card-heading { display:flex; align-items:center; gap:12px; min-height:47px; }
.card-heading b { flex:none; font-size:15px; }
.card-heading span { flex:1; color:#737983; font-size:11px; }
.card-heading :deep(.el-button) { height:28px; margin-left:0; }
.basic-grid { display:grid; grid-template-columns:1.15fr .72fr .86fr .86fr 1.2fr; gap:12px; }
.basic-grid :deep(.el-form-item),.terms-grid :deep(.el-form-item) { margin-bottom:0; }
.basic-grid :deep(.el-form-item__label),.terms-grid :deep(.el-form-item__label) { padding-bottom:4px; color:#646a73; font-size:11px; }
.basic-grid :deep(.el-input),.basic-grid :deep(.el-date-editor),.terms-grid :deep(.el-input) { width:100%; }
.field-help { margin:12px 0 0; color:#9aa0aa; font-size:10px; }
.snapshot-panels { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.snapshot-panel { display:grid; gap:6px; min-width:0; padding:12px 14px; border-radius:6px; background:#f7f8fa; }
.snapshot-panel.is-editable { cursor:pointer; }
.snapshot-panel.is-editable:hover { background:#f0f7ff; box-shadow:inset 0 0 0 1px #afd8ff; }
.snapshot-panel div { display:flex; justify-content:space-between; color:#747b85; font-size:11px; }
.snapshot-panel button,.summary-card button { padding:0; border:0; color:#0877e1; background:transparent; font-size:11px; text-align:left; cursor:pointer; }
.snapshot-panel strong,.snapshot-panel small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.snapshot-panel strong { font-size:13px; }
.snapshot-panel small { color:#7c828c; font-size:10px; }
.product-with-image { display:flex; align-items:center; gap:10px; }
.product-thumb { display:grid; flex:none; width:38px; height:38px; place-items:center; overflow:hidden; border-radius:5px; color:#5f6670; background:#f3f4f6; font-size:20px; }
.product-thumb :deep(.el-image) { width:100%; height:100%; }
.product-thumb-upload { display:block; flex:none; }
.product-thumb-upload :deep(.el-upload) { display:block; position:relative; border-radius:5px; }
.product-thumb-action { position:absolute; right:0; bottom:0; left:0; padding:2px 0; color:#fff; background:rgb(0 0 0 / 56%); font-size:9px; line-height:1; text-align:center; }
.product-cell { display:grid; gap:3px; min-width:0; }
.product-cell b,.product-cell small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-cell b { font-weight:600; }
.product-cell small { color:#8a8f99; font-size:10px; }
.line-action-buttons { display:flex; gap:6px; white-space:nowrap; }
.line-action-buttons :deep(.el-button) { margin:0; }
.editor-card :deep(.el-table__header th) { height:34px; color:#444950; background:#f5f6f8; font-size:11px; }
.editor-card :deep(.el-table__body td) { height:54px; font-size:11px; }
.packaging-ready { display:block; margin-top:2px; color:#14933d; font-size:10px; }
.table-footnote { display:flex; align-items:center; gap:5px; min-height:24px; margin-top:6px; padding:0 8px; border:1px solid #cce4ff; border-radius:4px; color:#0877e1; background:#eef7ff; font-size:10px; }
.table-footnote.warning-note { border-color:#fde7c3; color:#c36b0c; background:#fff8ed; }
.terms-grid { display:grid; grid-template-columns:1.2fr .62fr 1fr 1.35fr; gap:12px; margin-bottom:10px; }
.editor-summary { display:grid; align-content:start; gap:12px; }
.editor-summary h2 { margin:0; font-size:17px; line-height:30px; }
.summary-card :deep(.el-card__body) { display:grid; gap:11px; padding:14px; }
.summary-version { position:relative; background:#eef7ff; border-color:#cfe5fb; }
.summary-version small { color:#646a73; }
.summary-version strong { font-size:15px; }
.summary-version :deep(.el-tag) { position:absolute; top:10px; right:10px; }
.summary-card h3 { display:flex; justify-content:space-between; align-items:center; margin:0; font-size:13px; }
.summary-card p { display:flex; justify-content:space-between; gap:8px; margin:0; color:#707680; font-size:11px; }
.summary-card p b { color:#1f2329; font-weight:500; text-align:right; }
.summary-card p b.deposit { color:#e76f00; }
.summary-card p b.balance { color:#0877e1; }
.summary-card .total { display:flex; justify-content:space-between; padding-top:11px; border-top:1px solid #e1e4e8; }
.summary-card .total strong { font-size:16px; }
.summary-card > :deep(.el-card__body) > small { color:#8a8f99; font-size:10px; }
.summary-card .validation { justify-content:flex-start; align-items:flex-start; color:#14933d; line-height:1.45; }
.summary-card .validation.warning { color:#d97706; }
.source-card p b { max-width:62%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.summary-actions { display:grid; grid-template-columns:1fr 1.48fr; gap:12px; }
.summary-actions :deep(.el-button) { width:100%; height:34px; margin:0; }
.next-help { color:#8a8f99; font-size:10px; text-align:center; }
.line-form__numbers { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.line-form :deep(.el-form-item) { margin-bottom:14px; }
.dialog-image-tools { display:flex; align-items:center; gap:10px; }
.dialog-product-image,.dialog-image-empty { width:72px; height:52px; border-radius:5px; }
.dialog-image-empty { display:grid; place-items:center; color:#8a8f99; background:#f3f4f6; font-size:11px; }
.image-field-help { margin:6px 0 0; color:#8a8f99; font-size:11px; line-height:1.4; }
.seller-profile-dialog__intro { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:20px; padding:13px 14px; border:1px solid #d7e9fb; border-radius:8px; background:#f4f9ff; }
.seller-profile-dialog__intro div { display:grid; gap:5px; }
.seller-profile-dialog__intro b { font-size:14px; }
.seller-profile-dialog__intro span { color:#68707c; font-size:12px; line-height:1.5; }
.seller-profile-form,.buyer-master-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 16px; }
.seller-profile-form :deep(.el-form-item),.buyer-master-form :deep(.el-form-item) { margin-bottom:14px; }
.seller-profile-form__full,.buyer-master-form__full { grid-column:1 / -1; }
.buyer-master-tabs { margin-top:16px; }
.buyer-address-toolbar { display:flex; min-height:34px; align-items:center; justify-content:space-between; gap:12px; margin:6px 0 14px; color:#646a73; font-size:12px; }
.buyer-address-toolbar .buyer-record-selector { flex:1; margin:0; }
.buyer-address-toolbar :deep(.el-button) { flex:none; margin:0; }
.buyer-record-selector { display:grid; grid-template-columns:86px minmax(0,1fr); align-items:center; gap:10px; margin:6px 0 16px; color:#5f6670; font-size:12px; }
.buyer-contact-methods { display:grid; gap:4px; margin:-3px 0 14px; padding:9px 11px; border-radius:6px; color:#646a73; background:#f7f8fa; font-size:11px; }
.buyer-contact-methods small { color:#858b94; line-height:1.5; }
.buyer-tab-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:2px; padding-top:14px; border-top:1px solid #ebeef2; }
.buyer-tab-actions span { color:#8a8f99; font-size:12px; }
.basis-editor-list { display:grid; gap:10px; margin:16px 0 10px; }
.basis-editor-item { display:grid; grid-template-columns:1.4fr .8fr 1.2fr 90px 110px 58px; gap:8px; align-items:center; padding:10px; border:1px solid #e4e4e7; border-radius:8px; }
.price-matrix-table { margin-top:16px; }
@media (max-width:1380px) { .basic-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }.trade-term-field { grid-column:span 2; }.terms-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:1100px) { .editor-layout { grid-template-columns:1fr; }.editor-summary { grid-template-columns:repeat(2,minmax(0,1fr)); }.editor-summary h2,.summary-actions,.next-help { grid-column:span 2; } }
@media (max-width:900px) { .editor-header { align-items:flex-start; flex-direction:column; }.editor-actions { justify-content:flex-start; }.editor-main :deep(.el-table) { min-width:860px; }.editor-main :deep(.el-table__inner-wrapper) { overflow-x:auto; }.basis-editor-item{grid-template-columns:1fr 1fr} }
@media (max-width:600px) { .editor-steps { grid-template-columns:repeat(2,1fr); }.step:nth-child(2)::after { display:none; }.basic-grid,.terms-grid,.snapshot-panels,.editor-summary,.seller-profile-form,.buyer-master-form { grid-template-columns:1fr; }.trade-term-field,.editor-summary h2,.summary-actions,.next-help { grid-column:auto; }.editor-title h1 { font-size:20px; }.editor-actions { width:100%; }.editor-actions :deep(.el-button) { flex:1; margin:0; }.summary-actions { grid-template-columns:1fr; }.seller-profile-dialog__intro { flex-direction:column; }.buyer-record-selector { grid-template-columns:1fr; gap:6px; } }

/* QUO-V2-03 / QUO-V2-05 报价编辑 */
.quotation-editor-page { min-width: 0; color: #1f1d18; --el-color-primary: #c84e28; font-family: 'Noto Sans SC','Microsoft YaHei',sans-serif; }
.editor-header { min-height: 102px; align-items: flex-start; }
.back-link { color: #c84e28; }
.editor-title { gap: 28px; margin-top: 14px; }
.editor-title h1 { font-family: 'Noto Serif SC','STSong',serif; font-size: 36px; font-weight: 600; line-height: 46px; }
.editor-title strong { font-family: 'Noto Serif SC','STSong',serif; font-size: 30px; font-weight: 500; line-height: 46px; }
.editor-title :deep(.el-tag) { min-width: 72px; border: 0; border-radius: 999px; color: #5e5d59; background: #f0eee6; }
.editor-header p { margin-top: 2px; color: #968f84; font-size: 12px; }
.editor-actions { gap: 20px; padding-top: 20px; }
.editor-actions :deep(.el-button) { min-width: 132px; height: 44px; margin: 0; border-color: #ddd6c9; border-radius: 5px; background: #fcfbf7; font-size: 15px; }
.editor-actions .black-button { width: 140px; }
.black-button { color: #fff!important; border-color: #c84e28!important; background: #c84e28!important; }
.black-button:hover { border-color: #b94423!important; background: #b94423!important; }
.black-button.is-disabled,.black-button:disabled { color: #aaa49b!important; border-color: #ece6db!important; background: #eee8dd!important; }
.editor-steps { display: none; }
.editor-layout { grid-template-columns: minmax(0,1fr) 450px; gap: 16px; align-items: start; }
.editor-main { gap: 16px; }
.editor-card,.summary-card { border-color: #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.editor-card :deep(.el-card__header) { min-height: 42px; padding: 0 20px; border-bottom: 0; }
.editor-card :deep(.el-card__body) { padding: 0 20px 20px; }
.card-heading { min-height: 42px; gap: 16px; }
.card-heading b { font-size: 18px; }
.card-heading > span { display: none; }
.card-heading small { color: #6f6a61; font-size: 13px; }
.card-heading :deep(.el-button) { height: 40px; padding: 0 22px; border-color: #c84e28; border-radius: 4px; color: #c84e28; background: #fcfbf7; }
.price-basis-link { margin-left: auto; padding: 0; border: 0; color: #c84e28; background: transparent; cursor: pointer; font-size: 13px; }
.price-basis-link:disabled { color: #aaa49b; cursor: not-allowed; }
.basic-grid { grid-template-columns: 1.55fr .6fr .84fr .92fr .92fr; gap: 20px; }
.basic-grid :deep(.el-form-item__label),.terms-grid :deep(.el-form-item__label) { padding-bottom: 7px; color: #6f6a61; font-size: 13px; }
.basic-grid :deep(.el-input__wrapper),.basic-grid :deep(.el-select__wrapper),.terms-grid :deep(.el-input__wrapper) { min-height: 44px; border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.basic-grid :deep(.is-disabled .el-input__wrapper),.terms-grid :deep(.is-disabled .el-input__wrapper) { background: #eee9df; }
.snapshot-panels { gap: 0; }
.snapshot-panels > * { min-height: 100px; padding: 4px 20px; border: 0; border-radius: 0; background: transparent; }
.snapshot-panels > * + * { border-left: 1px solid #ddd6c9; }
.snapshot-panels :deep(.seller-card) { min-height: 100px; padding: 4px 20px 4px 0; border: 0; border-radius: 0; background: transparent; }
.snapshot-panels :deep(.seller-card footer) { display: none; }
.snapshot-panel div { color: #1f1d18; font-size: 13px; }
.snapshot-panel button,.summary-card button { color: #c84e28; }
.snapshot-panel strong { font-size: 16px; }
.snapshot-panel small { color: #6f6a61; font-size: 13px; }
.editor-card :deep(.el-table) { --el-table-border-color: #e5ded2; --el-table-header-bg-color: #efe8dd; color: #1f1d18; background: #fcfbf7; }
.editor-card :deep(.el-table__header th) { height: 42px; color: #6f6a61; background: #efe8dd; font-size: 12px; font-weight: 500; }
.editor-card :deep(.el-table__body td) { height: 72px; font-size: 12px; background: #fcfbf7; }
.product-thumb { width: 44px; height: 64px; border: 1px solid #ddd6c9; border-radius: 4px; background: #f4f0e8; }
.product-cell b { font-size: 13px; }
.product-cell small { color: #6f6a61; font-size: 11px; }
.table-footnote { min-height: 40px; margin: 0; padding: 0 16px; border: 0; border-radius: 0; color: #6f6a61; background: #f7f3eb; }
.terms-grid { grid-template-columns: 1.2fr .55fr 1fr 1.1fr; gap: 16px; }
.terms-card :deep(.el-textarea__inner) { border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.editor-summary { position: sticky; top: 0; display: block; min-height: 864px; padding: 24px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.editor-summary h2 { margin: 0 0 12px; font-family: 'Noto Serif SC','STSong',serif; font-size: 22px; line-height: 32px; }
.summary-card { border: 0; border-bottom: 1px solid #ddd6c9; border-radius: 0; }
.summary-card :deep(.el-card__body) { gap: 14px; padding: 16px 0; }
.summary-version { position: absolute; top: 24px; right: 24px; border: 0; }
.summary-version :deep(.el-card__body) { padding: 0; }
.summary-version strong { font-size: 14px; }
.summary-card h3 { font-size: 17px; }
.summary-card p { font-size: 13px; }
.summary-card .total { margin-top: 10px; padding-top: 16px; }
.summary-card .total strong { color: #c84e28; font-size: 30px; }
.summary-card .validation.warning { color: #b8781e; }
.summary-actions { display: block; margin-top: 24px; }
.summary-actions :deep(.el-button) { height: 50px; font-size: 16px; }
.next-help { display: block; margin-top: 12px; color: #968f84; font-size: 12px; }
:global(.quotation-price-dialog) { border-radius: 6px; background: #fcfbf7; }
:global(.quotation-price-dialog .el-dialog__header) { margin: 0; padding: 30px 32px 0; }
:global(.quotation-price-dialog .el-dialog__title) { font-family: 'Noto Serif SC','STSong',serif; font-size: 28px; font-weight: 600; }
:global(.quotation-price-dialog .el-dialog__body) { padding: 18px 32px 24px; }
:global(.quotation-price-dialog .el-dialog__footer) { padding: 16px 32px; border-top: 1px solid #ddd6c9; }
.price-dialog-subtitle { margin: -8px 0 10px; color: #6f6a61; font-size: 13px; }
.quotation-price-dialog :deep(.el-alert) { border: 0; color: #5d5140; background: #faecd6; }
.basis-section-heading,.product-price-heading { display: flex; align-items: center; gap: 18px; min-height: 56px; }
.basis-section-heading b,.product-price-heading b { font-family: 'Noto Serif SC','STSong',serif; font-size: 18px; }
.basis-section-heading span,.product-price-heading span { color: #968f84; font-size: 13px; }
.basis-section-heading :deep(.el-button) { width: 166px; height: 42px; margin-left: auto; border-color: #c84e28; color: #c84e28; background: #fcfbf7; }
.basis-editor-list { margin: 0; }
.basis-editor-item { display: block; padding: 18px 20px; border-color: #ddd6c9; border-radius: 4px; background: #fcfbf7; }
.basis-editor-item header { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.basis-editor-item header b { font-size: 17px; }.basis-editor-item header > span { flex: 1; }
.basis-editor-item header :deep(.el-tag) { border: 0; color: #b8781e; background: #faeedb; }
.basis-form-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.basis-form-grid label { display: grid; gap: 7px; color: #6f6a61; font-size: 13px; }
.basis-form-grid .currency-field { grid-column: 1; max-width: 288px; }
.basis-form-grid :deep(.el-input__wrapper),.basis-form-grid :deep(.el-select__wrapper) { min-height: 44px; border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.basis-form-grid :deep(.is-disabled .el-input__wrapper) { background: #eee8dd; }
.price-matrix-table :deep(.el-table__header th) { background: #efe8dd; }
:global(.quotation-product-dialog) { border-radius: 7px; background: #fcfbf7; }
:global(.quotation-product-dialog .el-dialog__header) { margin: 0; padding: 34px 44px 0; }
:global(.quotation-product-dialog .el-dialog__title) { font-family: 'Noto Serif SC','STSong',serif; font-size: 30px; font-weight: 600; }
:global(.quotation-product-dialog .el-dialog__body) { padding: 12px 44px 20px; }
:global(.quotation-product-dialog .el-dialog__footer) { margin: 0 44px; padding: 20px 0 30px; border-top: 1px solid #ddd6c9; }
:global(.quotation-product-dialog .el-dialog__footer .el-button) { min-width: 108px; height: 44px; border-radius: 4px; }
.product-dialog-lead { margin: 0 0 28px; color: #6f6a61; font-size: 14px; }
.quotation-product-dialog .line-form :deep(.el-form-item) { margin-bottom: 20px; }
.quotation-product-dialog .line-form :deep(.el-form-item__label) { padding-bottom: 8px; color: #1f1d18; font-size: 14px; }
.quotation-product-dialog .line-form :deep(.el-input__wrapper),.quotation-product-dialog .line-form :deep(.el-textarea__inner) { min-height: 44px; border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.quotation-product-dialog .dialog-product-image,.quotation-product-dialog .dialog-image-empty { width: 104px; height: 104px; border: 1px dashed #ddd6c9; border-radius: 4px; background: #fffefb; }
.quotation-product-dialog .dialog-image-tools { gap: 28px; }
.quotation-product-dialog .line-form__numbers { gap: 24px; }
</style>
