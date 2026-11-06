<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Icon as VanIcon, Popup as VanPopup } from 'vant'
import 'vant/es/icon/style'
import 'vant/es/popup/style'
import { useAuthStore } from '@/stores/auth'

defineProps<{ active: 'issue' | 'report' | 'receipt' | 'configuration' }>()
const router = useRouter()
const auth = useAuthStore()
const expanded = ref(false)
const trigger = ref<HTMLButtonElement>()
const drawer = ref<HTMLElement>()
const entries = computed(() => [
  { key: 'issue', title: '生产领料', icon: 'logistics', path: '/' },
  { key: 'report', title: '生产报工', icon: 'records-o', path: '/production-report' },
  { key: 'receipt', title: '生产入库', icon: 'goods-collect-o', path: '/production-receipt' },
  ...(auth.hasPermission('workshop_config.view_workshopemployee')
    ? [{ key: 'configuration', title: '车间配置', icon: 'setting-o', path: '/configuration' }] : []),
])
function navigate(path: string) {
  expanded.value = false
  void router.push(path)
}
function focusMenu() {
  const target = drawer.value?.querySelector<HTMLButtonElement>('[aria-current="page"]') || drawer.value?.querySelector<HTMLButtonElement>('button')
  target?.focus()
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { expanded.value = false; return }
  if (event.key !== 'Tab') return
  const buttons = drawer.value?.querySelectorAll<HTMLButtonElement>('button')
  if (!buttons?.length) return
  const first = buttons[0]!
  const last = buttons[buttons.length - 1]!
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
</script>

<template>
  <button ref="trigger" type="button" class="menu-trigger" aria-label="展开侧边菜单" aria-haspopup="dialog" aria-controls="workshop-navigation" :aria-expanded="expanded" @click.stop="expanded = true">
    <VanIcon name="bars" size="23" aria-hidden="true" />
  </button>
  <VanPopup v-model:show="expanded" position="left" teleport="body" class="workshop-menu-popup" :duration="0.2" aria-label="车间导航" aria-modal="true" close-on-popstate @opened="focusMenu" @closed="trigger?.focus()">
    <div id="workshop-navigation" ref="drawer" class="workshop-menu" @keydown="keydown">
      <div class="menu-heading"><h2>车间工作台</h2><button type="button" class="menu-close" aria-label="关闭侧边菜单" @click="expanded = false"><VanIcon name="cross" size="21" aria-hidden="true" /></button></div>
      <nav aria-label="车间功能">
        <button v-for="entry in entries" :key="entry.key" type="button" class="menu-entry" :aria-current="active === entry.key ? 'page' : undefined" @click="navigate(entry.path)">
          <VanIcon :name="entry.icon" size="22" aria-hidden="true" /><span>{{ entry.title }}</span><VanIcon name="arrow" size="16" aria-hidden="true" />
        </button>
      </nav>
    </div>
  </VanPopup>
</template>

<style scoped>
.menu-trigger, .menu-close { display: grid; place-items: center; flex: 0 0 44px; width: 44px; height: 44px; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--mobile-text); cursor: pointer; }
.menu-trigger:focus-visible, .menu-close:focus-visible, .menu-entry:focus-visible { outline: 2px solid var(--mobile-primary); outline-offset: -2px; }
.workshop-menu-popup { width: min(288px, 85vw); height: 100%; background: var(--mobile-surface); }
.workshop-menu { min-height: 100%; padding: calc(16px + env(safe-area-inset-top)) 16px calc(16px + env(safe-area-inset-bottom)); }
.menu-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 24px; }
.menu-heading h2 { margin: 0 8px; font-size: 18px; font-weight: 650; color: var(--mobile-text); }
.workshop-menu nav { display: grid; gap: 8px; }
.menu-entry { display: flex; align-items: center; gap: 12px; min-height: 56px; width: 100%; padding: 12px 14px; border: 0; border-radius: 10px; background: transparent; color: var(--mobile-text); font: inherit; font-size: 16px; text-align: left; cursor: pointer; }
.menu-entry > span { flex: 1; }
.menu-entry[aria-current="page"] { color: var(--mobile-primary); background: var(--mobile-primary-soft); font-weight: 600; }
.menu-entry:active, .menu-trigger:active, .menu-close:active { background: var(--mobile-primary-soft); }
@media (hover: hover) { .menu-entry:hover, .menu-trigger:hover, .menu-close:hover { background: var(--mobile-primary-soft); } }
@media (prefers-reduced-motion: reduce) { .workshop-menu-popup { transition-duration: 0s !important; } }
</style>
