import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { usePageTabsStore } from '@/stores/pageTabs'

// 仅同步身份边界，不负责身份切换入口、草稿确认或业务路由落点。
export function usePageTabsIdentitySync() {
  const auth = useAuthStore()
  const tabs = usePageTabsStore()
  const router = useRouter()
  const route = useRoute()
  watch(() => [auth.identityGeneration, auth.waitingForRole] as const, (_, previous) => {
    if (previous) tabs.clear()
    tabs.synchronizeAccount(auth.user?.id, auth.identityPermissionSignature, router)
    // 身份边界不能把原账号的对象 ID/query/fullPath 带入新账号页签。
    if (!previous && tabs.accountId) tabs.recordRoute(route)
  }, { immediate: true, flush: 'sync' })
  watch(() => route.fullPath, () => {
    if (auth.identityReady) tabs.recordRoute(route)
  })
}
