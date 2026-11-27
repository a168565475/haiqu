import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'

let navigationSequence = 0

describe('首页和旧工作台链接的权限分流', () => {
  it.each([
    ['production_tasks.view_productiontask', 'production-overview'],
    ['workshop_reporting.view_workreport', 'workshop-workbench'],
    ['procurement.view_purchaseorder', 'purchase-workbench'],
  ])('消息卡片按 %s 分流时保留收件编号，不透传其他参数', async (permission, target) => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: {
      id: 1, username: 'entry-test', display_name: '入口测试', is_superuser: false,
      employee: { id: 'employee-1', employee_code: 'E001', display_name: '入口测试', status: 'ACTIVE' },
      permissions: [permission!], data_scope: 'SELF',
    } })
    const recipient = '12345678-1234-1234-1234-123456789abc'
    await router.push(`/?notification=${recipient}&unexpected=ignored`)
    expect(router.currentRoute.value.name).toBe(target)
    expect(router.currentRoute.value.query).toEqual({ notification: recipient })
  })
  it.each([
    ['/', ['production_tasks.view_productiontask'], 'production-overview'],
    ['/workbench/manager', ['production_tasks.view_productiontask'], 'production-overview'],
    ['/workbench/sales', ['production_tasks.view_productiontask'], 'production-overview'],
    ['/', ['workshop_reporting.view_workreport'], 'workshop-workbench'],
    ['/workbench/manager', ['production_scheduling.view_productionschedule'], 'workshop-workbench'],
    ['/workbench/sales', ['inventory.view_finishedgoodsreceipt'], 'workshop-workbench'],
    ['/', ['production_tasks.view_productiontask', 'workshop_reporting.view_workreport'], 'production-overview'],
    ['/', ['procurement.view_purchaseorder'], 'purchase-workbench'],
    ['/', ['procurement.manage_packagingpurchase'], 'home'],
    ['/workbench/merchandiser', [], 'home'],
    ['/workbench/purchase', ['procurement.manage_packagingpurchase'], 'home'],
    ['/workbench/sewing-outsourcing', ['outsourcing.view_outsourcingorder'], 'sewing-outsourcing-workbench'],
    ['/workbench/sewing-outsourcing', [], 'home'],
    ['/', ['procurement.view_purchaseorder', 'production_tasks.view_productiontask'], 'production-overview'],
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
  it.each([
    ['METAL_DIRECTOR', false, 'workshop-workbench'],
    ['WAREHOUSE_KEEPER', false, 'warehouse-workbench'],
    ['SEWING_DIRECTOR', false, 'workshop-workbench'],
    ['ASSEMBLY_DIRECTOR', false, 'workshop-workbench'],
    ['METAL_DIRECTOR', true, 'workshop-workbench'],
    ['OUTSOURCING', false, 'sewing-outsourcing-workbench'],
    ['PMC', false, 'production-overview'],
    ['MERCHANDISER', false, 'merchandiser-workbench'],
    ['OUTSOURCING', true, 'production-overview'],
  ] as const)('兼有多个模块查看权时按实际岗位 %s 跳转（超管 %s）', async (role, isSuperuser, target) => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: {
      id: 1, username: 'entry-test', display_name: '入口测试', is_superuser: isSuperuser,
      employee: { id: 'e1', employee_code: 'E001', display_name: '入口测试', status: 'ACTIVE' },
      permissions: ['outsourcing.view_outsourcingorder', 'production_tasks.view_productiontask', 'production_scheduling.view_productionschedule'], data_scope: 'ALL',
      effective_access: { active: true, is_superuser: isSuperuser, roles: [{ id: 'r1', code: role, name: role }],
        actions: {}, legacy_sources: [], version: '1' },
    } })
    const recipient = '12345678-1234-1234-1234-123456789abc'
    await router.push(`/?notification=${recipient}&entry_check=${++navigationSequence}`)
    expect(router.currentRoute.value.name).toBe(target)
    expect(router.currentRoute.value.query).toEqual({ notification: recipient })
  })

  it('兼任跟单的金工主任登录后优先进入自己的车间', async () => {
    setActivePinia(createPinia())
    useAuthStore().applyAuthResponse({ authenticated: true, user: {
      id: 1, username: 'director', display_name: '测试主管', is_superuser: false,
      employee: { id: 'e1', employee_code: 'E001', display_name: '测试主管', status: 'ACTIVE' },
      permissions: ['production_tasks.view_productiontask', 'workshop_reporting.view_workreport'], data_scope: 'ALL',
      effective_access: { active: true, is_superuser: false,
        roles: ['MERCHANDISER', 'METAL_DIRECTOR'].map(code => ({ id: code, code, name: code })),
        actions: {}, legacy_sources: [], version: '1' },
    } })
    await router.push(`/?entry_check=${++navigationSequence}`)
    expect(router.currentRoute.value.name).toBe('workshop-workbench')
  })
})
