import { describe, expect, it } from 'vitest'
import { createPageTab, MAX_PAGE_TABS, removePageTab, upsertPageTab, type PageTab, type PageTabRoute } from './pageTabs'

function route(overrides: Partial<PageTabRoute> = {}): PageTabRoute {
  return {
    name: 'purchase-orders', path: '/purchase-orders', fullPath: '/purchase-orders',
    params: {}, query: {}, meta: { layout: 'erp', breadcrumbs: [{ label: '采购管理' }, { label: '采购订单' }] },
    ...overrides,
  }
}

function tab(id: string): PageTab {
  return { id, title: id, fullPath: `/${id}` }
}

describe('全局页面选项卡身份', () => {
  it('登录、没有名称以及外部地址不进入ERP页签', () => {
    expect(createPageTab(route({ name: 'login', meta: {} }))).toBeNull()
    expect(createPageTab(route({ name: undefined }))).toBeNull()
    expect(createPageTab(route({ fullPath: '//example.com' }))).toBeNull()
    expect(createPageTab(route({ fullPath: 'https://example.com' }))).toBeNull()
  })

  it.each(['manager-workbench', 'sales-workbench'])('暂时隐藏的 %s 不再创建页签', (name) => {
    expect(createPageTab(route({ name }))).toBeNull()
  })

  it('分页、筛选和排序改变地址，保留原列表身份', () => {
    const original = createPageTab(route())!
    const filtered = createPageTab(route({ fullPath: '/purchase-orders?page=2&q=床&ordering=created_at', query: { page: '2', q: '床', ordering: 'created_at' } }))!
    expect(filtered.id).toBe(original.id)
    expect(filtered.fullPath).not.toBe(original.fullPath)
  })

  it('参数顺序不影响身份，不同对象以及编辑模式隔离', () => {
    const first = createPageTab(route({ name: 'quotation-packaging', params: { quotationId: 'quote-a', lineId: 'line-a' } }))!
    expect(createPageTab(route({ name: 'quotation-packaging', params: { lineId: 'line-a', quotationId: 'quote-a' } }))!.id).toBe(first.id)
    expect(createPageTab(route({ name: 'quotation-packaging', params: { quotationId: 'quote-a', lineId: 'line-b' } }))!.id).not.toBe(first.id)
    expect(createPageTab(route({ name: 'quotation-edit', params: { quotationId: 'quote-a' } }))!.id).not.toBe(first.id)
  })

  it('同一客户只读子页面合并，保留最新地址；另一客户和编辑页单独打开', () => {
    const detail = createPageTab(route({ name: 'customer-detail', params: { customerId: 'customer-1' } }))!
    const timeline = createPageTab(route({ name: 'customer-timeline', params: { customerId: 'customer-1' }, fullPath: '/customers/customer-1/timeline' }))!
    expect(timeline.id).toBe(detail.id)
    expect(timeline.title).toBe('客户详情')
    expect(upsertPageTab([detail], timeline)).toEqual([timeline])
    expect(createPageTab(route({ name: 'customer-detail', params: { customerId: 'customer-2' } }))!.id).not.toBe(detail.id)
    expect(createPageTab(route({ name: 'customer-edit', params: { customerId: 'customer-1' } }))!.id).not.toBe(detail.id)
  })

  it.each([
    ['purchase-order-create-details', 'source_id'],
    ['purchase-order-create-details', 'bom_id'],
    ['assembly-finished-receipt', 'schedule_product_id'],
    ['internal-semi-receipt', 'plan_category'],
    ['material-issue-new', 'production_task_id'],
    ['material-issue-new', 'product_line_id'],
    ['material-issue-new', 'schedule_product_id'],
    ['sales-order-create', 'quotationVersionId'],
    ['production-task-create', 'delivery_batch_id'],
    ['sample-new', 'editApplication'],
    ['sample-new', 'sourceId'],
    ['bom-create', 'production_task_product_id'],
    ['workshop-outsourcing-new', 'source_issue_line_id'],
    ['wage-scheme-new', 'craft_id'],
    ['work-report-new', 'schedule_product_id'],
    ['quotation-preview', 'version'],
    ['suppliers', 'edit'],
    ['wage-schemes', 'detail'],
  ])('%s 的 %s 业务上下文区分页签', (name, key) => {
    const first = createPageTab(route({ name, query: { [key]: 'a', page: '1' } }))!
    const second = createPageTab(route({ name, query: { [key]: 'b', page: '1' } }))!
    const paginated = createPageTab(route({ name, query: { [key]: 'a', page: '2' } }))!
    expect(first.id).not.toBe(second.id)
    expect(first.title).toBe(second.title)
    expect(first.id).toBe(paginated.id)
  })

  it('同名参数在列表中是筛选，在新建页中才是业务来源', () => {
    const filtered = createPageTab(route({ name: 'material-issues', query: { production_task_id: 'a', product_line_id: 'b' } }))!
    expect(filtered.id).toBe(createPageTab(route({ name: 'material-issues' }))!.id)
    const inventory = createPageTab(route({ name: 'finished-goods-inventory', query: { schedule_product_id: 'a', tab: 'records' } }))!
    expect(inventory.id).toBe(createPageTab(route({ name: 'finished-goods-inventory' }))!.id)
  })

  it('详情页只显示标题，同标题的不同单据仍使用独立身份', () => {
    const result = createPageTab(route({
      name: 'purchase-order-detail', params: { id: 'c4000000-0000-4000-8000-000000000001' },
      meta: { layout: 'erp', breadcrumbs: [{ label: '采购管理' }, { label: '采购订单' }, { label: '查看明细' }] },
    }))!
    expect(result.title).toBe('采购订单查看明细')
    const another = createPageTab(route({
      name: 'purchase-order-detail', params: { id: 'c4000000-0000-4000-8000-000000000002' },
      meta: { layout: 'erp', breadcrumbs: [{ label: '采购管理' }, { label: '采购订单' }, { label: '查看明细' }] },
    }))!
    expect(another.title).toBe(result.title)
    expect(another.id).not.toBe(result.id)
    expect(createPageTab(route({ name: 'home' }))!.title).toBe('工作台')
    expect(createPageTab(route({ name: 'home' }))!.pinned).toBe(true)
  })
})

describe('选项卡数量与先开先移除', () => {
  it('打开第六个删除最早的普通页面，工作台固定首位并计入上限', () => {
    const home = { ...tab('home'), pinned: true }
    const tabs = [home, ...Array.from({ length: 4 }, (_, i) => tab(`page-${i}`))]
    const result = upsertPageTab(tabs, tab('new'))
    expect(MAX_PAGE_TABS).toBe(5)
    expect(result).toHaveLength(5)
    expect(result.map(item => item.id)).toEqual(['home', 'page-1', 'page-2', 'page-3', 'new'])
    expect(tabs).toHaveLength(5)
    expect(tabs[0]).toBe(home)
  })

  it('重开原页在原位置更新地址和标题，不改先后、不删除任何页', () => {
    const tabs = Array.from({ length: 5 }, (_, i) => tab(`page-${i}`))
    const updated = { ...tabs[0]!, title: '更新后标题', fullPath: '/page-0?page=2' }
    const result = upsertPageTab(tabs, updated)
    expect(result).toHaveLength(5)
    expect(result[0]).toEqual(updated)
    expect(result.map(item => item.id)).toEqual(tabs.map(item => item.id))
    expect(tabs[0]!.title).toBe('page-0')
  })

  it('连续打开保持工作台和最近打开的四个普通页面', () => {
    let tabs: PageTab[] = [{ ...tab('home'), pinned: true }]
    for (let i = 0; i < 20; i++) tabs = upsertPageTab(tabs, tab(`page-${i}`))
    expect(tabs.map(item => item.id)).toEqual(['home', 'page-16', 'page-17', 'page-18', 'page-19'])
  })

  it('补回工作台时放到首位，保持普通页面打开顺序及总数上限', () => {
    const tabs = Array.from({ length: 5 }, (_, i) => tab(`page-${i}`))
    const result = upsertPageTab(tabs, { ...tab('home'), pinned: true })
    expect(result.map(item => item.id)).toEqual(['home', 'page-1', 'page-2', 'page-3', 'page-4'])
  })

  it('固定工作台不能被关闭，普通页面仍可关闭', () => {
    const home = { ...tab('home'), pinned: true }
    const tabs = [home, tab('a')]
    expect(removePageTab(tabs, 'home')).toEqual(tabs)
    expect(removePageTab(tabs, 'a')).toEqual([home])
  })

  it('删除不存在的页不报错，不修改原数组', () => {
    const tabs = [tab('a'), tab('b')]
    expect(removePageTab(tabs, 'missing')).toEqual(tabs)
    expect(removePageTab(tabs, 'a')).toEqual([tabs[1]])
    expect(tabs).toHaveLength(2)
  })
})
