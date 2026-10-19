<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Box,
  Document,
  TrendCharts,
  User,
} from '@element-plus/icons-vue'

import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import CustomerOverviewV2 from '@/views/customers/CustomerOverviewV2.vue'
import CustomerEditDialog from '@/views/customers/CustomerEditDialog.vue'
import CustomerRelatedRecordsV2 from '@/components/customers/CustomerRelatedRecordsV2.vue'
import ComplaintListView from '@/views/complaints/ComplaintListView.vue'
import TaskCenterView from '@/views/tasks/TaskCenterView.vue'
import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
import { useOptions } from '@/composables/useOptions'
import { getTimelineEventTypeLabel, getTimelineSourceTypeLabel } from '@/utils/customerTimeline'
import { toCustomerDictionaryOptions, withHistoricalCustomerOption } from '@/utils/referenceOptions'
import { fetchCustomerContacts } from '@/api/contacts'
import { fetchTask, fetchTasks, postTaskAction } from '@/api/tasks'
import { createCommunication, createTask } from '@/api/crm'
import {
  approveCustomerTransferRequest,
  cancelCustomerTransferRequest,
  checkCustomerDuplicates,
  createCustomerEntity,
  createCustomerTag,
  createCustomerTransferRequest,
  createEntityAddress,
  fetchCustomer,
  fetchCustomerEntities,
  fetchCustomerEntity,
  fetchCustomerOptions,
  fetchCustomerSummary,
  fetchCustomerTimeline,
  fetchCustomerTransferRequest,
  fetchCustomerTransferRequests,
  fetchEntityAddress,
  fetchEntityAddresses,
  rejectCustomerTransferRequest,
  setCustomerClassification,
  setCustomerGrade,
  setCustomerSource,
  updateCustomer,
  updateCustomerEntity,
  updateEntityAddress,
} from '@/api/customers'
import { useAuthStore } from '@/stores/auth'
import type {
  CustomerAddress,
  CustomerDetail,
  CustomerDictionaryOption,
  CustomerDuplicateMatch,
  CustomerEntity,
  CustomerOptions,
  CustomerSummary,
  CustomerTimelineEvent,
  CustomerTransferRequest,
} from '@/types/customer'
import type { ContactListItem } from '@/types/contact'
import type { TaskScope, TaskSummary } from '@/types/task'

interface AddressDraft {
  addressType: string
  countryCode: string
  stateProvince: string
  city: string
  postalCode: string
  addressLine1: string
  addressLine2: string
  recipientName: string
  recipientPhone: string
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const gradeOptions = useOptions('CUSTOMER_GRADE')
const typeOptions = useOptions('CUSTOMER_TYPE')
const sourceOptions = useOptions('CUSTOMER_SOURCE')
const countryOptions = useOptions('COUNTRY_REGION')
const communicationOptions = useOptions('COMMUNICATION_TYPE')
const communicationTypeOptions = communicationOptions.options
const customerId = computed(() => String(route.params.customerId || ''))
const routeName = computed(() => String(route.name || 'customer-detail'))
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const customer = ref<CustomerDetail | null>(null)
const customerEtag = ref('')
const summary = ref<CustomerSummary | null>(null)
const baseLoadedCustomerId = ref('')
const options = ref<CustomerOptions | null>(null)
const entities = ref<CustomerEntity[]>([])
const addresses = ref<CustomerAddress[]>([])
const entityEtag = ref('')
const addressEtag = ref('')
const activeAddressId = ref('')
const appendedAddressDrafts = ref<AddressDraft[]>([])
const creatingNewAddress = computed(() => appendedAddressDrafts.value.length > 0)
const tagDialogVisible = ref(false)
const tagDraftIds = ref<string[]>([])
const tagCreating = ref(false)
const newTagForm = reactive({ name: '', color: '#3E63DD' })
const duplicateMatches = ref<CustomerDuplicateMatch[]>([])
const checkingDuplicate = ref(false)
let duplicateTimer: ReturnType<typeof setTimeout> | undefined

const timeline = ref<CustomerTimelineEvent[]>([])
const timelineLoading = ref(false)
const timelineCursor = ref<string | null>(null)
const timelineFilters = reactive({ keyword: '', eventType: '', occurredFrom: '', occurredTo: '' })
const contacts = ref<ContactListItem[]>([])
const contactsLoading = ref(false)
const contactsError = ref('')
const communicationContactsCustomerId = ref('')
const customerTasks = ref<TaskSummary[]>([])
const customerTasksLoading = ref(false)
const customerTasksError = ref('')
const taskCreateVisible = ref(false)
const editDialogVisible = ref(false)
const completingTaskId = ref('')
const communicationSaving = ref(false)
const communicationForm = reactive({
  type: 'EMAIL',
  direction: 'OUTBOUND' as 'INBOUND' | 'OUTBOUND' | 'INTERNAL',
  contactId: '',
  occurredAt: new Date().toISOString(),
  subject: '',
  content: '',
  createTask: true,
  taskTitle: '',
  taskDueAt: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
})

const transferRequests = ref<CustomerTransferRequest[]>([])
const transferLoading = ref(false)
const transferForm = reactive({ ownerId: '', reason: '', taskPolicy: 'TRANSFER_ALL' })

const editForm = reactive({
  accountName: '', englishName: '', shortName: '', lifecycleStage: 'LEAD', countryCode: '', website: '',
  primaryRegionId: '', secondaryRegionId: '', industryId: '', interestedProductIds: [] as string[], inquiryKeywords: '',
  sourceSystem: '', externalId: '', notes: '', gradeId: '', sourceId: '', typeIds: [] as string[],
  tagIds: [] as string[], reason: '客户资料编辑',
  entityLegalName: '', entityEnglishName: '', registrationNumber: '', taxIdentifier: '',
  addressCountryCode: '', stateProvince: '', city: '', postalCode: '', addressLine1: '', addressLine2: '',
  recipientName: '', recipientPhone: '',
})

const EDIT_DISPLAY_DEFAULTS = Object.freeze({
  defaultLanguage: 'English',
  defaultCurrency: 'USD',
  addressType: '办公地址',
})
type EditDisplayForm = { -readonly [Key in keyof typeof EDIT_DISPLAY_DEFAULTS]: string }
const editDisplayForm = reactive<EditDisplayForm>({ ...EDIT_DISPLAY_DEFAULTS })
const editInitialSnapshot = ref('')
const editActiveSection = ref('profile')
const secondaryRegionOptions = computed(() => options.value?.secondary_regions.filter(
  (item) => item.parent_id === editForm.primaryRegionId,
) || [])
const selectedSecondaryRegion = computed(() => secondaryRegionOptions.value.find(
  (item) => item.id === editForm.secondaryRegionId,
))
const sourceSalespersonNames = computed(() => {
  const names = customer.value?.current_assignments
    .filter((assignment) => ['PRIMARY_OWNER', 'COLLABORATOR'].includes(assignment.assignment_role))
    .map((assignment) => assignment.employee.display_name) || []
  return [...new Set(names)].join('、')
})
const sourceManagerNames = computed(() => {
  const names = customer.value?.current_assignments
    .filter((assignment) => assignment.assignment_role === 'MANAGER')
    .map((assignment) => assignment.employee.display_name) || []
  return [...new Set(names)].join('、')
})

const mode = computed<'overview' | 'edit' | 'timeline' | 'tasks' | 'complaints' | 'inquiries' | 'quotations' | 'samples' | 'orders' | 'transfer'>(() => {
  if (routeName.value === 'customer-edit') return 'edit'
  if (routeName.value === 'customer-timeline') return 'timeline'
  if (routeName.value === 'customer-tasks') return 'tasks'
  if (routeName.value === 'customer-complaints') return 'complaints'
  if (routeName.value === 'customer-inquiries') return 'inquiries'
  if (routeName.value === 'customer-quotations') return 'quotations'
  if (routeName.value === 'customer-samples') return 'samples'
  if (routeName.value === 'customer-orders') return 'orders'
  if (routeName.value === 'customer-transfer') return 'transfer'
  return 'overview'
})
const isV2DetailMode = computed(() => mode.value !== 'edit')
const usesCompactDetailControls = computed(() => mode.value !== 'edit')
const relatedRecordKind = computed<'inquiries' | 'quotations' | 'samples' | 'orders' | null>(() => (
  ['inquiries', 'quotations', 'samples', 'orders'].includes(mode.value)
    ? mode.value as 'inquiries' | 'quotations' | 'samples' | 'orders'
    : null
))
const canChange = computed(() => authStore.canFor('customers.change_customeraccount', customer.value))
const canTransfer = computed(() => authStore.hasPermission('customers.transfer_customer'))
const canApproveTransfer = computed(() => authStore.hasPermission('customers.approve_customer_transfer'))
const canCommunicate = computed(() => authStore.canFor('crm.add_customercommunication', customer.value))
const canTask = computed(() => authStore.hasPermission('workflow.add_businesstask'))
const canViewTasks = computed(() => authStore.hasPermission('workflow.view_businesstask'))
const canViewComplaints = computed(() => authStore.canFor('customers.view_customercomplaint', customer.value))
const canCreateInquiry = computed(() => authStore.canFor('inquiries.add_inquiry', customer.value))
const canCreateQuotation = computed(() => authStore.canFor('quotations.add_quotation', customer.value))
const taskScope = computed<TaskScope>(() => {
  if (authStore.hasPermission('workflow.view_all_businesstask')) return 'ALL'
  if (authStore.hasPermission('workflow.view_team_businesstask')) return 'TEAM'
  return 'ME'
})
const profileCompleteness = computed(() => {
  if (!customer.value) return 0
  const values = [
    customer.value.account_name, customer.value.english_name, customer.value.short_name,
    customer.value.primary_country_code, customer.value.primary_website_url,
    customer.value.customer_grade?.id, customer.value.latest_source?.id,
    customer.value.customer_types.length ? 'yes' : '', customer.value.customer_tags.length ? 'yes' : '',
    addresses.value[0]?.address_line1, addresses.value[0]?.city,
  ]
  return Math.round((values.filter(Boolean).length / values.length) * 100)
})
const editCompletedCount = computed(() => Math.max(1, Math.round(profileCompleteness.value / 100 * 11)))
const editIsDirty = computed(() => editInitialSnapshot.value !== '' && editInitialSnapshot.value !== currentEditSnapshot())
const overviewGradeLabel = computed(() => {
  const label = customer.value?.customer_grade?.display_name || '未定级'
  return label.endsWith('级') ? label : `${label}级`
})
const overviewTypeLabel = computed(() => (
  customer.value?.customer_types[0]?.display_name
  || customer.value?.industry?.display_name
  || '未分类'
))
const overviewRegionLabel = computed(() => (
  customer.value?.secondary_region?.region_name
  || customer.value?.primary_region?.region_name
  || customer.value?.primary_country_code
  || '地区未录入'
))

const customerUpdatedLabel = computed(() => {
  if (!customer.value?.updated_at) return '暂无更新时间'
  const date = new Date(customer.value.updated_at)
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', hour12: false }).format(date)
})

function apiError(error: unknown, fallback = '请求失败，请稍后重试。'): string {
  if (!(error instanceof AxiosError)) return fallback
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const body = error.response.data as { error?: { message?: string; field_errors?: Record<string, string[]> } }
  const fieldError = body.error?.field_errors ? Object.values(body.error.field_errors).flat()[0] : undefined
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有执行该操作的权限。'
  if (error.response.status === 412) return '客户资料已被其他人修改，请刷新后重试。'
  if (error.response.status === 428) return '缺少并发版本信息，请刷新页面后重试。'
  if (error.response.status >= 500) return '后端服务异常，请稍后重试。'
  return fieldError || body.error?.message || fallback
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function formatCountryOption(item: CustomerDictionaryOption): string {
  return `${item.display_name}（${item.item_code}）`
}

watch([gradeOptions.options, typeOptions.options, sourceOptions.options], ([grades, types, sources]) => {
  if (!options.value || !customer.value || loading.value || gradeOptions.configVersion.value === null) return
  options.value = {
    ...options.value,
    customer_grades: withHistoricalCustomerOption(toCustomerDictionaryOptions(grades), customer.value.customer_grade),
    customer_types: customer.value.customer_types.reduce(
      (result, current) => withHistoricalCustomerOption(result, current), toCustomerDictionaryOptions(types),
    ),
    customer_sources: withHistoricalCustomerOption(toCustomerDictionaryOptions(sources), customer.value.latest_source),
  }
})

let baseLoadRequest: Promise<void> | null = null
let summaryRequest = 0
let communicationContactsRequest = 0
let customerTasksRequest = 0
let disposed = false
function loadCustomerBase(force = false): Promise<void> {
  if (baseLoadRequest) return baseLoadRequest
  baseLoadRequest = fetchCustomerBase(force).finally(() => { baseLoadRequest = null })
  return baseLoadRequest
}

async function fetchCustomerBase(force = false) {
  if (!force && baseLoadedCustomerId.value === customerId.value && customer.value) return
  const summaryRequestId = ++summaryRequest
  loading.value = true
  loadError.value = ''
  try {
    const needsEditOptions = mode.value === 'edit' || mode.value === 'transfer'
    const [versioned, summaryData, optionData, publishedOptions] = await Promise.all([
      fetchCustomer(customerId.value), fetchCustomerSummary(customerId.value),
      needsEditOptions ? fetchCustomerOptions() : Promise.resolve(null),
      needsEditOptions
        ? Promise.all([gradeOptions.load(), typeOptions.load(), sourceOptions.load(), countryOptions.load()]).catch(() => null)
        : Promise.resolve(null),
      // 地址参与资料完整度计算，提前读取；只有编辑模式读取保存所需版本。
      loadEntityAddress(mode.value === 'edit'),
    ])
    if (disposed) return
    customer.value = versioned.data
    customerEtag.value = versioned.etag || ''
    if (summaryRequestId === summaryRequest) summary.value = summaryData
    if (!optionData || !publishedOptions || gradeOptions.configVersion.value === null) {
      options.value = optionData
    } else {
      const [grades, types, sources] = publishedOptions
      const activeGrades = toCustomerDictionaryOptions(grades)
      const activeTypes = toCustomerDictionaryOptions(types)
      const activeSources = toCustomerDictionaryOptions(sources)
      options.value = {
        ...optionData,
        customer_grades: withHistoricalCustomerOption(activeGrades, versioned.data.customer_grade),
        customer_types: versioned.data.customer_types.reduce(
          (result, current) => withHistoricalCustomerOption(result, current),
          activeTypes,
        ),
        customer_sources: withHistoricalCustomerOption(activeSources, versioned.data.latest_source),
        country_options: withHistoricalCustomerOption(optionData.country_options, {
          item_code: versioned.data.primary_country_code,
          display_name: versioned.data.primary_country_code,
        }),
      }
    }
    if (mode.value === 'edit') fillEditForm()
    baseLoadedCustomerId.value = customerId.value
  } catch (error) {
    if (!disposed) loadError.value = apiError(error, '客户资料加载失败。')
  } finally {
    loading.value = false
  }
}

async function loadEntityAddress(includeVersions = true) {
  entities.value = await fetchCustomerEntities(customerId.value)
  addresses.value = []
  entityEtag.value = ''
  addressEtag.value = ''
  activeAddressId.value = ''
  appendedAddressDrafts.value = []
  const entity = entities.value[0]
  if (!entity) return
  if (!includeVersions) {
    addresses.value = await fetchEntityAddresses(entity.id)
    return
  }
  const [entityVersion, entityAddresses] = await Promise.all([
    fetchCustomerEntity(entity.id),
    fetchEntityAddresses(entity.id),
  ])
  entityEtag.value = entityVersion.etag || ''
  addresses.value = entityAddresses
  if (addresses.value[0]) {
    activeAddressId.value = addresses.value[0].id
    const addressVersion = await fetchEntityAddress(addresses.value[0].id)
    addressEtag.value = addressVersion.etag || ''
  }
}

function fillEditForm() {
  const item = customer.value
  if (!item) return
  const entity = entities.value[0]
  const address = addresses.value[0]
  Object.assign(editForm, {
    accountName: item.account_name, englishName: item.english_name, shortName: item.short_name,
    lifecycleStage: item.lifecycle_stage, countryCode: item.primary_country_code,
    primaryRegionId: item.primary_region?.id || '', secondaryRegionId: item.secondary_region?.id || '',
    industryId: item.industry?.id || '',
    interestedProductIds: item.interested_products.map((value) => value.product_item_id), inquiryKeywords: item.inquiry_keywords,
    website: item.primary_website_url, sourceSystem: item.source_system, externalId: item.external_id,
    notes: item.notes,
    gradeId: options.value?.customer_grades.find((value) => value.item_code === item.customer_grade?.item_code)?.id || '',
    sourceId: options.value?.customer_sources.find((value) => value.item_code === item.latest_source?.item_code)?.id || '',
    typeIds: item.customer_types.map((current) => options.value?.customer_types.find((value) => value.item_code === current.item_code)?.id).filter((value): value is string => Boolean(value)),
    tagIds: item.customer_tags.map((value) => value.id),
    entityLegalName: entity?.legal_name || item.account_name,
    entityEnglishName: entity?.english_legal_name || item.english_name,
    registrationNumber: entity?.registration_number || '', taxIdentifier: entity?.tax_identifier || '',
    addressCountryCode: address?.country_code || item.primary_country_code,
    stateProvince: address?.state_province || '', city: address?.city || '', postalCode: address?.postal_code || '',
    addressLine1: address?.address_line1 || '', addressLine2: address?.address_line2 || '',
    recipientName: address?.recipient_name || '', recipientPhone: address?.recipient_phone || '',
  })
  Object.assign(editDisplayForm, EDIT_DISPLAY_DEFAULTS)
  if (address?.label) editDisplayForm.addressType = address.label
  editInitialSnapshot.value = currentEditSnapshot()
}

function currentEditSnapshot() {
  return JSON.stringify({
    form: { ...editForm },
    display: { ...editDisplayForm },
    appendedAddresses: appendedAddressDrafts.value,
  })
}

function scrollEditSection(section: string) {
  editActiveSection.value = section
  document.getElementById(`edit-section-${section}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function fillAddressForm(address?: CustomerAddress) {
  Object.assign(editForm, {
    addressCountryCode: address?.country_code || customer.value?.primary_country_code || editForm.countryCode,
    stateProvince: address?.state_province || '',
    city: address?.city || '',
    postalCode: address?.postal_code || '',
    addressLine1: address?.address_line1 || '',
    addressLine2: address?.address_line2 || '',
    recipientName: address?.recipient_name || '',
    recipientPhone: address?.recipient_phone || '',
  })
  editDisplayForm.addressType = address?.label || EDIT_DISPLAY_DEFAULTS.addressType
}

function createEmptyAddressDraft(): AddressDraft {
  return {
    addressType: EDIT_DISPLAY_DEFAULTS.addressType,
    countryCode: customer.value?.primary_country_code || editForm.countryCode,
    stateProvince: '',
    city: '',
    postalCode: '',
    addressLine1: '',
    addressLine2: '',
    recipientName: '',
    recipientPhone: '',
  }
}

function startAddAddress() {
  appendedAddressDrafts.value.push(createEmptyAddressDraft())
  ElMessage.info(`已在下方追加第 ${appendedAddressDrafts.value.length} 条待新增地址。`)
}

function removeAppendedAddress(index: number) {
  appendedAddressDrafts.value.splice(index, 1)
}

function validateAddressForms(): string {
  const baseHasAddressData = Boolean(
    editForm.addressLine1.trim()
    || editForm.stateProvince.trim()
    || editForm.city.trim()
    || editForm.postalCode.trim()
    || editForm.recipientName.trim()
    || editForm.recipientPhone.trim(),
  )
  if (baseHasAddressData && !editForm.addressLine1.trim()) return '请填写当前地址的详细地址。'
  if (baseHasAddressData && !editForm.addressCountryCode) return '请选择当前地址对应的国家/地区。'
  for (const [index, draft] of appendedAddressDrafts.value.entries()) {
    if (!draft.addressLine1.trim()) return `请填写新增地址 ${index + 1} 的详细地址，或删除该行。`
    if (!draft.countryCode) return `请选择新增地址 ${index + 1} 对应的国家/地区。`
  }
  return ''
}

async function loadActiveAddressEtag(addressId?: string) {
  addressEtag.value = ''
  if (!addressId) return
  try {
    const addressVersion = await fetchEntityAddress(addressId)
    addressEtag.value = addressVersion.etag || ''
  } catch (error) {
    ElMessage.error(apiError(error, '地址版本信息加载失败。'))
  }
}

async function selectAddress(addressId: string) {
  const address = addresses.value.find((item) => item.id === addressId)
  if (!address) return
  activeAddressId.value = address.id
  fillAddressForm(address)
  await loadActiveAddressEtag(address.id)
  if (!creatingNewAddress.value) editInitialSnapshot.value = currentEditSnapshot()
}

function formatAddressOption(address: CustomerAddress): string {
  const location = address.city || formatCountryOption(
    options.value?.country_options.find((item) => item.item_code === address.country_code)
      || { id: '', item_code: address.country_code, display_name: address.country_code, description: '' },
  )
  return `${address.label || '地址'} · ${location}`
}

async function createTagInDialog() {
  const tagName = newTagForm.name.trim()
  if (!tagName) {
    ElMessage.warning('请输入标签名称。')
    return
  }

  tagCreating.value = true
  try {
    const createdTag = await createCustomerTag({
      tag_name: tagName,
      color: newTagForm.color,
    })
    options.value?.customer_tags.push(createdTag)
    if (!tagDraftIds.value.includes(createdTag.id)) {
      tagDraftIds.value.push(createdTag.id)
    }
    newTagForm.name = ''
    ElMessage.success('新标签已创建并自动选中。')
  } catch (error) {
    ElMessage.error(apiError(error, '新标签创建失败。'))
  } finally {
    tagCreating.value = false
  }
}

function applySelectedTags() {
  editForm.tagIds = [...tagDraftIds.value]
  tagDialogVisible.value = false
}

function scheduleEditDuplicateCheck() {
  if (duplicateTimer) clearTimeout(duplicateTimer)
  if (mode.value !== 'edit' || loading.value || !editIsDirty.value) return
  duplicateTimer = setTimeout(async () => {
    if (editForm.accountName.trim().length < 2 && editForm.website.trim().length < 4) return
    checkingDuplicate.value = true
    try {
      const query = editForm.accountName.trim()
        ? { name: editForm.accountName.trim(), website: editForm.website.trim() || undefined }
        : { website: editForm.website.trim() }
      duplicateMatches.value = (await checkCustomerDuplicates({
        ...query, country_code: editForm.countryCode || undefined, exclude_customer_id: customerId.value,
      })).matches
    } catch {
      duplicateMatches.value = []
    } finally {
      checkingDuplicate.value = false
    }
  }, 400)
}

async function saveProfile(returnAfterSave = false, asDraft = false) {
  if (!customer.value || !customerEtag.value || !editForm.accountName.trim() || !editForm.primaryRegionId) {
    ElMessage.warning('请完整填写客户名称和一级地区。')
    return
  }
  const addressValidationMessage = validateAddressForms()
  if (addressValidationMessage) {
    ElMessage.warning(addressValidationMessage)
    return
  }
  saving.value = true
  try {
    await updateCustomer(customerId.value, {
      account_name: editForm.accountName.trim(), english_name: editForm.englishName.trim(),
      short_name: editForm.shortName.trim(), lifecycle_stage: editForm.lifecycleStage as CustomerDetail['lifecycle_stage'],
      primary_country_code: selectedSecondaryRegion.value?.country_code || '',
      primary_region_id: editForm.primaryRegionId, secondary_region_id: editForm.secondaryRegionId || null,
      inquiry_keywords: editForm.inquiryKeywords.trim(), industry_item_id: editForm.industryId || null,
      interested_product_item_ids: editForm.interestedProductIds,
      primary_website_url: editForm.website.trim(),
      source_system: editForm.sourceSystem.trim(), external_id: editForm.externalId.trim(), notes: editForm.notes.trim(),
    }, customerEtag.value)
    const currentGradeId = options.value?.customer_grades.find((value) => value.item_code === customer.value?.customer_grade?.item_code)?.id
    const currentSourceId = options.value?.customer_sources.find((value) => value.item_code === customer.value?.latest_source?.item_code)?.id
    if (editForm.gradeId && editForm.gradeId !== currentGradeId) {
      await setCustomerGrade(customerId.value, { grade_item_id: editForm.gradeId, reason: editForm.reason })
    }
    if (editForm.sourceId && editForm.sourceId !== currentSourceId) {
      await setCustomerSource(customerId.value, { source_item_id: editForm.sourceId, notes: editForm.reason })
    }
    await setCustomerClassification(customerId.value, {
      customer_type_item_ids: editForm.typeIds, customer_tag_ids: editForm.tagIds, reason: editForm.reason,
    })
    const savedAddressIds = await saveEntityAddresses()
    ElMessage.success(asDraft ? '当前资料已保存；后端暂不区分草稿状态。' : '客户资料与画像历史已保存。')
    await loadCustomerBase(true)
    const lastSavedAddressId = savedAddressIds[savedAddressIds.length - 1]
    if (lastSavedAddressId) await selectAddress(lastSavedAddressId)
    if (returnAfterSave) void router.push({ name: 'customer-detail', params: { customerId: customerId.value } })
  } catch (error) {
    ElMessage.error(apiError(error, '客户资料保存失败。'))
  } finally {
    saving.value = false
  }
}

async function saveEntityAddresses(): Promise<string[]> {
  if (!customer.value || !editForm.entityLegalName.trim()) return []
  let entity = entities.value[0]
  const entityPayload = {
    entity_code: entity?.entity_code || `${customer.value.account_code}-LEGAL`, entity_type: entity?.entity_type || 'COMPANY',
    legal_name: editForm.entityLegalName.trim(), english_legal_name: editForm.entityEnglishName.trim(),
    registration_country_code: editForm.countryCode, registration_number: editForm.registrationNumber.trim(),
    tax_country_code: editForm.countryCode, tax_identifier: editForm.taxIdentifier.trim(), notes: '客户资料页维护',
  }
  if (!entity) entity = await createCustomerEntity(customerId.value, entityPayload)
  else if (entityEtag.value) {
    entity = await updateCustomerEntity(entity.id, entityPayload, entityEtag.value)
  }
  const savedAddressIds: string[] = []
  const activeAddress = addresses.value.find((item) => item.id === activeAddressId.value)
  if (editForm.addressLine1.trim()) {
    const addressPayload = {
      address_code: activeAddress?.address_code || `ADDR_${Date.now().toString(36).toUpperCase()}_BASE`,
      label: editDisplayForm.addressType,
      country_code: editForm.addressCountryCode, state_province: editForm.stateProvince.trim(), city: editForm.city.trim(),
      postal_code: editForm.postalCode.trim(), address_line1: editForm.addressLine1.trim(),
      address_line2: editForm.addressLine2.trim(), recipient_name: editForm.recipientName.trim(),
      recipient_phone: editForm.recipientPhone.trim(), is_verified: false,
    }
    if (!activeAddress) {
      const createdAddress = await createEntityAddress(entity.id, addressPayload)
      savedAddressIds.push(createdAddress.id)
    } else {
      if (!addressEtag.value) throw new Error('缺少地址版本信息，请重新选择地址。')
      const updatedAddress = await updateEntityAddress(activeAddress.id, addressPayload, addressEtag.value)
      savedAddressIds.push(updatedAddress.id)
    }
  }

  const addressCodePrefix = Date.now().toString(36).toUpperCase()
  for (const [index, draft] of appendedAddressDrafts.value.entries()) {
    const createdAddress = await createEntityAddress(entity.id, {
      address_code: `ADDR_${addressCodePrefix}_${index + 1}`,
      label: draft.addressType,
      country_code: draft.countryCode,
      state_province: draft.stateProvince.trim(),
      city: draft.city.trim(),
      postal_code: draft.postalCode.trim(),
      address_line1: draft.addressLine1.trim(),
      address_line2: draft.addressLine2.trim(),
      recipient_name: draft.recipientName.trim(),
      recipient_phone: draft.recipientPhone.trim(),
      is_verified: false,
    })
    savedAddressIds.push(createdAddress.id)
  }
  return savedAddressIds
}

let timelineRequest = 0
async function loadTimeline(reset = true) {
  const requestId = ++timelineRequest
  const filters = mode.value === 'overview'
    ? { keyword: '', eventType: '', occurredFrom: '', occurredTo: '' }
    : { ...timelineFilters }
  timelineLoading.value = true
  try {
    const result = await fetchCustomerTimeline(customerId.value, {
      event_type: filters.eventType || undefined,
      occurred_from: filters.occurredFrom || undefined,
      occurred_to: filters.occurredTo || undefined,
      cursor: reset ? undefined : timelineCursor.value || undefined,
      page_size: 20,
    })
    if (requestId !== timelineRequest) return
    const items = filters.keyword.trim()
      ? result.data.filter((item) => `${item.title} ${item.summary}`.includes(filters.keyword.trim()))
      : result.data
    timeline.value = reset ? items : [...timeline.value, ...items]
    timelineCursor.value = result.meta.next
  } catch (error) {
    if (requestId === timelineRequest) ElMessage.error(apiError(error, '客户时间线加载失败。'))
  } finally {
    if (requestId === timelineRequest) timelineLoading.value = false
  }
}

async function loadCommunicationContacts(force = false) {
  if (!force && communicationContactsCustomerId.value === customerId.value) return
  const requestId = ++communicationContactsRequest
  const requestedCustomerId = customerId.value
  contacts.value = []
  contactsLoading.value = true
  contactsError.value = ''
  try {
    const items: ContactListItem[] = []
    let page = 1
    let totalPages = 1
    do {
      const result = await fetchCustomerContacts(requestedCustomerId, { page, page_size: 100 })
      if (requestId !== communicationContactsRequest) return
      items.push(...result.data)
      totalPages = result.meta?.total_pages || 1
      page += 1
    } while (page <= totalPages)
    contacts.value = items
    communicationContactsCustomerId.value = requestedCustomerId
  } catch (error) {
    if (requestId === communicationContactsRequest) {
      contactsError.value = apiError(error, '联系人加载失败，请重试。')
      communicationContactsCustomerId.value = ''
    }
  } finally {
    if (requestId === communicationContactsRequest) contactsLoading.value = false
  }
}

async function saveCommunication() {
  if (!communicationForm.subject.trim() || !communicationForm.content.trim()) {
    ElMessage.warning('请填写沟通主题和内容。')
    return
  }
  communicationSaving.value = true
  try {
    const communication = await createCommunication({
      customer_account_id: customerId.value, communication_type: communicationForm.type,
      direction: communicationForm.direction, subject: communicationForm.subject.trim(),
      content: communicationForm.content.trim(), occurred_at: communicationForm.occurredAt,
      contact_participant_ids: communicationForm.contactId ? [communicationForm.contactId] : [],
    })
    if (communicationForm.createTask && canTask.value) {
      const ownerId = customer.value?.primary_owner?.id || authStore.user?.employee?.id
      if (ownerId) {
        await createTask({
          assignee_employee_id: ownerId, title: communicationForm.taskTitle.trim() || `跟进：${communicationForm.subject.trim()}`,
          description: `由沟通记录自动创建：${communicationForm.content.trim()}`, priority: 'NORMAL',
          due_at: communicationForm.taskDueAt, source_type: 'COMMUNICATION', source_id: communication.id,
        })
      }
    }
    Object.assign(communicationForm, { subject: '', content: '', taskTitle: '' })
    ElMessage.success(communicationForm.createTask ? '沟通记录和后续任务已保存。' : '沟通记录已保存。')
    await Promise.all([loadTimeline(true), loadCustomerBase(true)])
  } catch (error) {
    ElMessage.error(apiError(error, '沟通记录保存失败。'))
  } finally {
    communicationSaving.value = false
  }
}

function resetTimelineFilters() {
  Object.assign(timelineFilters, { keyword: '', eventType: '', occurredFrom: '', occurredTo: '' })
  void loadTimeline(true)
}

function clearCommunicationForm() {
  Object.assign(communicationForm, {
    type: 'EMAIL',
    direction: 'OUTBOUND',
    contactId: '',
    occurredAt: new Date().toISOString(),
    subject: '',
    content: '',
    createTask: true,
    taskTitle: '',
    taskDueAt: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
  })
}

function exportTimeline() {
  if (!timeline.value.length) {
    ElMessage.info('当前没有可导出的时间线记录。')
    return
  }
  const escape = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const header = ['时间', '类型', '标题', '摘要', '来源']
  const body = timeline.value.map((event) => [
    event.occurred_at,
    getTimelineEventTypeLabel(event.event_type),
    event.title,
    event.summary,
    getTimelineSourceTypeLabel(event.source_type),
  ].map(escape).join(','))
  const blob = new Blob([`\ufeff${header.map(escape).join(',')}\n${body.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${customer.value?.account_code || 'customer'}-时间线.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

async function loadTransfers() {
  if (!canTransfer.value) return
  try {
    const result = await fetchCustomerTransferRequests()
    transferRequests.value = result.data.filter((item) => item.customer.id === customerId.value)
  } catch (error) {
    ElMessage.error(apiError(error, '转移记录加载失败。'))
  }
}

async function submitTransfer() {
  if (!transferForm.ownerId || transferForm.reason.trim().length < 2) {
    ElMessage.warning('请选择接收人并填写至少 2 个字的转移原因。')
    return
  }
  try {
    await ElMessageBox.confirm('转移需审批，提交后不会立即变更负责人。是否继续？', '确认提交', { type: 'warning', customClass: 'customer-detail-message-box' })
    transferLoading.value = true
    await createCustomerTransferRequest({
      customer_id: customerId.value, to_employee_id: transferForm.ownerId, reason: transferForm.reason.trim(),
    })
    ElMessage.success('客户转移申请已提交，等待审批。')
    transferForm.reason = ''
    await loadTransfers()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '客户转移申请提交失败。'))
  } finally {
    transferLoading.value = false
  }
}

function canCancelTransfer(item: CustomerTransferRequest): boolean {
  return item.status === 'PENDING'
    && canTransfer.value
    && item.requested_by?.id === authStore.user?.employee?.id
}

async function decideTransfer(item: CustomerTransferRequest, action: 'approve' | 'reject' | 'cancel') {
  const labels = { approve: '审批通过', reject: '驳回', cancel: '取消申请' }
  try {
    const { value } = await ElMessageBox.prompt(
      `请输入${labels[action]}说明（至少 2 个字符）。`,
      labels[action],
      {
        confirmButtonText: '确认',
        cancelButtonText: '返回',
        inputType: 'textarea',
        inputPattern: /\S.{1,}/s,
        inputErrorMessage: '说明至少需要 2 个字符。',
        customClass: 'customer-detail-message-box',
      },
    )
    transferLoading.value = true
    const latest = await fetchCustomerTransferRequest(item.id)
    if (!latest.etag) throw new Error('转移申请缺少 ETag，无法安全提交。')
    if (action === 'approve') {
      await approveCustomerTransferRequest(item.id, value.trim(), latest.etag)
    } else if (action === 'reject') {
      await rejectCustomerTransferRequest(item.id, value.trim(), latest.etag)
    } else {
      await cancelCustomerTransferRequest(item.id, value.trim(), latest.etag)
    }
    ElMessage.success(`${labels[action]}成功。`)
    await Promise.all([loadCustomerBase(true), loadTransfers()])
  } catch (error) {
    if (error === 'cancel' || error === 'close' || (error as { action?: string }).action === 'cancel') return
    ElMessage.error(apiError(error, `${labels[action]}失败，请稍后重试。`))
  } finally {
    transferLoading.value = false
  }
}

function navigateTab(name: string) {
  const routeNames: Record<string, string> = {
    overview: 'customer-detail', timeline: 'customer-timeline',
    tasks: 'customer-tasks', complaints: 'customer-complaints',
    inquiries: 'customer-inquiries', quotations: 'customer-quotations', samples: 'customer-samples',
    orders: 'customer-orders',
  }
  void router.push({ name: routeNames[name], params: { customerId: customerId.value } })
}

function openNewInquiry() {
  void router.push({ name: 'inquiry-create', query: { customer_id: customerId.value } })
}

function openNewQuotation() {
  void router.push({ name: 'quotations', query: { customer_id: customerId.value, create: '1' } })
}

function openCustomerEdit() {
  if (canChange.value) editDialogVisible.value = true
}

async function handleCustomerEdited(updatedCustomerId: string) {
  if (updatedCustomerId !== customerId.value) return
  // 保存前的慢请求不能代替保存后的刷新。
  if (baseLoadRequest) await baseLoadRequest
  if (disposed || updatedCustomerId !== customerId.value) return
  await loadCustomerBase(true)
  if (mode.value === 'overview' || mode.value === 'timeline') await loadTimeline(true)
}

function handleHeaderMore(command: string) {
  if (command === 'edit') {
    openCustomerEdit()
  } else if (command === 'transfer') {
    void router.push({ name: 'customer-transfer', params: { customerId: customerId.value } })
  }
}

async function refreshCustomerSummary() {
  const requestId = ++summaryRequest
  try {
    const value = await fetchCustomerSummary(customerId.value)
    if (requestId === summaryRequest) summary.value = value
  } catch (error) {
    if (requestId === summaryRequest) ElMessage.error(apiError(error, '客户汇总刷新失败。'))
  }
}

async function initializeMode() {
  if (disposed || !customerId.value || !String(route.name || '').startsWith('customer-')) return
  const baseAlreadyLoaded = baseLoadedCustomerId.value === customerId.value && Boolean(customer.value)
  const requests: Promise<unknown>[] = [loadCustomerBase()]
  // 页签中的业务操作可能改变数量；仅刷新汇总，客户基础资料继续复用。
  if (baseAlreadyLoaded) requests.push(refreshCustomerSummary())
  if (mode.value === 'overview') {
    requests.push(loadTimeline(true), loadCustomerOpenTasks(), loadCommunicationContacts(true))
  }
  if (mode.value === 'timeline') requests.push(
    loadTimeline(true), loadCommunicationContacts(true),
    communicationOptions.load().catch(error => ElMessage.error(apiError(error, '沟通方式加载失败。'))),
  )
  if (mode.value === 'transfer') requests.push(loadTransfers())
  await Promise.all(requests)
}

async function refreshOverview() {
  await Promise.all([
    loadCustomerBase(true),
    loadTimeline(true),
    loadCustomerOpenTasks(),
    loadCommunicationContacts(true),
  ])
}

async function loadCustomerOpenTasks() {
  const requestId = ++customerTasksRequest
  if (!canViewTasks.value) {
    customerTasks.value = []
    customerTasksError.value = ''
    return
  }
  customerTasksLoading.value = true
  customerTasksError.value = ''
  try {
    const commonFilters = {
      scope: taskScope.value,
      customer_id: customerId.value,
      ordering: 'due_at',
      page: 1,
      page_size: 50,
    }
    const [pending, inProgress] = await Promise.all([
      fetchTasks({ ...commonFilters, status: 'PENDING' }),
      fetchTasks({ ...commonFilters, status: 'IN_PROGRESS' }),
    ])
    if (requestId !== customerTasksRequest) return
    const uniqueTasks = new Map<string, TaskSummary>()
    for (const task of [...pending.data, ...inProgress.data]) uniqueTasks.set(task.id, task)
    customerTasks.value = [...uniqueTasks.values()].sort((left, right) => {
      if (!left.due_at) return 1
      if (!right.due_at) return -1
      return new Date(left.due_at).getTime() - new Date(right.due_at).getTime()
    })
  } catch (error) {
    if (requestId !== customerTasksRequest) return
    customerTasks.value = []
    customerTasksError.value = apiError(error, '客户任务加载失败。')
  } finally {
    if (requestId === customerTasksRequest) customerTasksLoading.value = false
  }
}

async function completeCustomerTask(task: TaskSummary) {
  if (completingTaskId.value) return
  try {
    await ElMessageBox.confirm(`确认将任务“${task.title}”标记为已完成？`, '完成任务', {
      type: 'warning',
      confirmButtonText: '确认完成',
      cancelButtonText: '取消',
      customClass: 'customer-detail-message-box',
    })
    completingTaskId.value = task.id
    const latest = await fetchTask(task.id)
    if (!latest.etag) throw new Error('任务缺少版本信息，无法安全完成。')
    await postTaskAction(task.id, 'complete', { note: '在客户详情中确认完成' }, latest.etag)
    ElMessage.success('任务已完成。')
    await Promise.all([loadCustomerOpenTasks(), loadCustomerBase(true), loadTimeline(true)])
  } catch (error) {
    if (error === 'cancel' || error === 'close' || (error as { action?: string }).action === 'cancel') return
    if (error instanceof AxiosError && error.response?.status === 412) {
      ElMessage.error('任务已被其他人修改，已保留当前页面，请刷新后重试。')
      return
    }
    ElMessage.error(apiError(error, '任务完成失败，请稍后重试。'))
  } finally {
    completingTaskId.value = ''
  }
}

async function handleTaskCreated() {
  await Promise.all([loadCustomerOpenTasks(), loadCustomerBase(true), loadTimeline(true)])
}

watch(() => [editForm.accountName, editForm.website, editForm.countryCode], scheduleEditDuplicateCheck)
watch(() => editForm.primaryRegionId, () => {
  if (!secondaryRegionOptions.value.some((item) => item.id === editForm.secondaryRegionId)) {
    editForm.secondaryRegionId = ''
  }
})
watch(() => route.fullPath, () => void initializeMode())
watch(() => [route.hash, customer.value?.id, contactsLoading.value], async () => {
  if (route.hash !== '#customer-contacts' || mode.value !== 'overview' || !customer.value || contactsLoading.value) return
  await nextTick()
  document.getElementById('customer-contacts')?.scrollIntoView({ block: 'nearest' })
}, { flush: 'post' })
onMounted(initializeMode)
onBeforeUnmount(() => {
  disposed = true
  summaryRequest += 1
  communicationContactsRequest += 1
  customerTasksRequest += 1
  timelineRequest += 1
  if (duplicateTimer) clearTimeout(duplicateTimer)
})
</script>

<template>
  <div
    v-loading="loading"
    class="customer-detail-page"
    :class="[
      { 'customer-detail-page--overview-v2': isV2DetailMode, 'customer-detail-page--compact-controls': usesCompactDetailControls },
      `customer-detail-page--${mode}`,
    ]"
    data-customer-detail-page
  >
    <ElAlert v-if="loadError" type="error" :title="loadError" show-icon :closable="false">
      <ElButton size="small" @click="initializeMode">重试</ElButton>
    </ElAlert>

    <template v-if="customer">
      <section v-if="isV2DetailMode" class="customer-overview-hero" data-customer-overview-header>
        <div class="customer-overview-heading">
          <h1 :title="customer.account_name">{{ customer.account_name }}</h1>
          <div class="customer-overview-meta">
            <span>{{ customer.account_code }}</span>
            <i aria-hidden="true" />
            <span>{{ overviewRegionLabel }}</span>
            <i aria-hidden="true" />
            <span>{{ overviewGradeLabel }}</span>
            <CustomerActivityTag :activity="customer.activity" />
            <span>负责人&nbsp; {{ customer.primary_owner?.display_name || '未分配' }}</span>
            <span class="customer-type-tag">{{ overviewTypeLabel }}</span>
            <span class="profile-completeness-label">资料完整度</span>
            <strong class="profile-completeness-value">{{ profileCompleteness }}%</strong>
          </div>
          <div class="customer-overview-actions">
            <ElButton class="erp-button-motion" type="primary" :disabled="!canCommunicate" @click="navigateTab('timeline')">记录沟通</ElButton>
            <ElButton class="erp-button-motion" :disabled="!canCreateInquiry" @click="openNewInquiry">新建询盘</ElButton>
            <ElButton class="erp-button-motion" :disabled="!canCreateQuotation" @click="openNewQuotation">新建报价</ElButton>
            <ElButton class="erp-button-motion" :disabled="!canTask" @click="taskCreateVisible = true">新建任务</ElButton>
            <ElButton class="erp-button-motion" :disabled="!canChange" @click="openCustomerEdit">编辑客户</ElButton>
            <ElDropdown trigger="click" @command="handleHeaderMore">
              <ElButton class="customer-overview-more erp-button-motion">更多&nbsp;⌄</ElButton>
              <template #dropdown>
                <ElDropdownMenu>
                  <ElDropdownItem v-if="canChange" command="edit">编辑资料</ElDropdownItem>
                  <ElDropdownItem v-if="canTransfer" command="transfer">客户转移</ElDropdownItem>
                </ElDropdownMenu>
              </template>
            </ElDropdown>
          </div>
        </div>

        <nav class="customer-overview-tabs" aria-label="客户详情导航">
          <button :class="{ active: mode === 'overview' }" type="button" @click="navigateTab('overview')">概览</button>
          <button :class="{ active: mode === 'timeline' }" type="button" @click="navigateTab('timeline')">时间轴</button>
          <button :class="{ active: mode === 'tasks' }" type="button" @click="navigateTab('tasks')">任务</button>
          <button :class="{ active: mode === 'inquiries' }" type="button" @click="navigateTab('inquiries')">询盘</button>
          <button :class="{ active: mode === 'quotations' }" type="button" @click="navigateTab('quotations')">报价</button>
          <button :class="{ active: mode === 'samples' }" type="button" @click="navigateTab('samples')">样品</button>
          <button :class="{ active: mode === 'orders' }" type="button" @click="navigateTab('orders')">订单</button>
          <button :class="{ active: mode === 'complaints' }" type="button" @click="navigateTab('complaints')">客诉</button>
        </nav>
      </section>

      <section v-else-if="mode !== 'edit'" class="customer-hero">
        <div class="detail-meta-row">
          <span></span>
          <span>客户资料更新于 {{ customerUpdatedLabel }}</span>
        </div>
        <header class="customer-header">
            <div class="customer-identity">
              <span class="avatar">{{ customer.short_name.slice(0, 2).toUpperCase() || 'CU' }}</span>
              <h1>{{ customer.account_name }}</h1>
              <ElTag class="grade-tag" type="info" effect="plain">{{ customer.customer_grade?.display_name || 'A级' }}</ElTag>
              <ElTag class="status-tag" type="success">{{ customer.activity?.display_name === '数据不足' ? '正常' : (customer.activity?.display_name || '正常') }}</ElTag>
              <p>{{ customer.primary_region?.region_name || '地区未录入' }}{{ customer.secondary_region ? ` · ${customer.secondary_region.region_name}` : '' }} · {{ customer.industry?.display_name || '行业未录入' }} · 负责人：{{ customer.primary_owner?.display_name || '未分配' }}</p>
          </div>
          <div class="header-actions">
            <ElButton v-if="canCommunicate" type="primary" @click="navigateTab('timeline')">记录沟通</ElButton>
            <ElButton @click="openNewInquiry">新建询盘</ElButton>
            <ElButton v-if="canTask" class="customer-task-header-button" @click="taskCreateVisible = true">新建任务</ElButton>
            <ElDropdown trigger="click" @command="handleHeaderMore">
              <ElButton>更多</ElButton>
              <template #dropdown>
                <ElDropdownMenu>
                  <ElDropdownItem v-if="canChange" command="edit">编辑资料</ElDropdownItem>
                  <ElDropdownItem v-if="canTransfer" command="transfer">客户转移</ElDropdownItem>
                </ElDropdownMenu>
              </template>
            </ElDropdown>
          </div>
        </header>

        <nav v-if="mode !== 'transfer'" class="detail-tabs">
          <button @click="navigateTab('overview')">概览</button>
          <button :class="{ active: mode === 'timeline' }" @click="navigateTab('timeline')">时间轴</button>
          <button :class="{ active: mode === 'tasks' }" @click="navigateTab('tasks')">任务</button>
          <button :class="{ active: mode === 'inquiries' }" @click="navigateTab('inquiries')">询盘</button>
          <button :class="{ active: mode === 'quotations' }" @click="navigateTab('quotations')">报价</button>
          <button :class="{ active: mode === 'samples' }" @click="navigateTab('samples')">样品</button>
          <button :class="{ active: mode === 'orders' }" @click="navigateTab('orders')">订单</button>
          <button :class="{ active: mode === 'complaints' }" @click="navigateTab('complaints')">客诉</button>
        </nav>
      </section>

      <CustomerOverviewV2
        v-if="mode === 'overview'"
        :customer="customer"
        :summary="summary"
        :contacts="contacts"
        :contacts-loading="contactsLoading"
        :contacts-error="contactsError"
        :timeline="timeline"
        :timeline-loading="timelineLoading"
        :tasks="customerTasks"
        :tasks-loading="customerTasksLoading"
        :tasks-error="customerTasksError"
        :can-view-tasks="canViewTasks"
        :can-create-task="canTask"
        :can-edit-customer="canChange"
        :completing-task-id="completingTaskId"
        @complete-task="completeCustomerTask"
        @create-task="taskCreateVisible = true"
        @edit-customer="openCustomerEdit"
        @retry-contacts="loadCommunicationContacts(true)"
        @contacts-changed="refreshOverview"
        @refresh="refreshOverview"
        @retry-tasks="loadCustomerOpenTasks"
      />

      <main v-else-if="mode === 'edit'" class="edit-page">
        <header class="edit-page-header">
          <p>客户管理 / 客户列表 / 客户编辑</p>
          <div class="edit-title-row">
            <div><h1>编辑客户</h1><ElTag type="success">正常</ElTag><span>{{ customer.account_code }} · {{ customer.account_name }}</span></div>
            <div><small>最后保存：{{ customerUpdatedLabel }}</small><ElButton @click="router.push({ name: 'customers' })">返回列表</ElButton></div>
          </div>
        </header>

        <ElAlert v-if="duplicateMatches.length" class="edit-duplicate-alert" type="warning" :title="`发现 ${duplicateMatches.length} 个疑似重复客户，已排除当前客户`" show-icon :closable="false" />

        <section class="edit-workspace">
          <aside class="edit-section-nav">
            <div class="edit-progress"><strong>客户资料</strong><span>资料完整度 {{ profileCompleteness }}%</span><ElProgress :percentage="profileCompleteness" :show-text="false" :stroke-width="4" /></div>
            <button :class="{ active: editActiveSection === 'profile' }" type="button" @click="scrollEditSection('profile')"><ElIcon><Document /></ElIcon>主体资料</button>
            <button :class="{ active: editActiveSection === 'address' }" type="button" @click="scrollEditSection('address')"><ElIcon><Box /></ElIcon>地址信息</button>
            <button :class="{ active: editActiveSection === 'attributes' }" type="button" @click="scrollEditSection('attributes')"><ElIcon><TrendCharts /></ElIcon>客户属性</button>
            <button :class="{ active: editActiveSection === 'ownership' }" type="button" @click="scrollEditSection('ownership')"><ElIcon><User /></ElIcon>归属与标签</button>
            <div class="edit-nav-tip"><strong>{{ editCompletedCount }} / 11 项必填已完成</strong><span>保存时将统一校验</span></div>
          </aside>

          <ElForm label-position="top" class="edit-form">
            <section id="edit-section-profile" class="edit-form-card profile-card">
              <header><div><ElIcon><Document /></ElIcon><strong>主体资料</strong><span>带 * 为必填</span></div><small v-if="checkingDuplicate">正在查重…</small></header>
              <div class="figma-form-grid">
                <ElFormItem label="客户名称 *" required><ElInput v-model="editForm.accountName" /></ElFormItem><ElFormItem label="客户简称"><ElInput v-model="editForm.shortName" /></ElFormItem><ElFormItem label="法定主体名称"><ElInput v-model="editForm.entityLegalName" /></ElFormItem><ElFormItem label="网站 / 域名"><ElInput v-model="editForm.website" /></ElFormItem>
                <ElFormItem label="一级地区 *" required><ElSelect v-model="editForm.primaryRegionId" filterable><ElOption v-for="item in options?.primary_regions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="二级地区"><ElSelect v-model="editForm.secondaryRegionId" filterable clearable :disabled="!editForm.primaryRegionId"><ElOption v-for="item in secondaryRegionOptions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="默认语言"><ElSelect v-model="editDisplayForm.defaultLanguage"><ElOption label="English" value="English" /><ElOption label="简体中文" value="简体中文" /></ElSelect></ElFormItem><ElFormItem label="税号 / 注册号"><ElInput v-model="editForm.taxIdentifier" /></ElFormItem>
              </div>
            </section>

            <section id="edit-section-address" class="edit-form-card address-card">
              <header>
                <div><ElIcon><Box /></ElIcon><strong>地址信息</strong><small>已保存 {{ addresses.length }} 条</small><ElTag v-if="creatingNewAddress" type="success" size="small">待新增 {{ appendedAddressDrafts.length }} 条</ElTag></div>
                <div class="address-actions">
                  <ElSelect v-if="addresses.length" v-model="activeAddressId" size="small" @change="selectAddress"><ElOption v-for="address in addresses" :key="address.id" :label="formatAddressOption(address)" :value="address.id" /></ElSelect>
                  <ElButton text @click="startAddAddress">＋ 添加地址</ElButton>
                </div>
              </header>
              <div class="figma-form-grid">
                <ElFormItem label="地址类型 *" required><ElSelect v-model="editDisplayForm.addressType"><ElOption label="办公地址" value="办公地址" /><ElOption label="收货地址" value="收货地址" /></ElSelect></ElFormItem><ElFormItem label="国家 / 地区 *" required><ElSelect v-model="editForm.addressCountryCode"><ElOption v-for="item in options?.country_options" :key="item.id" :label="formatCountryOption(item)" :value="item.item_code" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="州 / 省"><ElInput v-model="editForm.stateProvince" /></ElFormItem><ElFormItem label="城市"><ElInput v-model="editForm.city" /></ElFormItem>
                <ElFormItem label="详细地址 *" required><ElInput v-model="editForm.addressLine1" /></ElFormItem><ElFormItem label="邮编"><ElInput v-model="editForm.postalCode" /></ElFormItem><ElFormItem label="收货联系人"><ElInput v-model="editForm.recipientName" /></ElFormItem><ElFormItem label="收货电话"><ElInput v-model="editForm.recipientPhone" /></ElFormItem>
              </div>
              <div v-for="(draft, index) in appendedAddressDrafts" :key="index" class="appended-address-block">
                <div class="appended-address-heading">
                  <strong>新增地址 {{ index + 1 }}</strong>
                  <ElButton text type="danger" @click="removeAppendedAddress(index)">删除此条</ElButton>
                </div>
                <div class="figma-form-grid">
                  <ElFormItem label="地址类型 *" required><ElSelect v-model="draft.addressType"><ElOption label="办公地址" value="办公地址" /><ElOption label="收货地址" value="收货地址" /></ElSelect></ElFormItem><ElFormItem label="国家 / 地区 *" required><ElSelect v-model="draft.countryCode"><ElOption v-for="item in options?.country_options" :key="item.id" :label="formatCountryOption(item)" :value="item.item_code" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="州 / 省"><ElInput v-model="draft.stateProvince" /></ElFormItem><ElFormItem label="城市"><ElInput v-model="draft.city" /></ElFormItem>
                  <ElFormItem label="详细地址 *" required><ElInput v-model="draft.addressLine1" /></ElFormItem><ElFormItem label="邮编"><ElInput v-model="draft.postalCode" /></ElFormItem><ElFormItem label="收货联系人"><ElInput v-model="draft.recipientName" /></ElFormItem><ElFormItem label="收货电话"><ElInput v-model="draft.recipientPhone" /></ElFormItem>
                </div>
              </div>
            </section>

            <section id="edit-section-attributes" class="edit-form-card attributes-card">
              <header><div><ElIcon><TrendCharts /></ElIcon><strong>客户属性</strong></div></header>
              <div class="figma-form-grid">
                <ElFormItem label="客户类型 *" required><ElSelect v-model="editForm.typeIds" multiple collapse-tags><ElOption v-for="item in options?.customer_types" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="客户来源 *" required><ElSelect v-model="editForm.sourceId"><ElOption v-for="item in options?.customer_sources" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem><ElFormItem label="客户等级 *" required><ElSelect v-model="editForm.gradeId"><ElOption v-for="item in options?.customer_grades" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
                <ElFormItem label="所属行业"><ElSelect v-model="editForm.industryId" clearable><ElOption v-for="item in options?.industries" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="感兴趣产品"><ElSelect v-model="editForm.interestedProductIds" multiple collapse-tags clearable><ElOption v-for="item in options?.interested_products" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="询盘关键词"><ElInput v-model="editForm.inquiryKeywords" /></ElFormItem><ElFormItem label="生命周期"><ElSelect v-model="editForm.lifecycleStage"><ElOption v-for="item in options?.lifecycle_stages" :key="item.item_code" :label="item.display_name" :value="item.item_code" /></ElSelect></ElFormItem>
              </div>
            </section>

            <section id="edit-section-ownership" class="edit-form-card ownership-card">
              <header><div><ElIcon><User /></ElIcon><strong>归属与标签</strong></div></header>
                <div class="figma-form-grid ownership-fields">
                  <ElFormItem label="负责人 *" required><ElInput :model-value="customer.primary_owner?.display_name || ''" readonly /></ElFormItem>
                  <ElFormItem label="业务员"><ElInput :model-value="sourceSalespersonNames" readonly /></ElFormItem>
                  <ElFormItem label="分管人"><ElInput :model-value="sourceManagerNames" readonly /></ElFormItem>
                </div>
            </section>
          </ElForm>
        </section>

        <footer class="edit-action-bar">
          <span><i :class="{ saved: !editIsDirty }"></i>{{ editIsDirty ? '有未保存修改 · 保存时将校验全部必填项' : '所有修改已保存' }}</span>
          <div><ElButton @click="router.push({ name: 'customer-detail', params: { customerId } })">取消</ElButton><ElButton :loading="saving" @click="saveProfile(false, true)">保存草稿</ElButton><ElButton :loading="saving" @click="saveProfile(true)">保存并返回</ElButton><ElButton type="primary" :loading="saving" @click="saveProfile(false)">保存</ElButton></div>
        </footer>
      </main>


      <main v-else-if="mode === 'tasks'" class="customer-task-embed">
        <ElEmpty v-if="!canViewTasks" description="当前账号无权查看客户任务" />
        <TaskCenterView
          v-else
          embedded
          :customer-id="customerId"
          :customer-name="customer.account_name"
          :default-scope="taskScope"
          :default-assignee-id="customer.primary_owner?.id || authStore.user?.employee?.id || ''"
        />
      </main>

      <main v-else-if="mode === 'complaints'" class="customer-complaint-embed">
        <ElEmpty v-if="!canViewComplaints" description="当前账号无权查看客户客诉" />
        <ComplaintListView
          v-else
          embedded
          :customer-id="customerId"
          :customer-name="customer.account_name"
        />
      </main>

      <CustomerRelatedRecordsV2
        v-else-if="relatedRecordKind"
        :key="`${customerId}:${relatedRecordKind}`"
        :kind="relatedRecordKind"
        :customer-id="customerId"
        :customer-name="customer.account_name"
        :sales-metrics="customer"
      />

      <main v-else-if="mode === 'timeline'" class="customer-timeline-v2 erp-glass-list">
        <section class="customer-timeline-v2__filters erp-list-filter erp-list-filters">
          <ElInput v-model="timelineFilters.keyword" placeholder="搜索主题、内容、编号" clearable @keyup.enter="loadTimeline(true)" />
          <ElSelect v-model="timelineFilters.eventType" clearable placeholder="类型：全部"><ElOption label="沟通" value="COMMUNICATION" /><ElOption label="任务" value="TASK" /><ElOption label="客户资料" value="CUSTOMER" /></ElSelect>
          <ElDatePicker v-model="timelineFilters.occurredFrom" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="开始时间" />
          <ElDatePicker v-model="timelineFilters.occurredTo" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="结束时间" />
          <div class="erp-list-filter-actions">
            <ElButton class="erp-button-motion" @click="resetTimelineFilters">重置</ElButton>
            <ElButton class="erp-button-motion" type="primary" @click="loadTimeline(true)">应用筛选</ElButton>
          </div>
        </section>

        <div class="customer-timeline-v2__workspace">
          <section v-loading="timelineLoading" class="customer-timeline-v2__list-panel erp-list-surface">
            <header><div><h2>客户时间轴</h2><small>{{ timeline.length }} 条已加载</small></div><ElButton class="erp-button-motion" @click="exportTimeline">导出记录</ElButton></header>
            <div v-if="timeline.length" class="customer-timeline-v2__list">
              <article v-for="event in timeline" :key="event.id" class="customer-timeline-v2__event">
                <time>{{ formatDate(event.occurred_at) }}</time>
                <span class="customer-timeline-v2__dot" aria-hidden="true" />
                <div>
                  <div><CustomerActivityTag :label="getTimelineEventTypeLabel(event.event_type)" tone="info" /><strong :title="event.title">{{ event.title }}</strong></div>
                  <p :title="event.summary || ''">{{ event.summary || '无补充摘要' }}</p>
                  <small>来源：{{ getTimelineSourceTypeLabel(event.source_type) }} · 只读业务事实</small>
                </div>
              </article>
              <ElButton v-if="timelineCursor" class="customer-timeline-v2__more" :loading="timelineLoading" @click="loadTimeline(false)">加载更多记录</ElButton>
            </div>
            <ElEmpty v-else description="暂无符合条件的时间线记录" />
          </section>

          <section class="customer-timeline-v2__composer erp-list-surface erp-flat-form">
            <header><div><h2>记录沟通</h2><span>保存后写入客户时间轴</span></div></header>
            <ElForm label-position="top">
              <ElFormItem label="沟通方式" required><ElRadioGroup v-model="communicationForm.type"><ElRadioButton v-for="item in communicationTypeOptions" :key="item.id" :value="item.code">{{ item.label }}</ElRadioButton></ElRadioGroup></ElFormItem>
              <div class="customer-timeline-v2__form-grid">
                <ElFormItem label="联系人"><ElSelect v-model="communicationForm.contactId" clearable placeholder="选择联系人"><ElOption v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
                <ElFormItem label="沟通方向" required><ElSelect v-model="communicationForm.direction"><ElOption label="去电 / 发出" value="OUTBOUND" /><ElOption label="来电 / 收到" value="INBOUND" /><ElOption label="内部沟通" value="INTERNAL" /></ElSelect></ElFormItem>
                <ElFormItem label="沟通时间" required><ElDatePicker v-model="communicationForm.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></ElFormItem>
              </div>
              <ElFormItem label="主题" required><ElInput v-model="communicationForm.subject" maxlength="250" placeholder="输入本次沟通主题" /></ElFormItem>
              <ElFormItem label="沟通内容" required><ElInput v-model="communicationForm.content" type="textarea" :rows="5" maxlength="5000" show-word-limit placeholder="记录关键需求、结论与待办" /></ElFormItem>
              <div class="customer-timeline-v2__attachment" title="当前沟通接口暂未接入附件字段"><strong>附件</strong><span>附件接口尚未接入，暂不可上传</span></div>
              <section class="customer-timeline-v2__followup">
                <ElCheckbox v-model="communicationForm.createTask" :disabled="!canTask">同时创建下一步跟进任务</ElCheckbox>
                <div v-if="communicationForm.createTask" class="customer-timeline-v2__form-grid customer-timeline-v2__form-grid--two"><ElFormItem label="任务标题"><ElInput v-model="communicationForm.taskTitle" /></ElFormItem><ElFormItem label="截止时间"><ElDatePicker v-model="communicationForm.taskDueAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></ElFormItem></div>
              </section>
            </ElForm>
            <footer><ElButton @click="clearCommunicationForm">清空</ElButton><ElButton type="primary" :disabled="!canCommunicate" :loading="communicationSaving" @click="saveCommunication">保存沟通</ElButton></footer>
          </section>
        </div>
      </main>

      <main v-else class="transfer-page erp-glass-list">
        <header class="section-heading erp-list-surface"><div><h2>客户转移申请</h2><p>转移客户归属，不修改历史订单和财务事实。</p></div><ElButton class="erp-button-motion" @click="router.push({ name: 'customer-detail', params: { customerId } })">取消</ElButton></header>
        <section class="transfer-grid">
          <ElCard shadow="never"><template #header><strong>转移设置</strong></template><ElAlert :title="`当前负责人：${customer.primary_owner?.display_name || '未分配'}`" type="info" :closable="false" /><ElForm label-position="top"><ElFormItem label="接收人" required><ElSelect v-model="transferForm.ownerId" filterable><ElOption v-for="owner in options?.owner_options.filter((item) => item.id !== customer?.primary_owner?.id)" :key="owner.id" :label="owner.display_name" :value="owner.id" /></ElSelect></ElFormItem><ElFormItem label="转移原因" required><ElInput v-model="transferForm.reason" type="textarea" :rows="4" maxlength="2000" /></ElFormItem><ElCheckbox checked disabled>通知原负责人和接收人</ElCheckbox></ElForm><ElButton type="primary" :loading="transferLoading" :disabled="!canTransfer" @click="submitTransfer">预览并提交</ElButton></ElCard>
          <ElCard shadow="never"><template #header><strong>关联对象影响</strong></template><ElDescriptions :column="1" border><ElDescriptionsItem label="联系人">{{ summary?.counts.contacts || 0 }} 个，保持归属客户不变</ElDescriptionsItem><ElDescriptionsItem label="进行中询价">{{ summary?.counts.open_inquiries || 0 }} 个，自动归属接收人可见范围</ElDescriptionsItem><ElDescriptionsItem label="有效报价">{{ summary?.counts.open_quotations || 0 }} 个，历史版本不改写</ElDescriptionsItem><ElDescriptionsItem label="样品跟进">{{ summary?.counts.active_samples || 0 }} 个，状态不变</ElDescriptionsItem><ElDescriptionsItem label="未完成任务">{{ summary?.counts.open_tasks || 0 }} 个，审批执行时按后端策略处理</ElDescriptionsItem></ElDescriptions></ElCard>
          <ElCard shadow="never"><template #header><strong>审批与历史</strong></template><ElAlert title="未完成任务保留原任务事实与负责人；客户可见范围在转移获批后随新归属更新。" type="warning" :closable="false" show-icon /><ElTimeline v-if="transferRequests.length"><ElTimelineItem v-for="item in transferRequests" :key="item.id" :timestamp="formatDate(item.submitted_at)"><strong>{{ item.from_employee.display_name }} → {{ item.to_employee.display_name }}</strong><p>{{ item.request_reason }}</p><p v-if="item.decision_note" class="muted">处理说明：{{ item.decision_note }}</p><div class="transfer-actions"><ElTag>{{ item.status }}</ElTag><template v-if="item.status === 'PENDING'"><ElButton v-if="canApproveTransfer" size="small" type="success" :loading="transferLoading" @click="decideTransfer(item, 'approve')">审批通过</ElButton><ElButton v-if="canApproveTransfer" size="small" type="danger" plain :loading="transferLoading" @click="decideTransfer(item, 'reject')">驳回</ElButton><ElButton v-if="canCancelTransfer(item)" size="small" :loading="transferLoading" @click="decideTransfer(item, 'cancel')">取消申请</ElButton></template></div></ElTimelineItem></ElTimeline><ElEmpty v-else description="暂无转移申请" :image-size="70" /></ElCard>
        </section>
      </main>
    </template>

    <CustomerEditDialog v-model="editDialogVisible" :customer-id="customerId" @saved="handleCustomerEdited" @cancelled="handleCustomerEdited(customerId)" />

    <TaskCreateDialog
      v-model="taskCreateVisible"
      embedded
      :scope="taskScope"
      :fixed-customer-id="customerId"
      :fixed-customer-name="customer?.account_name || ''"
      :default-assignee-id="customer?.primary_owner?.id || authStore.user?.employee?.id || ''"
      @created="handleTaskCreated"
    />

    <AppWindowDialog v-model="tagDialogVisible" class="customer-detail-dialog" title="添加客户标签" :width="460" :height="420">
      <div class="tag-create-row">
        <ElInput
          v-model="newTagForm.name"
          maxlength="100"
          placeholder="输入新标签名称"
          clearable
          @keyup.enter="createTagInDialog"
        />
        <ElColorPicker v-model="newTagForm.color" />
        <ElButton type="primary" :loading="tagCreating" @click="createTagInDialog">新增</ElButton>
      </div>
      <p class="tag-create-tip">新增后立即保存到标签库，并自动勾选当前标签。</p>
      <ElEmpty v-if="!options?.customer_tags.length" description="暂无可用客户标签" :image-size="64" />
      <ElCheckboxGroup v-else v-model="tagDraftIds" class="tag-choice-list">
        <ElCheckbox v-for="item in options.customer_tags" :key="item.id" :value="item.id">{{ item.tag_name }}</ElCheckbox>
      </ElCheckboxGroup>
      <template #footer><ElButton @click="tagDialogVisible = false">取消</ElButton><ElButton type="primary" :disabled="!options?.customer_tags.length" @click="applySelectedTags">确定</ElButton></template>
    </AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.customer-detail-page {
  min-width: 0;
  min-height: calc(100% + 48px);
  margin: -24px;
  color: var(--erp-color-text-primary);
  background: var(--erp-page-background);
  --el-color-primary: var(--erp-color-brand);
}

.customer-detail-page--overview-v2 {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
  min-height: 0;
  margin: 0;
  color: token.$crm-text-primary;
  background: transparent;
  font-family: token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary};
}

.customer-overview-hero {
  position: relative;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 16px 16px 10px;
  border: 1px solid var(--erp-glass-border);
  border-radius: var(--erp-glass-radius);
  background: var(--erp-glass-surface);
  box-shadow: var(--erp-glass-shadow);
  backdrop-filter: var(--erp-glass-backdrop);
}

.customer-overview-heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px 20px;
}

.customer-overview-heading h1 {
  min-width: 0;
  margin: 0;
  color: token.$crm-text-primary;
  font-family: token.$crm-font-body;
  font-size: 36px !important;
  font-weight: 700;
  line-height: 44px;
  overflow-wrap: anywhere;
}

.customer-overview-meta {
  grid-column: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
  color: token.$crm-text-secondary;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}

.customer-overview-meta > i {
  width: 1px;
  height: 12px;
  background: token.$crm-border-strong;
}

.customer-overview-meta :deep(.customer-activity-tag) {
  min-width: 52px;
  margin-left: 2px;
  padding: 0 9px;
  border-radius: token.$crm-radius-2;
  font-size: 11px;
}

.customer-overview-meta :deep(.customer-activity-tag.is-success) {
  color: token.$crm-success;
  background: token.$crm-success-soft;
}

.customer-overview-meta :deep(.customer-activity-tag.is-info) {
  color: var(--erp-tag-info-text);
  background: var(--erp-tag-info-background);
}

.customer-overview-meta :deep(.customer-activity-tag.is-warning) {
  color: token.$crm-warning;
  background: token.$crm-warning-soft;
}

.customer-overview-meta :deep(.customer-activity-tag.is-danger) {
  color: token.$crm-danger;
  background: token.$crm-danger-soft;
}

.customer-overview-meta :deep(.customer-activity-tag.is-neutral) {
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
}

.profile-completeness-label {
  margin-left: -2px;
}

.profile-completeness-value {
  margin-left: -6px;
  color: token.$crm-primary;
  font-weight: 700;
}

.customer-type-tag {
  height: 24px;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
  font-size: 11px;
  font-weight: 500;
}

.customer-overview-actions {
  grid-column: 2;
  grid-row: 1 / span 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.customer-overview-actions :deep(.el-button) {
  height: 32px;
  margin: 0;
  padding: 0 14px;
  border-color: var(--erp-button-secondary-border);
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: var(--erp-button-secondary-surface);
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

.customer-overview-actions :deep(.el-button:not(.is-disabled):hover) {
  border-color: token.$crm-border-strong;
  color: token.$crm-primary-hover;
  background: var(--erp-button-secondary-hover-surface);
}

.customer-overview-actions :deep(.el-button--primary) {
  border-color: var(--erp-button-primary-border);
  color: token.$crm-text-inverse;
  background: var(--erp-button-primary-surface);
}

.customer-overview-actions :deep(.el-button--primary:not(.is-disabled):hover) {
  border-color: var(--erp-button-primary-border);
  color: token.$crm-text-inverse;
  background: var(--erp-button-primary-hover-surface);
}

.customer-overview-actions :deep(.el-button.is-disabled) {
  border-color: token.$crm-border-default;
  color: token.$crm-text-disabled;
  background: token.$crm-color-disabled;
}

.customer-overview-tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 6px;
  margin-top: 14px;
}

.customer-overview-tabs button {
  position: relative;
  height: 32px;
  padding: 0 12px;
  border: 0;
  color: token.$crm-text-secondary;
  background: transparent;
  font-family: token.$crm-font-body;
  font-size: 13px;
  line-height: 20px;
  font-weight: 500;
  cursor: pointer;
}

.customer-overview-tabs button:hover {
  color: token.$crm-primary-hover;
}

.customer-overview-tabs button.active {
  color: token.$crm-primary;
  font-weight: 600;
}

.customer-overview-tabs button.active::after {
  position: absolute;
  right: 12px;
  bottom: 0;
  left: 12px;
  height: 3px;
  border-radius: 4px 4px 1px 1px;
  background: var(--erp-tab-active-indicator);
  content: '';
}

.customer-overview-tabs button:disabled {
  color: token.$crm-text-disabled;
  cursor: not-allowed;
}
.customer-timeline-v2.erp-glass-list { height: auto; min-width: 0; padding: 0; font-size: 13px; line-height: 20px; }
.customer-timeline-v2__filters { gap: 8px; }
.customer-timeline-v2__filters :deep(.el-input) { width: 250px; max-width: 100%; }
.customer-timeline-v2__filters :deep(.el-select) { width: 150px; }
.customer-timeline-v2__filters :deep(.el-date-editor) { width: 185px; max-width: 100%; }
.customer-timeline-v2__filters :deep(.el-button) { margin: 0; }
.customer-timeline-v2__workspace { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); align-items: start; gap: 14px; }
.customer-timeline-v2__list-panel, .customer-timeline-v2__composer { min-width: 0; padding: 16px; }
.customer-timeline-v2__list-panel > header, .customer-timeline-v2__composer > header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.customer-timeline-v2__list-panel h2, .customer-timeline-v2__composer h2 { margin: 0; font-family: token.$crm-font-body; font-size: 16px; font-weight: 700; line-height: 24px; }
.customer-timeline-v2__list-panel header span, .customer-timeline-v2__composer header span, .customer-timeline-v2__list-panel header small { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.customer-timeline-v2__list-panel header div, .customer-timeline-v2__composer header div { display: flex; flex-direction: column; gap: 4px; }
.customer-timeline-v2__list { min-width: 0; }
.customer-timeline-v2__event { display: grid; grid-template-columns: 112px 12px minmax(0, 1fr); align-items: start; gap: 10px; padding: 14px 0; border-bottom: 1px solid token.$crm-border-subtle; }
.customer-timeline-v2__event:last-of-type { border-bottom: 0; }
.customer-timeline-v2__event time { color: token.$crm-text-muted; font-size: 12px; line-height: 20px; }
.customer-timeline-v2__dot { width: 8px; height: 8px; margin-top: 7px; border: 2px solid token.$crm-color-surface; border-radius: 50%; background: token.$crm-primary; box-shadow: 0 0 0 1px token.$crm-primary; }
.customer-timeline-v2__event > div { min-width: 0; }
.customer-timeline-v2__event > div > div { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.customer-timeline-v2__event strong { font-size: 13px; line-height: 20px; overflow-wrap: anywhere; }
.customer-timeline-v2__event p { margin: 6px 0; color: token.$crm-text-regular; font-size: 13px; line-height: 20px; overflow-wrap: anywhere; }
.customer-timeline-v2__event small { color: token.$crm-text-muted; font-size: 12px; overflow-wrap: anywhere; }
.customer-timeline-v2__more { width: 100%; margin: 12px 0 0; }
.customer-timeline-v2__composer :deep(.el-form-item) { margin-bottom: 14px; }
.customer-timeline-v2__composer :deep(.el-form-item__label) { height: auto; margin-bottom: 4px; color: token.$crm-text-regular; font-size: 12px; line-height: 20px; }
.customer-timeline-v2__composer :deep(.el-select), .customer-timeline-v2__composer :deep(.el-date-editor) { width: 100%; min-width: 0; }
.customer-timeline-v2__composer :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: 6px; }
.customer-timeline-v2__composer :deep(.el-radio-button__inner) { height: 32px; padding: 0 12px; border: 1px solid token.$crm-border-default; border-radius: var(--erp-radius-control); font-size: 12px; line-height: 30px; box-shadow: none; }
.customer-timeline-v2__form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.customer-timeline-v2__form-grid > :last-child:nth-child(odd) { grid-column: 1 / -1; }
.customer-timeline-v2__form-grid--two { margin-top: 12px; }
.customer-timeline-v2__attachment { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 12px; border: 1px dashed token.$crm-border-default; border-radius: var(--erp-radius-control); color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 12px; }
.customer-timeline-v2__attachment strong { color: token.$crm-text-secondary; }
.customer-timeline-v2__followup { margin-top: 12px; padding-top: 12px; border-top: 1px solid token.$crm-border-subtle; }
.customer-timeline-v2__composer > footer { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid token.$crm-border-subtle; }
.customer-timeline-v2__composer > footer :deep(.el-button) { margin: 0; }
@media (max-width: 1599px) {
  .customer-overview-heading { grid-template-columns: minmax(0, 1fr); }
  .customer-overview-actions { grid-column: 1; grid-row: auto; justify-content: flex-end; margin-top: 6px; }
}
@media (max-width: 980px) {
  .customer-timeline-v2__workspace { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 600px) {
  .customer-timeline-v2__event { grid-template-columns: 12px minmax(0, 1fr); }
  .customer-timeline-v2__event time { grid-column: 1 / -1; }
  .customer-timeline-v2__form-grid { grid-template-columns: minmax(0, 1fr); }
}
.customer-header, .customer-identity, .header-actions, .detail-tabs, .section-heading, .timeline-filters, .sticky-actions { display: flex; align-items: center; }
.customer-hero { border-bottom: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
.detail-meta-row { min-height: 32px; display: flex; align-items: center; justify-content: space-between; padding: 7px 24px 0; color: var(--erp-color-text-regular); font-size: 12px; }
.customer-header { min-height: 65px; justify-content: space-between; gap: 18px; padding: 2px 24px 12px; }
.customer-identity { min-width: 0; gap: 12px; }
.customer-identity h1 { max-width: 320px; flex: none; overflow: hidden; margin: 0; color: var(--erp-color-text-primary); font-size: 26px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.customer-identity p, .section-heading p { min-width: 0; overflow: hidden; margin: 0; color: var(--erp-color-text-regular); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.avatar { flex: none; display: grid; width: 40px; height: 40px; place-items: center; border-radius: 9px; color: var(--erp-color-text-inverse); background: var(--erp-color-brand); font-weight: 700; }
.grade-tag { min-width: 72px; justify-content: center; border: 0; color: var(--erp-tag-neutral-text); background: var(--erp-tag-neutral-background); }
.status-tag { min-width: 72px; justify-content: center; border: 0; }
.header-actions { flex: none; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.header-actions :deep(.el-button) { min-width: 96px; height: 32px; margin: 0; padding: 0 18px; border-radius: 8px; }
.header-actions :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }
.detail-tabs { height: 58px; gap: 0; padding: 0 24px; border-top: 1px solid var(--erp-color-border); }
.detail-tabs button { height: 58px; flex: none; padding: 0 28px; border: 0; border-bottom: 2px solid transparent; color: var(--erp-color-text-regular); background: transparent; cursor: pointer; white-space: nowrap; }
.detail-tabs button.active { border-bottom-color: var(--erp-color-border); color: var(--erp-color-text-primary); font-weight: 700; }
.detail-tabs button:disabled { color: var(--erp-color-text-disabled); cursor: not-allowed; }
.overview-page { padding: 24px; background: var(--erp-page-background); }
.customer-complaint-embed { min-width: 0; }
.snapshot-banner { min-height: 40px; display: flex; align-items: center; gap: 10px; padding: 0 14px; border: 1px solid var(--erp-color-border-strong); border-radius: 7px; color: var(--erp-color-info); background: var(--erp-color-subtle); font-size: 12px; }
.snapshot-banner span { flex: 1; }
.snapshot-banner button { border: 0; color: var(--erp-color-info); background: transparent; font: inherit; font-weight: 600; cursor: pointer; }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 12px 0; }
.metric-grid article { position: relative; min-width: 0; min-height: 116px; display: flex; flex-direction: column; padding: 18px 14px; border: 1px solid var(--erp-color-border); border-radius: 9px; background: var(--erp-color-surface); }
.metric-grid small { color: var(--erp-color-text-regular); font-size: 12px; }
.metric-grid strong { overflow: hidden; margin-top: 14px; color: var(--erp-color-text-primary); font-size: 22px; line-height: 1; text-overflow: ellipsis; white-space: nowrap; }
.metric-grid span { margin-top: 8px; color: var(--erp-color-text-regular); font-size: 11px; }
.metric-grid .is-positive { color: var(--erp-color-success); }
.metric-grid .is-warning { color: var(--erp-color-warning); }
.metric-secondary { position: absolute; right: 14px; bottom: 16px; }
.metric-icon { position: absolute; top: 12px; right: 12px; box-sizing: content-box; padding: 8px; border-radius: 8px; color: var(--erp-color-text-regular); background: var(--erp-color-subtle); }
.overview-grid { display: grid; grid-template-columns: 1.62fr 1fr 1fr; gap: 18px; }
.legacy-source-card { margin-top: 12px; padding: 18px; border: 1px solid var(--erp-color-border); border-radius: 10px; background: var(--erp-color-surface); }
.legacy-source-card > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--erp-color-border); }
.legacy-source-card > header > div { display: flex; align-items: center; gap: 8px; color: var(--erp-color-text-primary); }
.legacy-source-card > header span { color: var(--erp-color-text-regular); font-size: 11px; }
.legacy-source-card dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; margin: 0; }
.legacy-source-card dl > div { min-width: 0; padding: 12px 10px; border-bottom: 1px solid var(--erp-color-border); }
.legacy-source-card dt { margin-bottom: 4px; color: var(--erp-color-text-regular); font-size: 11px; }
.legacy-source-card dd { overflow-wrap: anywhere; margin: 0; color: var(--erp-color-text-primary); font-size: 13px; }
.overview-card { min-width: 0; min-height: 638px; overflow: hidden; border: 1px solid var(--erp-color-border); border-radius: 9px; background: var(--erp-color-surface); }
.panel-header { height: 56px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; border-bottom: 1px solid var(--erp-color-border); }
.panel-header > div { display: flex; align-items: center; gap: 10px; }
.panel-header strong { color: var(--erp-color-text-primary); font-size: 15px; }
.panel-header span { color: var(--erp-color-text-regular); font-size: 11px; }
.panel-header button { border: 0; color: var(--erp-color-text-primary); background: transparent; font-weight: 600; cursor: pointer; }
.activity-list { display: flex; flex-direction: column; gap: 8px; padding: 16px; }
.activity-item { min-height: 96px; display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 7px; }
.activity-item > .el-icon { box-sizing: content-box; padding: 8px; border-radius: 8px; color: var(--erp-color-text-regular); background: var(--erp-color-subtle); }
.activity-item div { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.activity-item strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.activity-item span, .activity-item time { color: var(--erp-color-text-regular); font-size: 11px; }
.activity-item time { white-space: nowrap; }
.next-action-list { display: flex; flex-direction: column; gap: 10px; padding: 16px 16px 8px; }
.next-action-item { min-height: 106px; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; align-items: start; gap: 10px; padding: 16px 12px; border: 1px solid var(--erp-color-border); border-radius: 7px; }
.next-action-item { cursor: pointer; }
.next-action-item div { min-width: 0; display: flex; flex-direction: column; gap: 13px; }
.next-action-item strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.next-action-item span { color: var(--erp-color-text-regular); font-size: 11px; white-space: nowrap; }
.next-action-item em { min-width: 72px; padding: 5px 10px; border-radius: 7px; color: var(--erp-color-warning); background: var(--erp-color-subtle); font-size: 11px; font-style: normal; text-align: center; }
.create-task-button { min-width: 96px; height: 32px; margin: 12px 16px; border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }
.risk-panel { padding-bottom: 18px; }
.credit-usage { margin: 16px; padding: 18px 12px; border: 1px solid var(--erp-color-border); border-radius: 7px; }
.credit-usage > div { display: flex; justify-content: space-between; color: var(--erp-color-text-regular); font-size: 11px; }
.credit-usage strong { display: block; margin: 18px 0 10px; font-size: 19px; }
.credit-usage :deep(.el-progress-bar__inner) { background: var(--erp-color-info); }
.risk-note { min-height: 104px; display: flex; flex-direction: column; gap: 8px; margin: 0 16px 10px; padding: 16px 12px; border: 1px solid; border-radius: 7px; }
.risk-note strong { font-size: 12px; }
.risk-note span { color: var(--erp-color-text-regular); font-size: 10px; }
.risk-note.warning { border-color: var(--erp-color-warning-border); color: var(--erp-color-warning); background: var(--erp-color-subtle); }
.risk-note.danger { border-color: var(--erp-color-danger-border); color: var(--erp-color-danger); background: var(--erp-color-subtle); }
.risk-note.info { border-color: var(--erp-color-border-strong); color: var(--erp-color-info); background: var(--erp-color-subtle); }
.risk-panel > p { margin: 22px 16px 0; color: var(--erp-color-text-regular); font-size: 10px; }
.timeline-page { margin: 24px; }
.customer-task-embed { min-width: 0; }
.related-module-page { min-width: 0; padding: 24px; }
.related-module-heading { min-height: 48px; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.related-module-heading h2 { margin: 0 0 4px; color: var(--erp-color-text-primary); font-size: 20px; line-height: 26px; }
.related-module-heading p { margin: 0; color: var(--erp-color-text-regular); font-size: 12px; line-height: 18px; }
.related-module-heading :deep(.el-button) { height: 32px; margin: 0; border-radius: 8px; }
.related-module-heading :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }
.related-table-card { overflow: hidden; border: 1px solid var(--erp-table-border); border-radius: 8px; background: var(--erp-table-background); box-shadow: 0 4px 12px color-mix(in srgb, var(--erp-shadow-color) 5%, transparent); }
.related-table-card :deep(.el-table__header-wrapper th.el-table__cell) { height: 44px; color: var(--erp-table-text); background: var(--erp-table-header-background); font-size: 12px; font-weight: 600; }
.related-table-card :deep(.el-table__body-wrapper td.el-table__cell) { height: 48px; color: var(--erp-table-text); font-size: 12px; }
.related-table-card :deep(.el-table__row:hover > td.el-table__cell) { background: var(--erp-table-background); }
.related-table-card :deep(.el-tag) { min-width: 72px; height: 24px; justify-content: center; border: 0; border-radius: 6px; color: var(--erp-tag-neutral-text); background: var(--erp-tag-neutral-background); font-size: 11px; }
.related-table-card :deep(.el-button) { height: 28px; margin: 0; border-radius: 6px; font-size: 12px; }
.timeline-page :deep(.el-card__header) { display: flex; justify-content: space-between; }
.section-heading { justify-content: space-between; margin-bottom: 14px; }
.section-heading h2 { margin: 0; font-size: 24px; }
.edit-page { width: min(1320px, calc(100% - 48px)); margin: 24px auto 0; padding-bottom: 24px; }
.edit-page-header { height: 72px; }
.edit-page-header > p { margin: 0 0 8px; color: var(--erp-color-text-regular); font-size: 12px; line-height: 14px; }
.edit-title-row, .edit-title-row > div { display: flex; align-items: center; }
.edit-title-row { height: 44px; justify-content: space-between; }
.edit-title-row > div { gap: 12px; }
.edit-title-row h1 { margin: 0; color: var(--erp-color-text-primary); font-size: 26px; line-height: 32px; }
.edit-title-row span, .edit-title-row small { color: var(--erp-color-text-regular); font-size: 13px; }
.edit-title-row :deep(.el-tag) { width: 72px; height: 24px; border: 0; border-radius: 6px; }
.edit-title-row :deep(.el-button) { width: 96px; height: 32px; margin-left: 0; border-color: var(--erp-color-border); border-radius: 8px; }
.edit-duplicate-alert { margin-bottom: 8px; }
.edit-workspace { height: 808px; display: grid; grid-template-columns: 196px minmax(0, 1fr); overflow: hidden; margin-top: 16px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); box-shadow: 0 8px 18px color-mix(in srgb, var(--erp-shadow-color) 10%, transparent); }
.edit-section-nav { padding: 24px 16px; border-right: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
.edit-progress { height: 46px; display: flex; flex-direction: column; gap: 3px; margin-bottom: 8px; }
.edit-progress strong { color: var(--erp-color-text-primary); font-size: 14px; line-height: 17px; }
.edit-progress span { color: var(--erp-color-text-regular); font-size: 11px; line-height: 13px; }
.edit-progress :deep(.el-progress-bar__outer) { background: var(--erp-color-subtle); }
.edit-progress :deep(.el-progress-bar__inner) { background: var(--erp-color-surface); }
.edit-section-nav > button { width: 164px; height: 40px; display: flex; align-items: center; gap: 10px; margin: 0 0 8px; padding: 0 12px; border: 0; border-radius: 8px; color: var(--erp-color-text-primary); background: transparent; font-size: 13px; cursor: pointer; }
.edit-section-nav > button:hover { background: var(--erp-color-hover); }
.edit-section-nav > button.active { color: var(--erp-color-text-primary); background: var(--erp-color-selected); font-weight: 600; }
.edit-section-nav > button :deep(.el-icon) { width: 20px; height: 20px; font-size: 20px; }
.edit-nav-tip { height: 66px; display: flex; flex-direction: column; gap: 4px; margin-top: 8px; padding: 10px; border: 1px solid var(--erp-color-border); border-radius: 7px; background: var(--erp-color-surface); }
.edit-nav-tip strong { font-size: 11px; line-height: 14px; }
.edit-nav-tip span { color: var(--erp-color-text-regular); font-size: 10px; }
.edit-form { height: 808px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; padding: 24px; scroll-behavior: smooth; }
.edit-form-card { flex: none; box-sizing: border-box; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); scroll-margin-top: 24px; }
.edit-form-card.profile-card { height: 182px; }
.edit-form-card.address-card { min-height: 180px; }
.edit-form-card.attributes-card { height: 170px; padding-top: 10px; }
.edit-form-card.ownership-card { height: 192px; }
.edit-form-card > header { height: 20px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.edit-form-card > header > div { display: flex; align-items: center; gap: 8px; }
.edit-form-card > header strong { color: var(--erp-color-text-primary); font-size: 14px; line-height: 17px; }
.edit-form-card > header span, .edit-form-card > header small { color: var(--erp-color-text-regular); font-size: 10px; }
.edit-form-card > header :deep(.el-icon) { width: 20px; height: 20px; color: var(--erp-color-text-regular); font-size: 20px; }
.edit-form-card > header :deep(.el-button) { height: 28px; padding: 0 12px; color: var(--erp-color-text-primary); font-size: 12px; }
.address-actions { display: flex; align-items: center; gap: 6px; }
.address-actions :deep(.el-select) { width: 172px; }
.address-actions :deep(.el-select__wrapper) { min-height: 28px; }
.appended-address-block { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--erp-color-border); }
.appended-address-heading { height: 28px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.appended-address-heading strong { color: var(--erp-color-text-primary); font-size: 12px; }
.appended-address-heading :deep(.el-button) { height: 28px; margin: 0; padding: 0 4px; font-size: 11px; }
.figma-form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px 16px; }
.figma-form-grid :deep(.el-form-item) { height: 52px; margin: 0; }
.figma-form-grid :deep(.el-form-item__label), .customer-tags-field :deep(.el-form-item__label) { height: 17px; margin: 0; padding: 0; color: var(--erp-color-text-secondary); font-size: 11px; line-height: 13px; }
.figma-form-grid :deep(.el-form-item__content) { height: 32px; line-height: 32px; }
.figma-form-grid :deep(.el-select), .figma-form-grid :deep(.el-input) { width: 100%; }
.figma-form-grid :deep(.el-input__wrapper), .figma-form-grid :deep(.el-select__wrapper), .customer-tags-field :deep(.el-select__wrapper) { min-height: 32px; padding: 0 12px; border-radius: 8px; box-shadow: 0 0 0 1px var(--erp-color-border) inset; }
.figma-form-grid :deep(.el-input__inner), .figma-form-grid :deep(.el-select__placeholder), .figma-form-grid :deep(.el-select__selected-item), .customer-tags-field :deep(.el-select__selected-item) { color: var(--erp-input-text); font-size: 13px; }
.customer-tags-field { height: 52px; margin: 8px 0 0; }
.customer-tags-field :deep(.el-form-item__content) { height: 32px; display: flex; flex-wrap: nowrap; gap: 8px; }
.selected-tag-list { display: flex; align-items: center; gap: 8px; }
.selected-tag-list :deep(.el-tag) { min-width: 72px; height: 24px; justify-content: center; border: 0; border-radius: 6px; font-size: 11px; }
.customer-tags-field :deep(.el-button) { height: 28px; padding: 0 4px; color: var(--erp-color-brand); font-size: 12px; }
.customer-tags-field > :deep(.el-form-item__content) > span { color: var(--erp-color-text-secondary); font-size: 10px; white-space: nowrap; }
.tag-create-row { display: grid; grid-template-columns: minmax(0, 1fr) 32px 64px; align-items: center; gap: 10px; }
.tag-create-tip { margin: 8px 0 18px; color: var(--erp-color-text-secondary); font-size: 12px; }
.tag-choice-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.edit-action-bar { height: 56px; display: flex; align-items: center; justify-content: space-between; margin-top: 16px; padding: 0 16px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); }
.edit-action-bar > span { display: flex; align-items: center; gap: 8px; color: var(--erp-color-text-regular); font-size: 11px; }
.edit-action-bar i { width: 8px; height: 8px; border-radius: 50%; background: var(--erp-color-warning); }
.edit-action-bar i.saved { background: var(--erp-color-success); }
.edit-action-bar > div { display: flex; gap: 8px; }
.edit-action-bar :deep(.el-button) { width: 96px; height: 32px; margin: 0; border-radius: 8px; }
.edit-action-bar :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }
.form-grid { display: grid; gap: 0 12px; }
.form-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 12px; }
.form-grid :deep(.el-select), .form-grid :deep(.el-date-editor) { width: 100%; }
.sticky-actions { position: sticky; z-index: 3; bottom: 0; justify-content: space-between; gap: 12px; margin-top: 16px; padding: 14px 18px; border: 1px solid var(--erp-color-border); border-radius: 10px; background: color-mix(in srgb, var(--erp-color-surface) 96%, transparent); box-shadow: 0 -5px 16px color-mix(in srgb, var(--erp-shadow-color) 6%, transparent); }
.sticky-actions span { color: var(--erp-color-text-regular); font-size: 13px; }
.timeline-filters { gap: 10px; margin-bottom: 12px; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 10px; background: var(--erp-color-surface); }
.timeline-layout { display: grid; grid-template-columns: 1.5fr 1fr; gap: 12px; }
.timeline-event { padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 8px; }
.timeline-event strong { margin-left: 10px; }
.timeline-event p { margin: 10px 0; }
.timeline-event small { color: var(--erp-color-text-regular); }
.transfer-grid { display: grid; grid-template-columns: 1.1fr 1fr 1fr; gap: 12px; }
.transfer-grid :deep(.el-select) { width: 100%; }
.transfer-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.transfer-page.erp-glass-list { height: auto; margin: 0; font-size: 13px; line-height: 20px; }
.transfer-page .section-heading { margin: 0; padding: 16px; gap: 12px; }
.transfer-page .section-heading h2 { margin: 0 0 4px; font-size: 16px; line-height: 24px; }
.transfer-page .section-heading p { white-space: normal; }
.transfer-page .transfer-grid { min-width: 0; align-items: start; gap: 14px; }
.transfer-grid :deep(.el-card) { min-width: 0; border: 1px solid var(--erp-glass-border); border-radius: var(--erp-glass-radius); background: var(--erp-glass-surface); box-shadow: var(--erp-glass-shadow); backdrop-filter: var(--erp-glass-backdrop); }
.transfer-grid :deep(.el-card__header) { padding: 14px 16px; border-bottom: 1px solid var(--erp-color-border); font-size: 16px; }
.transfer-grid :deep(.el-card__body) { padding: 16px; }
.transfer-grid :deep(.el-form) { margin-top: 14px; }
.transfer-grid :deep(.el-form-item__label) { font-size: 12px; line-height: 20px; }
.transfer-grid :deep(.el-alert), .transfer-grid :deep(.el-timeline) { margin-bottom: 14px; }
.transfer-grid :deep(.el-timeline) { padding-left: 12px; }
.transfer-grid :deep(.el-descriptions__cell) { font-size: 13px; overflow-wrap: anywhere; }

.customer-detail-page--compact-controls :deep(.el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: var(--erp-radius-control) !important;
}

.customer-detail-page--compact-controls :deep(.el-input__wrapper),
.customer-detail-page--compact-controls :deep(.el-select__wrapper),
.customer-detail-page--compact-controls :deep(.el-date-editor.el-input__wrapper),
.customer-detail-page--compact-controls :deep(.el-input-number) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: var(--erp-radius-control) !important;
}

.customer-detail-page--compact-controls :deep(.el-pagination .el-select__wrapper),
.customer-detail-page--compact-controls :deep(.el-pagination .el-input__wrapper) {
  height: 28px !important;
  min-height: 28px !important;
}

.customer-detail-page--contacts :deep(.contact-page--v2) {
  padding-top: 14px;
}

.customer-detail-page--contacts :deep(.contact-page--v2 .contact-heading) {
  height: 46px;
  margin-top: 8px;
}

.customer-detail-page--contacts :deep(.contact-page--v2 .filter-card) {
  height: 32px;
  gap: 10px;
  margin-top: 6px;
}

.customer-detail-page--contacts :deep(.contact-page--v2 .contact-toolbar) {
  height: 32px;
  margin-top: 10px;
}

.customer-detail-page--contacts :deep(.contact-page--v2 .batch-actions),
.customer-detail-page--contacts :deep(.contact-page--v2 .view-actions) {
  gap: 10px;
}

.customer-detail-page--contacts :deep(.contact-page--v2 .table-card) {
  margin-top: 8px;
}

.customer-detail-page :deep(.customer-detail-list-shell__metrics),
.customer-detail-page--complaints :deep(.complaint-page.embedded .metric-strip) {
  display: none;
}

:global(.customer-detail-dialog) {
  --el-color-primary: #{token.$crm-primary};
}

:global(.customer-detail-dialog .el-button),
:global(.customer-detail-message-box .el-button),
:global(.customer-detail-drawer .el-button),
:global(body:has(.customer-detail-page--compact-controls) .el-dialog .el-button),
:global(body:has(.customer-detail-page--compact-controls) .el-message-box .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: var(--erp-radius-control) !important;
}

:global(.customer-detail-dialog .el-form-item),
:global(.customer-detail-drawer .el-form-item) {
  margin-bottom: 12px;
}
@media (max-width: 1200px) { .metric-grid { grid-template-columns: repeat(3, 1fr); } .overview-grid, .transfer-grid { grid-template-columns: 1fr; } .form-grid.four { grid-template-columns: repeat(2, 1fr); } .edit-page { width: calc(100% - 32px); } .edit-workspace { grid-template-columns: 168px minmax(0, 1fr); } .edit-section-nav { padding-inline: 10px; } .edit-section-nav > button { width: 146px; } .figma-form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .edit-form-card.profile-card, .edit-form-card.attributes-card { height: 300px; } .edit-form-card.address-card { min-height: 300px; } .edit-form-card.ownership-card { height: 240px; } }
@media (max-width: 1500px) { .customer-task-header-button { display: none; } }
@media (max-width: 800px) { .customer-header, .section-heading, .sticky-actions, .related-module-heading { align-items: stretch; flex-direction: column; } .customer-identity { flex-wrap: wrap; } .timeline-layout { grid-template-columns: 1fr; } .timeline-filters { align-items: stretch; flex-direction: column; } .metric-grid, .form-grid.four, .form-grid.two { grid-template-columns: 1fr; } .detail-tabs { overflow-x: auto; } .related-module-page { padding: 12px; overflow: hidden; } .related-table-card { overflow-x: auto; } .related-table-card :deep(.el-table) { min-width: 900px; } .edit-page { width: calc(100% - 24px); margin-top: 12px; } .edit-title-row, .edit-title-row > div, .edit-action-bar { align-items: flex-start; flex-direction: column; } .edit-page-header { height: auto; margin-bottom: 12px; } .edit-title-row { height: auto; gap: 12px; } .edit-workspace { height: auto; display: block; } .edit-section-nav { display: none; } .edit-form { height: auto; overflow: visible; padding: 12px; } .figma-form-grid { grid-template-columns: 1fr; } .edit-form-card.profile-card, .edit-form-card.address-card, .edit-form-card.attributes-card, .edit-form-card.ownership-card { height: auto; } .edit-action-bar { height: auto; gap: 12px; padding: 12px; } .edit-action-bar > div { width: 100%; flex-wrap: wrap; } }
</style>
