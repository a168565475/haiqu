<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { createComplaint, uploadComplaintImage } from '@/api/complaints'
import { fetchContacts } from '@/api/contacts'
import { fetchCustomers } from '@/api/customers'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { ContactListItem } from '@/types/contact'
import type { CustomerListItem } from '@/types/customer'
import type { Complaint, ComplaintDictionaryItem, ComplaintOptions } from '@/types/complaint'
import { complaintRequestMessage, validateComplaintImages } from '@/utils/complaintFeedback'

const props = defineProps<{
  modelValue: boolean
  options: ComplaintOptions | null
  complaintTypes: ComplaintDictionaryItem[]
  severities: ComplaintDictionaryItem[]
  fixedCustomerId?: string
  fixedCustomerName?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; created: [complaint: Complaint] }>()
const customers = ref<CustomerListItem[]>([])
const contacts = ref<ContactListItem[]>([])
const files = ref<File[]>([])
const failedFiles = ref<File[]>([])
const createdComplaint = ref<Complaint | null>(null)
const submitting = ref(false)
const retrying = ref(false)
const form = reactive({
  customer_id: '', contact_id: '', complaint_type_item_id: '', severity_item_id: '', title: '',
  source_order_reference: '', order_date: '', product_name: '', product_sku: '', issue_description: '',
  owner_employee_id: '', collaborator_employee_ids: [] as string[],
})

watch(() => props.modelValue, async visible => {
  if (!visible) return
  Object.assign(form, {
    customer_id: props.fixedCustomerId || '', contact_id: '', complaint_type_item_id: '', severity_item_id: '', title: '',
    source_order_reference: '', order_date: '', product_name: '', product_sku: '', issue_description: '',
    owner_employee_id: '', collaborator_employee_ids: [],
  })
  files.value = []
  failedFiles.value = []
  createdComplaint.value = null
  contacts.value = []
  if (props.fixedCustomerId) await loadContacts(props.fixedCustomerId)
  else await loadCustomers()
})

async function loadCustomers(keyword = '') {
  try { customers.value = (await fetchCustomers({ q: keyword || undefined, page: 1, page_size: 50 })).data }
  catch (error) { ElMessage.error(complaintRequestMessage(error)) }
}

async function loadContacts(customerId: string) {
  contacts.value = []
  form.contact_id = ''
  if (!customerId) return
  try { contacts.value = (await fetchContacts({ customer_id: customerId, page: 1, page_size: 100, status: 'ACTIVE' })).data }
  catch (error) { ElMessage.error(complaintRequestMessage(error)) }
}

function selectImages(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || [])
  const validation = validateComplaintImages(selected)
  if (validation) {
    ElMessage.warning(validation)
    input.value = ''
    return
  }
  files.value = selected
  failedFiles.value = []
}

function validationMessage() {
  if (!form.customer_id) return '请选择客户。'
  if (!form.complaint_type_item_id) return '请选择客诉类型。'
  if (!form.severity_item_id) return '请选择严重程度。'
  if (!form.title.trim()) return '请填写客诉标题。'
  if (!form.issue_description.trim()) return '请填写问题描述。'
  return ''
}

async function uploadFiles(complaintId: string, targets: File[]) {
  const failures: File[] = []
  for (const file of targets) {
    try { await uploadComplaintImage(complaintId, file) }
    catch { failures.push(file) }
  }
  return failures
}

async function submit() {
  if (submitting.value || createdComplaint.value) return
  const validation = validationMessage()
  if (validation) return ElMessage.warning(validation)
  submitting.value = true
  try {
    const result = await createComplaint({
      customer_id: form.customer_id,
      contact_id: form.contact_id || null,
      complaint_type_item_id: form.complaint_type_item_id,
      severity_item_id: form.severity_item_id,
      title: form.title.trim(),
      source_order_reference: form.source_order_reference.trim(),
      source_order_snapshot: { order_date: form.order_date, product_name: form.product_name.trim(), product_sku: form.product_sku.trim() },
      issue_description: form.issue_description.trim(),
      owner_employee_id: form.owner_employee_id || undefined,
      collaborator_employee_ids: form.collaborator_employee_ids,
    })
    createdComplaint.value = result.data
    emit('created', result.data)
    failedFiles.value = await uploadFiles(result.data.id, files.value)
    if (failedFiles.value.length) {
      ElMessage.warning(`客诉已创建，${failedFiles.value.length} 张图片上传失败，可立即重试。`)
    } else {
      ElMessage.success('客诉已创建。')
      emit('update:modelValue', false)
    }
  } catch (error) {
    ElMessage.error(complaintRequestMessage(error))
  } finally { submitting.value = false }
}

async function retryFailedImages() {
  if (!createdComplaint.value || !failedFiles.value.length || retrying.value) return
  retrying.value = true
  failedFiles.value = await uploadFiles(createdComplaint.value.id, failedFiles.value)
  retrying.value = false
  if (failedFiles.value.length) return ElMessage.error(`仍有 ${failedFiles.value.length} 张图片上传失败，请检查网络后重试。`)
  ElMessage.success('失败图片已全部补传。')
  emit('update:modelValue', false)
}

function close() {
  if (!submitting.value && !retrying.value) emit('update:modelValue', false)
}
</script>

<template>
  <AppWindowDialog class="complaint-operation-dialog complaint-create-dialog" :model-value="modelValue" title="新建客诉" :width="1140" :height="850" destroy-on-close :close-on-click-modal="!submitting && !retrying" :close-on-press-escape="!submitting && !retrying" :show-close="!submitting && !retrying" @update:model-value="value => { if (!value) close() }">
    <div class="create-body">
      <el-alert v-if="createdComplaint && failedFiles.length" class="upload-warning" type="warning" :closable="false" show-icon :title="`客诉 ${createdComplaint.complaint_code} 已创建，但有 ${failedFiles.length} 张图片上传失败。重试不会重复创建客诉。`" />
      <el-form label-position="top" :disabled="submitting || retrying || !!createdComplaint">
        <section class="form-column">
          <h3>基础信息</h3>
          <div class="two-columns">
            <el-form-item label="客户" required><el-select v-model="form.customer_id" filterable remote :remote-method="loadCustomers" :disabled="!!fixedCustomerId" placeholder="请选择客户" @change="loadContacts"><el-option v-if="fixedCustomerId" :label="fixedCustomerName" :value="fixedCustomerId" /><el-option v-for="item in customers" :key="item.id" :label="`${item.account_name}（${item.account_code}）`" :value="item.id" /></el-select></el-form-item>
            <el-form-item label="联系人"><el-select v-model="form.contact_id" clearable placeholder="请选择联系人"><el-option v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item>
            <el-form-item label="客诉类型" required><el-select v-model="form.complaint_type_item_id"><el-option v-for="item in complaintTypes" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></el-select></el-form-item>
            <el-form-item label="严重程度" required><el-select v-model="form.severity_item_id"><el-option v-for="item in severities" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></el-select></el-form-item>
          </div>
          <el-form-item label="客诉标题" required><el-input v-model="form.title" maxlength="250" show-word-limit /></el-form-item>
          <el-form-item label="问题描述" required><el-input v-model="form.issue_description" type="textarea" :rows="6" maxlength="5000" show-word-limit /></el-form-item>
        </section>
        <section class="form-column form-column--right">
          <h3>责任与来源</h3>
          <div class="two-columns"><el-form-item label="负责人"><el-select v-model="form.owner_employee_id" clearable placeholder="默认当前员工"><el-option v-for="item in options?.employees" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item><el-form-item label="协同人"><el-select v-model="form.collaborator_employee_ids" multiple collapse-tags><el-option v-for="item in options?.employees" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item></div>
          <h3 class="subheading">关联订单 <small>订单模块未接入前手工填写</small></h3>
          <div class="two-columns"><el-form-item label="订单号"><el-input v-model="form.source_order_reference" /></el-form-item><el-form-item label="订单日期"><el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="产品名称"><el-input v-model="form.product_name" /></el-form-item><el-form-item label="产品编号"><el-input v-model="form.product_sku" /></el-form-item></div>
          <el-form-item label="图片证据"><label class="upload-box"><input type="file" multiple accept="image/jpeg,image/png,image/webp" @change="selectImages" /><strong>选择本地图片</strong><span>JPG / PNG / WebP，单张不超过 5MB</span></label><div v-if="files.length" class="file-list"><span v-for="file in files" :key="`${file.name}-${file.size}`" :class="{ failed: failedFiles.includes(file) }">{{ file.name }}</span></div></el-form-item>
        </section>
      </el-form>
    </div>
    <template #footer><el-button :disabled="submitting || retrying" @click="close">{{ createdComplaint ? '稍后处理' : '取消' }}</el-button><el-button v-if="createdComplaint && failedFiles.length" type="primary" :loading="retrying" @click="retryFailedImages">重试失败图片</el-button><el-button v-else type="primary" :loading="submitting" :disabled="!!createdComplaint" @click="submit">创建客诉</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.create-body { height: 698px; overflow: hidden; margin: -30px; background: #faf9f6; }.create-body > :deep(.el-form) { height: 100%; display: grid; grid-template-columns: 1fr 1fr; }.form-column { padding: 26px 30px; overflow-y: auto; }.form-column--right { border-left: 1px solid #e5dfd7; background: #f6f3ed; }.form-column h3 { margin: 0 0 20px; color: #282522; font-size: 19px; }.form-column h3.subheading { margin-top: 10px; padding-top: 20px; border-top: 1px solid #e1dbd3; }.form-column h3 small { margin-left: 8px; color: #8c857e; font-size: 12px; font-weight: 400; }.two-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }.create-body :deep(.el-select), .create-body :deep(.el-date-editor) { width: 100%; }.create-body :deep(.el-textarea__inner), .create-body :deep(.el-input__wrapper), .create-body :deep(.el-select__wrapper) { background: #fffefb; box-shadow: 0 0 0 1px #ded8d0 inset; }.upload-box { min-height: 104px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 6px; border: 1px dashed #bdb5ac; border-radius: 4px; color: #8f3b24; background: #fdfbf7; cursor: pointer; }.upload-box input { display: none; }.upload-box span { color: #8d867f; font-size: 12px; }.file-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }.file-list span { padding: 5px 8px; border-radius: 3px; background: #ebe7df; font-size: 12px; }.file-list span.failed { color: #fff; background: #b53333; }.upload-warning { position: absolute; z-index: 2; top: 82px; right: 28px; left: 28px; }
</style>
