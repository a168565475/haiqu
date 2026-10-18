<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Close, House } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { usePageTabsStore } from '@/stores/pageTabs'
import { createPageTab, type PageTab } from '@/utils/pageTabs'

const route = useRoute()
const router = useRouter()
const store = usePageTabsStore()
const listElement = ref<HTMLElement>()
const activeId = computed(() => createPageTab(route)?.id)

watch([activeId, () => JSON.stringify(store.tabs.map(tab => [tab.id, tab.title]))], async () => {
  await nextTick()
  const list = listElement.value
  if (!list) return
  const selected = list.querySelector<HTMLElement>('[aria-selected="true"]')
  if (!selected) return
  const itemRect = selected.getBoundingClientRect()
  const listRect = list.getBoundingClientRect()
  if (itemRect.left < listRect.left) list.scrollLeft += itemRect.left - listRect.left
  else if (itemRect.right > listRect.right) list.scrollLeft += itemRect.right - listRect.right
}, { immediate: true })

function scrollTabs(event: WheelEvent) {
  const list = listElement.value
  if (!list || list.scrollWidth <= list.clientWidth || event.ctrlKey) return
  event.preventDefault()
  list.scrollLeft += Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
}

async function navigate(action: () => Promise<unknown>) {
  if (store.navigating) return
  store.navigating = true
  try { await action() } catch { ElMessage.error('页面切换失败，请重试。') }
  finally { store.navigating = false }
}

function openTab(tab: PageTab) {
  if (activeId.value === tab.id) return
  void navigate(() => router.push(tab.fullPath))
}

async function closeTab(tab: PageTab) {
  if (store.navigating || tab.pinned) return
  if (activeId.value !== tab.id) {
    store.removeTab(tab.id)
    return
  }
  const index = store.tabs.findIndex(item => item.id === tab.id)
  const destination = store.tabs[index - 1] || store.tabs[index + 1]
  const accountId = store.accountId
  await navigate(async () => {
    const failure = await router.push(destination?.fullPath || '/')
    // 取消未保存保护时保留页签；跳转登录时账号清理负责处理。
    if (!failure && store.accountId === accountId && createPageTab(router.currentRoute.value)?.id !== tab.id) {
      store.removeTab(tab.id)
    }
  })
}
</script>

<template>
  <nav class="global-page-tabs" aria-label="已打开的页面">
    <div ref="listElement" class="global-page-tabs__list" role="tablist" aria-label="页面选项卡" @wheel="scrollTabs">
      <div class="global-page-tabs__strip">
        <div
          v-for="tab in store.tabs"
          :key="tab.id"
          class="global-page-tab"
          :class="{ 'global-page-tab--home': tab.pinned }"
          :data-tab-id="tab.id"
          role="tab"
          :aria-selected="activeId === tab.id"
          :aria-label="tab.title"
          :tabindex="activeId === tab.id ? 0 : -1"
          @keydown.enter.self.prevent="openTab(tab)"
          @keydown.space.self.prevent="openTab(tab)"
        >
          <button type="button" class="global-page-tab__open" data-tab-open :title="tab.title" :disabled="store.navigating" @click="openTab(tab)">
            <House v-if="tab.pinned" aria-hidden="true" />
            <span class="global-page-tab__label">{{ tab.title }}</span>
          </button>
          <button v-if="!tab.pinned" type="button" class="global-page-tab__close" data-tab-close :aria-label="`关闭${tab.title}`" :disabled="store.navigating" @click="closeTab(tab)">
            <Close aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  </nav>
</template>

<style scoped lang="scss">
.global-page-tabs {
  width: 100%;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: center;
  color: var(--erp-color-text-secondary);
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}
.global-page-tabs__list {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: center;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}
.global-page-tabs__list::-webkit-scrollbar { display: none; width: 0; height: 0; }
.global-page-tabs__strip {
  flex: none;
  height: 100%;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 4px;
}
.global-page-tab {
  box-sizing: border-box;
  position: relative;
  flex: none;
  display: flex;
  align-items: center;
  height: 44px;
  border-radius: 5px;
  color: var(--erp-color-text-secondary);
  font-size: 13px;
  line-height: 20px;
  white-space: nowrap;
}
.global-page-tab:hover { background: var(--erp-menu-hover-background); }
.global-page-tab[aria-selected='true'] { color: var(--erp-menu-accent); font-weight: 600; }
.global-page-tab[aria-selected='true'] .global-page-tab__open::after {
  content: '';
  position: absolute;
  right: 4px;
  bottom: -6px;
  left: 4px;
  height: 3px;
  border-radius: 4px 4px 1px 1px;
  background: var(--erp-tab-active-indicator);
}
.global-page-tab__open {
  position: relative;
  flex: none;
  min-width: 0;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: inherit;
  font: 13px/20px 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  font-weight: inherit;
  cursor: pointer;
}
.global-page-tab__label { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.global-page-tab__close {
  flex: none;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--erp-color-text-muted);
  cursor: pointer;
}
.global-page-tab__close:hover:not(:disabled) { color: var(--erp-color-text-secondary); background: var(--erp-menu-hover-background); }
.global-page-tabs svg { width: 16px; height: 16px; flex: none; }
.global-page-tab__close svg { width: 12px; height: 12px; }
.global-page-tabs button:disabled { cursor: wait; }
.global-page-tabs button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.global-page-tab:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: -2px; }
</style>
