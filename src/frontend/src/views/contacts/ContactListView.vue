<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { isAxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Operation, Plus, Rank, Refresh, Search, Upload } from '@element-plus/icons-vue'

import ContactTable from '@/components/contacts/ContactTable.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ResizableDrawerHandle from '@/components/ResizableDrawerHandle.vue'
import {
  bulkCreateContactTasks,
  bulkMarkContactsLeft,
  checkContactDuplicate,
  contactImportTemplateUrl,
  createContact,
  createContactEmploymentRecord,
  createSavedContactView,
  deleteContact,
  fetchContact,
  fetchContactEmploymentHistory,
  fetchContactOptions,
  fetchContacts,
  fetchCustomerContacts,
  fetchImportRecords,
  fetchSavedContactViews,
  markContactLeft,
  updateContact,
  uploadContactImport,
} from '@/api/contacts'
import { fetchCustomerOptions, fetchCustomers } from '@/api/customers'
import { useOptions } from '@/composables/useOptions'
import { useAuthStore } from '@/stores/auth'
import { toContactOptions, withHistoricalContactOption } from '@/utils/referenceOptions'
import type { CustomerListItem, CustomerOwnerOption } from '@/types/customer'
import type {
  ContactCreateInput,
  CustomerContactSummary,
  ContactPrioritySummary,
  ContactDetail,
  ContactDuplicateSummary,
  ContactEmploymentEvent,
  ContactListItem,
  ContactListQuery,
  ContactOptions,
  ContactRoleType,
  ImportBatch,
  ImportRecord,
  SavedContactView,
} from '@/types/contact'

const route = useRoute()
const authStore = useAuthStore()
const languageOptions = useOptions('CONTACT_LANGUAGE')
const timezoneOptions = useOptions('CONTACT_TIMEZONE')
const customerId = computed(() => typeof route.params.customerId === 'string' ? route.params.customerId : '')
const showCustomer = computed(() => !customerId.value)
const embeddedV2 = computed(() => Boolean(customerId.value))
const loading = ref(false)
const rows = ref<ContactListItem[]>([])
const contactSummary = ref<CustomerContactSummary | null>(null)
const selected = ref<ContactListItem[]>([])
const total = ref(0)
const customerOptions = ref<CustomerListItem[]>([])
const ownerOptions = ref<CustomerOwnerOption[]>([])
const savedViews = ref<SavedContactView[]>([])
const contactOptions = ref<ContactOptions>({ role_options: [], status_options: [], language_options: [], timezone_options: [] })

const query = reactive<ContactListQuery>({
  q: '', status: '', role_type: '', last_interaction: '', ordering: 'display_name', page: 1, page_size: 20,
})
const allColumns = [
  { value: 'name', label: '姓名' }, { value: 'customer', label: '客户' },
  { value: 'position', label: '职位' }, { value: 'department', label: '部门' },
  { value: 'roles', label: '决策角色' }, { value: 'methods', label: '联系方式' },
  { value: 'interaction', label: '最近互动' }, { value: 'status', label: '任职状态' },
  { value: 'relationship', label: '关系与偏好' },
]
const visibleColumns = ref(allColumns.map((item) => item.value))
const columnsVisible = ref(false)
const compact = ref(true)
const saveViewVisible = ref(false)
const savedViewName = ref('')

const activeCount = computed(() => embeddedV2.value ? contactSummary.value?.active ?? '—'
  : rows.value.filter(item => item.status === 'ACTIVE').length)
const decisionMakerCount = computed(() => embeddedV2.value ? contactSummary.value?.decision_maker ?? '—'
  : rows.value.filter(item => item.status === 'ACTIVE' && item.active_roles.some(role => role.role_type === 'DECISION_MAKER')).length)
const primaryContactCount = computed(() => contactSummary.value?.primary ?? '—')
const leftContactCount = computed(() => contactSummary.value?.left ?? '—')
const staleContactCount = computed(() => contactSummary.value?.stale ?? '—')
const priorityContact = computed(() => [...(contactSummary.value?.priority_candidates || [])]
  .sort((a, b) => a.display_name.localeCompare(b.display_name, 'zh-CN'))[0] || null)

const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'edit' | 'view'>('create')
const drawerLoading = ref(false)
const editingContact = ref<ContactDetail | null>(null)
const editingEtag = ref<string | null>(null)
const form = reactive({
  customer_id: '', display_name: '', english_name: '', position_title: '', department_name: '',
  role_type: '' as ContactRoleType | '', status: 'ACTIVE' as 'ACTIVE' | 'INACTIVE',
  email: '', phone: '', preferred_language_code: '', timezone_code: '',
  is_key_contact: false, is_primary_contact: false, notes: '',
})
const duplicateChecking = ref(false)
const duplicateResults = ref<ContactDuplicateSummary[]>([])
let duplicateTimer: ReturnType<typeof setTimeout> | null = null

const historyVisible = ref(false)
const historyLoading = ref(false)
const historyContact = ref<ContactDetail | null>(null)
const historyEtag = ref<string | null>(null)
const employmentHistory = ref<ContactEmploymentEvent[]>([])
const recordVisible = ref(false)
const recordSaving = ref(false)
const recordForm = reactive({ effective_on: '', title: '', position_title: '', department_name: '', role_types: [] as ContactRoleType[], is_primary_contact: false, notes: '' })

const leaveVisible = ref(false)
const leaveLoading = ref(false)
const leavingContact = ref<ContactDetail | null>(null)
const leavingEtag = ref<string | null>(null)
const leaveForm = reactive({
  effective_date: '', replacement_contact_id: '',
  unfinished_task_policy: 'TRANSFER_TO_OWNER' as 'TRANSFER_TO_OWNER' | 'KEEP_ASSIGNEE' | 'CANCEL_OPEN',
  preserve_history: true as const, remove_from_marketing: true, notify_stakeholders: false, reason: '',
})
const replacementOptions = computed(() => rows.value.filter((item) => (
  item.status === 'ACTIVE' && item.id !== leavingContact.value?.id
)))

const taskVisible = ref(false)
const taskForm = reactive({
  title: '', description: '', priority: 'NORMAL', due_at: '',
  assignee_mode: 'CUSTOMER_OWNER', assignee_employee_id: '',
})
const importVisible = ref(false)
const importFile = ref<File | null>(null)
const importAllowDuplicates = ref(false)
const importBatch = ref<ImportBatch | null>(null)
const importRecords = ref<ImportRecord[]>([])
const importing = ref(false)

const canCreate = computed(() => authStore.hasPermission('customers.add_customercontact'))
const canChange = computed(() => authStore.hasPermission('customers.change_customercontact'))
const canDelete = computed(() => authStore.hasPermission('customers.delete_customercontact'))
const canBulkLeave = computed(() => authStore.hasPermission('customers.bulk_change_customercontact'))
const canBulkTask = computed(() => authStore.hasPermission('customers.bulk_create_contact_task'))
const canImport = computed(() => authStore.hasPermission('customers.import_customercontact'))
const isReadOnly = computed(() => drawerMode.value === 'view')
const legacyContactEntries = computed(() => Object.entries(editingContact.value?.legacy_source_data?.fields || {}))
const hasDuplicate = computed(() => duplicateResults.value.some((item) => (
  item.same_customer_matches.length || item.cross_customer_matches.length || item.hidden_cross_customer_count
)))
const duplicateTitle = computed(() => {
  if (duplicateChecking.value) return '正在实时检查邮箱和电话重复情况…'
  if (hasDuplicate.value) return '发现重复联系方式，请确认现有联系人后再保存'
  return '邮箱与电话未发现其他客户联系人重复'
})

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function relativeInteraction(contact: ContactPrioritySummary): string {
  if (!contact.last_interaction) return '从未互动'
  const occurredAt = new Date(contact.last_interaction.occurred_at).getTime()
  if (!Number.isFinite(occurredAt)) return '互动时间未知'
  const hours = Math.max(0, Math.floor((Date.now() - occurredAt) / 3_600_000))
  if (hours < 24) return `${hours} 小时前`
  if (hours < 48) return '昨天'
  if (hours < 24 * 30) return `${Math.floor(hours / 24)} 天前`
  return new Date(occurredAt).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

const priorityContactText = computed(() => {
  const contact = priorityContact.value
  if (!contact) return ''
  const role = contact.active_roles[0]?.role_type_display || contact.position_title || '关键联系人'
  return `优先联系：${contact.display_name} · ${role} · 最近互动 ${relativeInteraction(contact)}`
})

function errorMessage(error: unknown): string {
  if (!isAxiosError(error)) return '操作失败，请稍后重试。'
  if (!error.response) return '网络连接异常，表单内容已保留，请检查服务后重试。'
  const status = error.response.status
  const data = error.response.data as Record<string, unknown> | undefined
  const detail = typeof data?.detail === 'string' ? data.detail : undefined
  const apiError = data?.error as Record<string, unknown> | undefined
  const message = detail || (typeof apiError?.message === 'string' ? apiError.message : '')
  if (message) return message
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '没有执行此操作的权限。'
  if (status === 409) return '数据存在业务冲突，请检查后重试。'
  if (status === 412) return '联系人已被其他人修改，请刷新最新数据后重试。'
  if (status === 428) return '缺少数据版本，请重新打开联系人后再保存。'
  if (status >= 500) return '后端服务异常，表单内容已保留，请稍后重试。'
  if (data) {
    const first = Object.values(data)[0]
    if (Array.isArray(first) && typeof first[0] === 'string') return first[0]
    if (typeof first === 'string') return first
  }
  return '操作失败，请稍后重试。'
}

let contactsRequest = 0
async function loadContacts(): Promise<void> {
  const requestId = ++contactsRequest
  const targetCustomerId = customerId.value
  loading.value = true
  try {
    const result = targetCustomerId
      ? await fetchCustomerContacts(targetCustomerId, { ...query, include_summary: true })
      : await fetchContacts({ ...query })
    if (requestId !== contactsRequest || targetCustomerId !== customerId.value) return
    rows.value = result.data
    total.value = result.meta.total
    selected.value = []
    contactSummary.value = result.summary || null
  } catch (error) {
    if (requestId !== contactsRequest) return
    ElMessage.error(errorMessage(error))
  } finally {
    if (requestId === contactsRequest) loading.value = false
  }
}

function resetFilters(): void {
  Object.assign(query, { q: '', status: '', role_type: '', last_interaction: '', page: 1 })
  void loadContacts()
}

function resetForm(): void {
  Object.assign(form, {
    customer_id: customerId.value, display_name: '', english_name: '', position_title: '', department_name: '',
    role_type: '', status: 'ACTIVE', email: '', phone: '', preferred_language_code: '', timezone_code: '',
    is_key_contact: false, is_primary_contact: false, notes: '',
  })
  editingContact.value = null
  editingEtag.value = null
  duplicateResults.value = []
}

function methodValue(contact: ContactDetail, types: string[]): string {
  return contact.methods.find((item) => types.includes(item.method_type))?.display_value || ''
}

async function openCreate(): Promise<void> {
  resetForm()
  drawerMode.value = 'create'
  drawerVisible.value = true
  if (showCustomer.value && !customerOptions.value.length) {
    customerOptions.value = (await fetchCustomers({ page_size: 100 })).data
  }
}

async function openContact(row: ContactListItem, mode: 'edit' | 'view'): Promise<void> {
  drawerMode.value = mode
  drawerVisible.value = true
  drawerLoading.value = true
  duplicateResults.value = []
  try {
    const result = await fetchContact(row.id)
    editingContact.value = result.data
    editingEtag.value = result.etag
    Object.assign(form, {
      customer_id: result.data.customer.id,
      display_name: result.data.display_name,
      english_name: result.data.english_name,
      position_title: result.data.position_title,
      department_name: result.data.department_name,
      role_type: result.data.active_roles[0]?.role_type || '',
      status: result.data.status === 'INACTIVE' ? 'INACTIVE' : 'ACTIVE',
      email: methodValue(result.data, ['EMAIL']),
      phone: methodValue(result.data, ['MOBILE', 'PHONE']),
      preferred_language_code: result.data.preferred_language_code,
      timezone_code: result.data.timezone_code,
      is_key_contact: result.data.is_key_contact,
      is_primary_contact: result.data.is_primary_contact,
      notes: result.data.notes,
    })
    contactOptions.value = {
      ...contactOptions.value,
      language_options: withHistoricalContactOption(
        contactOptions.value.language_options,
        result.data.preferred_language_code,
      ),
      timezone_options: withHistoricalContactOption(
        contactOptions.value.timezone_options,
        result.data.timezone_code,
      ),
    }
  } catch (error) {
    drawerVisible.value = false
    ElMessage.error(errorMessage(error))
  } finally {
    drawerLoading.value = false
  }
}

async function deleteContactRow(row: ContactListItem): Promise<void> {
  try {
    const current = await fetchContact(row.id)
    await ElMessageBox.confirm(
      `确定永久删除联系人「${current.data.display_name}」吗？其联系方式、任职记录及关联业务数据会一并删除，且无法恢复。`,
      '永久删除联系人',
      { type: 'error', confirmButtonText: '确认永久删除', cancelButtonText: '取消', customClass: embeddedV2.value ? 'customer-detail-message-box' : '' },
    )
    const result = await deleteContact(row.id, current.etag || '')
    ElMessage.success(`联系人已永久删除，同时删除 ${result.deleted_count} 条关联数据。`)
    await loadContacts()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function runDuplicateCheck(): Promise<void> {
  if (isReadOnly.value || !form.customer_id) return
  const checks = [
    form.email.trim() ? { method_type: 'EMAIL' as const, value: form.email.trim() } : null,
    form.phone.trim() ? { method_type: 'MOBILE' as const, value: form.phone.trim() } : null,
  ].filter(Boolean) as Array<{ method_type: 'EMAIL' | 'MOBILE'; value: string }>
  if (!checks.length) {
    duplicateResults.value = []
    return
  }
  duplicateChecking.value = true
  try {
    duplicateResults.value = await Promise.all(checks.map((item) => checkContactDuplicate({
      customer_id: form.customer_id,
      method_type: item.method_type,
      value: item.value,
      exclude_contact_id: editingContact.value?.id,
    })))
  } catch (error) {
    ElMessage.warning(`实时查重失败：${errorMessage(error)}`)
  } finally {
    duplicateChecking.value = false
  }
}

function scheduleDuplicateCheck(): void {
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = setTimeout(() => void runDuplicateCheck(), 450)
}

function contactMethods() {
  return [
    form.email.trim() ? { method_type: 'EMAIL' as const, raw_value: form.email.trim(), is_primary: true, is_preferred: true } : null,
    form.phone.trim() ? { method_type: 'MOBILE' as const, raw_value: form.phone.trim(), is_primary: true, is_preferred: true } : null,
  ].filter(Boolean) as ContactCreateInput['methods']
}

async function submitContact(confirmed = false): Promise<void> {
  if (!form.display_name.trim()) return void ElMessage.warning('请填写联系人姓名。')
  if (!form.customer_id) return void ElMessage.warning('请选择所属客户。')
  if (drawerMode.value === 'create' && !contactMethods().length) return void ElMessage.warning('请至少填写邮箱或电话。')
  if (hasDuplicate.value && !confirmed) {
    try {
      await ElMessageBox.confirm('检测到重复联系方式，确认已核对现有联系人并继续保存吗？', '重复联系方式提醒', {
        type: 'warning', confirmButtonText: '确认继续', cancelButtonText: '返回检查',
        customClass: embeddedV2.value ? 'customer-detail-message-box' : '',
      })
    } catch {
      return
    }
    return submitContact(true)
  }
  drawerLoading.value = true
  try {
    const payload = {
      display_name: form.display_name.trim(), english_name: form.english_name.trim(),
      position_title: form.position_title.trim(), department_name: form.department_name.trim(),
      preferred_language_code: form.preferred_language_code, timezone_code: form.timezone_code,
      is_key_contact: form.is_key_contact, is_primary_contact: form.is_primary_contact,
      status: form.status, notes: form.notes,
      role_types: form.role_type ? [form.role_type] : [], methods: contactMethods(),
      duplicate_acknowledged: confirmed,
    }
    if (drawerMode.value === 'create') {
      await createContact({ customer_id: form.customer_id, ...payload })
    } else if (editingContact.value && editingEtag.value) {
      await updateContact(editingContact.value.id, payload, editingEtag.value)
    }
    drawerVisible.value = false
    ElMessage.success('联系人已保存。')
    await loadContacts()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    drawerLoading.value = false
  }
}

async function openHistory(row: ContactListItem): Promise<void> {
  historyVisible.value = true
  historyLoading.value = true
  try {
    const [detail, events] = await Promise.all([fetchContact(row.id), fetchContactEmploymentHistory(row.id)])
    historyContact.value = detail.data
    historyEtag.value = detail.etag
    employmentHistory.value = events
  } catch (error) {
    historyVisible.value = false
    ElMessage.error(errorMessage(error))
  } finally {
    historyLoading.value = false
  }
}

function openEmploymentRecord(): void {
  if (!historyContact.value) return
  Object.assign(recordForm, {
    effective_on: today(), title: '更新任职记录', position_title: historyContact.value.position_title,
    department_name: historyContact.value.department_name,
    role_types: historyContact.value.active_roles.map((item) => item.role_type),
    is_primary_contact: historyContact.value.is_primary_contact, notes: '',
  })
  recordVisible.value = true
}

async function submitEmploymentRecord(): Promise<void> {
  if (!historyContact.value || !historyEtag.value || !recordForm.title.trim()) return
  recordSaving.value = true
  try {
    const result = await createContactEmploymentRecord(historyContact.value.id, { ...recordForm }, historyEtag.value)
    historyEtag.value = result.etag
    employmentHistory.value = await fetchContactEmploymentHistory(historyContact.value.id)
    historyContact.value = (await fetchContact(historyContact.value.id)).data
    recordVisible.value = false
    ElMessage.success('任职记录已保存。')
    await loadContacts()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    recordSaving.value = false
  }
}

async function openLeave(row: ContactListItem): Promise<void> {
  leaveLoading.value = true
  leaveVisible.value = true
  Object.assign(leaveForm, {
    effective_date: today(), replacement_contact_id: '', unfinished_task_policy: 'TRANSFER_TO_OWNER',
    remove_from_marketing: true, notify_stakeholders: false, reason: '',
  })
  try {
    const detail = await fetchContact(row.id)
    leavingContact.value = detail.data
    leavingEtag.value = detail.etag
  } catch (error) {
    leaveVisible.value = false
    ElMessage.error(errorMessage(error))
  } finally {
    leaveLoading.value = false
  }
}

async function submitLeave(): Promise<void> {
  if (!leavingContact.value || !leavingEtag.value) return
  if (leavingContact.value.is_primary_contact && replacementOptions.value.length && !leaveForm.replacement_contact_id) {
    return void ElMessage.warning('该联系人是主要联系人，请选择新的主要联系人。')
  }
  leaveLoading.value = true
  try {
    await markContactLeft(leavingContact.value.id, {
      ...leaveForm,
      replacement_contact_id: leaveForm.replacement_contact_id || null,
      preserve_history: true,
    }, leavingEtag.value)
    leaveVisible.value = false
    ElMessage.success('离职交接已完成，历史记录已保留。')
    await loadContacts()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    leaveLoading.value = false
  }
}

async function openBulkLeave(): Promise<void> {
  if (!selected.value.length) return
  try {
    const { value } = await ElMessageBox.prompt('批量离职仅适用于无需主要联系人接替的记录，请填写原因。', '批量标记离职', {
      inputPlaceholder: '离职原因', inputValidator: (input) => Boolean(input.trim()) || '请填写原因',
      customClass: embeddedV2.value ? 'customer-detail-message-box' : '',
    })
    await bulkMarkContactsLeft(selected.value.map((item) => item.id), value)
    ElMessage.success('批量离职处理完成。')
    await loadContacts()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function openBulkTask(): Promise<void> {
  if (!selected.value.length) return
  Object.assign(taskForm, { title: '跟进联系人', description: '', priority: 'NORMAL', due_at: '', assignee_mode: 'CUSTOMER_OWNER', assignee_employee_id: '' })
  if (!ownerOptions.value.length) ownerOptions.value = (await fetchCustomerOptions()).owner_options
  taskVisible.value = true
}

async function submitBulkTask(): Promise<void> {
  if (!taskForm.title.trim() || !taskForm.due_at) return void ElMessage.warning('请填写任务标题和截止时间。')
  try {
    await bulkCreateContactTasks({ contact_ids: selected.value.map((item) => item.id), ...taskForm, assignee_employee_id: taskForm.assignee_mode === 'SPECIFIC' ? taskForm.assignee_employee_id : undefined })
    taskVisible.value = false
    ElMessage.success('批量任务已创建。')
    await loadContacts()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function onFileChange(event: Event): void {
  importFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function submitImport(): Promise<void> {
  if (!importFile.value) return void ElMessage.warning('请选择 CSV 或 XLSX 文件。')
  importing.value = true
  try {
    importBatch.value = await uploadContactImport(importFile.value, customerId.value || undefined, importAllowDuplicates.value)
    importRecords.value = importBatch.value.failure_count ? await fetchImportRecords(importBatch.value.id) : []
    ElMessage.success('导入处理完成。')
    await loadContacts()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    importing.value = false
  }
}

async function saveCurrentView(): Promise<void> {
  if (!savedViewName.value.trim()) return
  try {
    await createSavedContactView({
      view_name: savedViewName.value,
      filter_definition: Object.fromEntries(Object.entries(query).filter(([, value]) => value !== '' && value !== undefined)),
      column_definition: visibleColumns.value,
      sort_definition: query.ordering ? [query.ordering] : [],
    })
    savedViews.value = await fetchSavedContactViews()
    saveViewVisible.value = false
    ElMessage.success('视图已保存。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function applySavedView(view: SavedContactView): Promise<void> {
  Object.assign(query, { q: '', status: '', role_type: '', last_interaction: '', ordering: 'display_name', page: 1 }, view.filter_definition)
  visibleColumns.value = view.column_definition.length ? [...view.column_definition] : allColumns.map((item) => item.value)
  await loadContacts()
}

watch(() => [form.email, form.phone, form.customer_id], scheduleDuplicateCheck)
watch(customerId, async () => {
  query.page = 1
  query.status = ''
  contactSummary.value = null
  await loadContacts()
})
onBeforeUnmount(() => { contactsRequest += 1; if (duplicateTimer) clearTimeout(duplicateTimer) })
  onMounted(async () => {
    const contactsLoading = loadContacts()
    const [legacyOptions] = await Promise.all([
    fetchContactOptions().catch(() => contactOptions.value),
    fetchSavedContactViews().then((data) => { savedViews.value = data }).catch(() => undefined),
  ])
  contactOptions.value = legacyOptions
  try {
    const [languages, timezones] = await Promise.all([languageOptions.load(), timezoneOptions.load()])
    if (languageOptions.configVersion.value !== null) {
      contactOptions.value = {
        ...legacyOptions,
        language_options: toContactOptions(languages),
        timezone_options: toContactOptions(timezones, 'timezone_code'),
      }
    }
  } catch {
    ElMessage.warning('统一配置暂时不可用，联系人页面已回退到兼容选项。')
  }
    await contactsLoading
})
</script>

<template>
  <section class="contact-page" :class="{ 'is-embedded': !showCustomer, 'contact-page--v2': embeddedV2 }" data-customer-contacts-v2>
    <section v-if="embeddedV2" class="contact-summary-strip" aria-label="联系人概况">
      <article><span>联系人</span><strong>{{ contactSummary?.total ?? '—' }}</strong></article>
      <article><span>关键决策人</span><strong>{{ decisionMakerCount }}</strong></article>
      <article><span>主要联系人</span><strong>{{ primaryContactCount }}</strong></article>
      <article><span>30天未联系</span><strong>{{ staleContactCount }}</strong></article>
      <article><span>已离职</span><strong>{{ leftContactCount }}</strong></article>
      <p v-if="priorityContactText" :title="priorityContactText">{{ priorityContactText }}</p>
    </section>

    <header class="contact-heading">
      <div><h2>联系人管理</h2><p>共 {{ activeCount }} 位在职联系人 · {{ decisionMakerCount }} 位关键决策人</p></div>
      <div v-if="!embeddedV2" class="heading-actions">
        <ElButton v-if="canImport" :icon="Upload" @click="importVisible = true">导入联系人</ElButton>
        <ElButton v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">新增联系人</ElButton>
      </div>
    </header>

    <section class="filter-card">
      <ElInput v-model="query.q" :prefix-icon="Search" clearable placeholder="搜索姓名、职位、邮箱" @keyup.enter="query.page = 1; loadContacts()" />
      <ElSelect v-model="query.role_type" clearable placeholder="决策角色：全部"><ElOption v-for="item in contactOptions.role_options" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="query.status" clearable placeholder="任职状态：全部"><ElOption v-for="item in contactOptions.status_options" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="query.last_interaction" clearable placeholder="最近互动：全部"><ElOption label="7 天内" value="WITHIN_7_DAYS" /><ElOption label="30 天内" value="WITHIN_30_DAYS" /><ElOption label="90 天内" value="WITHIN_90_DAYS" /><ElOption label="从未互动" value="NEVER" /></ElSelect>
      <ElButton type="primary" @click="query.page = 1; loadContacts()">查询</ElButton>
      <ElButton @click="resetFilters">重置</ElButton>
    </section>

    <section class="contact-toolbar">
      <div class="batch-actions"><span>已选择 {{ selected.length }} 项</span><ElButton v-if="canBulkTask" :disabled="!selected.length" @click="openBulkTask">批量发任务</ElButton><ElButton v-if="canBulkLeave" :disabled="!selected.length" @click="openBulkLeave">标记离职</ElButton></div>
      <div class="view-actions">
        <ElButton v-if="embeddedV2 && canImport" class="toolbar-import-button" :icon="Upload" @click="importVisible = true">导入联系人</ElButton>
        <ElButton v-if="embeddedV2 && canCreate" class="toolbar-create-button" type="primary" :icon="Plus" @click="openCreate">新增联系人</ElButton>
        <ElDropdown v-if="embeddedV2 && savedViews.length" @command="applySavedView"><ElButton class="toolbar-save-view-button">保存视图</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem v-for="view in savedViews" :key="view.id" :command="view">{{ view.view_name }}</ElDropdownItem></ElDropdownMenu></template></ElDropdown>
        <ElButton v-else-if="embeddedV2" class="toolbar-save-view-button" @click="savedViewName = ''; saveViewVisible = true">保存视图</ElButton>
        <ElDropdown v-if="!embeddedV2 && savedViews.length" @command="applySavedView"><ElButton>保存视图</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem v-for="view in savedViews" :key="view.id" :command="view">{{ view.view_name }}</ElDropdownItem></ElDropdownMenu></template></ElDropdown>
        <ElButton v-else-if="!embeddedV2" @click="savedViewName = ''; saveViewVisible = true">保存视图</ElButton>
        <ElButton :icon="Operation" @click="columnsVisible = true">列设置</ElButton>
        <ElButton v-if="!embeddedV2" :icon="Rank" :class="{ 'is-density-active': compact }" @click="compact = !compact">紧凑显示</ElButton>
        <ElButton v-if="embeddedV2" :icon="Refresh" @click="loadContacts">刷新</ElButton>
        <ElButton v-else :icon="Refresh" circle aria-label="刷新" @click="loadContacts" />
      </div>
    </section>

    <section class="table-card">
      <ContactTable :rows="rows" :loading="loading" :show-customer="showCustomer" :visible-columns="visibleColumns" :can-change="canChange" :can-leave="canChange" :can-delete="canDelete" :compact="compact" :v2="embeddedV2" @selection-change="selected = $event" @view="openContact($event, 'view')" @edit="openContact($event, 'edit')" @history="openHistory" @leave="openLeave" @delete="deleteContactRow" />
      <footer class="table-footer"><span>共 {{ total }} 条<span v-if="rows.some((item) => item.status === 'LEFT')"> · 其中 {{ rows.filter((item) => item.status === 'LEFT').length }} 位已离职</span></span><ElPagination v-model:current-page="query.page" v-model:page-size="query.page_size" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @change="loadContacts" /></footer>
    </section>

    <ElDrawer v-model="drawerVisible" :title="drawerMode === 'create' ? '新增联系人' : drawerMode === 'edit' ? '编辑联系人' : '联系人详情'" size="min(560px, 100vw)" :class="['cus05-contact-drawer', { 'customer-detail-drawer': embeddedV2 }]" destroy-on-close>
      <ResizableDrawerHandle />
      <ElForm v-loading="drawerLoading" label-position="top" class="contact-form">
        <ElFormItem v-if="showCustomer && drawerMode === 'create'" label="所属客户 *" required><ElSelect v-model="form.customer_id" filterable :disabled="isReadOnly" placeholder="选择客户"><ElOption v-for="customer in customerOptions" :key="customer.id" :label="`${customer.account_name}（${customer.account_code}）`" :value="customer.id" /></ElSelect></ElFormItem>
        <div class="form-grid"><ElFormItem label="姓名 *" required><ElInput v-model="form.display_name" :disabled="isReadOnly" maxlength="150" /></ElFormItem><ElFormItem label="英文名"><ElInput v-model="form.english_name" :disabled="isReadOnly" maxlength="150" /></ElFormItem></div>
        <div class="form-grid"><ElFormItem label="职位"><ElInput v-model="form.position_title" :disabled="isReadOnly" maxlength="150" placeholder="例如：采购经理（演示）" /></ElFormItem><ElFormItem label="部门"><ElInput v-model="form.department_name" :disabled="isReadOnly" maxlength="150" placeholder="例如：采购部（演示）" /></ElFormItem></div>
        <div class="form-grid"><ElFormItem label="决策角色"><ElSelect v-model="form.role_type" :disabled="isReadOnly" clearable><ElOption v-for="item in contactOptions.role_options" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem><ElFormItem label="任职状态"><ElSelect v-model="form.status" :disabled="isReadOnly"><ElOption v-for="item in contactOptions.status_options.filter((option) => option.value !== 'LEFT')" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem></div>
        <div class="form-grid"><ElFormItem label="邮箱"><ElInput v-model="form.email" :disabled="isReadOnly" /></ElFormItem><ElFormItem label="电话"><ElInput v-model="form.phone" :disabled="isReadOnly" /></ElFormItem></div>
        <div class="form-grid"><ElFormItem label="首选语言"><ElSelect v-model="form.preferred_language_code" :disabled="isReadOnly" clearable><ElOption v-for="item in contactOptions.language_options" :key="item.value" :label="item.label" :value="item.value" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="时区"><ElSelect v-model="form.timezone_code" :disabled="isReadOnly" clearable><ElOption v-for="item in contactOptions.timezone_options" :key="item.value" :label="item.label" :value="item.value" :disabled="item.disabled" /></ElSelect></ElFormItem></div>
        <div class="duplicate-notice" :class="{ warning: hasDuplicate }"><strong>{{ duplicateTitle }}</strong><span>{{ hasDuplicate ? '请选择已有联系人，或确认重复风险后继续保存。' : '提交时再次实时校验，避免跨客户重复建档' }}</span></div>
        <ElCheckbox v-model="form.is_primary_contact" :disabled="isReadOnly">设为该客户主要联系人</ElCheckbox>
        <ElCheckbox v-model="form.is_key_contact" :disabled="isReadOnly">标记为关键联系人</ElCheckbox>
        <ElFormItem label="内部备注" class="notes-field"><ElInput v-model="form.notes" :disabled="isReadOnly" type="textarea" :rows="3" /></ElFormItem>
        <section v-if="isReadOnly && legacyContactEntries.length" class="legacy-contact-data">
          <header><strong>旧 ERP 补充资料</strong><span>仅展示源文件中的非空字段</span></header>
          <dl><div v-for="([label, value]) in legacyContactEntries" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
        </section>
      </ElForm>
      <template #footer><ElButton @click="drawerVisible = false">{{ isReadOnly ? '关闭' : '取消' }}</ElButton><ElButton v-if="!isReadOnly" type="primary" :loading="drawerLoading" @click="submitContact()">保存联系人</ElButton></template>
    </ElDrawer>

    <ElDrawer v-model="historyVisible" size="min(1260px, 100vw)" :class="['cus05-history-drawer', { 'customer-detail-drawer': embeddedV2 }]" :with-header="false" destroy-on-close>
      <ResizableDrawerHandle />
      <section v-loading="historyLoading" class="history-panel">
        <header><div><h2>{{ historyContact?.display_name }} · 任职历史</h2><p>保留职位、部门、决策角色和主要联系人变化</p></div><ElButton v-if="canChange && historyContact?.status !== 'LEFT'" type="primary" @click="openEmploymentRecord">新增任职记录</ElButton></header>
        <article v-if="historyContact" class="current-employment"><span class="history-avatar">{{ historyContact.display_name.slice(0, 2) }}</span><div><strong>{{ historyContact.position_title || '未填写职位' }} · {{ historyContact.department_name || '未填写部门' }}</strong><p>{{ historyContact.created_at.slice(0, 10) }} 至今 · {{ historyContact.customer.account_name }}</p><small>{{ historyContact.is_primary_contact ? '主要联系人 · ' : '' }}{{ historyContact.active_roles.map((item) => item.role_type_display).join('、') || '未设置决策角色' }}</small></div><ElTag type="success">{{ historyContact.status_display }}</ElTag><ElTag v-if="historyContact.is_primary_contact">主要联系人</ElTag></article>
        <div class="history-timeline"><article v-for="item in employmentHistory" :key="item.id"><div class="history-date"><strong>{{ item.effective_on }}</strong><span>{{ item.event_type_display }}</span></div><div><h3>{{ item.title }}</h3><p>{{ item.position_title || '未填写职位' }} · {{ item.department_name || '未填写部门' }}</p><small>{{ item.actor_employee ? `由 ${item.actor_employee.display_name} 更新` : '系统迁移记录' }}<template v-if="item.notes">；{{ item.notes }}</template></small></div></article><ElEmpty v-if="!employmentHistory.length" description="暂无任职历史" /></div>
      </section>
    </ElDrawer>

    <AppWindowDialog v-model="recordVisible" title="新增任职记录" :width="570" :height="650"><ElForm label-position="top"><ElFormItem label="生效日期" required><ElDatePicker v-model="recordForm.effective_on" type="date" value-format="YYYY-MM-DD" /></ElFormItem><ElFormItem label="记录标题" required><ElInput v-model="recordForm.title" /></ElFormItem><div class="form-grid"><ElFormItem label="职位"><ElInput v-model="recordForm.position_title" /></ElFormItem><ElFormItem label="部门"><ElInput v-model="recordForm.department_name" /></ElFormItem></div><ElFormItem label="决策角色"><ElSelect v-model="recordForm.role_types" multiple><ElOption v-for="item in contactOptions.role_options" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem><ElCheckbox v-model="recordForm.is_primary_contact">设为主要联系人</ElCheckbox><ElFormItem label="说明"><ElInput v-model="recordForm.notes" type="textarea" :rows="3" /></ElFormItem></ElForm><template #footer><ElButton @click="recordVisible = false">取消</ElButton><ElButton type="primary" :loading="recordSaving" @click="submitEmploymentRecord">保存记录</ElButton></template></AppWindowDialog>

    <AppWindowDialog v-model="leaveVisible" title="标记联系人离职" :width="570" :height="720" class="cus05-leave-dialog"><div v-loading="leaveLoading"><p class="leave-description">离职不会删除历史沟通、报价或订单关联。</p><ElAlert v-if="leavingContact?.is_primary_contact || leavingContact?.open_task_count" :title="`该联系人${leavingContact?.is_primary_contact ? '当前是主要联系人' : ''}${leavingContact?.open_task_count ? `，并有 ${leavingContact.open_task_count} 个未完成任务` : ''}`" description="提交前必须选择任务处理方式；有可接替联系人时还需选择新的主要联系人。" type="warning" :closable="false" show-icon /><ElForm label-position="top"><ElFormItem label="离职生效日期" required><ElDatePicker v-model="leaveForm.effective_date" type="date" value-format="YYYY-MM-DD" /></ElFormItem><ElFormItem v-if="leavingContact?.is_primary_contact" label="新的主要联系人" :required="Boolean(replacementOptions.length)"><ElSelect v-model="leaveForm.replacement_contact_id" clearable placeholder="选择在职联系人"><ElOption v-for="item in replacementOptions" :key="item.id" :label="`${item.display_name} · ${item.position_title || '未填写职位'}`" :value="item.id" /></ElSelect><small v-if="!replacementOptions.length">当前没有其他在职联系人，离职后客户将暂时没有主要联系人。</small></ElFormItem><ElFormItem label="未完成任务"><ElSelect v-model="leaveForm.unfinished_task_policy"><ElOption label="转移给客户负责人" value="TRANSFER_TO_OWNER" /><ElOption label="保持原任务负责人" value="KEEP_ASSIGNEE" /><ElOption label="取消未完成任务" value="CANCEL_OPEN" /></ElSelect></ElFormItem><ElFormItem label="离职说明"><ElInput v-model="leaveForm.reason" maxlength="500" /></ElFormItem><div class="leave-options"><ElCheckbox :model-value="true" disabled>保留历史沟通和商业单据关联</ElCheckbox><ElCheckbox v-model="leaveForm.remove_from_marketing">从群发与营销名单中移除</ElCheckbox><ElCheckbox v-model="leaveForm.notify_stakeholders">通知客户负责人和相关任务负责人</ElCheckbox></div></ElForm></div><template #footer><ElButton @click="leaveVisible = false">取消</ElButton><ElButton type="primary" :loading="leaveLoading" @click="submitLeave">确认标记离职</ElButton></template></AppWindowDialog>

    <AppWindowDialog v-model="taskVisible" title="批量创建任务" :width="560" :height="660"><ElForm label-position="top"><ElFormItem label="任务标题" required><ElInput v-model="taskForm.title" /></ElFormItem><ElFormItem label="说明"><ElInput v-model="taskForm.description" type="textarea" /></ElFormItem><div class="form-grid"><ElFormItem label="优先级"><ElSelect v-model="taskForm.priority"><ElOption label="普通" value="NORMAL" /><ElOption label="高" value="HIGH" /><ElOption label="紧急" value="URGENT" /></ElSelect></ElFormItem><ElFormItem label="截止时间" required><ElDatePicker v-model="taskForm.due_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></ElFormItem></div><ElFormItem label="负责人方式"><ElRadioGroup v-model="taskForm.assignee_mode"><ElRadio value="CUSTOMER_OWNER">各客户当前负责人</ElRadio><ElRadio value="SPECIFIC">指定统一负责人</ElRadio></ElRadioGroup></ElFormItem><ElFormItem v-if="taskForm.assignee_mode === 'SPECIFIC'" label="指定负责人"><ElSelect v-model="taskForm.assignee_employee_id" filterable><ElOption v-for="owner in ownerOptions" :key="owner.id" :label="owner.display_name" :value="owner.id" /></ElSelect></ElFormItem></ElForm><template #footer><ElButton @click="taskVisible = false">取消</ElButton><ElButton type="primary" @click="submitBulkTask">创建 {{ selected.length }} 项任务</ElButton></template></AppWindowDialog>

    <AppWindowDialog v-model="importVisible" class="customer-management-table-dialog" title="导入联系人" :width="720" :height="680"><ElAlert title="仅支持 UTF-8 CSV 或 XLSX，最大 5MB、500 行；文件将在解析前通过病毒扫描。" type="info" :closable="false" /><a :href="contactImportTemplateUrl(showCustomer ? 'global' : 'customer')" class="template-link"><ElIcon><Download /></ElIcon>下载导入模板</a><input class="file-input" type="file" accept=".csv,.xlsx" @change="onFileChange" /><ElCheckbox v-model="importAllowDuplicates">允许同一客户存在重复邮箱或手机（确认风险后使用）</ElCheckbox><ElDescriptions v-if="importBatch" border :column="2"><ElDescriptionsItem label="状态">{{ importBatch.status }}</ElDescriptionsItem><ElDescriptionsItem label="扫描">{{ importBatch.source_file.scan_status }}</ElDescriptionsItem><ElDescriptionsItem label="成功">{{ importBatch.success_count }}</ElDescriptionsItem><ElDescriptionsItem label="失败">{{ importBatch.failure_count }}</ElDescriptionsItem></ElDescriptions><ElTable v-if="importRecords.length" :data="importRecords" max-height="260"><ElTableColumn prop="row_number" label="行" width="70" /><ElTableColumn prop="status" label="状态" width="100" /><ElTableColumn prop="error_message" label="错误原因" min-width="300" /></ElTable><template #footer><ElButton @click="importVisible = false">关闭</ElButton><ElButton type="primary" :loading="importing" @click="submitImport">开始导入</ElButton></template></AppWindowDialog>

    <AppWindowDialog v-model="columnsVisible" title="列设置" :width="420" :height="420"><ElCheckboxGroup v-model="visibleColumns"><ElCheckbox v-for="column in allColumns" :key="column.value" :value="column.value">{{ column.label }}</ElCheckbox></ElCheckboxGroup></AppWindowDialog>
    <AppWindowDialog v-model="saveViewVisible" title="保存当前视图" :width="420" :height="250"><ElInput v-model="savedViewName" maxlength="150" placeholder="视图名称" /><template #footer><ElButton @click="saveViewVisible = false">取消</ElButton><ElButton type="primary" @click="saveCurrentView">保存</ElButton></template></AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.contact-page { min-width: 0; min-height: 868px; display: grid; grid-template-rows: 52px 72px 40px minmax(620px, 1fr); gap: 12px; padding: 24px; color: #30343b; background: var(--erp-page-background); --el-color-primary: #18181b; }
@media (min-width: 981px) {
  .contact-page:not(.is-embedded) {
    height: calc(100dvh - 84px);
    min-height: 0;
    grid-template-rows: 52px 72px 40px minmax(0, 1fr);
  }
}
.contact-heading { height: 52px; display: flex; align-items: flex-start; justify-content: space-between; }
.contact-heading h2 { margin: 0; color: #18181b; font-size: 22px; line-height: 30px; }
.contact-heading p { margin: 2px 0 0; color: #737a86; font-size: 11px; line-height: 14px; }
.heading-actions { height: 52px; display: flex; align-items: center; gap: 8px; }
.heading-actions :deep(.el-button) { width: 116px; height: 32px; margin: 0; border-radius: 8px; font-size: 12px; }
.heading-actions :deep(.el-button--primary) { border-color: #18181b; background: #18181b; }
.filter-card { height: 72px; display: grid; grid-template-columns: minmax(260px, 420px) repeat(3, 188px) 84px 84px minmax(0, 1fr); align-items: center; gap: 12px; padding: 0 16px; border: 1px solid #dfe2e7; border-radius: 10px; background: #fff; }
.filter-card :deep(.el-input__wrapper), .filter-card :deep(.el-select__wrapper) { min-height: 32px; border-radius: 8px; box-shadow: 0 0 0 1px #d4d4d8 inset; }
.filter-card :deep(.el-button) { width: 84px; height: 32px; margin: 0; border-radius: 8px; font-size: 12px; }
.filter-card :deep(.el-button--primary) { border-color: #18181b; background: #18181b; }
.contact-toolbar { height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.batch-actions, .view-actions { display: flex; align-items: center; gap: 8px; }
.batch-actions > span { width: 92px; color: #737a86; font-size: 11px; }
.contact-toolbar :deep(.el-button) { height: 32px; margin: 0; border-color: #d4d4d8; border-radius: 8px; color: #3f3f46; background: #fff; font-size: 12px; }
.contact-toolbar :deep(.el-button.is-density-active) { border-color: #a1a1aa; color: #18181b; background: #f4f4f5; }
.batch-actions :deep(.el-button:first-of-type) { width: 112px; }.batch-actions :deep(.el-button:last-of-type) { width: 96px; }
.view-actions :deep(.el-button) { min-width: 80px; }.view-actions :deep(.el-button.is-circle) { min-width: 32px; width: 32px; }
.table-card { min-width: 0; height: 620px; display: grid; grid-template-rows: minmax(0, 1fr) 48px; overflow: hidden; padding: 16px 16px 0; border: 1px solid #dfe2e7; border-radius: 10px; background: #fff; }
.table-card > :deep(.el-table) { min-width: 0; min-height: 0; height: 100%; }
@media (min-width: 981px) {
  .contact-page:not(.is-embedded) .table-card { height: 100%; min-height: 0; }
}
.table-footer { height: 48px; display: flex; align-items: center; justify-content: space-between; color: #737a86; font-size: 11px; }
.table-footer :deep(.el-pagination) { padding: 0; }.table-footer :deep(.el-select__wrapper), .table-footer :deep(.btn-prev), .table-footer :deep(.btn-next), .table-footer :deep(.el-pager li) { min-height: 32px; border-radius: 6px; }
.table-footer :deep(.el-pager li.is-active) { color: #fff; background: #18181b; }

.contact-page--v2 {
  width: 100%;
  min-width: 0;
  min-height: 870px;
  box-sizing: border-box;
  display: block;
  padding: 14px 28px 20px;
  color: token.$crm-text-regular;
  background: token.$crm-color-page;
  font-family: token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary};
}

.contact-summary-strip {
  height: 72px;
  min-width: 0;
  display: grid;
  grid-template-columns: 240px 200px 200px 200px 200px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
}

.contact-summary-strip article {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  padding: 0 18px;
}

.contact-summary-strip article:not(:last-of-type)::after {
  position: absolute;
  top: 12px;
  right: 0;
  width: 1px;
  height: 48px;
  background: token.$crm-border-subtle;
  content: '';
}

.contact-summary-strip article span {
  color: token.$crm-text-secondary;
  font-size: 11px;
  line-height: 16px;
}

.contact-summary-strip article strong {
  color: token.$crm-text-primary;
  font-size: 20px;
  font-weight: 700;
  line-height: 24px;
}

.contact-summary-strip p {
  min-width: 0;
  align-self: center;
  overflow: hidden;
  margin: 0;
  padding: 0 40px;
  color: token.$crm-primary;
  font-size: 12px;
  font-weight: 500;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contact-page--v2 .contact-heading {
  height: 46px;
  align-items: center;
  margin-top: 8px;
}

.contact-page--v2 .contact-heading > div:first-child {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 14px;
}

.contact-page--v2 .contact-heading h2 {
  color: token.$crm-text-primary;
  font-family: token.$crm-font-display;
  font-size: 24px;
  line-height: 32px;
}

.contact-page--v2 .contact-heading p {
  margin: 0;
  color: token.$crm-text-secondary;
  font-size: 11px;
  line-height: 18px;
}

.contact-page--v2 .heading-actions {
  height: 32px;
  gap: 10px;
  margin-right: 12px;
  transform: translateY(-2px);
}

.contact-page--v2 .heading-actions :deep(.el-button) {
  width: 116px;
  height: 32px;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

.contact-page--v2 .heading-actions :deep(.el-button--primary) {
  width: 116px;
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

.contact-page--v2 .filter-card {
  height: 32px;
  grid-template-columns: 380px 180px 170px 176px 76px 76px minmax(0, 1fr);
  gap: 10px;
  margin-top: 6px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.contact-page--v2 .filter-card :deep(.el-input__wrapper),
.contact-page--v2 .filter-card :deep(.el-select__wrapper) {
  min-height: 32px;
  padding: 0 12px;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

.contact-page--v2 .filter-card :deep(.el-input__inner),
.contact-page--v2 .filter-card :deep(.el-select__placeholder),
.contact-page--v2 .filter-card :deep(.el-select__selected-item) {
  color: token.$crm-text-secondary;
  font-family: token.$crm-font-body;
  font-size: 12px;
}

.contact-page--v2 .filter-card :deep(.el-button) {
  width: 76px;
  height: 32px;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 12px;
}

.contact-page--v2 .filter-card :deep(.el-button--primary) {
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

.contact-page--v2 .filter-card > :deep(.el-button:nth-of-type(2)) {
  transform: translateX(-2px);
}

.contact-page--v2 .contact-toolbar {
  height: 32px;
  margin-top: 10px;
}

.contact-page--v2 .batch-actions,
.contact-page--v2 .view-actions {
  gap: 10px;
}

.contact-page--v2 .batch-actions > span {
  width: 76px;
  color: token.$crm-text-secondary;
  font-size: 11px;
}

.contact-page--v2 .contact-toolbar :deep(.el-button) {
  height: 32px;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 12px;
}

.contact-page--v2 .batch-actions :deep(.el-button:first-of-type) {
  width: 112px;
}

.contact-page--v2 .batch-actions :deep(.el-button:last-of-type) {
  width: 104px;
}

.contact-page--v2 .view-actions :deep(.el-button) {
  width: 92px;
}

.contact-page--v2 .view-actions :deep(.toolbar-import-button),
.contact-page--v2 .view-actions :deep(.toolbar-create-button) {
  width: 116px;
}

.contact-page--v2 .view-actions :deep(.toolbar-create-button) {
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

.contact-page--v2 .view-actions :deep(.toolbar-save-view-button) {
  width: 132px;
}

.contact-page--v2 .view-actions {
  margin-right: 24px;
}

.contact-page--v2 .view-actions :deep(.el-button.is-circle) {
  width: 32px;
  min-width: 32px;
}

.contact-page--v2 .table-card {
  width: 1634px;
  min-width: 1634px;
  height: 584px;
  min-height: 584px;
  grid-template-rows: minmax(0, 1fr) 52px;
  padding: 0;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  margin-top: 8px;
}

.contact-page--v2 .table-card > :deep(.el-table) {
  width: 1634px;
  min-width: 1634px;
  height: 100%;
}

.contact-page--v2 .table-footer {
  height: 52px;
  padding: 0 14px;
  border-top: 1px solid token.$crm-border-subtle;
  color: token.$crm-text-secondary;
  font-size: 11px;
}

.contact-page--v2 .table-footer :deep(.el-select__wrapper),
.contact-page--v2 .table-footer :deep(.btn-prev),
.contact-page--v2 .table-footer :deep(.btn-next),
.contact-page--v2 .table-footer :deep(.el-pager li) {
  min-width: 32px;
  min-height: 32px;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
}

.contact-page--v2 .table-footer :deep(.el-pager li.is-active) {
  border-color: token.$crm-primary;
  color: token.$crm-primary;
  background: token.$crm-color-surface;
}
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.contact-form :deep(.el-form-item) { margin-bottom: 10px; }.contact-form :deep(.el-form-item__label) { height: 19px; padding: 0; color: #3f3f46; font-size: 11px; line-height: 14px; }
.contact-form :deep(.el-input__wrapper), .contact-form :deep(.el-select__wrapper) { min-height: 32px; border-radius: token.$crm-radius-2; }.contact-form :deep(.el-select), .contact-form :deep(.el-date-editor) { width: 100%; }
.duplicate-notice { min-height: 54px; display: flex; flex-direction: column; justify-content: center; gap: 3px; margin: 0 0 12px; padding: 6px 14px; border: 1px solid #b9daf5; border-radius: 7px; color: #1671c5; background: #eef7ff; }
.duplicate-notice.warning { border-color: #f1d487; color: #b45309; background: #fffaf0; }.duplicate-notice strong { font-size: 12px; }.duplicate-notice span { font-size: 10px; }
.notes-field { margin-top: 12px; }.template-link { display: inline-flex; align-items: center; gap: 6px; margin: 16px 0 0; color: #18181b; font-size: 12px; text-decoration: none; }.file-input { display: block; width: 100%; margin: 16px 0 12px; padding: 12px; border: 1px dashed #c5cad3; border-radius: 8px; }
.legacy-contact-data { margin-top: 16px; padding: 14px; border: 1px solid #dfe2e7; border-radius: 8px; background: #fafafa; }
.legacy-contact-data header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 10px; border-bottom: 1px solid #e4e4e7; }
.legacy-contact-data header span, .legacy-contact-data dt { color: #71717a; font-size: 10px; }
.legacy-contact-data dl { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; margin: 0; }
.legacy-contact-data dl > div { min-width: 0; padding: 10px 0; border-bottom: 1px solid #eceef1; }
.legacy-contact-data dt { margin-bottom: 3px; }.legacy-contact-data dd { overflow-wrap: anywhere; margin: 0; color: #27272a; font-size: 12px; }
.history-panel { min-height: 100%; padding: 24px 28px 60px; background: #f7f8fa; }.history-panel > header { height: 48px; display: flex; align-items: center; justify-content: space-between; }.history-panel h2 { margin: 0; color: #18181b; font-size: 20px; }.history-panel header p { margin: 2px 0 0; color: #71717a; font-size: 11px; }.history-panel header :deep(.el-button) { width: 124px; height: 32px; border-radius: 8px; }
.current-employment { height: 96px; display: flex; align-items: center; gap: 20px; margin-top: 16px; padding: 16px 18px; border: 1px solid #dfe2e7; border-radius: 9px; background: #fff; }.history-avatar { width: 48px; height: 48px; display: grid; place-items: center; border-radius: 50%; color: #fff; background: #18181b; font-weight: 600; }.current-employment > div { flex: 1; }.current-employment strong { color: #18181b; font-size: 15px; }.current-employment p, .current-employment small { margin: 5px 0 0; color: #71717a; font-size: 11px; }.history-timeline { min-height: 520px; margin-top: 16px; padding: 16px 18px; border: 1px solid #dfe2e7; border-radius: 9px; background: #fff; }.history-timeline article { min-height: 108px; display: grid; grid-template-columns: 166px 1fr; padding: 14px; border-bottom: 1px solid #edf0f4; }.history-date { display: flex; flex-direction: column; gap: 4px; }.history-date strong { font-size: 12px; }.history-date span, .history-timeline small { color: #71717a; font-size: 10px; }.history-timeline h3 { margin: 0; color: #18181b; font-size: 14px; }.history-timeline p { margin: 6px 0; color: #3f3f46; font-size: 11px; }
.leave-description { margin: 0 0 14px; color: #71717a; font-size: 12px; }.leave-options { display: flex; flex-direction: column; gap: 12px; }.cus05-leave-dialog :deep(.el-alert) { margin-bottom: 14px; }.cus05-leave-dialog :deep(.el-select), .cus05-leave-dialog :deep(.el-date-editor) { width: 100%; }
:global(.cus05-contact-drawer .el-drawer__header) { height: 72px; margin: 0; padding: 0 24px; border-bottom: 1px solid #e4e4e7; color: #18181b; font-size: 20px; font-weight: 600; }:global(.cus05-contact-drawer .el-drawer__body) { padding: 20px 24px; }:global(.cus05-contact-drawer .el-drawer__footer) { height: 72px; display: flex; align-items: center; justify-content: flex-end; padding: 0 24px; border-top: 1px solid #e4e4e7; }:global(.cus05-contact-drawer .el-drawer__footer .el-button) { width: 96px; height: 32px; border-radius: 8px; }:global(.cus05-contact-drawer .el-drawer__footer .el-button--primary) { width: 120px; border-color: #18181b; background: #18181b; }
:global(.customer-detail-drawer .el-drawer__header) { height: 64px; }
:global(.customer-detail-drawer .el-drawer__body) { padding: 16px 24px; }
:global(.customer-detail-drawer .el-drawer__footer) { height: 64px; }
:global(.cus05-history-drawer .el-drawer__body) { padding: 0; }
@media (max-width: 1500px) { .contact-page { padding: 20px; }.filter-card { grid-template-columns: minmax(230px, 1.5fr) repeat(3, minmax(145px, 1fr)) 72px 64px; }.filter-card :deep(.el-button) { width: 100%; }.table-card { padding-inline: 12px; } }
@media (max-width: 1599px) and (min-width: 981px) {
  .contact-page--v2 { padding: 18px 24px 24px; }
  .contact-page--v2 .contact-summary-strip { grid-template-columns: repeat(5, 160px) minmax(0, 1fr); }
  .contact-page--v2 .table-card { width: 100%; min-width: 0; padding-inline: 0; }
  .contact-page--v2 .table-card > :deep(.el-table) { width: 100%; min-width: 0; }
}
@media (max-width: 980px) { .contact-page { grid-template-rows: auto auto auto minmax(620px, 1fr); padding: 12px; }.filter-card { height: auto; grid-template-columns: 1fr 1fr; padding-block: 12px; }.contact-toolbar { height: auto; align-items: stretch; flex-direction: column; }.contact-heading { height: auto; align-items: stretch; flex-direction: column; gap: 8px; }.heading-actions { justify-content: flex-end; }.table-card { height: 620px; }.form-grid { grid-template-columns: 1fr; } }
</style>
