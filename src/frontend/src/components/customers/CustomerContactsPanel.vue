<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { createContact, fetchContact, updateContact } from '@/api/contacts'
import { useAuthStore } from '@/stores/auth'
import type { ContactDetail, ContactListItem, ContactMethod, ContactUpdateInput } from '@/types/contact'

const props = withDefaults(defineProps<{
  customerId: string
  contacts: ContactListItem[]
  loading?: boolean
  error?: string
}>(), { loading: false, error: '' })
const emit = defineEmits<{ retry: []; changed: [] }>()
const auth = useAuthStore()
const canCreate = computed(() => auth.hasPermission('customers.add_customercontact'))
const canEdit = computed(() => auth.hasPermission('customers.change_customercontact'))
const canReadEmail = computed(() => auth.hasPermission('customers.view_sensitive_customercontactmethod'))
const visible = ref(false)
const loadingDetail = ref(false)
const saving = ref(false)
const formError = ref('')
const editing = ref<ContactDetail | null>(null)
const editingId = ref('')
const etag = ref<string | null>(null)
const form = reactive({ name: '', email: '' })
let requestVersion = 0

const contactsInOrder = computed(() => [...props.contacts].sort((a, b) => Number(Boolean(b.is_primary_contact)) - Number(Boolean(a.is_primary_contact))))
// 后端按主要标记、ID 选择同类型首条；这里保持完全相同的编辑目标。
function emailMethod(contact: ContactListItem | null): ContactMethod | undefined {
  return contact?.methods.filter(method => method.method_type === 'EMAIL' && !method.archived_at)
    .sort((a, b) => Number(b.is_primary) - Number(a.is_primary) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))[0]
}
const originalEmail = computed(() => emailMethod(editing.value))
const emailHidden = computed(() => Boolean(originalEmail.value && (!canReadEmail.value || !originalEmail.value.display_value || originalEmail.value.display_value.includes('*'))))
const emailEditable = computed(() => !editing.value || (originalEmail.value
  ? !emailHidden.value && auth.hasPermission('customers.change_customercontactmethod')
  : auth.hasPermission('customers.add_customercontactmethod')))

function emails(contact: ContactListItem): ContactMethod[] {
  return contact.methods.filter(method => method.method_type === 'EMAIL' && !method.archived_at)
}

function message(error: unknown): string {
  if (!isAxiosError(error)) return error instanceof Error ? error.message : '联系人操作失败，请重试。'
  if (!error.response) return '网络连接异常，已保留输入内容，请重试。'
  if (error.response.status === 412) return '联系人已被其他人修改，请关闭并重新编辑。'
  if (error.response.status === 428) return '缺少数据版本，请关闭并重新编辑。'
  const data = error.response.data
  if (typeof data?.error?.message === 'string') return data.error.message
  if (typeof data?.detail === 'string') return data.detail
  if (data && typeof data === 'object') {
    const first = Object.values(data)[0]
    if (Array.isArray(first) && typeof first[0] === 'string') return first[0]
  }
  return error.response.status === 403 ? '没有执行此操作的权限。' : '联系人保存失败，请检查输入后重试。'
}

function closeEditor() {
  requestVersion += 1
  visible.value = false
  loadingDetail.value = false
}

function add() {
  if (!canCreate.value) return
  requestVersion += 1
  editing.value = null
  editingId.value = ''
  etag.value = null
  form.name = ''
  form.email = ''
  formError.value = ''
  loadingDetail.value = false
  visible.value = true
}

async function edit(contact: ContactListItem) {
  if (!canEdit.value || contact.status === 'LEFT') return
  const currentRequest = ++requestVersion
  editing.value = null
  editingId.value = contact.id
  form.name = contact.display_name
  form.email = ''
  etag.value = null
  formError.value = ''
  loadingDetail.value = true
  visible.value = true
  try {
    const result = await fetchContact(contact.id)
    if (currentRequest !== requestVersion) return
    if (result.data.status === 'LEFT') throw new Error('该联系人已离职，请在联系人菜单查看历史资料。')
    editing.value = result.data
    etag.value = result.etag
    form.name = result.data.display_name
    form.email = emailHidden.value ? '' : emailMethod(result.data)?.display_value || ''
    if (!result.etag) formError.value = '未取得数据版本，暂不能保存，请关闭后重试。'
  } catch (error) {
    if (currentRequest === requestVersion) formError.value = message(error)
  } finally {
    if (currentRequest === requestVersion) loadingDetail.value = false
  }
}

async function save() {
  if (saving.value || loadingDetail.value || editingId.value && !editing.value) return
  const name = form.name.trim()
  const email = form.email.trim()
  if (!name) { formError.value = '请填写联系人名称。'; return }
  if (!editing.value && !canCreate.value || editing.value && !canEdit.value) return
  if (!editing.value && !email) { formError.value = '请填写联系人邮箱。'; return }
  if (emailEditable.value && email.includes('*')) { formError.value = '请填写完整邮箱，不能保存脱敏值。'; return }
  if (emailEditable.value && email && !/^[^\s@]+@[^\s@]+$/.test(email)) {
    formError.value = '请填写有效的邮箱地址。'; return
  }
  if (editing.value && !etag.value) { formError.value = '未取得数据版本，请关闭后重试。'; return }
  if (editing.value && originalEmail.value && emailEditable.value && !email) {
    formError.value = '已有邮箱不能在此清空；可修改邮箱，其他联系方式在联系人菜单管理。'; return
  }
  const currentRequest = requestVersion
  saving.value = true
  formError.value = ''
  try {
    if (editing.value && etag.value) {
      const payload: ContactUpdateInput = { display_name: name }
      if (emailEditable.value && email && email !== originalEmail.value?.display_value) {
        const method = originalEmail.value
        payload.methods = [{
          method_type: 'EMAIL', raw_value: email,
          is_primary: method?.is_primary ?? true,
          is_preferred: method?.is_preferred ?? true,
          verification_status: 'UNVERIFIED',
        }]
      }
      await updateContact(editing.value.id, payload, etag.value)
    } else {
      await createContact({ customer_id: props.customerId, display_name: name,
        methods: [{ method_type: 'EMAIL', raw_value: email, is_primary: true, is_preferred: true }] })
    }
    if (currentRequest !== requestVersion) return
    visible.value = false
    ElMessage.success('联系人已保存。')
    emit('changed')
  } catch (error) {
    if (currentRequest === requestVersion) formError.value = message(error)
  } finally {
    saving.value = false
  }
}

watch(() => props.customerId, closeEditor)
onBeforeUnmount(() => { requestVersion += 1 })
</script>

<template>
  <section id="customer-contacts" class="customer-contacts-panel" aria-label="客户联系人">
    <header class="contacts-heading">
      <h3>联系人</h3>
      <ElButton v-if="canCreate" class="erp-button-motion" text type="primary" @click="add">新增</ElButton>
    </header>
    <div v-if="error" class="contacts-state is-error" role="alert">
      <span>{{ error }}</span><ElButton text type="primary" @click="emit('retry')">重试</ElButton>
    </div>
    <div v-else-if="loading" class="contacts-state" aria-live="polite">正在加载联系人…</div>
    <ul v-else-if="contactsInOrder.length" class="contacts-list">
      <li v-for="contact in contactsInOrder" :key="contact.id" class="contact-row">
        <div class="contact-values">
          <strong>{{ contact.display_name }}</strong>
          <div v-if="emails(contact).length" class="contact-emails">
            <template v-for="method in emails(contact)" :key="method.id">
              <a v-if="canReadEmail && method.display_value && !method.display_value.includes('*')" :href="`mailto:${method.display_value}`">{{ method.display_value }}</a>
              <span v-else>{{ method.display_value || method.masked_value || '—' }}</span>
            </template>
          </div>
          <span v-else class="contact-no-email">未填写邮箱</span>
        </div>
        <ElButton v-if="canEdit && contact.status !== 'LEFT'" text type="primary" :aria-label="`编辑联系人 ${contact.display_name}`" @click="edit(contact)">编辑</ElButton>
      </li>
    </ul>
    <p v-else class="contacts-state">暂无联系人</p>

    <AppWindowDialog v-model="visible" :title="editingId ? '编辑联系人' : '新增联系人'" :width="440" height="auto" destroy-on-close :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @closed="closeEditor">
      <ElForm v-loading="loadingDetail" label-position="top" class="customer-contact-form" @submit.prevent="save">
        <ElAlert v-if="formError" :title="formError" type="error" :closable="false" show-icon />
        <ElFormItem label="名称" required><ElInput v-model="form.name" maxlength="150" :disabled="saving || loadingDetail" aria-label="联系人名称" /></ElFormItem>
        <ElFormItem label="邮箱" :required="!editingId">
          <ElInput v-model="form.email" type="email" maxlength="255" :disabled="saving || loadingDetail || !emailEditable" :placeholder="emailHidden ? '邮箱已脱敏，当前账号不可修改' : '填写邮箱'" aria-label="联系人邮箱" />
        </ElFormItem>
        <p v-if="editing && emails(editing).length > 1" class="contact-form-note">这里修改上方显示的邮箱，其他邮箱继续保留。</p>
      </ElForm>
      <template #footer>
        <ElButton class="erp-button-motion" :disabled="saving" @click="closeEditor">取消</ElButton>
        <ElButton class="erp-button-motion" type="primary" :loading="saving" :disabled="loadingDetail || Boolean(editingId && (!editing || !etag))" @click="save">保存</ElButton>
      </template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.customer-contacts-panel { border-top: 1px solid var(--erp-color-border); padding-top: 12px; min-width: 0; }
.contacts-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.contacts-heading h3 { margin: 0; font-size: 13px; line-height: 20px; font-weight: 600; }
.contacts-heading :deep(.el-button), .contact-row :deep(.el-button) { height: 32px; margin: 0; flex: none; }
.contacts-list { list-style: none; margin: 0; padding: 0; }
.contact-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 0; }
.contact-row + .contact-row { border-top: 1px solid var(--erp-color-border); }
.contact-values, .contact-emails { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
.contact-values strong { font-size: 13px; line-height: 20px; font-weight: 600; overflow-wrap: anywhere; }
.contact-emails a, .contact-emails span, .contact-no-email { font-size: 13px; line-height: 20px; overflow-wrap: anywhere; color: var(--erp-color-text-secondary); }
.contact-emails a { color: var(--erp-color-brand); text-decoration: none; }
.contact-emails a:hover { text-decoration: underline; }
.contacts-state { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; font-size: 13px; line-height: 20px; color: var(--erp-color-text-secondary); }
.contacts-state.is-error { color: var(--erp-color-danger); }
.customer-contact-form :deep(.el-alert) { margin-bottom: 12px; }
.contact-form-note { margin: 0; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
</style>
