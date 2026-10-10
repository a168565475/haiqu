<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

import { fetchQuotationTemplateSellerProfile, updateQuotationTemplateSellerProfile } from '@/api/quotations'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { QuotationTemplate, QuotationTemplateSellerProfile } from '@/types/quotation'

const props = withDefaults(defineProps<{
  modelValue: boolean
  templateId: string | null
  contextName?: string
}>(), { contextName: '单据' })
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [template: QuotationTemplate]
}>()

const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const loading = ref(false)
const saving = ref(false)
const template = ref<QuotationTemplate | null>(null)
const etag = ref('')
const form = reactive<QuotationTemplateSellerProfile>({
  company_name: '', contact_person: '', phone: '', fax: '', skype: '', qq: '', wechat: '', whatsapp: '',
  address: '', email: '', facebook: '', website: '',
})

function value(config: Record<string, unknown>, key: string) {
  return typeof config[key] === 'string' ? String(config[key]) : ''
}

function applyTemplate(item: QuotationTemplate) {
  const config = item.template_config || {}
  Object.assign(form, {
    company_name: value(config, 'seller_company_name'), contact_person: value(config, 'seller_contact_person'),
    phone: value(config, 'seller_phone'), fax: value(config, 'seller_fax'), skype: value(config, 'seller_skype'),
    qq: value(config, 'seller_qq'), wechat: value(config, 'seller_wechat'), whatsapp: value(config, 'seller_whatsapp'),
    address: value(config, 'seller_address'), email: value(config, 'seller_email'),
    facebook: value(config, 'seller_facebook'), website: value(config, 'seller_website'),
  })
}

function errorMessage(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '卖方资料处理失败。'
  const data = error.response?.data as { error?: { message?: string } } | undefined
  return data?.error?.message || '卖方资料处理失败，请稍后重试。'
}

async function load() {
  if (!props.templateId) {
    ElMessage.warning('当前单据尚未关联固定卖方模板。')
    visible.value = false
    return
  }
  loading.value = true
  try {
    const result = await fetchQuotationTemplateSellerProfile(props.templateId)
    template.value = result.data
    etag.value = result.etag
    applyTemplate(result.data)
  } catch (error) {
    ElMessage.error(errorMessage(error))
    visible.value = false
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!template.value || !etag.value) return
  if (!form.company_name.trim()) return ElMessage.warning('请填写公司英文全称。')
  try {
    await ElMessageBox.confirm(
      `保存后会影响以后新建的报价和销售订单；已经锁定或确认的历史单据仍使用原快照。确定继续吗？`,
      '确认更新全局卖方模板',
      { confirmButtonText: '确认更新', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = Object.fromEntries(Object.entries(form).map(([key, item]) => [key, item.trim()])) as unknown as QuotationTemplateSellerProfile
    const result = await updateQuotationTemplateSellerProfile(template.value.id, payload, etag.value)
    template.value = result.data
    etag.value = result.etag
    applyTemplate(result.data)
    emit('saved', result.data)
    visible.value = false
    ElMessage.success(`卖方模板已更新为 V${result.data.template_version}，当前${props.contextName}草稿已刷新。`)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

watch(() => props.modelValue, (value) => { if (value) void load() })
</script>

<template>
  <AppWindowDialog v-model="visible" :class="{ 'sales-order-seller-dialog': contextName === '销售订单' }" title="编辑固定卖方主体" :width="860" :height="760" :close-on-click-modal="false" destroy-on-close>
    <div v-loading="loading">
      <el-alert type="warning" :closable="false" show-icon title="这是全局固定卖方模板。保存会影响以后新建的报价和销售订单，不会改写已锁定或已确认单据。" />
      <div class="dialog-meta"><strong>卖方联系资料</strong><el-tag v-if="template" effect="plain">模板 V{{ template.template_version }}</el-tag></div>
      <el-form label-position="top" class="seller-form">
        <el-form-item label="公司英文全称 *" class="full"><el-input v-model="form.company_name" maxlength="300" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="form.contact_person" maxlength="120" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="form.phone" maxlength="80" /></el-form-item>
        <el-form-item label="传真"><el-input v-model="form.fax" maxlength="80" /></el-form-item>
        <el-form-item label="Skype"><el-input v-model="form.skype" maxlength="120" /></el-form-item>
        <el-form-item label="QQ"><el-input v-model="form.qq" maxlength="120" /></el-form-item>
        <el-form-item label="微信"><el-input v-model="form.wechat" maxlength="120" /></el-form-item>
        <el-form-item label="WhatsApp"><el-input v-model="form.whatsapp" maxlength="80" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" maxlength="254" /></el-form-item>
        <el-form-item label="Facebook"><el-input v-model="form.facebook" maxlength="500" /></el-form-item>
        <el-form-item label="网站"><el-input v-model="form.website" maxlength="500" /></el-form-item>
        <el-form-item label="地址" class="full"><el-input v-model="form.address" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
      <p class="role-hint">责任角色：业务资料维护人员。本阶段仅提示责任，不做额外审批。</p>
    </div>
    <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存并更新模板</el-button></template>
  </AppWindowDialog>
</template>

<style lang="scss" scoped>
.dialog-meta{display:flex;align-items:center;justify-content:space-between;margin:16px 0 8px}.seller-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 20px}.seller-form .full{grid-column:1/-1}.seller-form :deep(.el-form-item){margin-bottom:14px}.role-hint{margin:0;color:#71717a;font-size:12px}
.sales-order-seller-dialog{border-radius:6px;background:#fcfbf7}.sales-order-seller-dialog :deep(.el-dialog__header){margin:0;padding:24px 28px 18px;border-bottom:1px solid #ddd6c9}.sales-order-seller-dialog :deep(.el-dialog__title){font-family:'Noto Serif SC','Songti SC',serif;font-size:24px;font-weight:600}.sales-order-seller-dialog :deep(.el-dialog__body){padding:18px 28px}.sales-order-seller-dialog :deep(.el-dialog__footer){padding:14px 28px 22px}.sales-order-seller-dialog :deep(.el-input__wrapper){min-height:38px;border-radius:4px}.sales-order-seller-dialog :deep(.el-button){height:32px;border-radius:4px}.sales-order-seller-dialog :deep(.el-button--primary){border-color:#c84e28;background:#c84e28}.sales-order-seller-dialog :deep(.el-alert){border:0;background:#f0eadf}.sales-order-seller-dialog .seller-form :deep(.el-form-item__label){color:#6f6a61}
</style>
