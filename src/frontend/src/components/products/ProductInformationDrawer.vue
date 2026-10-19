<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import {
  createProduct,
  fetchProduct,
  fetchProductOptions,
  updateProduct,
} from '@/api/products'
import type {
  ProductInformation,
  ProductInformationInput,
  ProductOptions,
} from '@/types/product'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  productId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [product: ProductInformation]
  closed: []
}>()

const formRef = ref<FormInstance>()
const drawerRoot = ref<HTMLElement>()
const loading = ref(false)
const optionsLoading = ref(false)
const saving = ref(false)
const detailError = ref('')
const optionsError = ref('')
const currentEtag = ref('')
const conflict = ref(false)
const missingVersion = ref(false)
const serverErrors = ref<Record<string, string>>({})
const localDraftBeforeReload = ref<ProductInformationInput | null>(null)
const loadedProduct = ref<ProductInformation | null>(null)
const options = ref<ProductOptions>({ categories: [], units: [], items: [] })
let requestId = 0
let suspendCategoryWatch = false
let initialSnapshot = ''

function emptyForm(): ProductInformationInput {
  return {
    product_number: '',
    product_code: '',
    category: '',
    product_name: '',
    specification: '',
    unit: '',
    product_item: '',
    warehouse_number: '',
    warehouse_name: '',
    scale: 'CUSTOM',
    status: 'ACTIVE',
  }
}

const form = reactive<ProductInformationInput>(emptyForm())
const title = computed(() => props.mode === 'create' ? '新增产品' : '编辑产品')
const drawerSize = computed(() => props.mode === 'create' ? '744px' : '748px')
const isDirty = computed(() => JSON.stringify(form) !== initialSnapshot)

const categoryOptions = computed(() => {
  const result = [...options.value.categories]
  const product = loadedProduct.value
  if (product && !result.some((item) => item.id === product.category)) {
    result.unshift({ id: product.category, category_name: `${product.category_name}（历史）` })
  }
  return result
})

const unitOptions = computed(() => {
  const result = [...options.value.units]
  const product = loadedProduct.value
  if (product && !result.some((item) => item.id === product.unit)) {
    result.unshift({ id: product.unit, unit_code: product.unit_code, unit_name: `${product.unit_name}（历史）` })
  }
  return result
})

const productItemOptions = computed(() => {
  if (!form.category) return []
  const result = options.value.items.filter((item) => item.category_id === form.category)
  const product = loadedProduct.value
  if (product && product.product_item === form.product_item && !result.some((item) => item.id === product.product_item)) {
    result.unshift({
      id: product.product_item,
      item_number: `${product.item_number}（历史：${product.item_category_name}）`,
      category_id: product.item_category_id,
      category_name: product.item_category_name,
    })
  }
  return result
})

const relationMismatch = computed(() => {
  const selected = productItemOptions.value.find((item) => item.id === form.product_item)
  return Boolean(selected && form.category && selected.category_id !== form.category)
})
const preservesHistoricalMismatch = computed(() => {
  const product = loadedProduct.value
  return props.mode === 'edit' && Boolean(
    product
    && product.category_item_mismatch
    && form.category === product.category
    && form.product_item === product.product_item,
  )
})

const rules: FormRules<ProductInformationInput> = {
  product_number: [{ required: true, message: '请输入品号', trigger: 'blur' }],
  category: [{ required: true, message: '请选择产品类别', trigger: 'change' }],
  product_name: [{ required: true, message: '请输入品名', trigger: 'blur' }],
  specification: [{ required: true, message: '请输入规格', trigger: 'blur' }],
  unit: [{ required: true, message: '请选择单位', trigger: 'change' }],
  product_item: [{ required: true, message: '请选择货号', trigger: 'change' }],
  scale: [{ required: true, message: '请选择规模', trigger: 'change' }],
  status: [{ required: true, message: '请选择状态', trigger: 'change' }],
}

function responseDetails(error: unknown): {
  status?: number
  message?: string
  fields?: Record<string, string[]>
} {
  const response = (error as {
    response?: {
      status?: number
      data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
    }
  })?.response
  return {
    status: response?.status,
    message: response?.data?.error?.message || response?.data?.detail,
    fields: response?.data?.error?.field_errors,
  }
}

function fieldError(field: keyof ProductInformationInput): string {
  return serverErrors.value[field] || ''
}

function focusFirstError(): void {
  void nextTick(() => {
    drawerRoot.value?.querySelector<HTMLElement>('.el-form-item.is-error input, .el-form-item.is-error .el-select__wrapper')?.focus()
  })
}

function assignProduct(product: ProductInformation, etag: string): void {
  suspendCategoryWatch = true
  loadedProduct.value = product
  currentEtag.value = etag
  Object.assign(form, {
    product_number: product.product_number,
    product_code: product.product_code,
    category: product.category,
    product_name: product.product_name,
    specification: product.specification,
    unit: product.unit,
    product_item: product.product_item,
    warehouse_number: product.warehouse_number,
    warehouse_name: product.warehouse_name,
    scale: product.scale,
    status: product.status,
  })
  initialSnapshot = JSON.stringify(form)
  nextTick(() => {
    formRef.value?.clearValidate()
    suspendCategoryWatch = false
  })
}

async function loadOptions(activeRequest: number): Promise<void> {
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const response = await fetchProductOptions()
    if (activeRequest === requestId) options.value = response
  } catch {
    if (activeRequest === requestId) optionsError.value = '类别、单位和货号选项加载失败，请重试。'
  } finally {
    if (activeRequest === requestId) optionsLoading.value = false
  }
}

async function loadDrawer(preserveDraft = false): Promise<void> {
  const activeRequest = ++requestId
  if (!preserveDraft) localDraftBeforeReload.value = null
  loading.value = props.mode === 'edit'
  detailError.value = ''
  conflict.value = false
  missingVersion.value = false
  serverErrors.value = {}
  loadedProduct.value = null
  currentEtag.value = ''
  suspendCategoryWatch = true
  Object.assign(form, emptyForm())
  initialSnapshot = JSON.stringify(form)
  suspendCategoryWatch = false

  const optionsRequest = loadOptions(activeRequest)
  if (props.mode === 'edit') {
    if (!props.productId) {
      detailError.value = '缺少产品记录编号，无法读取编辑资料。'
      loading.value = false
      return
    }
    try {
      const response = await fetchProduct(props.productId)
      if (activeRequest === requestId) assignProduct(response.data, response.etag)
    } catch {
      if (activeRequest === requestId) detailError.value = '产品详情加载失败，本次没有沿用上一条记录。'
    } finally {
      if (activeRequest === requestId) loading.value = false
    }
  }
  await optionsRequest
}

async function save(): Promise<void> {
  if (!formRef.value || saving.value || loading.value || detailError.value) return
  serverErrors.value = {}
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    focusFirstError()
    return
  }
  if (relationMismatch.value && !preservesHistoricalMismatch.value) {
    serverErrors.value = { product_item: '货号必须属于所选产品类别。' }
    focusFirstError()
    return
  }
  if (saving.value) return

  const payload: ProductInformationInput = {
    product_number: form.product_number.trim(),
    product_code: form.product_code.trim(),
    category: form.category,
    product_name: form.product_name.trim(),
    specification: form.specification.trim(),
    unit: form.unit,
    product_item: form.product_item,
    warehouse_number: form.warehouse_number.trim(),
    warehouse_name: form.warehouse_name.trim(),
    scale: form.scale,
    status: form.status,
  }

  saving.value = true
  conflict.value = false
  missingVersion.value = false
  try {
    const response = props.mode === 'edit' && props.productId
      ? await updateProduct(props.productId, payload, currentEtag.value)
      : await createProduct(payload)
    initialSnapshot = JSON.stringify(form)
    localDraftBeforeReload.value = null
    ElMessage.success(props.mode === 'edit' ? '产品信息已更新' : '产品信息已新增')
    emit('saved', response.data)
    emit('update:modelValue', false)
  } catch (error) {
    const details = responseDetails(error)
    serverErrors.value = Object.fromEntries(
      Object.entries(details.fields || {}).map(([key, messages]) => [key, messages[0] || '填写不正确']),
    )
    if (details.status === 412) {
      conflict.value = true
      ElMessage.error('该产品已被其他人修改，本次内容未保存。')
    } else if (details.status === 428) {
      missingVersion.value = true
      ElMessage.error('缺少数据版本，本次内容未保存。')
    } else {
      ElMessage.error(details.message || Object.values(serverErrors.value)[0] || '产品信息保存失败，输入内容已保留。')
    }
    focusFirstError()
  } finally {
    saving.value = false
  }
}

async function reloadLatest(): Promise<void> {
  const recovery = {
    form: { ...form }, etag: currentEtag.value, loaded: loadedProduct.value,
    snapshot: initialSnapshot, conflict: conflict.value, missingVersion: missingVersion.value,
  }
  localDraftBeforeReload.value = { ...form }
  await loadDrawer(true)
  if (detailError.value) {
    const failure = detailError.value
    suspendCategoryWatch = true
    Object.assign(form, recovery.form)
    currentEtag.value = recovery.etag
    loadedProduct.value = recovery.loaded
    initialSnapshot = recovery.snapshot
    conflict.value = recovery.conflict
    missingVersion.value = recovery.missingVersion
    detailError.value = ''
    localDraftBeforeReload.value = null
    void nextTick(() => { suspendCategoryWatch = false })
    ElMessage.error(`${failure} 本地草稿已恢复，请稍后重试。`)
    return
  }
  ElMessage.info('已读取最新资料；可恢复旧草稿进行对照，本次不会自动保存。')
}

function restoreDraft(): void {
  if (!localDraftBeforeReload.value) return
  suspendCategoryWatch = true
  Object.assign(form, localDraftBeforeReload.value)
  localDraftBeforeReload.value = null
  void nextTick(() => {
    formRef.value?.clearValidate()
    suspendCategoryWatch = false
  })
  ElMessage.info('已恢复旧草稿，请核对服务器最新版本后再保存。')
}

async function confirmDiscard(): Promise<boolean> {
  if (!isDirty.value && !localDraftBeforeReload.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，确定放弃并关闭吗？', '放弃修改', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

async function canLeave(): Promise<boolean> {
  if (saving.value) {
    ElMessage.warning('产品信息正在保存，请等待请求完成后再离开。')
    return false
  }
  return confirmDiscard()
}

async function requestClose(): Promise<void> {
  if (!await canLeave()) return
  initialSnapshot = JSON.stringify(form)
  emit('update:modelValue', false)
}

async function beforeClose(done: () => void): Promise<void> {
  if (!await canLeave()) return
  initialSnapshot = JSON.stringify(form)
  done()
}

watch(
  () => [props.modelValue, props.mode, props.productId] as const,
  ([visible]) => {
    if (visible) void loadDrawer()
    else { requestId += 1; localDraftBeforeReload.value = null }
  },
  { immediate: true },
)

watch(
  () => form.category,
  (category) => {
    if (suspendCategoryWatch || !form.product_item) return
    const selected = options.value.items.find((item) => item.id === form.product_item)
    if (selected && selected.category_id !== category) form.product_item = ''
  },
)

defineExpose({ hasUnsavedChanges: isDirty, confirmDiscard, canLeave })
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    :title="title"
    :width="drawerSize"
    height="auto"
    destroy-on-close
    class="product-information-dialog"
    :before-close="beforeClose"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @closed="emit('closed')"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div ref="drawerRoot" class="drawer-content" :aria-busy="loading || optionsLoading">
      <p class="dialog-subtitle">{{ mode === 'create' ? '建立可供生产任务与 BOM 引用的成品资料。' : '修改当前产品资料；保存时会校验数据版本。' }}</p>
      <div v-if="detailError" class="drawer-state" role="alert">
        <strong>{{ detailError }}</strong>
        <ElButton @click="loadDrawer">重新读取</ElButton>
      </div>
      <template v-else>
        <ElAlert v-if="optionsError" :title="optionsError" type="error" :closable="false" show-icon>
          <template #default><ElButton link type="primary" @click="loadOptions(requestId)">重试选项</ElButton></template>
        </ElAlert>
        <ElAlert
          v-if="relationMismatch"
          title="当前历史类别与货号不匹配；两个关联均不修改时可保留，主动修改后必须重新匹配。"
          type="warning"
          :closable="false"
          show-icon
        />
        <ElAlert v-if="conflict || missingVersion" type="warning" :closable="false" show-icon>
          <template #title>{{ conflict ? '数据已被其他人更新，本次未保存。' : '缺少数据版本，本次未保存。' }}</template>
          <template #default><ElButton link type="primary" @click="reloadLatest">重新读取最新资料</ElButton></template>
        </ElAlert>
        <ElAlert
          v-if="localDraftBeforeReload"
          title="已读取服务器最新资料，旧草稿尚未保存。"
          type="info"
          :closable="false"
          show-icon
        >
          <template #default><ElButton link type="primary" @click="restoreDraft">恢复旧草稿</ElButton></template>
        </ElAlert>

        <ElForm
          ref="formRef"
          v-loading="loading"
          :model="form"
          :rules="rules"
          label-position="top"
          class="product-form"
          :disabled="saving || loading"
        >
          <section class="form-section">
            <h3><span>1</span>基本识别</h3>
            <div class="form-grid">
              <ElFormItem label="品号" prop="product_number" required :error="fieldError('product_number')">
                <ElInput v-model="form.product_number" maxlength="100" placeholder="请输入唯一品号" />
              </ElFormItem>
              <ElFormItem label="类型" required>
                <ElInput model-value="成品" disabled />
              </ElFormItem>
              <ElFormItem label="产品编码" prop="product_code" :error="fieldError('product_code')">
                <ElInput v-model="form.product_code" maxlength="100" placeholder="可选；填写后必须唯一" />
                <small>产品编码可不填，填写后须唯一。</small>
              </ElFormItem>
              <ElFormItem label="品名" prop="product_name" required :error="fieldError('product_name')">
                <ElInput v-model="form.product_name" maxlength="200" placeholder="请输入品名" />
              </ElFormItem>
            </div>
          </section>

          <section class="form-section">
            <h3><span>2</span>产品归类</h3>
            <div class="form-grid">
              <ElFormItem label="类别" prop="category" required :error="fieldError('category')">
                <ElSelect v-model="form.category" filterable placeholder="请选择成品类别">
                  <ElOption v-for="item in categoryOptions" :key="item.id" :label="item.category_name" :value="item.id" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem label="货号" prop="product_item" required :error="fieldError('product_item')">
                <ElSelect v-model="form.product_item" filterable :disabled="!form.category" placeholder="请先选择类别">
                  <ElOption v-for="item in productItemOptions" :key="item.id" :label="item.item_number" :value="item.id" />
                </ElSelect>
                <small>类别与货号关联，请先选择类别。</small>
              </ElFormItem>
              <ElFormItem label="规格" prop="specification" required :error="fieldError('specification')">
                <ElInput v-model="form.specification" maxlength="300" placeholder="请输入规格" />
              </ElFormItem>
              <ElFormItem label="单位" prop="unit" required :error="fieldError('unit')">
                <ElSelect v-model="form.unit" filterable placeholder="请选择单位">
                  <ElOption v-for="item in unitOptions" :key="item.id" :label="item.unit_name" :value="item.id" />
                </ElSelect>
              </ElFormItem>
            </div>
          </section>

          <section class="form-section">
            <h3><span>3</span>存放与属性</h3>
            <div class="form-grid">
              <ElFormItem label="仓库号" prop="warehouse_number" :error="fieldError('warehouse_number')">
                <ElInput v-model="form.warehouse_number" maxlength="100" placeholder="请输入仓库号" />
              </ElFormItem>
              <ElFormItem label="仓库名称" prop="warehouse_name" :error="fieldError('warehouse_name')">
                <ElInput v-model="form.warehouse_name" maxlength="150" placeholder="请输入仓库名称" />
              </ElFormItem>
              <ElFormItem label="规模" prop="scale" required :error="fieldError('scale')">
                <ElSelect v-model="form.scale"><ElOption label="定制" value="CUSTOM" /><ElOption label="常规" value="REGULAR" /></ElSelect>
              </ElFormItem>
              <ElFormItem label="状态" prop="status" required :error="fieldError('status')">
                <ElSelect v-model="form.status"><ElOption label="正常" value="ACTIVE" /><ElOption label="废弃" value="INACTIVE" /></ElSelect>
              </ElFormItem>
            </div>
          </section>
        </ElForm>
      </template>
    </div>

    <template #footer>
      <ElButton :disabled="saving" @click="requestClose">取消</ElButton>
      <ElButton type="primary" :loading="saving" :disabled="loading || Boolean(detailError)" @click="save">
        {{ mode === 'create' ? '保存产品' : '保存修改' }}
      </ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

:global(.product-information-dialog.app-window-dialog) {
  max-width: calc(100vw - 32px);
  background: token.$crm-color-surface;
}
:global(.product-information-dialog .app-window-dialog__body) { padding: 0 24px; }
:global(.product-information-dialog .app-window-dialog__footer) { min-height: 60px; display: flex; justify-content: flex-end; gap: 8px; padding: 10px 24px; background: token.$crm-color-surface; }
:global(.product-information-dialog .app-window-dialog__footer .el-button) { width: 108px; height: 36px; border-radius: token.$crm-radius-2; }
:global(.product-information-dialog .app-window-dialog__footer .el-button--primary) { width: 132px; }
.dialog-subtitle { margin: 14px 0 0; color: token.$crm-text-secondary; font: 12px/18px token.$crm-font-body; }
.drawer-content { display: flow-root; }
.drawer-content > .el-alert { margin: 12px 0; }
.drawer-state { min-height: 360px; display: grid; place-content: center; justify-items: center; gap: 16px; color: token.$crm-text-secondary; }
.product-form { padding: 4px 0 12px; }
.form-section { padding-top: 5px; }
.form-section + .form-section { margin-top: 4px; }
.form-section h3 { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; color: token.$crm-text-primary; font: 700 17px/24px token.$crm-font-display; }
.form-section h3::after { height: 1px; flex: 1; content: ''; background: token.$crm-border-subtle; }
.form-section h3 span { width: 18px; height: 18px; display: grid; place-items: center; border-radius: 50%; color: token.$crm-text-inverse; background: token.$crm-neutral; font: 11px/1 token.$crm-font-body; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 22px; }
.product-form :deep(.el-form-item) { margin-bottom: 8px; }
.product-form :deep(.el-form-item__label) { height: 20px; padding: 0 0 3px; color: token.$crm-text-primary; font: 12px/17px token.$crm-font-body; }
.product-form :deep(.el-input__wrapper), .product-form :deep(.el-select__wrapper) { height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
.product-form :deep(.el-form-item__error) { position: static; padding-top: 2px; line-height: 14px; }
.product-form :deep(.el-select) { width: 100%; }
.product-form small { display: block; margin-top: 2px; color: token.$crm-text-muted; font: 10px/14px token.$crm-font-body; }
</style>
