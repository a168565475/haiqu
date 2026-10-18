<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { checkCustomerDuplicates, createCustomer, fetchCustomerOptions } from '@/api/customers'
import { useAuthStore } from '@/stores/auth'
import type { CustomerDuplicateMatch, CustomerOptions } from '@/types/customer'
import {
  buildCustomerCreatePayload, createEmptyCustomerForm, customerRequestError, getDerivedCountryCode,
  getSecondaryRegions, validateCustomerCreateForm, type CustomerFormErrors,
} from './customerForm'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [customerId: string, continueCreating: boolean]
  openExisting: [customerId: string]
  cancelled: []
}>()
const authStore = useAuthStore()
const canCreate = computed(() => authStore.hasPermission('customers.add_customeraccount'))
const form = reactive(createEmptyCustomerForm())
const options = ref<CustomerOptions | null>(null)
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const checkingDuplicate = ref(false)
const duplicateError = ref('')
const duplicateMatches = ref<CustomerDuplicateMatch[]>([])
const fieldErrors = reactive<CustomerFormErrors>({})
const workspace = ref<HTMLElement | null>(null)
const initialForm = ref(JSON.stringify(form))
const isDirty = computed(() => JSON.stringify(form) !== initialForm.value)
let duplicateTimer: ReturnType<typeof setTimeout> | undefined
let duplicateSequence = 0
let optionsSequence = 0
let pendingClose: Promise<boolean> | null = null
const secondaryRegions = computed(() => getSecondaryRegions(options.value, form.primaryRegionId))
const countryCode = computed(() => getDerivedCountryCode(options.value, form.secondaryRegionId))
const highRiskMatches = computed(() => duplicateMatches.value.filter(item => item.match_level === 'HIGH'))
const canCheckDuplicate = computed(() => form.accountName.trim().length >= 2 || form.website.trim().length >= 4)

async function loadOptions() {
  const sequence = ++optionsSequence
  loading.value = true
  loadError.value = ''
  try {
    const result = await fetchCustomerOptions()
    if (sequence === optionsSequence) options.value = result
  } catch (error) {
    if (sequence === optionsSequence) loadError.value = customerRequestError(error, '客户建档选项加载失败。')
  } finally {
    if (sequence === optionsSequence) loading.value = false
  }
}
function clearFieldErrors() {
  for (const key of Object.keys(fieldErrors) as Array<keyof CustomerFormErrors>) delete fieldErrors[key]
}
function stopDuplicateCheck() {
  if (duplicateTimer) clearTimeout(duplicateTimer)
  duplicateTimer = undefined
  duplicateSequence += 1
  checkingDuplicate.value = false
}
function resetForm() {
  stopDuplicateCheck()
  Object.assign(form, createEmptyCustomerForm())
  initialForm.value = JSON.stringify(form)
  clearFieldErrors()
  duplicateMatches.value = []
  duplicateError.value = ''
}
async function runDuplicateCheck() {
  const sequence = ++duplicateSequence
  if (!props.modelValue || !canCheckDuplicate.value) {
    duplicateMatches.value = []
    duplicateError.value = ''
    return
  }
  checkingDuplicate.value = true
  duplicateError.value = ''
  try {
    const query = form.accountName.trim()
      ? { name: form.accountName.trim(), website: form.website.trim() || undefined }
      : { website: form.website.trim() }
    const result = await checkCustomerDuplicates({ ...query, country_code: countryCode.value || undefined })
    if (sequence === duplicateSequence) duplicateMatches.value = result.matches
  } catch (error) {
    if (sequence === duplicateSequence) {
      duplicateMatches.value = []
      duplicateError.value = customerRequestError(error, '重复客户检查失败，请稍后重试。')
    }
  } finally {
    if (sequence === duplicateSequence) checkingDuplicate.value = false
  }
}
function scheduleDuplicateCheck() {
  stopDuplicateCheck()
  if (props.modelValue) duplicateTimer = setTimeout(() => void runDuplicateCheck(), 400)
}
async function confirmDiscard(): Promise<boolean> {
  if (!props.modelValue) return true
  if (saving.value) return false
  if (!isDirty.value) return true
  if (pendingClose) return pendingClose
  pendingClose = (async () => {
    try {
      await ElMessageBox.confirm('填写内容尚未保存，确定关闭？', '关闭新建客户', {
        confirmButtonText: '放弃修改', cancelButtonText: '继续填写', type: 'warning',
      })
      initialForm.value = JSON.stringify(form)
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
function requestClose() { void beforeClose(() => handleWindowVisibility(false)) }
async function openExistingCustomer(customerId: string) {
  if (!await confirmDiscard()) return
  emit('update:modelValue', false)
  emit('openExisting', customerId)
}
async function submitCreate(continueCreating = false) {
  if (saving.value || !canCreate.value) return
  clearFieldErrors()
  const errors = validateCustomerCreateForm(form)
  Object.assign(fieldErrors, errors)
  if (Object.keys(errors).length) {
    ElMessage.warning('请检查标记的客户资料。')
    await nextTick()
    workspace.value?.querySelector<HTMLElement>(`[data-field="${Object.keys(errors)[0]}"] input`)?.focus()
    return
  }
  saving.value = true
  try {
    const created = await createCustomer(buildCustomerCreatePayload(form, options.value))
    initialForm.value = JSON.stringify(form)
    saving.value = false
    ElMessage.success('客户已创建。')
    if (continueCreating) {
      resetForm()
      workspace.value?.closest<HTMLElement>('.app-window-dialog__body')?.scrollTo({ top: 0, behavior: 'smooth' })
    } else emit('update:modelValue', false)
    emit('created', created.data.id, continueCreating)
  } catch (error) {
    ElMessage.error(customerRequestError(error, '客户创建失败，请检查资料后重试。'))
  } finally { saving.value = false }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (props.modelValue && (isDirty.value || saving.value)) { event.preventDefault(); event.returnValue = '' }
}
watch(() => props.modelValue, visible => {
  if (!visible) { stopDuplicateCheck(); optionsSequence += 1; return }
  resetForm()
  if (canCreate.value) void loadOptions()
  else loading.value = false
}, { immediate: true })
watch(() => [form.accountName, form.website, form.secondaryRegionId], scheduleDuplicateCheck)
watch(() => form.primaryRegionId, (current, previous) => { if (previous && current !== previous) form.secondaryRegionId = '' })
watch(form, clearFieldErrors, { deep: true })
onBeforeRouteLeave(confirmDiscard)
onBeforeRouteUpdate(confirmDiscard)
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => { stopDuplicateCheck(); optionsSequence += 1; window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" class="customer-create-dialog" title="新建客户"
    :width="920" :height="620" :minimizable="false" :close-on-click-modal="false"
    :before-close="beforeClose" destroy-on-close @update:model-value="handleWindowVisibility">
    <section v-if="!canCreate" class="create-page-state"><ElResult icon="warning" title="无权新建客户" sub-title="当前账号缺少新建客户权限，请联系管理员。" /></section>
    <section v-else-if="loading" class="create-page-state" aria-busy="true"><ElSkeleton :rows="10" animated /></section>
    <section v-else-if="loadError" class="create-page-state"><ElResult icon="error" title="无法打开新建客户" :sub-title="loadError"><template #extra><ElButton class="erp-button-motion" type="primary" @click="loadOptions">重新加载</ElButton></template></ElResult></section>
    <section v-else ref="workspace" class="create-workspace" data-customer-create-page>
      <ElForm label-position="top" class="create-form" :model="form" :disabled="saving" @submit.prevent>
        <div class="section-heading"><strong>客户基础资料</strong><span>{{ checkingDuplicate ? '正在自动查重' : '输入客户名称或网站后自动查重' }}</span></div>
        <div class="create-form-grid">
          <ElFormItem label="客户名称" required :error="fieldErrors.accountName" data-field="accountName"><ElInput v-model="form.accountName" maxlength="250" placeholder="输入公司或客户名称" /></ElFormItem>
          <ElFormItem label="网站 / 域名" :error="fieldErrors.website" data-field="website"><ElInput v-model="form.website" maxlength="500" placeholder="例如 example.com" /></ElFormItem>
          <ElFormItem label="一级地区" required :error="fieldErrors.primaryRegionId" data-field="primaryRegionId"><ElSelect v-model="form.primaryRegionId" filterable placeholder="请选择一级地区"><ElOption v-for="item in options?.primary_regions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem>
          <ElFormItem label="二级地区" data-field="secondaryRegionId"><ElSelect v-model="form.secondaryRegionId" filterable clearable :disabled="!form.primaryRegionId" placeholder="可不填写"><ElOption v-for="item in secondaryRegions" :key="item.id" :label="item.region_name" :value="item.id" /></ElSelect></ElFormItem>
          <ElFormItem label="客户来源" required :error="fieldErrors.sourceId" data-field="sourceId"><ElSelect v-model="form.sourceId" filterable placeholder="请选择客户来源"><ElOption v-for="item in options?.customer_sources" :key="item.id" :label="item.display_name" :value="item.id" :disabled="item.disabled" /></ElSelect></ElFormItem>
          <ElFormItem label="国家代码" data-field="countryCode"><ElInput :model-value="countryCode ? `${countryCode} · 由二级地区自动带出` : '由二级地区自动带出'" disabled /></ElFormItem>
        </div>
        <ElAlert v-if="highRiskMatches.length" class="duplicate-alert" type="warning" :closable="false" show-icon :title="`当前输入触发 ${highRiskMatches.length} 条高匹配记录，请确认是否为已有客户。`" />
        <ElAlert v-else-if="duplicateError" class="duplicate-alert" type="error" :closable="false" show-icon :title="duplicateError" />
        <div class="section-heading contact-heading"><strong>初始联系人</strong><span>可选 · 填写邮箱时必须同时填写姓名</span></div>
        <div class="create-form-grid contact-grid">
          <ElFormItem label="联系人姓名" :error="fieldErrors.contactName" data-field="contactName"><ElInput v-model="form.contactName" maxlength="150" placeholder="可稍后补充" /></ElFormItem>
          <ElFormItem label="邮箱" :error="fieldErrors.contactMethod" data-field="contactMethod"><ElInput v-model="form.contactMethod" type="email" maxlength="255" placeholder="输入联系人邮箱" /></ElFormItem>
        </div>
        <p class="completion-hint">创建后可在客户详情继续完善主体、地址、客户类型、等级与标签。</p>
      </ElForm>
      <aside class="create-context" aria-label="重复检查与创建说明">
        <section class="context-card duplicate-card" :aria-busy="checkingDuplicate">
          <template v-if="duplicateMatches.length">
            <header><strong>发现 {{ duplicateMatches.length }} 个匹配客户</strong></header>
            <p>客户名称或网站与已有记录相似，请先确认是否为同一客户。</p>
            <article v-for="match in duplicateMatches.slice(0, 3)" :key="match.customer_id" class="duplicate-match">
              <strong>{{ match.account_name }}</strong><span>{{ match.account_code }} · {{ match.primary_country_code || '国家未知' }} · {{ match.lifecycle_stage }}</span>
              <small>{{ match.primary_website_url || '未登记网站' }}</small>
              <div><ElButton class="erp-button-motion" type="primary" :disabled="saving" @click="openExistingCustomer(match.customer_id)">选择已有客户</ElButton><ElButton class="erp-button-motion" :disabled="saving" @click="openExistingCustomer(match.customer_id)">查看详情</ElButton></div>
            </article>
          </template>
          <template v-else><strong>实时重复校验</strong><p v-if="checkingDuplicate">正在检查客户名称、网站和国家信息…</p><p v-else-if="duplicateError">{{ duplicateError }}</p><p v-else>输入客户名称或网站后，系统会在这里显示真实匹配结果。</p></template>
        </section>
        <section class="context-card"><strong>创建规则</strong><p>客户名称、一级地区、客户来源为必填。填写邮箱时必须同时填写联系人姓名。</p><p>创建后建立客户主档与编号，记录来源、负责人及初始活跃度。</p></section>
      </aside>
    </section>
    <template #footer>
      <ElButton class="erp-button-motion" :disabled="saving" @click="requestClose">取消</ElButton>
      <ElButton class="erp-button-motion" :loading="saving" :disabled="loading || Boolean(loadError) || !canCreate" @click="submitCreate(true)">继续创建</ElButton>
      <ElButton class="erp-button-motion" type="primary" :loading="saving" :disabled="loading || Boolean(loadError) || !canCreate" @click="submitCreate(false)">创建客户</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use './customer-form-shared' as shared;
.create-page-state { padding: 16px; }
.create-workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 32%); gap: 20px; min-width: 0; color: var(--erp-color-text-primary); }
.create-form { min-width: 0; @include shared.element-form-controls(32px, 12px, 13px, 7px); }
.create-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.section-heading strong { font-size: 16px; font-weight: 600; }
.section-heading span, .completion-hint { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.contact-heading { margin-top: 20px; }
.completion-hint { margin: 16px 0 0; }
.duplicate-alert { margin-top: 20px; }
.create-context { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.context-card { padding: 16px; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); background: var(--erp-color-subtle); font-size: 13px; }
.context-card p { margin: 10px 0 0; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.duplicate-match { display: flex; flex-direction: column; gap: 6px; padding-top: 14px; margin-top: 14px; border-top: 1px solid var(--erp-color-border); overflow-wrap: anywhere; }
.duplicate-match span, .duplicate-match small { color: var(--erp-color-text-secondary); font-size: 12px; }
.duplicate-match > div { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
@media (max-width: 900px) { .create-workspace { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 600px) { .create-form-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
