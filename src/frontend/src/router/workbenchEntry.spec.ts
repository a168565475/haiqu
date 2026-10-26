import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'

let navigationSequence = 0

describe('首页和旧工作台链接的权限分流', () => {
  it.each([
    ['/', ['production_tasks.view_productiontask'], 'production-overview'],
    ['/workbench/manager', ['production_tasks.view_productiontask'], 'production-overview'],
    ['/workbench/sales', ['production_tasks.view_productiontask'], 'production-overview'],
    ['/', ['workshop_reporting.view_workreport'], 'workshop-workbench'],
    ['/workbench/manager', ['production_scheduling.view_productionschedule'], 'workshop-workbench'],
    ['/workbench/sales', ['inventory.view_finishedgoodsreceipt'], 'workshop-workbench'],
    ['/', ['production_tasks.view_productiontask', 'workshop_reporting.view_workreport'], 'production-overview'],
    ['/', ['customers.view_customeraccount'], 'home'],
    ['/workbench/manager', ['customers.view_customeraccount'], 'home'],
    ['/workbench/sales', [], 'home'],
  ])('%s 按现有权限 %j 进入 %s', async (path, permissions, target) => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: {
      id: 1, username: 'entry-test', display_name: '入口测试', is_superuser: false,
      employee: { id: 'employee-1', employee_code: 'E001', display_name: '入口测试', status: 'ACTIVE' },
      permissions, data_scope: 'SELF',
    } })
    await router.push(`${path}?entry_check=${++navigationSequence}`)
    expect(router.currentRoute.value.name).toBe(target)
    if (target === 'home') {
      expect(router.currentRoute.value.matched.at(-1)?.components?.default).toHaveProperty('__name', 'WorkbenchLandingView')
    }
  })
})
