import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'

const routeNames = ['home', 'customers', 'complaints', 'inquiries', 'quotations', 'sales-orders', 'tasks',
  'samples', 'sample-inventory', 'products', 'raw-materials', 'production-tasks', 'boms', 'purchase-orders',
  'purchase-inbounds', 'purchase-returns', 'workshop-configuration', 'workshop-scheduling', 'workshop-metalworking-plan',
  'workshop-outsourcing', 'material-issues', 'wage-schemes', 'work-report-days', 'finished-goods-inventory',
  'material-inventory', 'access-management', 'reference-data-settings', 'theme-settings']
let wrapper: VueWrapper

async function setup() {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = { id: 1, username: 'admin', display_name: '测试管理员', is_superuser: true,
    employee: null, data_scope: 'ALL', permissions: [
      'customers.view_customeraccount', 'customers.view_customercomplaint', 'inquiries.view_inquiry',
      'quotations.view_quotation', 'workflow.view_businesstask', 'samples.view_samplerequest',
      'samples.view_sampleinventoryline', 'products.view_productinformation', 'products.view_rawmaterialinformation',
      'production_tasks.view_productiontask', 'boms.view_bom', 'procurement.view_purchaseorder',
      'workshop_config.view_workshop', 'production_scheduling.view_productionschedule',
      'material_issues.view_materialissue', 'workshop_reporting.view_wagescheme',
      'inventory.view_finishedgoodsreceipt', 'inventory.view_materialinbound',
    ] }
  const router = createRouter({ history: createMemoryHistory(), routes: routeNames.map(name => ({
    name, path: `/${name}`, component: { template: '<div />' },
    meta: { activeMenu: name === 'workshop-metalworking-plan' ? 'workshop-internal-plan' : name },
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
  it('进入子页面仍默认收起，一级名称精简且唯一', async () => {
    await setup()
    expect(panel().exists()).toBe(false)
    expect(wrapper.findAll('.app-sidebar__menu-label').map(item => item.text())).toEqual(
      ['工作台', '客户', '样品', '产品', '生产', '采购', '车间', '仓库', '权限', '配置', '主题'],
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
    expect(wrapper.find('[data-menu-key="settings"]').exists()).toBe(false)
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
