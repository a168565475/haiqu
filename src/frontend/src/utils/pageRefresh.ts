import type { NavigationFailure, Router } from 'vue-router'

const pendingRefreshes = new WeakMap<Router, Promise<void | NavigationFailure>>()

/** 刷新只返回已注册的 ERP 页面，避免桥接地址循环或跳出系统。 */
export function resolveRefreshTarget(router: Router, value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')
    || value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value)) return '/'

  try {
    const target = router.resolve(value)
    if (!target.matched.length || target.meta.layout !== 'erp'
      || target.name === 'page-refresh' || target.name === 'not-found') return '/'
    return target.fullPath
  } catch {
    return '/'
  }
}

/** 先经过真实路由离开保护，再由桥接页重新进入；两次替换不会新增历史。 */
export function refreshCurrentPage(router: Router): Promise<void | NavigationFailure> {
  const current = router.currentRoute.value
  if (current.meta.layout !== 'erp' || current.name === 'not-found'
    || resolveRefreshTarget(router, current.fullPath) !== current.fullPath) return Promise.resolve()

  const pending = pendingRefreshes.get(router)
  if (pending) return pending

  const refresh = router.replace({ name: 'page-refresh', query: { target: current.fullPath } })
    .finally(() => { pendingRefreshes.delete(router) })
  pendingRefreshes.set(router, refresh)
  return refresh
}
