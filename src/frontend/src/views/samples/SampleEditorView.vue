<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchSample, fetchSampleFormOptions } from '@/api/samples'
import { completeSampleApplicationProducts, fetchSampleApplicationProductOptions } from '@/api/sampleApplication'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { confirmSampleNoMaterials, fetchSampleMaterials, fetchSampleMaterialUnits, saveSampleMaterials } from '@/api/sampleMaterials'
import SampleMaterialEditor from '@/components/samples/SampleMaterialEditor.vue'
import SampleMaterialApplicationInfo from '@/components/samples/SampleMaterialApplicationInfo.vue'
import SampleProductImage from '@/components/samples/SampleProductImage.vue'
import SampleFullscreenHeader from '@/components/samples/SampleFullscreenHeader.vue'
import { useSampleFullscreen } from '@/composables/useSampleFullscreen'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import { sampleMaterialError, validateSampleMaterials } from '@/utils/sampleMaterial'
import type { SampleDetail, SampleFormOptions } from '@/types/sample'
import type { SampleProductEdit, SampleProductCandidate } from '@/types/sampleEditor'
import type { SampleMaterialDraft, SampleMaterialLoadResult, SampleMaterialUnit } from '@/types/sampleMaterial'

const route = useRoute(), router = useRouter()
const root = ref<HTMLElement>()
const { fullscreen, toggleFullscreen } = useSampleFullscreen(root)
const activeTab = ref<'product' | 'materials'>('product')
const sample = ref<SampleDetail | null>(null), etag = ref('')
const loading = ref(true), saving = ref(false), productsLoading = ref(false)
const errorMessage = ref(''), actionError = ref(''), materialError = ref(''), successMessage = ref('')
const options = ref<SampleFormOptions | null>(null), productOptions = ref<SampleProductCandidate[]>([])
const productWindowVisible = ref(false), activeProductId = ref('')
const linkedProducts = new Map<string, { name: string; specification: string }>()
const products = ref<SampleProductEdit[]>([]), purpose = ref(''), initialProducts = ref('')
const materials = ref<SampleMaterialLoadResult | null>(null), units = ref<SampleMaterialUnit[]>([])
const draft = reactive<SampleMaterialDraft>({ lines: [], notes: '' }), initialMaterials = ref('')
const editorOpen = ref(false), editorDirty = ref(false)
let productRequest = 0
const dimensions = [
  { key: 'length_cm', label: '长（cm）' }, { key: 'armrest_width_cm', label: '扶手宽（cm）' },
  { key: 'seat_width_cm', label: '坐宽（cm）' }, { key: 'back_height_cm', label: '背高（cm）' }, { key: 'seat_height_cm', label: '坐高（cm）' },
] as const
const canEditProducts = computed(() => Boolean(sample.value?.application_actions?.is_application && sample.value.edit_capabilities?.can_complete))
const requirementsPending = computed(() => sample.value?.edit_capabilities?.mode === 'COMPLETE')
const canEditMaterials = computed(() => !requirementsPending.value && Boolean(materials.value?.available && materials.value.canEdit))
const productState = () => JSON.stringify({ products: products.value, purpose: purpose.value })
const productsDirty = computed(() => Boolean(initialProducts.value) && productState() !== initialProducts.value)
const materialsDirty = computed(() => editorDirty.value || Boolean(initialMaterials.value) && JSON.stringify(draft) !== initialMaterials.value)
useSampleUnsavedChanges(() => productsDirty.value || materialsDirty.value, '离开打样编辑页')
const materialUnavailable = computed(() => requirementsPending.value ? '请先完善并保存产品需求，再填写材料。' : materials.value && !materials.value.available ? materials.value.reason : '当前阶段或账号无材料编辑权限，材料需求只读。')

function applySample(result: { data: SampleDetail; etag: string }) {
  sample.value = result.data; etag.value = result.etag
  products.value = (result.data.products || []).map(product => ({
    id: product.id, product_id: product.product_id || '', category_id: product.category_id || '',
    product_name: product.product_name, specification: product.specification,
    length_cm: product.length_cm, armrest_width_cm: product.armrest_width_cm, seat_width_cm: product.seat_width_cm,
    back_height_cm: product.back_height_cm, seat_height_cm: product.seat_height_cm,
    details: product.details.map(detail => ({ id: detail.id, product_color_id: detail.product_color_id || '', color_code: detail.color_code,
      sample_quantity: detail.sample_quantity, tolerance: detail.tolerance, notes: detail.notes })),
  }))
  purpose.value = result.data.purpose
  linkedProducts.clear()
  for (const product of products.value) if (product.product_id) linkedProducts.set(product.id, { name: product.product_name, specification: product.specification })
  initialProducts.value = productState()
}
function applyMaterials(result: SampleMaterialLoadResult) {
  materials.value = result
  if (!result.available) return
  draft.lines = result.draft.lines.map(line => ({ ...line })); draft.notes = result.draft.notes
  initialMaterials.value = JSON.stringify(draft)
  etag.value = result.etag
  if (sample.value) { sample.value.status = result.status; sample.value.status_display = result.statusLabel }
}
async function loadMaterials() {
  materialError.value = ''
  if (!sample.value) return
  try {
    applyMaterials(await fetchSampleMaterials(sample.value.id))
    units.value = await fetchSampleMaterialUnits()
  } catch (error) { materialError.value = sampleMaterialError(error) }
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
  if (!id) { product.product_id = ''; linkedProducts.delete(product.id); return }
  const selected = productOptions.value.find(item => item.id === id)
  if (!selected) return
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
function openProductWindow(id: string) { activeProductId.value = id; productWindowVisible.value = true }
function colorLabel(id: string) {
  const color = options.value?.colors.find(item => item.id === id)
  return color ? `${color.color_card} / ${color.color_name} / ${color.color_code}` : ''
}
function selectColor(detail: SampleProductEdit['details'][number]) {
  detail.color_code = options.value?.colors.find(item => item.id === detail.product_color_id)?.color_code || ''
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
  if (!sample.value || !canEditProducts.value || saving.value) return
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
    applySample(await completeSampleApplicationProducts(sample.value.id, etag.value, payload, purpose.value))
    productWindowVisible.value = false
    successMessage.value = '产品需求已保存。材料需求尚未提交，请继续填写材料或确认无需用料。'
    // 产品与材料分次保存；第二步读取失败不覆盖第一步的成功，也不清除输入。
    await loadMaterials()
    activeTab.value = 'materials'
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
async function submitMaterials() {
  if (!sample.value || !canEditMaterials.value || saving.value || editorOpen.value || materialError.value) return
  actionError.value = ''; successMessage.value = ''
  const validation = validateSampleMaterials(draft, units.value)
  if (validation) { actionError.value = validation; return }
  saving.value = true
  try {
    applyMaterials(await saveSampleMaterials({ sampleId: sample.value.id, etag: etag.value,
      draft: { lines: draft.lines.map(line => ({ ...line })), notes: draft.notes }, submit: true }))
    successMessage.value = '材料需求已提交仓库。'
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
async function noMaterials() {
  if (!sample.value || !canEditMaterials.value || saving.value || editorOpen.value || materialError.value) return
  try { await ElMessageBox.confirm('确认本次打样无需用料？本页尚未提交的材料不会提交，确认后可进行生产和参数上传。', '确认无需用料', { confirmButtonText: '确认无需用料', cancelButtonText: '取消' }) }
  catch { return }
  saving.value = true; actionError.value = ''; successMessage.value = ''
  try {
    applyMaterials(await confirmSampleNoMaterials(sample.value.id, etag.value)); editorDirty.value = false
    successMessage.value = '已确认无需用料，可在详情中继续生产和参数上传。'
  } catch (error) { actionError.value = sampleMaterialError(error) }
  finally { saving.value = false }
}
onMounted(loadPage)
</script>

<template>
  <Teleport to="body" :disabled="!fullscreen">
    <section ref="root" class="sample-editor-page" :class="{ 'is-fullscreen': fullscreen }" aria-label="编辑打样需求" v-loading="loading">
      <SampleFullscreenHeader v-if="fullscreen" title="打样需求 · 全屏编辑" :subtitle="sample?.request_number || ''" @exit="toggleFullscreen" />
      <header v-else class="editor-heading">
        <div><div class="editor-breadcrumb">样品跟进 / 编辑打样需求</div><div class="title-line"><h1>{{ sample?.request_number || '打样需求' }}</h1><span>{{ sample?.status_display }}</span></div></div>
        <div class="heading-actions"><ElButton :disabled="saving" @click="router.push({ name: 'sample-detail', params: route.params })">查看详情</ElButton><ElButton :disabled="saving" @click="router.push({ name: 'samples' })">返回列表</ElButton></div>
      </header>
      <div v-if="errorMessage" role="alert"><ElAlert :title="errorMessage" type="error" :closable="false" /><ElButton @click="loadPage">重新加载</ElButton></div>
      <template v-else-if="sample">
        <ElAlert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon role="alert" />
        <ElAlert v-if="successMessage" :title="successMessage" type="success" :closable="false" show-icon role="status" />
        <nav class="editor-tabs" role="tablist" aria-label="打样编辑内容" @keydown="tabKeydown">
          <button id="sample-product-tab" type="button" role="tab" aria-controls="sample-product-panel" :aria-selected="activeTab === 'product'" :tabindex="activeTab === 'product' ? 0 : -1" @click="selectTab('product')">申请与产品</button>
          <button id="sample-materials-tab" type="button" role="tab" aria-controls="sample-materials-panel" :aria-selected="activeTab === 'materials'" :tabindex="activeTab === 'materials' ? 0 : -1" @click="selectTab('materials')">材料需求</button>
        </nav>
        <section v-show="activeTab === 'product'" id="sample-product-panel" role="tabpanel" aria-labelledby="sample-product-tab">
          <SampleMaterialApplicationInfo :sample="sample" />
          <article v-for="(product, index) in products" :key="product.id" class="card product-card">
            <header><h2>产品信息{{ products.length > 1 ? ` ${index + 1}` : '' }}</h2><ElButton plain @click="openProductWindow(product.id)">{{ canEditProducts ? '编辑产品信息' : '查看产品信息' }}</ElButton></header>
            <div class="product-overview">
              <SampleProductImage :src="sample.reference_image ? `/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/` : undefined" />
              <div class="product-details">
                <section><h3>产品属性</h3><dl>
                  <div><dt>产品名称</dt><dd>{{ product.product_name || '—' }}</dd></div><div><dt>产品规格</dt><dd>{{ product.specification || '—' }}</dd></div>
                  <div><dt>产品类别</dt><dd>{{ options?.categories.find(item => item.id === product.category_id)?.category_name || sample.products?.[index]?.category_name || '—' }}</dd></div>
                  <div><dt>产品关联</dt><dd>{{ product.product_id ? '已关联产品档案' : '自定义产品' }}</dd></div>
                </dl></section>
                <section><h3>产品尺寸</h3><dl><div v-for="field in dimensions" :key="field.key"><dt>{{ field.label }}</dt><dd>{{ product[field.key] || '—' }}</dd></div></dl></section>
                <section><h3>打样信息</h3><dl><template v-for="detail in product.details" :key="detail.id"><div><dt>颜色 / 色号</dt><dd>{{ colorLabel(detail.product_color_id) || sample.products?.[index]?.details.find(item => item.id === detail.id)?.color_name || '—' }} / {{ detail.color_code || '—' }}</dd></div><div><dt>打样数量</dt><dd class="quantity-value">{{ detail.sample_quantity ?? '—' }} PCS</dd></div><div><dt>产品备注</dt><dd>{{ detail.notes || '—' }}</dd></div></template></dl></section>
              </div>
            </div>
          </article>
          <div class="card requirements"><h2>打样要求</h2><p>{{ purpose || '—' }}</p><span v-if="productsDirty" class="field-hint">产品窗口的修改尚未保存。</span></div>
          <footer class="panel-actions"><span v-if="!canEditProducts">{{ requirementsPending ? '当前账号没有完善产品需求的权限。' : '按当前样品阶段展示产品资料。' }}</span><ElButton v-if="canEditProducts" type="primary" :loading="saving" :disabled="loading || saving || !options" @click="saveProducts">保存产品需求</ElButton></footer>
        </section>
        <AppWindowDialog v-model="productWindowVisible" :title="canEditProducts ? '编辑产品信息' : '产品信息'" width="760px" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
          <p class="field-hint">窗口内修改会保留在本页，保存产品需求后生效。</p>
          <ElAlert v-if="actionError" :title="actionError" type="error" :closable="false" role="alert" />
          <template v-for="(product, index) in products" :key="product.id">
              <ElForm v-if="product.id === activeProductId" label-position="top" :disabled="saving || !canEditProducts" class="product-fields">
                <ElFormItem label="关联产品（选填）"><ElSelect :model-value="product.product_id" clearable filterable remote :remote-method="searchProducts" :loading="productsLoading" :aria-label="`产品${index + 1}`" placeholder="可选择已有产品，也可手填名称和规格" @update:model-value="chooseProduct(product, $event)"><ElOption v-if="product.product_id && !productOptions.some(item => item.id === product.product_id)" :value="product.product_id" :label="product.product_name" /><ElOption v-for="item in productOptions" :key="item.id" :value="item.id" :label="`${item.product_name} · ${item.specification}`" /></ElSelect><span v-if="!product.product_id" class="field-hint">{{ product.product_name }}（自定义产品）</span></ElFormItem>
                <ElFormItem label="产品类别 *"><ElSelect v-model="product.category_id" aria-label="产品类别" placeholder="选择产品类别"><ElOption v-if="product.category_id && !options" :value="product.category_id" :label="sample.products?.[index]?.category_name || product.category_id" /><ElOption v-for="category in options?.categories" :key="category.id" :value="category.id" :label="category.category_name" /></ElSelect></ElFormItem>
                <ElFormItem label="产品名称 *"><ElInput v-model="product.product_name" aria-label="产品名称" maxlength="500" @input="clearProductLinkIfEdited(product)" /></ElFormItem><ElFormItem label="规格"><ElInput v-model="product.specification" aria-label="产品规格" maxlength="2000" @input="clearProductLinkIfEdited(product)" /></ElFormItem>
                <ElFormItem v-for="field in dimensions" :key="field.key" :label="field.label"><ElInput v-model="product[field.key]" :aria-label="field.label" inputmode="decimal" /></ElFormItem>
                <div v-for="detail in product.details" :key="detail.id" class="color-fields">
                  <ElFormItem label="颜色（色卡 / 颜色 / 色号） *"><ElSelect v-model="detail.product_color_id" filterable aria-label="产品颜色" placeholder="选择真实颜色" @change="selectColor(detail)"><ElOption v-if="detail.product_color_id && !options" :value="detail.product_color_id" :label="sample.products?.[index]?.details.find(item => item.id === detail.id)?.color_name || detail.product_color_id" /><ElOption v-for="color in options?.colors" :key="color.id" :value="color.id" :label="colorLabel(color.id)" /></ElSelect></ElFormItem>
                  <ElFormItem label="色号"><ElInput v-model="detail.color_code" aria-label="色号" maxlength="100" /></ElFormItem>
                  <ElFormItem label="打样数量（PCS） *"><ElInputNumber v-model="detail.sample_quantity" aria-label="打样数量" :min="1" :max="2147483647" :precision="0" :controls="false" /></ElFormItem>
                  <ElFormItem label="公差"><ElSelect v-model="detail.tolerance" aria-label="公差"><ElOption v-if="!options" :value="detail.tolerance" :label="sample.products?.[index]?.details.find(item => item.id === detail.id)?.tolerance_display || detail.tolerance" /><ElOption v-for="item in options?.tolerances" :key="item.value" :value="item.value" :label="item.label" /></ElSelect></ElFormItem>
                  <ElFormItem label="产品备注"><ElInput v-model="detail.notes" aria-label="产品备注" maxlength="2000" /></ElFormItem>
                </div>
              </ElForm>
          </template>
          <div class="requirements"><label for="sample-purpose">打样要求</label><ElInput id="sample-purpose" v-model="purpose" type="textarea" :rows="3" maxlength="2000" :disabled="saving || !canEditProducts" /></div>
          <template #footer><ElButton :disabled="saving" @click="productWindowVisible = false">返回概览</ElButton><ElButton v-if="canEditProducts" type="primary" :loading="saving" :disabled="saving || !options" @click="saveProducts">保存产品需求</ElButton></template>
        </AppWindowDialog>
        <section v-show="activeTab === 'materials'" id="sample-materials-panel" role="tabpanel" aria-labelledby="sample-materials-tab">
          <div v-if="materialError" role="alert"><ElAlert :title="materialError" type="error" :closable="false" /><ElButton :disabled="saving || materialsDirty" @click="loadMaterials">重新加载材料</ElButton></div>
          <p v-if="!canEditMaterials" class="field-hint">{{ materialUnavailable }}</p>
          <SampleMaterialEditor layout="sidebar" v-model="draft.lines" :units="units" :fullscreen="fullscreen" :unavailable-message="!canEditMaterials ? materialUnavailable : ''" :disabled="loading || saving || !canEditMaterials || Boolean(materialError)" @toggle-fullscreen="toggleFullscreen" @editing-change="editorOpen = $event" @dirty-change="editorDirty = $event" />
          <div class="card requirements"><label for="sample-material-notes">需求备注（选填）</label><ElInput id="sample-material-notes" v-model="draft.notes" maxlength="2000" :disabled="saving || !canEditMaterials" /></div>
          <footer class="panel-actions"><template v-if="canEditMaterials"><ElButton :disabled="saving || editorOpen || Boolean(materialError)" @click="noMaterials">无需用料</ElButton><ElButton type="primary" :loading="saving" :disabled="saving || editorOpen || Boolean(materialError)" @click="submitMaterials">提交仓库</ElButton></template><ElButton v-else :disabled="saving" @click="router.push({ name: 'sample-detail', params: { sampleId: sample.id } })">查看流程进度</ElButton></footer>
        </section>
      </template>
    </section>
  </Teleport>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.sample-editor-page { min-width: 0; color: var(--erp-color-text-primary); }
.sample-editor-page.is-fullscreen { position: fixed; z-index: 1900; inset: 0; padding: 16px; overflow: auto; box-sizing: border-box; background: var(--erp-color-subtle); }
.editor-heading { min-height: 44px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px 24px; margin-bottom: 14px; }
.editor-breadcrumb { margin-bottom: 4px; color: var(--erp-color-text-secondary); font-size: 12px; }
.title-line, .heading-actions { display: flex; align-items: center; gap: 14px; }
.title-line h1 { margin: 0; font-size: 26px; line-height: 38px; }
.title-line span, .field-hint { color: token.$crm-text-secondary; font-size: 13px; }
.editor-tabs { display: flex; gap: 24px; margin: 16px 0; }
.editor-tabs button { height: 32px; padding: 0 4px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: token.$crm-text-secondary; font: inherit; font-size: 13px; line-height: 20px; cursor: pointer; }
.editor-tabs button:hover { background: token.$crm-color-subtle; }
.editor-tabs button[aria-selected='true'] { border-bottom-color: token.$crm-primary; color: token.$crm-primary; font-weight: 600; }
.editor-tabs button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.card { @include detail.surface; padding: 16px; margin-top: 16px; }
.product-card > header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; }
.product-card h2 { margin: 0; font-size: 17px; line-height: 26px; }
.product-card > header span { font-size: 12px; color: token.$crm-text-secondary; }
.product-details { min-width: 0; }
.product-details section + section { margin-top: 16px; padding-top: 16px; border-top: 1px solid token.$crm-border-default; }
.product-details h3 { margin: 0 0 8px; font-size: 13px; font-weight: 600; line-height: 20px; }
.product-details dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin: 0; }
.product-details dl > div { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 8px; min-width: 0; font-size: 13px; line-height: 24px; }
.product-details dt { color: token.$crm-text-secondary; }
.product-details dd { margin: 0; color: token.$crm-text-primary; overflow-wrap: anywhere; }
.product-details .quantity-value { color: token.$crm-primary; font-weight: 600; }
.product-overview { display: grid; grid-template-columns: minmax(240px, 32%) minmax(0, 1fr); align-items: start; gap: 24px; margin-top: 16px; }
.sample-product-image { height: 260px; }
.product-fields, .color-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; min-width: 0; }
.product-fields :deep(.el-select), .product-fields :deep(.el-input-number) { width: 100%; }
.color-fields { grid-column: 1 / -1; border-top: 1px solid token.$crm-border-default; padding-top: 16px; }
.requirements label { display: block; margin-bottom: 12px; font-size: 13px; }
.requirements h2 { margin: 0 0 12px; font-size: 17px; line-height: 26px; }
.requirements p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.panel-actions { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 16px; }
.sample-editor-page > :deep(.el-alert) { margin-bottom: 12px; }
@media (max-width: 900px) { .product-overview { grid-template-columns: 1fr; } .sample-product-image { height: 200px; } }
@media (max-width: 600px) { .product-fields, .color-fields { grid-template-columns: 1fr; } }
</style>
