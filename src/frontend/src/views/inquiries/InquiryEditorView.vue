<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { createInquiry, fetchInquiry, fetchInquiryOptions, inquiryProductImageUrl, removeInquiryProductImage, saveInquiryDraft, submitInquiry, uploadInquiryAttachment, uploadInquiryProductImage } from '@/api/inquiries'
import { fetchAllProductionDataRecords } from '@/api/productionData'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import ProductImage from '@/components/products/ProductImage.vue'
import { fetchCustomerContacts, fetchContact, fetchContactOptions } from '@/api/contacts'
import { fetchCustomers, fetchCustomer } from '@/api/customers'
import { fetchAllMasterDataRecords } from '@/api/referenceData'
import { useAuthStore } from '@/stores/auth'
import type { ContactListItem, ContactOption } from '@/types/contact'
import type { CustomerListItem } from '@/types/customer'
import type { InquiryDetail, InquiryDraftInput, InquiryItem, InquiryOptions, InquiryFile } from '@/types/inquiry'
import type { Currency, Incoterm } from '@/types/referenceData'
import type { ProductCategory, ProductColor, ProductionUnit } from '@/types/productionData'
import { blankProduct, decimalUnits, newInquiryKey, productAmount, quantitySummary, validateAttachment, validateProducts } from './inquiryEditorState'
import { formatEstimatedAmount } from './inquiryListState'
import checkIcon from '@/assets/inquiries/create-check.svg'

const route = useRoute(), router = useRouter(), auth = useAuthStore()
const savedId = ref(String(route.params.inquiryId || ''))
const loading = ref(true), ready = ref(false), busy = ref(false), action = ref('')
const validationError = ref(false)
const errorMessage = ref(''), customerError = ref(''), contactError = ref('')
const customerLoading = ref(false), contactLoading = ref(false)
const customers = ref<CustomerListItem[]>([]), contacts = ref<ContactListItem[]>([])
const selectedCustomer = ref<CustomerListItem | null>(null)
const options = ref<InquiryOptions | null>(null)
const languages = ref<ContactOption[]>([])
const currencies = ref<Currency[]>([]), incoterms = ref<Incoterm[]>([])
const files = ref<InquiryFile[]>([])
const productCategories = ref<ProductCategory[]>([]), productUnits = ref<ProductionUnit[]>([]), productColors = ref<ProductColor[]>([])
const catalogError = ref(''), productDialogVisible = ref(false), productDialogItem = ref<InquiryItem | null>(null)
const productDialogIndex = ref(-1)
const pendingProductImages = reactive<Record<number, { file: File | null; remove: boolean; preview: string }>>({})
const pendingFiles = ref<Array<{ id: string; file: File; error: string }>>([])
const fileInput = ref<HTMLInputElement | null>(null)
const inquiryNumber = ref(''), draftVersion = ref(0), inquiryStatus = ref('DRAFT')
const ownerName = ref(auth.user?.employee?.display_name || '')
const etag = ref('')
const form = reactive({ customer_account_id: '', customer_contact_id: '', inquiry_source: '', subject: '', description: '', received_at: new Date().toISOString(), requested_due_at: null as string | null, customer_language_code: '', trade_term_code: '', trade_term_place: '', delivery_requirement: '', estimated_amount_min: null as string | null, estimated_amount_max: null as string | null, estimated_currency_code: '', items: [] as InquiryItem[] })
const canSave = computed(() => ready.value && inquiryStatus.value === 'DRAFT' && !!auth.user?.employee && auth.hasPermission(savedId.value ? 'inquiries.change_inquiry' : 'inquiries.add_inquiry'))
const canSubmit = computed(() => canSave.value && auth.hasPermission('inquiries.change_inquiry'))
const canUpload = computed(() => auth.hasPermission('inquiries.add_inquiryfilelink') && auth.hasPermission('inquiries.change_inquiry'))
const canUploadProductImage = computed(() => auth.hasPermission('inquiries.change_inquiryitem') && auth.hasPermission('inquiries.change_inquiry'))
const disabled = computed(() => busy.value || !canSave.value)
const uncertainSave = ref(false)
const formLocked = computed(() => disabled.value || uncertainSave.value)
const activeItems = computed(() => form.items.filter(item => !blankProduct(item)))
const estimatedAmount = computed(() => formatEstimatedAmount({ product_amount: productAmount(activeItems.value) }))
const quantities = computed(() => quantitySummary(activeItems.value))
const selectedContact = computed(() => contacts.value.find(item => item.id === form.customer_contact_id))
const contactEmail = computed(() => selectedContact.value?.methods?.find(method => method.is_primary && method.method_type === 'EMAIL')?.masked_value || selectedContact.value?.methods?.find(method => method.method_type === 'EMAIL')?.masked_value || '—')
const receivedDate = computed({ get: () => form.received_at ? new Date(form.received_at) : null, set: (value: Date | null) => { form.received_at = value && Number.isFinite(value.getTime()) ? value.toISOString() : '' } })
const checks = computed(() => [
  { label: '已选择客户', ok: !!form.customer_account_id },
  { label: `已填写 ${activeItems.value.length} 条产品需求`, ok: activeItems.value.length > 0 && !validateProducts(activeItems.value) },
  { label: '已选择有效联系人', ok: !!selectedContact.value && selectedContact.value.status === 'ACTIVE' && !contactError.value },
  { label: '已选择询盘来源', ok: !!form.inquiry_source },
])
let stopped = false, customerRequest = 0, contactRequest = 0, navigating = false
let originalDescription = '', originalPlainDescription = ''
let nextLineNumber = 1
const initialSnapshot = ref('')
let idempotencyKey = newInquiryKey(), attemptPayload: InquiryDraftInput | null = null
const snapshot = () => JSON.stringify(form)
const dirty = computed(() => ready.value && (snapshot() !== initialSnapshot.value || pendingFiles.value.length > 0 || Object.keys(pendingProductImages).length > 0))
function emptyItem(): InquiryItem { return { line_number: nextLineNumber++, product_id: null, product_category_id: null, product_unit_id: null, product_color_id: null, product_description: '', specification: '', color: '', material: '', quantity: '1', unit_code: 'PCS', target_unit_price: null, target_currency_code: '', expected_date: null, product_match_status: 'PENDING', notes: '' } }
function errorText(error: any): string {
  const status = error?.response?.status
  if (status === 412 || status === 428) return '记录版本已变化，请先保留当前填写内容，再重新打开草稿。'
  if (status === 403) return '当前账号没有此操作权限。'
  if (status === 401) return '登录状态已失效，请重新登录。'
  return error?.response?.data?.error?.message || (error instanceof Error ? error.message : '') || '请求失败，请稍后重试。'
}
function trimSentenceEnd(value: string) { return value.replace(/[。！？.!?]+$/g, '') }
function plainDescription(value: string) {
  const body = new DOMParser().parseFromString(value, 'text/html').body
  body.querySelectorAll('br').forEach(node => node.replaceWith('\n'))
  body.querySelectorAll('p,div,li').forEach(node => node.append('\n'))
  return body.textContent?.trim() || ''
}
function populate(detail: InquiryDetail) {
  savedId.value = detail.id; inquiryNumber.value = detail.inquiry_number; draftVersion.value = detail.draft_version; inquiryStatus.value = detail.status
  ownerName.value = detail.owner?.display_name || '未分配'
  originalDescription = detail.description || ''; originalPlainDescription = plainDescription(originalDescription)
  Object.assign(form, { customer_account_id: detail.customer.id, customer_contact_id: detail.customer_contact || '', inquiry_source: detail.inquiry_source, subject: detail.subject, description: originalPlainDescription, received_at: detail.received_at, requested_due_at: detail.requested_due_at, customer_language_code: detail.customer_language_code, trade_term_code: detail.trade_term_code, trade_term_place: detail.trade_term_place, delivery_requirement: detail.delivery_requirement, estimated_amount_min: detail.estimated_amount_min, estimated_amount_max: detail.estimated_amount_max, estimated_currency_code: detail.estimated_currency_code, items: detail.items.map(item => ({ ...item })) })
  nextLineNumber = Math.max(nextLineNumber, ...detail.items.map(item => (item.line_number || 0) + 1))
  files.value = detail.files
}
async function searchCustomers(query = '') {
  const request = ++customerRequest; customerLoading.value = true; customerError.value = ''
  try {
    const result = await fetchCustomers({ q: query.trim(), page_size: 100, ordering: 'account_name' })
    if (stopped || request !== customerRequest) return
    customers.value = result.data
    if (selectedCustomer.value && !customers.value.some(item => item.id === selectedCustomer.value?.id)) customers.value.unshift(selectedCustomer.value)
  } catch (error) { if (request === customerRequest) customerError.value = errorText(error) }
  finally { if (request === customerRequest) customerLoading.value = false }
}
async function loadContacts(customerId: string) {
  const request = ++contactRequest; contacts.value = []; contactError.value = ''; contactLoading.value = !!customerId
  if (!customerId) return
  try {
    let page = 1, totalPages = 1
    const rows: ContactListItem[] = []
    do {
      const result = await fetchCustomerContacts(customerId, { status: 'ACTIVE', page_size: 100, page })
      if (stopped || request !== contactRequest) return
      rows.push(...result.data); totalPages = result.meta.total_pages; page++
    } while (page <= totalPages)
    contacts.value = rows
    if (form.customer_contact_id && !rows.some(item => item.id === form.customer_contact_id)) {
      const result = await fetchContact(form.customer_contact_id)
      if (stopped || request !== contactRequest) return
      contacts.value.push(result.data)
    }
  } catch (error) { if (request === contactRequest) contactError.value = errorText(error) }
  finally { if (request === contactRequest) contactLoading.value = false }
}
async function changeCustomer(id: string) {
  if (savedId.value) return
  form.customer_contact_id = ''; selectedCustomer.value = customers.value.find(item => item.id === id) || null
  await loadContacts(id)
}
async function load() {
  loading.value = true; ready.value = false; errorMessage.value = ''
  try {
    const [contactOptions, inquiryOptions, currencyRows, tradeRows] = await Promise.all([fetchContactOptions(), fetchInquiryOptions(), fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' }), fetchAllMasterDataRecords<Incoterm>('incoterms', { status: 'ACTIVE' })])
    if (stopped) return
    languages.value = contactOptions.language_options; options.value = inquiryOptions; currencies.value = currencyRows; incoterms.value = tradeRows
    if (savedId.value) { const result = await fetchInquiry(savedId.value); if (stopped) return; etag.value = result.etag || ''; populate(result.data) }
    else { form.items = []; form.customer_account_id = typeof route.query.customer_id === 'string' ? route.query.customer_id : '' }
    const catalog = await Promise.allSettled([fetchAllProductionDataRecords<ProductCategory>('product-categories'), fetchAllProductionDataRecords<ProductionUnit>('production-units'), fetchAllProductionDataRecords<ProductColor>('product-colors')])
    if (stopped) return
    productCategories.value = catalog[0].status === 'fulfilled' ? catalog[0].value.filter(row => row.item_type === 'FINISHED') : []
    productUnits.value = catalog[1].status === 'fulfilled' ? catalog[1].value : []
    productColors.value = catalog[2].status === 'fulfilled' ? catalog[2].value : []
    catalogError.value = catalog.some(result => result.status === 'rejected') ? '产品维护选项加载失败或缺少权限，请重新加载页面。已填写内容可保留。' : ''
    if (form.customer_account_id) {
      const result = await fetchCustomer(form.customer_account_id)
      if (stopped) return
      selectedCustomer.value = result.data
      await loadContacts(form.customer_account_id)
    }
    await searchCustomers()
    if (stopped) return
    initialSnapshot.value = snapshot(); ready.value = true
  } catch (error) { if (!stopped) errorMessage.value = errorText(error) }
  finally { if (!stopped) loading.value = false }
}
function addItem() { if (!formLocked.value && form.items.length < 200) { productDialogIndex.value = -1; productDialogItem.value = emptyItem(); productDialogVisible.value = true } }
function editItem(index: number) { if (!formLocked.value && form.items[index]) { productDialogIndex.value = index; productDialogItem.value = { ...form.items[index]! }; productDialogVisible.value = true } }
function clearPendingImage(line: number) { const pending = pendingProductImages[line]; if (pending?.preview) URL.revokeObjectURL(pending.preview); delete pendingProductImages[line] }
function confirmProduct(value: { item: InquiryItem; imageChanged: boolean; imageFile: File | null; removeImage: boolean }) {
  if (formLocked.value) return
  if (productDialogIndex.value < 0) form.items.push(value.item)
  else form.items[productDialogIndex.value] = value.item
  if (value.imageChanged) {
    const line = value.item.line_number!
    clearPendingImage(line)
    pendingProductImages[line] = { file: value.imageFile, remove: value.removeImage, preview: value.imageFile ? URL.createObjectURL(value.imageFile) : '' }
  }
}
function productImageSource(item: InquiryItem) {
  const pending = pendingProductImages[item.line_number!]
  if (pending) return pending.preview
  return item.id && item.product_image_id ? `${inquiryProductImageUrl(item.id)}?v=${item.product_image_id}` : ''
}
function removeItem(index: number) { if (!formLocked.value && index >= 0 && index < form.items.length) { clearPendingImage(form.items[index]!.line_number!); form.items.splice(index, 1) } }
async function saveProductImages() {
  for (const key of Object.keys(pendingProductImages)) {
    const line = Number(key), pending = pendingProductImages[line]!
    const index = form.items.findIndex(item => item.line_number === line)
    const item = form.items[index]
    if (!item?.id) throw new Error('产品明细尚未保存，图片已保留，请重试保存。')
    try {
      const result = pending.file ? await uploadInquiryProductImage(item.id, pending.file, etag.value) : pending.remove && item.product_image_id ? await removeInquiryProductImage(item.id, etag.value) : null
      if (result) { form.items[index] = result.data; etag.value = result.etag || '' }
      clearPendingImage(line)
      initialSnapshot.value = snapshot()
    } catch (error) { throw new Error(`草稿已保存，第 ${index + 1} 条产品图片保存失败：${trimSentenceEnd(errorText(error))}。当前图片已保留，可重试保存。`) }
  }
}
function pickFiles(event: Event) {
  const input = event.target as HTMLInputElement
  if (!formLocked.value && canUpload.value) for (const file of Array.from(input.files || [])) {
    const error = validateAttachment(file)
    if (error) { ElMessage.warning(`${file.name}：${error}`); continue }
    if (files.value.length + pendingFiles.value.length >= 100) { ElMessage.warning('单张询盘最多上传 100 个附件。'); break }
    pendingFiles.value.push({ id: newInquiryKey(), file, error: '' })
  }
  input.value = ''
}
function buildPayload(): InquiryDraftInput {
  const description = form.description === originalPlainDescription ? originalDescription : form.description.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
  return { customer_contact_id: form.customer_contact_id || null, inquiry_source: form.inquiry_source, subject: form.subject.trim() || `${activeItems.value[0]?.product_description.trim() || selectedCustomer.value?.account_name || '客户'}询盘`.slice(0, 250), description, received_at: form.received_at, requested_due_at: form.requested_due_at, customer_language_code: form.customer_language_code.trim(), trade_term_code: form.trade_term_code, trade_term_place: form.trade_term_place.trim(), delivery_requirement: form.delivery_requirement.trim(), estimated_amount_min: form.estimated_amount_min === '' ? null : form.estimated_amount_min, estimated_amount_max: form.estimated_amount_max === '' ? null : form.estimated_amount_max, estimated_currency_code: form.estimated_currency_code, items: activeItems.value.map(item => ({ ...item, target_unit_price: item.target_unit_price === '' ? null : item.target_unit_price })), idempotency_key: idempotencyKey }
}
function validate(submit: boolean) {
  if (!form.customer_account_id) return '请选择已有客户。'
  if (!form.received_at || !Number.isFinite(Date.parse(form.received_at))) return '请选择有效接收时间。'
  if (contactLoading.value || contactError.value) return '联系人仍在加载或加载失败，请重试后保存。'
  if (submit && !checks.value.every(check => check.ok)) return '请完成右侧提交检查；也可以先保存草稿。'
  const productError = validateProducts(activeItems.value)
  if (productError) return productError
  if (form.customer_language_code && !/^[A-Z0-9][A-Z0-9_-]{0,29}$/.test(form.customer_language_code)) return '客户语言请使用大写编码，例如 EN。'
  if (form.estimated_amount_min !== null && form.estimated_amount_min !== '' || form.estimated_amount_max !== null && form.estimated_amount_max !== '' || form.estimated_currency_code) {
    const minimum = decimalUnits(form.estimated_amount_min, 2, 16), maximum = decimalUnits(form.estimated_amount_max, 2, 16)
    if (minimum === null || maximum === null || !form.estimated_currency_code) return '客户预算须同时填写非负的下限、上限及币种，最多 2 位小数。'
    if (minimum > maximum) return '客户预算上限不能小于下限。'
  }
  return ''
}
async function save(submit = false) {
  if (disabled.value || submit && !canSubmit.value) return
  const invalid = validate(submit)
  if (invalid) { validationError.value = true; errorMessage.value = invalid; return }
  if (attemptPayload && JSON.stringify({ ...buildPayload(), idempotency_key: '' }) !== JSON.stringify({ ...attemptPayload, idempotency_key: '' })) {
    errorMessage.value = '上次保存结果尚未确认，请先恢复上次提交内容后重试，避免重复创建。'; return
  }
  validationError.value = false; busy.value = true; action.value = submit ? 'submit' : 'save'; errorMessage.value = ''
  try {
    if (!savedId.value || snapshot() !== initialSnapshot.value || attemptPayload) {
      attemptPayload ||= buildPayload()
      const result = savedId.value ? await saveInquiryDraft(savedId.value, attemptPayload, etag.value) : await createInquiry({ ...attemptPayload, customer_account_id: form.customer_account_id })
      etag.value = result.etag || ''; populate(result.data); initialSnapshot.value = snapshot(); attemptPayload = null; uncertainSave.value = false; idempotencyKey = newInquiryKey()
    }
    await saveProductImages()
    while (pendingFiles.value.length) {
      const pending = pendingFiles.value[0]!
      pending.error = ''
      try {
        const upload = await uploadInquiryAttachment(savedId.value, pending.file, pending.id, etag.value)
        etag.value = upload.etag || ''; files.value.push(upload.data); pendingFiles.value.shift()
      } catch (error) { pending.error = errorText(error); throw new Error(`草稿已保存，附件“${pending.file.name}”上传失败：${pending.error}`) }
    }
    if (submit) {
      const submitted = await submitInquiry(savedId.value, etag.value)
      navigating = true; await router.replace({ name: 'inquiry-detail', params: { inquiryId: submitted.data.id } })
      ElMessage.success('询盘已提交。')
    } else {
      navigating = true; await router.replace({ name: 'inquiry-edit', params: { inquiryId: savedId.value } }); navigating = false
      ElMessage.success(`草稿 V${draftVersion.value} 已保存。`)
    }
  } catch (error: any) {
    if (error?.response?.status && error.response.status < 500) attemptPayload = null
    uncertainSave.value = !!attemptPayload
    errorMessage.value = errorText(error)
  } finally { busy.value = false; action.value = '' }
}
function back() { if (!busy.value) void router.push({ name: 'inquiries' }) }
async function allowLeave() {
  if (navigating) return true
  if (busy.value) return false
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('当前填写内容或待上传附件尚未保存，确定离开？', '离开新建询盘', { confirmButtonText: '离开', cancelButtonText: '继续填写', type: 'warning' }); return true } catch { return false }
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
watch(form, () => { if (validationError.value) { errorMessage.value = ''; validationError.value = false } })
onBeforeRouteLeave(allowLeave)
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => { stopped = true; customerRequest++; contactRequest++; Object.keys(pendingProductImages).forEach(key => clearPendingImage(Number(key))); window.removeEventListener('beforeunload', beforeUnload) })
</script>
<template>
  <section v-loading="loading" class="inquiry-editor">
    <header class="editor-header">
      <div class="heading-copy"><h1>{{ savedId ? '编辑询盘' : '新建询盘' }}</h1><p>{{ savedId ? `${inquiryNumber} · 草稿 V${draftVersion}` : '先保存草稿，补全联系人与来源后再正式提交。' }}</p></div>
      <div class="header-actions"><el-button :disabled="busy" @click="back">取消</el-button><el-button :disabled="!canSave || busy" :loading="action === 'save'" @click="save(false)">保存草稿</el-button><el-button type="primary" :disabled="!canSubmit || busy" :loading="action === 'submit'" @click="save(true)">确认提交</el-button></div>
    </header>
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="page-error" />
    <div v-if="!loading && !ready" class="load-error"><el-button @click="load">重新加载</el-button></div>
    <el-alert v-if="ready && !canSave" :title="inquiryStatus !== 'DRAFT' ? '该询盘已提交，当前页面仅供查看。' : '当前账号缺少操作权限或有效员工档案。'" type="warning" :closable="false" class="page-error" />
    <div v-if="ready" class="editor-grid">
      <div class="editor-left">
        <section class="editor-panel customer-panel"><h2>客户与来源</h2>
          <el-form :disabled="formLocked" label-position="top" class="basic-form">
            <el-form-item label="客户名称" required><el-select v-model="form.customer_account_id" aria-label="客户名称" filterable remote :remote-method="searchCustomers" :loading="customerLoading" :disabled="!!savedId" clearable placeholder="搜索并选择已有客户" @change="changeCustomer"><el-option v-for="customer in customers" :key="customer.id" :value="customer.id" :label="customer.account_name" /></el-select></el-form-item>
            <el-form-item label="国家 / 地区"><el-input :model-value="selectedCustomer?.primary_country_code || '—'" disabled aria-label="国家 / 地区" /></el-form-item>
            <el-form-item label="询盘来源" required><el-select v-model="form.inquiry_source" aria-label="询盘来源" clearable filterable placeholder="请选择询盘来源"><el-option v-if="form.inquiry_source && !options?.sources.some(source => source.item_code === form.inquiry_source)" :value="form.inquiry_source" :label="`${form.inquiry_source}（历史值）`" disabled/><el-option v-for="source in options?.sources" :key="source.item_code" :value="source.item_code" :label="source.display_name" :disabled="source.disabled" /></el-select></el-form-item>
            <el-form-item label="联系人" required><el-select v-model="form.customer_contact_id" aria-label="联系人" filterable clearable :disabled="!form.customer_account_id || !!contactError" :loading="contactLoading" placeholder="请选择联系人（提交必填）"><el-option v-for="contact in contacts" :key="contact.id" :value="contact.id" :label="contact.status === 'ACTIVE' ? contact.display_name : `${contact.display_name}（已失效）`" :disabled="contact.status !== 'ACTIVE'" /></el-select></el-form-item>
            <el-form-item label="联系邮箱"><el-input :model-value="contactEmail" disabled aria-label="联系邮箱" /></el-form-item>
            <el-form-item label="接收时间" required><el-date-picker v-model="receivedDate" type="datetime" aria-label="接收时间" placeholder="请选择接收时间" format="YYYY-MM-DD HH:mm" /></el-form-item>
            <el-form-item label="客户语言"><el-select v-model="form.customer_language_code" aria-label="客户语言" filterable clearable placeholder="请选择语言"><el-option v-if="form.customer_language_code && !languages.some(language => language.value === form.customer_language_code)" :value="form.customer_language_code" :label="form.customer_language_code" disabled/><el-option v-for="language in languages" :key="language.value" :value="language.value" :label="language.label" :disabled="language.disabled"/></el-select></el-form-item>
          </el-form>
          <p v-if="customerError" class="inline-error">客户搜索失败：{{ customerError }} <button class="text-link" :disabled="busy" @click="searchCustomers()">重试</button></p>
          <p v-if="contactError" class="inline-error">联系人加载失败：{{ contactError }} <button class="text-link" :disabled="busy" @click="loadContacts(form.customer_account_id)">重试</button></p>
          <p class="responsibility-note">责任角色：业务员 · {{ ownerName || '当前账号未关联员工' }}{{ savedId ? '' : '（当前登录人）' }}</p>
        </section>
        <section class="editor-panel products-panel"><div class="panel-heading"><h2>产品需求</h2><el-button :icon="Plus" :disabled="formLocked || form.items.length >= 200" @click="addItem">添加产品</el-button></div>
          <div v-horizontal-overflow class="item-table scroll-actions-container"><table><colgroup><col style="width:9%"/><col style="width:16%"/><col style="width:15%"/><col style="width:9%"/><col style="width:9%"/><col style="width:9%"/><col style="width:10%"/><col style="width:10%"/><col style="width:5%"/><col style="width:8%"/></colgroup><thead><tr><th>类别</th><th>品名</th><th>规格</th><th>颜色</th><th>材质</th><th>数量 / 单位</th><th>目标价</th><th>期望日期</th><th>图片</th><th class="scroll-actions-cell">操作</th></tr></thead><tbody><tr v-for="(item, index) in form.items" :key="item.id || item.line_number" class="product-row"><td>{{ productCategories.find(row => row.id === item.product_category_id)?.category_name || '—' }}</td><td :title="`${item.product_description} · ${item.product_number_snapshot || '手填定制产品'}`">{{ item.product_description }}</td><td :title="item.specification">{{ item.specification || '—' }}</td><td :title="item.color">{{ item.color || '—' }}</td><td :title="item.material">{{ item.material || '—' }}</td><td>{{ item.quantity }} {{ item.unit_code }}</td><td>{{ item.target_unit_price === null || item.target_unit_price === '' ? '—' : `${item.target_unit_price} ${item.target_currency_code}` }}</td><td>{{ item.expected_date || '—' }}</td><td><ProductImage v-if="productImageSource(item)" :src="productImageSource(item)" :name="`${item.product_description}产品图片`"/><span v-else>无图</span></td><td class="product-actions scroll-actions-cell"><el-button link type="primary" :disabled="formLocked" :aria-label="`编辑第${index + 1}行`" @click="editItem(index)">编辑</el-button><el-button link type="primary" :disabled="formLocked" :aria-label="`删除第${index + 1}行`" @click="removeItem(index)">删除</el-button></td></tr><tr v-if="!form.items.length"><td colspan="10" class="empty-state">暂无产品需求，可添加产品，或先保存草稿。</td></tr></tbody></table></div>
          <p class="items-summary">已录入 {{ activeItems.length }} 个产品需求 · 合计数量 {{ quantities }} · 目标价格仅供需求记录，不直接生成报价</p>
        </section>
        <section class="editor-panel notes-panel"><h2>需求备注</h2><el-input v-model="form.description" :disabled="formLocked" aria-label="需求备注" type="textarea" :rows="6" maxlength="5000" show-word-limit placeholder="记录客户原始需求、包装要求及其他补充说明" /></section>
      </div>
      <aside class="editor-right">
        <section class="editor-panel trade-panel"><h2>贸易与预算</h2><el-form :disabled="formLocked" label-position="top" class="trade-form"><el-form-item label="贸易条款"><el-select v-model="form.trade_term_code" aria-label="贸易条款" filterable clearable placeholder="请选择"><el-option v-if="form.trade_term_code && !incoterms.some(term => term.code === form.trade_term_code)" :value="form.trade_term_code" :label="form.trade_term_code" disabled/><el-option v-for="term in incoterms" :key="term.code" :value="term.code" :label="term.code" /></el-select></el-form-item><el-form-item label="交货地点"><el-input v-model="form.trade_term_place" aria-label="交货地点" maxlength="150" placeholder="例如 Ningbo" /></el-form-item><el-form-item label="目标交期"><el-input v-model="form.delivery_requirement" aria-label="目标交期" maxlength="250" placeholder="例如 下单后 45 天" /></el-form-item><el-form-item label="预估金额（产品合计）"><div class="product-total" aria-live="polite">{{ estimatedAmount }}</div></el-form-item><el-form-item label="客户预算（选填）" class="budget-field"><div class="budget-input"><el-input v-model="form.estimated_amount_min" aria-label="客户预算下限" inputmode="decimal" maxlength="19" placeholder="下限"/><span>至</span><el-input v-model="form.estimated_amount_max" aria-label="客户预算上限" inputmode="decimal" maxlength="19" placeholder="上限"/><el-select v-model="form.estimated_currency_code" aria-label="客户预算币种" filterable clearable placeholder="币种"><el-option v-if="form.estimated_currency_code && !currencies.some(currency => currency.code === form.estimated_currency_code)" :value="form.estimated_currency_code" :label="form.estimated_currency_code" disabled/><el-option v-for="currency in currencies" :key="currency.code" :value="currency.code" :label="currency.code"/></el-select></div></el-form-item></el-form></section>
        <section class="editor-panel attachments-panel"><div class="panel-heading"><h2>客户附件</h2><el-button :disabled="formLocked || !canUpload || files.length + pendingFiles.length >= 100" @click="fileInput?.click()">上传附件</el-button><input ref="fileInput" class="file-input" type="file" accept=".pdf,.xlsx,.jpg,.jpeg,.png" multiple aria-label="选择客户附件" :disabled="formLocked || !canUpload" @change="pickFiles" /></div><p class="file-hint">PDF、XLSX、JPG、PNG，每个不超过 10 MB；保存时按当前文件策略处理。</p><div class="attachment-list"><div v-for="file in files" :key="file.id" class="attachment-row"><span class="file-badge" :class="{ sheet: file.original_name.toLowerCase().endsWith('.xlsx') }">{{ file.original_name.split('.').pop()?.toUpperCase() }}</span><div><strong :title="file.original_name">{{ file.original_name }}</strong><small>{{ (file.size_bytes / 1024 / 1024).toFixed(2) }} MB · {{ file.scan_status === 'SKIPPED' ? '内部上传，未扫描' : file.scan_status === 'CLEAN' ? '已上传' : '待处理' }}</small></div></div><div v-for="(pending, index) in pendingFiles" :key="pending.id" class="attachment-row" :class="{ failed: pending.error }"><span class="file-badge" :class="{ sheet: pending.file.name.toLowerCase().endsWith('.xlsx') }">{{ pending.file.name.split('.').pop()?.toUpperCase() }}</span><div><strong :title="pending.file.name">{{ pending.file.name }}</strong><small>{{ (pending.file.size / 1024 / 1024).toFixed(2) }} MB · {{ pending.error ? '上传失败，可重试保存' : busy ? '等待上传 / 当前策略处理中' : '待上传' }}</small></div><el-button link :disabled="formLocked" :aria-label="`移除附件${pending.file.name}`" @click="pendingFiles.splice(index, 1)">移除</el-button></div><p v-if="!files.length && !pendingFiles.length" class="empty-state">暂无附件</p></div></section>
        <section class="editor-panel check-panel"><h2>提交检查</h2><ul><li v-for="check in checks" :key="check.label" :class="{ complete: check.ok }"><span v-if="check.ok" class="checked" role="img" aria-label="已完成"><img :src="checkIcon" alt=""/><span aria-hidden="true">✓</span></span><span v-else class="unchecked" aria-label="待完成"/>{{ check.label }}</li></ul><p>正式提交后进入待首响，由当前负责人跟进。</p></section>
      </aside>
    </div>
    <InquiryProductDialog v-if="productDialogItem" v-model="productDialogVisible" :item="productDialogItem" :categories="productCategories" :units="productUnits" :colors="productColors" :currencies="currencies" :can-upload="canUploadProductImage" :catalog-error="catalogError" :pending-image="pendingProductImages[productDialogItem.line_number!]?.file" :pending-removal="pendingProductImages[productDialogItem.line_number!]?.remove" @confirm="confirmProduct"/>
  </section>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.inquiry-editor { --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-border-radius-base: var(--erp-radius-control); --el-text-color-regular: #{token.$crm-text-secondary}; min-width: 0; padding: 0; color: token.$crm-text-primary; background: transparent; font: 13px var(--erp-font-body); }
h1,h2,p { margin: 0; } h1 { font: 700 36px/44px var(--erp-font-body); } h2 { font-family: var(--erp-font-body); font-size: 18px; line-height: 28px; }
.editor-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }.heading-copy { min-width: 0; }.heading-copy p { color: token.$crm-text-muted; font-size: 12px; line-height: 18px; }.header-actions { display: flex; flex-wrap: wrap; gap: 12px; min-width: 0; }.header-actions :deep(.el-button) { min-width: 96px; margin: 0; }.text-link { color: token.$crm-info; background: none; border: 0; padding: 0; font-size: 12px; cursor: pointer; }.back-link { height: 20px; display: block; }.page-error { margin-bottom: 12px; }.load-error { padding: 60px; text-align: center; }
.editor-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 32%); gap: 14px; align-items: start; }.editor-left,.editor-right { min-width: 0; display: grid; gap: 14px; align-content: start; }.editor-panel { @include detail.surface; padding: 16px; }.editor-panel h2 { border-bottom: 1px solid token.$crm-border-subtle; padding-bottom: 8px; margin-bottom: 10px; }.panel-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }.panel-heading h2 { border: 0; margin: 0; padding: 0; }.panel-heading :deep(.el-button) { height: 32px; margin: 0; }.basic-form { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); column-gap: 14px; }.responsibility-note { font-size: 12px; color: token.$crm-text-muted; line-height: 20px; }.inline-error { color: token.$crm-danger; margin-bottom: 10px; font-size: 12px; }
.inquiry-editor :deep(.el-form-item) { margin-bottom: 12px; min-width: 0; }.inquiry-editor :deep(.el-form-item__label) { font-size: 12px; line-height: 18px; height: auto; padding: 0; margin-bottom: 5px; color: token.$crm-text-secondary; }.inquiry-editor :deep(.el-input__wrapper),.inquiry-editor :deep(.el-select__wrapper) { font-size: 13px; }.inquiry-editor :deep(.el-select),.inquiry-editor :deep(.el-date-editor.el-input) { width: 100%; min-width: 0; }.inquiry-editor :deep(.el-button) { font-family: inherit; }
.item-table { max-height: 350px; overflow: auto; }.item-table table { width: 100%; min-width: 980px; table-layout: fixed; border-collapse: collapse; font-size: 12px; }.item-table th { position: sticky; top: 0; z-index: 1; background: token.$crm-color-subtle; text-align: left; font-weight: 400; height: 36px; color: token.$crm-text-secondary; }.item-table th,.item-table td { padding: 6px 4px; }.item-table td { border-bottom: 1px solid token.$crm-border-subtle; height: 44px; }.item-table :deep(.el-input__wrapper) { padding: 1px 6px; }.item-table :deep(.el-input__prefix) { display: none; }.price-input { display: grid; grid-template-columns: minmax(0,1fr) 78px; gap: 4px; }.price-input :deep(.el-select__wrapper) { padding: 4px 6px; }.items-summary { @include detail.inset; margin-top: 12px; padding: 12px; min-height: 42px; color: token.$crm-text-muted; font-size: 12px; line-height: 20px; overflow-wrap: anywhere; }.notes-panel :deep(textarea) { font-family: inherit; font-size: 13px; line-height: 22px; background: var(--erp-input-surface); color: token.$crm-text-primary; min-height: 156px; }.notes-panel :deep(.el-input__count) { background: transparent; }
.trade-form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 12px; }.trade-form .budget-field { grid-column: 1 / -1; margin-bottom: 0; }.budget-input { display: grid; grid-template-columns: minmax(0,1fr) auto minmax(0,1fr) 86px; gap: 6px; align-items: center; width: 100%; }.product-total { box-sizing: border-box; min-height: 32px; width: 100%; padding: 6px 10px; border: 1px solid var(--erp-input-border); border-radius: var(--erp-radius-control); background: var(--erp-input-readonly-background); font-size: 12px; line-height: 18px; overflow-wrap: anywhere; }.file-input { display: none; }.file-hint,.check-panel p { font-size: 12px; color: token.$crm-text-muted; line-height: 20px; }.attachment-list { display: grid; gap: 6px; max-height: 250px; overflow: auto; margin-top: 10px; }.attachment-row { @include detail.inset; display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 6px; }.attachment-row > div { min-width: 0; flex: 1; }.attachment-row strong { font-size: 12px; font-weight: 500; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.attachment-row small { display: block; margin-top: 5px; color: token.$crm-text-muted; font-size: 11px; }.file-badge { width: 36px; height: 36px; flex-shrink: 0; display: grid; place-items: center; border-radius: 3px; color: var(--erp-tag-brand-text); background: var(--erp-tag-brand-background); font-size: 10px; font-weight: 700; }.file-badge.sheet { color: var(--erp-tag-success-text); background: var(--erp-tag-success-background); }.failed { border-color: token.$crm-danger; }.empty-state { padding: 20px 6px; color: token.$crm-text-muted; text-align: center; font-size: 12px; }.check-panel ul { list-style: none; padding: 0; margin: 14px 0 18px; display: grid; gap: 14px; }.check-panel li { display: flex; align-items: center; gap: 10px; color: token.$crm-text-muted; font-size: 12px; }.check-panel li.complete { color: token.$crm-text-secondary; }.check-panel img,.unchecked { width: 18px; height: 18px; flex-shrink: 0; }.checked { position: relative; width: 18px; height: 18px; flex-shrink: 0; }.checked > span { position: absolute; inset: 0; display: grid; place-items: center; color: token.$crm-text-inverse; font-size: 12px; font-weight: 700; }.unchecked { border: 1px solid token.$crm-border-strong; border-radius: 50%; }
.products-panel .item-table { border: 1px solid var(--erp-table-frame-border); border-radius: var(--erp-radius-control); background: var(--erp-table-background); }
.products-panel .item-table table { min-width: 780px; border-collapse: separate; border-spacing: 0; }
.products-panel .item-table th { height: 44px; padding: 0 8px !important; font-weight: 500; border-bottom: 1px solid token.$crm-border-default; }
.products-panel .item-table td { height: 34px !important; padding: 0 8px !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-bottom-color: token.$crm-border-default; }
.products-panel .item-table tbody tr:last-child td { border-bottom: 0; }
.products-panel .item-table tbody tr:hover td { background: token.$crm-color-row-hover; }
.product-actions :deep(.el-button) { margin: 0 4px 0 0; padding: 0; font-size: 12px; }
@media (max-width:1200px) { .editor-grid { grid-template-columns:minmax(0,1fr); } }
@media (max-width:680px) { .basic-form,.trade-form { grid-template-columns:minmax(0,1fr); } .budget-input { grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); } .budget-input > :deep(.el-select) { grid-column:1 / -1; } }
</style>
