<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, Close } from '@element-plus/icons-vue'
import { ElButton } from 'element-plus'
import { useNotificationsStore } from '@/stores/notifications'
import { useAuthStore } from '@/stores/auth'
import type { NotificationItem } from '@/types/notifications'

const router = useRouter()
const store = useNotificationsStore()
const auth = useAuthStore()
const trigger = ref<HTMLButtonElement>()
const panel = ref<HTMLElement>()
const closeButton = ref<HTMLButtonElement>()
const shaking = ref(false)
const position = ref({ left: '8px', top: '48px' })
const totalPages = computed(() => Math.max(1, Math.ceil(store.count / store.pageSize)))
const label = computed(() => store.countError ? '消息，未读数量更新失败'
  : store.unread === null ? '消息，未读数量尚未加载' : `消息，${store.unread} 条未读`)
let shakeTimer: ReturnType<typeof setTimeout> | undefined
let media: MediaQueryList | undefined
let disposed = false

function stopShake() { clearTimeout(shakeTimer); shaking.value = false }
function updatePosition() {
  const rect = trigger.value?.getBoundingClientRect()
  if (!rect) return
  const width = Math.min(360, window.innerWidth - 16)
  position.value = {
    left: `${Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8))}px`,
    top: `${rect.bottom + 8}px`,
  }
}
function close(restoreFocus = true) {
  store.close()
  if (restoreFocus) trigger.value?.focus()
}
async function toggle() {
  if (store.opened) { close(); return }
  stopShake()
  updatePosition()
  void store.open()
  await nextTick()
  closeButton.value?.focus()
}
function outside(event: Event) {
  const target = event.target
  if (store.opened && target instanceof Node && !panel.value?.contains(target) && !trigger.value?.contains(target)) close(false)
}
function escape(event: KeyboardEvent) {
  if (event.key === 'Escape' && store.opened) { event.preventDefault(); event.stopPropagation(); close() }
}
function motionChanged() { if (media?.matches) stopShake() }
function formatTime(value: string) {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai',
  }).format(date) : '时间未知'
}
async function activate(item: NotificationItem) {
  const account = auth.user
  const destination = await store.readAndResolve(item)
  if (!destination || disposed || !store.opened || auth.user !== account) return
  try {
    if (!router.hasRoute(destination.name)) { store.actionError = '消息已读，但对应业务页面尚未开放。'; return }
    const failure = await router.push(destination)
    if (disposed) return
    if (failure) { store.actionError = '消息已读，页面切换未完成，请重试。'; return }
    close()
  } catch {
    if (!disposed) store.actionError = '消息已读，但页面跳转失败，请重试。'
  }
}

watch(() => store.arrival, (next, previous) => {
  if (next <= previous || store.opened || media?.matches) return
  stopShake()
  shaking.value = true
  shakeTimer = setTimeout(stopShake, 650)
})
watch(() => store.opened, opened => { if (opened) stopShake() })
watch(() => store.unread, unread => { if (unread === null) stopShake() })
onMounted(() => {
  media = window.matchMedia('(prefers-reduced-motion: reduce)')
  media.addEventListener('change', motionChanged)
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
  document.addEventListener('keydown', escape, true)
  window.addEventListener('resize', updatePosition)
  store.start()
})
onBeforeUnmount(() => {
  disposed = true
  store.stop()
  stopShake()
  media?.removeEventListener('change', motionChanged)
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', outside)
  document.removeEventListener('keydown', escape, true)
  window.removeEventListener('resize', updatePosition)
})
</script>

<template>
  <div class="header-messages">
    <button ref="trigger" type="button" class="header-messages__trigger" data-message-toggle
      :class="{ 'is-shaking': shaking }" :aria-label="label" :title="store.countError || label"
      aria-haspopup="dialog" :aria-expanded="store.opened" aria-controls="header-message-panel" @click="toggle">
      <Bell aria-hidden="true" />
      <span v-if="store.unread !== null && store.unread > 0" class="header-messages__badge" aria-hidden="true">{{ store.unread > 99 ? '99+' : store.unread }}</span>
      <span v-if="store.countError" class="header-messages__error-dot" aria-hidden="true">!</span>
    </button>
    <Teleport to="body">
      <section v-if="store.opened" id="header-message-panel" ref="panel" class="header-message-panel" :style="position"
        role="dialog" aria-modal="false" aria-labelledby="header-message-title" @keydown.esc.stop.prevent="close()">
        <header class="header-message-panel__header">
          <strong id="header-message-title">消息</strong>
          <span>{{ store.unread === null ? '未读数量未知' : `${store.unread} 条未读` }}</span>
          <button ref="closeButton" type="button" aria-label="关闭消息" @click="close()"><Close aria-hidden="true" /></button>
        </header>
        <div v-if="store.countError" class="header-message-panel__notice" role="alert">
          {{ store.countError }} <ElButton link :disabled="store.countLoading || store.blocked" @click="store.refreshUnread()">重试未读数</ElButton>
        </div>
        <div v-if="store.actionError" class="header-message-panel__notice" role="alert">{{ store.actionError }}</div>
        <div class="header-message-panel__list" :aria-busy="store.loading">
          <p v-if="store.loading && !store.items.length" class="header-message-panel__state" role="status">正在加载消息…</p>
          <div v-else-if="store.error" class="header-message-panel__state" role="alert">
            <p>{{ store.error }}</p><ElButton :disabled="store.blocked" @click="store.retry()">重新加载</ElButton>
          </div>
          <p v-else-if="!store.items.length" class="header-message-panel__state" role="status">{{ store.count ? '此页暂无消息，请返回上一页。' : '暂无消息' }}</p>
          <template v-else>
            <button v-for="item in store.items" :key="item.id" type="button" class="header-message-panel__item"
              :class="{ 'is-unread': !item.read_at }" :disabled="store.loading || !!store.actionId" :aria-busy="store.actionId === item.id"
              :aria-label="`${item.read_at ? '已读' : '未读'}，${item.title}，${item.target_accessible ? '查看业务' : '标记已读并重新检查访问权限'}`"
              @click="activate(item)">
              <span class="header-message-panel__title">{{ item.title }}<small>{{ item.read_at ? '已读' : '未读' }}</small></span>
              <span class="header-message-panel__body">{{ item.body }}</span>
              <time :datetime="item.created_at">{{ formatTime(item.created_at) }}</time>
              <span v-if="store.actionId === item.id" role="status">正在标记并打开…</span>
            </button>
          </template>
        </div>
        <footer class="header-message-panel__footer">
          <button type="button" :disabled="store.loading || !!store.actionId || store.page <= 1" @click="store.loadPage(store.page - 1)">上一页</button>
          <span aria-live="polite">{{ store.page }} / {{ totalPages }} 页</span>
          <button type="button" :disabled="store.loading || !!store.actionId || store.page >= totalPages" @click="store.loadPage(store.page + 1)">下一页</button>
        </footer>
      </section>
    </Teleport>
  </div>
</template>

<style scoped lang="scss">
.header-messages { display: flex; flex: none; }
.header-messages__trigger {
  position: relative; display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; padding: 6px; border: 0; border-radius: var(--erp-radius-control);
  color: var(--erp-header-user-color); background: transparent; cursor: pointer;
  svg { width: 20px; height: 20px; }
  &:hover { background: var(--erp-menu-hover-background); }
  &:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
  &.is-shaking { animation: header-message-shake 600ms ease-out 1; transform-origin: 50% 20%; }
}
.header-messages__badge, .header-messages__error-dot {
  position: absolute; top: -4px; right: -5px; box-sizing: border-box; min-width: 18px; height: 18px;
  padding: 0 4px; border-radius: 10px; color: var(--erp-color-text-inverse); background: var(--erp-color-danger);
  font: 11px/18px var(--erp-font-body); font-variant-numeric: tabular-nums;
}
.header-messages__error-dot { top: 18px; width: 14px; height: 14px; min-width: 14px; padding: 0; line-height: 14px; }
.header-message-panel {
  position: fixed; z-index: 2100; box-sizing: border-box; display: flex; flex-direction: column;
  width: min(360px, calc(100vw - 16px)); max-height: calc(100dvh - 88px);
  border: 1px solid var(--erp-color-border); border-radius: 5px;
  color: var(--erp-color-text-primary); background: var(--erp-color-surface);
  font: 13px/20px var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
  button { font: inherit; color: inherit; cursor: pointer; }
  button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: -2px; }
  button:disabled { cursor: default; }
}
.header-message-panel__header, .header-message-panel__footer {
  display: flex; flex: none; align-items: center; gap: 8px; padding: 8px 12px;
  button { display: inline-flex; align-items: center; justify-content: center; min-height: 32px; padding: 0 8px; border: 0; border-radius: 5px; background: transparent; }
  button:hover:not(:disabled) { background: var(--erp-menu-hover-background); }
}
.header-message-panel__header {
  border-bottom: 1px solid var(--erp-color-border);
  strong { font-size: 14px; font-weight: 600; }
  span { color: var(--erp-color-text-secondary); }
  button { width: 32px; margin-left: auto; padding: 8px; svg { width: 16px; height: 16px; } }
}
.header-message-panel__list { min-height: 0; overflow: auto; scrollbar-width: thin; scrollbar-color: var(--erp-scrollbar-thumb) var(--erp-scrollbar-track); }
.header-message-panel__item {
  display: flex; flex-direction: column; gap: 6px; width: 100%; padding: 12px 16px;
  border: 0; border-bottom: 1px solid var(--erp-color-border); text-align: left; overflow-wrap: anywhere; background: transparent;
  &:last-child { border-bottom: 0; }
  &.is-unread { background: var(--erp-color-selected); }
  &:hover:not(:disabled) { background: var(--erp-menu-hover-background); }
  &:disabled { opacity: .7; }
  time { font-size: 12px; color: var(--erp-color-text-secondary); }
}
.header-message-panel__title { display: flex; align-items: baseline; gap: 8px; font-weight: 600; small { flex: none; font-size: 11px; font-weight: 400; color: var(--erp-color-brand); white-space: nowrap; } }
.header-message-panel__body { white-space: pre-wrap; }
.header-message-panel__footer { justify-content: space-between; border-top: 1px solid var(--erp-color-border); button:disabled { color: var(--erp-color-text-secondary); } }
.header-message-panel__state { padding: 20px 16px; margin: 0; p { margin: 0 0 8px; } }
.header-message-panel__notice { padding: 8px 12px; color: var(--erp-color-danger); overflow-wrap: anywhere; }
@keyframes header-message-shake { 0%, 100% { transform: rotate(0); } 20% { transform: rotate(-12deg); } 40% { transform: rotate(10deg); } 60% { transform: rotate(-7deg); } 80% { transform: rotate(4deg); } }
@media (prefers-reduced-motion: reduce) { .header-messages__trigger.is-shaking { animation: none; } }
</style>
