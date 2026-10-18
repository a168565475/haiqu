<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Close, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { createPurchaseContractTemplate, fetchPurchaseContractTemplate, updatePurchaseContractTemplate } from '@/api/purchaseOrders'
import { useAuthStore } from '@/stores/auth'
import type { PurchaseContractTemplate } from '@/types/purchaseOrder'

const props = defineProps<{ visible: boolean; templateId?: string }>()
const emit = defineEmits<{ 'update:visible': [value: boolean]; created: [] }>()
const auth = useAuthStore()
const isEditing = computed(() => Boolean(props.templateId))
const drawerTitle = computed(() => isEditing.value ? '编辑采购合同模板' : '新建采购合同模板')
const record = ref<PurchaseContractTemplate | null>(null)
const etag = ref('')
const loading = ref(false)
const loadError = ref('')
const versionConflict = ref(false)
const originalConfig = ref<Record<string, unknown>>({})
const currentVersion = computed(() => record.value?.current_version?.version_number ?? null)
const nextVersion = computed(() => currentVersion.value === null ? '—' : currentVersion.value + 1)
let loadSequence = 0
const canCreate = computed(() => Boolean(auth.user?.is_superuser || auth.moduleCan(props.templateId ? 'procurement.change_purchasecontracttemplate' : 'procurement.add_purchasecontracttemplate', 'procurement.view_purchaseorder')))
const emptyForm = () => ({
  templateName: '',
  versionName: '初始版',
  categories: [] as string[],
  status: 'ACTIVE' as 'ACTIVE' | 'INACTIVE',
  title: '采购合同',
  settlementMode: 'NORMAL' as 'NORMAL' | 'ACTUAL_WEIGHT',
  taxRate: '13',
  freightBearer: '乙方',
  paymentAndDelivery: '乙方应在{{采购交期}}前将货物送达甲方指定地点；付款方式以双方最终确认内容为准。',
  qualityStandards: '乙方供应的产品应符合双方确认的规格、样品及质量要求，不得侵犯第三方知识产权。\n产品材质、尺寸、颜色、外观和单位应与确认样或双方书面确认内容一致；不合格品由乙方负责退换并承担相关费用。',
  deliveryHandover: '乙方送货至甲方指定地点，送货前通知甲方采购人员验收；验收不合格时，甲方有权拒收或要求退换。',
  specialInstructions: '价格及技术要求以本采购表和双方书面确认内容为准；未经甲方书面确认，不得擅自变更。',
  disputeResolution: '履行过程中发生争议，双方应先友好协商；协商不成，向甲方所在地有管辖权的人民法院起诉。',
  effectiveness: '本采购表一式两份，甲乙双方各执一份，自双方签字或盖章之日起生效；扫描件、电子邮件确认件具有同等效力。',
  changeSummary: '',
})
const categories = [
  { value: 'TUBE', label: '管材' }, { value: 'HARDWARE', label: '五金' },
  { value: 'PLASTIC_PART', label: '塑料件' }, { value: 'PACKAGING', label: '包材' },
  { value: 'FABRIC', label: '面料' }, { value: 'AUXILIARY', label: '辅料' },
  { value: 'FINISHED_GOODS', label: '成品' },
]
const form = reactive(emptyForm())
const formRef = ref<FormInstance>()
const saving = ref(false)
const savingMode = ref<'CURRENT' | 'NEW_VERSION'>('NEW_VERSION')
const saveError = ref('')
const closing = ref(false)
const baseline = ref(JSON.stringify(form))
const dirty = computed(() => JSON.stringify(form) !== baseline.value)
const saveDisabled = computed(() => closing.value || loading.value || !!loadError.value || versionConflict.value || !canCreate.value || (isEditing.value && !etag.value))
let disposed = false
let confirmingClose = false
const rules: FormRules = {
  templateName: [{ required: true, whitespace: true, message: '请输入模板名称', trigger: 'blur' }, { max: 150, message: '模板名称不能超过150个字符', trigger: 'blur' }],
  versionName: [{ required: true, whitespace: true, message: '请输入版本名称', trigger: 'blur' }, { max: 150, message: '版本名称不能超过150个字符', trigger: 'blur' }],
  changeSummary: [{ required: true, whitespace: true, message: '请输入本次变更内容', trigger: 'blur' }, { max: 500, message: '变更内容不能超过500个字符', trigger: 'blur' }],
  taxRate: [{ validator: (_rule, value: string, callback) => {
    if (value.trim() && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 100) callback()
    else callback(new Error('税率须为0至100之间的数字'))
  }, trigger: 'blur' }],
}
function errorMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response?.data
  return Object.values(data?.error?.field_errors || {}).flat()[0] || data?.error?.message || data?.detail || fallback
}
function formatDateTime(value?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
async function loadDetail(): Promise<void> {
  const sequence = ++loadSequence
  const id = props.templateId
  if (!id || !canCreate.value) return
  loading.value = true
  loadError.value = ''
  etag.value = ''
  try {
    const result = await fetchPurchaseContractTemplate(id)
    if (disposed || sequence !== loadSequence || !props.visible || closing.value) return
    const data = result.data
    const version = data?.current_version
    const config = version?.content_config
    if (!result.etag || data?.id !== id || !version || !Number.isInteger(version.version_number) || version.version_number < 1
      || !config || typeof config !== 'object' || Array.isArray(config) || !Array.isArray(data.supplier_categories)
      || !['ACTIVE', 'INACTIVE'].includes(data.status) || typeof data.template_name !== 'string') throw new Error('模板资料或版本校验信息不完整')
    const defaults = emptyForm()
    const legacyTerms = Array.isArray(config.terms) ? config.terms.map(String) : []
    Object.assign(form, {
      templateName: data.template_name, versionName: version.version_name ?? '', categories: [...data.supplier_categories], status: data.status,
      title: String(config.title ?? defaults.title), settlementMode: config.settlement_mode === 'ACTUAL_WEIGHT' ? 'ACTUAL_WEIGHT' : 'NORMAL',
      taxRate: String(config.tax_rate ?? defaults.taxRate), freightBearer: String(config.freight_bearer ?? defaults.freightBearer),
      paymentAndDelivery: String(config.payment_and_delivery ?? defaults.paymentAndDelivery),
      qualityStandards: Array.isArray(config.quality_standards) ? config.quality_standards.map(String).join('\n') : legacyTerms.length ? legacyTerms.slice(0, 2).join('\n') : defaults.qualityStandards,
      deliveryHandover: String(config.delivery_handover ?? defaults.deliveryHandover), specialInstructions: String(config.special_instructions ?? defaults.specialInstructions),
      disputeResolution: String(config.dispute_resolution ?? defaults.disputeResolution), effectiveness: String(config.effectiveness ?? defaults.effectiveness), changeSummary: '',
    })
    record.value = data
    originalConfig.value = config
    etag.value = result.etag
    baseline.value = JSON.stringify(form)
    versionConflict.value = false
    saveError.value = ''
    await nextTick()
    formRef.value?.clearValidate()
  } catch (error) {
    if (!disposed && sequence === loadSequence) loadError.value = errorMessage(error, '模板资料或版本校验信息加载失败，请重试。')
  } finally { if (!disposed && sequence === loadSequence) loading.value = false }
}
async function reloadDetail(): Promise<void> {
  if (loading.value || !await mayClose() || !props.visible || closing.value) return
  await loadDetail()
}
async function mayClose(): Promise<boolean> {
  if (saving.value || confirmingClose) return false
  if (!dirty.value) return true
  confirmingClose = true
  try {
    await ElMessageBox.confirm('已填写的模板内容尚未保存，关闭后将丢失。', '放弃未保存的修改？', {
      confirmButtonText: '放弃修改', cancelButtonText: '继续填写', type: 'warning', closeOnClickModal: false,
    })
    return !disposed && !saving.value
  } catch { return false }
  finally { confirmingClose = false }
}
function finishClose(): void { closing.value = true; ++loadSequence; emit('update:visible', false) }
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
function insertDeliveryVariable(): void {
  if (saving.value || saveDisabled.value) return
  if (form.paymentAndDelivery.includes('{{采购交期}}')) { ElMessage.info('已包含采购交期变量'); return }
  form.paymentAndDelivery += '{{采购交期}}'
}
async function save(mode: 'CURRENT' | 'NEW_VERSION' = 'NEW_VERSION'): Promise<void> {
  if (!props.visible || closing.value || confirmingClose || saveDisabled.value || saving.value || !formRef.value) return
  saving.value = true
  savingMode.value = mode
  saveError.value = ''
  try {
    if (!await formRef.value.validate().catch(() => false)) return
    if (disposed || !props.visible || !canCreate.value) return
    const payload = {
      template_name: form.templateName.trim(), version_name: form.versionName.trim(), supplier_categories: [...form.categories],
      status: form.status, change_summary: form.changeSummary.trim(),
      content_config: {
        ...originalConfig.value,
        title: form.title.trim(), buyer: isEditing.value ? originalConfig.value.buyer : { name: '浙江嗨趣休闲用品有限公司', address: '', contact: '', phone: '' },
        settlement_mode: form.settlementMode, tax_rate: form.taxRate.trim(), freight_bearer: form.freightBearer, show_image: isEditing.value ? originalConfig.value.show_image : true,
        payment_and_delivery: form.paymentAndDelivery.trim(),
        quality_standards: form.qualityStandards.split(/\r?\n/).map(item => item.trim()).filter(Boolean),
        delivery_handover: form.deliveryHandover.trim(), special_instructions: form.specialInstructions.trim(),
        dispute_resolution: form.disputeResolution.trim(), effectiveness: form.effectiveness.trim(),
      },
    }
    const result = isEditing.value
      ? await updatePurchaseContractTemplate(props.templateId!, { ...payload, save_mode: mode }, etag.value)
      : await createPurchaseContractTemplate(payload)
    if (disposed) return
    if (!result?.id) throw new Error('保存结果不完整')
    ElMessage.success(isEditing.value ? (mode === 'CURRENT' ? '当前模板已保存。' : '模板新版本已保存。') : '采购模板已创建。')
    finishClose()
    emit('created')
  } catch (error) {
    if (!disposed) {
      const status = (error as { response?: { status?: number } })?.response?.status
      versionConflict.value = isEditing.value && (status === 412 || status === 428)
      saveError.value = versionConflict.value ? '模板已被其他人修改或版本校验信息失效，已保留你的输入。请重新加载最新模板后再修改。' : errorMessage(error, '保存未成功确认，请核实后重试；已填写内容已保留。')
    }
  } finally { if (!disposed) saving.value = false }
}
watch(() => [props.visible, props.templateId] as const, async ([visible]) => {
  ++loadSequence
  if (!visible) return
  closing.value = false
  loading.value = false
  loadError.value = ''
  record.value = null
  originalConfig.value = {}
  etag.value = ''
  versionConflict.value = false
  Object.assign(form, emptyForm())
  baseline.value = JSON.stringify(form)
  saveError.value = ''
  await nextTick()
  formRef.value?.clearValidate()
  if (isEditing.value) void loadDetail()
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; ++loadSequence; window.removeEventListener('beforeunload', preventUnload) })
</script>

<template>
  <AppWindowDialog :model-value="visible" class="purchase-template-create-drawer" :class="{ 'purchase-template-edit-drawer': isEditing }" modal-class="purchase-template-create-overlay" :title="drawerTitle"
    :width="1360" :show-close="false" :close-on-click-modal="false" :close-on-press-escape="!saving"
    :before-close="beforeClose" @update:model-value="emit('update:visible', $event)">
    <template #header>
      <div class="template-create-heading"><h2>{{ drawerTitle }}</h2><p v-if="isEditing">当前版本 {{ currentVersion === null ? '—' : `V${currentVersion}` }} · 最近更新：{{ record?.updated_by_name || '—' }} · {{ formatDateTime(record?.updated_at) }}</p><p v-else>设置模板信息和合同条款，创建后可在采购表中选用。</p></div>
      <ElButton text :icon="Close" :disabled="saving" :aria-label="`关闭${drawerTitle}`" class="template-create-close" @click="close" />
    </template>
    <div v-if="loadError || saveError" class="template-create-error" role="alert">{{ loadError || saveError }}<ElButton v-if="loadError || versionConflict" link :disabled="loading || saving" @click="reloadDetail">重新加载</ElButton></div>
    <ElForm ref="formRef" v-loading="loading" :model="form" :rules="rules" :disabled="saving || saveDisabled" label-position="top" require-asterisk-position="right"
      class="template-create-form" :aria-busy="saving || loading" @submit.prevent="save()">
      <section class="template-basic-settings">
        <h3>基本设置</h3><div class="template-basic-fields">
          <ElFormItem label="模板名称" prop="templateName"><ElInput v-model="form.templateName" aria-label="模板名称" maxlength="150" placeholder="请输入模板名称" /></ElFormItem>
          <ElFormItem label="版本名称" prop="versionName"><ElInput v-model="form.versionName" aria-label="版本名称" maxlength="150" placeholder="请输入版本名称" /></ElFormItem>
          <ElFormItem label="适用供应商类别" class="template-category"><ElSelect v-model="form.categories" aria-label="适用供应商类别" multiple collapse-tags collapse-tags-tooltip :max-collapse-tags="2" placeholder="请选择，可多选"><ElOption v-for="item in categories" :key="item.value" :label="item.label" :value="item.value" /></ElSelect><p class="field-help">不选类别时作为通用模板</p></ElFormItem>
          <ElFormItem label="状态"><ElSelect v-model="form.status" aria-label="状态"><ElOption label="启用" value="ACTIVE" /><ElOption label="停用" value="INACTIVE" /></ElSelect></ElFormItem>
          <ElFormItem label="合同标题"><ElInput v-model="form.title" aria-label="合同标题" /></ElFormItem>
          <ElFormItem label="结算方式"><ElSelect v-model="form.settlementMode" aria-label="结算方式"><ElOption label="按数量和单价" value="NORMAL" /><ElOption label="按实际重量" value="ACTUAL_WEIGHT" /></ElSelect></ElFormItem>
          <div class="template-field-pair"><ElFormItem label="默认税率（%）" prop="taxRate"><ElInput v-model="form.taxRate" aria-label="默认税率（%）" inputmode="decimal" /></ElFormItem><ElFormItem label="默认运费承担方"><ElSelect v-model="form.freightBearer" aria-label="默认运费承担方" filterable allow-create><ElOption label="甲方" value="甲方" /><ElOption label="乙方" value="乙方" /></ElSelect></ElFormItem></div>
        </div>
      </section>
      <section class="template-contract-terms">
        <h3>合同条款</h3><div class="template-terms-fields">
          <ElFormItem class="template-payment"><template #label><span>二、支付方式和交期</span><ElButton :disabled="saving" @click="insertDeliveryVariable">插入采购交期</ElButton></template><ElInput v-model="form.paymentAndDelivery" aria-label="二、支付方式和交期" type="textarea" resize="none" /><p class="field-help">生成采购表时自动替换为该供应商的采购交期。</p></ElFormItem>
          <ElFormItem label="三、产品质量标准（每行一条）" class="template-quality"><ElInput v-model="form.qualityStandards" aria-label="三、产品质量标准（每行一条）" type="textarea" resize="none" /></ElFormItem>
          <div class="template-field-pair template-terms-row"><ElFormItem label="四、送货交接"><ElInput v-model="form.deliveryHandover" aria-label="四、送货交接" type="textarea" resize="none" /></ElFormItem><ElFormItem label="五、特别说明"><ElInput v-model="form.specialInstructions" aria-label="五、特别说明" type="textarea" resize="none" /></ElFormItem></div>
          <div class="template-field-pair template-terms-row template-last-terms"><ElFormItem label="六、争议解决"><ElInput v-model="form.disputeResolution" aria-label="六、争议解决" type="textarea" resize="none" /></ElFormItem><ElFormItem label="七、合同生效"><ElInput v-model="form.effectiveness" aria-label="七、合同生效" type="textarea" resize="none" /></ElFormItem></div>
          <ElFormItem label="本次变更内容" prop="changeSummary" class="template-change-summary"><ElInput v-model="form.changeSummary" aria-label="本次变更内容" maxlength="500" show-word-limit :placeholder="isEditing ? '请输入本次修改的说明，便于追溯' : '请输入本次创建的说明，便于追溯'" /></ElFormItem>
        </div>
      </section>
    </ElForm>
    <template #footer>
      <p class="template-create-notice"><ElIcon><InfoFilled /></ElIcon><span v-if="isEditing">保存当前模板：更新 {{ currentVersion === null ? '—' : `V${currentVersion}` }}；保存为新版本：创建 {{ currentVersion === null ? '—' : `V${nextVersion}` }}。已生成采购表不受影响。</span><span v-else>创建后保存为初始版本，已生成采购表不受影响。</span></p>
      <ElButton :disabled="saving" @click="close">取消</ElButton>
      <ElButton v-if="isEditing" class="template-save-current" :loading="saving && savingMode === 'CURRENT'" :disabled="saving || saveDisabled" @click="save('CURRENT')">保存当前模板</ElButton>
      <ElButton type="primary" :loading="saving && savingMode === 'NEW_VERSION'" :disabled="saving || saveDisabled" @click="save('NEW_VERSION')">{{ isEditing ? '保存为新版本' : '创建模板' }}</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.purchase-template-create-overlay { background: color-mix(in srgb, var(--erp-overlay-scrim-color) 46%, transparent); }
.purchase-template-create-drawer {
  top: 0 !important; height: 100% !important; max-width: 100vw; box-shadow: none; background: token.$crm-color-surface; color: token.$crm-text-primary; font: 16px/24px 'Noto Sans SC Variable', token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary}; --el-text-color-placeholder: #{token.$crm-text-muted};
  .app-window-dialog__header { flex: 0 0 52px; box-sizing: border-box; padding: 10px 24px; margin: 0; align-items: center; border-bottom: 1px solid token.$crm-border-default; color: inherit; }
  .template-create-heading { display: flex; min-width: 0; align-items: baseline; gap: 16px; }
  .template-create-heading h2 { margin: 0; font: 600 22px/28px 'Noto Serif SC Variable', token.$crm-font-display; white-space: nowrap; }
  .template-create-heading p { margin: 0; overflow: hidden; color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
  .template-create-close.el-button { width: 32px; height: 32px; padding: 0; font-size: 18px; color: token.$crm-text-secondary; }
  .app-window-dialog__body { padding: 0 32px 16px; overflow-y: auto; }
  .template-create-form { display: grid; grid-template-columns: 408px minmax(0,1fr); gap: 32px; min-height: 784px; position: relative; }
  .template-create-form::after { content: ''; position: absolute; left: 424px; top: 0; bottom: 0; width: 1px; background: token.$crm-border-default; }
  section { min-width: 0; }
  h3 { display: flex; align-items: center; height: 54px; padding: 0 22px; margin: 0; background: token.$crm-color-subtle; font-size: 20px; font-weight: 700; }
  .template-basic-fields { padding: 24px 12px 0; }
  .template-terms-fields { padding: 10px 12px 0; }
  .el-form-item { margin: 0; }
  .el-form-item__label { height: 24px; margin-bottom: 4px; padding: 0; color: token.$crm-text-primary; font-size: 16px; line-height: 24px; }
  .el-form-item.is-required > .el-form-item__label::after { color: token.$crm-primary !important; }
  .el-input, .el-select { width: 100%; font-family: 'Noto Sans SC Variable', #{token.$crm-font-body}; }
  .el-input__wrapper, .el-select__wrapper { height: 32px; min-height: 32px; padding: 0 14px; border-radius: var(--erp-radius-control); box-shadow: 0 0 0 1px var(--erp-input-border) inset; background: var(--erp-input-surface); font-size: 16px; }
  .el-input__inner { height: 30px; font: inherit; }
  .el-input__count-inner { background: var(--erp-input-surface); font-size: 14px; color: token.$crm-text-muted; }
  .el-textarea__inner { padding: 10px 14px; border-radius: var(--erp-radius-control); box-shadow: 0 0 0 1px var(--erp-input-border) inset; background: var(--erp-input-surface); font: 16px/22px 'Noto Sans SC Variable', token.$crm-font-body; color: token.$crm-text-primary; }
  .template-basic-fields > .el-form-item { margin-bottom: 24px; }
  .field-help { width: 100%; margin: 8px 0 0; color: token.$crm-text-secondary; font-size: 14px; line-height: 24px; }
  .template-basic-fields > .template-category { margin-bottom: 26px; }
  .template-category .el-tag { height: 30px; padding: 0 10px; font-size: 16px; color: var(--erp-color-text-inverse); background: var(--erp-tag-brand-background); border-color: transparent; }
  .template-category .el-tag__close { width: 16px; height: 16px; font-size: 16px; color: var(--erp-color-text-inverse); }
  .template-field-pair { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 24px; }
  .template-payment .el-form-item__label { width: 100%; display: flex; justify-content: space-between; align-items: center; height: 36px; margin-bottom: 8px; }
  .template-payment .el-button { height: 36px; padding: 0 20px; font: inherit; }
  .template-payment .el-textarea__inner { height: 92px; }
  .template-payment .field-help { margin-top: 4px; }
  .template-quality { margin-top: 24px; }
  .template-quality .el-form-item__label, .template-terms-row .el-form-item__label, .template-change-summary .el-form-item__label { margin-bottom: 8px; }
  .template-quality .el-textarea__inner { height: 106px; }
  .template-terms-row { margin-top: 26px; }
  .template-terms-row .el-textarea__inner { height: 88px; }
  .template-last-terms .el-textarea__inner { height: 76px; padding-top: 5px; padding-bottom: 5px; }
  .template-change-summary { margin-top: 24px; }
  .template-change-summary .el-input__wrapper { height: 32px; min-height: 32px; }
  .app-window-dialog__footer { box-sizing: border-box; flex: 0 0 64px; padding: 0 24px; border-top: 1px solid token.$crm-border-default; display: flex; gap: 12px; align-items: center; text-align: left; }
  .template-create-notice { display: flex; min-width: 0; align-items: center; gap: 10px; flex: 1; margin: 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
  .template-create-notice span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .template-create-notice .el-icon { flex: none; font-size: 18px; color: token.$crm-text-muted; }
  .app-window-dialog__footer .el-button { height: 32px; width: 92px; margin: 0; font: 500 13px 'Noto Sans SC Variable', token.$crm-font-body; }
  .app-window-dialog__footer .el-button--primary { width: 148px; }
  .template-create-error { padding: 10px 14px; margin-bottom: 12px; color: token.$crm-primary; background: token.$crm-color-subtle; }
}
.purchase-template-edit-drawer {
  .app-window-dialog__footer .el-button { width: 92px; }
  .app-window-dialog__footer .template-save-current { width: 140px; }
  .app-window-dialog__footer .el-button--primary { width: 148px; }
}
</style>

