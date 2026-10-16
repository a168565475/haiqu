<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { createProduct, fetchProductOptions, fetchProducts } from '@/api/products'
import type { ProductInformation, ProductInformationInput, ProductOptions } from '@/types/product'

const props = defineProps<{
  modelValue: boolean
  initialValues?: Partial<ProductInformationInput>
  initialUnitCode?: string
  initialItemNumber?: string
  submitProduct?: (input: ProductInformationInput) => Promise<ProductInformation>
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [product: ProductInformation]
}>()

const formRef = ref<FormInstance>()
const loading = ref(false)
const saving = ref(false)
const options = ref<ProductOptions>({ categories: [], units: [], items: [] })
const numberHint = ref('')
let numberCheckTimer: ReturnType<typeof setTimeout> | undefined
let numberCheckRequest = 0

function emptyForm(): ProductInformationInput {
  return {
    product_number: '', product_code: '', category: '', product_name: '', specification: '', unit: '',
    product_item: '', warehouse_number: '', warehouse_name: '', scale: 'CUSTOM', status: 'ACTIVE',
  }
}

const form = reactive<ProductInformationInput>(emptyForm())
const availableItems = computed(() => (
  form.category ? options.value.items.filter((item) => item.category_id === form.category) : []
))
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

function errorMessage(error: unknown) {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const first = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return first || response?.data?.error?.message || response?.data?.detail || (error instanceof Error ? error.message : '') || '产品信息保存失败，请检查填写内容。'
}

async function open() {
  Object.assign(form, emptyForm(), props.initialValues || {})
  await nextTick()
  formRef.value?.clearValidate()
  loading.value = true
  try {
    options.value = await fetchProductOptions()
    if (!form.unit && props.initialUnitCode) {
      form.unit = options.value.units.find(unit => unit.unit_code === props.initialUnitCode || unit.unit_name === props.initialUnitCode)?.id || ''
    }
    if (!form.product_item && props.initialItemNumber) {
      form.product_item = options.value.items.find(item => item.category_id === form.category && item.item_number === props.initialItemNumber)?.id || ''
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
    emit('update:modelValue', false)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!formRef.value || saving.value) return
  saving.value = true
  try {
    if (!await formRef.value.validate().catch(() => false)) return
    const input = {
      ...form,
      product_number: form.product_number.trim(),
      product_code: form.product_code.trim(),
      product_name: form.product_name.trim(),
      specification: form.specification.trim(),
      warehouse_number: form.warehouse_number.trim(),
      warehouse_name: form.warehouse_name.trim(),
    }
    const product = props.submitProduct ? await props.submitProduct(input) : (await createProduct(input)).data
    ElMessage.success('产品信息已新增')
    emit('created', product)
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

watch(() => props.modelValue, (visible) => { if (visible) void open() })
watch(() => form.product_number, (value) => {
  if (numberCheckTimer) clearTimeout(numberCheckTimer)
  const request = ++numberCheckRequest
  numberHint.value = ''
  if (!props.submitProduct || !props.modelValue || !value.trim()) return
  numberCheckTimer = setTimeout(async () => {
    try {
      const result = await fetchProducts({ q: value.trim(), page: 1, page_size: 100 })
      if (request === numberCheckRequest) numberHint.value = result.data.some(product => product.product_number === value.trim()) ? `品号 ${value.trim()} 已存在，请核对或填写其他品号。` : ''
    } catch {
      if (request === numberCheckRequest) numberHint.value = '品号查询未完成，保存时仍会校验唯一性。'
    }
  }, 350)
})
onBeforeUnmount(() => { ++numberCheckRequest; if (numberCheckTimer) clearTimeout(numberCheckTimer) })
watch(() => form.category, () => {
  if (form.product_item && !availableItems.value.some((item) => item.id === form.product_item)) form.product_item = ''
})
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    title="新增产品"
    width="min(760px, 94vw)"
    destroy-on-close
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
  >
    <ElAlert title="类别、单位、货号来自生产维护；带 * 的字段必填。" type="info" :closable="false" class="dialog-alert" />
    <ElForm ref="formRef" v-loading="loading" :model="form" :rules="rules" :disabled="saving" label-position="top" class="product-form">
      <div class="form-grid">
        <ElFormItem label="品号" prop="product_number" required><ElTooltip :disabled="!numberHint" :content="numberHint" :trigger="['hover', 'focus']" placement="top" effect="light" popper-class="bom-product-number-hint"><ElInput v-model="form.product_number" aria-label="品号" maxlength="100" placeholder="请输入唯一品号" /></ElTooltip></ElFormItem>
        <ElFormItem label="类型" required><ElInput model-value="成品" disabled /></ElFormItem>
        <ElFormItem label="产品编码" prop="product_code"><ElInput v-model="form.product_code" maxlength="100" placeholder="可为空，填写后必须唯一" /></ElFormItem>
        <ElFormItem label="类别" prop="category" required><ElSelect v-model="form.category" filterable placeholder="请选择成品类别"><ElOption v-for="item in options.categories" :key="item.id" :label="item.category_name" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="品名" prop="product_name" required><ElInput v-model="form.product_name" maxlength="200" placeholder="请输入品名" /></ElFormItem>
        <ElFormItem label="规格" prop="specification" required><ElInput v-model="form.specification" maxlength="300" placeholder="请输入规格" /></ElFormItem>
        <ElFormItem label="单位" prop="unit" required><ElSelect v-model="form.unit" filterable placeholder="请选择单位"><ElOption v-for="item in options.units" :key="item.id" :label="item.unit_name" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="货号" prop="product_item" required><ElSelect v-model="form.product_item" filterable :disabled="!form.category" placeholder="请先选择类别"><ElOption v-for="item in availableItems" :key="item.id" :label="item.item_number" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="仓库号" prop="warehouse_number"><ElInput v-model="form.warehouse_number" maxlength="100" placeholder="请输入仓库号" /></ElFormItem>
        <ElFormItem label="仓库名称" prop="warehouse_name"><ElInput v-model="form.warehouse_name" maxlength="150" placeholder="请输入仓库名称" /></ElFormItem>
        <ElFormItem label="规模" prop="scale" required><ElSelect v-model="form.scale"><ElOption label="定制" value="CUSTOM" /><ElOption label="常规" value="REGULAR" /></ElSelect></ElFormItem>
        <ElFormItem label="状态" prop="status" required><ElSelect v-model="form.status"><ElOption label="正常" value="ACTIVE" /><ElOption label="废弃" value="INACTIVE" /></ElSelect></ElFormItem>
      </div>
    </ElForm>
    <template #footer>
      <ElButton :disabled="saving" @click="emit('update:modelValue', false)">取消</ElButton>
      <ElButton type="primary" :loading="saving" @click="save">保存</ElButton>
    </template>
  </ElDialog>
</template>

<style lang="scss" scoped>
@use '@/styles/crm/tokens' as token;
.dialog-alert { margin-bottom: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.product-form :deep(.el-select) { width: 100%; }
:global(.el-popper.bom-product-number-hint) { max-width: 300px; padding: 8px 12px; border: 1px solid token.$crm-danger; border-radius: 5px; background: token.$crm-color-surface; color: token.$crm-danger; font-size: 12px; line-height: 18px; }
</style>
