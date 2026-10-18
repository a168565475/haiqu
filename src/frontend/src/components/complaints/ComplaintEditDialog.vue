<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { updateComplaint } from '@/api/complaints'
import { fetchContacts } from '@/api/contacts'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { ContactListItem } from '@/types/contact'
import type { Complaint, ComplaintDictionaryItem, ComplaintOptions } from '@/types/complaint'
import { complaintRequestMessage } from '@/utils/complaintFeedback'

const props = defineProps<{
  modelValue: boolean
  complaint: Complaint | null
  etag: string | null
  options: ComplaintOptions | null
  complaintTypes: ComplaintDictionaryItem[]
  severities: ComplaintDictionaryItem[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; updated: [complaint: Complaint, etag: string | null] }>()
const contacts = ref<ContactListItem[]>([])
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({
  contact_id: '', complaint_type_item_id: '', severity_item_id: '', title: '', source_order_reference: '',
  order_date: '', product_name: '', product_sku: '', issue_description: '', owner_employee_id: '',
  collaborator_employee_ids: [] as string[],
})

watch(() => props.modelValue, async visible => {
  if (!visible || !props.complaint) return
  errorMessage.value = ''
  const snapshot = props.complaint.source_order_snapshot || {}
  Object.assign(form, {
    contact_id: props.complaint.contact?.id || '', complaint_type_item_id: props.complaint.complaint_type.id,
    severity_item_id: props.complaint.severity.id, title: props.complaint.title,
    source_order_reference: props.complaint.source_order_reference, order_date: String(snapshot.order_date || ''),
    product_name: String(snapshot.product_name || ''), product_sku: String(snapshot.product_sku || ''),
    issue_description: props.complaint.issue_description, owner_employee_id: props.complaint.owner.id,
    collaborator_employee_ids: props.complaint.collaborators.map(item => item.id),
  })
  try { contacts.value = (await fetchContacts({ customer_id: props.complaint.customer.id, page: 1, page_size: 100, status: 'ACTIVE' })).data }
  catch (error) { errorMessage.value = complaintRequestMessage(error) }
})

function close() { if (!submitting.value) emit('update:modelValue', false) }

async function submit() {
  if (submitting.value) return
  if (!form.complaint_type_item_id || !form.severity_item_id) return ElMessage.warning('请选择客诉类型和严重程度。')
  if (!form.title.trim()) return ElMessage.warning('请填写客诉标题。')
  if (!form.issue_description.trim()) return ElMessage.warning('请填写问题描述。')
  if (!props.complaint || !props.etag) return ElMessage.warning('缺少记录版本，请刷新详情。')
  submitting.value = true
  errorMessage.value = ''
  try {
    const result = await updateComplaint(props.complaint.id, {
      contact_id: form.contact_id || null,
      complaint_type_item_id: form.complaint_type_item_id,
      severity_item_id: form.severity_item_id,
      title: form.title.trim(),
      source_order_reference: form.source_order_reference.trim(),
      source_order_snapshot: { order_date: form.order_date, product_name: form.product_name.trim(), product_sku: form.product_sku.trim() },
      issue_description: form.issue_description.trim(),
      owner_employee_id: form.owner_employee_id,
      collaborator_employee_ids: form.collaborator_employee_ids,
    }, props.etag)
    emit('updated', result.data, result.etag)
    emit('update:modelValue', false)
    ElMessage.success('客诉信息已更新。')
  } catch (error) { errorMessage.value = complaintRequestMessage(error) }
  finally { submitting.value = false }
}
</script>

<template>
  <AppWindowDialog class="complaint-operation-dialog complaint-edit-dialog" :model-value="modelValue" title="编辑客诉信息" :width="1110" :height="864" destroy-on-close :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @update:model-value="value => { if (!value) close() }">
    <div class="edit-body">
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />
      <el-form label-position="top" :disabled="submitting">
        <section>
          <h3>客诉信息</h3>
          <div class="two-columns"><el-form-item label="联系人"><el-select v-model="form.contact_id" clearable><el-option v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item><el-form-item label="负责人"><el-select v-model="form.owner_employee_id"><el-option v-for="item in options?.employees" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item><el-form-item label="客诉类型" required><el-select v-model="form.complaint_type_item_id"><el-option v-for="item in complaintTypes" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></el-select></el-form-item><el-form-item label="严重程度" required><el-select v-model="form.severity_item_id"><el-option v-for="item in severities" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></el-select></el-form-item></div>
          <el-form-item label="客诉标题" required><el-input v-model="form.title" maxlength="250" show-word-limit /></el-form-item>
          <el-form-item label="问题描述" required><el-input v-model="form.issue_description" type="textarea" :rows="7" maxlength="5000" show-word-limit /></el-form-item>
        </section>
        <section class="right-column">
          <h3>责任协同</h3>
          <el-form-item label="协同人"><el-select v-model="form.collaborator_employee_ids" multiple collapse-tags><el-option v-for="item in options?.employees" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item>
          <h3 class="subheading">关联订单</h3>
          <div class="two-columns"><el-form-item label="订单号"><el-input v-model="form.source_order_reference" /></el-form-item><el-form-item label="订单日期"><el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="产品名称"><el-input v-model="form.product_name" /></el-form-item><el-form-item label="产品编号"><el-input v-model="form.product_sku" /></el-form-item></div>
          <p class="readonly-note">客户归属及原始客户信息不可在此修改，客户合并后的追溯关系由系统保留。</p>
        </section>
      </el-form>
    </div>
    <template #footer><el-button :disabled="submitting" @click="close">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">保存修改</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;.edit-body { height: auto; overflow: visible; margin: 0; background: transparent; font-size: 13px; }.edit-body > :deep(.el-alert) { position: static; z-index: 2; margin-bottom: 14px; }.edit-body > :deep(.el-form) { height: auto; display: grid; grid-template-columns: minmax(0,1.15fr) minmax(0,.85fr); gap: 14px; }.edit-body section { @include detail.inset; padding: 16px; overflow-y: visible; }.edit-body h3 { margin: 0 0 14px; font-size: 16px; font-family: var(--erp-font-body); line-height: 24px; }.edit-body h3.subheading { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--erp-color-border); }.two-columns { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 14px; }.edit-body :deep(.el-select), .edit-body :deep(.el-date-editor) { width: 100%; }.edit-body :deep(.el-input__wrapper), .edit-body :deep(.el-select__wrapper), .edit-body :deep(.el-textarea__inner) { background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-color-border) inset; }.readonly-note { margin-top: 18px; padding: 14px; border-left: 3px solid var(--erp-color-warning-border); color: var(--erp-color-text-regular); background: var(--erp-color-subtle); font-size: 13px; line-height: 21px; }:global(.complaint-edit-dialog) { container-type:inline-size; }@container (max-width:740px) { .edit-body > :deep(.el-form) { grid-template-columns:minmax(0,1fr); } }@container (max-width:440px) { .two-columns { grid-template-columns:minmax(0,1fr); } }
</style>
