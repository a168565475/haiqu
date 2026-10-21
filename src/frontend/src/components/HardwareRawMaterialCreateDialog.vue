<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { cuttingSpecificationError } from '@/utils/cuttingSpecification'

import { createRawMaterial, fetchRawMaterialOptions } from '@/api/rawMaterials'
import type {
  RawMaterialInformation,
  RawMaterialInput,
  RawMaterialOptions,
} from '@/types/rawMaterial'

interface HardwareRawMaterialFormState {
  category: string
  material_number: string
  material_name: string
  specification: string
  unit: string
  warehouse_number: string
  color: string
  material: string
  notes: string
}

const props = defineProps<{
  modelValue: boolean
  itemType?: 'MATERIAL' | 'SEMI_FINISHED'
  categoryName?: string
  title?: string
  subjectLabel?: string
  testId?: string
  requireCuttingSpecification?: boolean
  inheritFabricAttributes?: boolean
  stageMaterial?: (payload: RawMaterialInput, display: Pick<RawMaterialInformation, 'category_name' | 'unit_name' | 'unit_code' | 'color_name'>) => void | Promise<void>
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'created', value: RawMaterialInformation): void
}>()

const dialogVisible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const emptyOptions = (): RawMaterialOptions => ({
  item_types: [],
  categories: [],
  units: [],
  colors: [],
  warehouses: [],
  box_shapes: [],
})

const emptyForm = (): HardwareRawMaterialFormState => ({
  category: '',
  material_number: '',
  material_name: '',
  specification: '',
  unit: '',
  warehouse_number: '',
  color: '',
  material: '',
  notes: '',
})

const formRef = ref<FormInstance>()
const form = reactive<HardwareRawMaterialFormState>(emptyForm())
const options = ref<RawMaterialOptions>(emptyOptions())
const categoryId = ref('')
const optionsLoading = ref(false)
const optionsError = ref('')
const submitError = ref('')
const saving = ref(false)
let optionsRequestId = 0

type ValidationCallback = (error?: Error) => void

function requiredText(message: string) {
  return (_rule: unknown, value: string, callback: ValidationCallback) => {
    if (!value || !value.trim()) {
      callback(new Error(message))
      return
    }
    callback()
  }
}

const rules: FormRules<HardwareRawMaterialFormState> = {
  category: [{ required: true, message: '请选择类别', trigger: 'change' }],
  material_number: [{ validator: requiredText('请输入品号'), trigger: 'blur' }],
  material_name: [{ validator: requiredText('请输入品名'), trigger: 'blur' }],
  specification: [{ validator: (_rule, value, callback) => {
    if (props.requireCuttingSpecification) {
      const error = cuttingSpecificationError(value)
      callback(error ? new Error(error) : undefined)
    } else requiredText('请输入规格')(_rule, value, callback)
  }, trigger: 'blur' }],
  unit: [{ required: true, message: '请选择单位', trigger: 'change' }],
  warehouse_number: [{ required: true, message: '请选择仓库', trigger: 'change' }],
}

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as {
    response?: {
      data?: {
        error?: { message?: string; field_errors?: Record<string, string[]> }
        detail?: string
      }
    }
  })?.response
  const firstFieldError = response?.data?.error?.field_errors
    ? Object.values(response.data.error.field_errors).flat()[0]
    : ''
  return firstFieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

function resetForm(): void {
  Object.assign(form, emptyForm())
  submitError.value = ''
  nextTick(() => formRef.value?.clearValidate())
}

async function loadOptions(): Promise<void> {
  const requestId = ++optionsRequestId
  optionsLoading.value = true
  optionsError.value = ''
  categoryId.value = ''
  try {
    const response = await fetchRawMaterialOptions()
    if (requestId !== optionsRequestId) return

    const itemType = props.itemType || 'MATERIAL'
    const matchingCategories = response.categories.filter((item) => (
      item.item_type === itemType
      && (!props.categoryName || item.category_name === props.categoryName)
    ))
    if (!matchingCategories.length || (props.categoryName && matchingCategories.length !== 1)) {
      options.value = response
      const typeLabel = itemType === 'MATERIAL' ? '材料' : '半成品'
      const expected = props.categoryName ? `${typeLabel} / ${props.categoryName}` : typeLabel
      optionsError.value = matchingCategories.length === 0
        ? `未找到已启用的“${expected}”类别，请先在生产维护中检查类别配置。`
        : `“${expected}”类别配置不唯一，请联系管理员处理后重试。`
      return
    }

    options.value = response
    if (props.categoryName) {
      categoryId.value = matchingCategories[0].id
      form.category = matchingCategories[0].id
    }
  } catch (error) {
    if (requestId !== optionsRequestId) return
    options.value = emptyOptions()
    optionsError.value = apiErrorMessage(error, '原料选项加载失败，请稍后重试。')
  } finally {
    if (requestId === optionsRequestId) optionsLoading.value = false
  }
}

function selectWarehouse(warehouseNumber: string): void {
  if (!warehouseNumber) return
  const selected = options.value.warehouses.find(
    (item) => item.warehouse_number === warehouseNumber,
  )
  if (!selected) form.warehouse_number = ''
}

async function submit(): Promise<void> {
  if (!formRef.value || saving.value || optionsLoading.value) return
  submitError.value = ''

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const selectedCategoryId = props.categoryName ? categoryId.value : form.category
  if (!selectedCategoryId) {
    submitError.value = optionsError.value || '请选择可用的原料类别。'
    return
  }

  const selectedUnit = options.value.units.find((item) => item.id === form.unit)
  if (!selectedUnit) {
    submitError.value = '所选单位已不可用，请重新选择。'
    form.unit = ''
    return
  }
  const selectedWarehouse = options.value.warehouses.find(
    (item) => item.warehouse_number === form.warehouse_number,
  )
  if (!selectedWarehouse) {
    submitError.value = '所选仓库已不可用，请重新选择。'
    form.warehouse_number = ''
    return
  }
  if (!props.inheritFabricAttributes && form.color && !options.value.colors.some((item) => item.id === form.color)) {
    submitError.value = '所选颜色已不可用，请重新选择。'
    form.color = ''
    return
  }

  const payload: RawMaterialInput = {
    material_number: form.material_number.trim(),
    item_type: props.itemType || 'MATERIAL',
    category: selectedCategoryId,
    material_name: form.material_name.trim(),
    specification: form.specification.trim(),
    unit: selectedUnit.id,
    color: props.inheritFabricAttributes ? null : form.color || null,
    material: props.inheritFabricAttributes ? '' : form.material.trim(),
    is_packaging_auxiliary: false,
    box_shape: '',
    notes: form.notes.trim(),
    warehouse_number: selectedWarehouse.warehouse_number,
    warehouse_name: selectedWarehouse.warehouse_name,
  }

  saving.value = true
  try {
    if (props.stageMaterial) {
      await props.stageMaterial(payload, {
        category_name: options.value.categories.find(item => item.id === selectedCategoryId)?.category_name || '',
        unit_name: selectedUnit.unit_name,
        unit_code: selectedUnit.unit_code,
        color_name: props.inheritFabricAttributes ? '' : options.value.colors.find(item => item.id === form.color)?.color_name || '',
      })
    } else {
      const created = await createRawMaterial(payload)
      emit('created', created.data)
    }
    dialogVisible.value = false
  } catch (error) {
    submitError.value = apiErrorMessage(error, `${props.subjectLabel || props.categoryName || '原料'}新增失败，请稍后重试。`)
  } finally {
    saving.value = false
  }
}

function closeDialog(): void {
  if (!saving.value) dialogVisible.value = false
}

function beforeClose(done: () => void): void {
  if (!saving.value) done()
}

function handleClosed(): void {
  optionsRequestId += 1
  optionsLoading.value = false
  optionsError.value = ''
  categoryId.value = ''
  options.value = emptyOptions()
  resetForm()
}

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    resetForm()
    void loadOptions()
  },
  { immediate: true },
)
</script>

<template>
  <AppWindowDialog
    v-model="dialogVisible"
    :data-testid="testId || 'hardware-raw-material-create-dialog'"
    :title="title || `新增${subjectLabel || categoryName || '原料'}`"
    width="760px"
    append-to-body
    destroy-on-close
    :before-close="beforeClose"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    class="hardware-raw-material-create-dialog bom-reference-create-dialog"
    @closed="handleClosed"
  >
    <el-alert
      :title="stageMaterial ? '本次仅暂存到 BOM，保存整份 BOM 时自动建立原料档案。' : categoryName
        ? `类型固定为“${(itemType || 'MATERIAL') === 'MATERIAL' ? '材料' : '半成品'}”，类别固定为“${categoryName}”；保存后将刷新当前选择列表。`
        : `类型固定为“${(itemType || 'MATERIAL') === 'MATERIAL' ? '材料' : '半成品'}”；保存后将刷新当前选择列表。`"
      type="info"
      :closable="false"
      class="dialog-tip"
    />
    <el-alert
      v-if="optionsError"
      :title="optionsError"
      type="error"
      :closable="false"
      show-icon
      class="dialog-error"
    >
      <template #default>
        <el-button size="small" :loading="optionsLoading" @click="loadOptions">重新加载</el-button>
      </template>
    </el-alert>
    <el-alert
      v-if="submitError"
      :title="submitError"
      type="error"
      :closable="false"
      show-icon
      class="dialog-error"
    />

    <el-form
      ref="formRef"
      v-loading="optionsLoading"
      :model="form"
      :rules="rules"
      :disabled="optionsLoading || Boolean(optionsError)"
      label-position="top"
      class="hardware-raw-material-form"
    >
      <div class="form-grid">
        <el-form-item label="类型">
          <el-input :model-value="(itemType || 'MATERIAL') === 'MATERIAL' ? '材料' : '半成品'" disabled />
        </el-form-item>
        <el-form-item label="类别" prop="category" required>
          <el-input v-if="categoryName" :model-value="categoryName" disabled />
          <el-select v-else v-model="form.category" filterable placeholder="请选择类别">
            <el-option
              v-for="item in options.categories.filter((option) => option.item_type === (itemType || 'MATERIAL'))"
              :key="item.id"
              :label="item.category_name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="品号" prop="material_number" required>
          <el-input v-model="form.material_number" :aria-label="`${subjectLabel || categoryName || '原料'}品号`" maxlength="100" placeholder="请输入唯一品号" />
        </el-form-item>
        <el-form-item label="品名" prop="material_name" required>
          <el-input v-model="form.material_name" :aria-label="`${subjectLabel || categoryName || '原料'}品名`" maxlength="200" placeholder="请输入品名" />
        </el-form-item>
        <el-form-item label="规格" prop="specification" required>
          <el-input v-model="form.specification" :aria-label="`${subjectLabel || categoryName || '原料'}规格`" maxlength="300" placeholder="请输入规格" />
          <small v-if="requireCuttingSpecification">规格必填，请填写实际尺寸或明确型号，不能用“/”等占位符。</small>
        </el-form-item>
        <el-form-item label="单位" prop="unit" required>
          <el-select v-model="form.unit" :aria-label="`${subjectLabel || categoryName || '原料'}单位`" filterable placeholder="请选择单位">
            <el-option
              v-for="item in options.units"
              :key="item.id"
              :label="item.unit_name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库" prop="warehouse_number" required>
          <el-select
            v-model="form.warehouse_number"
            :aria-label="`${subjectLabel || categoryName || '原料'}仓库`"
            filterable
            placeholder="请选择仓库"
            @change="selectWarehouse"
          >
            <el-option
              v-for="item in options.warehouses"
              :key="`${item.warehouse_number}-${item.warehouse_name}`"
              :label="`${item.warehouse_number} / ${item.warehouse_name}`"
              :value="item.warehouse_number"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!inheritFabricAttributes" label="颜色" prop="color">
          <el-select v-model="form.color" :aria-label="`${subjectLabel || categoryName || '原料'}颜色`" clearable filterable placeholder="请选择颜色（选填）">
            <el-option
              v-for="item in options.colors"
              :key="item.id"
              :label="item.label"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!inheritFabricAttributes" label="材质" prop="material">
          <el-input v-model="form.material" :aria-label="`${subjectLabel || categoryName || '原料'}材质`" maxlength="200" placeholder="请输入材质（选填）" />
        </el-form-item>
        <el-form-item label="备注" prop="notes" class="form-item--wide">
          <el-input
            v-model="form.notes"
            :aria-label="`${subjectLabel || categoryName || '原料'}备注`"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="请输入备注（选填）"
          />
        </el-form-item>
      </div>
    </el-form>

    <template #footer>
      <el-button :disabled="saving" @click="closeDialog">取消</el-button>
      <el-button
        :data-testid="testId ? `${testId}-submit` : 'hardware-raw-material-create-submit'"
        type="primary"
        :loading="saving"
        :disabled="optionsLoading || Boolean(optionsError)"
        @click="submit"
      >
        {{ stageMaterial ? '暂存并选中' : '保存' }}
      </el-button>
    </template>
  </AppWindowDialog>
</template>

<style lang="scss" scoped>
.dialog-tip,
.dialog-error {
  margin-bottom: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}

.form-item--wide {
  grid-column: 1 / -1;
}

.hardware-raw-material-form :deep(.el-select) {
  width: 100%;
}

</style>
