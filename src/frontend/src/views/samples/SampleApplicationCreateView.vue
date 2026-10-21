<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import SampleProductImage from '@/components/samples/SampleProductImage.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, type UploadFile } from 'element-plus'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import SampleSection from '@/components/samples/SampleSection.vue'
import uploadIcon from '@/assets/samples/upload-reference.svg'
import { fetchSample, fetchSampleFormContext, fetchSampleFormOptions } from '@/api/samples'
import { createClientUuid } from '@/utils/clientUuid'
import { fetchCustomerContacts } from '@/api/contacts'
import { fetchCustomer, fetchCustomers } from '@/api/customers'
import { fetchProducts } from '@/api/products'
import { submitSampleApplication } from '@/api/sampleApplication'
import { useAuthStore } from '@/stores/auth'
import { sampleDimensionFields, type SampleApplicationDraft } from '@/types/sampleApplication'
import type { SampleCustomerOption, SampleFormContext, SampleFormOptions } from '@/types/sample'
import type { ProductInformation } from '@/types/product'
import type { ContactListItem } from '@/types/contact'
import { validateSampleApplication, validateSampleReferenceImage } from '@/utils/sampleApplication'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref('')
const submitError = ref('')
const options = ref<SampleFormOptions | null>(null)
const context = ref<SampleFormContext | null>(null)
const contacts = ref<ContactListItem[]>([])
const customerMatches = ref<SampleCustomerOption[]>([])
const selectedCustomer = ref<SampleCustomerOption | null>(null)
const customersLoading = ref(false)
const customerOptions = computed(() => [...new Map([
  ...(selectedCustomer.value ? [selectedCustomer.value] : []), ...customerMatches.value,
].map(customer => [customer.id, customer])).values()])
const products = ref<ProductInformation[]>([])
const contactsLoading = ref(false)
const productsLoading = ref(false)
const imagePreview = ref('')
const sourceImageVisible = ref(false)
const uploadKey = ref(0)
const selectedProduct = ref('')
const linkedProductSnapshot = ref<{ name: string; specification: string } | null>(null)
const initialValue = ref('')
const submissionKey = createClientUuid()
const editingId = computed(() => typeof route.query.editApplication === 'string' ? route.query.editApplication : '')
const editingEtag = ref('')
const returnedNote = ref('')
let contactsRequest = 0
let customersRequest = 0
let productsRequest = 0
let submitted = false
const form = reactive<SampleApplicationDraft>({
  sourceType: null, sourceId: '', sourceProductId: '', productId: '', customerId: '', contactId: '', ownerId: '',
  sampleType: '', shippingMethod: '', deliveryBatch: '', repeatOrder: null, orderDate: '', dueDate: '',
  productName: '', specification: '', lengthCm: '', armrestWidthCm: '', seatWidthCm: '', backHeightCm: '', seatHeightCm: '',
  requirements: '', quantity: null, referenceImage: null,
})
const sourceLocked = computed(() => Boolean(context.value))
const canCreate = computed(() => auth.hasPermission('samples.add_samplerequest'))
const sourceLabel = computed(() => context.value?.source_type === 'quotation' ? '来源报价' : '来源询盘')
const selectedSourceProduct = computed(() => context.value?.products.find(item => item.id === form.sourceProductId))
const selectableSourceImages = computed(() => {
  const productImages = selectedSourceProduct.value?.reference_images || []
  if (context.value?.source_type === 'quotation') return productImages
  return productImages.length ? productImages : context.value?.reference_images || []
})
const sourceImageLabel = computed(() => context.value?.source_type === 'quotation' ? '报价产品图片' : '询盘图片')
const dirty = computed(() => Boolean(initialValue.value) && (JSON.stringify({ ...form, referenceImage: null }) !== initialValue.value || Boolean(form.referenceImage)))

function apiError(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.response?.status === 403) return '当前账号没有查看或操作此数据的权限。'
    const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
    return data?.error?.message || data?.detail || '数据加载失败，请重试。'
  }
  return error instanceof Error ? error.message : '操作失败，请重试。'
}

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  try {
    if (!canCreate.value) throw new Error('当前账号没有创建打样申请的权限。')
    options.value = await fetchSampleFormOptions()
    customerMatches.value = options.value.customers
    form.ownerId = options.value.current_maker.id
    const existing = editingId.value ? await fetchSample(editingId.value) : null
    if (existing && !existing.data.application_actions?.can_resubmit) throw new Error('该申请当前不允许修改重提。')
    const sourceType = existing ? existing.data.source_quotation_version ? 'quotation' : existing.data.source_inquiry ? 'inquiry' : null : route.query.sourceType
    const sourceId = existing ? existing.data.source_quotation_version || existing.data.source_inquiry : route.query.sourceId
    if (!existing && (sourceType || sourceId)) {
      if (!['inquiry', 'quotation'].includes(String(sourceType)) || typeof sourceId !== 'string' || !sourceId) throw new Error('来源信息不完整，请从询盘或报价详情重新进入。')
      const source = await fetchSampleFormContext(sourceType as 'inquiry' | 'quotation', sourceId)
      context.value = source
      Object.assign(form, {
        sourceType: source.source_type, sourceId: source.source_id, customerId: source.customer.id,
        contactId: source.contact?.id || '', ownerId: source.owner.id,
        orderDate: source.basic_info.order_date || '', dueDate: source.suggested_due_date || '',
      })
      if (source.products.length === 1) chooseSourceProduct(source.products[0]!.id)
      else if (source.reference_images?.length === 1) chooseSourceImage(source.reference_images[0]!.id)
    }
    if (existing) {
      const sample = existing.data
      const product = sample.products?.[0]
      if (!product || !sample.owner) throw new Error('申请缺少产品或业务员信息，请联系管理员。')
      editingEtag.value = existing.etag
      returnedNote.value = sample.director_note || ''
      Object.assign(form, {
        customerId: sample.customer_account, contactId: sample.customer_contact || '', ownerId: sample.owner.id,
        sampleType: sample.sample_type, shippingMethod: sample.shipping_method, deliveryBatch: sample.delivery_batch,
        repeatOrder: sample.is_repeat_order, orderDate: sample.order_date || '', dueDate: sample.sample_due_date || '',
        sourceProductId: product.source_quotation_line_id || product.source_inquiry_item_id || '',
        productId: product.product_id || '',
        productName: product.product_name, specification: product.specification, requirements: sample.purpose,
        lengthCm: product.length_cm || '', armrestWidthCm: product.armrest_width_cm || '', seatWidthCm: product.seat_width_cm || '',
        backHeightCm: product.back_height_cm || '', seatHeightCm: product.seat_height_cm || '', quantity: product.total_sample_quantity,
      })
      selectedCustomer.value = { id: sample.customer_account, account_name: sample.customer_name, account_code: '' }
      if (sourceType && sourceId) {
        form.sourceType = sourceType as 'inquiry' | 'quotation'
        form.sourceId = String(sourceId)
        context.value = {
          source_type: form.sourceType, source_id: form.sourceId, source_parent_id: null, source_version_id: sample.source_quotation_version,
          source_number: sample.source_quotation_number || sample.source_inquiry_number, customer: selectedCustomer.value,
          contact: sample.customer_contact ? { id: sample.customer_contact, display_name: sample.customer_contact_name } : null,
          owner: sample.owner, transaction_entity_id: sample.transaction_entity,
          basic_info: { order_date: sample.order_date || null, sample_due_date: sample.sample_due_date || null }, suggested_due_date: sample.sample_due_date || null,
          sample_types: options.value.sample_types, unfinished_samples: [],
          products: [{ id: form.sourceProductId, source_inquiry_item_id: product.source_inquiry_item_id, source_quotation_line_id: product.source_quotation_line_id,
            product_name: product.product_name, specification: product.specification, source_quantity: String(product.total_sample_quantity), source_unit_code: 'PCS' }],
        }
      }
      selectedProduct.value = product.product_name
      linkedProductSnapshot.value = product.product_id ? { name: product.product_name, specification: product.specification } : null
      if (!sourceLocked.value) await loadContacts()
      if (sample.reference_image) imagePreview.value = `/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/`
    }
    if (!existing && !sourceLocked.value && route.query.customer_id) {
      if (typeof route.query.customer_id !== 'string') throw new Error('客户信息不完整，请从客户详情重新进入。')
      const { data: customer } = await fetchCustomer(route.query.customer_id)
      if (customer.archived_at) throw new Error('该客户已归档，不能创建新的打样申请。')
      selectedCustomer.value = { id: customer.id, account_name: customer.account_name, account_code: customer.account_code }
      form.customerId = customer.id
      await loadContacts()
    }
    if (!sourceLocked.value) void searchProducts('')
    initialValue.value = JSON.stringify({ ...form, referenceImage: null })
  } catch (error) { errorMessage.value = apiError(error) }
  finally { loading.value = false }
}

async function searchCustomers(query: string) {
  const request = ++customersRequest
  if (sourceLocked.value) return
  const keyword = query.trim()
  if (!keyword) { customerMatches.value = options.value?.customers || []; customersLoading.value = false; return }
  customersLoading.value = true
  try {
    const result = await fetchCustomers({ q: keyword, page: 1, page_size: 50, archived: 'false' })
    if (request === customersRequest) customerMatches.value = result.data
  } catch (error) {
    if (request === customersRequest) { customerMatches.value = []; ElMessage.error(apiError(error)) }
  } finally { if (request === customersRequest) customersLoading.value = false }
}

async function loadContacts(query = '') {
  const request = ++contactsRequest
  if (!form.customerId || sourceLocked.value) return
  contactsLoading.value = true
  try {
    const result = await fetchCustomerContacts(form.customerId, { page: 1, page_size: 100, q: query })
    if (request === contactsRequest) contacts.value = result.data
  } catch (error) { if (request === contactsRequest) ElMessage.error(apiError(error)) }
  finally { if (request === contactsRequest) contactsLoading.value = false }
}

function changeCustomer() {
  selectedCustomer.value = customerOptions.value.find(customer => customer.id === form.customerId) || null
  contactsRequest++
  form.contactId = ''
  contacts.value = []
  contactsLoading.value = false
  void loadContacts()
}

async function searchProducts(query: string) {
  if (sourceLocked.value) return
  const request = ++productsRequest
  productsLoading.value = true
  try {
    const result = await fetchProducts({ page: 1, page_size: 50, q: query.trim(), status: 'ACTIVE' })
    if (request === productsRequest) products.value = result.data
  } catch (error) { if (request === productsRequest) ElMessage.error(apiError(error)) }
  finally { if (request === productsRequest) productsLoading.value = false }
}

function openProductOptions(visible: boolean) {
  if (visible && !productsLoading.value && !products.value.length) void searchProducts('')
}

function chooseProduct(value: string) {
  const product = products.value.find(item => item.id === value)
  form.productId = product?.id || ''
  form.productName = product?.product_name || value
  form.specification = product?.specification || ''
  linkedProductSnapshot.value = product ? { name: product.product_name, specification: product.specification } : null
}

function clearProductLinkIfEdited() {
  if (!form.productId || !linkedProductSnapshot.value) return
  if (form.productName !== linkedProductSnapshot.value.name || form.specification !== linkedProductSnapshot.value.specification) {
    form.productId = ''
    linkedProductSnapshot.value = null
  }
}

function chooseSourceProduct(id: string) {
  const product = context.value?.products.find(item => item.id === id)
  const productChanged = form.sourceProductId !== (product?.id || '')
  form.sourceProductId = product?.id || ''
  form.productId = product?.product_id || ''
  form.productName = product?.product_name || ''
  form.specification = product?.specification || ''
  linkedProductSnapshot.value = product?.product_id ? { name: form.productName, specification: form.specification } : null
  if (!productChanged) return
  const images = context.value?.source_type === 'quotation'
    ? product?.reference_images || []
    : product?.reference_images?.length ? product.reference_images : context.value?.reference_images || []
  if (form.sourceReferenceImageId && !images.some(image => image.id === form.sourceReferenceImageId)) {
    releaseImage()
    form.sourceReferenceImageId = ''
  }
  form.removeReferenceImage = false
  if (!form.referenceImage && !form.sourceReferenceImageId && images.length === 1) chooseSourceImage(images[0]!.id)
}

function releaseImage() {
  if (imagePreview.value.startsWith('blob:')) URL.revokeObjectURL(imagePreview.value)
  imagePreview.value = ''
}

function selectImage(upload: UploadFile) {
  const file = upload.raw
  if (!file) return
  const message = validateSampleReferenceImage(file)
  if (message) { ElMessage.warning(message); uploadKey.value++; return }
  releaseImage()
  form.referenceImage = file
  form.sourceReferenceImageId = ''
  form.removeReferenceImage = false
  imagePreview.value = URL.createObjectURL(file)
  uploadKey.value++
}

function chooseSourceImage(id: string) {
  if (submitting.value) return
  const image = selectableSourceImages.value.find(item => item.id === id)
  if (!image) return
  releaseImage(); form.referenceImage = null; form.sourceReferenceImageId = image.id; form.removeReferenceImage = false; imagePreview.value = image.url; uploadKey.value++
  sourceImageVisible.value = false
}
function removeImage() { releaseImage(); form.referenceImage = null; form.sourceReferenceImageId = ''; form.removeReferenceImage = true; uploadKey.value++ }

async function submit() {
  if (loading.value || submitting.value || !canCreate.value) return
  submitError.value = ''
  const message = validateSampleApplication(form)
  if (message) { submitError.value = message; return }
  submitting.value = true
  try {
    const result = await submitSampleApplication({ ...form }, { key: submissionKey, sampleId: editingId.value || undefined, etag: editingEtag.value })
    submitted = true
    const effective = result.status === 'PENDING_COMPLETION'
    ElMessage.success(effective ? '打样申请已直接生效，待工厂完善需求。' : '打样申请已提交厂长确认。')
    await router.replace({ name: effective ? 'sample-detail' : 'sample-director-review', params: { sampleId: result.id } })
  } catch (error) { submitError.value = apiError(error) }
  finally { submitting.value = false }
}

useSampleUnsavedChanges(() => dirty.value && !submitted, '离开创建页')
onMounted(loadPage)
onBeforeUnmount(() => { customersRequest++; contactsRequest++; productsRequest++; releaseImage() })
</script>

<template>
  <section class="sample-create-page" data-figma-node="1851:18496" aria-label="创建打样申请">
    <div v-loading="loading" class="sample-create-content">
      <header class="application-heading">
        <h1>{{ editingId ? '补充打样申请' : '创建打样申请' }}</h1>
        <div class="application-heading-actions">
          <p v-if="submitError" class="submit-error" role="alert">{{ submitError }}</p>
          <ElButton class="cancel-button" :disabled="submitting" @click="router.push({ name: 'samples' })">取消</ElButton>
          <ElButton class="submit-button" type="primary" :loading="submitting" :disabled="loading || Boolean(errorMessage) || !canCreate" @click="submit">提交确认</ElButton>
        </div>
      </header>
      <div v-if="returnedNote" class="returned-note" role="note">退回意见：{{ returnedNote }}</div>
      <div v-if="errorMessage" class="application-error" role="alert"><p>{{ errorMessage }}</p><ElButton @click="loadPage">重新加载</ElButton></div>
      <ElForm v-else :disabled="submitting" label-position="top" class="application-form erp-flat-form" @submit.prevent="submit">
        <SampleSection title="基础信息" class="basic-section">
          <div class="basic-grid">
            <ElFormItem :label="sourceLabel"><ElInput class="readonly-field" :model-value="context?.source_number || '无来源询盘'" disabled /></ElFormItem>
            <ElFormItem label="客户">
              <ElInput v-if="sourceLocked" :model-value="context?.customer.account_name" disabled />
              <ElSelect v-else v-model="form.customerId" aria-label="客户" filterable remote :remote-method="searchCustomers" :loading="customersLoading" placeholder="请选择客户" @change="changeCustomer"><ElOption v-for="customer in customerOptions" :key="customer.id" :value="customer.id" :label="customer.account_name" /></ElSelect>
            </ElFormItem>
            <ElFormItem label="联系人">
              <ElInput v-if="sourceLocked" class="readonly-field" :model-value="context?.contact?.display_name || '—'" disabled />
              <ElSelect v-else v-model="form.contactId" aria-label="联系人" filterable clearable remote :remote-method="loadContacts" :loading="contactsLoading" :disabled="!form.customerId" placeholder="请选择联系人"><ElOption v-for="contact in contacts" :key="contact.id" :value="contact.id" :label="contact.display_name" /></ElSelect>
            </ElFormItem>
            <ElFormItem label="业务员">
              <ElInput v-if="sourceLocked" :model-value="context?.owner.display_name" disabled />
              <ElSelect v-else v-model="form.ownerId" aria-label="业务员" filterable placeholder="请选择业务员"><ElOption v-for="owner in options?.salespeople" :key="owner.id" :value="owner.id" :label="owner.display_name" /></ElSelect>
            </ElFormItem>
            <ElFormItem label="样品类型 *"><ElSelect v-model="form.sampleType" aria-label="样品类型" placeholder="请选择样品类型"><ElOption v-for="option in options?.sample_types" :key="option.value" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
            <ElFormItem label="寄送方式 *"><ElSelect v-model="form.shippingMethod" aria-label="寄送方式" placeholder="请选择寄送方式"><ElOption v-for="option in options?.shipping_methods" :key="option.value" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
            <ElFormItem label="交货方式 *"><ElSelect v-model="form.deliveryBatch" aria-label="交货方式" placeholder="请选择交货方式"><ElOption v-for="option in options?.delivery_batches" :key="option.value" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
            <ElFormItem label="是否返单 *"><ElSelect v-model="form.repeatOrder" aria-label="是否返单" placeholder="请选择"><ElOption v-for="option in options?.repeat_options" :key="String(option.value)" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
            <ElFormItem label="下单日期"><ElDatePicker v-model="form.orderDate" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" /></ElFormItem>
            <ElFormItem label="期望样品完成日期"><ElDatePicker v-model="form.dueDate" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" /></ElFormItem>
          </div>
        </SampleSection>

        <div class="application-columns">
          <SampleSection title="样品信息" class="product-section">
            <div class="product-body">
              <SampleProductImage class="product-image" :src="imagePreview" />
              <div class="product-fields">
                <ElFormItem label="产品名称">
                  <ElSelect v-if="sourceLocked" :model-value="form.sourceProductId" aria-label="产品名称" placeholder="请选择来源样品" @change="chooseSourceProduct"><ElOption v-for="product in context?.products" :key="product.id" :value="product.id" :label="product.product_name"><span class="product-option"><span class="product-option-name" :title="product.product_name">{{ product.product_name }}</span><span class="product-option-spec" :title="product.specification || '暂无规格'">{{ product.specification || '暂无规格' }}</span></span></ElOption></ElSelect>
                  <ElSelect v-else v-model="selectedProduct" aria-label="产品名称" filterable remote allow-create default-first-option :remote-method="searchProducts" :loading="productsLoading" placeholder="选择成品或输入产品名称" @visible-change="openProductOptions" @change="chooseProduct"><ElOption v-for="product in products" :key="product.id" :value="product.id" :label="product.product_name"><span class="product-option"><span class="product-option-name" :title="product.product_name">{{ product.product_name }}</span><span class="product-option-spec" :title="product.specification || '暂无规格'">{{ product.specification || '暂无规格' }}</span></span></ElOption></ElSelect>
                </ElFormItem>
                <ElFormItem label="规格"><ElInput v-model="form.specification" aria-label="规格" :disabled="sourceLocked" placeholder="请输入规格" maxlength="2000" @input="clearProductLinkIfEdited" /></ElFormItem>
                <div class="dimensions-grid"><ElFormItem v-for="field in sampleDimensionFields" :key="field.key" :label="field.label"><ElInput v-model="form[field.key]" :aria-label="field.label" inputmode="decimal" placeholder="选填" maxlength="11" /></ElFormItem></div>
                <ElFormItem label="特殊要求（选填）" class="requirements-field"><ElInput v-model="form.requirements" aria-label="特殊要求" type="textarea" :rows="4" resize="none" maxlength="2000" show-word-limit placeholder="请输入颜色、包装或工艺要求" /></ElFormItem>
              </div>
            </div>
          </SampleSection>
          <div class="application-aside">
            <SampleSection title="图片上传" class="upload-section">
              <p class="field-label">参考图片（选填）</p>
              <ElButton v-if="selectableSourceImages.length" class="source-image-select" :disabled="submitting" @click="sourceImageVisible = true">选择{{ sourceImageLabel }}（{{ selectableSourceImages.length }} 张）</ElButton>
              <div v-if="imagePreview" class="reference-preview"><img :src="imagePreview" alt="已选择的参考图片" /><div class="reference-image-actions"><ElUpload :key="uploadKey" :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png" :on-change="selectImage" :disabled="submitting"><ElButton :disabled="submitting">替换图片</ElButton></ElUpload><ElButton :disabled="submitting" @click="removeImage">移除图片</ElButton></div></div>
              <ElUpload v-else :key="uploadKey" drag :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png" :limit="1" :on-change="selectImage" :on-exceed="() => ElMessage.warning('最多选择一张参考图片。')">
                <img :src="uploadIcon" class="upload-icon" alt="" /><strong>上传参考图片</strong><span>支持 JPG、PNG，最多 1 张，单张不超过 5MB</span>
              </ElUpload>
              <p class="field-hint">可上传产品外观或客户参考图。</p>
            </SampleSection>
            <SampleSection title="打样数量" class="quantity-section">
              <ElFormItem label="打样数量 *"><ElInputNumber v-model="form.quantity" aria-label="打样数量" :controls="false" :min="1" :max="2147483647" placeholder="请输入数量" /><span class="quantity-unit">PCS</span></ElFormItem>
              <p class="field-hint">请输入大于 0 的整数。</p>
            </SampleSection>
          </div>
        </div>
      </ElForm>
    </div>
    <ElDialog v-model="sourceImageVisible" :title="`选择${sourceImageLabel}`" width="780px">
      <p>点击缩略图可放大查看，确认后点击“选用此图”。</p>
      <div class="sample-source-images">
        <article v-for="(image, index) in selectableSourceImages" :key="image.id" :class="{ 'is-selected': form.sourceReferenceImageId === image.id }">
          <ElImage :src="image.url" :alt="`${sourceImageLabel} ${index + 1}`" fit="contain" :preview-src-list="selectableSourceImages.map(item => item.url)" :initial-index="index" preview-teleported>
            <template #error><span>图片加载失败</span></template>
          </ElImage>
          <div><span>图片 {{ index + 1 }}</span><ElButton :type="form.sourceReferenceImageId === image.id ? 'primary' : 'default'" :disabled="submitting" @click="chooseSourceImage(image.id)">{{ form.sourceReferenceImageId === image.id ? '已选用' : '选用此图' }}</ElButton></div>
        </article>
      </div>
      <template #footer><ElButton @click="sourceImageVisible = false">关闭</ElButton></template>
    </ElDialog>
  </section>
</template>

<style scoped lang="scss" src="./sampleApplication.scss"></style>
