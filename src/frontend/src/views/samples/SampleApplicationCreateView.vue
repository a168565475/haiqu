<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, type UploadFile } from 'element-plus'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import { useProtectedResourceUrls } from '@/composables/useProtectedResourceUrl'
import SampleSection from '@/components/samples/SampleSection.vue'
import SampleProductFields from '@/components/samples/SampleProductFields.vue'
import type { ProductEntryDraft } from '@/types/productCatalog'
import uploadIcon from '@/assets/samples/upload-reference.svg'
import { fetchSample, fetchSampleFormContext, fetchSampleFormOptions } from '@/api/samples'
import { createClientUuid } from '@/utils/clientUuid'
import { fetchCustomerContacts } from '@/api/contacts'
import { fetchCustomer, fetchCustomers } from '@/api/customers'
import { submitSampleApplication } from '@/api/sampleApplication'
import { useAuthStore } from '@/stores/auth'
import { sampleDimensionFields, type SampleApplicationDraft } from '@/types/sampleApplication'
import type { SampleCustomerOption, SampleFormContext, SampleFormOptions } from '@/types/sample'
import type { ContactListItem } from '@/types/contact'
import { sampleProductSelection, validateSampleApplication, validateSampleReferenceImage } from '@/utils/sampleApplication'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(true)
const submitting = ref(false)
const productFields = ref<InstanceType<typeof SampleProductFields>>()
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
const contactsLoading = ref(false)
const imagePreview = ref('')
const sourceImageVisible = ref(false)
const uploadKey = ref(0)
const initialValue = ref('')
const submissionKey = createClientUuid()
const editingId = computed(() => typeof route.query.editApplication === 'string' ? route.query.editApplication : '')
const editingEtag = ref('')
const returnedNote = ref('')
const savedNumber = ref({ suffix: '', number: '' })
let contactsRequest = 0
let customersRequest = 0
let submitted = false
const form = reactive<SampleApplicationDraft>({
  manualRequestNumber: '', productColorId: '', isSalesperson: false,
  productSelection: sampleProductSelection('', ''),
  sourceType: null, sourceId: '', sourceProductId: '', productId: '', customerId: '', contactId: '', ownerId: '',
  sampleType: '', shippingMethod: '', deliveryBatch: '', repeatOrder: null, orderDate: '', dueDate: '',
  productName: '', specification: '', lengthCm: '', armrestWidthCm: '', seatWidthCm: '', backHeightCm: '', seatHeightCm: '',
  requirements: '', quantity: null, referenceImage: null,
})
const sourceLocked = computed(() => Boolean(context.value))
const productDraft = computed(() => form.productSelection?.draft || sampleProductSelection(form.productName, form.specification, form.productSelectionSnapshot).draft!)
const showCustomer = computed(() => options.value?.is_salesperson === true)
const numberPreview = computed(() => savedNumber.value.number && form.manualRequestNumber === savedNumber.value.suffix ? savedNumber.value.number : `HTS${form.manualRequestNumber.trim().toUpperCase()}`)
const canCreate = computed(() => auth.hasPermission('samples.add_samplerequest'))
const sourceLabel = computed(() => context.value?.source_type === 'quotation' ? '来源报价' : '来源询盘')
const selectedSourceProduct = computed(() => context.value?.products.find(item => item.id === form.sourceProductId))
const selectableSourceImages = computed(() => {
  const productImages = selectedSourceProduct.value?.reference_images || []
  if (context.value?.source_type === 'quotation') return productImages
  return productImages.length ? productImages : context.value?.reference_images || []
})
const sourcePreviewUrls = computed(() => selectableSourceImages.value.map(image => image.url))
const imageResources = useProtectedResourceUrls(() => [imagePreview.value, ...(sourceImageVisible.value ? sourcePreviewUrls.value : [])])
watch(imageResources.active, active => { if (!active) sourceImageVisible.value = false }, { flush: 'sync' })
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
    form.isSalesperson = options.value.is_salesperson === true
    customerMatches.value = options.value.customers
    form.ownerId = options.value.salespeople.some(person => person.id === options.value!.current_maker.id)
      ? options.value.current_maker.id : ''
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
      savedNumber.value = { suffix: sample.manual_request_number || '', number: sample.request_number }
      Object.assign(form, {
        manualRequestNumber: sample.manual_request_number || '', productColorId: product.details[0]?.product_color_id || '',
        customerId: sample.customer_account || '', contactId: sample.customer_contact || '', ownerId: sample.owner.id,
        sampleType: sample.sample_type, shippingMethod: sample.shipping_method, deliveryBatch: sample.delivery_batch,
        repeatOrder: sample.is_repeat_order, orderDate: sample.order_date || '', dueDate: sample.sample_due_date || '',
        sourceProductId: product.source_quotation_line_id || product.source_inquiry_item_id || '',
        productId: product.product_id || '', productCatalogId: product.product_catalog_id || '',
        productSelection: sampleProductSelection(product.product_name, product.specification, product.product_selection_snapshot), productSelectionSnapshot: product.product_selection_snapshot || null,
        productName: product.product_name, specification: product.specification, requirements: sample.purpose,
        lengthCm: product.length_cm || '', armrestWidthCm: product.armrest_width_cm || '', seatWidthCm: product.seat_width_cm || '',
        backHeightCm: product.back_height_cm || '', seatHeightCm: product.seat_height_cm || '', quantity: product.total_sample_quantity,
      })
      if (form.productSelection?.draft && !product.product_selection_snapshot?.name) Object.assign(form.productSelection.draft, { category_name: product.category_name || '', material: product.material_snapshot || '' })
      selectedCustomer.value = sample.customer_account ? { id: sample.customer_account, account_name: sample.customer_name, account_code: '' } : null
      if (sourceType && sourceId && selectedCustomer.value) {
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
            product_catalog_id: product.product_catalog_id || null, product_selection_snapshot: product.product_selection_snapshot,
            product_name: product.product_name, specification: product.specification_display ?? product.specification, source_quantity: String(product.total_sample_quantity), source_unit_code: product.product_selection_snapshot?.unit_code || 'PCS' }],
        }
      }
      if (showCustomer.value && !sourceLocked.value) await loadContacts()
      if (sample.reference_image) imagePreview.value = `/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/`
    }
    if (!existing && showCustomer.value && !sourceLocked.value && route.query.customer_id) {
      if (typeof route.query.customer_id !== 'string') throw new Error('客户信息不完整，请从客户详情重新进入。')
      const { data: customer } = await fetchCustomer(route.query.customer_id)
      if (customer.archived_at) throw new Error('该客户已归档，不能创建新的打样申请。')
      selectedCustomer.value = { id: customer.id, account_name: customer.account_name, account_code: customer.account_code }
      form.customerId = customer.id
      await loadContacts()
    }
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

function updateProduct(draft: ProductEntryDraft) {
  form.productId = ''; form.productCatalogId = ''; form.productSelection = { draft }
  form.productName = draft.name; form.specification = draft.specification
}

function chooseSourceProduct(id: string) {
  const product = context.value?.products.find(item => item.id === id)
  const productChanged = form.sourceProductId !== (product?.id || '')
  form.sourceProductId = product?.id || ''
  form.productId = product?.product_id || ''
  form.productCatalogId = product?.product_catalog_id || ''
  form.productSelection = null
  form.productSelectionSnapshot = product?.product_selection_snapshot || null
  form.productName = product?.product_name || ''
  form.specification = product?.specification || ''
  form.productSelection = sampleProductSelection(form.productName, form.specification, form.productSelectionSnapshot)
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
  productFields.value?.commit()
  const message = validateSampleApplication(form)
  if (message) { submitError.value = message; return }
  submitting.value = true
  try {
    const color = options.value?.colors.find(item => item.id === form.productColorId)
    const result = await submitSampleApplication({ ...form, productId: '', productCatalogId: '',
      productSelection: { draft: { ...productDraft.value, color_id: null, color_name: color?.color_name || '', sources: { ...productDraft.value.sources, color_name: 'typed' } } },
    }, { key: submissionKey, sampleId: editingId.value || undefined, etag: editingEtag.value })
    submitted = true
    const effective = result.status === 'PENDING_COMPLETION'
    ElMessage.success(effective ? '打样申请已直接生效，待工厂完善需求。' : '打样申请已提交厂长确认。')
    await router.replace({ name: effective ? 'sample-detail' : 'sample-director-review', params: { sampleId: result.id } })
  } catch (error) { submitError.value = apiError(error) }
  finally { submitting.value = false }
}

useSampleUnsavedChanges(() => dirty.value && !submitted, '离开创建页')
onMounted(loadPage)
onBeforeUnmount(() => { customersRequest++; contactsRequest++; releaseImage() })
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
            <ElFormItem label="打样单号 *" class="sample-number-field"><div class="sample-number-input"><ElInput v-model="form.manualRequestNumber" aria-label="打样单号后缀" maxlength="46" placeholder="请输入单号后缀"><template #prepend>HTS</template></ElInput><ElInput :model-value="numberPreview" class="number-preview" aria-label="完整打样单号" readonly /></div></ElFormItem>
            <ElFormItem :label="sourceLabel"><ElInput class="readonly-field" :model-value="context?.source_number || '无来源询盘'" disabled /></ElFormItem>
            <ElFormItem v-if="showCustomer" label="客户">
              <ElInput v-if="sourceLocked" :model-value="context?.customer.account_name" disabled />
              <ElSelect v-else v-model="form.customerId" aria-label="客户" filterable remote :remote-method="searchCustomers" :loading="customersLoading" placeholder="请选择客户" @change="changeCustomer"><ElOption v-for="customer in customerOptions" :key="customer.id" :value="customer.id" :label="customer.account_name" /></ElSelect>
            </ElFormItem>
            <ElFormItem v-if="showCustomer" label="联系人">
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
              <div class="product-fields">
                <ElFormItem v-if="sourceLocked && (context?.products.length || 0) > 1" label="来源明细"><ElSelect :model-value="form.sourceProductId" aria-label="来源明细" placeholder="请选择来源明细" @change="chooseSourceProduct"><ElOption v-for="product in context?.products" :key="product.id" :value="product.id" :label="`${product.product_name} / ${product.specification}`" /></ElSelect></ElFormItem>
                <SampleProductFields ref="productFields" :model-value="productDraft" :disabled="submitting" @update:model-value="updateProduct" />
                <ElFormItem label="色卡 / 色号 / 颜色 *"><ElSelect v-model="form.productColorId" aria-label="色卡 / 色号 / 颜色" filterable placeholder="请选择颜色"><ElOption v-for="color in options?.colors" :key="color.id" :value="color.id" :label="[color.color_card || '—', color.color_code || '—', color.color_name].join(' / ')" /></ElSelect></ElFormItem>
                <ElFormItem label="打样数量 *" class="quantity-field"><div class="quantity-input"><ElInputNumber v-model="form.quantity" aria-label="打样数量" :controls="false" :min="1" :max="2147483647" placeholder="请输入数量" /><span class="quantity-unit">{{ form.productSelection?.draft?.unit_name || form.productSelectionSnapshot?.unit_name || 'PCS' }}</span></div></ElFormItem>
                <div class="dimensions-grid"><ElFormItem v-for="field in sampleDimensionFields" :key="field.key" :label="field.label"><ElInput v-model="form[field.key]" :aria-label="field.label" inputmode="decimal" placeholder="选填" maxlength="11" /></ElFormItem></div>
                <ElFormItem label="备注（选填）" class="requirements-field"><ElInput v-model="form.requirements" aria-label="备注" type="textarea" :rows="4" resize="none" maxlength="2000" show-word-limit placeholder="请输入备注" /></ElFormItem>
              </div>
            </div>
          </SampleSection>
          <div class="application-aside">
            <SampleSection title="图片上传" class="upload-section">
              <p class="field-label">参考图片（选填）</p>
              <ElButton v-if="selectableSourceImages.length" class="source-image-select" :disabled="submitting" @click="sourceImageVisible = true">选择{{ sourceImageLabel }}（{{ selectableSourceImages.length }} 张）</ElButton>
              <div v-if="imagePreview" class="reference-preview"><img v-if="imageResources.active.value" :src="imageResources.urlFor(imagePreview)" alt="已选择的参考图片" /><div class="reference-image-actions"><ElUpload :key="uploadKey" :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png" :on-change="selectImage" :disabled="submitting"><ElButton :disabled="submitting">替换图片</ElButton></ElUpload><ElButton :disabled="submitting" @click="removeImage">移除图片</ElButton></div></div>
              <ElUpload v-else :key="uploadKey" drag :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png" :limit="1" :on-change="selectImage" :on-exceed="() => ElMessage.warning('最多选择一张参考图片。')">
                <img :src="uploadIcon" class="upload-icon" alt="" /><strong>上传参考图片</strong><span>支持 JPG、PNG，最多 1 张，单张不超过 5MB</span>
              </ElUpload>
              <p class="field-hint">可上传产品外观或客户参考图。</p>
            </SampleSection>
          </div>
        </div>
      </ElForm>
    </div>
    <ElDialog :model-value="sourceImageVisible && imageResources.active.value" @update:model-value="sourceImageVisible = $event" :title="`选择${sourceImageLabel}`" width="780px">
      <p>点击缩略图可放大查看，确认后点击“选用此图”。</p>
      <div class="sample-source-images">
        <article v-for="(image, index) in selectableSourceImages" :key="image.id" :class="{ 'is-selected': form.sourceReferenceImageId === image.id }">
          <ElImage v-if="imageResources.active.value" :src="imageResources.urlFor(image.url)" :alt="`${sourceImageLabel} ${index + 1}`" fit="contain" :preview-src-list="imageResources.urlsFor(sourcePreviewUrls)" :initial-index="index" preview-teleported>
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
