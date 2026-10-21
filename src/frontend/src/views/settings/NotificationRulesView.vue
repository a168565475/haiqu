<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElButton, ElInput, ElOption, ElSelect, ElSwitch, ElTag } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/notifications'
import type { NotificationPreview, NotificationRule, NotificationRuleWrite } from '@/types/notifications'

const MANAGE_PERMISSION = 'access_control.manage_notifications'
const auth = useAuthStore()
const permitted = computed(() => auth.managementCan(MANAGE_PERMISSION))
const forbidden = ref(false)
const canManage = computed(() => permitted.value && !forbidden.value)
const rules = ref<NotificationRule[]>([])
const roles = ref<{ role_code: string; display_name: string; archived: boolean }[]>([])
const loading = ref(false)
const loadError = ref('')
const notice = ref('')
const dialogVisible = ref(false)
const saving = ref(false)
const previewing = ref(false)
const stale = ref(false)
const operationError = ref('')
const selected = ref<NotificationRule>()
const etag = ref('')
const preview = ref<NotificationPreview>()
const form = reactive<NotificationRuleWrite>({ name: '', title_template: '', body_template: '', recipient_role_codes: [], recipient_scope: 'ROLE_MEMBERS', enabled: false })
let disposed = false
let pageVersion = 0
let editorVersion = 0
let previewRequest = 0

const roleLabel = computed(() => new Map(roles.value.map(role => [role.role_code, role.display_name])))
const availableRoles = computed(() => roles.value.filter(role => !role.archived))
const variableHint = computed(() => selected.value?.allowed_variables.map(value => `{{${value}}}`).join('、') || '')
const requiredHint = computed(() => selected.value?.required_variables.map(value => `{{${value}}}`).join('、') || '')

function clearEditor(): void {
  editorVersion++; previewRequest++
  selected.value = undefined; etag.value = ''; preview.value = undefined; dialogVisible.value = false
  saving.value = false; previewing.value = false; stale.value = false; operationError.value = ''
  Object.assign(form, { name: '', title_template: '', body_template: '', recipient_role_codes: [], recipient_scope: 'ROLE_MEMBERS', enabled: false })
}

function clearPage(): void {
  pageVersion++
  rules.value = []; roles.value = []; loading.value = false; loadError.value = ''; notice.value = ''
  clearEditor()
}

function rejectAccess(error: unknown): boolean {
  if (!isAxiosError(error) || ![401, 403].includes(error.response?.status || 0)) return false
  clearPage(); forbidden.value = true
  loadError.value = api.notificationError(error, '当前账号无法访问通知规则。')
  return true
}

async function loadRules(): Promise<void> {
  if (!canManage.value || loading.value || saving.value) return
  const version = pageVersion
  loading.value = true; loadError.value = ''; notice.value = ''
  try {
    const result = await api.getNotificationRules()
    if (disposed || version !== pageVersion || !canManage.value) return
    rules.value = result.data; roles.value = result.roles
  } catch (error) {
    if (disposed || version !== pageVersion || !canManage.value || rejectAccess(error)) return
    rules.value = []; roles.value = []
    loadError.value = api.notificationError(error, '通知规则加载失败，请稍后重试。')
  } finally { if (!disposed && version === pageVersion) loading.value = false }
}

function openEditor(rule: NotificationRule): void {
  if (!canManage.value || loading.value || saving.value) return
  clearEditor()
  selected.value = rule; etag.value = rule.etag
  Object.assign(form, { name: rule.name, title_template: rule.title_template, body_template: rule.body_template, recipient_role_codes: [...rule.recipient_role_codes], recipient_scope: rule.recipient_scope, enabled: rule.enabled })
  if (!etag.value) operationError.value = '通知规则版本缺失，请关闭弹窗并刷新后重试。'
  dialogVisible.value = true
}

function validateForm(): boolean {
  const allowed = new Set(selected.value?.allowed_variables || [])
  const text = `${form.title_template}\n${form.body_template}`
  const names = [...text.matchAll(/\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g)].map(match => match[1])
  if (!form.name.trim() || !form.title_template.trim() || !form.body_template.trim()) { operationError.value = '名称、标题和正文不能为空。'; return false }
  if (names.some(name => !allowed.has(name))) { operationError.value = '模板包含当前事件不允许的变量。'; return false }
  if ((selected.value?.required_variables || []).some(name => !names.includes(name))) { operationError.value = `模板必须包含：${requiredHint.value}。`; return false }
  if (new Set(form.recipient_role_codes).size !== form.recipient_role_codes.length) { operationError.value = '接收角色不可重复。'; return false }
  if (!form.recipient_role_codes.length && form.enabled) { operationError.value = '启用规则必须至少选择一个接收角色。'; return false }
  if (!selected.value?.supported_scopes.includes(form.recipient_scope)) { operationError.value = '当前事件不支持所选接收范围。'; return false }
  return true
}

async function saveRule(): Promise<void> {
  if (!canManage.value || !selected.value || saving.value || stale.value || !etag.value || !validateForm()) return
  const version = editorVersion
  saving.value = true; operationError.value = ''; notice.value = ''
  try {
    const result = await api.saveNotificationRule(selected.value.event_code, { ...form, name: form.name.trim(), recipient_role_codes: [...form.recipient_role_codes] }, etag.value)
    if (disposed || version !== editorVersion || !canManage.value) return
    const index = rules.value.findIndex(item => item.event_code === result.data.event_code)
    if (index >= 0) rules.value[index] = { ...result.data, etag: result.etag }
    clearEditor(); notice.value = '通知规则已保存，新事件将使用新版本。'
  } catch (error) {
    if (disposed || version !== editorVersion || !canManage.value || rejectAccess(error)) return
    stale.value = isAxiosError(error) && error.response?.status === 412
    operationError.value = api.notificationError(error, '保存结果未确认，请关闭弹窗并刷新核实后再操作。')
  } finally { if (!disposed && version === editorVersion) saving.value = false }
}

async function previewRule(): Promise<void> {
  if (!canManage.value || !selected.value || saving.value || previewing.value || !validateForm()) return
  const request = ++previewRequest
  previewing.value = true; operationError.value = ''; preview.value = undefined
  const examples: Record<string, string> = { document_no: '示例单号', operator: '示例操作人', occurred_at: '示例时间', product_name: '示例产品', quantity: '1', status: '示例状态', submitter: '示例提交人', workshop_name: '示例车间', system_path: selected.value.target_key }
  const variables = Object.fromEntries(selected.value.allowed_variables.map(name => [name, examples[name] || `示例${name}`]))
  try {
    const result = await api.previewNotificationRule(selected.value.event_code, { ...form, recipient_role_codes: [...form.recipient_role_codes], variables })
    if (!disposed && request === previewRequest && canManage.value) preview.value = result
  } catch (error) {
    if (disposed || request !== previewRequest || !canManage.value || rejectAccess(error)) return
    operationError.value = api.notificationError(error, '通知预览失败，请稍后重试。')
  } finally { if (!disposed && request === previewRequest) previewing.value = false }
}

function scopeLabel(rule: NotificationRule): string { return rule.scope_labels[rule.recipient_scope] || rule.recipient_scope }
function roleNames(rule: NotificationRule): string { return rule.recipient_role_codes.map(code => roleLabel.value.get(code) || code).join('、') || '未配置' }
function closeDialog(done?: () => void): void { if (!saving.value) { clearEditor(); done?.() } }

watch(form, () => { previewRequest++; previewing.value = false; preview.value = undefined }, { flush: 'sync' })
watch([permitted, () => auth.user?.id], () => {
  clearPage(); forbidden.value = false
  if (permitted.value) void loadRules()
}, { flush: 'sync' })
onMounted(() => { void loadRules() })
onBeforeUnmount(() => { disposed = true; clearPage() })
</script>

<template>
  <div class="notification-rules-page">
    <header class="page-heading">
      <div><h1>通知规则</h1><p>配置已登记业务事件的 ERP 站内消息和企业微信接收范围。</p></div>
      <ElButton :disabled="!canManage || loading || saving" @click="loadRules">刷新</ElButton>
    </header>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="loadError" class="error" role="alert">{{ loadError }}</p>
    <section v-if="!canManage" class="empty-card">当前账号没有通知规则管理权限。</section>
    <section v-else-if="!loadError" class="rules-card">
      <div v-if="loading" class="empty-state" role="status">正在读取通知规则…</div>
      <div v-else-if="!rules.length" class="empty-state">暂无已登记通知规则。</div>
      <div v-else class="table-scroll" role="region" aria-label="通知规则列表" tabindex="0"><table class="rules-table"><thead><tr><th>业务环节</th><th>模板</th><th>接收角色</th><th>范围</th><th>状态</th><th>版本</th><th>操作</th></tr></thead><tbody><tr v-for="rule in rules" :key="rule.event_code"><td><strong>{{ rule.display_name }}</strong><small>{{ rule.event_code }}</small></td><td><span>{{ rule.name }}</span><small>{{ rule.title_template }}</small></td><td>{{ roleNames(rule) }}<small v-for="warning in rule.warnings" :key="warning" class="rule-warning">{{ warning }}</small></td><td>{{ scopeLabel(rule) }}</td><td><ElTag :type="rule.enabled ? 'success' : 'info'">{{ rule.enabled ? '启用' : '停用' }}</ElTag></td><td>v{{ rule.version }}</td><td><ElButton link type="primary" @click="openEditor(rule)">编辑 / 预览</ElButton></td></tr></tbody></table></div>
    </section>
    <AppWindowDialog v-if="canManage" v-model="dialogVisible" title="编辑通知规则" :width="720" :min-width="280" :close-on-click-modal="false" :before-close="closeDialog" destroy-on-close>
      <template v-if="selected"><div class="dialog-grid"><div class="editor"><p class="event-label">{{ selected.display_name }} · {{ selected.event_code }}</p><label for="notification-name">模板名称<ElInput id="notification-name" :disabled="saving" v-model="form.name" maxlength="100" /></label><label for="notification-title">标题<ElInput id="notification-title" :disabled="saving" v-model="form.title_template" maxlength="200" /></label><label for="notification-body">正文<ElInput id="notification-body" :disabled="saving" v-model="form.body_template" type="textarea" :rows="6" maxlength="8192" /></label><p class="hint">可用变量：{{ variableHint }}</p><p class="hint">必要变量：{{ requiredHint }}</p><label for="notification-roles">接收角色<ElSelect id="notification-roles" :disabled="saving" v-model="form.recipient_role_codes" multiple collapse-tags collapse-tags-tooltip placeholder="选择角色"><ElOption v-for="role in availableRoles" :key="role.role_code" :label="`${role.display_name}（${role.role_code}）`" :value="role.role_code" /></ElSelect></label><label for="notification-scope">接收范围<ElSelect id="notification-scope" :disabled="saving" v-model="form.recipient_scope"><ElOption v-for="scope in selected.supported_scopes" :key="scope" :label="selected.scope_labels[scope] || scope" :value="scope" /></ElSelect></label><label class="switch-line"><span>启用规则</span><ElSwitch v-model="form.enabled" :disabled="saving" aria-label="启用规则" /></label><p v-if="operationError" class="error" role="alert">{{ operationError }}</p></div><aside class="preview"><div class="preview-heading"><strong>预览</strong><ElButton size="small" :loading="previewing" :disabled="saving" @click="previewRule">生成预览</ElButton></div><p v-if="preview" class="preview-scope">{{ preview.scope_label }} · {{ roleNames({ ...selected, recipient_role_codes: preview.recipient_role_codes }) }}</p><div v-if="preview" class="preview-message"><strong>{{ preview.title }}</strong><p>{{ preview.body }}</p></div><p v-for="warning in preview?.warnings" :key="warning" class="hint">{{ warning }}</p><p v-if="preview?.recipient_note" class="hint">{{ preview.recipient_note }}</p><p v-else class="hint">预览只替换示例变量，不发送任何消息。</p></aside></div></template>
      <template #footer><ElButton :disabled="saving" @click="closeDialog()">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="stale || !etag" @click="saveRule">保存</ElButton></template>
    </AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
.table-scroll { overflow-x:auto; border-radius:inherit; }
.notification-rules-page { min-width: 0; color: var(--erp-color-text-primary); }
.page-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:14px; }.page-heading h1 { margin:0; font-size:20px; line-height:28px; }.page-heading p { margin:4px 0 0; color:var(--erp-color-text-secondary); font-size:12px; }
.rules-card,.empty-card { border:1px solid var(--erp-glass-border); border-radius:12px; background:var(--erp-glass-surface); box-shadow:var(--erp-glass-shadow); }.empty-card,.empty-state { padding:48px 20px; text-align:center; color:var(--erp-color-text-secondary); }.rules-table { width:100%; min-width:760px; border-collapse:collapse; font-size:13px; }.rules-table th,.rules-table td { padding:12px 14px; border-bottom:1px solid var(--erp-color-border); text-align:left; vertical-align:top; }.rules-table th { color:var(--erp-color-text-secondary); font-size:12px; font-weight:500; }.rules-table tr:last-child td { border-bottom:0; }.rules-table small { display:block; margin-top:4px; color:var(--erp-color-text-secondary); font-size:11px; overflow-wrap:anywhere; }.notice,.error { margin:0 0 12px; padding:10px 12px; border-radius:8px; font-size:12px; }.notice { background:var(--erp-color-info-soft); color:var(--erp-color-text-secondary); }.error { background:var(--erp-color-danger-soft); color:var(--erp-color-danger); }.dialog-grid { display:grid; grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr); gap:16px; }.editor { min-width:0; display:flex; flex-direction:column; gap:11px; }.editor label { display:flex; flex-direction:column; gap:5px; font-size:12px; color:var(--erp-color-text-secondary); }.event-label { overflow-wrap:anywhere; margin:0; font-weight:600; color:var(--erp-color-text-primary); }.hint { margin:0; color:var(--erp-color-text-secondary); font-size:11px; line-height:1.7; overflow-wrap:anywhere; }.switch-line { flex-direction:row !important; align-items:center; justify-content:space-between; }.preview { min-width:0; padding:12px; border-radius:9px; background:var(--erp-color-info-soft); min-height:200px; }.preview-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; }.preview-scope { overflow-wrap:anywhere; margin:12px 0 8px; color:var(--erp-color-text-secondary); font-size:11px; }.preview-message { margin-top:12px; padding:12px; border:1px solid var(--erp-color-border-subtle); border-radius:8px; background:var(--erp-glass-inner-background); }.preview-message strong { overflow-wrap:anywhere; font-size:13px; }.preview-message p { margin:8px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; line-height:1.7; }
@media (max-width:700px) { .dialog-grid { grid-template-columns:1fr; } }
</style>
