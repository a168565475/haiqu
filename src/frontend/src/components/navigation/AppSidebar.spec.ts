import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { router as applicationRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { createPageTab } from '@/utils/pageTabs'
import AppSidebar from './AppSidebar.vue'

const boardEntries = [
  ['production-line-board', '/boards/production-line', '产线大屏'],
  ['warehouse-board', '/boards/warehouse', '仓库大屏'],
  ['production-progress-board', '/boards/production-progress', '生产进度看板'],
  ['production-board', '/boards/production', '生产大屏'],
] as const

const sidebarIconKeys = [
  'workbench', 'customer-management', 'sample-management', 'product-management',
  'production-management', 'procurement-management', 'workshop-management', 'warehouse-management',
  'employee-management', 'boards', 'settings',
] as const

const settingsEntries = [
  ['system-settings', '/settings'],
  ['access-management', '/settings/access'],
  ['reference-data-settings', '/settings/reference-data'],
  ['theme-settings', '/settings/theme'],
  ['wecom-settings', '/settings/wecom'],
  ['email-account-settings', '/settings/email-accounts'],
  ['notification-rules', '/settings/notifications'],
  ['master-data-center', '/settings/master-data'],
  ['production-data', '/settings/production-data'],
  ['inquiry-handling-settings', '/settings/inquiry-handling-time'],
  ['number-rules', '/settings/number-rules'],
] as const

const secondaryIconKeys: Record<string, string[]> = {
  workbench: ['manager-workbench', 'sales-workbench', 'production-workbench', 'production-overview', 'workshop-workbench'],
  'customer-management': ['customers', 'complaints', 'inquiries', 'quotations', 'sales-orders', 'tasks', 'analytics'],
  'sample-management': ['samples', 'sample-library'],
  'product-management': ['products', 'product-catalog', 'raw-materials', 'material-catalog'],
  'production-management': ['production-tasks', 'boms'],
  'procurement-management': ['purchase-orders', 'purchase-inbounds', 'purchase-returns'],
  'workshop-management': ['workshop-scheduling', 'workshop-internal-plan', 'workshop-outsourcing', 'material-issues', 'wage-schemes', 'work-report-days', 'workshop-configuration'],
  'warehouse-management': ['finished-goods-inventory', 'material-inventory', 'defective-inventory', 'inventory-warning'],
  'employee-management': ['employee-list', 'attendance'],
  boards: boardEntries.map(([name]) => name),
}

const routeNames = ['home', 'manager-workbench', 'sales-workbench', 'production-workbench', 'production-overview', 'workshop-workbench', 'customers', 'complaints', 'inquiries', 'quotations', 'sales-orders', 'tasks',
  'samples', 'sample-inventory', 'products', 'raw-materials', 'material-catalog', 'product-catalog', 'production-tasks', 'boms', 'purchase-orders',
  'purchase-inbounds', 'purchase-returns', 'workshop-configuration', 'workshop-scheduling', 'workshop-metalworking-plan',
  'workshop-outsourcing', 'material-issues', 'wage-schemes', 'work-report-days', 'finished-goods-inventory',
  'material-inventory', 'employee-list', 'wecom-attendance', ...settingsEntries.map(([name]) => name),
  ...boardEntries.map(([name]) => name)]
let wrapper: VueWrapper

async function setup() {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = { id: 1, username: 'admin', display_name: '测试管理员', is_superuser: true,
    employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, data_scope: 'ALL', permissions: [
      'customers.view_customeraccount', 'customers.view_customercomplaint', 'inquiries.view_inquiry',
      'quotations.view_quotation', 'workflow.view_businesstask', 'samples.view_samplerequest',
      'samples.view_sampleinventoryline', 'products.view_productinformation', 'products.view_rawmaterialinformation',
      'production_tasks.view_productiontask', 'boms.view_bom', 'procurement.view_purchaseorder',
      'workshop_config.view_workshop', 'production_scheduling.view_productionschedule',
      'material_issues.view_materialissue', 'workshop_reporting.view_wagescheme',
      'inventory.view_finishedgoodsreceipt', 'inventory.view_materialinbound', 'attendance.view_attendance',
    ] }
  const router = createRouter({ history: createMemoryHistory(), routes: routeNames.map(name => ({
    name, path: settingsEntries.find(([settingName]) => settingName === name)?.[1] || boardEntries.find(([boardName]) => boardName === name)?.[1] || `/${name}`, component: { template: '<div />' },
    meta: { activeMenu: settingsEntries.some(([settingName]) => settingName === name) ? 'settings' : name === 'workshop-metalworking-plan' ? 'workshop-internal-plan' : name === 'wecom-attendance' ? 'attendance' : name },
  })) })
  await router.push('/workshop-metalworking-plan')
  await router.isReady()
  vi.useFakeTimers()
  wrapper = mount(AppSidebar, { attachTo: document.body, global: { plugins: [pinia, router] } })
  return { auth, router }
}

const group = (key: string) => wrapper.get(`[data-menu-key="${key}-management"]`)
const panel = () => wrapper.find('[data-sidebar-flyout]')
const advance = async (ms: number) => { await vi.advanceTimersByTimeAsync(ms); await nextTick() }

afterEach(() => {
  wrapper?.unmount()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('全局悬停侧栏', () => {
  it('底部合并为配置入口，其余一级菜单仍渲染对应的确认图标', async () => {
    await setup()
    expect(wrapper.findAll('[data-confirmed-sidebar-icon]')).toHaveLength(sidebarIconKeys.length)
    for (const key of sidebarIconKeys) {
      const entry = wrapper.get(`[data-menu-key="${key}"]`)
      expect(entry.findAll('[data-confirmed-sidebar-icon]')).toHaveLength(1)
      expect(entry.get('[data-confirmed-sidebar-icon]').attributes('data-confirmed-sidebar-icon')).toBe(key)
    }
  })

  it('切换主菜单和底部入口时保持父级选中状态与对应图标', async () => {
    const { router } = await setup()
    expect(group('workshop').classes()).toContain('is-active')
    expect(group('customer').classes()).not.toContain('is-active')
    await router.push('/customers')
    expect(group('customer').classes()).toContain('is-active')
    expect(group('workshop').classes()).not.toContain('is-active')
    expect(group('customer').find('[data-confirmed-sidebar-icon="customer-management"]').exists()).toBe(true)

    for (const [name] of settingsEntries) {
      await router.push({ name })
      const entry = wrapper.get('[data-menu-key="settings"]')
      expect(entry.classes()).toContain('is-active')
      expect(entry.attributes('aria-current')).toBe('page')
      expect(entry.find('[data-confirmed-sidebar-icon="settings"]').exists()).toBe(true)
      expect(wrapper.findAll('.app-sidebar__footer-link.is-active')).toHaveLength(1)
      expect(group('customer').classes()).not.toContain('is-active')
    }
  })

  it('悬停各主菜单时浮层标题复用该菜单的确认图标', async () => {
    await setup()
    for (const key of sidebarIconKeys.slice(0, 10)) {
      const entry = wrapper.get(`[data-menu-key="${key}"]`)
      await entry.trigger('mouseenter')
      await advance(100)
      expect(panel().attributes('data-flyout-menu-key')).toBe(key)
      const heading = panel().get('.app-sidebar__flyout-heading')
      expect(heading.get('h2').text()).toBe(entry.get('.app-sidebar__menu-label').text())
      expect(heading.findAll('[data-confirmed-sidebar-icon]')).toHaveLength(1)
      expect(heading.get('[data-confirmed-sidebar-icon]').attributes('data-confirmed-sidebar-icon')).toBe(key)
    }
  })

  it('各组真实二级菜单完整渲染对应图标，待开放项也保留图形', async () => {
    const { auth } = await setup()
    auth.user = { ...auth.user!, permissions: [...auth.user!.permissions,
      'product_catalog.view_productcatalog', 'material_catalog.view_materialcatalog'] }
    await nextTick()
    const renderedKeys: string[] = []
    for (const [groupKey, keys] of Object.entries(secondaryIconKeys)) {
      await wrapper.get(`[data-menu-key="${groupKey}"]`).trigger('focus')
      expect(panel().findAll('[data-menu-key]').map(item => item.attributes('data-menu-key'))).toEqual(keys)
      for (const key of keys) {
        const entry = panel().get(`[data-menu-key="${key}"]`)
        expect(entry.findAll('[data-confirmed-secondary-sidebar-icon]')).toHaveLength(1)
        const icon = entry.get('[data-confirmed-secondary-sidebar-icon]')
        expect(icon.attributes('data-confirmed-secondary-sidebar-icon')).toBe(key)
        expect(icon.element.tagName.toLowerCase()).toBe('svg')
        expect(icon.find('path, circle, rect, ellipse, line, polygon, polyline').exists()).toBe(true)
        renderedKeys.push(key)
      }
    }
    expect(renderedKeys).toHaveLength(40)
    expect(new Set(renderedKeys).size).toBe(40)
  })

  it('二级悬停复用一个背景，不改变当前路由或选中项', async () => {
    const { router } = await setup()
    await group('workshop').trigger('focus')
    const plate = panel().get('[data-sidebar-hover-plate]')
    expect(plate.attributes('data-hover-menu-key')).toBe('')
    for (const key of ['workshop-scheduling', 'material-issues']) {
      await panel().get(`[data-menu-key="${key}"]`).trigger('mouseenter')
      expect(wrapper.findAll('[data-sidebar-hover-plate]')).toHaveLength(1)
      expect(panel().get('[data-sidebar-hover-plate]').element).toBe(plate.element)
      expect(plate.attributes('data-hover-menu-key')).toBe(key)
      expect((plate.element as HTMLElement).style.opacity).toBe('1')
      expect(router.currentRoute.value.name).toBe('workshop-metalworking-plan')
      expect(panel().get('[data-menu-key="workshop-internal-plan"]').attributes('aria-current')).toBe('page')
      expect(panel().get(`[data-menu-key="${key}"]`).classes()).not.toContain('is-active')
      expect(group('workshop').classes()).toContain('is-active')
    }
  })

  it.each([
    ['customer', 'complaints', 'analytics'],
    ['warehouse', 'material-inventory', 'defective-inventory'],
    ['warehouse', 'material-inventory', 'inventory-warning'],
  ])('从 %s 的 %s 移入待开放项 %s 时清除背景且不产生导航', async (groupKey, enabledKey, disabledKey) => {
    const { router } = await setup()
    await group(groupKey).trigger('focus')
    const plate = panel().get('[data-sidebar-hover-plate]')
    await panel().get(`[data-menu-key="${enabledKey}"]`).trigger('mouseenter')
    expect(plate.attributes('data-hover-menu-key')).toBe(enabledKey)
    const disabled = panel().get(`[data-menu-key="${disabledKey}"]`)
    await disabled.trigger('mouseenter')
    expect(disabled.attributes('aria-disabled')).toBe('true')
    expect(disabled.attributes('href')).toBeUndefined()
    expect(plate.attributes('data-hover-menu-key')).toBe('')
    expect((plate.element as HTMLElement).style.opacity).toBe('0')
    expect(router.currentRoute.value.name).toBe('workshop-metalworking-plan')
  })

  it('进入已选中的二级菜单时清除悬停背景，保留当前页标记', async () => {
    const { router } = await setup()
    await router.push('/customers')
    await group('customer').trigger('focus')
    const plate = panel().get('[data-sidebar-hover-plate]')
    await panel().get('[data-menu-key="complaints"]').trigger('mouseenter')
    expect(plate.attributes('data-hover-menu-key')).toBe('complaints')
    await panel().get('[data-menu-key="customers"]').trigger('mouseenter')
    expect(plate.attributes('data-hover-menu-key')).toBe('')
    expect((plate.element as HTMLElement).style.opacity).toBe('0')
    expect(panel().get('[data-menu-key="customers"]').attributes('aria-current')).toBe('page')
  })

  it('长菜单切换短菜单时清除背景几何，避免透明背景撑出滚动范围', async () => {
    await setup()
    await group('customer').trigger('focus')
    const row = panel().get('[data-menu-key="complaints"]')
    Object.defineProperties(row.element, {
      offsetTop: { configurable: true, value: 216 },
      offsetHeight: { configurable: true, value: 44 },
    })
    await row.trigger('mouseenter')
    expect((panel().get('[data-sidebar-hover-plate]').element as HTMLElement).style.transform).toBe('translateY(216px)')
    await group('procurement').trigger('focus')
    const plate = panel().get('[data-sidebar-hover-plate]')
    expect((plate.element as HTMLElement).style.transform).toBe('translateY(0px)')
    expect((plate.element as HTMLElement).style.height).toBe('0px')
    expect(plate.isVisible()).toBe(false)
  })

  it('切换分组、离开二级菜单和关闭浮层均清理共享背景', async () => {
    await setup()
    await group('customer').trigger('focus')
    await panel().get('[data-menu-key="complaints"]').trigger('mouseenter')
    expect(panel().get('[data-sidebar-hover-plate]').attributes('data-hover-menu-key')).toBe('complaints')
    await group('warehouse').trigger('focus')
    expect(panel().get('[data-sidebar-hover-plate]').attributes('data-hover-menu-key')).toBe('')

    await panel().get('[data-menu-key="material-inventory"]').trigger('mouseenter')
    await panel().get('.app-sidebar__flyout-menu').trigger('mouseleave')
    expect(panel().get('[data-sidebar-hover-plate]').attributes('data-hover-menu-key')).toBe('')

    await panel().get('[data-menu-key="material-inventory"]').trigger('mouseenter')
    await wrapper.get('nav').trigger('keydown', { key: 'Escape' })
    expect(panel().isVisible()).toBe(false)
    expect(panel().get('[data-sidebar-hover-plate]').attributes('data-hover-menu-key')).toBe('')
    expect((panel().get('[data-sidebar-hover-plate]').element as HTMLElement).style.opacity).toBe('0')

    await group('warehouse').trigger('focus')
    await panel().get('[data-menu-key="material-inventory"]').trigger('mouseenter')
    await wrapper.get('nav').trigger('mouseleave')
    await advance(160)
    expect(panel().isVisible()).toBe(false)
    expect(panel().get('[data-sidebar-hover-plate]').attributes('data-hover-menu-key')).toBe('')
  })

  it('独立产品管理保留旧产品信息默认入口，独立权限可打开新页面', async () => {
    expect(applicationRouter.resolve('/product-catalog').name).toBe('product-catalog')
    expect(applicationRouter.resolve('/products').name).toBe('products')
    const { auth, router } = await setup()
    auth.user = { ...auth.user!, is_superuser: false, permissions: ['product_catalog.view_productcatalog'] }
    await nextTick()
    await group('product').trigger('click')
    await advance(120)
    expect(panel().findAll('[data-menu-key]').map(item => item.attributes('data-menu-key'))).toEqual(['product-catalog'])
    await panel().get('[data-menu-key="product-catalog"]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.name).toBe('product-catalog')
  })
  it('管理员可从工作台分组分别打开主管版和业务员版', async () => {
    const { router } = await setup()
    await wrapper.get('[data-menu-key="workbench"]').trigger('click')
    expect(panel().findAll('.app-sidebar__flyout-label').map(item => item.text())).toEqual(['主管工作台', '业务员工作台', '生产负责人工作台', '生产总览', '车间主管工作台'])
    await panel().get('[data-menu-key="sales-workbench"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('sales-workbench')
    expect(wrapper.get('[data-menu-key="workbench"]').classes()).toContain('is-active')
    await wrapper.get('[data-menu-key="workbench"]').trigger('focus')
    await panel().get('[data-menu-key="manager-workbench"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('manager-workbench')
  })

  it('业务员只看到自己的工作台入口，无查看权限时不显示分组', async () => {
    const { auth } = await setup()
    auth.user = { ...auth.user!, username: 'sales', is_superuser: false,
      permissions: ['customers.view_customeraccount'] }
    await nextTick()
    await wrapper.get('[data-menu-key="workbench"]').trigger('click')
    expect(panel().findAll('.app-sidebar__flyout-label').map(item => item.text())).toEqual(['业务员工作台'])
    auth.user = { ...auth.user!, permissions: [] }
    await nextTick()
    expect(wrapper.find('[data-menu-key="workbench"]').exists()).toBe(false)
  })

  it.each([
    ['production_tasks.view_productiontask', ['production-workbench', 'production-overview']],
    ['workshop_reporting.view_workreport', ['workshop-workbench']],
  ])('生产入口按源模块权限展示：%s', async (permission, expected) => {
    const { auth } = await setup()
    auth.user = { ...auth.user!, is_superuser: false, permissions: [permission] }
    await nextTick()
    await wrapper.get('[data-menu-key="workbench"]').trigger('click')
    expect(panel().findAll('[data-menu-key]').map(item => item.attributes('data-menu-key'))).toEqual(expected)
  })

  it.each([
    ['production-workbench', '/workbench/production', '生产负责人工作台', 'owner'],
    ['production-overview', '/workbench/production-overview', '生产总览', 'executive'],
    ['workshop-workbench', '/workbench/workshop', '车间主管工作台', 'workshop'],
  ])('%s 提供独立生产视角及页签', (name, path, title, role) => {
    const resolved = applicationRouter.resolve({ name })
    expect(resolved.path).toBe(path)
    expect(resolved.matched.at(-1)?.props.default).toEqual({ role })
    expect(resolved.meta.activeMenu).toBe(name)
    expect(createPageTab(resolved)?.title).toBe(title)
  })

  it.each([
    ['manager-workbench', '/workbench/manager', '主管工作台', 'MANAGER'],
    ['sales-workbench', '/workbench/sales', '业务员工作台', 'SALES'],
  ])('%s 路由固定工作台版本并提供独立页签', (name, path, title, mode) => {
    const resolved = applicationRouter.resolve({ name })
    expect(resolved.path).toBe(path)
    expect(resolved.matched.at(-1)?.props.default).toEqual({ workbenchMode: mode })
    expect(createPageTab(resolved)?.title).toBe(title)
    expect(createPageTab(resolved)?.id).not.toBe(createPageTab(applicationRouter.resolve({ name: 'home' }))?.id)
  })

  it('点击看板只展开四个演示入口，不跳转当前业务页面且不要求业务权限', async () => {
    const { auth, router } = await setup()
    auth.user = { ...auth.user!, is_superuser: false, permissions: [] }
    await nextTick()
    await wrapper.get('[data-menu-key="boards"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workshop-metalworking-plan')
    expect(panel().isVisible()).toBe(true)
    expect(panel().findAll('.app-sidebar__flyout-label').map(item => item.text())).toEqual([
      '产线大屏', '仓库大屏', '生产进度看板', '生产大屏',
    ])
  })

  it.each(boardEntries)('%s 提供真实新标签链接、隔离来源窗口并提示辅助技术', async (name, path, label) => {
    const { router } = await setup()
    await wrapper.get('[data-menu-key="boards"]').trigger('click')
    const entry = panel().get(`[data-menu-key="${name}"]`)
    expect(entry.element.tagName).toBe('A')
    expect(entry.attributes('href')).toBe(path)
    expect(entry.attributes('target')).toBe('_blank')
    expect(entry.attributes('rel')).toBe('noopener noreferrer')
    expect(entry.attributes('aria-label')).toBe(`${label}（在新标签页打开）`)
    entry.element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workshop-metalworking-plan')
  })

  it('已有业务子菜单继续在当前标签页打开', async () => {
    const { router } = await setup()
    await group('customer').trigger('focus')
    const entry = panel().get('[data-menu-key="customers"]')
    expect(entry.attributes('target')).toBeUndefined()
    expect(entry.attributes('rel')).toBeUndefined()
    await entry.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('customers')
  })

  it.each([
    ['customer', 'customers'],
    ['sample', 'samples'],
    ['product', 'products'],
    ['production', 'production-tasks'],
    ['procurement', 'purchase-orders'],
    ['workshop', 'workshop-scheduling'],
    ['warehouse', 'finished-goods-inventory'],
  ])('点击%s一级菜单进入指定默认列表%s并收起浮层', async (menu, target) => {
    const { router } = await setup()
    await group(menu).trigger('focus')
    expect(panel().isVisible()).toBe(true)
    await group(menu).trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe(target)
    expect(panel().isVisible()).toBe(false)
    expect(group(menu).classes()).toContain('is-active')
  })

  it('点击已在当前默认列表的一级入口也收起浮层', async () => {
    const { router } = await setup()
    await router.push('/customers')
    await group('customer').trigger('focus')
    await group('customer').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('customers')
    expect(panel().isVisible()).toBe(false)
  })

  it('悬停延时未完成时点击，跳转后不会被旧计时器重新展开', async () => {
    const { router } = await setup()
    await group('customer').trigger('mouseenter')
    await advance(50)
    await group('customer').trigger('click')
    await flushPromises()
    await advance(300)
    expect(router.currentRoute.value.name).toBe('customers')
    expect(group('customer').attributes('aria-expanded')).toBe('false')
  })

  it('默认列表无权限时不跳转，仍可展开其他已授权子菜单', async () => {
    const { auth, router } = await setup()
    auth.user = { ...auth.user!, username: 'operator', is_superuser: false,
      permissions: ['customers.view_customercomplaint'] }
    await nextTick()
    await group('customer').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workshop-metalworking-plan')
    expect(panel().isVisible()).toBe(true)
    expect(panel().find('[data-menu-key="customers"]').exists()).toBe(false)
    expect(panel().get('[data-menu-key="complaints"]').attributes('href')).toBe('/complaints')
  })

  it('仅有原料管理查看权限时展开产品组，并可进入原料管理而不跳转无权产品列表', async () => {
    const { auth, router } = await setup()
    auth.user = { ...auth.user!, username: 'material-catalog-reader', is_superuser: false,
      permissions: ['material_catalog.view_materialcatalog'] }
    await nextTick()
    const navigate = vi.spyOn(router, 'push')
    await group('product').trigger('click')
    await flushPromises()
    expect(navigate).not.toHaveBeenCalled()
    expect(router.currentRoute.value.name).toBe('workshop-metalworking-plan')
    expect(panel().isVisible()).toBe(true)
    expect(panel().findAll('[data-menu-key]').map(item => item.attributes('data-menu-key'))).toEqual(['material-catalog'])
    const entry = panel().get('[data-menu-key="material-catalog"]')
    expect(entry.get('.app-sidebar__flyout-label').text()).toBe('原料管理')
    expect(entry.attributes('href')).toBe('/material-catalog')
    await entry.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('material-catalog')
    expect(panel().isVisible()).toBe(false)
    expect(group('product').classes()).toContain('is-active')
  })

  it('车间计划排产排第一、生产配置移到最后，键盘先进入计划排产', async () => {
    await setup()
    await group('workshop').trigger('keydown', { key: 'ArrowRight' })
    expect(panel().findAll('.app-sidebar__flyout-label').map(item => item.text())).toEqual([
      '计划排产', '内部计划', '委外加工', '生产领料', '工价方案', '报工记录', '生产配置',
    ])
    expect(document.activeElement?.getAttribute('data-menu-key')).toBe('workshop-scheduling')
  })

  it('仅有供应商权限仍可经采购默认入口进入原有采购页', async () => {
    const { auth, router } = await setup()
    auth.user = { ...auth.user!, username: 'supplier-reader', is_superuser: false,
      permissions: ['procurement.view_supplier'] }
    await nextTick()
    await group('procurement').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('purchase-orders')
    expect(group('procurement').attributes('aria-expanded')).toBe('false')
  })

  it('进入子页面仍默认收起，一级名称精简且唯一', async () => {
    await setup()
    expect(panel().exists()).toBe(false)
    expect(wrapper.findAll('.app-sidebar__menu-label').map(item => item.text())).toEqual(
      ['工作台', '客户', '样品', '产品', '生产', '采购', '车间', '仓库', '行政', '看板', '配置'],
    )
    expect(group('workshop').classes()).toContain('is-active')
  })

  it('短暂经过不弹出，停留后只显示对应的一个面板', async () => {
    await setup()
    await group('customer').trigger('mouseenter')
    await advance(50)
    await wrapper.get('nav').trigger('mouseleave')
    await advance(300)
    expect(panel().exists()).toBe(false)
    await group('workshop').trigger('mouseenter')
    await advance(100)
    expect(panel().isVisible()).toBe(true)
    expect(panel().attributes('data-flyout-menu-key')).toBe('workshop-management')
    expect(panel().findAll('[data-menu-key]')).toHaveLength(7)
  })

  it('跨入二级栏取消关闭，离开整个导航后收起', async () => {
    await setup()
    await group('workshop').trigger('mouseenter')
    await advance(100)
    await wrapper.get('nav').trigger('mouseleave')
    await advance(80)
    await panel().trigger('mouseenter')
    await advance(200)
    expect(panel().isVisible()).toBe(true)
    await wrapper.get('nav').trigger('mouseleave')
    await advance(160)
    expect(panel().isVisible()).toBe(false)
  })

  it('快速切换只打开最后一组，路由变化后关闭', async () => {
    const { router } = await setup()
    await group('customer').trigger('mouseenter')
    await advance(40)
    await group('workshop').trigger('mouseenter')
    await advance(100)
    expect(wrapper.findAll('[data-sidebar-flyout]')).toHaveLength(1)
    expect(panel().attributes('data-flyout-menu-key')).toBe('workshop-management')
    await router.push('/customers')
    expect(panel().isVisible()).toBe(false)
    expect(group('customer').classes()).toContain('is-active')
  })

  it('键盘可展开且 Esc 收起，不开放项没有假链接', async () => {
    await setup()
    await group('customer').trigger('keydown', { key: 'ArrowRight' })
    expect(panel().isVisible()).toBe(true)
    const disabled = panel().get('[data-menu-key="analytics"]')
    expect(disabled.attributes('aria-disabled')).toBe('true')
    expect(disabled.attributes('href')).toBeUndefined()
    await wrapper.get('nav').trigger('keydown', { key: 'Escape' })
    expect(panel().isVisible()).toBe(false)
  })

  it('权限刷新后移除失去权限的组并关闭其面板', async () => {
    const { auth } = await setup()
    await group('workshop').trigger('mouseenter')
    await advance(100)
    vi.restoreAllMocks()
    auth.user = { ...auth.user!, username: 'operator', is_superuser: false, permissions: [] }
    await nextTick()
    expect(wrapper.find('[data-menu-key="workshop-management"]').exists()).toBe(false)
    expect(panel().exists()).toBe(false)
    expect(wrapper.find('[data-menu-key="access-management"]').exists()).toBe(false)
    expect(wrapper.find('[data-menu-key="settings"]').exists()).toBe(true) // 已登录用户仍可进入界面主题及个人邮箱配置。
  })

  it('权限和企微不再独立占用侧栏，唯一配置入口进入卡片首页', async () => {
    const { auth, router } = await setup()
    expect(wrapper.findAll('.app-sidebar__footer-link')).toHaveLength(1)
    expect(wrapper.find('[data-menu-key="access-management"]').exists()).toBe(false)
    expect(wrapper.find('[data-menu-key="wecom-settings"]').exists()).toBe(false)
    expect(wrapper.get('[data-menu-key="settings"]').attributes('href')).toBe('/settings')
    await wrapper.get('[data-menu-key="settings"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('system-settings')
    expect(wrapper.get('[data-menu-key="settings"]').attributes('aria-current')).toBe('page')

    auth.user = { ...auth.user!, is_superuser: false, permissions: [] }
    await nextTick()
    expect(wrapper.findAll('.app-sidebar__footer-link')).toHaveLength(1)
    expect(wrapper.find('[data-menu-key="access-management"]').exists()).toBe(false)
    expect(wrapper.find('[data-menu-key="wecom-settings"]').exists()).toBe(false)
  })

  it.each([
    [true, false, ['employee-list']],
    [false, true, ['attendance']],
    [true, true, ['employee-list', 'attendance']],
    [false, false, []],
  ] as const)('员工目录与考勤权限独立显示：目录%s 考勤%s', async (directory, attendance, expected) => {
    const { auth } = await setup()
    auth.user = { ...auth.user!, username: 'employee-reader', is_superuser: false,
      permissions: attendance ? ['attendance.view_attendance'] : [],
      effective_access: { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'menu-test',
        actions: directory ? {
          'access_control.manage_accounts': { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE', role_id: 'role' }] },
        } : {} },
    }
    await nextTick()
    expect(wrapper.find('.app-sidebar__footer [data-menu-key="wecom-attendance"]').exists()).toBe(false)
    if (!expected.length) {
      expect(wrapper.find('[data-menu-key="employee-management"]').exists()).toBe(false)
      return
    }
    await group('employee').trigger('focus')
    expect(panel().findAll('[data-menu-key]').map(item => item.attributes('data-menu-key'))).toEqual(expected)
  })

  it('只有考勤权限时从员工与考勤组仍可进入原考勤路由并保留选中状态', async () => {
    const { auth, router } = await setup()
    auth.user = { ...auth.user!, username: 'attendance-reader', is_superuser: false, permissions: ['attendance.view_attendance'] }
    await nextTick()
    await group('employee').trigger('click')
    await panel().get('[data-menu-key="attendance"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('wecom-attendance')
    expect(group('employee').classes()).toContain('is-active')
  })

  it('卸载时清除尚未触发的悬停计时器', async () => {
    await setup()
    await group('workshop').trigger('mouseenter')
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('键盘焦点移到导航外时关闭二级栏', async () => {
    await setup()
    await group('workshop').trigger('focus')
    expect(panel().isVisible()).toBe(true)
    await wrapper.get('nav').trigger('focusout', { relatedTarget: document.body })
    expect(panel().isVisible()).toBe(false)
  })
})

describe('独立演示看板路由', () => {
  it.each(boardEntries)('%s 可按真实地址解析、要求登录并排除 ERP 外壳及页签', (name, path) => {
    const resolved = applicationRouter.resolve(path)
    expect(resolved.name).toBe(name)
    expect(resolved.meta.requiresAuth).toBe(true)
    expect(resolved.meta.layout).toBeUndefined()
    expect(createPageTab(resolved)).toBeNull()
  })
})

describe('员工考勤入口兼容', () => {
  it.each([
    ['/employees', 'employee-list', 'employee-list', '员工管理'],
    ['/attendance/wecom', 'wecom-attendance', 'attendance', '考勤管理'],
    ['/settings/wecom', 'wecom-settings', 'settings', '企业微信管理'],
  ])('%s 仍可解析并生成独立业务页签', (path, name, activeMenu, title) => {
    const resolved = applicationRouter.resolve(path)
    expect(resolved.name).toBe(name)
    expect(resolved.meta.requiresAuth).toBe(true)
    expect(resolved.meta.activeMenu).toBe(activeMenu)
    expect(createPageTab(resolved)?.title).toBe(title)
    expect(createPageTab(resolved)?.fullPath).toBe(path)
  })
})

describe('系统配置路由兼容', () => {
  it.each(settingsEntries)('%s 保留真实地址 %s 并选中唯一配置菜单', (name, path) => {
    const resolved = applicationRouter.resolve(path)
    expect(resolved.name).toBe(name)
    expect(resolved.meta.requiresAuth).toBe(true)
    expect(resolved.meta.activeMenu).toBe('settings')
  })
})
