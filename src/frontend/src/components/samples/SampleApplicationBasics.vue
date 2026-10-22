<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { fetchCustomerContacts } from '@/api/contacts'
import { fetchCustomers } from '@/api/customers'
import { fetchInquiries } from '@/api/inquiries'
import { fetchQuotations } from '@/api/quotations'
import { fetchSampleApplicationSourceContext } from '@/api/sampleApplication'
import type { SampleCustomerOption, SampleDetail, SampleFormOptions } from '@/types/sample'
import type { SampleApplicationBasicInput } from '@/types/sampleApplication'

const props = defineProps<{ modelValue: SampleApplicationBasicInput; options: SampleFormOptions | null; sample: SampleDetail }>()
const emit = defineEmits<{ 'update:modelValue': [value: SampleApplicationBasicInput] }>()
const customerMatches = ref<SampleCustomerOption[]>([])
const sourceMatches = ref<Array<{ id: string; label: string }>>([])
const contactMatches = ref<Array<{ id: string; display_name: string }>>([])
const customerLabels = ref<Record<string, SampleCustomerOption>>({})
const contactLabels = ref<Record<string, { id: string; display_name: string }>>({})
const ownerLabels = ref<Record<string, { id: string; display_name: string }>>({})
const sourceLabels = ref<Record<string, string>>({})
const customersLoading = ref(false), contactsLoading = ref(false), sourcesLoading = ref(false), contextLoading = ref(false)
const errorMessage = ref('')
let customerRequest = 0, contactRequest = 0, sourceRequest = 0, contextRequest = 0

const customers = computed(() => [...new Map([
  ...(props.options?.customers || []), ...customerMatches.value,
  ...(customerLabels.value[props.modelValue.customer_account_id] ? [customerLabels.value[props.modelValue.customer_account_id]!] : []),
].map(value => [value.id, value])).values()])
const contacts = computed(() => [...new Map([
  ...contactMatches.value,
  ...(props.modelValue.customer_contact_id && contactLabels.value[props.modelValue.customer_contact_id] ? [contactLabels.value[props.modelValue.customer_contact_id]!] : []),
].map(value => [value.id, value])).values()])
const owners = computed(() => [...new Map([
  ...(props.options?.salespeople || []),
  ...(ownerLabels.value[props.modelValue.owner_employee_id] ? [ownerLabels.value[props.modelValue.owner_employee_id]!] : []),
].map(value => [value.id, value])).values()])
const sources = computed(() => {
  const id = props.modelValue.source_id
  const label = sourceLabels.value[`${props.modelValue.source_type}:${id}`]
  return [...new Map([...sourceMatches.value, ...(id && label ? [{ id, label }] : [])].map(value => [value.id, value])).values()]
})

function update(patch: Partial<SampleApplicationBasicInput>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}
function errorText(error: unknown) {
  if (error instanceof AxiosError) {
    if (error.response?.status === 403) return '当前账号没有读取此选项的权限。'
    const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
    return data?.error?.message || data?.detail || '选项加载失败，请重新搜索。'
  }
  return error instanceof Error ? error.message : '选项加载失败，请重新搜索。'
}
watch(() => props.sample, sample => {
  customerLabels.value[sample.customer_account] = { id: sample.customer_account, account_name: sample.customer_name, account_code: '' }
  if (sample.customer_contact) contactLabels.value[sample.customer_contact] = { id: sample.customer_contact, display_name: sample.customer_contact_name }
  if (sample.owner) ownerLabels.value[sample.owner.id] = sample.owner
  if (sample.source_inquiry) sourceLabels.value[`inquiry:${sample.source_inquiry}`] = sample.source_inquiry_number
  if (sample.source_quotation_version) sourceLabels.value[`quotation:${sample.source_quotation_version}`] = sample.source_quotation_number
}, { immediate: true })
watch(() => [props.modelValue.source_type, props.modelValue.source_id, props.modelValue.customer_account_id], () => {
  contextRequest++; contextLoading.value = false
})
watch(() => props.modelValue.source_type, () => {
  sourceRequest++; sourcesLoading.value = false; sourceMatches.value = []
})
watch(() => [props.modelValue.customer_account_id, props.options], () => {
  contactRequest++; contactsLoading.value = false; contactMatches.value = []
  if (props.modelValue.customer_account_id && props.options) void searchContacts('')
}, { immediate: true })

async function searchCustomers(query: string) {
  const request = ++customerRequest
  errorMessage.value = ''
  if (!query.trim()) { customerMatches.value = props.options?.customers || []; customersLoading.value = false; return }
  customersLoading.value = true
  try {
    const result = await fetchCustomers({ q: query.trim(), page: 1, page_size: 50, archived: 'false' })
    if (request === customerRequest) customerMatches.value = result.data
  } catch (error) {
    if (request === customerRequest) { customerMatches.value = []; errorMessage.value = errorText(error) }
  } finally { if (request === customerRequest) customersLoading.value = false }
}
function changeCustomer(id: string) {
  contextRequest++; contextLoading.value = false
  const selected = customers.value.find(customer => customer.id === id)
  if (selected) customerLabels.value[id] = selected
  update({ customer_account_id: id, customer_contact_id: null, source_type: null, source_id: null })
}
async function searchContacts(query: string) {
  const request = ++contactRequest, customerId = props.modelValue.customer_account_id
  if (!customerId) { contactsLoading.value = false; return }
  contactsLoading.value = true; errorMessage.value = ''
  try {
    const result = await fetchCustomerContacts(customerId, { q: query.trim(), page: 1, page_size: 100 })
    if (request === contactRequest && customerId === props.modelValue.customer_account_id) contactMatches.value = result.data
  } catch (error) {
    if (request === contactRequest) { contactMatches.value = []; errorMessage.value = errorText(error) }
  } finally { if (request === contactRequest) contactsLoading.value = false }
}
function changeContact(id: string) {
  const selected = contacts.value.find(contact => contact.id === id)
  if (selected) contactLabels.value[id] = selected
  update({ customer_contact_id: id || null })
}
function changeSourceType(value: 'inquiry' | 'quotation' | '') {
  contextRequest++; contextLoading.value = false; errorMessage.value = ''
  update({ source_type: value || null, source_id: null })
}
function sourceVisibilityChanged(visible: boolean) {
  if (visible) void searchSources('')
}
async function searchSources(query: string) {
  const request = ++sourceRequest, type = props.modelValue.source_type
  if (!type) { sourcesLoading.value = false; return }
  sourcesLoading.value = true; errorMessage.value = ''
  try {
    const params = { q: query.trim(), page: 1, page_size: 50 }
    const matches = type === 'inquiry'
      ? (await fetchInquiries({ ...params, archived: 'false' })).data.map(row => ({ id: row.id, label: `${row.inquiry_number} · ${row.customer.name}` }))
      : (await fetchQuotations(params)).data.filter(row => row.current_version).map(row => ({ id: row.current_version!.id, label: `${row.quotation_number} · V${row.current_version!.version_number} · ${row.customer_name}` }))
    if (request === sourceRequest) sourceMatches.value = matches
  } catch (error) {
    if (request === sourceRequest) { sourceMatches.value = []; errorMessage.value = errorText(error) }
  } finally { if (request === sourceRequest) sourcesLoading.value = false }
}
async function changeSource(id: string) {
  const request = ++contextRequest, type = props.modelValue.source_type
  errorMessage.value = ''
  if (!id || !type) { contextLoading.value = false; update({ source_type: null, source_id: null }); return }
  contextLoading.value = true
  try {
    const context = await fetchSampleApplicationSourceContext(props.sample.id, type, id)
    if (request !== contextRequest) return
    sourceLabels.value[`${type}:${id}`] = context.source_number
    customerLabels.value[context.customer.id] = context.customer
    if (context.contact) contactLabels.value[context.contact.id] = context.contact
    ownerLabels.value[context.owner.id] = context.owner
    update({ source_type: type, source_id: id, customer_account_id: context.customer.id,
      customer_contact_id: context.contact?.id || null, owner_employee_id: context.owner.id })
  } catch (error) { if (request === contextRequest) errorMessage.value = errorText(error) }
  finally { if (request === contextRequest) contextLoading.value = false }
}
onBeforeUnmount(() => { customerRequest++; contactRequest++; sourceRequest++; contextRequest++ })
</script>

<template>
  <div class="sample-application-basics">
    <div v-if="errorMessage" class="basics-error" role="alert">{{ errorMessage }}</div>
    <div class="application-basic-grid">
      <ElFormItem label="来源类型"><ElSelect :model-value="modelValue.source_type || ''" aria-label="来源类型" clearable placeholder="无来源" @update:model-value="changeSourceType"><ElOption value="inquiry" label="询盘" /><ElOption value="quotation" label="报价" /></ElSelect></ElFormItem>
      <ElFormItem :label="modelValue.source_type === 'quotation' ? '来源报价' : '来源询盘'"><ElSelect :model-value="modelValue.source_id || ''" aria-label="来源单据" filterable remote clearable :disabled="!modelValue.source_type" :remote-method="searchSources" :loading="sourcesLoading || contextLoading" placeholder="搜索来源单据" @update:model-value="changeSource" @visible-change="sourceVisibilityChanged"><ElOption v-for="source in sources" :key="source.id" :value="source.id" :label="source.label" /></ElSelect></ElFormItem>
      <ElFormItem label="客户"><ElSelect :model-value="modelValue.customer_account_id" aria-label="客户" filterable remote :remote-method="searchCustomers" :loading="customersLoading" placeholder="请选择客户" @update:model-value="changeCustomer"><ElOption v-for="customer in customers" :key="customer.id" :value="customer.id" :label="customer.account_name" /></ElSelect></ElFormItem>
      <ElFormItem label="联系人"><ElSelect :model-value="modelValue.customer_contact_id || ''" aria-label="联系人" filterable remote clearable :remote-method="searchContacts" :loading="contactsLoading" :disabled="!modelValue.customer_account_id" placeholder="请选择联系人" @update:model-value="changeContact"><ElOption v-for="contact in contacts" :key="contact.id" :value="contact.id" :label="contact.display_name" /></ElSelect></ElFormItem>
      <ElFormItem label="业务员"><ElSelect :model-value="modelValue.owner_employee_id" aria-label="业务员" filterable placeholder="请选择业务员" @update:model-value="update({ owner_employee_id: $event })"><ElOption v-for="owner in owners" :key="owner.id" :value="owner.id" :label="owner.display_name" /></ElSelect></ElFormItem>
      <ElFormItem label="样品类型 *"><ElSelect :model-value="modelValue.sample_type" aria-label="样品类型" placeholder="请选择样品类型" @update:model-value="update({ sample_type: $event })"><ElOption v-if="!options && modelValue.sample_type" :value="modelValue.sample_type" :label="sample.sample_type_display" /><ElOption v-for="option in options?.sample_types" :key="option.value" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
      <ElFormItem label="寄送方式 *"><ElSelect :model-value="modelValue.shipping_method" aria-label="寄送方式" placeholder="请选择寄送方式" @update:model-value="update({ shipping_method: $event })"><ElOption v-if="!options && modelValue.shipping_method" :value="modelValue.shipping_method" :label="sample.shipping_method_display" /><ElOption v-for="option in options?.shipping_methods" :key="option.value" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
      <ElFormItem label="交货方式 *"><ElSelect :model-value="modelValue.delivery_batch" aria-label="交货方式" placeholder="请选择交货方式" @update:model-value="update({ delivery_batch: $event })"><ElOption v-if="!options && modelValue.delivery_batch" :value="modelValue.delivery_batch" :label="sample.delivery_batch_display" /><ElOption v-for="option in options?.delivery_batches" :key="option.value" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
      <ElFormItem label="是否返单 *"><ElSelect :model-value="modelValue.is_repeat_order" aria-label="是否返单" placeholder="请选择" @update:model-value="update({ is_repeat_order: $event })"><ElOption v-if="!options && modelValue.is_repeat_order !== null" :value="modelValue.is_repeat_order" :label="modelValue.is_repeat_order ? '是' : '否'" /><ElOption v-for="option in options?.repeat_options" :key="String(option.value)" :value="option.value" :label="option.label" /></ElSelect></ElFormItem>
      <ElFormItem label="下单日期"><ElDatePicker :model-value="modelValue.order_date" aria-label="下单日期" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" @update:model-value="update({ order_date: $event || null })" /></ElFormItem>
      <ElFormItem label="期望样品完成日期"><ElDatePicker :model-value="modelValue.sample_due_date" aria-label="期望样品完成日期" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" @update:model-value="update({ sample_due_date: $event || null })" /></ElFormItem>
    </div>
  </div>
</template>

<style scoped lang="scss">
.application-basic-grid { display: grid; min-width: 0; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px 20px; }
.application-basic-grid :deep(.el-form-item) { min-width: 0; margin-bottom: 0; }
.application-basic-grid :deep(.el-select), .application-basic-grid :deep(.el-date-editor.el-input) { width: 100%; }
.basics-error { margin-bottom: 12px; color: var(--el-color-danger); font-size: 13px; }
@media (max-width: 900px) { .application-basic-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; } }
@media (max-width: 600px) { .application-basic-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
