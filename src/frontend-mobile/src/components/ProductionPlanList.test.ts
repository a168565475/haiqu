import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { Button, Collapse, CollapseItem, Icon, Progress, Tag } from 'vant'
import type { MobilePlan } from '@/types/mobilePlan'
import ProductionPlanList from './ProductionPlanList.vue'

vi.mock('@/components/ProductImage.vue', () => ({ default: { name: 'ProductImage', props: ['src', 'alt'], template: '<img :src="src" :alt="alt">' } }))
function plan(id: string): MobilePlan {
  return {
    key: id, schedule_product_id: `schedule-product-${id}`, schedule_id: `schedule-${id}`, schedule_number: `SCH-${id}`,
    production_task_id: `task-${id}`, product_line_id: `product-${id}`, task_number: `SC-${id}`,
    product: { name: `产品-${id}`, number: `P-${id}`, specification: `规格-${id}`, color: `颜色-${id}`, material: '钢材', quantity: '120.0000', order_quantity: '240', unit: '件', image_url: `/api/products/${id}/image/` },
    plan_category: 'METAL', plan_category_label: '金工', workshop: { id: 'workshop-metal', name: '金工一车间' }, plan_date: '2026-11-02',
    task_status: 'ACTIVE', task_status_display: '生产中', can_issue: true, issue_reason: '', can_report: true, can_open_report: true, report_reason: '',
    can_view_issues: true, can_view_reports: true, progress: { status: 'ACTIVE', percentage: 40 }, reporting_crafts: [],
    can_receive_finished: false, finished_receipt_reason: '',
    can_receive_semi: false, semi_receipt_reason: '',
  }
}
let wrapper: VueWrapper | undefined
async function openList(plans: MobilePlan[], mode: 'list' | 'summary', section: 'issue' | 'report' | 'receipt' = 'report') {
  wrapper = mount(ProductionPlanList, { props: { plans, mode, section }, global: { components: { VanButton: Button, VanCollapse: Collapse, VanCollapseItem: CollapseItem, VanIcon: Icon, VanProgress: Progress, VanTag: Tag } } })
  await flushPromises()
  return wrapper
}
function action(view: VueWrapper, text: string) {
  const found = view.findAll('button').find(button => button.text() === text)
  expect(found, `应有“${text}”操作`).toBeTruthy()
  return found!
}
const titles = (view: VueWrapper) => view.findAllComponents(CollapseItem).map(item => item.get('[aria-expanded]'))
const expanded = (view: VueWrapper) => titles(view).map(title => title.attributes('aria-expanded') === 'true')
function expectDetails(view: VueWrapper, item: MobilePlan) {
  for (const text of [item.task_number, item.product.name, item.product.number, item.product.specification, item.product.color, item.workshop.name, item.plan_category_label, item.plan_date!, '120', '40%']) expect(view.text()).toContain(text)
  expect(view.find(`img[alt="${item.product.name}"]`).attributes('src')).toBe(item.product.image_url)
}
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('生产计划清单与摘要', () => {
  it.each(['list', 'summary'] as const)('%s 分开领料、报工和记录操作，记录不依赖报工新增权限', async mode => {
    const item = { ...plan('history'), can_open_report: false, can_receive_semi: true }
    const view = await openList([item], mode, 'issue')
    expect(action(view, '申请领料').exists()).toBe(true)
    expect(view.text()).not.toContain('报工进度')
    expect(view.findAll('button').some(button => ['生产报工', '半成品入库'].includes(button.text()))).toBe(false)
    await view.setProps({ section: 'report' })
    expect(view.findAll('button').some(button => button.text() === '申请领料')).toBe(false)
    expect(action(view, '生产报工').attributes('disabled')).toBeDefined()
    expect(view.findAll('button').some(button => button.text().includes('入库'))).toBe(false)
    await view.setProps({ section: 'receipt' })
    expect(action(view, '半成品入库').exists()).toBe(true)
    expect(view.findAll('button').some(button => ['申请领料', '生产报工'].includes(button.text()))).toBe(false)
    await view.setProps({ section: 'report', records: true })
    expect(view.findAll('button').some(button => ['生产报工', '半成品入库'].includes(button.text()))).toBe(false)
    await action(view, '查看报工记录').trigger('click')
    expect(view.emitted('open')).toEqual([[item]])
    await view.setProps({ plans: [{ ...item, can_view_reports: false }] })
    expect(action(view, '查看报工记录').attributes('disabled')).toBeDefined()
  })
  it.each(['list', 'summary'] as const)('%s 仅装配显示入库入口，使用服务端能力并保留禁用原因', async mode => {
    const item = { ...plan('assembly'), plan_category: 'ASSEMBLY', can_receive_finished: true }
    const view = await openList([item], mode, 'receipt')
    await action(view, '成品入库').trigger('click')
    expect(view.emitted('receiveFinished')).toEqual([[item]])
    await view.setProps({ plans: [{ ...item, can_receive_finished: false, finished_receipt_reason: '当前账号没有该计划的成品入库权限。' }] })
    expect(action(view, '成品入库').attributes('disabled')).toBeDefined()
    expect(view.text()).toContain('当前账号没有该计划的成品入库权限。')
    await action(view, '成品入库').trigger('click')
    expect(view.emitted('receiveFinished')).toHaveLength(1)
    await view.setProps({ plans: [{ ...item, plan_category: 'METAL' }] })
    expect(view.findAll('button').some(button => button.text() === '成品入库')).toBe(false)
  })
  it.each(['list', 'summary'] as const)('%s 金工和车缝显示半成品入口，裁剪和装配不显示', async mode => {
    const item = { ...plan('semi'), can_receive_semi: true }
    const view = await openList([item], mode, 'receipt')
    await action(view, '半成品入库').trigger('click')
    expect(view.emitted('receiveSemi')).toEqual([[item]])
    const sewing = { ...item, plan_category: 'SEWING' }
    await view.setProps({ plans: [sewing] })
    await action(view, '半成品入库').trigger('click')
    expect(view.emitted('receiveSemi')![1]).toEqual([sewing])
    await view.setProps({ plans: [{ ...sewing, can_receive_semi: false, semi_receipt_reason: '没有该车间入库权限' }] })
    expect(action(view, '半成品入库').attributes('disabled')).toBeDefined()
    expect(view.text()).toContain('没有该车间入库权限')
    await action(view, '半成品入库').trigger('click')
    expect(view.emitted('receiveSemi')).toHaveLength(2)
    for (const category of ['CUTTING', 'ASSEMBLY']) {
      await view.setProps({ plans: [{ ...item, plan_category: category }] })
      expect(view.findAll('button').some(button => button.text() === '半成品入库')).toBe(false)
    }
  })
  it('清单按模块展示操作，并将当前计划传给导航事件', async () => {
    const item = plan('one')
    const view = await openList([item], 'list')
    expectDetails(view, item)
    expect(view.findComponent(Collapse).exists()).toBe(false)
    const productButton = view.findAll('button').find(button => button.find(`img[alt="${item.product.name}"]`).exists())!
    expect(productButton).toBeTruthy()
    await productButton.trigger('click')
    await action(view, '生产报工').trigger('click')
    await view.setProps({ section: 'issue' })
    await action(view, '申请领料').trigger('click')
    expect(view.emitted('open')).toEqual([[item]])
    expect(view.emitted('issue')).toEqual([[item]])
    expect(view.emitted('report')).toEqual([[item]])
  })
  it('摘要标题可扫描任务、产品、数量和进度，操作随模块切换', async () => {
    const item = plan('one')
    const view = await openList([item], 'summary')
    const title = titles(view)[0]!
    for (const text of [item.task_number, item.product.name, '120', '40%']) expect(title.text()).toContain(text)
    expectDetails(view, item)
    const productButton = view.findAll('button').find(button => button.find(`img[alt="${item.product.name}"]`).exists())!
    expect(productButton).toBeTruthy()
    await productButton.trigger('click')
    await action(view, '生产报工').trigger('click')
    await view.setProps({ section: 'issue' })
    await action(view, '申请领料').trigger('click')
    expect(view.emitted('open')).toEqual([[item]])
    expect(view.emitted('issue')).toEqual([[item]])
    expect(view.emitted('report')).toEqual([[item]])
  })
  it('两种视图都保留禁用原因，未知或不可查看进度不画成 0%，历史报工可打开', async () => {
    for (const mode of ['list', 'summary'] as const) {
      const denied = { ...plan('denied'), progress: null, can_issue: false, issue_reason: '无领料权限', can_report: false, can_open_report: false, report_reason: '无报工权限' }
      const view = await openList([denied], mode)
      expect(view.text()).not.toContain('无领料权限')
      expect(view.text()).toContain('无报工权限')
      expect(view.text()).toContain('进度不可查看')
      expect(view.findAllComponents(Progress)).toHaveLength(0)
      expect(action(view, '生产报工').attributes('disabled')).toBeDefined()
      await action(view, '生产报工').trigger('click')
      await view.setProps({ section: 'issue' })
      expect(view.text()).toContain('无领料权限')
      expect(view.text()).not.toContain('无报工权限')
      expect(action(view, '申请领料').attributes('disabled')).toBeDefined()
      await action(view, '申请领料').trigger('click')
      await view.setProps({ section: 'report' })
      expect(view.emitted('issue')).toBeUndefined()
      expect(view.emitted('report')).toBeUndefined()
      await view.setProps({ plans: [{ ...denied, progress: { status: 'NOT_CONFIGURED', percentage: null }, can_open_report: true, report_reason: '今日未匹配工价，可选择历史日期' }] })
      await flushPromises()
      expect(view.text()).toContain('待配置工序')
      expect(view.findAllComponents(Progress)).toHaveLength(0)
      expect(view.text()).toContain('今日未匹配工价，可选择历史日期')
      expect(action(view, '生产报工').attributes('disabled')).toBeUndefined()
      view.unmount(); wrapper = undefined
    }
  })
  it('首次非空数据打开首项，展开其他项时互斥', async () => {
    const view = await openList([], 'summary')
    await view.setProps({ plans: [plan('one'), plan('two')] }); await flushPromises()
    expect(view.getComponent(Collapse).props('accordion')).toBe(true)
    expect(expanded(view)).toEqual([true, false])
    await titles(view)[1]!.trigger('click'); await flushPromises()
    expect(expanded(view)).toEqual([false, true])
  })
  it('追加分页与切换视图保留已选项和全部收起状态', async () => {
    const first = plan('one'); const second = plan('two'); const third = plan('three')
    const view = await openList([first, second], 'summary')
    await titles(view)[1]!.trigger('click'); await flushPromises()
    await view.setProps({ plans: [first, second, third] }); await flushPromises()
    expect(expanded(view)).toEqual([false, true, false])
    await view.setProps({ mode: 'list' }); await flushPromises()
    await view.setProps({ mode: 'summary' }); await flushPromises()
    expect(expanded(view)).toEqual([false, true, false])
    await titles(view)[1]!.trigger('click'); await flushPromises()
    expect(expanded(view)).toEqual([false, false, false])
    await view.setProps({ plans: [first, second, third, plan('four')] }); await flushPromises()
    expect(expanded(view)).toEqual([false, false, false, false])
    await view.setProps({ mode: 'list' }); await flushPromises()
    await view.setProps({ mode: 'summary' }); await flushPromises()
    expect(expanded(view)).toEqual([false, false, false, false])
  })
  it('旧展开项不在新结果时打开新首项，清空后再次加载不残留旧项', async () => {
    const view = await openList([plan('one'), plan('two')], 'summary')
    await titles(view)[1]!.trigger('click'); await flushPromises()
    await view.setProps({ plans: [plan('three'), plan('four')] }); await flushPromises()
    expect(expanded(view)).toEqual([true, false])
    expect(view.text()).not.toContain('产品-two')
    await view.setProps({ plans: [] }); await flushPromises()
    expect(view.findAllComponents(CollapseItem)).toHaveLength(0)
    await view.setProps({ plans: [plan('five')] }); await flushPromises()
    expect(expanded(view)).toEqual([true])
  })
})
