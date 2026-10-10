<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

import { createBomAuxiliaryReference } from '@/api/boms'
import { fetchAllProductionDataRecords } from '@/api/productionData'
import type { BomAuxiliaryProductOption } from '@/types/bom'
import type { AccessoryMaterial } from '@/types/productionData'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'created', value: BomAuxiliaryProductOption): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const formRef = ref<FormInstance>()
const materials = ref<AccessoryMaterial[]>([])
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const form = reactive({ product_name: '', unit_name: '', specification: '', color: '', material: '' })
const rules: FormRules = {
  product_name: [{ required: true, message: '请输入品名', trigger: 'blur' }],
  unit_name: [{ required: true, message: '请输入单位', trigger: 'blur' }],
  specification: [{ required: true, message: '请输入规格', trigger: 'blur' }],
  color: [{ required: true, message: '请输入颜色', trigger: 'blur' }],
}

function reset() {
  Object.assign(form, { product_name: '', unit_name: '', specification: '', color: '', material: '' })
  errorMessage.value = ''
  nextTick(() => formRef.value?.clearValidate())
}

function errorText(error: unknown) {
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } } } })?.response
  return Object.values(response?.data?.error?.field_errors || {}).flat()[0]
    || response?.data?.error?.message
    || response?.data?.detail
    || '辅料资料新增失败，请稍后重试。'
}

async function loadMaterials() {
  loading.value = true
  errorMessage.value = ''
  try {
    materials.value = await fetchAllProductionDataRecords<AccessoryMaterial>('accessory-materials')
  } catch (error) {
    materials.value = []
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!formRef.value || saving.value) return
  if (!await formRef.value.validate().catch(() => false)) return
  saving.value = true
  errorMessage.value = ''
  try {
    const product = await createBomAuxiliaryReference({
      product_name: form.product_name.trim(),
      unit_name: form.unit_name.trim(),
      specification: form.specification.trim(),
      color: form.color.trim(),
      material: form.material.trim(),
    })
    emit('created', product)
    visible.value = false
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    saving.value = false
  }
}

watch(() => props.modelValue, (value) => {
  if (!value) return
  reset()
  void loadMaterials()
})
</script>

<template>
  <ElDialog v-model="visible" title="新增辅料资料" width="720px" append-to-body destroy-on-close :close-on-click-modal="false" class="auxiliary-reference-create-dialog bom-reference-create-dialog" @closed="reset">
    <ElAlert title="数据将写入“生产维护 / 辅料维护”，保存后可直接在当前辅料选择页使用。" type="info" :closable="false" class="create-tip" />
    <ElAlert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="create-tip" />
    <ElForm ref="formRef" v-loading="loading" :model="form" :rules="rules" label-position="top">
      <div class="create-grid">
        <ElFormItem label="品名" prop="product_name" required><ElInput v-model="form.product_name" maxlength="200" /></ElFormItem>
        <ElFormItem label="单位" prop="unit_name" required><ElInput v-model="form.unit_name" maxlength="50" /></ElFormItem>
        <ElFormItem label="规格" prop="specification" required><ElInput v-model="form.specification" maxlength="300" /></ElFormItem>
        <ElFormItem label="颜色" prop="color" required><ElInput v-model="form.color" maxlength="200" /></ElFormItem>
        <ElFormItem label="材质（选填）" class="is-wide">
          <ElSelect v-model="form.material" allow-create filterable clearable default-first-option placeholder="选择或输入新材质">
            <ElOption v-for="item in materials" :key="item.id" :label="item.material_name" :value="item.material_name" />
          </ElSelect>
        </ElFormItem>
      </div>
    </ElForm>
    <template #footer><ElButton :disabled="saving" @click="visible = false">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="loading || Boolean(errorMessage)" @click="submit">保存</ElButton></template>
  </ElDialog>
</template>

<style lang="scss" scoped>
.create-tip{margin-bottom:14px}.create-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px}.is-wide{grid-column:1/-1}.is-wide :deep(.el-select){width:100%}
</style>
