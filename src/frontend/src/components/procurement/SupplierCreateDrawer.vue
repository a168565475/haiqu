<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { createSupplier, fetchSupplier, fetchSupplierOptions, updateSupplier } from '@/api/suppliers'
import { useAuthStore } from '@/stores/auth'
import type { Supplier, SupplierInput, SupplierOptions } from '@/types/supplier'

const props = defineProps<{ visible: boolean; supplierId?: string }>()
const emit = defineEmits<{ 'update:visible': [value: boolean]; created: [] }>()
const auth = useAuthStore()
const isEditing = computed(() => Boolean(props.supplierId))
const title = computed(() => isEditing.value ? '编辑供应商' : '新建供应商')
const canCreate = computed(() => auth.user?.is_superuser === true || (auth.hasPermission('procurement.view_supplier') && auth.hasPermission(isEditing.value ? 'procurement.change_supplier' : 'procurement.add_supplier')))
const supplier = ref<Supplier | null>(null)
const editTargetId = ref('')
const etag = ref('')
const versionConflict = ref(false)
const emptyForm = (): SupplierInput => ({ supplier_type: 'MATERIAL', supplier_categories: [], supplier_name: '', payment_cycle: '', phone: '', is_disabled: false, remark: '' })
const form = reactive<SupplierInput>(emptyForm())
const formRef = ref<FormInstance>()
const options = ref<SupplierOptions>({ supplier_types: [], supplier_categories: [], payment_cycles: [], next_supplier_number: '' })
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const saveError = ref('')
const closing = ref(false)
const baseline = ref(JSON.stringify(emptyForm()))
const dirty = computed(() => JSON.stringify(form) !== baseline.value)
let loadVersion = 0
let disposed = false
let confirmingClose = false

const rules: FormRules<SupplierInput> = {
  supplier_type: [{ required: true, message: '请选择供应商类型', trigger: 'change' }],
  supplier_categories: [{ type: 'array', required: true, min: 1, message: '请至少选择一个供应商类别', trigger: 'change' }],
  supplier_name: [
    { required: true, whitespace: true, message: '请输入供应商名称', trigger: 'blur' },
    { max: 255, message: '供应商名称不能超过255个字符', trigger: 'blur' },
  ],
  phone: [{ validator: (_rule, value: string, callback) => {
    const phone = value.trim()
    if (!phone || (phone.length >= 3 && phone.length <= 100 && /^(?=.*\d)[0-9+\-()（）\s#.,，、/:：转分机extEXT]+$/.test(phone))) callback()
    else callback(new Error('联系电话格式不正确'))
  }, trigger: 'blur' }],
  remark: [{ max: 2000, message: '备注不能超过2000个字符', trigger: 'blur' }],
}

function errorMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response?.data
  return Object.values(data?.error?.field_errors || {}).flat()[0] || data?.error?.message || data?.detail || fallback
}

async function loadOptions(): Promise<void> {
  const version = ++loadVersion
  const id = editTargetId.value
  loading.value = true
  loadError.value = ''
  etag.value = ''
  try {
    const [result, detail] = await Promise.all([fetchSupplierOptions(), isEditing.value ? fetchSupplier(id) : Promise.resolve(null)])
    if (disposed || version !== loadVersion || !props.visible) return
    if (!result || ![result.supplier_types, result.supplier_categories, result.payment_cycles].every(Array.isArray)
      || !result.supplier_types.length || !result.supplier_categories.length || (!isEditing.value && !result.next_supplier_number)) throw new Error('供应商选项不完整')
    if (isEditing.value) {
      if (!detail?.etag || !detail.data?.supplier_number || !Array.isArray(detail.data.supplier_categories)) throw new Error('供应商资料或版本信息不完整')
      supplier.value = detail.data
      etag.value = detail.etag
      Object.assign(form, {
        supplier_type: detail.data.supplier_type, supplier_categories: [...detail.data.supplier_categories],
        supplier_name: detail.data.supplier_name, payment_cycle: detail.data.payment_cycle || '',
        phone: detail.data.phone || '', remark: detail.data.remark || '', is_disabled: detail.data.is_disabled,
      })
      baseline.value = JSON.stringify(form)
    }
    options.value = result
    versionConflict.value = false
    saveError.value = ''
  } catch (error) {
    if (!disposed && version === loadVersion) loadError.value = errorMessage(error, isEditing.value ? '供应商资料或版本信息加载失败，请重试。' : '供应商选项加载失败，请重试。')
  } finally {
    if (!disposed && version === loadVersion) loading.value = false
  }
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replaceAll('/', '-')
}

async function reloadDetail(): Promise<void> {
  if (!await mayClose() || !props.visible || closing.value) return
  await loadOptions()
}

async function openDuplicate(id: string): Promise<void> {
  if (!id || id === editTargetId.value || loading.value || !await mayClose() || !props.visible || closing.value) return
  editTargetId.value = id
  supplier.value = null
  Object.assign(form, emptyForm())
  baseline.value = JSON.stringify(form)
  await loadOptions()
  await nextTick()
  formRef.value?.clearValidate()
}

async function mayClose(): Promise<boolean> {
  if (saving.value || confirmingClose) return false
  if (!dirty.value) return true
  confirmingClose = true
  try {
    await ElMessageBox.confirm('已填写的供应商资料尚未保存，关闭后将丢失。', '放弃未保存的修改？', {
      confirmButtonText: '放弃修改', cancelButtonText: '继续填写', type: 'warning', closeOnClickModal: false,
    })
    return !disposed && !saving.value
  } catch { return false }
  finally { confirmingClose = false }
}
function finishClose(): void { closing.value = true; emit('update:visible', false) }
async function close(): Promise<void> { if (await mayClose()) finishClose() }
async function beforeClose(done: () => void): Promise<void> { if (await mayClose()) { finishClose(); done() } }
async function beforeNavigation(): Promise<boolean> {
  if (!props.visible) return true
  if (!await mayClose()) return false
  finishClose()
  return true
}
onBeforeRouteLeave(beforeNavigation)
onBeforeRouteUpdate(beforeNavigation)
function preventUnload(event: BeforeUnloadEvent): void {
  if (props.visible && (dirty.value || saving.value)) { event.preventDefault(); event.returnValue = '' }
}
window.addEventListener('beforeunload', preventUnload)

async function save(): Promise<void> {
  if (!props.visible || closing.value || confirmingClose || !canCreate.value || loading.value || loadError.value || versionConflict.value || (isEditing.value && !etag.value) || saving.value || !formRef.value) return
  saving.value = true
  saveError.value = ''
  try {
    if (!await formRef.value.validate().catch(() => false)) return
    if (disposed || !props.visible || !canCreate.value) return
    const payload: SupplierInput = {
      supplier_type: form.supplier_type, supplier_categories: [...form.supplier_categories], supplier_name: form.supplier_name.trim(),
      payment_cycle: form.payment_cycle || '', phone: form.phone.trim(), is_disabled: form.is_disabled, remark: form.remark.trim(),
    }
    if (isEditing.value) await updateSupplier(editTargetId.value, payload, etag.value)
    else await createSupplier(payload)
    if (disposed) return
    ElMessage.success(isEditing.value ? '供应商资料已更新' : '供应商已创建')
    emit('update:visible', false)
    emit('created')
  } catch (error) {
    if (!disposed) {
      const status = (error as { response?: { status?: number } })?.response?.status
      versionConflict.value = isEditing.value && (status === 412 || status === 428)
      saveError.value = versionConflict.value ? '资料版本已变化或校验信息失效，已保留你的输入。请重新加载最新资料后再修改。' : errorMessage(error, '保存未成功确认，请核实后重试；已填写内容已保留。')
    }
  } finally { if (!disposed) saving.value = false }
}

watch(() => [props.visible, props.supplierId] as const, async ([visible]) => {
  ++loadVersion
  if (!visible) return
  closing.value = false
  Object.assign(form, emptyForm())
  baseline.value = JSON.stringify(form)
  supplier.value = null
  editTargetId.value = props.supplierId || ''
  etag.value = ''
  versionConflict.value = false
  options.value = { supplier_types: [], supplier_categories: [], payment_cycles: [], next_supplier_number: '' }
  saveError.value = ''
  await nextTick()
  formRef.value?.clearValidate()
  if (canCreate.value) void loadOptions()
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; ++loadVersion; window.removeEventListener('beforeunload', preventUnload) })
</script>

<template>
  <ElDrawer :model-value="visible" class="supplier-create-drawer" :class="{ 'supplier-edit-drawer': isEditing }" modal-class="supplier-create-overlay" :title="title"
    size="784px" direction="rtl" append-to-body :show-close="false" :close-on-click-modal="false" :close-on-press-escape="!saving"
    :before-close="beforeClose" @update:model-value="emit('update:visible', $event)">
    <template #header>
      <div class="supplier-drawer-heading"><h2>{{ title }}</h2><p>带 <span>*</span> 的字段为必填项</p></div>
      <ElButton text :icon="Close" :disabled="saving" :aria-label="`关闭${title}`" class="supplier-drawer-close" @click="close" />
    </template>
    <div v-if="isEditing" class="supplier-edit-records">
      <p>提交：{{ supplier?.submitted_by_name || '—' }} · {{ formatDateTime(supplier?.submitted_at) }}</p>
      <p>更新：{{ supplier?.updated_by_name || '—' }} · {{ formatDateTime(supplier?.updated_at) }}</p>
    </div>
    <div v-if="loadError || saveError" class="supplier-drawer-error" role="alert">
      {{ loadError || saveError }}<ElButton v-if="loadError || versionConflict" link :disabled="loading || saving" @click="reloadDetail">重新加载</ElButton>
    </div>
    <ElForm ref="formRef" v-loading="loading" :model="form" :rules="rules" :disabled="loading || saving || !!loadError || !canCreate"
      label-position="top" class="supplier-drawer-form" :aria-busy="loading || saving" @submit.prevent="save">
      <div class="supplier-drawer-row number-type-row">
        <ElFormItem :label="isEditing ? '供应商编号（不可修改）' : '供应商编号'"><ElInput :model-value="(isEditing ? supplier?.supplier_number : options.next_supplier_number) || '—'" readonly aria-label="供应商编号" class="supplier-number-preview" /></ElFormItem>
        <ElFormItem label="供应商类型" prop="supplier_type" required><ElSelect v-model="form.supplier_type" :aria-label="isEditing ? '编辑供应商类型' : '新建供应商类型'" placeholder="请选择供应商类型" popper-class="supplier-create-select"><ElOption v-for="item in options.supplier_types" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
      </div>
      <div class="supplier-drawer-row name-category-row">
        <ElFormItem label="供应商名称" prop="supplier_name" required class="supplier-name-field"><ElInput v-model="form.supplier_name" maxlength="255" placeholder="请输入供应商名称" /></ElFormItem>
        <ElFormItem prop="supplier_categories" required class="supplier-category-field">
          <template #label>供应商类别<span class="supplier-category-help">可多选，至少选择一个类别</span></template>
          <ElSelect v-model="form.supplier_categories" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="3" aria-label="供应商类别" placeholder="请选择供应商类别，可多选" popper-class="supplier-create-select"><ElOption v-for="item in options.supplier_categories" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        </ElFormItem>
      </div>
      <div class="supplier-drawer-row payment-phone-row">
        <ElFormItem label="付款周期" prop="payment_cycle"><ElSelect v-model="form.payment_cycle" clearable :aria-label="isEditing ? '编辑付款周期' : '新建付款周期'" placeholder="请选择付款周期" popper-class="supplier-create-select"><ElOption v-for="item in options.payment_cycles" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
        <ElFormItem label="联系电话" prop="phone"><ElInput v-model="form.phone" maxlength="100" placeholder="请输入联系电话" /></ElFormItem>
      </div>
      <ElFormItem label="是否禁用" prop="is_disabled" class="supplier-disabled-field"><ElSwitch v-model="form.is_disabled" inline-prompt active-text="是" inactive-text="否" aria-label="是否禁用" /></ElFormItem>
      <ElFormItem label="备注" prop="remark" class="supplier-remark-field"><ElInput v-model="form.remark" type="textarea" :rows="3" maxlength="2000" show-word-limit resize="none" placeholder="请输入备注信息" /></ElFormItem>
    </ElForm>
    <aside v-if="isEditing && supplier?.duplicate_suppliers?.length" class="supplier-duplicate-notice" aria-label="同名供应商提醒">
      <p>存在同名供应商，请核对编号后再修改：</p>
      <ElButton v-for="item in supplier.duplicate_suppliers" :key="item.id" link :disabled="saving || loading" @click="openDuplicate(item.id)">{{ item.supplier_number }} · {{ item.status_display }}</ElButton>
    </aside>
    <template #footer><ElButton :disabled="saving" @click="close">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="closing || loading || !!loadError || versionConflict || (isEditing && !etag) || !canCreate" @click="save">{{ isEditing ? '保存修改' : '创建供应商' }}</ElButton></template>
  </ElDrawer>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.supplier-create-overlay { background: rgb(0 0 0 / 32%); }
.supplier-create-drawer {
  top: 0 !important; height: 100% !important; max-width: 100vw; background: token.$crm-color-surface; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary}; --el-text-color-placeholder: #{token.$crm-text-muted};
  .el-drawer__header { flex: 0 0 52px; box-sizing: border-box; padding: 10px 24px; margin: 0; align-items: center; border-bottom: 1px solid token.$crm-border-default; color: inherit; }
  .supplier-drawer-heading { display: flex; min-width: 0; align-items: baseline; gap: 16px; }
  .supplier-drawer-heading h2 { margin: 0; font: 600 22px/28px token.$crm-font-display; }
  .supplier-drawer-heading p { margin: 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; white-space: nowrap; }
  .supplier-drawer-heading p span { color: token.$crm-primary; }
  .supplier-drawer-close.el-button { width: 32px; height: 32px; padding: 0; font-size: 18px; color: token.$crm-text-secondary; }
  .el-drawer__body { padding: 16px 24px 20px; overflow-y: auto; }
  .supplier-drawer-form { margin-top: 0; }
  .supplier-drawer-row { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; }
  .el-form-item { margin: 0; }
  .el-form-item__label { height: 20px; margin-bottom: 4px; padding: 0; color: token.$crm-text-primary; font-size: 13px; line-height: 20px; }
  .el-form-item.is-required > .el-form-item__label::before { color: token.$crm-primary !important; }
  .el-input, .el-select { width: 100%; }
  .el-input__wrapper, .el-select__wrapper { height: 32px; min-height: 32px; padding: 0 12px; border-radius: 5px; box-shadow: 0 0 0 1px token.$crm-border-default inset; background: token.$crm-color-surface; font-size: 13px; }
  .el-input__inner { height: 30px; font: 13px token.$crm-font-body; }
  .supplier-number-preview .el-input__wrapper { background: token.$crm-color-subtle; }
  .supplier-number-preview .el-input__inner { color: token.$crm-text-muted; }
  .name-category-row, .payment-phone-row, .supplier-disabled-field, .supplier-remark-field { margin-top: 12px; }
  .supplier-category-help { margin-left: 12px; color: token.$crm-text-secondary; font-weight: 400; }
  .supplier-category-field { min-height: 0; }
  .supplier-category-field .el-tag { height: 22px !important; min-height: 22px !important; font-size: 12px; }
  .supplier-disabled-field .el-switch { width: 52px; height: 32px; --el-switch-on-color: #{token.$crm-primary}; --el-switch-off-color: #{token.$crm-neutral}; }
  .supplier-disabled-field .el-switch__core { min-width: 52px; border-color: transparent; }
  .supplier-disabled-field .el-switch__inner { font-size: 12px; }
  .el-textarea__inner { height: 84px; padding: 8px 12px 22px; font: 13px/20px token.$crm-font-body; box-shadow: 0 0 0 1px token.$crm-border-default inset; border-radius: 5px; background: token.$crm-color-surface; }
  .el-input__count { bottom: 4px; right: 12px; font-size: 11px; background: token.$crm-color-surface; color: token.$crm-text-muted; }
  .el-drawer__footer { flex: 0 0 64px; box-sizing: border-box; padding: 0 24px; display: flex; align-items: center; justify-content: flex-end; gap: 12px; border-top: 1px solid token.$crm-border-default; }
  .el-drawer__footer .el-button { margin: 0; width: 110px; height: 32px; border-radius: 5px; font: 500 13px token.$crm-font-body; }
  .el-drawer__footer .el-button--primary { width: 140px; }
  .supplier-drawer-error { color: token.$crm-danger; margin-top: 16px; overflow-wrap: anywhere; }
  .supplier-drawer-error .el-button { margin-left: 10px; color: token.$crm-primary; }
  &.supplier-edit-drawer {
    .el-drawer__header { flex-basis: 52px; }
    .el-drawer__body { padding-bottom: 20px; }
    .supplier-drawer-form { margin-top: 12px; }
  }
  .supplier-edit-records { box-sizing: border-box; min-height: 48px; padding: 4px 12px; border-radius: 5px; background: token.$crm-color-subtle; color: token.$crm-text-secondary; }
  .supplier-edit-records p { margin: 0; overflow-wrap: anywhere; }
  .supplier-edit-records p + p { margin-top: 4px; }
  .supplier-duplicate-notice { margin-top: 24px; padding: 12px 20px; border-radius: 4px; background: token.$crm-color-subtle; }
  .supplier-duplicate-notice p { margin: 0 0 8px; }
  .supplier-duplicate-notice .el-button { display: flex; margin: 4px 0; height: auto; white-space: normal; color: token.$crm-primary; }
}
.supplier-create-select { --el-color-primary: #{token.$crm-primary}; --el-bg-color-overlay: #{token.$crm-color-surface}; font: 13px/20px token.$crm-font-body; }
</style>
