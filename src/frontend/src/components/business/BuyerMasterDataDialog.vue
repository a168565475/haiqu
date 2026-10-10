<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { fetchContact, fetchCustomerContacts, updateContact } from '@/api/contacts'
import {
  createEntityAddress,
  fetchCustomerEntity,
  fetchEntityAddress,
  fetchEntityAddresses,
  updateCustomerEntity,
  updateEntityAddress,
} from '@/api/customers'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { ContactDetail, ContactListItem } from '@/types/contact'
import type { CustomerAddress, CustomerAddressInput, CustomerEntity } from '@/types/customer'

type BuyerTab = 'entity' | 'address' | 'contact'

const props = withDefaults(defineProps<{
  modelValue: boolean
  customerId: string
  entityId: string
  selectedAddressId?: string | null
  initialTab?: BuyerTab
  contextName?: string
  canEditEntity?: boolean
  canEditAddress?: boolean
  canEditContact?: boolean
  closeOnAddressSave?: boolean
}>(), {
  selectedAddressId: null,
  initialTab: 'entity',
  contextName: '单据',
  canEditEntity: true,
  canEditAddress: true,
  canEditContact: true,
  closeOnAddressSave: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'address-selected': [address: CustomerAddress | null]
  'address-saved': [address: CustomerAddress]
  'entity-updated': [entity: CustomerEntity]
}>()

const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const loading = ref(false)
const saving = ref(false)
const activeTab = ref<BuyerTab>('entity')
const entity = ref<CustomerEntity | null>(null)
const addresses = ref<CustomerAddress[]>([])
const contacts = ref<ContactListItem[]>([])
const contactDetail = ref<ContactDetail | null>(null)
const currentAddressId = ref('')
const currentContactId = ref('')
const creatingAddress = ref(false)
const entityForm = reactive({
  entity_code: '', entity_type: '', legal_name: '', english_legal_name: '', registration_country_code: '',
  registration_number: '', tax_country_code: '', tax_identifier: '', notes: '',
})
const addressForm = reactive<CustomerAddressInput>({
  address_code: '', label: '', country_code: '', state_province: '', city: '', postal_code: '',
  address_line1: '', address_line2: '', recipient_name: '', recipient_phone: '', is_verified: false,
})
const contactForm = reactive({
  display_name: '', english_name: '', position_title: '', department_name: '', preferred_language_code: '',
  timezone_code: '', is_key_contact: false, is_primary_contact: false, notes: '',
})

function errorMessage(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '客户资料处理失败。'
  const data = error.response?.data as { error?: { message?: string } } | undefined
  return data?.error?.message || '客户资料处理失败，请稍后重试。'
}

function applyEntity(item: CustomerEntity) {
  entity.value = item
  Object.assign(entityForm, {
    entity_code: item.entity_code, entity_type: item.entity_type, legal_name: item.legal_name,
    english_legal_name: item.english_legal_name, registration_country_code: item.registration_country_code,
    registration_number: item.registration_number, tax_country_code: item.tax_country_code,
    tax_identifier: item.tax_identifier, notes: item.notes,
  })
}

function clearAddress() {
  Object.assign(addressForm, {
    address_code: '', label: '', country_code: '', state_province: '', city: '', postal_code: '',
    address_line1: '', address_line2: '', recipient_name: '', recipient_phone: '', is_verified: false,
  })
}

function applyAddress(item: CustomerAddress | null) {
  if (!item) return clearAddress()
  Object.assign(addressForm, {
    address_code: item.address_code, label: item.label, country_code: item.country_code,
    state_province: item.state_province, city: item.city, postal_code: item.postal_code,
    address_line1: item.address_line1, address_line2: item.address_line2,
    recipient_name: item.recipient_name, recipient_phone: item.recipient_phone, is_verified: item.is_verified,
  })
}

function applyContact(item: ContactDetail | null) {
  contactDetail.value = item
  Object.assign(contactForm, item ? {
    display_name: item.display_name, english_name: item.english_name, position_title: item.position_title,
    department_name: item.department_name, preferred_language_code: item.preferred_language_code,
    timezone_code: item.timezone_code, is_key_contact: item.is_key_contact,
    is_primary_contact: item.is_primary_contact, notes: item.notes,
  } : {
    display_name: '', english_name: '', position_title: '', department_name: '', preferred_language_code: '',
    timezone_code: '', is_key_contact: false, is_primary_contact: false, notes: '',
  })
}

function selectAddress(addressId: string) {
  creatingAddress.value = false
  currentAddressId.value = addressId
  const item = addresses.value.find((address) => address.id === addressId) || null
  applyAddress(item)
  emit('address-selected', item)
}

async function selectContact(contactId: string) {
  currentContactId.value = contactId
  if (!contactId) return applyContact(null)
  try {
    applyContact((await fetchContact(contactId)).data)
  } catch (error) {
    applyContact(null)
    ElMessage.error(errorMessage(error))
  }
}

function newAddressCode() {
  return `ADDR_${new Date().toISOString().replace(/\D/g, '').slice(0, 14)}`
}

function startNewAddress() {
  if (!props.canEditAddress) return
  creatingAddress.value = true
  currentAddressId.value = ''
  clearAddress()
  addressForm.address_code = newAddressCode()
  addressForm.label = `${props.contextName}地址`
  addressForm.country_code = entity.value?.registration_country_code || ''
}

async function load() {
  if (!props.entityId) {
    ElMessage.warning('请先选择买方主体。')
    visible.value = false
    return
  }
  loading.value = true
  try {
    const [entityResult, addressResult, contactResult] = await Promise.all([
      fetchCustomerEntity(props.entityId),
      fetchEntityAddresses(props.entityId),
      props.customerId ? fetchCustomerContacts(props.customerId, { status: 'ACTIVE', page: 1, page_size: 100 }) : Promise.resolve({ data: [] as ContactListItem[] }),
    ])
    applyEntity(entityResult.data)
    addresses.value = addressResult.filter((item) => !item.archived_at)
    contacts.value = contactResult.data

    const requested = props.selectedAddressId && addresses.value.find((item) => item.id === props.selectedAddressId)
    const automatic = addresses.value.length === 1 ? addresses.value[0] : null
    selectAddress((requested || automatic)?.id || '')
    const contactId = contacts.value[0]?.id || ''
    await selectContact(contactId)
    activeTab.value = props.initialTab
    if (activeTab.value === 'address' && addresses.value.length === 0 && props.canEditAddress) startNewAddress()
  } catch (error) {
    ElMessage.error(errorMessage(error))
    visible.value = false
  } finally {
    loading.value = false
  }
}

async function saveEntity() {
  if (!entity.value || !props.canEditEntity) return
  if (!entityForm.legal_name.trim()) return ElMessage.warning('请填写法定名称。')
  saving.value = true
  try {
    const current = await fetchCustomerEntity(entity.value.id)
    if (!current.etag) throw new Error('客户主体版本缺失，请重新打开后重试。')
    const updated = await updateCustomerEntity(entity.value.id, {
      entity_code: entityForm.entity_code.trim(), entity_type: entityForm.entity_type,
      legal_name: entityForm.legal_name.trim(), english_legal_name: entityForm.english_legal_name.trim(),
      registration_country_code: entityForm.registration_country_code.trim().toUpperCase(),
      registration_number: entityForm.registration_number.trim(), tax_country_code: entityForm.tax_country_code.trim().toUpperCase(),
      tax_identifier: entityForm.tax_identifier.trim(), notes: entityForm.notes.trim(),
    }, current.etag)
    applyEntity(updated)
    emit('entity-updated', updated)
    ElMessage.success('买方交易主体已更新。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function saveAddress() {
  if (!props.canEditAddress) return
  if (!addressForm.address_code.trim()) return ElMessage.warning('请填写地址编码。')
  if (!addressForm.country_code.trim()) return ElMessage.warning('请填写国家/地区代码。')
  if (!addressForm.address_line1.trim()) return ElMessage.warning('请填写地址第一行。')
  saving.value = true
  try {
    const payload: CustomerAddressInput = {
      ...addressForm,
      address_code: addressForm.address_code.trim().toUpperCase(), label: addressForm.label.trim(),
      country_code: addressForm.country_code.trim().toUpperCase(), state_province: addressForm.state_province.trim(),
      city: addressForm.city.trim(), postal_code: addressForm.postal_code.trim(), address_line1: addressForm.address_line1.trim(),
      address_line2: addressForm.address_line2.trim(), recipient_name: addressForm.recipient_name.trim(),
      recipient_phone: addressForm.recipient_phone.trim(),
    }
    let saved: CustomerAddress
    if (creatingAddress.value) {
      saved = await createEntityAddress(props.entityId, payload)
    } else {
      if (!currentAddressId.value) return
      const current = await fetchEntityAddress(currentAddressId.value)
      if (!current.etag) throw new Error('地址版本缺失，请重新打开后重试。')
      saved = await updateEntityAddress(currentAddressId.value, payload, current.etag)
    }
    addresses.value = (await fetchEntityAddresses(props.entityId)).filter((item) => !item.archived_at)
    creatingAddress.value = false
    currentAddressId.value = saved.id
    applyAddress(saved)
    emit('address-selected', saved)
    emit('address-saved', saved)
    ElMessage.success(`客户地址已保存，并已选为本次${props.contextName}地址。`)
    if (props.closeOnAddressSave) visible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function saveContact() {
  if (!currentContactId.value || !props.canEditContact) return
  saving.value = true
  try {
    const current = await fetchContact(currentContactId.value)
    if (!current.etag) throw new Error('联系人版本缺失，请重新打开后重试。')
    await updateContact(currentContactId.value, {
      display_name: contactForm.display_name.trim(), english_name: contactForm.english_name.trim(),
      position_title: contactForm.position_title.trim(), department_name: contactForm.department_name.trim(),
      preferred_language_code: contactForm.preferred_language_code.trim(), timezone_code: contactForm.timezone_code.trim(),
      is_key_contact: contactForm.is_key_contact, is_primary_contact: contactForm.is_primary_contact, notes: contactForm.notes.trim(),
    }, current.etag)
    await selectContact(currentContactId.value)
    ElMessage.success('买方联系人已更新。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

watch(() => props.modelValue, (value) => { if (value) void load() })
</script>

<template>
  <AppWindowDialog v-model="visible" class="buyer-master-dialog" :class="{ 'sales-order-master-dialog': contextName === '销售订单' }" :title="contextName === '销售订单' ? '买方资料' : '编辑买方客户资料'" :width="900" :height="800" :close-on-click-modal="false">
    <div v-loading="loading">
      <el-alert :title="`此处修改客户主数据；已经锁定或确认的${contextName}仍使用既有快照。`" type="info" :closable="false" show-icon />
      <el-tabs v-model="activeTab" class="buyer-tabs">
        <el-tab-pane label="交易主体" name="entity">
          <el-form label-position="top" class="buyer-form">
            <el-form-item label="主体编码"><el-input v-model="entityForm.entity_code" :disabled="!canEditEntity" maxlength="80" /></el-form-item>
            <el-form-item label="主体类型"><el-input v-model="entityForm.entity_type" :disabled="!canEditEntity" maxlength="30" /></el-form-item>
            <el-form-item label="法定名称 *"><el-input v-model="entityForm.legal_name" :disabled="!canEditEntity" maxlength="300" /></el-form-item>
            <el-form-item label="英文法定名称"><el-input v-model="entityForm.english_legal_name" :disabled="!canEditEntity" maxlength="300" /></el-form-item>
            <el-form-item label="注册国家/地区"><el-input v-model="entityForm.registration_country_code" :disabled="!canEditEntity" maxlength="2" /></el-form-item>
            <el-form-item label="注册号"><el-input v-model="entityForm.registration_number" :disabled="!canEditEntity" maxlength="120" /></el-form-item>
            <el-form-item label="税务国家/地区"><el-input v-model="entityForm.tax_country_code" :disabled="!canEditEntity" maxlength="2" /></el-form-item>
            <el-form-item label="税号"><el-input v-model="entityForm.tax_identifier" :disabled="!canEditEntity" maxlength="120" /></el-form-item>
            <el-form-item label="备注" class="full"><el-input v-model="entityForm.notes" type="textarea" :rows="3" :disabled="!canEditEntity" maxlength="1000" /></el-form-item>
          </el-form>
          <div class="tab-actions"><span>责任角色：客户资料维护人员</span><el-button v-if="canEditEntity" type="primary" :loading="saving" @click="saveEntity">保存交易主体</el-button></div>
        </el-tab-pane>
        <el-tab-pane label="地址" name="address">
          <div class="address-toolbar">
            <div v-if="addresses.length && !creatingAddress" class="selector"><span>当前地址</span><el-select v-model="currentAddressId" placeholder="多地址时请选择" @change="selectAddress"><el-option v-for="item in addresses" :key="item.id" :value="item.id" :label="`${item.label || item.address_code} · ${item.city || item.country_code}`" /></el-select></div>
            <span v-else-if="creatingAddress">正在新增客户地址</span><span v-else>当前买方主体还没有地址</span>
            <el-button v-if="canEditAddress" :icon="Plus" @click="startNewAddress">新增地址</el-button>
          </div>
          <el-alert v-if="addresses.length > 1 && !currentAddressId && !creatingAddress" title="该主体有多个有效地址，请人工选择；系统不会擅自使用第一条地址。" type="warning" :closable="false" show-icon />
          <template v-if="currentAddressId || creatingAddress">
            <el-alert v-if="creatingAddress" :title="`地址将保存到客户交易主体档案，并自动选为本次${contextName}地址。`" type="info" :closable="false" show-icon />
            <el-form label-position="top" class="buyer-form address-form">
              <el-form-item label="地址编码"><el-input v-model="addressForm.address_code" :disabled="!canEditAddress" maxlength="50" /></el-form-item>
              <el-form-item label="地址标签"><el-input v-model="addressForm.label" :disabled="!canEditAddress" maxlength="150" /></el-form-item>
              <el-form-item label="国家/地区 *"><el-input v-model="addressForm.country_code" :disabled="!canEditAddress" maxlength="2" /></el-form-item>
              <el-form-item label="省/州"><el-input v-model="addressForm.state_province" :disabled="!canEditAddress" maxlength="150" /></el-form-item>
              <el-form-item label="城市"><el-input v-model="addressForm.city" :disabled="!canEditAddress" maxlength="150" /></el-form-item>
              <el-form-item label="邮编"><el-input v-model="addressForm.postal_code" :disabled="!canEditAddress" maxlength="30" /></el-form-item>
              <el-form-item label="地址第一行 *" class="full"><el-input v-model="addressForm.address_line1" :disabled="!canEditAddress" maxlength="250" /></el-form-item>
              <el-form-item label="地址第二行" class="full"><el-input v-model="addressForm.address_line2" :disabled="!canEditAddress" maxlength="250" /></el-form-item>
              <el-form-item label="收件人"><el-input v-model="addressForm.recipient_name" :disabled="!canEditAddress" maxlength="150" /></el-form-item>
              <el-form-item label="收件人电话"><el-input v-model="addressForm.recipient_phone" :disabled="!canEditAddress" maxlength="50" /></el-form-item>
              <el-form-item label="已校验"><el-switch v-model="addressForm.is_verified" :disabled="!canEditAddress" /></el-form-item>
            </el-form>
            <div class="tab-actions"><span>本轮确认订单不强制“已校验”标记</span><el-button v-if="canEditAddress" type="primary" :loading="saving" @click="saveAddress">{{ creatingAddress ? '新增并选用地址' : '保存并选用地址' }}</el-button></div>
          </template>
          <el-empty v-else-if="!addresses.length" description="请新增客户地址" :image-size="72"><el-button v-if="canEditAddress" type="primary" :icon="Plus" @click="startNewAddress">新增地址</el-button></el-empty>
        </el-tab-pane>
        <el-tab-pane label="联系人" name="contact">
          <template v-if="contacts.length">
            <div class="selector"><span>当前联系人</span><el-select v-model="currentContactId" @change="selectContact"><el-option v-for="item in contacts" :key="item.id" :value="item.id" :label="`${item.display_name}${item.position_title ? ` · ${item.position_title}` : ''}`" /></el-select></div>
            <p v-if="contactDetail" class="contact-methods">{{ contactDetail.methods.map((item) => `${item.method_type_display}：${item.masked_value}`).join(' · ') || '暂无联系方式' }}</p>
            <el-form label-position="top" class="buyer-form">
              <el-form-item label="姓名 *"><el-input v-model="contactForm.display_name" :disabled="!canEditContact" /></el-form-item><el-form-item label="英文名"><el-input v-model="contactForm.english_name" :disabled="!canEditContact" /></el-form-item>
              <el-form-item label="职位"><el-input v-model="contactForm.position_title" :disabled="!canEditContact" /></el-form-item><el-form-item label="部门"><el-input v-model="contactForm.department_name" :disabled="!canEditContact" /></el-form-item>
              <el-form-item label="偏好语言"><el-input v-model="contactForm.preferred_language_code" :disabled="!canEditContact" /></el-form-item><el-form-item label="时区"><el-input v-model="contactForm.timezone_code" :disabled="!canEditContact" /></el-form-item>
              <el-form-item label="关键联系人"><el-switch v-model="contactForm.is_key_contact" :disabled="!canEditContact" /></el-form-item><el-form-item label="主要联系人"><el-switch v-model="contactForm.is_primary_contact" :disabled="!canEditContact" /></el-form-item>
              <el-form-item label="备注" class="full"><el-input v-model="contactForm.notes" type="textarea" :rows="3" :disabled="!canEditContact" /></el-form-item>
            </el-form>
            <div class="tab-actions"><span>责任角色：客户资料维护人员</span><el-button v-if="canEditContact" type="primary" :loading="saving" @click="saveContact">保存联系人</el-button></div>
          </template>
          <el-empty v-else description="当前客户没有可编辑的联系人" :image-size="72" />
        </el-tab-pane>
      </el-tabs>
    </div>
    <template #footer><el-button @click="visible = false">关闭</el-button></template>
  </AppWindowDialog>
</template>

<style lang="scss" scoped>
.buyer-tabs{margin-top:16px}.buyer-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.buyer-form .full{grid-column:1/-1}.buyer-form :deep(.el-form-item){margin-bottom:13px}.address-toolbar{display:flex;min-height:40px;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 12px;color:#646a73;font-size:12px}.selector{display:grid;grid-template-columns:86px minmax(0,1fr);align-items:center;gap:10px;flex:1;margin:6px 0 14px;color:#5f6670;font-size:12px}.tab-actions{display:flex;align-items:center;justify-content:flex-end;gap:16px}.tab-actions span,.contact-methods{color:#71717a;font-size:12px}.address-form{margin-top:12px}
.sales-order-master-dialog{border-radius:6px;background:#fcfbf7}.sales-order-master-dialog :deep(.el-dialog__header){margin:0;padding:24px 28px 18px;border-bottom:1px solid #ddd6c9}.sales-order-master-dialog :deep(.el-dialog__title){font-family:'Noto Serif SC','Songti SC',serif;font-size:24px;font-weight:600}.sales-order-master-dialog :deep(.el-dialog__body){padding:18px 28px}.sales-order-master-dialog :deep(.el-dialog__footer){padding:14px 28px 22px}.sales-order-master-dialog .buyer-tabs{margin-top:8px}.sales-order-master-dialog :deep(.el-tabs__active-bar){background:#c84e28}.sales-order-master-dialog :deep(.el-tabs__item){height:52px;font-size:16px}.sales-order-master-dialog :deep(.el-tabs__item.is-active){color:#c84e28}.sales-order-master-dialog :deep(.el-input__wrapper),.sales-order-master-dialog :deep(.el-select__wrapper){min-height:38px;border-radius:4px}.sales-order-master-dialog :deep(.el-button){height:32px;border-radius:4px}.sales-order-master-dialog :deep(.el-button--primary){border-color:#c84e28;background:#c84e28}.sales-order-master-dialog :deep(.el-alert){border:0;background:#f0eadf}.sales-order-master-dialog .address-toolbar{min-height:46px;color:#6f6a61}.sales-order-master-dialog .buyer-form :deep(.el-form-item__label){color:#6f6a61}
</style>
