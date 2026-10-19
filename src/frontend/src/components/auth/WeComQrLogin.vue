<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { cancelWeComQrSession, createWeComQrSession, ExistingAuthSessionError, getAuthErrorMessage } from '@/api/auth'
import type { AuthResponse, WeComQrSession } from '@/types/auth'
import { buildWeComCallbackUrl, loadWeComLoginSdk, validateWeComQrSession, WeComQrError } from './wecomLoginSdk'
import type { WeComLoginPanel } from './wecomLoginSdk'

const props = defineProps<{ nextPath: string }>()
const emit = defineEmits<{ authenticated: [response: AuthResponse] }>()
const host = ref<HTMLElement>()
const status = ref<'loading' | 'ready' | 'expired' | 'error' | 'cancelling' | 'redirecting'>('loading')
const errorMessage = ref('')
const panelCommunication = ref<'pending' | 'confirmed'>('pending')
const showPanelHint = ref(false)
let generation = 0
let disposed = false
let completing = false
let session: WeComQrSession | null = null
let panel: WeComLoginPanel | null = null
let expiryTimer: number | undefined
let panelInitTimer: number | undefined
let pendingCreate: Promise<WeComQrSession> | null = null
let cancellation: Promise<boolean> | null = null

function removePanel() {
  window.clearTimeout(expiryTimer)
  expiryTimer = undefined
  window.clearTimeout(panelInitTimer)
  panelInitTimer = undefined
  showPanelHint.value = false
  panelCommunication.value = 'pending'
  panel?.unmount()
  panel = null
}

function confirmPanelCommunication() {
  window.clearTimeout(panelInitTimer)
  panelInitTimer = undefined
  panelCommunication.value = 'confirmed'
  showPanelHint.value = false
}

function expire() {
  removePanel()
  status.value = 'expired'
}

async function cancel(): Promise<boolean> {
  if (completing) return false
  if (cancellation) return cancellation
  generation += 1
  removePanel()
  status.value = 'cancelling'
  const active = session
  const pending = pendingCreate
  cancellation = (async () => {
    let target = active
    if (!target && pending) {
      // 没有取得 state 时尚未展示二维码；取得后必须定向取消，不能影响其他标签页。
      try { target = await pending } catch { return true }
    }
    if (!target) return true
    try {
      await cancelWeComQrSession(target.state)
      if (session?.state === target.state) session = null
      return true
    } catch {
      session = target
      status.value = 'error'
      errorMessage.value = '旧二维码取消失败，请检查网络后重试；暂时不能切换或刷新。'
      return false
    }
  })()
  try { return await cancellation } finally { cancellation = null }
}

async function start() {
  if (disposed) return
  const run = ++generation
  status.value = 'loading'
  errorMessage.value = ''
  panelCommunication.value = 'pending'
  showPanelHint.value = false
  const request = createWeComQrSession(props.nextPath)
  pendingCreate = request
  try {
    const created = await request
    if (pendingCreate === request) pendingCreate = null
    if (disposed || run !== generation) return
    session = created
    validateWeComQrSession(created)
    const sdk = await loadWeComLoginSdk()
    if (disposed || run !== generation || !host.value) return
    validateWeComQrSession(created)
    expiryTimer = window.setTimeout(expire, Math.max(0, Date.parse(created.expires_at) - Date.now()))
    panelInitTimer = window.setTimeout(() => {
      if (disposed || run !== generation || status.value !== 'ready' || panelCommunication.value === 'confirmed') return
      // 官方桌面端探测可能超过一分钟；未回调不能证明二维码不可用。
      showPanelHint.value = true
    }, 75_000)
    let panelFailed = false
    panel = sdk.createWWLoginPanel({
      el: host.value,
      params: {
        login_type: created.login_type, appid: created.appid, agentid: created.agentid,
        redirect_uri: created.redirect_uri, state: created.state,
        redirect_type: 'callback', panel_size: 'small', lang: 'zh',
      },
      onCheckWeComLogin(result) {
        // 这是桌面端探测的异步回调，不能作为二维码显示或扫码成功的前置条件。
        if (disposed || run !== generation || (status.value !== 'loading' && status.value !== 'ready')
          || typeof result?.isWeComLogin !== 'boolean') return
        if (Date.parse(created.expires_at) <= Date.now()) { expire(); return }
        confirmPanelCommunication()
      },
      onLoginSuccess({ code }) {
        if (disposed || run !== generation || status.value !== 'ready') return
        if (Date.parse(created.expires_at) <= Date.now()) { expire(); return }
        try {
          const callback = buildWeComCallbackUrl(created, code)
          confirmPanelCommunication()
          completing = true
          status.value = 'redirecting'
          removePanel()
          window.location.assign(callback)
        } catch (error) {
          completing = false
          status.value = 'error'
          errorMessage.value = error instanceof WeComQrError ? error.message : '无法继续企业微信登录，请重新扫码'
        }
      },
      onLoginFail() {
        if (disposed || run !== generation || (status.value !== 'loading' && status.value !== 'ready')) return
        panelFailed = true
        status.value = 'error'
        errorMessage.value = '企业微信扫码登录未完成，请刷新二维码重试。'
        removePanel()
      },
    })
    if (panelFailed) { removePanel(); return }
    status.value = 'ready'
  } catch (error) {
    if (disposed || run !== generation) return
    removePanel()
    if (error instanceof ExistingAuthSessionError) {
      completing = true
      status.value = 'redirecting'
      emit('authenticated', error.response)
      return
    }
    status.value = 'error'
    errorMessage.value = error instanceof WeComQrError ? error.message : getAuthErrorMessage(error)
  } finally {
    if (pendingCreate === request) pendingCreate = null
  }
}

async function refresh() {
  if (status.value === 'loading' || status.value === 'cancelling' || completing) return
  if (await cancel()) await start()
}

onMounted(start)
onBeforeUnmount(() => {
  disposed = true
  removePanel()
  if (!completing) void cancel().then(cancelled => {
    if (!cancelled) console.error('企业微信扫码会话取消失败，旧二维码需等待服务端到期。')
  })
})
defineExpose({ cancel })
</script>

<template>
  <div class="wecom-login" :data-panel-communication="panelCommunication" :aria-busy="status === 'loading' || status === 'cancelling'">
    <div v-show="status === 'ready'" ref="host" class="wecom-panel" aria-label="企业微信官方扫码登录" />
    <div v-if="status !== 'ready'" class="wecom-status" role="status" aria-live="polite">
      <template v-if="status === 'loading'">正在加载企业微信二维码…</template>
      <template v-else-if="status === 'cancelling'">正在取消旧二维码…</template>
      <template v-else-if="status === 'redirecting'">正在验证登录信息…</template>
      <template v-else-if="status === 'expired'">
        <strong>二维码已失效</strong><span>请刷新二维码后重新扫码。</span>
      </template>
      <template v-else><strong>暂时无法扫码登录</strong><span>{{ errorMessage }}</span></template>
    </div>
    <p v-if="showPanelHint && status === 'ready'" class="wecom-panel-hint" role="status">
      若二维码未显示，请检查网络或浏览器限制后刷新。
    </p>
    <button
      v-if="status === 'ready' || status === 'expired' || status === 'error'"
      type="button"
      class="wecom-refresh"
      @click="refresh"
    >{{ status === 'ready' ? '刷新二维码' : '重新加载' }}</button>
  </div>
</template>

<style scoped>
.wecom-login { width: 100%; text-align: center; color: var(--erp-color-text-inverse); }
.wecom-panel, .wecom-status { width: 320px; max-width: 100%; min-height: 380px; margin: 0 auto; }
.wecom-panel { background: transparent; border: 0; box-shadow: none; }
.wecom-panel :deep(iframe) { display: block; border: 0; }
.wecom-status { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; font-size: 14px; line-height: 24px; }
.wecom-status span { max-width: 300px; opacity: .82; }
.wecom-panel-hint { width: 320px; max-width: 100%; margin: 14px auto 0; font-size: 12px; line-height: 20px; opacity: .82; }
.wecom-refresh { margin-top: 18px; padding: 2px 6px; border: 0; background: transparent; color: inherit; font: inherit; font-size: 13px; text-decoration: underline; text-underline-offset: 4px; cursor: pointer; }
.wecom-refresh:focus-visible { outline: 2px solid currentColor; outline-offset: 4px; }
</style>
