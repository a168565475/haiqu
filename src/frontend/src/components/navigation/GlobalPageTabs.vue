<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Close, House, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { usePageTabsStore } from '@/stores/pageTabs'
import { createPageTab, type PageTab } from '@/utils/pageTabs'
import { refreshCurrentPage } from '@/utils/pageRefresh'

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
    <button type="button" class="global-page-tabs__refresh" data-page-refresh aria-label="刷新当前页面" title="刷新当前页面" :disabled="store.navigating" @click="navigate(() => refreshCurrentPage(router))">
      <Refresh aria-hidden="true" />
    </button>
  </nav>
</template>

<style scoped lang="scss">
.global-page-tabs {
  width: 100%;
  min-width: 0;
  height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  color: #1f1d18;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}
.global-page-tabs__list {
  flex: 1;
  min-width: 0;
  height: 28px;
  align-self: flex-end;
  display: flex;
  align-items: center;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}
.global-page-tabs__list::-webkit-scrollbar { display: none; width: 0; height: 0; }
.global-page-tabs__strip {
  position: relative;
  flex: none;
  height: 28px;
  display: flex;
  align-items: center;
  gap: 2px;
  padding-right: 28px;
}
.global-page-tab {
  box-sizing: border-box;
  position: relative;
  flex: none;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0;
  height: 28px;
  padding-right: 0;
  border: 1px solid #ddd6c9;
  border-bottom-width: 2px;
  border-radius: 0;
  background: #fcfbf7;
  color: #6f6a61;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}
.global-page-tab:hover { background: #f0eadf; border-color: #c9c0b2; }
.global-page-tab[aria-selected='true'] {
  border-color: #c84e28;
  border-left-width: 2px;
  color: #1f1d18;
  font-weight: 600;
  background: #fff4e6;
}
.global-page-tab__open {
  flex: none;
  min-width: 0;
  height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 4px 0 10px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  font: 12px/18px 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  font-weight: inherit;
  cursor: pointer;
}
.global-page-tab--home { padding-right: 10px; }
.global-page-tab--home .global-page-tab__open { padding-right: 0; }
.global-page-tab__label { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.global-page-tab__close {
  flex: none;
  width: 22px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #968f84;
  cursor: pointer;
}
.global-page-tab__close:hover:not(:disabled) { color: #6f6a61; }
.global-page-tabs svg { width: 14px; height: 14px; flex: none; }
.global-page-tab__close svg { width: 12px; height: 12px; }
.global-page-tabs__refresh {
  box-sizing: border-box;
  flex: none;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid #ddd6c9;
  border-radius: 0;
  background: #fcfbf7;
  color: #6f6a61;
  cursor: pointer;
}
.global-page-tabs__refresh:hover { background: #f0eadf; }
.global-page-tabs button:disabled { cursor: wait; }
.global-page-tabs button:focus-visible, .global-page-tab:focus-visible { outline: 2px solid #3898ec; outline-offset: -2px; }
</style>
