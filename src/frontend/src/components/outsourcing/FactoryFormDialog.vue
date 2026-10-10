<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { OutsourcingCraftOption, OutsourcingFactory, OutsourcingFactoryInput } from '@/types/outsourcing'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  factory?: OutsourcingFactory | null
  initialCraftId?: string
  crafts: OutsourcingCraftOption[]
  saving?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [value: OutsourcingFactoryInput]
}>()

const formRef = ref<FormInstance>()
const form = reactive<OutsourcingFactoryInput>({
  craft_ids: [],
  name: '',
  processing_type: '',
  estimated_output: null,
  estimated_output_unit: '',
  estimated_output_period: '',
  contact_name: '',
  contact_phone: '',
  address: '',
  remark: '',
  payment_cycle: 'MONTHLY',
})

const title = computed(() => props.mode === 'create' ? '新增加工厂' : '编辑加工厂')
const primaryCraftId = computed({
  get: () => form.craft_ids[0] || '',
  set: (value: string) => { form.craft_ids = value ? [value] : [] },
})
const rules: FormRules<OutsourcingFactoryInput> = {
  craft_ids: [{ required: true, message: '请选择外协工序', trigger: 'change' }],
  name: [{ required: true, message: '请输入加工厂名称', trigger: 'blur' }],
  processing_type: [{ required: true, message: '请输入加工类型', trigger: 'blur' }],
  contact_name: [{ required: true, message: '请输入联系人', trigger: 'blur' }],
  contact_phone: [{ required: true, message: '请输入联系电话', trigger: 'blur' }],
  address: [{ required: true, message: '请输入地址', trigger: 'blur' }],
}

function reset(): void {
  const factory = props.factory
  form.craft_ids = factory?.crafts.map((item) => item.id) ?? (props.initialCraftId ? [props.initialCraftId] : [])
  form.name = factory?.name ?? ''
  form.processing_type = factory?.processing_type ?? ''
  form.estimated_output = factory?.estimated_output ?? null
  form.estimated_output_unit = factory?.estimated_output_unit ?? ''
  form.estimated_output_period = factory?.estimated_output_period ?? ''
  form.contact_name = factory?.contact_name ?? ''
  form.contact_phone = factory?.contact_phone ?? ''
  form.address = factory?.address ?? ''
  form.remark = factory?.remark ?? ''
  form.payment_cycle = 'MONTHLY'
  formRef.value?.clearValidate()
}

function updateVisible(visible: boolean): void {
  if (!visible && props.saving) return
  emit('update:modelValue', visible)
}

watch(() => props.modelValue, (visible) => {
  if (visible) reset()
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) {
    ElMessage.warning('请先补全必填信息。')
    return
  }
  emit('submit', { ...form, craft_ids: [...form.craft_ids] })
}
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    :title="title"
    :width="1080"
    :height="412"
    destroy-on-close
    class="outsourcing-factory-dialog"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @update:model-value="updateVisible"
  >
    <ElForm ref="formRef" :model="form" :rules="rules" label-position="left" label-width="120px" require-asterisk-position="right" class="factory-form">
      <ElFormItem label="外协工序" prop="craft_ids">
        <ElSelect v-model="primaryCraftId" placeholder="请选择外协工序" popper-class="outsourcing-select-popper">
          <ElOption v-for="craft in crafts" :key="craft.id" :label="craft.name" :value="craft.id" />
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="联系人" prop="contact_name"><ElInput v-model="form.contact_name" maxlength="100" /></ElFormItem>
      <ElFormItem label="名称" prop="name"><ElInput v-model="form.name" maxlength="255" /></ElFormItem>
      <ElFormItem label="联系电话" prop="contact_phone"><ElInput v-model="form.contact_phone" maxlength="100" /></ElFormItem>
      <ElFormItem label="加工类型" prop="processing_type"><ElInput v-model="form.processing_type" maxlength="200" /></ElFormItem>
      <ElFormItem label="地址" prop="address"><ElInput v-model="form.address" maxlength="500" /></ElFormItem>
      <ElFormItem label="加工厂预产量">
        <ElInput v-model="form.estimated_output" maxlength="22" placeholder="可选，周期和单位待业务确认" />
      </ElFormItem>
      <ElFormItem label="备注"><ElInput v-model="form.remark" maxlength="500" /></ElFormItem>
      <div class="factory-form-spacer" />
      <ElFormItem label="付款周期"><ElSelect v-model="form.payment_cycle"><ElOption label="月结" value="MONTHLY" /></ElSelect></ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton :disabled="saving" @click="updateVisible(false)">取消</ElButton>
      <ElButton type="primary" :loading="saving" @click="submit">保存</ElButton>
    </template>
  </AppWindowDialog>
</template>
