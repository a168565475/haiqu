<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import {
  createRawMaterial,
  fetchRawMaterial,
  fetchRawMaterialOptions,
  updateRawMaterial,
} from '@/api/rawMaterials'
import type {
  RawMaterialBoxShape,
  RawMaterialInformation,
  RawMaterialInput,
  RawMaterialItemType,
  RawMaterialOptions,
  RawMaterialWarehouseOption,
} from '@/types/rawMaterial'

interface RawMaterialFormState {
  material_number: string
  item_type: RawMaterialItemType | ''
  category: string
  material_name: string
  specification: string
  unit: string
  color: string
  material: string
  is_packaging_auxiliary: boolean
  box_shape: RawMaterialBoxShape | ''
  notes: string
  warehouse_key: string
}

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  materialId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [material: RawMaterialInformation]
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
const localDraftBeforeReload = ref<{
  form: RawMaterialFormState
  colorTouched: boolean
  legacyColorLabel: string
} | null>(null)
const loadedMaterial = ref<RawMaterialInformation | null>(null)
const legacyColorLabel = ref('')
const options = ref<RawMaterialOptions>({
  item_types: [], categories: [], units: [], colors: [], warehouses: [], box_shapes: [],
})
const LEGACY_COLOR_VALUE = '__legacy_color__'
let requestId = 0
let suspendFormWatch = false
let colorTouched = false
let initialSnapshot = ''

function emptyForm(): RawMaterialFormState {
  return {
    material_number: '', item_type: '', category: '', material_name: '', specification: '',
    unit: '', color: '', material: '', is_packaging_auxiliary: false, box_shape: '', notes: '', warehouse_key: '',
  }
}

function warehouseKey(item: RawMaterialWarehouseOption): string {
  return JSON.stringify([item.warehouse_number, item.warehouse_name])
}

const form = reactive<RawMaterialFormState>(emptyForm())
const title = computed(() => props.mode === 'create' ? '新增原料' : '编辑原料')
const drawerSize = computed(() => props.mode === 'create' ? '896px' : '923px')
const isDirty = computed(() => JSON.stringify(form) !== initialSnapshot)
const categoryOptions = computed(() => {
  const result = options.value.categories.filter((item) => item.item_type === form.item_type)
  const material = loadedMaterial.value
  if (material && material.item_type === form.item_type && !result.some((item) => item.id === material.category)) {
    result.unshift({ id: material.category, item_type: material.item_type, category_name: `${material.category_name}（历史）` })
  }
  return result
})
const unitOptions = computed(() => {
  const result = [...options.value.units]
  const material = loadedMaterial.value
  if (material && !result.some((item) => item.id === material.unit)) {
    result.unshift({ id: material.unit, unit_code: material.unit_code, unit_name: `${material.unit_name}（历史）` })
  }
  return result
})
const colorOptions = computed(() => {
  const result = [...options.value.colors]
  const material = loadedMaterial.value
  if (material?.color && !result.some((item) => item.id === material.color)) {
    result.unshift({ id: material.color, color_card: '', color_code: '', color_name: material.color_name, label: `${material.color_label || material.color_name}（历史）` })
  }
  return result
})
const selectableWarehouses = computed(() => {
  const result = [...options.value.warehouses]
  const material = loadedMaterial.value
  if (material) {
    const current = { warehouse_number: material.warehouse_number, warehouse_name: material.warehouse_name }
    if (!result.some((item) => warehouseKey(item) === warehouseKey(current))) result.unshift(current)
  }
  return result
})
const isPackagingCategory = computed(() => {
  const selected = categoryOptions.value.find((item) => item.id === form.category)
  return form.item_type === 'MATERIAL' && selected?.category_name.replace('（历史）', '') === '包材'
})

const rules: FormRules<RawMaterialFormState> = {
  material_number: [{ required: true, message: '请输入品号', trigger: 'blur' }],
  item_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  category: [{ required: true, message: '请选择类别', trigger: 'change' }],
  material_name: [{ required: true, message: '请输入品名', trigger: 'blur' }],
  specification: [{ required: true, message: '请输入规格', trigger: 'blur' }],
  unit: [{ required: true, message: '请选择单位', trigger: 'change' }],
  warehouse_key: [{ required: true, message: '请选择仓库名称', trigger: 'change' }],
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

function fieldError(field: keyof RawMaterialFormState): string {
  if (field === 'warehouse_key') return serverErrors.value.warehouse_name || serverErrors.value.warehouse_number || ''
  return serverErrors.value[field] || ''
}

function focusFirstError(): void {
  void nextTick(() => {
    drawerRoot.value?.querySelector<HTMLElement>('.el-form-item.is-error input, .el-form-item.is-error textarea, .el-form-item.is-error .el-select__wrapper')?.focus()
  })
}

function assignMaterial(material: RawMaterialInformation, etag: string): void {
  suspendFormWatch = true
  loadedMaterial.value = material
  legacyColorLabel.value = material.has_legacy_color ? material.color_name : ''
  currentEtag.value = etag
  Object.assign(form, {
    material_number: material.material_number,
    item_type: material.item_type,
    category: material.category,
    material_name: material.material_name,
    specification: material.specification,
    unit: material.unit,
    color: material.color || (material.has_legacy_color ? LEGACY_COLOR_VALUE : ''),
    material: material.material,
    is_packaging_auxiliary: material.is_packaging_auxiliary,
    box_shape: material.box_shape,
    notes: material.notes,
    warehouse_key: warehouseKey(material),
  })
  colorTouched = false
  initialSnapshot = JSON.stringify(form)
  nextTick(() => {
    formRef.value?.clearValidate()
    suspendFormWatch = false
  })
}

async function loadOptions(activeRequest: number): Promise<void> {
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const response = await fetchRawMaterialOptions()
    if (activeRequest === requestId) options.value = response
  } catch {
    if (activeRequest === requestId) optionsError.value = '类别、单位、颜色和仓库选项加载失败，请重试。'
  } finally {
    if (activeRequest === requestId) optionsLoading.value = false
  }
}

async function loadDrawer(preserveDraft = false): Promise<void> {
  const activeRequest = ++requestId
  if (!preserveDraft) localDraftBeforeReload.value = null
  loading.value = props.mode === 'edit'
  detailError.value = ''
  optionsError.value = ''
  conflict.value = false
  missingVersion.value = false
  serverErrors.value = {}
  loadedMaterial.value = null
  legacyColorLabel.value = ''
  currentEtag.value = ''
  suspendFormWatch = true
  Object.assign(form, emptyForm())
  colorTouched = false
  initialSnapshot = JSON.stringify(form)
  suspendFormWatch = false

  const optionsRequest = loadOptions(activeRequest)
  if (props.mode === 'edit') {
    if (!props.materialId) {
      detailError.value = '缺少原料记录编号，无法读取编辑资料。'
      loading.value = false
      return
    }
    try {
      const response = await fetchRawMaterial(props.materialId)
      if (activeRequest === requestId) assignMaterial(response.data, response.etag)
    } catch {
      if (activeRequest === requestId) detailError.value = '原料详情加载失败，本次没有沿用上一条记录。'
    } finally {
      if (activeRequest === requestId) loading.value = false
    }
  }
  await optionsRequest
}

function selectedWarehouse(): RawMaterialWarehouseOption | undefined {
  return selectableWarehouses.value.find((item) => warehouseKey(item) === form.warehouse_key)
}

async function save(): Promise<void> {
  if (!formRef.value || saving.value || loading.value || detailError.value) return
  serverErrors.value = {}
  const valid = await formRef.value.validate().catch(() => false)
  const warehouse = selectedWarehouse()
  if (!valid || !form.item_type || !warehouse) {
    if (!warehouse) serverErrors.value = { warehouse_name: '请选择有效的仓库编号与名称组合。' }
    focusFirstError()
    return
  }
  if (saving.value) return

  const payload: RawMaterialInput = {
    material_number: form.material_number.trim(),
    item_type: form.item_type,
    category: form.category,
    material_name: form.material_name.trim(),
    specification: form.specification.trim(),
    unit: form.unit,
    material: form.material.trim(),
    is_packaging_auxiliary: isPackagingCategory.value ? form.is_packaging_auxiliary : false,
    box_shape: isPackagingCategory.value ? form.box_shape : '',
    notes: form.notes,
    warehouse_number: warehouse.warehouse_number,
    warehouse_name: warehouse.warehouse_name,
  }
  const isLegacyUnchanged = props.mode === 'edit' && !colorTouched && form.color === LEGACY_COLOR_VALUE
  if (!isLegacyUnchanged) payload.color = form.color && form.color !== LEGACY_COLOR_VALUE ? form.color : null

  saving.value = true
  conflict.value = false
  missingVersion.value = false
  try {
    const response = props.mode === 'edit' && props.materialId
      ? await updateRawMaterial(props.materialId, payload, currentEtag.value)
      : await createRawMaterial(payload)
    initialSnapshot = JSON.stringify(form)
    localDraftBeforeReload.value = null
    ElMessage.success(props.mode === 'edit' ? '原料信息已更新' : '原料信息已新增')
    emit('saved', response.data)
    emit('update:modelValue', false)
  } catch (error) {
    const details = responseDetails(error)
    serverErrors.value = Object.fromEntries(
      Object.entries(details.fields || {}).map(([key, messages]) => [key, messages[0] || '填写不正确']),
    )
    if (details.status === 412) {
      conflict.value = true
      ElMessage.error('该原料已被其他人修改，本次内容未保存。')
    } else if (details.status === 428) {
      missingVersion.value = true
      ElMessage.error('缺少数据版本，本次内容未保存。')
    } else {
      ElMessage.error(details.message || Object.values(serverErrors.value)[0] || '原料信息保存失败，输入内容已保留。')
    }
    focusFirstError()
  } finally {
    saving.value = false
  }
}

async function reloadLatest(): Promise<void> {
  const recovery = {
    form: { ...form }, colorTouched, legacyColorLabel: legacyColorLabel.value,
    etag: currentEtag.value, loaded: loadedMaterial.value,
    snapshot: initialSnapshot, conflict: conflict.value, missingVersion: missingVersion.value,
  }
  localDraftBeforeReload.value = {
    form: { ...form }, colorTouched, legacyColorLabel: legacyColorLabel.value,
  }
  await loadDrawer(true)
  if (detailError.value) {
    const failure = detailError.value
    suspendFormWatch = true
    Object.assign(form, recovery.form)
    colorTouched = recovery.colorTouched
    legacyColorLabel.value = recovery.legacyColorLabel
    currentEtag.value = recovery.etag
    loadedMaterial.value = recovery.loaded
    initialSnapshot = recovery.snapshot
    conflict.value = recovery.conflict
    missingVersion.value = recovery.missingVersion
    detailError.value = ''
    localDraftBeforeReload.value = null
    void nextTick(() => { suspendFormWatch = false })
    ElMessage.error(`${failure} 本地草稿已恢复，请稍后重试。`)
    return
  }
  ElMessage.info('已读取最新资料；可恢复旧草稿进行对照，本次不会自动保存。')
}

function restoreDraft(): void {
  const draft = localDraftBeforeReload.value
  if (!draft) return
  suspendFormWatch = true
  Object.assign(form, draft.form)
  colorTouched = draft.colorTouched
  legacyColorLabel.value = draft.legacyColorLabel
  localDraftBeforeReload.value = null
  void nextTick(() => {
    formRef.value?.clearValidate()
    suspendFormWatch = false
  })
  ElMessage.info('已恢复旧草稿，请核对服务器最新版本后再保存。')
}

async function confirmDiscard(): Promise<boolean> {
  if (!isDirty.value && !localDraftBeforeReload.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，确定放弃并关闭吗？', '放弃修改', {
      confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

async function canLeave(): Promise<boolean> {
  if (saving.value) {
    ElMessage.warning('原料信息正在保存，请等待请求完成后再离开。')
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
  () => [props.modelValue, props.mode, props.materialId] as const,
  ([visible]) => {
    if (visible) void loadDrawer()
    else { requestId += 1; localDraftBeforeReload.value = null }
  },
  { immediate: true },
)

watch(
  () => form.item_type,
  (itemType) => {
    if (suspendFormWatch) return
    const selected = options.value.categories.find((item) => item.id === form.category)
    if (form.category && (!selected || selected.item_type !== itemType)) form.category = ''
    form.is_packaging_auxiliary = false
    form.box_shape = ''
  },
)

watch(
  () => form.category,
  () => {
    if (suspendFormWatch || isPackagingCategory.value) return
    form.is_packaging_auxiliary = false
    form.box_shape = ''
  },
)

watch(
  () => form.color,
  () => {
    if (!suspendFormWatch) colorTouched = true
  },
)

defineExpose({ hasUnsavedChanges: isDirty, confirmDiscard, canLeave })
</script>

<template>
  <ElDrawer
    :model-value="modelValue"
    :size="drawerSize"
    :modal="false"
    append-to-body
    destroy-on-close
    class="raw-material-information-drawer"
    :before-close="beforeClose"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @closed="emit('closed')"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="drawer-heading">
        <h2>{{ title }}</h2>
        <p>{{ mode === 'create' ? '类别随类型联动，包材专属字段仅在包材类别显示。' : '修改当前原料资料；保存时会校验数据版本。' }}</p>
      </div>
    </template>

    <div ref="drawerRoot" class="drawer-content" :aria-busy="loading || optionsLoading">
      <div v-if="detailError" class="drawer-state" role="alert">
        <strong>{{ detailError }}</strong>
        <ElButton @click="loadDrawer">重新读取</ElButton>
      </div>
      <template v-else>
        <ElAlert v-if="optionsError" :title="optionsError" type="error" :closable="false" show-icon>
          <template #default><ElButton link type="primary" @click="loadOptions(requestId)">重试选项</ElButton></template>
        </ElAlert>
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
          class="raw-form"
          :disabled="saving || loading"
        >
          <section class="form-section">
            <h3>基本识别</h3>
            <div class="form-grid">
              <ElFormItem label="品号" prop="material_number" required :error="fieldError('material_number')">
                <ElInput v-model="form.material_number" maxlength="100" placeholder="请输入唯一品号" />
              </ElFormItem>
              <ElFormItem label="类型" prop="item_type" required :error="fieldError('item_type')">
                <ElSelect v-model="form.item_type" placeholder="请选择类型">
                  <ElOption v-for="item in options.item_types" :key="item.value" :label="item.label" :value="item.value" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem label="类别" prop="category" required :error="fieldError('category')">
                <ElSelect v-model="form.category" filterable :disabled="!form.item_type" placeholder="请先选择类型">
                  <ElOption v-for="item in categoryOptions" :key="item.id" :label="item.category_name" :value="item.id" />
                </ElSelect>
                <small>类别随类型联动，包材专属字段仅在包材类别显示。</small>
              </ElFormItem>
              <ElFormItem label="品名" prop="material_name" required :error="fieldError('material_name')">
                <ElInput v-model="form.material_name" maxlength="200" placeholder="请输入品名" />
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
            <h3>材质与存放</h3>
            <div class="form-grid">
              <ElFormItem label="颜色" prop="color" :error="fieldError('color')">
                <ElSelect v-model="form.color" clearable filterable placeholder="请选择颜色">
                  <ElOption
                    v-if="legacyColorLabel && form.color === LEGACY_COLOR_VALUE"
                    :label="legacyColorLabel === '/' ? '历史值：无颜色（/）' : `历史值：${legacyColorLabel}`"
                    :value="LEGACY_COLOR_VALUE"
                  />
                  <ElOption v-for="item in colorOptions" :key="item.id" :label="item.label" :value="item.id" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem label="材质" prop="material" :error="fieldError('material')">
                <ElInput v-model="form.material" maxlength="200" placeholder="请输入材质" />
              </ElFormItem>
              <ElFormItem label="仓库名称" prop="warehouse_key" required :error="fieldError('warehouse_key')">
                <ElSelect v-model="form.warehouse_key" filterable :disabled="!selectableWarehouses.length" placeholder="请选择仓库名称">
                  <ElOption
                    v-for="item in selectableWarehouses"
                    :key="warehouseKey(item)"
                    :label="`${item.warehouse_number} / ${item.warehouse_name}`"
                    :value="warehouseKey(item)"
                  />
                </ElSelect>
                <small v-if="!selectableWarehouses.length" class="field-warning">当前没有有效仓库组合，不能保存。</small>
              </ElFormItem>
            </div>
          </section>

          <section v-if="isPackagingCategory" class="form-section packaging-section">
            <h3>包装属性 <small>非包材类别不显示包装属性。</small></h3>
            <div class="form-grid">
              <ElFormItem label="是否包材辅料" prop="is_packaging_auxiliary" :error="fieldError('is_packaging_auxiliary')">
                <ElRadioGroup v-model="form.is_packaging_auxiliary"><ElRadio :value="true">是</ElRadio><ElRadio :value="false">否</ElRadio></ElRadioGroup>
              </ElFormItem>
              <ElFormItem label="箱子形状" prop="box_shape" :error="fieldError('box_shape')">
                <ElSelect v-model="form.box_shape" clearable placeholder="请选择箱子形状">
                  <ElOption v-for="item in options.box_shapes" :key="item.value" :label="item.label" :value="item.value" />
                </ElSelect>
              </ElFormItem>
            </div>
          </section>

          <ElFormItem label="备注" prop="notes" class="notes-field" :error="fieldError('notes')">
            <ElInput v-model="form.notes" type="textarea" :rows="3" placeholder="请填写备注" />
          </ElFormItem>
        </ElForm>
      </template>
    </div>

    <template #footer>
      <ElButton :disabled="saving" @click="requestClose">取消</ElButton>
      <ElButton type="primary" :loading="saving" :disabled="loading || Boolean(detailError) || !selectableWarehouses.length" @click="save">
        {{ mode === 'create' ? '保存原料' : '保存修改' }}
      </ElButton>
    </template>
  </ElDrawer>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

:global(.raw-material-information-drawer.el-drawer),
:global(.raw-material-information-drawer .el-drawer) {
  top: 64px;
  height: calc(100% - 64px);
  border-left: 1px solid token.$crm-border-default;
  background: token.$crm-color-surface;
  box-shadow: -8px 0 24px rgb(31 29 24 / 8%);
}
:global(.raw-material-information-drawer .el-drawer__header) { min-height: 90px; margin: 0; padding: 14px 24px 10px; border-bottom: 1px solid token.$crm-border-subtle; }
:global(.raw-material-information-drawer .el-drawer__body) { min-height: 0; padding: 0 24px; overflow-y: auto; }
:global(.raw-material-information-drawer .el-drawer__footer) { min-height: 60px; display: flex; justify-content: flex-end; gap: 8px; padding: 10px 24px; border-top: 1px solid token.$crm-border-subtle; background: token.$crm-color-surface; }
:global(.raw-material-information-drawer .el-drawer__footer .el-button) { width: 126px; height: 36px; border-radius: token.$crm-radius-2; }
:global(.raw-material-information-drawer .el-drawer__footer .el-button--primary) { width: 143px; border-color: token.$crm-primary; background: token.$crm-primary; }
.drawer-heading h2 { margin: 0; color: token.$crm-text-primary; font: 700 24px/34px token.$crm-font-display; }
.drawer-heading p { margin: 2px 0 0; color: token.$crm-text-secondary; font: 12px/18px token.$crm-font-body; }
.drawer-content { min-height: 100%; }
.drawer-content > .el-alert { margin: 12px 0; }
.drawer-state { min-height: 360px; display: grid; place-content: center; justify-items: center; gap: 16px; color: token.$crm-text-secondary; }
.raw-form { padding: 4px 0 12px; }
.form-section { padding-top: 4px; }
.form-section + .form-section { margin-top: 2px; }
.form-section h3 { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; color: token.$crm-text-primary; font: 700 17px/24px token.$crm-font-display; }
.form-section h3::after { height: 1px; flex: 1; content: ''; background: token.$crm-border-subtle; }
.form-section h3 small { color: token.$crm-text-secondary; font: 11px/16px token.$crm-font-body; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 20px; }
.raw-form :deep(.el-form-item) { margin-bottom: 8px; }
.raw-form :deep(.el-form-item__label) { height: 20px; padding: 0 0 3px; color: token.$crm-text-primary; font: 12px/17px token.$crm-font-body; }
.raw-form :deep(.el-input__wrapper), .raw-form :deep(.el-select__wrapper) { min-height: 36px; border-radius: token.$crm-radius-2; box-shadow: 0 0 0 1px token.$crm-border-default inset; }
.raw-form :deep(.el-form-item__error) { position: static; padding-top: 2px; line-height: 14px; }
.raw-form :deep(.el-select) { width: 100%; }
.raw-form :deep(.el-textarea__inner) { min-height: 58px !important; border-radius: token.$crm-radius-2; box-shadow: 0 0 0 1px token.$crm-border-default inset; resize: none; }
.raw-form small { display: block; margin-top: 2px; color: token.$crm-text-muted; font: 10px/14px token.$crm-font-body; }
.raw-form .field-warning { color: token.$crm-danger; }
.notes-field { margin-top: 4px; }
</style>
