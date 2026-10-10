<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const customerId = computed(() => String(route.params.customerId || ''))
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
const activeSection = ref('profile')
const changeReason = ref('客户资料编辑')
const initialSnapshot = ref('')
const initialEntityAddressSnapshot = ref('')
const initialGradeId = ref('')
const initialSourceId = ref('')
const initialTypeIds = ref<string[]>([])
const initialTagIds = ref<string[]>([])
let duplicateTimer: ReturnType<typeof setTimeout> | undefined

const secondaryRegions = computed(() => getSecondaryRegions(options.value, form.primaryRegionId))
const derivedCountryCode = computed(() => getDerivedCountryCode(options.value, form.secondaryRegionId) || form.countryCode)
const selectedCountryName = computed(() => {
  const countryCode = form.addressCountryCode || derivedCountryCode.value
  return options.value?.country_options.find((item) => item.item_code === countryCode)?.display_name || countryCode || '未设置'
})
const primaryOwner = computed(() => customer.value?.primary_owner?.display_name || '未分配')
const currentSnapshot = computed(() => customerFormSnapshot(form))
const isDirty = computed(() => Boolean(initialSnapshot.value && currentSnapshot.value !== initialSnapshot.value))
const completeness = computed(() => {
  const fields = [
    form.accountName,
    form.primaryRegionId,
    form.sourceId,
    form.gradeId,
    form.typeIds.length ? 'yes' : '',
    form.website,
    form.entityLegalName,
    form.addressLine1,
  ]
  return Math.round(fields.filter(Boolean).length / fields.length * 100)
})
const lifecycleName = computed(() => options.value?.lifecycle_stages.find((item) => item.item_code === form.lifecycleStage)?.display_name || form.lifecycleStage)

function sortedValues(values: string[]) {
  return [...values].sort().join('|')
}

function clearFieldErrors() {
  for (const key of Object.keys(fieldErrors) as Array<keyof CustomerFormErrors>) delete fieldErrors[key]
}

async function focusFirstError(errors: CustomerFormErrors) {
  await nextTick()
  const firstKey = Object.keys(errors)[0]
  if (!firstKey) return
  const target = document.querySelector<HTMLElement>(`[data-field="${firstKey}"] input, [data-field="${firstKey}"] textarea`)
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

async function loadRelatedData(item: CustomerDetail) {
  const customerEntities = await fetchCustomerEntities(customerId.value)
  entity.value = customerEntities[0] || null
  entityEtag.value = ''
  addresses.value = []
  activeAddressId.value = ''
  addressEtag.value = ''
  if (!entity.value) return

  const [versionedEntity, entityAddresses] = await Promise.all([
    fetchCustomerEntity(entity.value.id),
    fetchEntityAddresses(entity.value.id),
  ])
  entity.value = versionedEntity.data
  entityEtag.value = versionedEntity.etag || ''
  addresses.value = entityAddresses
  const firstAddress = entityAddresses[0]
  if (!firstAddress) return
  activeAddressId.value = firstAddress.id
  const versionedAddress = await fetchEntityAddress(firstAddress.id)
  addressEtag.value = versionedAddress.etag || ''
  Object.assign(form, mapCustomerToForm(item, options.value!, entity.value, versionedAddress.data))
}

async function loadPage() {
  if (!customerId.value) {
    loadError.value = '客户编号缺失，无法打开编辑页。'
    loading.value = false
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    const [versioned, optionData] = await Promise.all([
      fetchCustomer(customerId.value),
      fetchCustomerOptions(),
    ])
    customer.value = versioned.data
    customerEtag.value = versioned.etag || ''
    options.value = ensureHistoricalOptions(optionData, versioned.data)
    Object.assign(form, mapCustomerToForm(versioned.data, options.value))
    await loadRelatedData(versioned.data)
    rememberInitialState()
  } catch (error) {
    loadError.value = customerRequestError(error, '客户资料加载失败。')
  } finally {
    loading.value = false
  }
}

async function selectAddress(addressId: string) {
  if (saving.value || addressId === activeAddressId.value) return
  if (isDirty.value) {
    try {
      await ElMessageBox.confirm('切换地址会放弃当前未保存的修改，是否继续？', '切换地址', {
        type: 'warning',
        customClass: 'customer-form-message-box',
      })
    } catch {
      return
    }
  }
  const address = addresses.value.find((item) => item.id === addressId)
  if (!address || !customer.value || !options.value) return
  const versionedAddress = await fetchEntityAddress(address.id)
  activeAddressId.value = address.id
  addressEtag.value = versionedAddress.etag || ''
  Object.assign(form, mapCustomerToForm(customer.value, options.value, entity.value || undefined, versionedAddress.data))
  rememberInitialState()
}

async function startNewAddress() {
  if (isDirty.value) {
    try {
      await ElMessageBox.confirm('新增地址会放弃当前未保存的修改，是否继续？', '新增地址', {
        type: 'warning',
        customClass: 'customer-form-message-box',
      })
    } catch {
      return
    }
  }
  if (!customer.value || !options.value) return
  activeAddressId.value = ''
  addressEtag.value = ''
  Object.assign(form, mapCustomerToForm(customer.value, options.value, entity.value || undefined))
  form.addressCountryCode = customer.value.primary_country_code || derivedCountryCode.value
  rememberInitialState()
  activeSection.value = 'address'
}

function scheduleDuplicateCheck() {
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = setTimeout(async () => {
    if (!customer.value || (form.accountName.trim().length < 2 && form.website.trim().length < 4)) {
      duplicateMatches.value = []
      return
    }
    checkingDuplicate.value = true
    try {
      const query = form.accountName.trim()
        ? { name: form.accountName.trim(), website: form.website.trim() || undefined }
        : { website: form.website.trim() }
      duplicateMatches.value = (await checkCustomerDuplicates({
        ...query,
        country_code: derivedCountryCode.value || undefined,
        exclude_customer_id: customerId.value,
      })).matches
    } catch {
      duplicateMatches.value = []
    } finally {
      checkingDuplicate.value = false
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

async function saveEntityAndAddress() {
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

  if (!entity.value) entity.value = await createCustomerEntity(customerId.value, entityPayload)
  else {
    if (!entityEtag.value) throw new Error('缺少主体版本信息，请刷新页面后重试。')
    entity.value = await updateCustomerEntity(entity.value.id, entityPayload, entityEtag.value)
  }

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

async function saveProfile(returnAfterSave = false, asDraft = false) {
  if (saving.value || !canEdit.value || !customer.value || !options.value) return
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
    activeSection.value = 'ownership'
    return
  }
  if (!customerEtag.value) {
    ElMessage.error('缺少客户版本信息，请刷新页面后重试。')
    return
  }

  saving.value = true
  let wroteData = false
  try {
    await updateCustomer(customerId.value, buildCustomerUpdatePayload(form, options.value), customerEtag.value)
    wroteData = true
    if (form.gradeId !== initialGradeId.value) {
      await setCustomerGrade(customerId.value, { grade_item_id: form.gradeId, reason: changeReason.value.trim() })
    }
    if (form.sourceId !== initialSourceId.value) {
      await setCustomerSource(customerId.value, { source_item_id: form.sourceId, notes: changeReason.value.trim() })
    }
    if (sortedValues(form.typeIds) !== sortedValues(initialTypeIds.value) || sortedValues(form.tagIds) !== sortedValues(initialTagIds.value)) {
      await setCustomerClassification(customerId.value, {
        customer_type_item_ids: [...form.typeIds],
        customer_tag_ids: [...form.tagIds],
        reason: changeReason.value.trim(),
      })
    }
    await saveEntityAndAddress()
    ElMessage.success(asDraft ? '当前修改已保存；系统暂不区分草稿状态。' : '客户资料已保存。')
    await loadPage()
    if (returnAfterSave) await router.push({ name: 'customer-detail', params: { customerId: customerId.value } })
  } catch (error) {
    ElMessage.error(wroteData
      ? `${customerRequestError(error, '后续资料保存失败。')} 部分资料可能已保存，页面将重新加载。`
      : customerRequestError(error, '客户资料保存失败。'))
    if (wroteData) await loadPage()
  } finally {
    saving.value = false
  }
}

function scrollToSection(section: string) {
  activeSection.value = section
  document.getElementById(`edit-section-${section}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function cancelEdit() {
  if (isDirty.value) {
    try {
      await ElMessageBox.confirm('当前修改尚未保存，确定返回客户详情吗？', '放弃修改', {
        type: 'warning',
        customClass: 'customer-form-message-box',
      })
    } catch {
      return
    }
  }
  await router.push({ name: 'customer-detail', params: { customerId: customerId.value } })
}

async function returnToList() {
  if (isDirty.value) {
    try {
      await ElMessageBox.confirm('当前修改尚未保存，确定返回客户列表吗？', '放弃修改', {
        type: 'warning',
        customClass: 'customer-form-message-box',
      })
    } catch {
      return
    }
  }
  await router.push({ name: 'customers' })
}

function addressSummary(address: CustomerAddress) {
  return [address.label || '地址', address.city || address.country_code].filter(Boolean).join(' · ')
}

watch(() => [form.accountName, form.website, form.secondaryRegionId], scheduleDuplicateCheck)
watch(() => form.primaryRegionId, (current, previous) => {
  if (previous && current !== previous) form.secondaryRegionId = ''
})
watch(form, clearFieldErrors, { deep: true })

onMounted(() => {
  if (canEdit.value) void loadPage()
  else loading.value = false
})
onBeforeUnmount(() => {
  if (duplicateTimer) clearTimeout(duplicateTimer)
})
</script>

<template>
  <main class="customer-edit-page" data-customer-edit-page>
    <header class="form-page-header">
      <div class="title-block">
        <p>客户管理 / 客户列表 / 编辑客户</p>
        <div class="title-line">
          <h1>编辑客户</h1>
          <span v-if="customer" class="title-status">{{ customer.archived_at ? '已归档' : '正常' }}</span>
          <b v-if="customer">{{ customer.account_code }} · {{ customer.account_name }}</b>
        </div>
        <small>{{ customer ? `最后保存：${formatCustomerDateTime(customer.updated_at)} · 负责人：${primaryOwner}` : '加载客户资料中' }}</small>
      </div>
      <div class="header-actions">
        <ElButton @click="returnToList">返回列表</ElButton>
      </div>
    </header>

    <section v-if="!canEdit" class="page-state">
      <ElResult icon="warning" title="无权编辑客户" sub-title="当前账号缺少编辑客户权限，请联系管理员。">
        <template #extra><ElButton @click="router.push({ name: 'customers' })">返回客户列表</ElButton></template>
      </ElResult>
    </section>
    <section v-else-if="loading" class="page-state page-state--loading" aria-busy="true">
      <ElSkeleton :rows="12" animated />
    </section>
    <section v-else-if="loadError" class="page-state">
      <ElResult icon="error" title="无法打开客户编辑页" :sub-title="loadError">
        <template #extra>
          <ElButton @click="router.push({ name: 'customers' })">返回列表</ElButton>
          <ElButton type="primary" @click="loadPage">重新加载</ElButton>
        </template>
      </ElResult>
    </section>

    <template v-else-if="customer && options">
      <section class="edit-workspace">
        <aside class="edit-section-nav" aria-label="编辑内容导航">
          <p class="nav-heading">客户资料</p>
          <div class="nav-progress">
            <div><span>资料完整度</span><strong>{{ completeness }}%</strong></div>
            <ElProgress :percentage="completeness" :show-text="false" :stroke-width="4" />
            <small>{{ Math.round(completeness / 100 * 11) }} / 11 项必填已完成</small>
          </div>
          <p class="nav-subheading">编辑分区</p>
          <button :class="{ 'is-active': activeSection === 'profile' }" @click="scrollToSection('profile')"><span>01</span>主体资料</button>
          <button :class="{ 'is-active': activeSection === 'address' }" @click="scrollToSection('address')"><span>02</span>地址信息</button>
          <button :class="{ 'is-active': activeSection === 'attributes' }" @click="scrollToSection('attributes')"><span>03</span>客户属性</button>
          <button :class="{ 'is-active': activeSection === 'ownership' }" @click="scrollToSection('ownership')"><span>04</span>归属与标签</button>
          <div class="save-rule"><strong>保存规则</strong><p>保存时统一校验必填项；客户分类、来源和等级变化会保留画像历史。</p></div>
        </aside>

        <ElForm label-position="top" class="edit-form" :model="form" @submit.prevent>
          <section id="edit-section-profile" class="form-card">
            <header><div><h2>主体资料</h2><p><b>*</b> 为必填</p></div><span>{{ checkingDuplicate ? '正在实时查重' : '正在实时查重' }}</span></header>
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
              <div><h2>地址信息</h2><p>已保存 {{ addresses.length }} 条</p></div>
              <div class="address-header-actions">
                <div v-if="addresses.length" class="address-tabs">
                  <button v-for="item in addresses" :key="item.id" :class="{ 'is-active': activeAddressId === item.id }" @click.prevent="selectAddress(item.id)">{{ addressSummary(item) }}</button>
                  <span v-if="!activeAddressId">新增地址</span>
                </div>
                <ElButton @click="startNewAddress">＋ 新增地址</ElButton>
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
            <header><div><h2>客户属性</h2><p>变更将保留画像历史</p></div><span>下方继续：归属与标签</span></header>
            <div class="edit-grid">
              <ElFormItem label="客户类型" required :error="fieldErrors.typeIds" data-field="typeIds"><ElSelect v-model="form.typeIds" multiple collapse-tags><ElOption v-for="item in options.customer_types" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="客户来源" required :error="fieldErrors.sourceId" data-field="sourceId"><ElSelect v-model="form.sourceId"><ElOption v-for="item in options.customer_sources" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="客户等级" required :error="fieldErrors.gradeId" data-field="gradeId"><ElSelect v-model="form.gradeId"><ElOption v-for="item in options.customer_grades" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="生命周期"><ElSelect v-model="form.lifecycleStage"><ElOption v-for="item in options.lifecycle_stages" :key="item.item_code" :label="item.display_name" :value="item.item_code" /></ElSelect></ElFormItem>
            </div>
            <div class="attribute-summary">所属行业：{{ options.industries.find((item) => item.id === form.industryId)?.display_name || '未设置' }}　 感兴趣产品：{{ form.interestedProductIds.length ? `${form.interestedProductIds.length} 项` : '未设置' }}　 负责人：{{ primaryOwner }}（只读）</div>
          </section>

          <div class="continue-hint">继续向下可编辑感兴趣产品、询盘关键词、业务员、分管人和客户标签</div>

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
              <ElFormItem class="span-2" label="变更说明" required><ElInput v-model="changeReason" maxlength="200" placeholder="用于等级、来源与分类的审计记录" /></ElFormItem>
              <ElFormItem class="span-2" label="备注"><ElInput v-model="form.notes" type="textarea" :rows="3" maxlength="2000" show-word-limit /></ElFormItem>
            </div>
          </section>

          <section id="edit-section-duplicate" class="form-card duplicate-section">
            <header><div><h2>重复检查</h2><p>根据当前客户名称、网站和国家实时检查，不包含本客户</p></div><span>{{ checkingDuplicate ? '检查中' : `${duplicateMatches.length} 条匹配` }}</span></header>
            <div v-if="duplicateMatches.length" class="duplicate-list">
              <article v-for="match in duplicateMatches" :key="match.customer_id">
                <div><strong>{{ match.account_name }}</strong><span>{{ match.account_code }} · {{ match.primary_country_code || '国家未知' }}</span></div>
                <b>{{ match.match_score }}%</b>
              </article>
            </div>
            <div v-else class="duplicate-empty">{{ checkingDuplicate ? '正在检查真实客户数据…' : '未发现其他匹配客户。' }}</div>
          </section>
        </ElForm>

        <aside class="edit-context" aria-label="客户编辑摘要">
          <section class="context-card snapshot-card">
            <h2>客户快照</h2>
            <p>{{ customer.account_code }} · {{ customer.account_name }}</p>
            <dl>
              <div><dt>客户状态</dt><dd>{{ lifecycleName }}</dd></div>
              <div><dt>国家 / 地区</dt><dd>{{ selectedCountryName }}</dd></div>
              <div><dt>负责人</dt><dd>{{ primaryOwner }}</dd></div>
              <div><dt>最近联系</dt><dd>{{ formatCustomerDateTime(customer.last_contact_at) }}</dd></div>
            </dl>
          </section>
          <section class="context-card change-card">
            <header><h2>本次修改</h2><span :class="{ 'has-change': isDirty }">{{ isDirty ? '未保存' : '已同步' }}</span></header>
            <p>{{ isDirty ? '页面存在未保存修改。保存时会使用版本号防止覆盖他人的更新。' : '当前表单与服务器数据一致。' }}</p>
          </section>
          <section class="context-card audit-card">
            <h2>保存说明</h2>
            <ul><li>客户编号不可修改</li><li>负责人通过客户转移流程调整</li><li>等级、来源与分类变更保留历史</li><li>地址与法定主体独立保存</li></ul>
          </section>
        </aside>
      </section>

      <footer class="edit-save-bar">
        <div><strong>{{ isDirty ? '有未保存的修改' : '当前资料已同步' }}</strong><span>保存失败时会保留当前输入并显示明确原因</span></div>
        <div class="footer-actions">
          <ElButton @click="cancelEdit">取消</ElButton>
          <ElButton :loading="saving" :disabled="!isDirty" @click="saveProfile(false, true)">保存草稿</ElButton>
          <ElButton type="primary" :loading="saving" :disabled="!isDirty" @click="saveProfile(true, false)">保存并返回</ElButton>
          <ElButton type="primary" :loading="saving" :disabled="!isDirty" @click="saveProfile(false, false)">保存</ElButton>
        </div>
      </footer>
    </template>
  </main>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use './customer-form-shared' as shared;

.customer-edit-page {
  width: 100%; height: calc(100dvh - 64px); min-height: 760px; overflow: hidden;
  color: token.$crm-text-primary; background: token.$crm-color-page; font-family: token.$crm-font-body;
  @include shared.crm-buttons;
}
.form-page-header { height: 104px; display: flex; align-items: center; justify-content: space-between; padding: 0 28px; border-bottom: 1px solid token.$crm-border-default; background: token.$crm-color-surface; }
.title-block { height: 83px; padding-top: 1px; }
.title-block > p { margin: 0; color: token.$crm-text-muted; font-size: 11px; line-height: 20px; }
.title-line { height: 38px; display: flex; align-items: center; gap: 12px; }
.title-line h1 { margin: 0; font-family: token.$crm-font-display; font-size: 28px; font-weight: 700; line-height: 33px; letter-spacing: -0.02em; }
.title-line span { height: 24px; display: inline-flex; align-items: center; padding: 0 9px; border-radius: token.$crm-radius-pill; color: token.$crm-text-secondary; background: token.$crm-color-subtle; font-size: 11px; }
.title-line .title-status { color: token.$crm-success; background: token.$crm-success-soft; }
.title-line b { max-width: 520px; overflow: hidden; color: token.$crm-text-secondary; font-size: 13px; font-weight: 500; line-height: 24px; text-overflow: ellipsis; white-space: nowrap; }
.title-block > small { display: block; color: token.$crm-text-muted; font-size: 11px; line-height: 20px; }
.header-actions { display: flex; gap: 8px; }
.header-actions :deep(.el-button:first-child) { width: 84px; padding: 0; }
.page-state { height: calc(100% - 104px); display: grid; place-items: center; padding: 48px; background: token.$crm-color-surface; }
.page-state--loading { display: block; }
.page-state--loading :deep(.el-skeleton) { max-width: 1200px; margin: 40px auto; }

.edit-workspace { height: calc(100% - 176px); display: grid; grid-template-columns: 196px minmax(0, 1060px) 346px; gap: 20px; padding: 20px 24px; overflow: hidden; }
.edit-section-nav { min-height: 0; overflow: hidden; background: token.$crm-color-surface; }
.nav-heading, .nav-subheading { height: 34px; margin: 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.nav-subheading { display: flex; align-items: flex-end; padding-bottom: 4px; }
.edit-section-nav > button { width: 100%; height: 32px; display: flex; align-items: center; gap: 10px; padding: 0 12px; border: 0; border-radius: token.$crm-radius-2; color: token.$crm-text-secondary; background: transparent; font: 500 12px/20px token.$crm-font-body; text-align: left; cursor: pointer; }
.edit-section-nav > button:hover { background: token.$crm-color-subtle; }
.edit-section-nav > button.is-active { color: token.$crm-primary; background: token.$crm-danger-soft; }
.edit-section-nav > button span { width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; background: token.$crm-color-subtle; color: token.$crm-text-muted; font-size: 11px; }
.edit-section-nav > button.is-active span { color: token.$crm-text-inverse; background: token.$crm-primary; }
.nav-progress { height: 82px; padding: 12px 14px; border: 1px solid token.$crm-border-default; border-radius: 7px; background: token.$crm-color-surface; }
.nav-progress > div { display: flex; justify-content: space-between; margin-bottom: 8px; color: token.$crm-text-secondary; font-size: 11px; line-height: 20px; }
.nav-progress strong { color: token.$crm-success; }
.nav-progress :deep(.el-progress-bar__outer) { background: token.$crm-border-default; }
.nav-progress :deep(.el-progress-bar__inner) { background: token.$crm-success; }
.nav-progress small { display: block; margin-top: 7px; color: token.$crm-text-muted; font-size: 10px; line-height: 16px; }
.save-rule { margin-top: 14px; padding: 12px; border-radius: 7px; color: token.$crm-text-secondary; background: token.$crm-warning-soft; }
.save-rule strong { color: token.$crm-warning; font-size: 11px; line-height: 19px; }
.save-rule p { margin: 6px 0 0; font-size: 10px; line-height: 18px; }

.edit-form { min-height: 0; overflow-x: hidden; overflow-y: auto; padding-right: 4px; scroll-behavior: smooth; @include shared.element-form-controls(32px, 11px, 12px, 3px); }
.form-card { margin-bottom: 12px; padding: 16px; scroll-margin-top: 8px; border: 1px solid token.$crm-border-default; border-radius: 8px; background: token.$crm-color-surface; }
.form-card > header { min-height: 38px; display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; border-bottom: 1px solid token.$crm-border-subtle; }
.form-card > header h2 { margin: 0; font-family: token.$crm-font-display; font-size: 16px; font-weight: 700; line-height: 22px; }
.form-card > header p { margin: 2px 0 0; color: token.$crm-text-muted; font-size: 11px; line-height: 18px; }
.form-card > header > span { padding: 2px 8px; border-radius: token.$crm-radius-pill; color: token.$crm-success; background: token.$crm-success-soft; font-size: 11px; line-height: 20px; }
.form-card > header p b { color: token.$crm-primary; }
.form-card > header :deep(.el-button) { height: 32px; padding: 0 12px; font-size: 11px; }
.edit-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px 12px; }
.edit-grid :deep(.el-form-item) { min-width: 0; min-height: 56px; }
.span-2 { grid-column: span 2; }
.span-4 { grid-column: 1 / -1; }
.edit-grid :deep(.el-textarea__inner) { min-height: 74px !important; padding: 8px 10px; border: 0; border-radius: token.$crm-radius-3; box-shadow: 0 0 0 1px token.$crm-border-default inset; resize: vertical; }
.address-header-actions { display: flex; align-items: center; gap: 8px; min-width: 0; }
.address-tabs { max-width: 380px; display: flex; align-items: center; gap: 6px; overflow-x: auto; }
.address-tabs button, .address-tabs > span { height: 28px; flex: none; padding: 0 10px; border: 1px solid token.$crm-border-default; border-radius: token.$crm-radius-pill; color: token.$crm-text-secondary; background: token.$crm-color-surface; font: 11px/26px token.$crm-font-body; cursor: pointer; }
.address-tabs button.is-active, .address-tabs > span { border-color: token.$crm-primary; color: token.$crm-primary; background: token.$crm-danger-soft; }
.address-version { height: 28px; display: flex; align-items: center; justify-content: space-between; margin-top: 8px; padding: 0 10px; border-radius: token.$crm-radius-3; color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 10px; }
.address-version b { color: token.$crm-warning; font-weight: 500; }
.address-card { padding: 16px 20px; }
.address-card .address-version { height: 24px; margin-top: 6px; }
.attributes-card { padding: 16px 20px; }
.attributes-card > header { min-height: 32px; margin-bottom: 8px; }
.attribute-summary { height: 36px; display: flex; align-items: center; margin-top: 8px; padding: 0 10px; border-radius: token.$crm-radius-3; color: token.$crm-text-secondary; background: token.$crm-success-soft; font-size: 10px; }
.continue-hint { height: 72px; display: grid; place-items: center; margin-bottom: 12px; border: 1px solid token.$crm-border-default; border-radius: 8px; color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 11px; }
.duplicate-list { display: grid; gap: 8px; }
.duplicate-list article { height: 48px; display: flex; align-items: center; justify-content: space-between; padding: 0 12px; border: 1px solid token.$crm-warning-border; border-radius: token.$crm-radius-3; background: token.$crm-warning-soft; }
.duplicate-list article div { display: flex; flex-direction: column; }
.duplicate-list strong { font-size: 12px; line-height: 19px; }
.duplicate-list span { color: token.$crm-text-muted; font-size: 10px; line-height: 17px; }
.duplicate-list b { color: token.$crm-warning; font-size: 12px; }
.duplicate-empty { height: 52px; display: grid; place-items: center; color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 12px; }

.edit-context { min-height: 0; display: flex; flex-direction: column; gap: 14px; overflow: hidden; }
.context-card { padding: 16px; border: 1px solid token.$crm-border-default; border-radius: 8px; background: token.$crm-color-surface; }
.snapshot-card { height: 294px; }
.snapshot-card h2 { margin: 0; overflow: hidden; font-size: 15px; line-height: 23px; text-overflow: ellipsis; white-space: nowrap; }
.snapshot-card > p { margin: 2px 0 12px; color: token.$crm-text-muted; font-size: 11px; line-height: 18px; }
.snapshot-card dl { margin: 0; border-top: 1px solid token.$crm-border-subtle; }
.snapshot-card dl div { min-height: 37px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid token.$crm-border-subtle; }
.snapshot-card dt { color: token.$crm-text-muted; font-size: 11px; }
.snapshot-card dd { margin: 0; overflow: hidden; color: token.$crm-text-secondary; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.context-card h2 { margin: 0; font-size: 13px; line-height: 21px; }
.change-card header { display: flex; align-items: center; justify-content: space-between; }
.change-card { height: 151px; }
.change-card header span { padding: 2px 8px; border-radius: token.$crm-radius-pill; color: token.$crm-success; background: token.$crm-success-soft; font-size: 10px; }
.change-card header span.has-change { color: token.$crm-warning; background: token.$crm-warning-soft; }
.change-card p { margin: 10px 0 0; color: token.$crm-text-secondary; font-size: 11px; line-height: 19px; }
.audit-card { background: token.$crm-color-subtle; }
.audit-card { height: 156px; }
.audit-card ul { display: flex; flex-direction: column; gap: 8px; margin: 10px 0 0; padding: 0; list-style: none; }
.audit-card li { position: relative; padding-left: 13px; color: token.$crm-text-secondary; font-size: 11px; line-height: 18px; }
.audit-card li::before { position: absolute; top: 7px; left: 0; width: 5px; height: 5px; border-radius: 50%; background: token.$crm-primary; content: ''; }

.edit-save-bar { height: 72px; display: flex; align-items: center; justify-content: space-between; padding: 0 28px; border-top: 1px solid token.$crm-border-default; background: token.$crm-color-surface; box-shadow: 0 -5px 18px rgba(31, 29, 24, 0.04); }
.edit-save-bar > div:first-child { display: flex; flex-direction: column; }
.edit-save-bar strong { font-size: 12px; line-height: 20px; }
.edit-save-bar span { color: token.$crm-text-muted; font-size: 10px; line-height: 18px; }
.footer-actions { display: flex; gap: 8px; }
.footer-actions :deep(.el-button:first-child) { width: 58px; padding: 0; }
.footer-actions :deep(.el-button:nth-child(2)) { width: 84px; padding: 0; }
.footer-actions :deep(.el-button:nth-child(3)) { width: 97px; padding: 0; }
.footer-actions :deep(.el-button:nth-child(4)) { width: 58px; padding: 0; }

/* 按客诉编辑原型收敛为居中的双栏操作面板。 */
.customer-edit-page {
  width: min(1320px, calc(100% - 56px));
  height: min(900px, calc(100dvh - 132px));
  min-height: 0;
  margin: 20px auto;
  border: 1px solid token.$crm-border-default;
  border-radius: 6px;
  background: token.$crm-color-surface;
  box-shadow: 0 18px 46px rgb(43 37 31 / 14%);
}

.form-page-header {
  height: 76px;
  padding: 0 30px;
}

.title-block {
  height: auto;
  padding: 0;
}

.title-block > p {
  display: none;
}

.title-line {
  height: 36px;
}

.title-line h1 {
  font-size: 28px;
  font-weight: 600;
  line-height: 34px;
}

.title-line b {
  max-width: 560px;
}

.title-block > small {
  line-height: 18px;
}

.edit-workspace {
  height: calc(100% - 148px);
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 0;
  padding: 0;
  background: token.$crm-color-surface;
}

.edit-section-nav {
  display: none;
}

.edit-form {
  padding: 20px 28px;
  overflow-y: auto;
  @include shared.element-form-controls(32px, 11px, 12px, 4px);
}

:global(.customer-form-message-box) {
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  --el-color-primary: #{token.$crm-primary};
}

:global(.customer-form-message-box .el-button) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

:global(.customer-form-message-box .el-button + .el-button) {
  margin-left: 8px;
}

:global(.customer-form-message-box .el-button--primary) {
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

:global(.customer-form-message-box .el-button--primary:hover),
:global(.customer-form-message-box .el-button--primary:focus-visible) {
  border-color: token.$crm-primary-hover;
  background: token.$crm-primary-hover;
}

.form-card {
  margin-bottom: 12px;
  padding: 16px;
  border-radius: 4px;
}

.form-card > header h2 {
  font-size: 18px;
  font-weight: 600;
}

.edit-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 12px;
}

.span-4 {
  grid-column: 1 / -1;
}

.edit-context {
  gap: 14px;
  padding: 24px;
  overflow-y: auto;
  border-left: 1px solid token.$crm-border-default;
  background: token.$crm-color-subtle;
}

.context-card {
  height: auto;
  min-height: 0;
  border-radius: 4px;
}

.snapshot-card,
.change-card,
.audit-card {
  height: auto;
}

.edit-save-bar {
  height: 72px;
  padding: 0 30px;
  box-shadow: none;
}

.footer-actions {
  gap: 10px;
}

.footer-actions :deep(.el-button) {
  min-width: 88px;
  height: 32px;
  margin: 0;
  border-radius: token.$crm-radius-2;
}

.footer-actions :deep(.el-button:nth-child(3)) {
  min-width: 104px;
}

@media (max-width: 1500px) {
  .customer-edit-page { overflow: hidden; }
  .form-page-header, .edit-workspace, .edit-save-bar { min-width: 0; }
}
</style>
