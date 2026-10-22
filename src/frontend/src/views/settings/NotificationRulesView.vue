<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElButton, ElInput, ElOption, ElSelect, ElSwitch, ElTag } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/notifications'
import type { NotificationPreview, NotificationRule, NotificationRuleWrite, NotificationPreviewDraft, NotificationPreviewAttempt, NotificationPreviewRecipients } from '@/types/notifications'

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
const previewDraft = ref<NotificationPreviewDraft>()
const previewExpired = ref(false)
const recipients = ref<NotificationPreviewRecipients>()
const recipientSearch = ref('')
const recipientLoading = ref(false)
const bindingId = ref('')
const sending = ref(false)
const checking = ref(false)
const sendStarted = ref(false)
const sentPreviewId = ref('')
const sendForbidden = ref(false)
const sendError = ref('')
const attempt = ref<NotificationPreviewAttempt>()
const canSend = computed(() => canManage.value && auth.managementCan('access_control.manage_wecom') && !sendForbidden.value)
const busy = computed(() => saving.value || sending.value)
const awaitingOutcome = computed(() => sendStarted.value && (!attempt.value || ['PROCESSING', 'UNCERTAIN'].includes(attempt.value.status)))
const sendReady = computed(() => canSend.value && recipients.value?.available && bindingId.value && preview.value?.preview_token && previewDraft.value && !previewExpired.value && !busy.value && !sendStarted.value)
const form = reactive<NotificationRuleWrite>({ name: '', title_template: '', body_template: '', recipient_role_codes: [], recipient_scope: 'ROLE_MEMBERS', enabled: false })
let disposed = false
let pageVersion = 0
let editorVersion = 0
let previewRequest = 0
let recipientRequest = 0
let sendRequest = 0
let attemptQuery = 0
let expiryTimer: ReturnType<typeof setTimeout> | undefined

const roleLabel = computed(() => new Map(roles.value.map(role => [role.role_code, role.display_name])))
const availableRoles = computed(() => roles.value.filter(role => !role.archived))
const requiredHint = computed(() => selected.value?.required_variables.map(value => `{{${value}}}`).join('、') || '')
const definitions = computed(() => selected.value?.variable_definitions || [])
const requiredDefinitions = computed(() => definitions.value.filter(item => selected.value?.required_variables.includes(item.name)))
const optionalDefinitions = computed(() => definitions.value.filter(item => !selected.value?.required_variables.includes(item.name)))

function clearPreview(): void {
  previewRequest++; previewing.value = false; preview.value = undefined; previewDraft.value = undefined; previewExpired.value = false
  clearTimeout(expiryTimer)
}

function clearSendState(): void {
  sendRequest++; attemptQuery++
  sending.value = false; checking.value = false; sendStarted.value = false
  sendError.value = ''; attempt.value = undefined; sentPreviewId.value = ''
}

function clearEditor(): void {
  editorVersion++; recipientRequest++; clearPreview()
  clearSendState()
  selected.value = undefined; etag.value = ''; preview.value = undefined; dialogVisible.value = false
  saving.value = false; previewing.value = false; stale.value = false; operationError.value = ''
  recipients.value = undefined; bindingId.value = ''; recipientSearch.value = ''; recipientLoading.value = false
  sending.value = false; checking.value = false; sendStarted.value = false; sendForbidden.value = false; sendError.value = ''; attempt.value = undefined
  sentPreviewId.value = ''
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
  if (!canManage.value || loading.value || busy.value) return
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
  if (!canManage.value || loading.value || busy.value) return
  clearEditor()
  selected.value = rule; etag.value = rule.etag
  Object.assign(form, { name: rule.name, title_template: rule.title_template, body_template: rule.body_template, recipient_role_codes: [...rule.recipient_role_codes], recipient_scope: rule.recipient_scope, enabled: rule.enabled })
  if (!etag.value) operationError.value = '通知规则版本缺失，请关闭弹窗并刷新后重试。'
  dialogVisible.value = true
  if (canSend.value) void loadRecipients()
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
  if (!canManage.value || !selected.value || busy.value || stale.value || !etag.value || !validateForm()) return
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
  if (!canManage.value || !selected.value || busy.value || previewing.value || awaitingOutcome.value || !validateForm()) return
  if (definitions.value.length !== selected.value.allowed_variables.length) { operationError.value = '变量说明未加载，请关闭弹窗并刷新页面。'; return }
  const request = ++previewRequest
  attemptQuery++; checking.value = false; sentPreviewId.value = ''
  clearTimeout(expiryTimer)
  previewing.value = true; operationError.value = ''; preview.value = undefined
  previewDraft.value = undefined; sendStarted.value = false; sendError.value = ''; attempt.value = undefined; previewExpired.value = false
  const variables = Object.fromEntries(definitions.value.map(item => [item.name, item.example]))
  const draft = { ...form, recipient_role_codes: [...form.recipient_role_codes], variables }
  try {
    const result = await api.previewNotificationRule(selected.value.event_code, draft, etag.value)
    if (!disposed && request === previewRequest && canManage.value) {
      preview.value = result; previewDraft.value = draft
      if (result.expires_at) expiryTimer = setTimeout(() => { previewExpired.value = true }, Math.max(0, Date.parse(result.expires_at) - Date.now()))
    }
  } catch (error) {
    if (disposed || request !== previewRequest || !canManage.value || rejectAccess(error)) return
    operationError.value = api.notificationError(error, '通知预览失败，请稍后重试。')
  } finally { if (!disposed && request === previewRequest) previewing.value = false }
}

function handleSendError(error: unknown, fallback: string): void {
  if (isAxiosError(error) && error.response?.status === 401) { rejectAccess(error); return }
  if (isAxiosError(error) && error.response?.status === 403) { clearSendState(); recipientRequest++; sendForbidden.value = true; recipients.value = undefined; bindingId.value = ''; void loadRules() }
  sendError.value = api.notificationPreviewError(error, fallback)
}

async function loadRecipients(search = '', more = false): Promise<void> {
  if (!canSend.value || sending.value) return
  const request = ++recipientRequest
  const version = editorVersion
  recipientSearch.value = search; recipientLoading.value = true; sendError.value = ''
  try {
    const result = await api.getNotificationPreviewRecipients(search, more ? (recipients.value?.page || 1) + 1 : 1)
    if (disposed || request !== recipientRequest || version !== editorVersion || !canSend.value) return
    recipients.value = { ...result, data: more ? [...(recipients.value?.data || []), ...result.data] : result.data }
  } catch (error) {
    if (disposed || request !== recipientRequest || version !== editorVersion) return
    recipients.value = undefined; handleSendError(error, '接收人员读取失败，请重试。')
  } finally { if (!disposed && request === recipientRequest && version === editorVersion) recipientLoading.value = false }
}

async function sendPreview(): Promise<void> {
  if (!sendReady.value || !selected.value || !preview.value?.preview_token || !previewDraft.value || !recipients.value) return
  const version = editorVersion
  const request = ++sendRequest
  sending.value = true; sendStarted.value = true; sendError.value = ''
  sentPreviewId.value = preview.value.preview_id || ''
  try {
    const result = await api.sendNotificationPreview(selected.value.event_code, { preview_token: preview.value.preview_token,
      binding_id: bindingId.value, config_etag: recipients.value.config_etag, draft: previewDraft.value })
    if (!disposed && version === editorVersion && request === sendRequest && canSend.value) { attempt.value = result; sentPreviewId.value = result.preview_id }
  } catch (error) {
    if (disposed || version !== editorVersion || request !== sendRequest) return
    const definiteRejection = isAxiosError(error) && error.response && error.response.status < 500
    if (definiteRejection) sendStarted.value = false
    handleSendError(error, '发送结果未确认，请查询本次结果，勿重复发送。')
  } finally { if (!disposed && version === editorVersion && request === sendRequest) sending.value = false }
}

async function checkAttempt(): Promise<void> {
  const id = attempt.value?.preview_id || sentPreviewId.value
  if (!id || !canSend.value || checking.value) return
  const version = editorVersion
  const query = ++attemptQuery
  checking.value = true; sendError.value = ''
  try {
    const result = await api.getNotificationPreviewAttempt(id)
    if (!disposed && version === editorVersion && query === attemptQuery && id === sentPreviewId.value && canSend.value) attempt.value = result
  } catch (error) {
    if (!disposed && version === editorVersion && query === attemptQuery && id === sentPreviewId.value) handleSendError(error, '暂未确认本次结果，请稍后再查询，勿重复发送。')
  } finally { if (!disposed && version === editorVersion && query === attemptQuery) checking.value = false }
}

function scopeLabel(rule: NotificationRule): string { return rule.scope_labels[rule.recipient_scope] || rule.recipient_scope }
function roleNames(rule: NotificationRule): string { return rule.recipient_role_codes.map(code => roleLabel.value.get(code) || code).join('、') || '未配置' }
function closeDialog(done?: () => void): void { if (!busy.value) { clearEditor(); done?.() } }

watch(form, clearPreview, { flush: 'sync' })
watch(() => auth.managementCan('access_control.manage_wecom'), allowed => {
  clearSendState()
  recipientRequest++; recipients.value = undefined; bindingId.value = ''; sendForbidden.value = false
  if (allowed && dialogVisible.value) void loadRecipients()
}, { flush: 'sync' })
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
    <AppWindowDialog v-if="canManage" v-model="dialogVisible" title="编辑通知规则" :width="920" :min-width="280" :close-on-click-modal="false" :before-close="closeDialog" destroy-on-close>
      <template v-if="selected">
        <div class="dialog-grid">
          <div class="editor">
            <p class="event-label">{{ selected.display_name }} · {{ selected.event_code }}</p>
            <label for="notification-name">模板名称<ElInput id="notification-name" :disabled="busy" v-model="form.name" maxlength="100" /></label>
            <label for="notification-title">标题<ElInput id="notification-title" :disabled="busy" v-model="form.title_template" maxlength="200" /></label>
            <label for="notification-body">正文<ElInput id="notification-body" :disabled="busy" v-model="form.body_template" type="textarea" :rows="6" maxlength="8192" /></label>
            <label for="notification-roles">接收角色<ElSelect id="notification-roles" :disabled="busy" v-model="form.recipient_role_codes" multiple collapse-tags collapse-tags-tooltip placeholder="选择角色"><ElOption v-for="role in availableRoles" :key="role.role_code" :label="`${role.display_name}（${role.role_code}）`" :value="role.role_code" /></ElSelect></label>
            <label for="notification-scope">接收范围<ElSelect id="notification-scope" :disabled="busy" v-model="form.recipient_scope"><ElOption v-for="scope in selected.supported_scopes" :key="scope" :label="selected.scope_labels[scope] || scope" :value="scope" /></ElSelect></label>
            <label class="switch-line"><span>启用规则</span><ElSwitch v-model="form.enabled" :disabled="busy" aria-label="启用规则" /></label>
            <p v-if="operationError" class="error" role="alert">{{ operationError }}</p>
          </div>
          <aside class="preview">
            <div class="preview-heading"><strong>预览</strong><ElButton size="small" :loading="previewing" :disabled="busy || awaitingOutcome" @click="previewRule">生成预览</ElButton></div>
            <section class="variable-group" aria-label="必要变量">
              <h3>必要变量</h3>
              <table class="variable-table"><thead><tr><th>名称</th><th>变量名</th></tr></thead><tbody><tr v-for="item in requiredDefinitions" :key="item.name"><td>{{ item.label }}</td><td><code v-text="'{{' + item.name + '}}'"></code></td></tr></tbody></table>
              <p v-if="!requiredDefinitions.length" class="hint">暂无必要变量说明。</p>
            </section>
            <section class="variable-group" aria-label="可用变量">
              <h3>可用变量（非必填）</h3>
              <table v-if="optionalDefinitions.length" class="variable-table"><thead><tr><th>名称</th><th>变量名</th></tr></thead><tbody><tr v-for="item in optionalDefinitions" :key="item.name"><td>{{ item.label }}</td><td><code v-text="'{{' + item.name + '}}'"></code></td></tr></tbody></table>
              <p v-else class="hint">无其他可用变量。</p>
            </section>
            <p v-if="preview" class="preview-scope">{{ preview.scope_label }} · {{ roleNames({ ...selected, recipient_role_codes: preview.recipient_role_codes }) }}</p>
            <div v-if="preview" class="preview-message"><strong>{{ preview.title }}</strong><p>{{ preview.body }}</p></div>
            <p v-else class="hint preview-placeholder">点击生成预览；修改规则后需重新生成。</p>
            <p v-if="previewExpired" class="hint" role="status">预览已过期，请重新生成。</p>
            <p v-for="warning in preview?.warnings" :key="warning" class="hint">{{ warning }}</p>
            <p v-if="preview?.recipient_note" class="hint">{{ preview.recipient_note }}</p>
            <p class="hint">生成预览使用示例内容，不发送消息。点击“发送预览”才会发给下方选定的一人。</p>
            <section class="preview-send" aria-label="发送预览">
              <label for="notification-preview-recipient">已绑定员工</label>
              <ElSelect id="notification-preview-recipient" v-model="bindingId" :disabled="!canSend || busy || !recipients?.available || sendStarted" :loading="recipientLoading" filterable remote :remote-method="loadRecipients" placeholder="选择姓名或搜索员工编码">
                <ElOption v-for="person in recipients?.data" :key="person.binding_id" :value="person.binding_id" :label="`${person.employee_name}（${person.employee_code}）`" />
              </ElSelect>
              <p v-if="!canSend" class="hint">试发需要通知规则和企业微信两项管理权限。</p>
              <p v-else-if="recipients?.message" class="hint" role="status">{{ recipients.message }}</p>
              <ElButton v-if="canSend && !recipients && !recipientLoading" size="small" :disabled="busy" @click="loadRecipients()">重新读取接收人员</ElButton>
              <ElButton v-if="recipients && recipients.data.length < recipients.count" size="small" :disabled="recipientLoading || busy" @click="loadRecipients(recipientSearch, true)">加载更多人员</ElButton>
              <div class="send-actions"><ElButton type="primary" :loading="sending" :disabled="!sendReady" @click="sendPreview">发送预览</ElButton><ElButton v-if="sendStarted" :loading="checking" :disabled="sending || !canSend" @click="checkAttempt">查询本次结果</ElButton></div>
              <p v-if="attempt" class="hint" role="status">{{ attempt.recipient_name }}：{{ attempt.message }}</p>
              <p v-if="sendError" class="error" role="alert">{{ sendError }}</p>
            </section>
          </aside>
        </div>
      </template>
      <template #footer><ElButton :disabled="busy" @click="closeDialog()">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="sending || stale || !etag" @click="saveRule">保存</ElButton></template>
    </AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
.table-scroll { overflow-x:auto; border-radius:inherit; }
.notification-rules-page { min-width: 0; color: var(--erp-color-text-primary); }
.page-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:14px; }.page-heading h1 { margin:0; font-size:20px; line-height:28px; }.page-heading p { margin:4px 0 0; color:var(--erp-color-text-secondary); font-size:12px; }
.rules-card,.empty-card { border:1px solid var(--erp-glass-border); border-radius:12px; background:var(--erp-glass-surface); box-shadow:var(--erp-glass-shadow); }.empty-card,.empty-state { padding:48px 20px; text-align:center; color:var(--erp-color-text-secondary); }.rules-table { width:100%; min-width:760px; border-collapse:collapse; font-size:13px; }.rules-table th,.rules-table td { padding:12px 14px; border-bottom:1px solid var(--erp-color-border); text-align:left; vertical-align:top; }.rules-table th { color:var(--erp-color-text-secondary); font-size:12px; font-weight:500; }.rules-table tr:last-child td { border-bottom:0; }.rules-table small { display:block; margin-top:4px; color:var(--erp-color-text-secondary); font-size:11px; overflow-wrap:anywhere; }.notice,.error { margin:0 0 12px; padding:10px 12px; border-radius:8px; font-size:12px; }.notice { background:var(--erp-color-info-soft); color:var(--erp-color-text-secondary); }.error { background:var(--erp-color-danger-soft); color:var(--erp-color-danger); }.dialog-grid { display:grid; grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr); gap:16px; }.editor { min-width:0; display:flex; flex-direction:column; gap:11px; }.editor label { display:flex; flex-direction:column; gap:5px; font-size:12px; color:var(--erp-color-text-secondary); }.event-label { overflow-wrap:anywhere; margin:0; font-weight:600; color:var(--erp-color-text-primary); }.hint { margin:0; color:var(--erp-color-text-secondary); font-size:11px; line-height:1.7; overflow-wrap:anywhere; }.switch-line { flex-direction:row !important; align-items:center; justify-content:space-between; }.preview { min-width:0; padding:12px; border-radius:9px; background:var(--erp-color-info-soft); min-height:200px; }.preview-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; }.preview-scope { overflow-wrap:anywhere; margin:12px 0 8px; color:var(--erp-color-text-secondary); font-size:11px; }.preview-message { margin-top:12px; padding:12px; border:1px solid var(--erp-color-border-subtle); border-radius:8px; background:var(--erp-glass-inner-background); }.preview-message strong { overflow-wrap:anywhere; font-size:13px; }.preview-message p { margin:8px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; line-height:1.7; }
.variable-group { margin-top:12px; }.variable-group h3 { margin:0 0 6px; font-size:12px; font-weight:600; }.variable-table { width:100%; border-collapse:collapse; table-layout:fixed; font-size:12px; }.variable-table th,.variable-table td { padding:5px 6px; border-bottom:1px solid var(--erp-color-border-subtle); text-align:left; overflow-wrap:anywhere; }.variable-table th { font-weight:500; color:var(--erp-color-text-secondary); }.variable-table th:first-child { width:38%; }.variable-table code { white-space:normal; font-size:11px; }.preview-placeholder { margin:12px 0; }.preview-send { margin-top:16px; display:flex; flex-direction:column; gap:8px; border-top:1px solid var(--erp-color-border-subtle); padding-top:12px; font-size:12px; }.send-actions { display:flex; gap:8px; flex-wrap:wrap; }.send-actions .el-button + .el-button { margin-left:0; }
@media (max-width:700px) { .dialog-grid { grid-template-columns:1fr; } }
</style>
