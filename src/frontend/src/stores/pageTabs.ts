import { defineStore } from 'pinia'
import type { Router } from 'vue-router'

import { MAX_PAGE_TABS, createPageTab, removePageTab, upsertPageTab, type PageTab, type PageTabRoute } from '@/utils/pageTabs'

const storagePrefix = 'haiqu:page-tabs:v1:'

function storageKey(accountId: string) {
  return `${storagePrefix}${accountId}`
}

function removeStoredTabs(accountId: string) {
  if (!accountId) return
  try { sessionStorage.removeItem(storageKey(accountId)) } catch { /* 存储不可用时仍可使用页面导航。 */ }
}

export const usePageTabsStore = defineStore('page-tabs', {
  state: () => ({
    tabs: [] as PageTab[],
    accountId: '',
    permissionSignature: '',
    navigating: false,
  }),
  actions: {
    synchronizeAccount(userId: string | number | undefined, permissionSignature: string, router: Router) {
      const nextAccountId = userId === undefined || userId === null ? '' : String(userId)
      if (!nextAccountId) {
        this.clear()
        return
      }
      if (this.accountId === nextAccountId) {
        if (this.permissionSignature !== permissionSignature) {
          // 权限变化后丢弃旧入口；后续访问仍由原有接口校验权限。
          this.tabs = []
          removeStoredTabs(this.accountId)
          this.permissionSignature = permissionSignature
          const home = createPageTab(router.resolve({ name: 'home' }))
          if (home) this.tabs = [home]
        }
        return
      }
      removeStoredTabs(this.accountId)
      this.accountId = nextAccountId
      this.permissionSignature = permissionSignature
      this.tabs = []
      this.navigating = false
      try {
        const saved: unknown = JSON.parse(sessionStorage.getItem(storageKey(nextAccountId)) || 'null')
        if (saved && typeof saved === 'object' && 'permissionSignature' in saved
          && saved.permissionSignature === permissionSignature && 'paths' in saved && Array.isArray(saved.paths)) {
          // 不信任存储中的标题或路由身份；按当前路由配置重新计算。
          for (const fullPath of saved.paths.slice(-MAX_PAGE_TABS)) {
            if (typeof fullPath !== 'string' || !fullPath.startsWith('/') || fullPath.startsWith('//')) continue
            const resolved = router.resolve(fullPath)
            if (resolved.name === 'not-found') continue
            const tab = createPageTab(resolved)
            if (tab) this.tabs = upsertPageTab(this.tabs, tab)
          }
        }
      } catch { /* 损坏或不可用的存储不阻断登录。 */ }
      if (!this.tabs.some(tab => tab.pinned)) {
        const home = createPageTab(router.resolve({ name: 'home' }))
        if (home) this.tabs = upsertPageTab(this.tabs, home)
      }
    },
    recordRoute(route: PageTabRoute) {
      if (!this.accountId) return
      const tab = createPageTab(route)
      if (!tab || String(route.name) === 'not-found') return
      const existing = this.tabs.find(item => item.id === tab.id)
      if (existing) tab.title = existing.title
      this.tabs = upsertPageTab(this.tabs, tab)
      this.persist()
    },
    setTabTitle(route: PageTabRoute, title: string) {
      const tab = createPageTab(route)
      if (!this.accountId || !tab || typeof title !== 'string' || !title.trim()) return
      const existing = this.tabs.find(item => item.id === tab.id)
      if (existing) existing.title = title.trim().slice(0, 280)
    },
    removeTab(id: string) {
      this.tabs = removePageTab(this.tabs, id)
      this.persist()
    },
    persist() {
      if (!this.accountId) return
      try {
        sessionStorage.setItem(storageKey(this.accountId), JSON.stringify({
          permissionSignature: this.permissionSignature,
          paths: this.tabs.map(tab => tab.fullPath),
        }))
      } catch { /* 内存中的五个入口仍可使用。 */ }
    },
    clear() {
      removeStoredTabs(this.accountId)
      this.tabs = []
      this.accountId = ''
      this.permissionSignature = ''
      this.navigating = false
    },
  },
})
