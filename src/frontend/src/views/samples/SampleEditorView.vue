<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { fetchSample, fetchSampleFormOptions } from '@/api/samples'
import { completeSampleApplicationProducts, fetchSampleApplicationProductOptions } from '@/api/sampleApplication'
import { confirmSampleNoMaterials, fetchSampleMaterials, fetchSampleMaterialUnits, saveSampleMaterials } from '@/api/sampleMaterials'
import SampleMaterialEditor from '@/components/samples/SampleMaterialEditor.vue'
import SampleApplicationBasics from '@/components/samples/SampleApplicationBasics.vue'
import SampleProductImage from '@/components/samples/SampleProductImage.vue'
import SampleSection from '@/components/samples/SampleSection.vue'
import SampleFullscreenHeader from '@/components/samples/SampleFullscreenHeader.vue'
import { useSampleFullscreen } from '@/composables/useSampleFullscreen'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import uploadIcon from '@/assets/samples/upload-reference.svg'
import { validateSampleReferenceImage } from '@/utils/sampleApplication'
import { sampleMaterialError, validateSampleMaterials } from '@/utils/sampleMaterial'
import type { SampleDetail, SampleFormOptions } from '@/types/sample'
import type { SampleApplicationBasicInput } from '@/types/sampleApplication'
import type { SampleProductEdit, SampleProductCandidate } from '@/types/sampleEditor'
import type { SampleMaterialDraft, SampleMaterialLoadResult, SampleMaterialUnit } from '@/types/sampleMaterial'

const route = useRoute(), router = useRouter()
const root = ref<HTMLElement>()
const { fullscreen, toggleFullscreen } = useSampleFullscreen(root)
const activeTab = ref<'product' | 'materials'>(route.query.tab === 'materials' ? 'materials' : 'product')
const sample = ref<SampleDetail | null>(null), etag = ref('')
const loading = ref(true), saving = ref(false), productsLoading = ref(false)
const errorMessage = ref(''), actionError = ref(''), materialError = ref(''), successMessage = ref('')
const options = ref<SampleFormOptions | null>(null), productOptions = ref<SampleProductCandidate[]>([])
const referenceImage = ref<File | null>(null), localImagePreview = ref(''), uploadKey = ref(0)
const imagePreview = computed(() => localImagePreview.value || (sample.value?.reference_image ? `/api/v1/sample-requests/${sample.value.id}/business-files/${sample.value.reference_image}/` : ''))
const linkedProducts = new Map<string, { name: string; specification: string }>()
const colorSpecificationBaselines = new Map<string, string>()
const products = ref<SampleProductEdit[]>([]), purpose = ref(''), initialProducts = ref('')
const basic = ref<SampleApplicationBasicInput>({ source_type: null, source_id: null, customer_account_id: '', customer_contact_id: null, owner_employee_id: '', sample_type: '', shipping_method: '', delivery_batch: '', is_repeat_order: null, order_date: null, sample_due_date: null })
const materials = ref<SampleMaterialLoadResult | null>(null), units = ref<SampleMaterialUnit[]>([])
const draft = reactive<SampleMaterialDraft>({ lines: [], notes: '' }), initialMaterials = ref('')
const editorOpen = ref(false), editorDirty = ref(false)
const productCapabilitiesFresh = ref(false), productRefreshing = ref(false), productRefreshError = ref('')
const materialsLoading = ref(false)
let productRequest = 0
const dimensions = [
  { key: 'length_cm', label: '长（cm）' }, { key: 'armrest_width_cm', label: '扶手宽（cm）' },
  { key: 'seat_width_cm', label: '坐宽（cm）' }, { key: 'back_height_cm', label: '背高（cm）' }, { key: 'seat_height_cm', label: '坐高（cm）' },
] as const
const canEditProducts = computed(() => productCapabilitiesFresh.value && Boolean(sample.value?.application_actions?.is_application && sample.value.application_actions.can_edit_products))
const canEditMaterials = computed(() => Boolean(materials.value?.available && materials.value.canEdit))
const canSubmitMaterials = computed(() => canEditMaterials.value && Boolean(materials.value?.available && materials.value.canSubmit))
const productState = () => JSON.stringify({ products: products.value, purpose: purpose.value, basic: basic.value })
const productsDirty = computed(() => Boolean(initialProducts.value) && (productState() !== initialProducts.value || Boolean(referenceImage.value)))
const materialsDirty = computed(() => editorDirty.value || Boolean(initialMaterials.value) && JSON.stringify(draft) !== initialMaterials.value)
useSampleUnsavedChanges(() => productsDirty.value || materialsDirty.value, '离开打样编辑页')
const materialUnavailable = computed(() => {
  const result = materials.value
  if (!result) return '材料需求状态尚未加载。'
  if (!result.available) return result.reason || '当前材料需求不可编辑。'
  return result.canEdit ? '' : '当前账号没有材料需求编辑权限，材料需求只读。'
})

function applySample(result: { data: SampleDetail; etag: string }, preserveDraft = false, expectedEtag = '') {
  const keepDraft = preserveDraft && productsDirty.value
  // 保留旧草稿时只接受本窗口已确认的版本，不能借回读采用第三方的新版本绕过 If-Match。
  if (preserveDraft && (productsDirty.value || materialsDirty.value) && expectedEtag && result.etag !== expectedEtag) {
    productCapabilitiesFresh.value = false
    throw new Error('产品版本已被其他操作更新，草稿仍保留，不会自动采用新版本。请核对后重新打开页面。')
  }
  sample.value = result.data; etag.value = result.etag
  productCapabilitiesFresh.value = true; productRefreshError.value = ''
  if (keepDraft) return
  basic.value = {
    source_type: result.data.source_quotation_version ? 'quotation' : result.data.source_inquiry ? 'inquiry' : null,
    source_id: result.data.source_quotation_version || result.data.source_inquiry || null,
    customer_account_id: result.data.customer_account, customer_contact_id: result.data.customer_contact || null,
    owner_employee_id: result.data.owner?.id || '', sample_type: result.data.sample_type,
    shipping_method: result.data.shipping_method || '', delivery_batch: result.data.delivery_batch || '',
    is_repeat_order: result.data.is_repeat_order ?? null, order_date: result.data.order_date || null,
    sample_due_date: result.data.sample_due_date || result.data.requested_due_at?.slice(0, 10) || null,
  }
  colorSpecificationBaselines.clear()
  products.value = (result.data.products || []).map(product => ({
    id: product.id, product_id: product.product_id || '', category_id: product.category_id || '',
    product_name: product.product_name, specification: product.specification,
    length_cm: product.length_cm, armrest_width_cm: product.armrest_width_cm, seat_width_cm: product.seat_width_cm,
    back_height_cm: product.back_height_cm, seat_height_cm: product.seat_height_cm,
    details: product.details.map(detail => ({ id: detail.id, product_color_id: detail.product_color_id || '', color_code: detail.color_code,
      sample_quantity: detail.sample_quantity, tolerance: detail.tolerance, notes: detail.notes })),
  }))
  purpose.value = result.data.purpose
  clearImageDraft()
  syncProductLinks()
  initialProducts.value = productState()
}
function applyMaterials(result: SampleMaterialLoadResult, preserveDraft = false, expectedEtag = '') {
  const keepDraft = preserveDraft && materialsDirty.value
  if (preserveDraft && (materialsDirty.value || productsDirty.value) && result.available && expectedEtag && result.etag !== expectedEtag) {
    productCapabilitiesFresh.value = false
    throw new Error('材料版本已被其他操作更新，草稿仍保留，不会自动采用新版本。请核对后重新打开页面。')
  }
  materials.value = result
  if (!result.available) return
  if (!keepDraft) {
    draft.lines = result.draft.lines.map(line => ({ ...line })); draft.notes = result.draft.notes
    initialMaterials.value = JSON.stringify(draft)
  }
  etag.value = result.etag
  if (sample.value) { sample.value.status = result.status; sample.value.status_display = result.statusLabel }
}
async function loadMaterials({ preserveDraft = false, duringSave = false } = {}) {
  if (!sample.value || materialsLoading.value || productRefreshing.value || (saving.value && !duringSave)) return
  const expectedEtag = etag.value
  materialsLoading.value = true; materialError.value = ''
  try {
    applyMaterials(await fetchSampleMaterials(sample.value.id), preserveDraft, expectedEtag)
    units.value = await fetchSampleMaterialUnits()
  } catch (error) { materialError.value = sampleMaterialError(error) }
  finally { materialsLoading.value = false }
}
async function refreshProductCapabilities(duringSave = false) {
  if (!sample.value || productRefreshing.value || materialsLoading.value || (saving.value && !duringSave)) return
  const expectedEtag = etag.value
  productCapabilitiesFresh.value = false; productRefreshError.value = ''; productRefreshing.value = true
  // 材料动作已更新版本，不能在详情读取失败时继续使用旧产品能力。
  productRequest++; productsLoading.value = false
  try { applySample(await fetchSample(sample.value.id), true, expectedEtag) }
  catch (error) { productRefreshError.value = `产品能力读取失败：${sampleMaterialError(error)} 产品输入仍保留，请重新核对后继续保存产品。` }
  finally { productRefreshing.value = false }
}
async function loadPage() {
  loading.value = true; errorMessage.value = ''; actionError.value = ''
  try {
    if (typeof route.params.sampleId !== 'string' || !route.params.sampleId) throw new Error('缺少打样申请编号。')
    applySample(await fetchSample(route.params.sampleId))
    // 只读申请不依赖产品检索权限；选项失败也不能把现有资料隐藏掉。
    if (canEditProducts.value) {
      options.value = await fetchSampleFormOptions()
      void searchProducts('')
    }
    await loadMaterials()
  } catch (error) { errorMessage.value = sampleMaterialError(error) }
  finally { loading.value = false }
}
async function searchProducts(query: string) {
  const request = ++productRequest
  productsLoading.value = true
  try {
    if (!sample.value) return
    const result = await fetchSampleApplicationProductOptions(sample.value.id, query)
    if (request === productRequest) productOptions.value = result
  } catch (error) { if (request === productRequest) actionError.value = `产品选项加载失败：${sampleMaterialError(error)}` }
  finally { if (request === productRequest) productsLoading.value = false }
}
function chooseProduct(product: SampleProductEdit, id: string) {
  colorSpecificationBaselines.delete(product.id)
  const selected = productOptions.value.find(item => item.id === id)
  if (!selected) {
    // 与创建页共用手输交互，但编辑既有记录不能清空已填写的规格。
    product.product_id = ''; product.product_name = id; linkedProducts.delete(product.id)
    return
  }
  product.product_id = id; product.product_name = selected.product_name; product.specification = selected.specification
  product.category_id = selected.category_id
  linkedProducts.set(product.id, { name: selected.product_name, specification: selected.specification })
}
function clearProductLinkIfEdited(product: SampleProductEdit) {
  const linked = linkedProducts.get(product.id)
  if (linked && (product.product_name !== linked.name || product.specification !== linked.specification)) {
    product.product_id = ''; linkedProducts.delete(product.id)
  }
}
function editProductSpecification(product: SampleProductEdit) {
  colorSpecificationBaselines.delete(product.id)
  clearProductLinkIfEdited(product)
}
function syncProductLinks() {
  linkedProducts.clear()
  for (const product of products.value) if (product.product_id) linkedProducts.set(product.id, { name: product.product_name, specification: product.specification })
}
async function cancelProductEdit() {
  if (saving.value || materialsLoading.value || productRefreshing.value) return
  if (productsDirty.value) {
    try { await ElMessageBox.confirm('放弃本次未保存的产品修改？材料草稿保持不变。', '取消产品编辑', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' }) }
    catch { return }
    const baseline = JSON.parse(initialProducts.value) as { products: SampleProductEdit[]; purpose: string; basic: SampleApplicationBasicInput }
    products.value = baseline.products; purpose.value = baseline.purpose
    basic.value = baseline.basic
    colorSpecificationBaselines.clear()
    syncProductLinks()
    clearImageDraft()
  }
}
function clearImageDraft() {
  if (localImagePreview.value) URL.revokeObjectURL(localImagePreview.value)
  localImagePreview.value = ''; referenceImage.value = null; uploadKey.value++
}
function selectImage(upload: UploadFile) {
  if (!canEditProducts.value || loading.value || saving.value || materialsLoading.value || productRefreshing.value) return
  const file = upload.raw
  if (!file) return
  const message = validateSampleReferenceImage(file)
  if (message) { ElMessage.warning(message); uploadKey.value++; return }
  clearImageDraft()
  referenceImage.value = file; localImagePreview.value = URL.createObjectURL(file)
}
function savedDetail(productId: string, detailId: string) {
  return sample.value?.products?.find(product => product.id === productId)?.details.find(detail => detail.id === detailId)
}
function colorLabel(id: string) {
  const color = options.value?.colors.find(item => item.id === id)
  return color ? `${color.color_card} / ${color.color_name} / ${color.color_code}` : ''
}
function replaceColorSegment(specification: string, colorName: string) {
  if (!colorName) return specification
  const segment = /(^|[；;])(\s*颜色\s*[:：])([^；;]*)/
  if (segment.test(specification)) return specification.replace(segment, (_match, prefix, label) => `${prefix}${label}${colorName}`)
  const separator = specification && !/[；;]\s*$/.test(specification) ? '；' : ''
  return `${specification}${separator}颜色：${colorName}`
}
function selectColor(product: SampleProductEdit, detail: SampleProductEdit['details'][number]) {
  const color = options.value?.colors.find(item => item.id === detail.product_color_id)
  detail.color_code = color?.color_code || ''
  // 规格是产品级字段，多颜色明细无法安全映射到单个颜色；此时只保存明细色号。
  if (product.details.length !== 1) return
  if (!colorSpecificationBaselines.has(product.id)) colorSpecificationBaselines.set(product.id, product.specification || '')
  const baseline = colorSpecificationBaselines.get(product.id) || ''
  const colorName = color?.color_name?.trim() || color?.color_code?.trim() || ''
  product.specification = replaceColorSegment(baseline, colorName)
}
function selectTab(tab: 'product' | 'materials') {
  if (editorOpen.value) { ElMessage.warning('请先完成或关闭当前材料行编辑。'); return }
  activeTab.value = tab
}
function tabKeydown(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  selectTab(event.key === 'Home' ? 'product' : event.key === 'End' ? 'materials' : activeTab.value === 'product' ? 'materials' : 'product')
  root.value?.querySelector<HTMLButtonElement>(`#sample-${activeTab.value}-tab`)?.focus()
}
async function saveProducts() {
  if (!sample.value || !canEditProducts.value || loading.value || saving.value || materialsLoading.value || productRefreshing.value) return
  actionError.value = ''; successMessage.value = ''
  if (!products.value.length || products.value.some(product => !product.product_name.trim() || !product.category_id || !product.details.length || product.details.some(detail => !detail.product_color_id || !Number.isSafeInteger(detail.sample_quantity) || (detail.sample_quantity || 0) <= 0))) {
    actionError.value = '请填写产品名称、选择产品类别和颜色，并填写大于 0 的整数打样数量。'; return
  }
  saving.value = true
  try {
    const payload = products.value.map(product => {
      const value = { ...product }
      for (const field of dimensions) value[field.key] = value[field.key] || null
      return value
    })
    applySample(await completeSampleApplicationProducts(sample.value.id, etag.value, payload, purpose.value, referenceImage.value || undefined, basic.value))
    successMessage.value = '产品需求已保存。材料填写内容仍保留，提交结果以材料页为准。'
    // 产品与材料分次保存；第二步读取失败不覆盖第一步的成功，也不清除输入。
    await loadMaterials({ preserveDraft: true, duringSave: true })
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
async function submitMaterials(submit: boolean) {
  if (!sample.value || !canEditMaterials.value || loading.value || saving.value || materialsLoading.value || productRefreshing.value || editorOpen.value || materialError.value) return
  if (submit && !canSubmitMaterials.value) return
  actionError.value = ''; successMessage.value = ''
  const validation = submit ? validateSampleMaterials(draft, units.value) : ''
  if (validation) { actionError.value = validation; return }
  saving.value = true
  try {
    if (submit && !await confirmMaterialAction(false)) return
    applyMaterials(await saveSampleMaterials({ sampleId: sample.value.id, etag: etag.value,
      draft: { lines: draft.lines.map(line => ({ ...line })), notes: draft.notes }, submit }))
    successMessage.value = submit ? '材料需求已提交仓库。' : '材料资料已保存。'
    await refreshProductCapabilities(true)
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
async function confirmMaterialAction(noMaterials: boolean) {
  const hasProductDraft = productsDirty.value
  if (!noMaterials && !hasProductDraft) return true
  const message = [
    noMaterials ? '确认本次打样无需用料？本页尚未提交的材料不会提交，确认后可进行生产和参数上传。' : '继续提交材料需求？',
    ...(hasProductDraft ? ['产品草稿尚未保存，本次操作不会保存产品。可先返回产品处理，或继续材料操作后单独保存产品。'] : []),
  ].join('\n')
  try {
    await ElMessageBox.confirm(message, hasProductDraft ? '产品草稿尚未保存' : '确认无需用料', {
      confirmButtonText: noMaterials ? '确认无需用料' : '继续提交材料', cancelButtonText: hasProductDraft ? '返回产品' : '取消',
    })
    return true
  } catch {
    if (hasProductDraft) {
      activeTab.value = 'product'
      await nextTick()
      root.value?.querySelector<HTMLElement>('.product-form-panel')?.scrollIntoView?.({ block: 'start' })
    }
    return false
  }
}
async function noMaterials() {
  if (!sample.value || !canSubmitMaterials.value || loading.value || saving.value || materialsLoading.value || productRefreshing.value || editorOpen.value || materialError.value) return
  saving.value = true; actionError.value = ''; successMessage.value = ''
  try {
    if (!await confirmMaterialAction(true)) return
    applyMaterials(await confirmSampleNoMaterials(sample.value.id, etag.value)); editorDirty.value = false
    successMessage.value = '已确认无需用料，可在详情中继续生产和参数上传。'
    await refreshProductCapabilities(true)
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
onMounted(loadPage)
onBeforeUnmount(clearImageDraft)
</script>

<template>
  <Teleport to="body" :disabled="!fullscreen">
    <section ref="root" class="sample-editor-page" :class="{ 'is-fullscreen': fullscreen }" aria-label="编辑打样需求" v-loading="loading">
      <SampleFullscreenHeader v-if="fullscreen" title="打样需求 · 全屏编辑" :subtitle="sample?.request_number || ''" @exit="toggleFullscreen" />
      <header v-else class="editor-heading">
        <div><div class="title-line"><h1>{{ sample?.request_number || '打样需求' }}</h1><span>{{ sample?.status_display }}</span></div></div>
        <div class="heading-actions"><ElButton :disabled="saving" @click="router.push({ name: 'sample-detail', params: route.params })">查看详情</ElButton><ElButton :disabled="saving" @click="router.push({ name: 'samples' })">返回列表</ElButton></div>
      </header>
      <div v-if="errorMessage" role="alert"><ElAlert :title="errorMessage" type="error" :closable="false" /><ElButton @click="loadPage">重新加载</ElButton></div>
      <template v-else-if="sample">
        <ElAlert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon role="alert" />
        <ElAlert v-if="successMessage" :title="successMessage" type="success" :closable="false" show-icon role="status" />
        <ElAlert v-if="productRefreshError" :title="productRefreshError" type="error" :closable="false" role="alert"><ElButton :disabled="saving || productRefreshing || materialsLoading" @click="refreshProductCapabilities()">重新核对产品能力</ElButton></ElAlert>
        <ElAlert v-if="productsDirty" :title="canEditProducts ? '产品草稿尚未保存，材料操作不会代为保存产品。' : '产品草稿尚未保存，内容已保留；当前产品能力不可用，请核对后再处理。'" type="warning" :closable="false" />
        <div class="editor-toolbar"><nav class="editor-tabs" role="tablist" aria-label="打样编辑内容" @keydown="tabKeydown">
          <button id="sample-product-tab" type="button" role="tab" aria-controls="sample-product-panel" :aria-selected="activeTab === 'product'" :tabindex="activeTab === 'product' ? 0 : -1" @click="selectTab('product')">申请与产品</button>
          <button id="sample-materials-tab" type="button" role="tab" aria-controls="sample-materials-panel" :aria-selected="activeTab === 'materials'" :tabindex="activeTab === 'materials' ? 0 : -1" @click="selectTab('materials')">材料需求</button>
        </nav>
        <div v-if="activeTab === 'product'" class="product-form-actions">
              <span v-if="!canEditProducts" class="field-hint">{{ !productCapabilitiesFresh ? '产品能力尚未确认，请重新核对。' : '当前账号没有此申请的产品编辑权限。' }}</span>
              <ElButton v-if="canEditProducts || productsDirty" class="cancel-button" :disabled="saving || materialsLoading || productRefreshing" @click="cancelProductEdit">取消修改</ElButton>
              <ElButton v-if="canEditProducts" class="submit-button" type="primary" :loading="saving" :disabled="loading || saving || materialsLoading || productRefreshing || !options" @click="saveProducts">保存</ElButton>
            </div>
        </div>
        <section v-show="activeTab === 'product'" id="sample-product-panel" class="product-form-panel" role="tabpanel" aria-labelledby="sample-product-tab">
          <div class="sample-create-page">
            <ElForm label-position="top" :disabled="saving || materialsLoading || productRefreshing || !canEditProducts" class="application-form erp-flat-form" @submit.prevent>
              <SampleSection title="基础信息" class="basic-section">
                <SampleApplicationBasics v-model="basic" :options="options" :sample="sample" />
              </SampleSection>
              <div class="application-columns">
                <SampleSection title="样品信息" class="product-section">
                  <div class="product-body">
                    <SampleProductImage class="product-image" :src="imagePreview" />
                    <div class="product-records">
                      <section v-for="(product, index) in products" :key="product.id" class="product-fields product-record" :data-product-id="product.id">
                        <h3 v-if="products.length > 1">产品 {{ index + 1 }}</h3>
                        <ElFormItem label="产品名称">
                          <ElSelect :model-value="product.product_id || product.product_name" aria-label="产品名称" filterable remote allow-create default-first-option :remote-method="searchProducts" :loading="productsLoading" placeholder="选择成品或输入产品名称" @change="chooseProduct(product, $event)">
                            <ElOption v-if="(product.product_id || product.product_name) && !productOptions.some(item => item.id === product.product_id)" :value="product.product_id || product.product_name" :label="product.product_name"><span class="product-option"><span class="product-option-name">{{ product.product_name }}</span><span class="product-option-spec">{{ product.specification || '暂无规格' }}</span></span></ElOption>
                            <ElOption v-for="item in productOptions" :key="item.id" :value="item.id" :label="item.product_name"><span class="product-option"><span class="product-option-name" :title="item.product_name">{{ item.product_name }}</span><span class="product-option-spec" :title="item.specification || '暂无规格'">{{ item.specification || '暂无规格' }}</span></span></ElOption>
                          </ElSelect>
                        </ElFormItem>
                        <ElFormItem label="规格"><ElInput v-model="product.specification" aria-label="产品规格" placeholder="请输入规格" maxlength="2000" @input="editProductSpecification(product)" /></ElFormItem>
                        <ElFormItem label="产品类别 *"><ElSelect v-model="product.category_id" aria-label="产品类别" placeholder="选择产品类别"><ElOption v-if="product.category_id && !options?.categories.some(item => item.id === product.category_id)" :value="product.category_id" :label="sample.products?.[index]?.category_name || product.category_id" /><ElOption v-for="category in options?.categories" :key="category.id" :value="category.id" :label="category.category_name" /></ElSelect></ElFormItem>
                        <div class="dimensions-grid"><ElFormItem v-for="field in dimensions" :key="field.key" :label="field.label"><ElInput v-model="product[field.key]" :aria-label="field.label" inputmode="decimal" placeholder="选填" maxlength="11" /></ElFormItem></div>
                        <section v-for="(detail, detailIndex) in product.details" :key="detail.id" class="detail-fields" :data-detail-id="detail.id">
                          <h3 v-if="product.details.length > 1">颜色明细 {{ detailIndex + 1 }}</h3>
                          <ElFormItem label="颜色（色卡 / 颜色 / 色号） *"><ElSelect v-model="detail.product_color_id" filterable aria-label="产品颜色" placeholder="选择真实颜色" @change="selectColor(product, detail)"><ElOption v-if="detail.product_color_id && !options?.colors.some(item => item.id === detail.product_color_id)" :value="detail.product_color_id" :label="[savedDetail(product.id, detail.id)?.color_card, savedDetail(product.id, detail.id)?.color_name, detail.color_code].filter(Boolean).join(' / ') || '当前颜色'" /><ElOption v-for="color in options?.colors" :key="color.id" :value="color.id" :label="colorLabel(color.id)" /></ElSelect></ElFormItem>
                          <ElFormItem label="色号"><ElInput v-model="detail.color_code" aria-label="色号" maxlength="100" /></ElFormItem>
                          <ElFormItem label="公差"><ElSelect v-model="detail.tolerance" aria-label="公差"><ElOption v-if="!options?.tolerances.some(item => item.value === detail.tolerance)" :value="detail.tolerance" :label="savedDetail(product.id, detail.id)?.tolerance_display || detail.tolerance" /><ElOption v-for="item in options?.tolerances" :key="item.value" :value="item.value" :label="item.label" /></ElSelect></ElFormItem>
                          <ElFormItem label="产品备注"><ElInput v-model="detail.notes" aria-label="产品备注" maxlength="2000" /></ElFormItem>
                        </section>
                        <ElFormItem v-if="index === products.length - 1" label="特殊要求（选填）" class="requirements-field"><ElInput id="sample-purpose" v-model="purpose" aria-label="特殊要求" type="textarea" :rows="4" resize="none" maxlength="2000" show-word-limit placeholder="请输入颜色、包装或工艺要求" /></ElFormItem>
                      </section>
                    </div>
                  </div>
                </SampleSection>
                <div class="application-aside">
                  <SampleSection title="参考图片" class="upload-section">
                    <p class="field-label">参考图片（选填）</p>
                    <div v-if="imagePreview" class="reference-preview"><img :src="imagePreview" alt="已选择的参考图片" /><div v-if="canEditProducts" class="reference-image-actions"><ElUpload :key="uploadKey" :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png" :on-change="selectImage" :disabled="saving || materialsLoading || productRefreshing"><ElButton :disabled="saving || materialsLoading || productRefreshing">替换图片</ElButton></ElUpload></div></div>
                    <ElUpload v-else-if="canEditProducts" :key="uploadKey" drag :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png" :limit="1" :on-change="selectImage" :on-exceed="() => ElMessage.warning('最多选择一张参考图片。')" :disabled="saving || materialsLoading || productRefreshing"><img :src="uploadIcon" class="upload-icon" alt="" /><strong>上传参考图片</strong><span>支持 JPG、PNG，最多 1 张，单张不超过 5MB</span></ElUpload>
                    <div v-else class="reference-preview"><span class="field-hint">暂无参考图片</span></div>
                  </SampleSection>
                  <SampleSection title="打样数量" class="quantity-section">
                    <template v-for="(product, index) in products" :key="product.id">
                      <div v-for="(detail, detailIndex) in product.details" :key="detail.id" class="quantity-detail" :data-quantity-detail-id="detail.id">
                        <h3 v-if="products.length > 1 || product.details.length > 1">产品 {{ index + 1 }} · {{ product.product_name }} / 明细 {{ detailIndex + 1 }}{{ detail.color_code ? ` · ${detail.color_code}` : '' }}</h3>
                        <ElFormItem label="打样数量 *"><ElInputNumber v-model="detail.sample_quantity" aria-label="打样数量" :controls="false" :min="1" :max="2147483647" :precision="0" placeholder="请输入数量" /><span class="quantity-unit">PCS</span></ElFormItem>
                      </div>
                    </template>
                    <p class="field-hint">请输入大于 0 的整数。</p>
                  </SampleSection>
                </div>
              </div>
            </ElForm>
          </div>
        </section>
        <section v-show="activeTab === 'materials'" id="sample-materials-panel" role="tabpanel" aria-labelledby="sample-materials-tab">
          <div v-if="materialError" role="alert"><ElAlert :title="materialError" type="error" :closable="false" /><ElButton :disabled="saving || materialsLoading || productRefreshing" @click="loadMaterials({ preserveDraft: true })">重新加载材料</ElButton></div>
          <p v-if="!canEditMaterials" class="field-hint">{{ materialUnavailable }}</p>
          <p v-if="materials?.available && materials.isRevision" class="field-hint">保存修改仅更新当前材料资料，已提交的仓库、采购和领料记录保留原快照。</p>
          <p v-if="materials?.available && materials.noMaterials" class="field-hint">此申请已确认无需用料，新增材料只保存资料，不会重新启动供料流程。</p>
          <SampleMaterialEditor class="erp-table-editor" layout="sidebar" v-model="draft.lines" :units="units" :fullscreen="fullscreen" :unavailable-message="!canEditMaterials ? materialUnavailable : ''" :disabled="loading || saving || materialsLoading || productRefreshing || !canEditMaterials || Boolean(materialError)" @toggle-fullscreen="toggleFullscreen" @editing-change="editorOpen = $event" @dirty-change="editorDirty = $event" />
          <div class="card requirements erp-flat-form"><label for="sample-material-notes">需求备注（选填）</label><ElInput id="sample-material-notes" v-model="draft.notes" maxlength="2000" :disabled="saving || materialsLoading || productRefreshing || !canEditMaterials" /></div>
          <footer class="panel-actions"><template v-if="canEditMaterials"><ElButton v-if="canSubmitMaterials" :disabled="saving || materialsLoading || productRefreshing || editorOpen || Boolean(materialError)" @click="noMaterials">无需用料</ElButton><ElButton :type="canSubmitMaterials ? 'default' : 'primary'" :loading="saving" :disabled="saving || materialsLoading || productRefreshing || editorOpen || Boolean(materialError)" @click="submitMaterials(false)">保存材料</ElButton><ElButton v-if="canSubmitMaterials" type="primary" :loading="saving" :disabled="saving || materialsLoading || productRefreshing || editorOpen || Boolean(materialError)" @click="submitMaterials(true)">提交仓库</ElButton></template><ElButton v-else :disabled="saving" @click="router.push({ name: 'sample-detail', params: { sampleId: sample.id } })">查看流程进度</ElButton></footer>
        </section>
      </template>
    </section>
  </Teleport>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
@use 'sass:meta';
// 创建页样式仅加载到产品面板，避免影响材料页与其他页面。
.product-form-panel { @include meta.load-css('./sampleApplication'); }
// 候选项 Teleport 到 body，保留本组件 scoped 限制，不能再依赖产品面板祖先。
.product-option { display: flex; min-width: 0; align-items: center; gap: 16px; }
.product-option-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.product-option-spec { max-width: 65%; overflow: hidden; color: token.$crm-text-secondary; font-size: 12px; font-weight: 400; text-overflow: ellipsis; }
.sample-editor-page { min-width: 0; color: var(--erp-color-text-primary); }
.sample-editor-page .application-form :deep(.el-form-item__label) { height: 20px; margin-bottom: 4px; font-size: 12px; line-height: 20px; }
.sample-editor-page.is-fullscreen { position: fixed; z-index: 1900; inset: 0; padding: 16px; overflow: auto; box-sizing: border-box; background: var(--erp-color-subtle); }
.editor-heading { min-height: 44px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px 24px; margin-bottom: 14px; }
.title-line, .heading-actions { display: flex; align-items: center; gap: 14px; }
.title-line h1 { margin: 0; font-size: 26px; line-height: 38px; }
.title-line span, .field-hint { color: token.$crm-text-secondary; font-size: 13px; }
.editor-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 16px 0; }
.editor-tabs { display: flex; flex: none; gap: 24px; }
.editor-tabs button { height: 32px; padding: 0 4px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: token.$crm-text-secondary; font: inherit; font-size: 13px; line-height: 20px; cursor: pointer; }
.editor-tabs button:hover { background: token.$crm-color-subtle; }
.editor-tabs button[aria-selected='true'] { border-bottom-color: token.$crm-primary; color: token.$crm-primary; font-weight: 600; }
.editor-tabs button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.card { @include detail.surface; padding: 16px; margin-top: 16px; }
.product-form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 12px; }
.product-form-actions :deep(.el-button) { height: 32px; margin: 0; }
.product-form-actions .cancel-button { width: 110px; }
.product-form-actions .submit-button { width: 140px; }
.product-records { min-width: 0; }
.product-record + .product-record { margin-top: 20px; padding-top: 20px; border-top: 1px solid token.$crm-border-subtle; }
.product-record h3, .quantity-detail h3 { margin: 0; font-size: 13px; line-height: 22px; overflow-wrap: anywhere; }
.detail-fields { display: grid; min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; }
.detail-fields h3 { grid-column: 1 / -1; }
@media (max-width: 700px) { .detail-fields { grid-template-columns: 1fr; } .editor-toolbar { flex-wrap: wrap; } }
.quantity-detail + .quantity-detail { margin-top: 16px; }
.requirements label { display: block; margin-bottom: 12px; font-size: 13px; }
.requirements h2 { margin: 0 0 12px; font-size: 17px; line-height: 26px; }
.requirements p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.panel-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 16px; }
.sample-editor-page > :deep(.el-alert) { margin-bottom: 12px; }
</style>
