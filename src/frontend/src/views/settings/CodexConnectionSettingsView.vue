<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { isAxiosError, isCancel } from 'axios'
import { ElButton, ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/codexConnection'
import type { CodexConnectionAction, CodexConnectionResponse, CodexConnectionSnapshot, CodexLoginChallenge } from '@/types/codexConnection'

defineProps<{ embedded?: boolean }>()
const auth = useAuthStore()
const permitted = computed(() => auth.isAuthenticated && !auth.waitingForRole && auth.managementCan('access_control.manage_codex_connection'))
const allowed = computed(() => permitted.value && auth.identityReady)
const connection = ref<CodexConnectionSnapshot>()
const etag = ref(''), model = ref(''), error = ref(''), notice = ref('')
const challenge = ref<CodexLoginChallenge>()
const challengeDisplayEnded = ref(false)
const loading = ref(false), writing = ref(false), confirming = ref(false)
const busy = computed(() => loading.value || writing.value || confirming.value)
const operating = computed(() => connection.value?.operation != null)
const ownsOperation = computed(() => !!connection.value?.operation && connection.value.operation.actor_id === auth.user?.employee?.id)
const canCancel = computed(() => allowed.value && ownsOperation.value && connection.value?.operation?.can_cancel && !busy.value && !!etag.value)
const canEdit = computed(() => allowed.value && !!connection.value && !!etag.value && !busy.value && !operating.value)
const canChangeAccount = computed(() => allowed.value && !!etag.value && !busy.value
  && (!operating.value || ['test', 'discover', 'extract'].includes(connection.value?.operation?.action || '')))
const modelChanged = computed(() => !!connection.value && model.value !== connection.value.selected_model)
const validModel = computed(() => !!model.value && connection.value?.models.some(item => item.id === model.value))
const statusText = computed(() => ({ DISCONNECTED: '未连接', CONNECTED: '已连接，模型尚未验证', READY: '已连接，所选模型最小测试通过',
  LOGIN_PENDING: '等待官方授权', DRAINING: '正在暂停新任务并等待当前任务结束', ERROR: '连接异常', UNKNOWN: '连接状态未知' })[connection.value?.status || 'UNKNOWN'])
let generation = 0, disposed = false
let pollTimer: ReturnType<typeof setTimeout> | undefined
let expiryTimer: ReturnType<typeof setTimeout> | undefined
let readController: AbortController | undefined

function stopPolling() { if (pollTimer !== undefined) clearTimeout(pollTimer); pollTimer = undefined }
function clearChallenge() { if (expiryTimer !== undefined) clearTimeout(expiryTimer); expiryTimer = undefined; challenge.value = undefined; challengeDisplayEnded.value = false }
function endChallengeDisplay() { clearChallenge(); challengeDisplayEnded.value = true }
function current(version: number) { return !disposed && version === generation && allowed.value }
function reset() {
  generation++; stopPolling(); clearChallenge(); readController?.abort(); readController = undefined
  connection.value = undefined; etag.value = ''; model.value = ''; error.value = ''; notice.value = ''
  loading.value = false; writing.value = false; confirming.value = false
}
function apply(result: CodexConnectionResponse) {
  const previous = connection.value
  if (previous?.operation?.id !== result.data.operation?.id || previous?.config_generation !== result.data.config_generation
    || result.data.status !== 'LOGIN_PENDING') clearChallenge()
  connection.value = result.data; etag.value = result.etag
  if (!previous || previous.selected_model !== result.data.selected_model || previous.config_generation !== result.data.config_generation) model.value = result.data.selected_model
}
function schedulePolling() {
  stopPolling()
  if (!disposed && allowed.value && operating.value) pollTimer = setTimeout(() => { void load() }, 2000)
}
async function readChallenge(version: number, signal: AbortSignal) {
  const operation = connection.value?.operation
  if (connection.value?.status !== 'LOGIN_PENDING' || !operation || !ownsOperation.value || !operation.can_cancel) { clearChallenge(); return }
  if (challenge.value?.operation_id === operation.id || challengeDisplayEnded.value) return
  try {
    const result = await api.getCodexLoginChallenge(operation.id, signal)
    if (!current(version) || connection.value?.operation?.id !== operation.id) return
    const remaining = Date.parse(result.expires_at) - Date.now()
    if (remaining <= 0) { endChallengeDisplay(); return }
    challenge.value = result
    expiryTimer = setTimeout(endChallengeDisplay, Math.min(remaining, 2_147_483_647))
  } catch (caught) {
    if (!current(version) || isCancel(caught)) return
    // 409 只表示授权信息尚未就绪，下一次状态轮询再读取。
    if (isAxiosError(caught) && caught.response?.status === 409) return
    clearChallenge(); error.value = api.codexConnectionError(caught)
  }
}
async function load() {
  if (!allowed.value || disposed || loading.value) return
  stopPolling(); loading.value = true
  const version = generation
  const controller = new AbortController(); readController = controller
  try {
    const result = await api.getCodexConnection(controller.signal)
    if (!current(version)) return
    apply(result)
    await readChallenge(version, controller.signal)
  } catch (caught) {
    if (current(version) && !isCancel(caught)) {
      etag.value = ''; clearChallenge(); error.value = api.codexConnectionError(caught)
      if (isAxiosError(caught) && [401, 403].includes(caught.response?.status || 0)) connection.value = undefined
    }
  } finally { if (current(version)) { loading.value = false; schedulePolling() } }
}
async function refreshView() { error.value = ''; notice.value = ''; await load() }
async function perform(action: CodexConnectionAction | 'model') {
  if (!allowed.value || busy.value || !etag.value) return
  if (action === 'login-cancel' ? !canCancel.value : action === 'switch' || action === 'disconnect' ? !canChangeAccount.value : !canEdit.value) return
  if (action === 'model' && (!validModel.value || !modelChanged.value)) return
  if (action === 'test' && (!connection.value?.account || !validModel.value || modelChanged.value)) return
  const version = generation, expectedEtag = etag.value, operationId = connection.value?.operation?.id
  if (action === 'switch' || action === 'disconnect') {
    confirming.value = true
    try {
      await ElMessageBox.confirm(action === 'switch'
        ? '更换账号会暂停新任务，等待当前任务结束后退出旧账号。新账号完成授权并通过模型测试后才恢复待处理任务。继续吗？'
        : '断开连接会暂停新任务，并等待当前任务结束。已有解析结果和生产单据会保留。继续吗？',
      action === 'switch' ? '更换 Codex 账号' : '断开 Codex 连接', { confirmButtonText: '继续', cancelButtonText: '返回', type: 'warning' })
    } catch (caught) {
      if (caught !== 'cancel' && caught !== 'close' && current(version)) error.value = '无法确认操作，请重试。'
      return
    } finally { if (current(version)) confirming.value = false }
    if (!current(version) || etag.value !== expectedEtag) return
  }
  stopPolling(); readController?.abort(); clearChallenge(); error.value = ''; notice.value = ''; writing.value = true
  try {
    const result = action === 'model' ? await api.saveCodexModel(model.value, expectedEtag)
      : await api.runCodexConnectionAction(action, expectedEtag, operationId)
    if (!current(version)) return
    apply(result)
    notice.value = action === 'model' ? '模型已保存，请完成最小测试。' : '操作已受理，实际结果以连接状态为准。'
  } catch (caught) {
    if (!current(version) || isCancel(caught)) return
    error.value = api.codexConnectionError(caught)
  } finally {
    if (current(version)) { writing.value = false; await load() }
  }
}
function formatTime(value: string | null | undefined) {
  if (!value) return '未知'
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? '未知' : time.toLocaleString('zh-CN', { hour12: false })
}
function canClose() {
  if (writing.value || confirming.value) { ElMessage.warning('操作正在提交，请稍候再关闭。'); return false }
  clearChallenge(); stopPolling(); readController?.abort(); generation++; loading.value = false
  return true
}
defineExpose({ canClose })
watch([allowed, () => auth.identityRequestGeneration], () => { reset(); if (allowed.value) void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { disposed = true; reset() })
</script>

<template>
  <section class="codex-connection system-settings-theme" data-testid="codex-connection-settings">
    <p v-if="!permitted" role="alert">当前账号无权管理 Codex 连接。</p>
    <p v-else-if="!allowed" role="status">正在核对 ERP 登录身份，请稍候。</p>
    <template v-else>
      <header class="connection-heading"><div><h2 v-if="!embedded">Codex 连接设置</h2><p>管理 ERP 专属账号。账号连接与模型测试分别显示。</p></div>
        <ElButton data-action="read" :disabled="busy" @click="refreshView">{{ loading ? '读取中…' : '重新读取' }}</ElButton></header>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="notice" role="status">{{ notice }}</p>
      <div v-if="connection" class="connection-content">
        <section class="card-shell"><h3>连接状态</h3>
          <p class="connection-status" data-testid="connection-status">{{ statusText }}</p>
          <dl><dt>当前账号</dt><dd>{{ connection.account?.display_name || '未连接或未知' }}</dd>
            <dt>账号套餐</dt><dd>{{ connection.account?.plan_type || '未知' }}</dd>
            <dt>最近检查</dt><dd>{{ formatTime(connection.last_checked_at) }}</dd>
            <dt>最近最小测试</dt><dd>{{ formatTime(connection.last_test_at) }}</dd></dl>
          <p v-if="connection.paused">新任务已暂停；恢复状态以服务器返回为准。</p>
          <p v-if="operating" role="status">操作正在进行，请等待状态更新。{{ ownsOperation ? '' : '本次操作由其他管理员发起。' }}</p>
          <p v-if="connection.status === 'ERROR'">{{ connection.error_code === 'USAGE_LIMIT_EXCEEDED'
            ? '官方用量已达限制，新任务已暂停。请等待额度恢复或更换可用账号后测试。'
            : '连接未就绪，请重新读取状态，或重新授权后测试。' }}</p>
          <div class="actions">
            <ElButton v-if="!connection.account" data-action="login" type="primary" :disabled="!canEdit" @click="perform('login')">连接账号</ElButton>
            <ElButton v-if="connection.account" data-action="switch" :disabled="!canChangeAccount" @click="perform('switch')">更换账号</ElButton>
            <ElButton v-if="connection.account" data-action="disconnect" :disabled="!canChangeAccount" @click="perform('disconnect')">断开连接</ElButton>
            <ElButton data-action="refresh" :disabled="!canEdit" @click="perform('refresh')">刷新账号与限额</ElButton>
            <ElButton v-if="connection.operation?.can_cancel && ownsOperation" data-action="cancel" :disabled="!canCancel" @click="perform('login-cancel')">取消本次授权</ElButton>
          </div>
          <p v-if="challengeDisplayEnded" role="status">验证码的本地展示已结束，仍在等待官方完成状态；请以连接状态更新为准。</p>
          <div v-if="challenge" class="authorization" data-testid="authorization">
            <p>打开官方页面，输入本次验证码完成授权。</p>
            <a :href="challenge.verification_url" target="_blank" rel="noopener noreferrer">前往 OpenAI 官方授权页面</a>
            <p>验证码：<strong class="user-code">{{ challenge.user_code }}</strong></p>
            <p>本地展示截止：{{ formatTime(challenge.expires_at) }}，官方授权结果以连接状态为准。关闭窗口会隐藏验证码，不代表取消授权。</p>
          </div>
        </section>
        <section class="card-shell"><h3>模型与最小测试</h3>
          <label class="model-field">选定模型
            <select v-model="model" aria-label="选定模型" :disabled="!canEdit || !connection.models.length">
              <option value="" disabled>请选择可用模型</option>
              <option v-if="model && !connection.models.some(item => item.id === model)" :value="model" disabled>{{ model }}（当前不可用）</option>
              <option v-for="item in connection.models" :key="item.id" :value="item.id">{{ item.display_name || item.id }}</option>
            </select>
          </label>
          <p v-if="!connection.models.length">当前没有可用模型信息，请刷新账号状态。</p>
          <p v-if="modelChanged">模型尚未保存；保存后需要重新测试。</p>
          <div class="actions"><ElButton data-action="save-model" :disabled="!canEdit || !validModel || !modelChanged" @click="perform('model')">保存模型</ElButton>
            <ElButton data-action="test" type="primary" :disabled="!canEdit || !connection.account || !validModel || modelChanged" @click="perform('test')">运行最小测试</ElButton></div>
        </section>
        <section class="card-shell"><h3>官方限额</h3>
          <p v-if="!connection.rate_limits || !connection.rate_limits.windows.length">使用限额：未知</p>
          <ul v-else class="limit-list"><li v-for="(window, index) in connection.rate_limits.windows" :key="index">
            {{ window.name || '额度窗口' }}：{{ window.used_percent == null ? '用量未知' : `已用 ${window.used_percent}%` }}
            <span>窗口 {{ window.window_minutes == null ? '未知' : `${window.window_minutes} 分钟` }}；重置时间 {{ formatTime(window.resets_at) }}</span>
          </li></ul>
          <p>额外额度：{{ connection.rate_limits?.credits?.unlimited === true ? '不设限' : connection.rate_limits?.credits?.balance ?? '未知' }}</p>
          <p>额外额度是否可用：{{ connection.rate_limits?.credits?.has_credits == null ? '未知' : connection.rate_limits.credits.has_credits ? '可用' : '不可用' }}</p>
          <small>更新时间：{{ formatTime(connection.limits_updated_at) }}</small>
        </section>
      </div>
      <p v-else-if="loading" role="status">正在读取连接状态…</p>
    </template>
  </section>
</template>

<style scoped lang="scss">
.codex-connection { padding: 12px; min-width: 0; }
.connection-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
h2, h3, p { margin: 0 0 12px; }
.connection-content { display: grid; gap: 16px; }
.card-shell { padding: 20px; border: 1px solid var(--erp-color-border, #dce2e9); border-radius: 10px; }
.connection-status { font-weight: 600; }
dl { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; margin: 0 0 16px; }
dt { color: var(--erp-color-text-secondary); }
dd { margin: 0; overflow-wrap: anywhere; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }
.actions :deep(.el-button + .el-button) { margin-left: 0; }
.authorization { margin-top: 18px; padding: 16px; background: var(--erp-color-selected, #eef5ff); border-radius: 8px; }
.authorization a { display: inline-block; margin-bottom: 12px; color: var(--erp-color-brand, #1677ff); }
.user-code { font-family: monospace; font-size: 20px; user-select: all; }
.model-field { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
select { min-height: 36px; width: min(360px, 100%); padding: 6px 10px; border: 1px solid var(--erp-color-border, #dce2e9); border-radius: 6px; color: inherit; background: var(--erp-color-surface, #fff); }
.error { color: var(--el-color-danger); }
.limit-list { padding-left: 20px; }
.limit-list li { margin-bottom: 10px; }
.limit-list span { display: block; color: var(--erp-color-text-secondary); }
@media (max-width: 680px) { .connection-heading { align-items: flex-start; } .card-shell { padding: 14px; } .model-field { align-items: flex-start; flex-direction: column; gap: 8px; } }
</style>
