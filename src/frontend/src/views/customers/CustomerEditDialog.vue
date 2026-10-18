<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  checkCustomerDuplicates,
  createCustomerEntity,
  createEntityAddress,
  fetchCustomer,
  fetchCustomerEntities,
  fetchCustomerEntity,
  fetchCustomerOptions,
  fetchEntityAddress,
  fetchEntityAddresses,
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
  CustomerDuplicateMatch,
  CustomerEntity,
  CustomerOptions,
} from '@/types/customer'

import {
  buildCustomerUpdatePayload,
  createEmptyCustomerForm,
  customerFormSnapshot,
  customerRequestError,
  formatCustomerDateTime,
  getDerivedCountryCode,
  getSecondaryRegions,
  mapCustomerToForm,
  validateCustomerEditForm,
  type CustomerFormErrors,
} from './customerForm'

const props = defineProps<{ modelValue: boolean; customerId: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  cancelled: []
  saved: [customerId: string, closeAfterSave: boolean]
}>()
const authStore = useAuthStore()
const customerId = computed(() => props.customerId)
const canEdit = computed(() => authStore.hasPermission('customers.change_customeraccount'))

const form = reactive(createEmptyCustomerForm())
const options = ref<CustomerOptions | null>(null)
const customer = ref<CustomerDetail | null>(null)
const customerEtag = ref('')
const entity = ref<CustomerEntity | null>(null)
const entityEtag = ref('')
const addresses = ref<CustomerAddress[]>([])
const activeAddressId = ref('')
const addressEtag = ref('')
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const fieldErrors = reactive<CustomerFormErrors>({})
const duplicateMatches = ref<CustomerDuplicateMatch[]>([])
const checkingDuplicate = ref(false)
const workspace = ref<HTMLElement | null>(null)
const editSections = [
  { id: 'profile', label: '主体资料' },
  { id: 'address', label: '地址属性' },
  { id: 'attributes', label: '客户属性' },
  { id: 'ownership', label: '归属与标签' },
] as const
type EditSection = typeof editSections[number]['id']
const activeSection = ref<EditSection>('profile')
let scrollBody: HTMLElement | null = null
const duplicateError = ref('')
const addressLoading = ref(false)
const changeReason = ref('客户资料编辑')
const initialSnapshot = ref('')
const initialEntityAddressSnapshot = ref('')
const initialGradeId = ref('')
const initialSourceId = ref('')
const initialTypeIds = ref<string[]>([])
const initialTagIds = ref<string[]>([])
let duplicateTimer: ReturnType<typeof setTimeout> | undefined
let loadSequence = 0
let duplicateSequence = 0
let addressSequence = 0
let pendingClose: Promise<boolean> | null = null

const secondaryRegions = computed(() => getSecondaryRegions(options.value, form.primaryRegionId))
const derivedCountryCode = computed(() => getDerivedCountryCode(options.value, form.secondaryRegionId) || form.countryCode)
const primaryOwner = computed(() => customer.value?.primary_owner?.display_name || '未分配')
const currentSnapshot = computed(() => customerFormSnapshot(form))
const isDirty = computed(() => Boolean(initialSnapshot.value && currentSnapshot.value !== initialSnapshot.value))
function sortedValues(values: string[]) {
  return [...values].sort().join('|')
}

function updateActiveSection() {
  if (!scrollBody || !workspace.value) return
  // 拉高窗口后末分组未必能滚到顶部；到达底部时仍保持末分组选中。
  if (scrollBody.scrollHeight > scrollBody.clientHeight && scrollBody.scrollHeight - scrollBody.clientHeight - scrollBody.scrollTop <= 1) {
    activeSection.value = 'ownership'
    return
  }
  const boundary = scrollBody.getBoundingClientRect().top + 24
  let current: EditSection = 'profile'
  for (const section of editSections) {
    const element = workspace.value.querySelector<HTMLElement>(`#edit-section-${section.id}`)
    if (element && element.getBoundingClientRect().top <= boundary) current = section.id
  }
  activeSection.value = current
}

function goToSection(id: EditSection) {
  const section = workspace.value?.querySelector<HTMLElement>(`#edit-section-${id}`)
  if (!scrollBody || !section) return
  activeSection.value = id
  scrollBody.scrollTo({ top: scrollBody.scrollTop + section.getBoundingClientRect().top - scrollBody.getBoundingClientRect().top - 8, behavior: 'auto' })
}

watch(workspace, (element) => {
  scrollBody?.removeEventListener('scroll', updateActiveSection)
  scrollBody = element?.closest<HTMLElement>('.app-window-dialog__body') || null
  activeSection.value = 'profile'
  if (scrollBody) {
    scrollBody.scrollTop = 0
    scrollBody.addEventListener('scroll', updateActiveSection, { passive: true })
  }
}, { flush: 'post' })

function clearFieldErrors() {
  for (const key of Object.keys(fieldErrors) as Array<keyof CustomerFormErrors>) delete fieldErrors[key]
}

async function focusFirstError(errors: CustomerFormErrors) {
  await nextTick()
  const firstKey = Object.keys(errors)[0]
  if (!firstKey) return
  const target = workspace.value?.querySelector<HTMLElement>(`[data-field="${firstKey}"] input, [data-field="${firstKey}"] textarea`)
  target?.focus()
}

function rememberInitialState() {
  initialSnapshot.value = customerFormSnapshot(form)
  initialEntityAddressSnapshot.value = entityAddressSnapshot()
  initialGradeId.value = form.gradeId
  initialSourceId.value = form.sourceId
  initialTypeIds.value = [...form.typeIds]
  initialTagIds.value = [...form.tagIds]
}

function entityAddressSnapshot() {
  return JSON.stringify({
    entityLegalName: form.entityLegalName.trim(),
    entityEnglishName: form.entityEnglishName.trim(),
    registrationNumber: form.registrationNumber.trim(),
    taxIdentifier: form.taxIdentifier.trim(),
    activeAddressId: activeAddressId.value,
    addressLabel: form.addressLabel.trim(),
    addressCountryCode: form.addressCountryCode,
    stateProvince: form.stateProvince.trim(),
    city: form.city.trim(),
    postalCode: form.postalCode.trim(),
    addressLine1: form.addressLine1.trim(),
    addressLine2: form.addressLine2.trim(),
    recipientName: form.recipientName.trim(),
    recipientPhone: form.recipientPhone.trim(),
  })
}

function ensureHistoricalOptions(optionData: CustomerOptions, item: CustomerDetail): CustomerOptions {
  const addHistorical = (list: CustomerOptions['customer_grades'], current: { item_code: string; display_name: string } | null) => {
    if (!current || list.some((option) => option.item_code === current.item_code)) return list
    return [...list, { id: current.item_code, item_code: current.item_code, display_name: `${current.display_name}（历史值）`, description: '', disabled: false }]
  }
  return {
    ...optionData,
    customer_grades: addHistorical(optionData.customer_grades, item.customer_grade),
    customer_sources: addHistorical(optionData.customer_sources, item.latest_source),
    customer_types: item.customer_types.reduce((list, current) => addHistorical(list, current), optionData.customer_types),
  }
}

function isCurrentLoad(sequence: number, id: string) {
  return sequence === loadSequence && props.modelValue && customerId.value === id
}

async function loadPage(): Promise<boolean> {
  const sequence = ++loadSequence
  const id = customerId.value
  if (!props.modelValue) return false
  if (!id) {
    loadError.value = '客户编号缺失，无法打开编辑页。'
    loading.value = false
    return false
  }
  loading.value = true
  loadError.value = ''
  stopDuplicateCheck()
  try {
    const [versioned, optionData] = await Promise.all([fetchCustomer(id), fetchCustomerOptions()])
    if (!isCurrentLoad(sequence, id)) return false
    const customerEntities = await fetchCustomerEntities(id)
    if (!isCurrentLoad(sequence, id)) return false
    let loadedEntity: CustomerEntity | null = customerEntities[0] || null
    let loadedEntityEtag = ''
    let loadedAddresses: CustomerAddress[] = []
    let loadedAddress: CustomerAddress | undefined
    let loadedAddressEtag = ''
    if (loadedEntity) {
      const [versionedEntity, entityAddresses] = await Promise.all([
        fetchCustomerEntity(loadedEntity.id), fetchEntityAddresses(loadedEntity.id),
      ])
      if (!isCurrentLoad(sequence, id)) return false
      loadedEntity = versionedEntity.data
      loadedEntityEtag = versionedEntity.etag || ''
      loadedAddresses = entityAddresses
      if (entityAddresses[0]) {
        const versionedAddress = await fetchEntityAddress(entityAddresses[0].id)
        if (!isCurrentLoad(sequence, id)) return false
        loadedAddress = versionedAddress.data
        loadedAddressEtag = versionedAddress.etag || ''
      }
    }
    customer.value = versioned.data
    customerEtag.value = versioned.etag || ''
    options.value = ensureHistoricalOptions(optionData, versioned.data)
    entity.value = loadedEntity
    entityEtag.value = loadedEntityEtag
    addresses.value = loadedAddresses
    activeAddressId.value = loadedAddress?.id || ''
    addressEtag.value = loadedAddressEtag
    Object.assign(form, mapCustomerToForm(versioned.data, options.value, loadedEntity || undefined, loadedAddress))
    rememberInitialState()
    return true
  } catch (error) {
    if (isCurrentLoad(sequence, id)) loadError.value = customerRequestError(error, '客户资料加载失败。')
    return false
  } finally {
    if (isCurrentLoad(sequence, id)) loading.value = false
  }
}

async function confirmAddressChange(message: string, title: string): Promise<boolean> {
  if (!isDirty.value) return true
  try {
    await ElMessageBox.confirm(message, title, { type: 'warning', customClass: 'customer-form-message-box' })
    return true
  } catch (error) {
    if (error === 'cancel' || error === 'close') return false
    throw error
  }
}

async function selectAddress(addressId: string) {
  if (saving.value || addressLoading.value || addressId === activeAddressId.value) return
  const sequence = ++addressSequence
  const id = customerId.value
  if (!await confirmAddressChange('切换地址会放弃当前未保存的修改，是否继续？', '切换地址')) return
  const address = addresses.value.find(item => item.id === addressId)
  if (!props.modelValue || sequence !== addressSequence || customerId.value !== id || !address || !customer.value || !options.value) return
  addressLoading.value = true
  try {
    const versionedAddress = await fetchEntityAddress(address.id)
    if (!props.modelValue || sequence !== addressSequence || customerId.value !== id) return
    activeAddressId.value = address.id
    addressEtag.value = versionedAddress.etag || ''
    Object.assign(form, mapCustomerToForm(customer.value, options.value, entity.value || undefined, versionedAddress.data))
    rememberInitialState()
  } catch (error) {
    if (props.modelValue && sequence === addressSequence && customerId.value === id) ElMessage.error(customerRequestError(error, '地址资料加载失败。'))
  } finally {
    if (sequence === addressSequence) addressLoading.value = false
  }
}

async function startNewAddress() {
  if (saving.value || addressLoading.value) return
  const sequence = ++addressSequence
  const id = customerId.value
  if (!await confirmAddressChange('新增地址会放弃当前未保存的修改，是否继续？', '新增地址')) return
  if (!props.modelValue || sequence !== addressSequence || customerId.value !== id || !customer.value || !options.value) return
  activeAddressId.value = ''
  addressEtag.value = ''
  Object.assign(form, mapCustomerToForm(customer.value, options.value, entity.value || undefined))
  form.addressCountryCode = customer.value.primary_country_code || derivedCountryCode.value
  rememberInitialState()
}

function stopDuplicateCheck() {
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = undefined
  duplicateSequence += 1
  checkingDuplicate.value = false
}
function scheduleDuplicateCheck() {
  stopDuplicateCheck()
  if (!props.modelValue || !customer.value) return
  duplicateTimer = setTimeout(async () => {
    const sequence = ++duplicateSequence
    const id = customerId.value
    duplicateError.value = ''
    if (form.accountName.trim().length < 2 && form.website.trim().length < 4) {
      duplicateMatches.value = []
      return
    }
    checkingDuplicate.value = true
    try {
      const query = form.accountName.trim()
        ? { name: form.accountName.trim(), website: form.website.trim() || undefined }
        : { website: form.website.trim() }
      const result = await checkCustomerDuplicates({ ...query, country_code: derivedCountryCode.value || undefined, exclude_customer_id: id })
      if (props.modelValue && sequence === duplicateSequence && id === customerId.value) duplicateMatches.value = result.matches
    } catch (error) {
      if (props.modelValue && sequence === duplicateSequence && id === customerId.value) {
        duplicateMatches.value = []
        duplicateError.value = customerRequestError(error, '重复客户检查失败，请稍后重试。')
      }
    } finally {
      if (sequence === duplicateSequence) checkingDuplicate.value = false
    }
  }, 400)
}

function hasEntityOrAddressData() {
  return [
    form.entityLegalName,
    form.entityEnglishName,
    form.registrationNumber,
    form.taxIdentifier,
    form.addressLine1,
    form.addressLine2,
    form.stateProvince,
    form.city,
    form.postalCode,
    form.recipientName,
    form.recipientPhone,
  ].some((value) => value.trim())
}

async function saveEntityAndAddress(id: string, sequence: number) {
  if (!customer.value || !hasEntityOrAddressData() || entityAddressSnapshot() === initialEntityAddressSnapshot.value) return
  const registrationCountry = form.addressCountryCode || derivedCountryCode.value
  const entityPayload = {
    entity_code: entity.value?.entity_code || `${customer.value.account_code}-LEGAL`,
    entity_type: entity.value?.entity_type || 'COMPANY',
    legal_name: form.entityLegalName.trim(),
    english_legal_name: form.entityEnglishName.trim(),
    registration_country_code: registrationCountry,
    registration_number: form.registrationNumber.trim(),
    tax_country_code: registrationCountry,
    tax_identifier: form.taxIdentifier.trim(),
    notes: entity.value?.notes || '客户资料页维护',
  }

  let savedEntity: CustomerEntity
  if (!entity.value) savedEntity = await createCustomerEntity(id, entityPayload)
  else {
    if (!entityEtag.value) throw new Error('缺少主体版本信息，请刷新页面后重试。')
    savedEntity = await updateCustomerEntity(entity.value.id, entityPayload, entityEtag.value)
  }
  if (!isCurrentLoad(sequence, id)) return
  entity.value = savedEntity

  if (!form.addressLine1.trim()) return
  const existingAddress = addresses.value.find((item) => item.id === activeAddressId.value)
  const addressPayload = {
    address_code: existingAddress?.address_code || `ADDR_${Date.now().toString(36).toUpperCase()}`,
    label: form.addressLabel.trim() || existingAddress?.label || '办公地址',
    country_code: form.addressCountryCode,
    state_province: form.stateProvince.trim(),
    city: form.city.trim(),
    postal_code: form.postalCode.trim(),
    address_line1: form.addressLine1.trim(),
    address_line2: form.addressLine2.trim(),
    recipient_name: form.recipientName.trim(),
    recipient_phone: form.recipientPhone.trim(),
    is_verified: existingAddress?.is_verified || false,
  }
  if (!existingAddress) await createEntityAddress(entity.value.id, addressPayload)
  else {
    if (!addressEtag.value) throw new Error('缺少地址版本信息，请重新选择地址。')
    await updateEntityAddress(existingAddress.id, addressPayload, addressEtag.value)
  }
}

async function saveProfile() {
  if (saving.value || loading.value || addressLoading.value || !props.modelValue || !canEdit.value || !customer.value || !options.value) return
  clearFieldErrors()
  const errors = validateCustomerEditForm(form)
  Object.assign(fieldErrors, errors)
  if (Object.keys(errors).length) {
    ElMessage.warning('请检查标记的客户资料。')
    await focusFirstError(errors)
    return
  }
  if (!changeReason.value.trim()) {
    ElMessage.warning('请填写变更说明。')
    await nextTick()
    workspace.value?.querySelector<HTMLElement>('[data-field="changeReason"] input')?.focus()
    return
  }
  if (!customerEtag.value) {
    ElMessage.error('缺少客户版本信息，请刷新页面后重试。')
    return
  }

  saving.value = true
  const id = customerId.value
  const sequence = loadSequence
  let wroteData = false
  try {
    await updateCustomer(id, buildCustomerUpdatePayload(form, options.value), customerEtag.value)
    wroteData = true
    if (!isCurrentLoad(sequence, id)) return
    if (form.gradeId !== initialGradeId.value) {
      await setCustomerGrade(id, { grade_item_id: form.gradeId, reason: changeReason.value.trim() })
    }
    if (!isCurrentLoad(sequence, id)) return
    if (form.sourceId !== initialSourceId.value) {
      await setCustomerSource(id, { source_item_id: form.sourceId, notes: changeReason.value.trim() })
    }
    if (!isCurrentLoad(sequence, id)) return
    if (sortedValues(form.typeIds) !== sortedValues(initialTypeIds.value) || sortedValues(form.tagIds) !== sortedValues(initialTagIds.value)) {
      await setCustomerClassification(id, {
        customer_type_item_ids: [...form.typeIds],
        customer_tag_ids: [...form.tagIds],
        reason: changeReason.value.trim(),
      })
    }
    if (!isCurrentLoad(sequence, id)) return
    await saveEntityAndAddress(id, sequence)
    if (!isCurrentLoad(sequence, id)) return
    if (!await loadPage()) return
    saving.value = false
    ElMessage.success('客户资料已保存。')
    emit('saved', id, false)
  } catch (error) {
    if (!isCurrentLoad(sequence, id)) return
    ElMessage.error(wroteData
      ? `${customerRequestError(error, '后续资料保存失败。')} 部分资料可能已保存，页面将重新加载。`
      : customerRequestError(error, '客户资料保存失败。'))
    if (wroteData) await loadPage()
  } finally {
    saving.value = false
  }
}

async function confirmDiscard(): Promise<boolean> {
  if (!props.modelValue) return true
  if (saving.value) return false
  if (!isDirty.value) return true
  if (pendingClose) return pendingClose
  const sequence = loadSequence
  const id = customerId.value
  pendingClose = (async () => {
    try {
      await ElMessageBox.confirm('当前修改尚未保存，确定关闭编辑？', '放弃修改', {
        type: 'warning', customClass: 'customer-form-message-box', confirmButtonText: '放弃修改', cancelButtonText: '继续编辑',
      })
      if (!isCurrentLoad(sequence, id)) return false
      initialSnapshot.value = currentSnapshot.value
      return true
    } catch (error) {
      if (error === 'cancel' || error === 'close') return false
      throw error
    } finally { pendingClose = null }
  })()
  return pendingClose
}
async function beforeClose(done: () => void) { if (await confirmDiscard()) done() }
function handleWindowVisibility(value: boolean) {
  emit('update:modelValue', value)
  if (!value) emit('cancelled')
}
function cancelEdit() { void beforeClose(() => handleWindowVisibility(false)) }
function beforeUnload(event: BeforeUnloadEvent) {
  if (props.modelValue && (isDirty.value || saving.value)) { event.preventDefault(); event.returnValue = '' }
}

function addressSummary(address: CustomerAddress) {
  return [address.label || '地址', address.city || address.country_code].filter(Boolean).join(' · ')
}

watch(() => [props.modelValue, props.customerId] as const, ([visible]) => {
  loadSequence += 1
  addressSequence += 1
  addressLoading.value = false
  stopDuplicateCheck()
  if (!visible) return
  customer.value = null
  customerEtag.value = ''
  options.value = null
  entity.value = null
  entityEtag.value = ''
  addresses.value = []
  activeAddressId.value = ''
  addressEtag.value = ''
  initialSnapshot.value = ''
  duplicateMatches.value = []
  duplicateError.value = ''
  changeReason.value = '客户资料编辑'
  clearFieldErrors()
  if (canEdit.value) void loadPage()
  else loading.value = false
}, { immediate: true })
watch(() => [form.accountName, form.website, form.secondaryRegionId], scheduleDuplicateCheck)
watch(() => form.primaryRegionId, (current, previous) => {
  if (!loading.value && previous && current !== previous) form.secondaryRegionId = ''
}, { flush: 'sync' })
watch(form, clearFieldErrors, { deep: true })
onBeforeRouteLeave(confirmDiscard)
onBeforeRouteUpdate(confirmDiscard)
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => {
  scrollBody?.removeEventListener('scroll', updateActiveSection)
  loadSequence += 1
  addressSequence += 1
  stopDuplicateCheck()
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <AppWindowDialog :model-value="modelValue" class="customer-edit-dialog" title="编辑客户" :width="1040" :height="780"
    :minimizable="false" :close-on-click-modal="false" :before-close="beforeClose" destroy-on-close @update:model-value="handleWindowVisibility">
    <section v-if="!canEdit" class="page-state"><ElResult icon="warning" title="无权编辑客户" sub-title="当前账号缺少编辑客户权限，请联系管理员。" /></section>
    <section v-else-if="loading" class="page-state" aria-busy="true"><ElSkeleton :rows="12" animated /></section>
    <section v-else-if="loadError" class="page-state"><ElResult icon="error" title="无法打开客户编辑" :sub-title="loadError"><template #extra><ElButton class="erp-button-motion" type="primary" @click="loadPage">重新加载</ElButton></template></ElResult></section>
    <section v-else-if="customer && options" ref="workspace" class="edit-workspace" data-customer-edit-page>
      <header class="customer-summary"><strong>{{ customer.account_code }} · {{ customer.account_name }}</strong><span>最后保存：{{ formatCustomerDateTime(customer.updated_at) }}</span></header>
      <div class="edit-layout">
        <nav class="edit-section-nav" aria-label="客户编辑分区">
          <button v-for="section in editSections" :key="section.id" type="button"
            :class="{ 'is-active': activeSection === section.id }"
            :aria-current="activeSection === section.id ? 'location' : undefined"
            :aria-controls="`edit-section-${section.id}`" @click="goToSection(section.id)">{{ section.label }}</button>
        </nav>
        <ElForm label-position="top" class="edit-form" :model="form" :disabled="saving || addressLoading" @submit.prevent>
          <section id="edit-section-profile" class="form-card">
            <header><div><h2>主体资料</h2><p><b>*</b> 为必填</p></div><span>{{ checkingDuplicate ? '正在实时查重' : '自动查重' }}</span></header>
            <div class="edit-grid">
              <ElFormItem label="客户名称" required :error="fieldErrors.accountName" data-field="accountName"><ElInput v-model="form.accountName" maxlength="250" /></ElFormItem>
              <ElFormItem label="客户简称" data-field="shortName"><ElInput v-model="form.shortName" maxlength="100" placeholder="可选" /></ElFormItem>
              <ElFormItem label="法定主体名称" :error="fieldErrors.entityLegalName" data-field="entityLegalName"><ElInput v-model="form.entityLegalName" maxlength="250" placeholder="可选" /></ElFormItem>
              <ElFormItem label="网站 / 域名" :error="fieldErrors.website" data-field="website"><ElInput v-model="form.website" maxlength="500" placeholder="例如 example.com" /></ElFormItem>
              <ElFormItem label="一级地区" required :error="fieldErrors.primaryRegionId" data-field="primaryRegionId"><ElSelect v-model="form.primaryRegionId" filterable><ElOption v-for="item in options.primary_regions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem>
              <ElFormItem label="二级地区"><ElSelect v-model="form.secondaryRegionId" filterable clearable :disabled="!form.primaryRegionId"><ElOption v-for="item in secondaryRegions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem>
              <ElFormItem label="默认语言"><ElInput model-value="跟随系统语言" disabled title="当前客户 API 暂无默认语言字段" /></ElFormItem>
              <ElFormItem label="税号 / 注册号"><ElInput v-model="form.taxIdentifier" maxlength="128" placeholder="可选" /></ElFormItem>
            </div>
          </section>

          <section id="edit-section-address" class="form-card address-card">
            <header>
              <div><h2>地址属性</h2><p>已保存 {{ addresses.length }} 条</p></div>
              <div class="address-header-actions">
                <div v-if="addresses.length" class="address-tabs">
                  <button v-for="item in addresses" :key="item.id" :class="{ 'is-active': activeAddressId === item.id }" :disabled="saving || addressLoading" @click.prevent="selectAddress(item.id)">{{ addressSummary(item) }}</button>
                  <span v-if="!activeAddressId">新增地址</span>
                </div>
                <ElButton class="erp-button-motion" @click="startNewAddress">＋ 新增地址</ElButton>
              </div>
            </header>
            <div class="edit-grid">
              <ElFormItem label="地址类型" required><ElSelect v-model="form.addressLabel"><ElOption label="办公地址" value="办公地址" /><ElOption label="收货地址" value="收货地址" /><ElOption label="账单地址" value="账单地址" /></ElSelect></ElFormItem>
              <ElFormItem label="国家 / 地区" :error="fieldErrors.addressCountryCode" data-field="addressCountryCode"><ElSelect v-model="form.addressCountryCode" filterable clearable><ElOption v-for="item in options.country_options" :key="item.id" :label="item.display_name" :value="item.item_code" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="省 / 州"><ElInput v-model="form.stateProvince" maxlength="100" placeholder="可选" /></ElFormItem>
              <ElFormItem label="城市"><ElInput v-model="form.city" maxlength="100" placeholder="可选" /></ElFormItem>
              <ElFormItem label="详细地址" :error="fieldErrors.addressLine1" data-field="addressLine1"><ElInput v-model="form.addressLine1" maxlength="500" placeholder="街道、门牌号等" /></ElFormItem>
              <ElFormItem label="邮政编码"><ElInput v-model="form.postalCode" maxlength="32" placeholder="可选" /></ElFormItem>
              <ElFormItem label="收件人"><ElInput v-model="form.recipientName" maxlength="150" placeholder="可选" /></ElFormItem>
              <ElFormItem label="联系电话"><ElInput v-model="form.recipientPhone" maxlength="64" placeholder="可选" /></ElFormItem>
            </div>
            <div class="address-version"><span>地址版本：{{ activeAddressId ? '已保存' : '新地址' }}</span><b>{{ activeAddressId ? '未验证' : '待保存' }}</b></div>
          </section>

          <section id="edit-section-attributes" class="form-card attributes-card">
            <header><div><h2>客户属性</h2><p>变更将保留画像历史</p></div></header>
            <div class="edit-grid">
              <ElFormItem label="客户类型" required :error="fieldErrors.typeIds" data-field="typeIds"><ElSelect v-model="form.typeIds" multiple collapse-tags><ElOption v-for="item in options.customer_types" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="客户来源" required :error="fieldErrors.sourceId" data-field="sourceId"><ElSelect v-model="form.sourceId"><ElOption v-for="item in options.customer_sources" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="客户等级" required :error="fieldErrors.gradeId" data-field="gradeId"><ElSelect v-model="form.gradeId"><ElOption v-for="item in options.customer_grades" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="生命周期"><ElSelect v-model="form.lifecycleStage"><ElOption v-for="item in options.lifecycle_stages" :key="item.item_code" :label="item.display_name" :value="item.item_code" /></ElSelect></ElFormItem>
            </div>
            <div class="attribute-summary">所属行业：{{ options.industries.find((item) => item.id === form.industryId)?.display_name || '未设置' }}　 感兴趣产品：{{ form.interestedProductIds.length ? `${form.interestedProductIds.length} 项` : '未设置' }}　 负责人：{{ primaryOwner }}（只读）</div>
          </section>

          <section id="edit-section-ownership" class="form-card">
            <header><div><h2>归属与标签</h2><p>扩展字段与审计说明</p></div></header>
            <div class="edit-grid">
              <ElFormItem label="英文名称" data-field="englishName"><ElInput v-model="form.englishName" maxlength="250" placeholder="可选" /></ElFormItem>
              <ElFormItem label="法定主体英文名"><ElInput v-model="form.entityEnglishName" maxlength="250" placeholder="可选" /></ElFormItem>
              <ElFormItem label="注册号"><ElInput v-model="form.registrationNumber" maxlength="128" placeholder="可选" /></ElFormItem>
              <ElFormItem label="地址补充"><ElInput v-model="form.addressLine2" maxlength="500" placeholder="楼层、房间等，可选" /></ElFormItem>
              <ElFormItem label="行业"><ElSelect v-model="form.industryId" filterable clearable><ElOption v-for="item in options.industries" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="感兴趣产品"><ElSelect v-model="form.interestedProductIds" multiple filterable collapse-tags clearable><ElOption v-for="item in options.interested_products" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="客户标签"><ElSelect v-model="form.tagIds" multiple filterable collapse-tags clearable><ElOption v-for="item in options.customer_tags" :key="item.id" :label="item.tag_name" :value="item.id" /></ElSelect></ElFormItem>
              <ElFormItem label="当前负责人"><ElInput :model-value="primaryOwner" disabled /></ElFormItem>
              <ElFormItem class="span-2" label="询盘关键词"><ElInput v-model="form.inquiryKeywords" maxlength="500" placeholder="多个关键词可用逗号分隔" /></ElFormItem>
              <ElFormItem label="来源系统" :error="fieldErrors.sourceSystem" data-field="sourceSystem"><ElInput v-model="form.sourceSystem" maxlength="64" placeholder="可选" /></ElFormItem>
              <ElFormItem label="外部编号" :error="fieldErrors.externalId" data-field="externalId"><ElInput v-model="form.externalId" maxlength="128" placeholder="成对填写" /></ElFormItem>
              <ElFormItem class="span-2" label="变更说明" required data-field="changeReason"><ElInput v-model="changeReason" maxlength="200" placeholder="用于等级、来源与分类的审计记录" /></ElFormItem>
              <ElFormItem class="span-2" label="备注"><ElInput v-model="form.notes" type="textarea" :rows="3" maxlength="2000" show-word-limit /></ElFormItem>
            </div>
          </section>

          <section id="edit-section-duplicate" class="form-card duplicate-section">
            <header><div><h2>重复检查</h2><p>根据当前客户名称、网站和国家实时检查，不包含本客户</p></div><span>{{ checkingDuplicate ? '检查中' : `${duplicateMatches.length} 条匹配` }}</span></header>
            <ElAlert v-if="duplicateError" type="error" :closable="false" :title="duplicateError" />
            <div v-else-if="duplicateMatches.length" class="duplicate-list">
              <article v-for="match in duplicateMatches" :key="match.customer_id">
                <div><strong>{{ match.account_name }}</strong><span>{{ match.account_code }} · {{ match.primary_country_code || '国家未知' }}</span></div>
                <b>{{ match.match_score }}%</b>
              </article>
            </div>
            <div v-else class="duplicate-empty">{{ checkingDuplicate ? '正在检查真实客户数据…' : '未发现其他匹配客户。' }}</div>
          </section>
        </ElForm>
      </div>
    </section>
    <template #footer>
      <div class="edit-save-actions">
      <span v-if="customer && !loading && !loadError" class="save-state">{{ isDirty ? '有未保存的修改' : '当前资料已同步' }}</span>
      <ElButton class="erp-button-motion" :disabled="saving" @click="cancelEdit">取消</ElButton>
      <ElButton class="erp-button-motion" type="primary" :loading="saving" :disabled="!canEdit || loading || Boolean(loadError) || addressLoading || !isDirty" @click="saveProfile">保存</ElButton>
      </div>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use './customer-form-shared' as shared;
.page-state { padding: 16px; }
.edit-workspace { min-width: 0; container-type: inline-size; color: token.$crm-text-primary; font-family: token.$crm-font-body; }
.customer-summary { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; font-size: 13px; }
.customer-summary span { color: token.$crm-text-muted; font-size: 11px; }
.edit-layout { display: grid; grid-template-columns: 136px minmax(0, 1fr); align-items: start; gap: 16px; }
.edit-section-nav { position: sticky; top: 0; display: grid; gap: 6px; }
.edit-section-nav button { min-height: 42px; padding: 10px 12px; border: 0; border-left: 3px solid transparent; border-radius: 0 8px 8px 0; color: token.$crm-text-secondary; background: transparent; font: 13px/20px token.$crm-font-body; text-align: left; cursor: pointer; }
.edit-section-nav button:hover { background: token.$crm-color-subtle; }
.edit-section-nav button.is-active { border-left-color: token.$crm-primary; color: token.$crm-primary; background: var(--erp-color-selected); font-weight: 600; }
.edit-section-nav button:focus-visible { outline: 2px solid token.$crm-primary; outline-offset: 2px; }
.edit-form { min-width: 0; @include shared.element-form-controls(32px, 12px, 13px, 4px); }
.form-card { margin-bottom: 12px; padding: 16px; scroll-margin-top: 8px; border: 1px solid token.$crm-border-default; border-radius: 8px; background: token.$crm-color-surface; }
.form-card > header { min-height: 38px; display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; border-bottom: 1px solid token.$crm-border-subtle; }
.form-card > header h2 { margin: 0; font-family: token.$crm-font-body; font-size: 16px; font-weight: 600; line-height: 24px; }
.form-card > header p { margin: 2px 0 0; color: token.$crm-text-muted; font-size: 11px; line-height: 18px; }
.form-card > header > span { padding: 2px 8px; border-radius: token.$crm-radius-pill; color: token.$crm-success; background: token.$crm-success-soft; font-size: 11px; line-height: 20px; }
.form-card > header p b { color: token.$crm-primary; }
.form-card > header :deep(.el-button) { height: 32px; padding: 0 12px; font-size: 11px; }
.edit-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 12px; }
.edit-grid :deep(.el-form-item) { min-width: 0; min-height: 56px; }
.span-2 { grid-column: span 2; }
.edit-grid :deep(.el-textarea__inner) { min-height: 74px; padding: 8px 10px; border: 0; border-radius: token.$crm-radius-3; box-shadow: 0 0 0 1px token.$crm-border-default inset; resize: vertical; }
.address-header-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; min-width: 0; }
.address-tabs { max-width: 380px; display: flex; align-items: center; gap: 6px; overflow-x: auto; }
.address-tabs button, .address-tabs > span { height: 28px; flex: none; padding: 0 10px; border: 1px solid token.$crm-border-default; border-radius: token.$crm-radius-pill; color: token.$crm-text-secondary; background: token.$crm-color-surface; font: 11px/26px token.$crm-font-body; cursor: pointer; }
.address-tabs button.is-active, .address-tabs > span { border-color: token.$crm-primary; color: token.$crm-primary; background: var(--erp-color-selected); }
.address-version { height: 28px; display: flex; align-items: center; justify-content: space-between; margin-top: 8px; padding: 0 10px; border-radius: token.$crm-radius-3; color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 10px; }
.address-version b { color: token.$crm-warning; font-weight: 500; }
.address-card { padding: 16px 20px; }
.address-card .address-version { height: 24px; margin-top: 6px; }
.attributes-card { padding: 16px 20px; }
.attributes-card > header { min-height: 32px; margin-bottom: 8px; }
.attribute-summary { min-height: 36px; display: flex; align-items: center; flex-wrap: wrap; margin-top: 8px; padding: 0 10px; border-radius: token.$crm-radius-3; color: token.$crm-text-secondary; background: token.$crm-success-soft; font-size: 10px; }
.duplicate-list { display: grid; gap: 8px; }
.duplicate-list article { height: 48px; display: flex; align-items: center; justify-content: space-between; padding: 0 12px; border: 1px solid token.$crm-warning-border; border-radius: token.$crm-radius-3; background: token.$crm-warning-soft; }
.duplicate-list article div { display: flex; flex-direction: column; }
.duplicate-list strong { font-size: 12px; line-height: 19px; }
.duplicate-list span { color: token.$crm-text-muted; font-size: 10px; line-height: 17px; }
.duplicate-list b { color: token.$crm-warning; font-size: 12px; }
.duplicate-empty { height: 52px; display: grid; place-items: center; color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 12px; }

.form-card:last-child { margin-bottom: 0; }
.edit-save-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.edit-save-actions :deep(.el-button) { margin: 0; }
.save-state { margin-right: auto; color: token.$crm-text-muted; font-size: 12px; }
@container (max-width: 640px) {
  .edit-layout { grid-template-columns: minmax(0, 1fr); }
  .edit-section-nav { position: static; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .edit-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .form-card > header { flex-wrap: wrap; gap: 8px; }
  .address-header-actions { justify-content: flex-start; }
}
@container (max-width: 400px) {
  .edit-grid { grid-template-columns: minmax(0, 1fr); }
  .span-2 { grid-column: auto; }
}
@media (max-width: 640px) {
  .save-state { flex-basis: 100%; }
}
</style>
