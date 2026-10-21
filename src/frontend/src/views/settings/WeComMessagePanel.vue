<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { isAxiosError } from 'axios'
import * as api from '@/api/wecom'
import type { WeComBinding, WeComMessageAttempt, WeComMessageTemplate, WeComMessageTemplateResponse, WeComMessageTestWrite } from '@/types/wecom'

const props = defineProps<{ erpOrigin: string }>()
const saved = ref<WeComMessageTemplate>(), etag = ref('')
const name = ref(''), body = ref(''), bodyInput = ref<HTMLTextAreaElement>()
const loading = ref(false), saving = ref(false), stale = ref(false)
const templateError = ref(''), notice = ref('')
const recipients = ref<WeComBinding[]>([]), recipientId = ref(''), recipientLoading = ref(false), recipientError = ref('')
const messageContent = ref('这是一条海趣 ERP 企业微信消息通道测试通知，无需业务处理。')
const sending = ref(false), querying = ref(false), sendError = ref('')
const pendingRequest = ref<{ data: WeComMessageTestWrite; etag: string }>()
const attempts = ref<WeComMessageAttempt[]>([]), recordCount = ref(0), recordPage = ref(1), recordLoading = ref(false), recordError = ref('')
const variables = ['接收人', '消息内容', '发送时间', '系统地址'] as const
const previewTime = new Date().toLocaleString('sv-SE', { hour12: false })
let disposed = false, templateRequest = 0, recipientRequest = 0, recordRequest = 0
const selectedRecipient = computed(() => recipients.value.find(item => item.id === recipientId.value))
const dirty = computed(() => !saved.value?.is_saved || name.value !== saved.value.name || body.value !== saved.value.body)
const busy = computed(() => loading.value || saving.value || sending.value)
const validationError = computed(() => {
  if (!name.value.trim()) return '请填写模板名称。'
  if (name.value.trim().length > 50) return '模板名称最多 50 个字符。'
  if (!body.value.trim()) return '请填写消息正文。'
  for (const match of body.value.matchAll(/\{\{([^{}]*)\}\}/g)) {
    if (!(variables as readonly string[]).includes(match[1]!)) return `不支持的变量：${match[1]}。`
  }
  const remaining = body.value.replace(/\{\{(接收人|消息内容|发送时间|系统地址)\}\}/g, '')
  if (remaining.includes('{{') || remaining.includes('}}')) return '变量格式不完整，请使用下方变量按钮插入。'
  return ''
})
const renderedBody = computed(() => {
  const values = { 接收人: selectedRecipient.value?.employee_name || '接收员工', 消息内容: messageContent.value, 发送时间: previewTime, 系统地址: props.erpOrigin || '系统地址未配置' }
  return body.value.replace(/\{\{(接收人|消息内容|发送时间|系统地址)\}\}/g, (_, key: typeof variables[number]) => values[key])
})
const byteCount = computed(() => new TextEncoder().encode(renderedBody.value).length)
const canSave = computed(() => !!saved.value && !!etag.value && !busy.value && !stale.value && !validationError.value && !pendingRequest.value)
const canSend = computed(() => canSave.value && !dirty.value && !!selectedRecipient.value && !recipientLoading.value && !recipientError.value && !!messageContent.value.trim() && byteCount.value <= 2048 && !!props.erpOrigin)
const recordPages = computed(() => Math.max(1, Math.ceil(recordCount.value / 20)))
const statusLabels: Record<WeComMessageAttempt['status'], string> = { PROCESSING: '正在处理', ACCEPTED: '企业微信已受理', FAILED: '发送失败', UNCERTAIN: '结果未确认' }
function formatTime(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function applyTemplate(result: WeComMessageTemplateResponse) {
  saved.value = { ...result.data }; name.value = result.data.name; body.value = result.data.body; etag.value = result.etag; stale.value = false
}
async function loadTemplate() {
  if (busy.value) return
  const request = ++templateRequest
  loading.value = true; templateError.value = ''; notice.value = ''
  try { const result = await api.getWeComMessageTemplate(); if (!disposed && request === templateRequest) applyTemplate(result) }
  catch (error) { if (!disposed && request === templateRequest) templateError.value = '无法读取消息模板。' + api.wecomError(error) }
  finally { if (!disposed && request === templateRequest) loading.value = false }
}
async function saveTemplate() {
  if (!canSave.value) return
  saving.value = true; templateError.value = ''; notice.value = ''
  try {
    const result = await api.saveWeComMessageTemplate({ name: name.value.trim(), body: body.value }, etag.value)
    if (disposed) return
    applyTemplate(result); notice.value = '模板已保存。'
  } catch (error) {
    if (!disposed) { stale.value = isAxiosError(error) && error.response?.status === 412; templateError.value = stale.value ? '模板已被其他操作修改，请重新加载后核对。' : api.wecomError(error) }
  } finally { if (!disposed) saving.value = false }
}
async function loadRecipients() {
  if (recipientLoading.value) return
  const request = ++recipientRequest
  recipientLoading.value = true; recipientError.value = ''
  const items: WeComBinding[] = []
  try {
    let page = 1
    while (true) {
      const result = await api.getWeComBindings({ search: '', status: '', page })
      if (disposed || request !== recipientRequest) return
      items.push(...result.data)
      if (!result.data.length || result.page * result.page_size >= result.count) break
      page = result.page + 1
    }
    recipients.value = items.filter(item => item.role_status === 'active' || item.role_status === 'waiting')
    if (!recipients.value.some(item => item.id === recipientId.value)) recipientId.value = recipients.value.length === 1 ? recipients.value[0]!.id : ''
  } catch (error) {
    if (!disposed && request === recipientRequest) { recipientError.value = '无法读取已绑定员工。' + api.wecomError(error); recipients.value = []; recipientId.value = '' }
  } finally { if (!disposed && request === recipientRequest) recipientLoading.value = false }
}
async function loadRecords(page = 1) {
  const request = ++recordRequest
  recordLoading.value = true; recordError.value = ''
  try {
    const result = await api.getWeComMessageAttempts({ page, page_size: 20 })
    if (disposed || request !== recordRequest) return
    attempts.value = result.data; recordCount.value = result.count; recordPage.value = result.page
  } catch (error) { if (!disposed && request === recordRequest) recordError.value = '无法读取发送记录。' + api.wecomError(error) }
  finally { if (!disposed && request === recordRequest) recordLoading.value = false }
}
function applyAttempt(attempt: WeComMessageAttempt) {
  // 结果来自当前请求或按同一请求编号查询；不把上游“受理”解释成送达。
  void loadRecords(1)
  if (attempt.status === 'ACCEPTED' || attempt.status === 'FAILED') {
    pendingRequest.value = undefined
    sendError.value = attempt.status === 'FAILED' ? attempt.message || '发送失败，请核对配置与接收员工。' : ''
    notice.value = attempt.status === 'ACCEPTED' ? '企业微信已受理，不等于送达或已读。' : ''
  } else {
    sendError.value = attempt.status === 'PROCESSING' ? '请求仍在处理，请查询发送结果，不要重复发送。' : '结果未确认，可能已被企业微信受理。请查询发送结果，不要重复发送。'
  }
}
async function queryResult() {
  const pending = pendingRequest.value
  if (!pending || querying.value) return
  querying.value = true
  try {
    const result = await api.getWeComMessageAttempts({ page: 1, page_size: 20, idempotency_key: pending.data.idempotency_key })
    if (disposed || pendingRequest.value?.data.idempotency_key !== pending.data.idempotency_key) return
    const attempt = result.data.find(item => item.idempotency_key === pending.data.idempotency_key)
    if (attempt) applyAttempt(attempt)
    else sendError.value = '结果未确认，暂未查询到发送记录。请稍后再次查询，不要重复发送。'
  } catch (error) { if (!disposed) sendError.value = '结果未确认，查询暂时不可用。' + api.wecomError(error) }
  finally { if (!disposed) querying.value = false }
}
async function sendTest() {
  if (!canSend.value) return
  if (typeof crypto.randomUUID !== 'function') { sendError.value = '当前浏览器不支持安全请求编号，请使用 HTTPS 或 localhost 后重试。'; return }
  const pending = { data: { binding_id: recipientId.value, message_content: messageContent.value, idempotency_key: crypto.randomUUID() }, etag: etag.value }
  pendingRequest.value = pending; sending.value = true; sendError.value = ''; notice.value = ''
  try {
    const result = await api.sendWeComMessageTest(pending.data, pending.etag)
    if (!disposed) applyAttempt(result)
  } catch (error) {
    if (disposed) return
    const status = isAxiosError(error) ? error.response?.status : undefined
    if (status && [400, 401, 403, 404, 409, 412, 428, 429].includes(status)) {
      pendingRequest.value = undefined; stale.value = status === 412
      sendError.value = status === 412 ? '模板版本已变化，本次未发送。请重新加载模板后核对。' : api.wecomError(error)
    } else {
      sendError.value = '结果未确认，正在核实发送记录，请勿重复发送。'
      await queryResult()
    }
  } finally { if (!disposed) sending.value = false }
}
async function insertVariable(variable: typeof variables[number]) {
  const input = bodyInput.value
  if (!input || busy.value || pendingRequest.value) return
  const start = input.selectionStart, end = input.selectionEnd, value = `{{${variable}}}`
  body.value = body.value.slice(0, start) + value + body.value.slice(end)
  await nextTick(); input.focus(); input.setSelectionRange(start + value.length, start + value.length)
}
onMounted(() => { void loadTemplate(); void loadRecipients(); void loadRecords() })
onBeforeUnmount(() => { disposed = true; templateRequest++; recipientRequest++; recordRequest++; saved.value = undefined; pendingRequest.value = undefined; name.value = ''; body.value = ''; messageContent.value = ''; recipients.value = []; attempts.value = [] })
</script>

<template>
  <div class="wecom-message-panel">
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div v-if="templateError" class="error-banner" role="alert"><span>{{ templateError }}</span><button :disabled="busy" @click="loadTemplate">重新加载模板</button></div>
    <div v-if="loading && !saved" class="glass state-panel" role="status">正在读取消息模板…</div>
    <div v-else-if="saved" class="message-grid">
      <section class="content-card glass editor-card">
        <div class="section-heading"><h2>通用通知模板</h2><small>纯文本 · 单条模板</small></div>
        <label class="field" for="wecom-message-name"><span>模板名称</span><input id="wecom-message-name" v-model="name" maxlength="50" :disabled="busy || !!pendingRequest"><small>便于管理员识别，不会作为额外标题发送。</small></label>
        <label class="field" for="wecom-message-body"><span>消息正文</span><textarea id="wecom-message-body" ref="bodyInput" v-model="body" class="template-body" maxlength="8192" :disabled="busy || !!pendingRequest" spellcheck="false"></textarea></label>
        <div class="variables" aria-label="插入模板变量"><span>插入变量</span><button v-for="variable in variables" :key="variable" :disabled="busy || !!pendingRequest" @click="insertVariable(variable)">{{ variable }}</button></div>
        <div class="byte-line"><span>按变量替换后的正文预估，最多 2048 UTF-8 字节。</span><strong class="byte-count" :class="{ 'over-limit': byteCount > 2048 }" aria-live="polite">{{ byteCount }} / 2048 字节</strong></div>
        <p v-if="validationError" class="validation-error" role="alert">{{ validationError }}</p>
        <p v-else-if="byteCount > 2048" class="validation-error" role="alert">正文超过 2048 字节，请缩短内容后再发送。</p>
        <p class="editor-note">模板用于通用应用通知。右侧填写测试内容后，可先核对正文；本期仅支持向一位已绑定员工发送测试消息。</p>
        <div class="editor-footer"><small>{{ dirty ? '修改尚未保存 · 请先保存模板再测试' : '模板已保存，可发送测试' }}</small><button class="primary" :disabled="!canSave" @click="saveTemplate">{{ saving ? '正在保存…' : '保存模板' }}</button></div>
      </section>
      <div class="right-column">
        <section class="content-card glass">
          <div class="section-heading"><h2>消息预览</h2><small>正文实时更新</small></div>
          <div class="message-stage"><div class="app-line"><span class="app-icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24"><path d="M5 5h14v11H9l-4 4V5Z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 9h8M8 12h5" stroke="currentColor" stroke-width="1.6"/></svg></span><span>海趣 ERP · 应用通知</span></div><div class="message-bubble">{{ renderedBody }}</div></div>
          <p class="preview-caption">发送时间为预览值，实际时间及字节数以服务端为准；显示样式由企业微信客户端决定。</p>
        </section>
        <section class="content-card glass test-card">
          <div class="section-heading"><h2>测试发送</h2><small>单人测试</small></div>
          <label class="field" for="wecom-message-recipient"><span>接收员工</span><select id="wecom-message-recipient" v-model="recipientId" :disabled="recipientLoading || sending || !!pendingRequest"><option value="">{{ recipientLoading ? '正在读取已绑定员工…' : '请选择已绑定员工' }}</option><option v-for="recipient in recipients" :key="recipient.id" :value="recipient.id">{{ recipient.employee_name }} · {{ recipient.employee_code }}</option></select><small v-if="!recipientLoading && !recipientError && !recipients.length">暂无可用的已绑定员工，请先在“员工管理”中核对。</small><small v-else>仅显示已绑定且未停用的员工。</small></label>
          <div v-if="recipientError" class="error-banner" role="alert"><span>{{ recipientError }}</span><button :disabled="recipientLoading" @click="loadRecipients">重新读取员工</button></div>
          <label class="field" for="wecom-message-content"><span>测试内容</span><textarea id="wecom-message-content" v-model="messageContent" class="test-content" maxlength="2048" :disabled="sending || !!pendingRequest"></textarea></label>
          <div class="send-row"><small>保存模板后再测试；按已保存模板发送。发送结果不代表对方已读。</small><button class="primary" :disabled="!canSend" @click="sendTest">{{ sending ? '正在发送…' : '发送测试' }}</button></div>
          <div v-if="sendError" class="error-banner send-result" role="alert"><span>{{ sendError }}</span><button v-if="stale" :disabled="busy" @click="loadTemplate">重新加载模板</button><button v-if="pendingRequest" :disabled="sending || querying" @click="queryResult">{{ querying ? '正在查询…' : '查询发送结果' }}</button></div>
        </section>
      </div>
    </div>
    <section class="content-card glass message-records">
      <div class="section-heading"><h2>最近发送记录</h2><button :disabled="recordLoading" @click="loadRecords(recordPage)">刷新记录</button></div>
      <p v-if="recordLoading" class="empty-records" role="status">正在读取发送记录…</p>
      <p v-else-if="recordError" class="error-banner" role="alert">{{ recordError }}</p>
      <div v-else-if="!attempts.length" class="empty-records"><svg width="36" height="36" viewBox="0 0 40 40" aria-hidden="true"><rect x="9" y="5" width="22" height="30" rx="4"/><path d="M14 14h12M14 20h12M14 26h7"/></svg><div><strong>暂无发送记录</strong><p>首次测试后，可在这里查看应用发送处理结果。</p></div></div>
      <div v-else class="attempt-list"><article v-for="attempt in attempts" :key="attempt.id" class="attempt-row"><div><strong>{{ attempt.recipient_name }}</strong><small>{{ attempt.template_name }} · {{ formatTime(attempt.created_at) }}</small></div><div class="attempt-result"><span class="attempt-status" :class="attempt.status.toLowerCase()">{{ statusLabels[attempt.status] }}</span><p>{{ attempt.message }}</p><small v-if="attempt.status === 'ACCEPTED'">已受理不等于送达或已读。</small></div></article></div>
      <div v-if="recordCount > 20" class="record-pagination"><small>共 {{ recordCount }} 条</small><div><button :disabled="recordLoading || recordPage <= 1" @click="loadRecords(recordPage - 1)">上一页</button><span>{{ recordPage }} / {{ recordPages }}</span><button :disabled="recordLoading || recordPage >= recordPages" @click="loadRecords(recordPage + 1)">下一页</button></div></div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.wecom-message-panel { display: flex; flex-direction: column; gap: 14px; min-width: 0; font: 13px/1.5 var(--erp-font-body); color: var(--erp-color-text-primary); }
h2, p { margin: 0; } h2 { font: 600 16px/24px var(--erp-font-body); } small { font-size: 12px; color: var(--erp-color-text-secondary); }
.glass { border: 1px solid var(--erp-glass-border); border-radius: 16px; background: var(--erp-glass-surface); box-shadow: var(--erp-glass-shadow); backdrop-filter: var(--erp-glass-backdrop); }
button, input, select, textarea { box-sizing: border-box; font: inherit; color: var(--erp-color-text-primary); border: 1px solid var(--erp-input-border); border-radius: 8px; background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow); }
button, input, select { height: 32px; padding: 0 12px; } button { cursor: pointer; white-space: nowrap; background: var(--erp-button-secondary-surface); box-shadow: var(--erp-button-secondary-shadow); } button:hover:not(:disabled) { background: var(--erp-button-secondary-hover-surface); } button.primary { color: var(--erp-button-primary-text); background: var(--erp-button-primary-surface); border-color: var(--erp-button-primary-border); box-shadow: var(--erp-button-primary-shadow); } button:disabled { cursor: not-allowed; opacity: .55; } input, select, textarea { min-width: 0; width: 100%; } textarea { padding: 11px 12px; line-height: 1.8; resize: vertical; } :focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.message-grid { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, 1fr); gap: 14px; align-items: stretch; }.content-card { padding: 16px 20px; min-width: 0; }.section-heading, .editor-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }.section-heading { margin-bottom: 14px; }.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }.field > span { font-weight: 500; }.field small { font-size: 11px; line-height: 17px; }.editor-card { display: flex; flex-direction: column; gap: 16px; }.editor-card .section-heading { margin-bottom: 0; }.template-body { min-height: 267px; }.variables { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin-top: 2px; }.variables span { font-size: 12px; color: var(--erp-color-text-secondary); margin-right: 3px; }.variables button { font-size: 12px; height: 27px; padding: 0 9px; border-color: var(--erp-color-border); color: var(--erp-color-brand); background: var(--erp-color-info-soft); box-shadow: none; }.byte-line { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; color: var(--erp-color-text-secondary); font-size: 11px; }.byte-count { white-space: nowrap; font-weight: 500; }.over-limit, .validation-error { color: var(--erp-color-danger); }.validation-error { font-size: 12px; }.editor-note { padding: 11px 12px; border-radius: 8px; background: var(--erp-color-info-soft); color: var(--erp-color-text-secondary); font-size: 12px; line-height: 1.8; }.editor-footer { margin-top: auto; padding-top: 4px; }.editor-footer small { font-size: 11px; }.right-column { display: flex; flex-direction: column; gap: 14px; min-width: 0; }.message-stage { border-radius: 10px; padding: 14px; background: var(--erp-color-info-soft); }.app-line { display: flex; align-items: center; gap: 8px; color: var(--erp-color-text-secondary); font-size: 12px; margin-bottom: 9px; }.app-icon { display: grid; place-items: center; width: 25px; height: 25px; border-radius: 7px; color: var(--erp-button-primary-text); background: var(--erp-button-primary-surface); }.message-bubble { padding: 13px 15px; border: 1px solid var(--erp-color-border-subtle); border-radius: 4px 11px 11px 11px; background: var(--erp-glass-inner-background); font-size: 13px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }.preview-caption { margin-top: 8px; font-size: 11px; color: var(--erp-color-text-secondary); }.test-card .field + .field { margin-top: 12px; }.test-content { min-height: 76px; }.send-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; }.send-row small { font-size: 11px; max-width: 310px; }.notice { padding: 10px 12px; border: 1px solid var(--erp-color-border-subtle); border-radius: 8px; color: var(--erp-color-text-secondary); background: var(--erp-color-info-soft); font-size: 12px; }.error-banner { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border: 1px solid var(--erp-color-danger-border); border-radius: 8px; background: var(--erp-color-danger-soft); font-size: 12px; overflow-wrap: anywhere; }.send-result { margin-top: 12px; flex-wrap: wrap; }.state-panel { padding: 40px; text-align: center; }.empty-records { display: flex; align-items: center; justify-content: center; gap: 13px; min-height: 92px; color: var(--erp-color-text-secondary); }.empty-records svg { stroke: var(--erp-color-text-muted); fill: none; stroke-width: 1.5; flex: none; }.empty-records strong { font-size: 13px; font-weight: 500; }.empty-records p { font-size: 11px; margin-top: 3px; }.attempt-row { display: flex; justify-content: space-between; gap: 20px; padding: 13px 0; }.attempt-row + .attempt-row { border-top: 1px solid var(--erp-color-border); }.attempt-row small { display: block; margin-top: 4px; font-size: 11px; }.attempt-result { text-align: right; overflow-wrap: anywhere; }.attempt-result p { font-size: 12px; margin-top: 4px; }.attempt-status { font-size: 12px; color: var(--erp-color-info); }.attempt-status.accepted { color: var(--erp-color-success); }.attempt-status.failed { color: var(--erp-color-danger); }.attempt-status.uncertain { color: var(--erp-color-warning); }.record-pagination, .record-pagination > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.record-pagination { padding-top: 12px; border-top: 1px solid var(--erp-color-border); }
@media (max-width: 1050px) { .message-grid { grid-template-columns: 1fr; }.content-card { padding: 16px; }.template-body { min-height: 230px; } }
@media (max-width: 850px) { .editor-card { gap: 14px; } }
@media (max-width: 640px) { .wecom-message-panel { gap: 10px; }.section-heading { gap: 10px; }.section-heading small { font-size: 11px; text-align: right; }.byte-line { gap: 8px; }.editor-footer { align-items: flex-start; gap: 12px; }.editor-footer small { max-width: 205px; }.send-row { align-items: flex-end; }.send-row small { max-width: 205px; }.message-stage { padding: 10px; }.error-banner, .attempt-row { flex-wrap: wrap; }.attempt-result { text-align: left; }.record-pagination { flex-wrap: wrap; } }
</style>
