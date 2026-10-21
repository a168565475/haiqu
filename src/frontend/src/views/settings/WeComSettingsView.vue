<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { ElButton } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import WeComMessagePanel from './WeComMessagePanel.vue'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/wecom'
import type { WeComAudit, WeComConfig, WeComConfigResponse, WeComConfigWrite } from '@/types/wecom'

const auth = useAuthStore()
const router = useRouter()
const permitted = computed(() => auth.managementCan('access_control.manage_wecom'))
const tab = ref<'config' | 'messages'>('config')
const messagesOpened = ref(false)
const config = ref<WeComConfig>()
const etag = ref('')
const loading = ref(false), saving = ref(false), checking = ref(false), stale = ref(false)
const loadError = ref(''), operationError = ref(''), notice = ref('')
const form = reactive<WeComConfigWrite>({ corp_id: '', agent_id: '', erp_origin: '', enabled: false, secret: '', callback_token: '', callback_aes_key: '' })
const credentialKeys = ['secret', 'callback_token', 'callback_aes_key'] as const
const credentialLabels = { secret: '应用 Secret', callback_token: '消息回调 Token', callback_aes_key: 'EncodingAESKey' }
const credentialReadErrors = computed(() => credentialKeys.filter(key => config.value?.[key] === null || config.value?.credential_read_errors.includes(key)))
const credentialReadMessage = computed(() => credentialReadErrors.value.map(key => `${credentialLabels[key]}读取失败`).join('；'))
function credentialStatus(key: typeof credentialKeys[number], configured: boolean) { return credentialReadErrors.value.includes(key) ? '读取失败' : configured ? '已配置' : '未配置' }
const dirty = computed(() => {
  const saved = config.value
  return !!saved && (form.corp_id !== saved.corp_id || form.agent_id !== saved.agent_id || form.erp_origin !== saved.erp_origin || form.enabled !== saved.enabled || credentialKeys.some(key => {
    const value = form[key]?.trim()
    return !!value && value !== saved[key]
  }))
})
const busy = computed(() => loading.value || saving.value || checking.value)
const connectionLabel = computed(() => config.value?.secret === null ? '登录凭据读取失败' : config.value?.last_check_status === 'SUCCESS' ? '连接检查通过' : config.value?.last_check_status === 'FAILED' ? '连接检查未通过' : '尚未验证')
let disposed = false

function clearCredentials() {
  for (const key of credentialKeys) {
    form[key] = ''
    if (config.value) config.value[key] = ''
  }
}
function applyConfig(result: WeComConfigResponse) {
  config.value = { ...result.data }; etag.value = result.etag
  Object.assign(form, { corp_id: result.data.corp_id, agent_id: String(result.data.agent_id), erp_origin: result.data.erp_origin, enabled: result.data.enabled, secret: result.data.secret ?? '', callback_token: result.data.callback_token ?? '', callback_aes_key: result.data.callback_aes_key ?? '' })
  stale.value = false
}
async function loadConfig() {
  if (!permitted.value || busy.value) return
  loading.value = true; loadError.value = ''; operationError.value = ''; notice.value = ''
  try { const result = await api.getWeComConfig(); if (!disposed) applyConfig(result) }
  catch (error) { if (!disposed) loadError.value = '无法读取企业微信配置。' + api.wecomError(error) }
  finally { loading.value = false }
}
async function saveConfig() {
  if (!permitted.value || busy.value || stale.value || !config.value || !etag.value) return
  operationError.value = ''; notice.value = ''
  if (form.callback_aes_key?.trim() && form.callback_aes_key.trim().length !== 43) { operationError.value = 'EncodingAESKey 应为 43 位，请按企业微信后台生成值填写。'; return }
  if (form.callback_token?.trim() && !/^[A-Za-z0-9]{1,32}$/.test(form.callback_token.trim())) { operationError.value = '消息回调 Token 应为不超过 32 位的字母或数字。'; return }
  saving.value = true
  const payload: WeComConfigWrite = { corp_id: form.corp_id, agent_id: form.agent_id, erp_origin: form.erp_origin, enabled: form.enabled }
  for (const key of credentialKeys) {
    const value = form[key]?.trim()
    if (value && value !== config.value[key]) payload[key] = value
  }
  try {
    const result = await api.saveWeComConfig(payload, etag.value)
    if (disposed) return
    applyConfig(result); notice.value = credentialReadErrors.value.length ? '配置已保存；仍有凭据读取失败，请重新填写对应字段。' : '配置已保存。'
  }
  catch (error) { if (!disposed) { stale.value = isAxiosError(error) && error.response?.status === 412; operationError.value = api.wecomError(error) } }
  finally { saving.value = false }
}
async function checkConnection() {
  if (!config.value || config.value.secret === null || busy.value || dirty.value || stale.value || !etag.value) return
  checking.value = true; operationError.value = ''; notice.value = ''
  try {
    const result = await api.checkWeComConnection(etag.value)
    if (disposed) return
    applyConfig(result)
    notice.value = config.value.last_check_status === 'SUCCESS' ? '服务器连接检查通过；仍需从企业微信工作台验证实际登录。' : '服务器连接检查未通过，请核对配置。'
  } catch (error) { if (!disposed) { stale.value = isAxiosError(error) && error.response?.status === 412; operationError.value = api.wecomError(error) } }
  finally { checking.value = false }
}
async function copyAddress(value: string) {
  try { await navigator.clipboard.writeText(value); notice.value = '已复制。' }
  catch { operationError.value = '浏览器未允许复制，请选中地址手动复制。' }
}

function selectTab(value: 'config' | 'messages') { tab.value = value; if (value === 'messages') messagesOpened.value = true }
function tabKey(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const target = event.key === 'Home' ? 'config' : event.key === 'End' ? 'messages' : tab.value === 'config' ? 'messages' : 'config'
  selectTab(target); document.getElementById(`wecom-tab-${target}`)?.focus()
}

const auditDialog = ref(false), audits = ref<WeComAudit[]>([]), auditLoading = ref(false), auditError = ref('')
const auditPage = ref(1), auditCount = ref(0)
const auditPages = computed(() => Math.max(1, Math.ceil(auditCount.value / 20)))
let auditRequest = 0
async function loadAudits(page = 1) {
  const request = ++auditRequest
  auditLoading.value = true; auditError.value = ''
  try { const result = await api.getWeComAudits(page); if (request === auditRequest) { audits.value = result.data; auditCount.value = result.count; auditPage.value = result.page } }
  catch (error) { if (request === auditRequest) auditError.value = '无法读取操作记录。' + api.wecomError(error) }
  finally { if (request === auditRequest) auditLoading.value = false }
}
function openAudits() { auditDialog.value = true; void loadAudits() }
function formatTime(value: string | null) { if (!value) return '尚未检查'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN', { hour12: false }) }
function auditAction(action: string) { return ({ MANUAL_BIND: '管理员绑定', AUTO_CREATE: '首次登录建档', CONFIG_UPDATE: '配置变更', CONFIG_CHECK: '连接检查', OAUTH_LOGIN: '企业微信登录', DIRECTORY_CREATE: '通讯录新建员工', DIRECTORY_CONFIRM_NEW: '确认新建员工', DIRECTORY_MATCH: '人工核对员工', DIRECTORY_DEPARTMENTS_FILL: '补充员工部门', DEPARTMENT_MAPPING_UPDATE: '调整部门映射' } as Record<string, string>)[action] || '企业微信操作' }
function auditResult(result: string) { return ({ SUCCESS: '成功', FAILED: '失败', CONFLICT: '冲突拒绝', REJECTED: '已拒绝' } as Record<string, string>)[result] || '已记录' }
onMounted(() => { void loadConfig() })
onBeforeUnmount(() => { disposed = true; clearCredentials(); config.value = undefined; etag.value = ''; auditRequest++ })
</script>

<template>
  <div class="wecom-page">
    <section v-if="!permitted" class="glass state-panel"><div><h1>无企业微信管理权限</h1><p>当前账号不能维护企业微信配置，请联系 admin。</p></div></section>
    <template v-else>
      <header class="page-heading glass">
        <div class="heading-line"><div class="heading-info"><h1>企业微信管理</h1><span class="tag" :class="{ success: config?.enabled }">{{ config?.enabled ? '已启用' : '未启用' }}</span></div>
          <div v-if="tab === 'config'" class="heading-actions"><button @click="openAudits">操作记录</button><button :disabled="busy || !config?.has_secret || config?.secret === null || !config?.encryption_ready || dirty || stale || !!loadError" @click="checkConnection">{{ checking ? '正在检查…' : '检查连接' }}</button><button class="primary" :disabled="busy || !config || stale || !!loadError" @click="saveConfig">{{ saving ? '正在保存…' : '保存配置' }}</button></div>
        </div>
        <p class="heading-copy">管理工作台登录与应用消息。员工同步与身份核对请进入员工管理，角色仍由权限管理分配。<button v-if="auth.canReadAccessDirectory" class="text-button" @click="router.push({ name: 'employee-list' })">进入员工管理 →</button><button v-if="auth.hasPermission('attendance.view_attendance')" class="text-button" @click="router.push({ name: 'wecom-attendance' })">进入考勤管理 →</button></p>
        <div class="tabs" role="tablist" aria-label="企业微信管理功能" @keydown="tabKey">
          <button id="wecom-tab-config" class="tab" role="tab" :aria-selected="tab === 'config'" aria-controls="wecom-config-panel" :tabindex="tab === 'config' ? 0 : -1" @click="selectTab('config')">接入配置</button>
          <button id="wecom-tab-messages" class="tab" role="tab" :aria-selected="tab === 'messages'" aria-controls="wecom-messages-panel" :tabindex="tab === 'messages' ? 0 : -1" @click="selectTab('messages')">消息模板</button>
        </div>
      </header>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <section v-if="messagesOpened" v-show="tab === 'messages'" id="wecom-messages-panel" role="tabpanel" aria-labelledby="wecom-tab-messages"><WeComMessagePanel :erp-origin="config?.erp_origin || ''" /></section>
      <section v-show="tab === 'config'" id="wecom-config-panel" role="tabpanel" aria-labelledby="wecom-tab-config">
        <div v-if="loading" class="glass state-panel" role="status">正在读取企业微信配置…</div>
        <div v-else-if="loadError" class="glass state-panel" role="alert"><div><h2>暂时无法加载配置</h2><p>{{ loadError }}</p><button @click="loadConfig">重新加载配置</button></div></div>
        <template v-else-if="config">
          <div v-if="operationError" class="error-banner" role="alert"><span>{{ operationError }}</span><button :disabled="busy" @click="loadConfig">重新加载配置</button></div>
          <div v-if="credentialReadMessage" class="error-banner credential-read-error" role="alert">{{ credentialReadMessage }}。请重新填写对应字段并保存；留空会保留原有凭据。</div>
          <div class="config-grid">
            <section class="content-card glass"><div class="section-heading"><h2>应用配置</h2><small>企业内部自建应用</small></div>
              <div class="form-grid">
                <label class="field" for="wecom-corp"><span>企业 ID <small>CorpID</small></span><input id="wecom-corp" :value="form.corp_id" readonly><small>企业微信后台 · 我的企业 → 企业信息</small></label>
                <label class="field" for="wecom-agent"><span>应用 ID <small>AgentId</small></span><input id="wecom-agent" :value="form.agent_id" readonly><small>企业微信后台 · 应用管理 → 对应自建应用</small></label>
                <label class="field" for="wecom-origin"><span>ERP 访问地址</span><input id="wecom-origin" :value="form.erp_origin" readonly></label>
                <label class="field" for="wecom-secret"><span>应用 Secret <small>· {{ credentialStatus('secret', config.has_secret) }}</small></span><input id="wecom-secret" v-model="form.secret" type="text" autocomplete="off" :disabled="busy || stale" maxlength="512" placeholder="填写密钥，留空保留已保存值"><small>已保存的密钥会直接显示；修改后请保存，留空保留原值。</small></label>
              </div>
              <div class="settings-row"><div><strong>启用企业微信登录</strong><p>完成配置与连接检查后即可启用。成员身份沿用已有绑定；遇到同名员工需先人工核对，具备有效权限后才能进入系统。</p></div><button class="switch" type="button" role="switch" :aria-checked="form.enabled" aria-label="启用企业微信登录" :disabled="busy || stale || (!form.enabled && (!config.configuration_complete || config.last_check_status !== 'SUCCESS'))" @click="form.enabled = !form.enabled"></button></div>
              <p v-if="dirty" class="footnote">有未保存的修改；请先保存，再检查连接。</p>
            </section>
            <aside class="content-card glass"><div class="section-heading"><h2>接入状态</h2></div><div class="status-lead"><strong>{{ connectionLabel }}</strong><p>{{ config.last_check_message || '请先保存配置，再检查连接' }}</p></div>
              <dl class="status-list"><div><dt>企业与应用参数</dt><dd>{{ config.configuration_complete ? '已配置' : '待完善' }}</dd></div><div><dt>应用 Secret</dt><dd>{{ credentialStatus('secret', config.has_secret) }}</dd></div><div><dt>服务器加密配置</dt><dd>{{ config.encryption_ready ? '就绪' : '未配置' }}</dd></div><div><dt>服务器连接</dt><dd>{{ config.secret === null ? '需修复凭据' : config.last_check_status === 'SUCCESS' ? '检查通过' : config.last_check_status === 'FAILED' ? '检查失败' : '未检查' }}</dd></div><div><dt>最近检查</dt><dd>{{ formatTime(config.last_checked_at) }}</dd></div><div><dt>工作台实际登录</dt><dd>需实际验证</dd></div></dl>
              <p class="footnote">连接检查通过后，还需从企业微信工作台实际打开一次，确认员工身份与登录结果。</p>
            </aside>
          </div>
          <section class="content-card glass callback-card"><div class="section-heading"><h2>消息回调凭据</h2><span class="callback-summary">Token：{{ credentialStatus('callback_token', config.has_callback_token) }}<span>EncodingAESKey：{{ credentialStatus('callback_aes_key', config.has_callback_aes_key) }}</span></span></div><p class="callback-explanation">仅保存凭据，本期不接收消息事件</p><div class="form-grid">
            <label class="field" for="wecom-token"><span>Token <small>· {{ credentialStatus('callback_token', config.has_callback_token) }}</small></span><input id="wecom-token" v-model="form.callback_token" type="text" autocomplete="off" :disabled="busy || stale" maxlength="32" placeholder="留空保留已保存值"><small>不超过 32 位的字母或数字，用于后续消息回调校验。</small></label>
            <label class="field" for="wecom-aes"><span>EncodingAESKey <small>· {{ credentialStatus('callback_aes_key', config.has_callback_aes_key) }}</small></span><input id="wecom-aes" v-model="form.callback_aes_key" type="text" autocomplete="off" :disabled="busy || stale" maxlength="43" placeholder="留空保留已保存值"><small>43 位消息加密密钥；与网页登录 Secret 分开保存。</small></label>
          </div></section>
          <section class="content-card glass addresses"><div class="section-heading"><h2>企业微信后台填写信息</h2><small>接入完成后使用以下地址</small></div>
            <div v-for="item in [{ label: '工作台应用主页', value: config.erp_origin }, { label: '网页登录回调', value: config.callback_url }, { label: '网页授权可信域名', value: config.trusted_domain }]" :key="item.label" class="address-row"><span class="muted">{{ item.label }}</span><span class="address-value">{{ item.value }}</span><button class="text-button" :aria-label="`复制${item.label}`" @click="copyAddress(item.value)">复制</button></div>
            <p class="footnote">将使用人员加入应用可见范围，并按企业微信后台要求配置服务器可信 IP。</p>
          </section>
        </template>
      </section>
    </template>

    <AppWindowDialog v-model="auditDialog" title="操作记录" :width="640" :min-width="280" :minimizable="false" destroy-on-close>
      <div class="wecom-dialog-content"><p v-if="auditLoading" role="status">正在读取操作记录…</p><div v-else-if="auditError" class="error-banner" role="alert">{{ auditError }}<button @click="loadAudits(auditPage)">重试</button></div><template v-else><p v-if="!audits.length" class="muted">暂无操作记录</p><article v-for="audit in audits" :key="audit.id" class="audit-entry"><header><strong>{{ auditAction(audit.action) }}</strong><span class="tag">{{ auditResult(audit.result) }}</span></header><p v-if="audit.user_id">企业微信：{{ audit.user_id }} → ERP：{{ audit.employee_name || '未绑定' }}</p><p>操作人：{{ audit.actor_name || '系统' }}</p><p>{{ audit.message }}</p><small>{{ formatTime(audit.occurred_at) }}</small></article></template></div>
      <template #footer><div class="pagination"><ElButton :disabled="auditLoading || auditPage <= 1" @click="loadAudits(auditPage - 1)">上一页</ElButton><span>{{ auditPage }} / {{ auditPages }}</span><ElButton :disabled="auditLoading || auditPage >= auditPages" @click="loadAudits(auditPage + 1)">下一页</ElButton></div><ElButton @click="auditDialog = false">关闭</ElButton></template>
    </AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
.wecom-page { display: flex; flex-direction: column; gap: 14px; min-width: 0; color: var(--erp-color-text-primary); font: 13px/1.5 var(--erp-font-body); }
.wecom-page, .wecom-dialog-content { h1, h2, p { margin: 0; } h2 { font-size: 16px; line-height: 24px; font-weight: 600; } }
// 外层容器强制标题尺寸，旧设置主题另设宋体；仅在本页恢复已确认的标题样式。
#erp-main-content .wecom-page h1 { font: 700 36px/44px var(--erp-font-body) !important; }
.glass { border: 1px solid var(--erp-glass-border); border-radius: 16px; background: var(--erp-glass-surface); box-shadow: var(--erp-glass-shadow); backdrop-filter: var(--erp-glass-backdrop); }
.wecom-page button, .wecom-page input, .wecom-page select, .wecom-dialog-content input, .wecom-dialog-content select, .wecom-dialog-content button { box-sizing: border-box; height: 32px; padding: 0 12px; border: 1px solid var(--erp-input-border); border-radius: 8px; color: var(--erp-color-text-primary); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow); font: inherit; }
.wecom-page button { cursor: pointer; white-space: nowrap; background: var(--erp-button-secondary-surface); box-shadow: var(--erp-button-secondary-shadow); }
.wecom-page button:hover:not(:disabled) { background: var(--erp-button-secondary-hover-surface); }
.wecom-page button:disabled { cursor: not-allowed; color: var(--erp-color-text-disabled); background: var(--erp-color-disabled); box-shadow: none; }
.wecom-page button.primary { color: var(--erp-button-primary-text); background: var(--erp-button-primary-surface); border-color: var(--erp-button-primary-border); box-shadow: var(--erp-button-primary-shadow); }
.wecom-page button.primary:disabled { opacity: .55; }
.wecom-page :focus-visible, .wecom-dialog-content :focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.wecom-page input, .wecom-page select, .wecom-dialog-content input, .wecom-dialog-content select { min-width: 0; width: 100%; }
.wecom-page input[readonly] { background: var(--erp-input-readonly-background); }
.wecom-page input::placeholder, .wecom-dialog-content input::placeholder { color: var(--erp-input-placeholder); }
.muted, small { color: var(--erp-color-text-secondary); } small { font-size: 12px; }
.page-heading { padding: 14px 16px 0; }.heading-line, .heading-info, .heading-actions, .section-heading, .pagination { display: flex; align-items: center; gap: 8px; }.heading-line, .section-heading { justify-content: space-between; gap: 16px; }.heading-info { gap: 14px; }.heading-copy { margin: 5px 0 8px !important; color: var(--erp-color-text-secondary); font-size: 12px; }
.tabs { display: flex; gap: 28px; }.wecom-page button.tab { position: relative; height: 40px; padding: 0 2px; border: 0; border-radius: 0; background: transparent; box-shadow: none; color: var(--erp-color-text-secondary); }.wecom-page button.tab[aria-selected='true'] { color: var(--erp-color-brand); font-weight: 600; }.tab[aria-selected='true']::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3px; border-radius: 3px 3px 0 0; background: var(--erp-tab-active-indicator); }
.config-grid { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 14px; }.content-card { padding: 16px 20px; min-width: 0; }.section-heading { margin-bottom: 12px; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px 20px; }.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }.field > span { font-weight: 500; }.field small { font-size: 11px; line-height: 17px; }.settings-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; border-top: 1px solid var(--erp-color-border); padding-top: 16px; margin-top: 18px; }.settings-row p { font-size: 12px; color: var(--erp-color-text-secondary); margin-top: 4px; }.wecom-page button.switch { width: 36px; height: 20px; padding: 0; border-radius: 999px; position: relative; background: var(--erp-color-border-strong); box-shadow: none; flex: none; }.switch::before { content: ''; position: absolute; left: 3px; top: 3px; border-radius: 50%; width: 12px; height: 12px; background: var(--erp-color-surface); }.wecom-page button.switch[aria-checked='true'] { background: var(--erp-color-brand); }.switch[aria-checked='true']::before { left: 19px; }
.callback-card > .section-heading { margin-bottom: 0; }.callback-summary { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 12px; font-size: 12px; color: var(--erp-color-text-secondary); }.callback-explanation { margin: 14px 0 !important; color: var(--erp-color-text-secondary); font-size: 12px; }
.status-lead { margin: 6px 0 18px; }.status-lead strong { font-size: 18px; line-height: 28px; }.status-lead p { font-size: 12px; color: var(--erp-color-text-secondary); }.status-list { display: flex; flex-direction: column; gap: 13px; margin: 0; padding: 14px 0; border-block: 1px solid var(--erp-color-border); font-size: 12px; }.status-list > div { display: flex; justify-content: space-between; gap: 12px; }.status-list dd { margin: 0; color: var(--erp-color-text-secondary); text-align: right; }.addresses, .callback-card { margin-top: 14px; }.address-row { display: grid; grid-template-columns: 122px minmax(0, 1fr) 48px; align-items: center; gap: 12px; padding: 9px 0; font-size: 12px; }.address-row + .address-row { border-top: 1px solid var(--erp-color-border-subtle); }.address-value { overflow-wrap: anywhere; }.wecom-page button.text-button { height: auto; min-height: 24px; padding: 0; border: 0; background: transparent; box-shadow: none; color: var(--erp-color-brand); font-size: 12px; }.footnote { margin-top: 12px !important; font-size: 12px; line-height: 20px; color: var(--erp-color-text-secondary); }.subtle-line, .notice { padding: 10px 12px; border: 1px solid var(--erp-color-border-subtle); border-radius: 8px; color: var(--erp-color-text-secondary); background: var(--erp-color-info-soft); font-size: 12px; }
.pagination button { height: 28px; padding: 0 9px; }.tag { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 9px; box-sizing: border-box; border: 1px solid var(--erp-tag-info-border); border-radius: 999px; font-size: 12px; line-height: 18px; color: var(--erp-tag-info-text); background: var(--erp-tag-info-background); white-space: nowrap; }.tag.warning { background: var(--erp-tag-warning-background); border-color: var(--erp-tag-warning-border); color: var(--erp-tag-warning-text); }.tag.success { background: var(--erp-tag-success-background); border-color: var(--erp-tag-success-border); color: var(--erp-tag-success-text); }
.error-banner { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; margin-bottom: 14px; border: 1px solid var(--erp-color-danger-border); border-radius: 8px; background: var(--erp-color-danger-soft); font-size: 12px; }.state-panel { min-height: 300px; display: flex; align-items: center; justify-content: center; padding: 24px; text-align: center; }.state-panel p { margin: 8px 0 18px; }.wecom-dialog-content { display: flex; flex-direction: column; gap: 16px; font: 13px/1.5 var(--erp-font-body); }.audit-entry + .audit-entry { border-top: 1px solid var(--erp-color-border); padding-top: 14px; }.audit-entry header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }.audit-entry p { overflow-wrap: anywhere; }
@media (min-width: 1700px) { .config-grid { grid-template-columns: minmax(0, 1fr) 350px; }.content-card { padding: 22px 24px; }.form-grid { gap: 22px 24px; }.address-row { padding: 13px 0; } }
@media (max-width: 1050px) { .config-grid { grid-template-columns: 1fr; }.content-card { padding: 16px; }.heading-actions { flex-wrap: wrap; justify-content: flex-end; } }
@media (max-width: 640px) { .wecom-page { gap: 10px; }.heading-line { align-items: flex-start; flex-direction: column; gap: 10px; }#erp-main-content .wecom-page h1 { font-size: 28px !important; line-height: 38px !important; }.heading-info { gap: 10px; }.form-grid { grid-template-columns: 1fr; gap: 14px; }.address-row { grid-template-columns: minmax(0, 1fr) 40px; gap: 4px 10px; }.address-row > .muted { grid-column: 1/-1; }.section-heading { align-items: flex-start; }.section-heading small { max-width: 150px; text-align: right; }.error-banner { flex-wrap: wrap; }.callback-card > .section-heading { flex-direction: column; gap: 8px; }.callback-summary { justify-content: flex-start; gap: 6px 12px; } }
</style>
