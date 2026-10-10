<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'

import type {
  ProductOption,
  ProductionTaskDetailInput,
  ProductionTaskOptions,
  ProductionTaskProductInput,
  ProductionTaskProductUpdateDraft,
} from '@/types/productionTask'

const props = defineProps<{
  modelValue: boolean
  product: ProductOption | null
  lineId: string
  taskCurrencyId: string
  options: ProductionTaskOptions | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [draft: ProductionTaskProductUpdateDraft]
}>()

const productImages = ref<File[]>([])
const detailImages = reactive<Record<string, File | null>>({})
const form = reactive<ProductionTaskProductInput>({
  client_key: '', product_id: '', product_color_id: null, color_code: '', quantity: '', unit_id: '',
  currency_id: '', unit_price: '', exchange_rate: '', special_requirements: '', packaging_method: '',
  retained_image_ids: [], details: [],
})

const colorCards = computed(() => Array.from(new Set((props.options?.colors || []).map((item) => item.color_card))).filter(Boolean))
const selectedColor = computed(() => props.options?.colors.find((item) => item.id === form.product_color_id) || null)
const colorNames = computed(() => Array.from(new Set((props.options?.colors || [])
  .filter((item) => item.color_card === selectedColorCard.value).map((item) => item.color_name))).filter(Boolean))
const selectedColorCard = ref('')
const selectedColorName = ref('')
const colorCodes = computed(() => (props.options?.colors || []).filter((item) => (
  item.color_card === selectedColorCard.value && item.color_name === selectedColorName.value
)))
const isCny = computed(() => props.options?.currencies.find((item) => item.id === form.currency_id)?.code === 'CNY')

function key() { return crypto.randomUUID() }
function reset() {
  const details: ProductionTaskDetailInput[] = (props.options?.detail_template || []).map((item) => ({
    client_key: key(), template_key: item.key, detail_type: item.type, category_label: item.category,
    is_selected: false, description: '',
  }))
  Object.assign(form, {
    client_key: props.lineId,
    product_id: props.product?.id || '',
    product_color_id: null,
    color_code: '',
    quantity: '',
    unit_id: props.product?.default_unit_id || '',
    currency_id: props.taskCurrencyId,
    unit_price: '',
    exchange_rate: props.options?.currencies.find((item) => item.id === props.taskCurrencyId)?.code === 'CNY' ? '1.000' : '',
    special_requirements: '',
    packaging_method: '',
    retained_image_ids: [],
    details: details.length ? details : [{ client_key: key(), template_key: '', detail_type: '', category_label: '', is_selected: false, description: '' }],
  })
  selectedColorCard.value = ''
  selectedColorName.value = ''
  productImages.value = []
  Object.keys(detailImages).forEach((item) => delete detailImages[item])
}

function changeCard() {
  selectedColorName.value = ''
  form.product_color_id = null
  form.color_code = ''
}
function changeName() {
  form.product_color_id = null
  form.color_code = ''
}
function changeCode() { form.color_code = selectedColor.value?.color_code || '' }
function changeCurrency() {
  form.exchange_rate = isCny.value ? '1.000' : ''
}
function normalizeQuantity() {
  form.quantity = (form.quantity.match(/^\d+/)?.[0] || '').replace(/^0+(?=\d)/, '')
}
function addDetail() {
  form.details.push({ client_key: key(), template_key: '', detail_type: '', category_label: '', is_selected: false, description: '' })
}
function chooseProductImages(uploadFile: UploadFile) {
  const file = uploadFile.raw
  if (!file) return
  if (productImages.value.length >= 20) return ElMessage.warning('每条颜色明细最多上传 20 张图片。')
  if (file.size > 10 * 1024 * 1024) return ElMessage.warning('单张图片不能超过 10 MB。')
  productImages.value.push(file)
}
function removeProductImage(uploadFile: UploadFile) {
  if (uploadFile.raw) productImages.value = productImages.value.filter((file) => file !== uploadFile.raw)
}
function chooseDetailImage(detail: ProductionTaskDetailInput, uploadFile: UploadFile) {
  if (uploadFile.raw) detailImages[detail.client_key] = uploadFile.raw
}
function validate() {
  if (!form.product_color_id || !form.color_code) return '请按顺序选择色卡、颜色和色号。'
  if (!/^[1-9]\d*$/.test(form.quantity)) return '订单数量必须是大于 0 的整数。'
  if (form.unit_price === '' || Number(form.unit_price) < 0) return '请填写正确的售价。'
  if (!/^\d+(\.\d{1,3})?$/.test(form.exchange_rate) || Number(form.exchange_rate) <= 0) return '汇率必须大于 0，且最多保留 3 位小数。'
  if (isCny.value && Number(form.exchange_rate) !== 1) return 'CNY 汇率必须为 1.000。'
  if (!form.details.length || form.details.some((item) => !item.detail_type.trim())) return '请补齐生产任务单明细类型。'
  return ''
}
function confirm() {
  const message = validate()
  if (message) return ElMessage.warning(message)
  form.exchange_rate = Number(form.exchange_rate).toFixed(3)
  emit('confirm', {
    payload: JSON.parse(JSON.stringify(form)),
    productImages: [...productImages.value],
    detailImages: { ...detailImages },
  })
  emit('update:modelValue', false)
}

watch(() => props.modelValue, (visible) => { if (visible) reset() })
</script>

<template>
  <ElDialog :model-value="modelValue" :title="`填写更换后的生产任务信息 · ${product?.product_name || ''}`" width="1180px" append-to-body destroy-on-close @update:model-value="emit('update:modelValue', $event)">
    <ElForm label-position="top" class="update-form">
      <div class="form-grid">
        <ElFormItem label="色卡" required><ElSelect v-model="selectedColorCard" placeholder="请选择" @change="changeCard"><ElOption v-for="item in colorCards" :key="item" :label="item" :value="item" /></ElSelect></ElFormItem>
        <ElFormItem label="颜色" required><ElSelect v-model="selectedColorName" :disabled="!selectedColorCard" placeholder="请选择" @change="changeName"><ElOption v-for="item in colorNames" :key="item" :label="item" :value="item" /></ElSelect></ElFormItem>
        <ElFormItem label="色号" required><ElSelect v-model="form.product_color_id" :disabled="!selectedColorName" placeholder="请选择" @change="changeCode"><ElOption v-for="item in colorCodes" :key="item.id" :label="item.color_code" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="订单数量" required><ElInput v-model="form.quantity" inputmode="numeric" placeholder="整数" @input="normalizeQuantity" /></ElFormItem>
        <ElFormItem label="单位" required><ElSelect v-model="form.unit_id" disabled><ElOption v-for="item in options?.units || []" :key="item.id" :label="`${item.unit_code} · ${item.unit_name}`" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="币种" required><ElSelect v-model="form.currency_id" disabled @change="changeCurrency"><ElOption v-for="item in options?.currencies || []" :key="item.id" :label="`${item.code} · ${item.name}`" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="售价" required><ElInput v-model="form.unit_price" placeholder="0.0000" /></ElFormItem>
        <ElFormItem label="汇率" required><ElInput v-model="form.exchange_rate" :disabled="isCny" placeholder="0.000" /></ElFormItem>
      </div>
      <ElFormItem label="明细图片（最多 20 张）"><ElUpload multiple :limit="20" :auto-upload="false" :show-file-list="true" accept=".jpg,.jpeg,.png,.gif,.webp" :on-change="chooseProductImages" :on-remove="removeProductImage"><ElButton>选择图片</ElButton></ElUpload></ElFormItem>
      <div class="detail-heading"><strong>生产任务单明细</strong><ElButton @click="addDetail">增加一条</ElButton></div>
      <ElTable :data="form.details" height="290" border size="small">
        <ElTableColumn prop="detail_type" label="类型" width="150"><template #default="{ row }"><ElInput v-model="row.detail_type" /></template></ElTableColumn>
        <ElTableColumn prop="category_label" label="类别项" width="160"><template #default="{ row }"><ElInput v-model="row.category_label" /></template></ElTableColumn>
        <ElTableColumn label="是否" width="92"><template #default="{ row }"><ElSelect v-model="row.is_selected"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect></template></ElTableColumn>
        <ElTableColumn label="描述" min-width="280"><template #default="{ row }"><ElInput v-model="row.description" maxlength="2000" /></template></ElTableColumn>
        <ElTableColumn label="图片" width="132"><template #default="{ row }"><ElUpload :auto-upload="false" :show-file-list="false" accept=".jpg,.jpeg,.png,.gif,.webp" :on-change="(file: UploadFile) => chooseDetailImage(row, file)"><ElButton size="small">{{ detailImages[row.client_key] ? '已选择' : '选择图片' }}</ElButton></ElUpload></template></ElTableColumn>
        <ElTableColumn label="操作" width="76"><template #default="{ $index }"><ElButton link type="danger" :disabled="form.details.length <= 1" @click="form.details.splice($index, 1)">删除</ElButton></template></ElTableColumn>
      </ElTable>
      <div class="text-grid">
        <ElFormItem label="特殊要求"><ElInput v-model="form.special_requirements" type="textarea" :rows="3" maxlength="3000" show-word-limit /></ElFormItem>
        <ElFormItem label="包装方式"><ElInput v-model="form.packaging_method" type="textarea" :rows="3" maxlength="3000" show-word-limit /></ElFormItem>
      </div>
    </ElForm>
    <template #footer><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" @click="confirm">确认使用</ElButton></template>
  </ElDialog>
</template>

<style scoped lang="scss">
.form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0 12px; }
.form-grid :deep(.el-select), .update-form :deep(.el-upload) { width: 100%; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; margin: 6px 0 10px; }
.text-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 14px; }
</style>
