<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch, type Component } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import SystemSettingsIcon from '@/components/settings/SystemSettingsIcon.vue'
import { systemSettings, canOpenSystemSetting, type SystemSettingsEntry, type SystemSettingsKey } from '@/config/systemSettings'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const visibleEntries = computed(() => systemSettings.filter(entry => canOpenSystemSetting(auth, entry.key)))
const activeEntry = ref<SystemSettingsEntry>()
const visible = ref(false)
const checking = ref(false)
const loading = ref(false)
const loadError = ref(false)
const currentView = shallowRef<Component>()
const page = ref<{ canClose?: () => boolean | Promise<boolean> }>()
const activeAllowed = computed(() => activeEntry.value !== undefined && canOpenSystemSetting(auth, activeEntry.value.key))
let requestVersion = 0
let disposed = false

const loaders: Record<SystemSettingsKey, () => Promise<{ default: Component }>> = {
  production: () => import('./ProductionDataView.vue'),
  email: () => import('./EmailAccountSettingsView.vue'),
  inquiry: () => import('./InquiryHandlingSettingsView.vue'),
  masterData: () => import('./MasterDataCenterView.vue'),
  numberRules: () => import('./NumberRulesView.vue'),
  notifications: () => import('./NotificationRulesView.vue'),
  sendRecords: () => import('./NotificationDeliveryRecordsView.vue'),
  theme: () => import('./ThemeSettingsView.vue'),
  parameters: () => import('./ReferenceDataSettingsView.vue'),
  wecom: () => import('./WeComSettingsView.vue'),
  access: () => import('./AccessManagementView.vue'),
  dictionary: () => import('./ReferenceDataSettingsView.vue'),
}
const pageProps = computed(() => {
  const key = activeEntry.value?.key
  if (key === 'parameters' || key === 'dictionary') return { section: key }
  if (['production', 'email', 'inquiry', 'masterData', 'numberRules', 'notifications', 'sendRecords', 'access', 'wecom'].includes(key || '')) return { embedded: true }
  return {}
})

async function loadSelectedPage() {
  const entry = activeEntry.value
  if (!entry || !activeAllowed.value) return
  const version = ++requestVersion
  loading.value = true
  loadError.value = false
  try {
    const module = await loaders[entry.key]()
    if (version === requestVersion && visible.value && activeAllowed.value) currentView.value = module.default
  } catch (error) {
    if (version === requestVersion) {
      console.error('配置页面加载失败', error)
      loadError.value = true
    }
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

async function openSetting(entry: SystemSettingsEntry) {
  if (checking.value) return
  if (visible.value) {
    ElMessage.info('请先还原或关闭当前配置窗口。')
    return
  }
  checking.value = true
  try {
    await auth.ensureFreshAuthentication()
    if (disposed) return
    if (!auth.isAuthenticated) {
      await router.replace({ name: 'login', query: { redirect: '/settings' } })
      return
    }
    if (auth.waitingForRole) {
      await router.replace({ name: 'waiting-role' })
      return
    }
    if (!canOpenSystemSetting(auth, entry.key)) {
      ElMessage.warning('当前账号没有该配置的访问权限。')
      return
    }
    activeEntry.value = entry
    currentView.value = undefined
    visible.value = true
    await loadSelectedPage()
  } catch (error) {
    console.error('配置入口身份检查失败', error)
    if (!disposed) ElMessage.error('无法确认登录状态，请稍后重试。')
  } finally {
    checking.value = false
  }
}

async function canLeave() {
  if (!visible.value || !activeAllowed.value) return true
  return (await page.value?.canClose?.()) !== false
}
async function beforeClose(done: () => void) {
  if (await canLeave()) done()
}
function closed() {
  requestVersion++
  currentView.value = undefined
  activeEntry.value = undefined
  loadError.value = false
  loading.value = false
}
watch(activeAllowed, allowed => {
  if (!allowed && visible.value) {
    requestVersion++
    currentView.value = undefined
    loading.value = false
  } else if (allowed && visible.value && !currentView.value && !loading.value && !loadError.value) {
    void loadSelectedPage()
  }
})
onBeforeRouteLeave(canLeave)
onBeforeUnmount(() => { disposed = true; requestVersion++ })
</script>

<template>
  <section class="system-settings-hub" aria-label="系统配置" data-testid="system-settings-hub">
    <div v-if="!visibleEntries.length" class="settings-hub-state">当前账号没有可用的配置入口。</div>
    <div v-else class="settings-hub-grid">
      <button v-for="entry in visibleEntries" :key="entry.key" v-glass-spotlight.tilt type="button"
        class="settings-hub-card" :disabled="checking" :data-settings-key="entry.key" @click="openSetting(entry)">
        <span class="settings-hub-icon"><SystemSettingsIcon :name="entry.name" /></span>
        <span class="settings-hub-copy"><strong>{{ entry.name }}</strong><span>{{ entry.description }}</span></span>
      </button>
    </div>
    <AppWindowDialog v-model="visible" :title="activeEntry?.name || '系统配置'" :width="1120" :height="740"
      fullscreen edge-to-edge destroy-on-close :close-on-click-modal="false" :before-close="beforeClose"
      class="system-settings-window" @closed="closed">
      <div class="settings-page-host">
        <div v-if="!activeAllowed" class="settings-hub-state">当前账号已无权访问此配置，请关闭窗口。</div>
        <div v-else-if="loadError" class="settings-hub-state" role="alert"><p>配置页面加载失败，请重试。</p><button type="button" @click="loadSelectedPage">重新加载</button></div>
        <div v-else-if="loading" class="settings-hub-state" role="status">正在加载配置…</div>
        <component :is="currentView" v-else-if="currentView" ref="page" :key="activeEntry?.key" v-bind="pageProps" />
      </div>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/workbench' as workbench;
.system-settings-hub { min-width: 0; }
.settings-hub-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.settings-hub-card {
  @include workbench.glass-card;
  display: grid;
  grid-template-columns: 122px minmax(0, 1fr);
  align-items: center;
  gap: 5px;
  padding: 10px;
  min-width: 0;
  color: var(--erp-color-text-primary);
  text-align: left;
  font: inherit;
  cursor: pointer;
  --sidebar-icon-ink: var(--erp-menu-icon-ink);
  --sidebar-icon-accent: var(--erp-menu-accent);
  --sidebar-icon-fill: var(--erp-menu-icon-fill);
  --sidebar-icon-muted: var(--erp-menu-icon-muted);
  &:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 3px; }
  &:disabled { cursor: progress; }
}
.settings-hub-icon { display: block; width: 122px; height: 122px; transition: transform 200ms cubic-bezier(.2,.8,.2,1); }
.settings-hub-icon :deep(svg) { stroke-width: 2; transform-origin: 50% 60%; }
.settings-hub-copy { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.settings-hub-copy strong { font-size: 17px; line-height: 24px; font-weight: 600; overflow-wrap: anywhere; }
.settings-hub-copy > span { font-size: 12px; line-height: 18px; color: var(--erp-color-text-secondary); overflow-wrap: anywhere; }
.settings-hub-state { padding: 32px 16px; text-align: center; color: var(--erp-color-text-secondary); }
.settings-hub-state button { @include workbench.secondary-button; border-width: 1px; border-style: solid; padding: 6px 16px; cursor: pointer; }
.settings-page-host { flex: 1; min-height: 0; min-width: 0; overflow: auto; }
:global(.app-window-dialog.system-settings-window) { --settings-window-background: var(--erp-page-background, var(--erp-color-page)); background: var(--settings-window-background); }
:global(.app-window-dialog.system-settings-window.is-maximized) { border: 0; border-radius: 0; }
:global(.system-settings-window > .app-window-dialog__body) { display: flex; min-height: 0; padding: 10px; overflow: hidden; background: transparent; }
@media (hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference) {
  .settings-hub-card:hover:not(:disabled) .settings-hub-icon { transform: translateY(-3px) scale(1.07); }
  .settings-hub-card:hover:not(:disabled) .settings-hub-icon :deep(svg) { animation: settings-icon-nod 380ms cubic-bezier(.2,.8,.2,1) both; }
}
@keyframes settings-icon-nod { 0%,100% { transform: rotate(0); } 35% { transform: rotate(-7deg); } 65% { transform: rotate(3deg); } }
@media (max-width: 1550px) {
  .settings-hub-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .settings-hub-card { grid-template-columns: 110px minmax(0, 1fr); }
  .settings-hub-icon { width: 110px; height: 110px; }
}
@media (max-width: 1050px) { .settings-hub-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 680px) { .settings-hub-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .settings-hub-icon { transition: none; } }
</style>
