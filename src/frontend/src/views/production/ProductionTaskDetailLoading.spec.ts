import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as api from '@/api/productionTasks'
import ProductImage from '@/components/products/ProductImage.vue'
import ProductionTaskDetailView from './ProductionTaskDetailView.vue'

const permissionState = vi.hoisted(() => ({ allowed: true }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { taskId: 'one' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => permissionState.allowed, moduleCan: () => permissionState.allowed }) }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTask: vi.fn(), fetchProductionTaskOptions: vi.fn(), decideProductionTaskByPmc: vi.fn() }))

describe('生产任务详情按需选项', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    permissionState.allowed = true
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { id: 'one', task_number: 'PROD-ONE', status: 'PENDING_VALIDATION', salesperson: { display_name: '业务员' }, products: [], followers: [], delivery_batches: [], current_boms: [], audit_timeline: [] }, etag: 'v1' } as never)
  })
  it.each([
    ['PENDING_CONFIRMATION', 'ORDER_COMPLETED', true, false],
    ['VERIFIED', 'ORDER_PURCHASING', true, false],
    ['VERIFIED', 'ORDER_COMPLETED', false, false],
    ['VERIFIED', 'ORDER_COMPLETED', true, true],
  ])('排产按钮遵守 BOM=%s、采购=%s 和权限=%s', async (bomStatus, purchaseStatus, allowed, visible) => {
    permissionState.allowed = Boolean(allowed)
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: {
      id: 'one', task_number: 'HT26201', status: 'READY', bom_status: bomStatus, purchase_status: purchaseStatus,
      salesperson: { display_name: '业务员' }, products: [], followers: [], current_boms: [], audit_timeline: [],
    }, etag: 'v1' } as never)
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    expect(wrapper.findAll('button').some(button => button.text() === '计划排产')).toBe(visible)
    wrapper.unmount()
  })
  it('产品档案默认仅首项展开，支持逐项切换，并保留人民币及分单位汇总', async () => {
    const product = { id: 'first', product_name: '露营椅', quantity: 2, unit_name: '把', local_unit_price: '12.5000', local_total_amount: '25.0000', packaging_method: '独立包装', special_requirements: '保留备注' }
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { id: 'one', task_number: 'HT26201', status: 'READY', salesperson: { display_name: '业务员' }, followers: [], current_boms: [], audit_timeline: [], products: [product, { ...product, id: 'second', product_name: '折叠桌', quantity: 3, unit_name: '张', local_total_amount: '37.5000' }] }, etag: 'v1' } as never)
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    const files = wrapper.findAll('details.product-file')
    expect(files).toHaveLength(2)
    expect(files.map(file => (file.element as HTMLDetailsElement).open)).toEqual([true, false])
    expect(wrapper.find('.compare-table').exists()).toBe(false)
    expect(wrapper.get('.summary-bar').text()).toContain('62.5000')
    expect(wrapper.get('.summary-bar').text()).toContain('2 把 / 3 张')
    expect(files[0].text()).toContain('独立包装')
    expect(files[0].text()).toContain('保留备注')
    expect(wrapper.get('.products-heading').text()).toBe('生产产品档案')
    expect(wrapper.find('.archive-tools').exists()).toBe(false)
    ;(files[0].element as HTMLDetailsElement).open = false
    await files[0].trigger('toggle')
    await flushPromises()
    expect(files.every(file => !(file.element as HTMLDetailsElement).open)).toBe(true)
    ;(files[1].element as HTMLDetailsElement).open = true
    await files[1].trigger('toggle')
    await flushPromises()
    expect(files.map(file => (file.element as HTMLDetailsElement).open)).toEqual([false, true])
    ;(files[0].element as HTMLDetailsElement).open = true
    await files[0].trigger('toggle')
    await flushPromises()
    expect(files.map(file => (file.element as HTMLDetailsElement).open)).toEqual([true, true])
    ;(files[1].element as HTMLDetailsElement).open = false
    await files[1].trigger('toggle')
    await flushPromises()
    expect(files.map(file => (file.element as HTMLDetailsElement).open)).toEqual([true, false])
    wrapper.unmount()
  })

  it('没有产品时明确显示空档案，标题区仅保留标题', async () => {
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    expect(wrapper.findAll('details.product-file')).toHaveLength(0)
    expect(wrapper.get('.products-card').text()).toContain('暂无产品明细')
    expect(wrapper.get('.products-heading').text()).toBe('生产产品档案')
    expect(wrapper.find('.archive-tools').exists()).toBe(false)
    wrapper.unmount()
  })
  it('读取失败显示错误与重试，成功后再显示真实返回资料', async () => {
    const response = await api.fetchProductionTask('one')
    vi.mocked(api.fetchProductionTask).mockRejectedValueOnce(new Error('无权查看或单据不存在'))
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    expect(wrapper.get('.load-error').text()).toContain('无权查看或单据不存在')
    expect(wrapper.find('.summary-bar').exists()).toBe(false)
    vi.mocked(api.fetchProductionTask).mockResolvedValueOnce(response)
    await wrapper.get('.load-error button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.load-error').exists()).toBe(false)
    expect(wrapper.get('.task-number').text()).toBe('PROD-ONE')
    wrapper.unmount()
  })
  it('详情未返回时显示加载提示，不显示金额占位结果', async () => {
    vi.mocked(api.fetchProductionTask).mockReturnValue(new Promise(() => {}))
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus] } })
    expect(wrapper.get('[role="status"]').text()).toContain('正在加载生产任务单')
    expect(wrapper.find('.summary-bar').exists()).toBe(false)
    wrapper.unmount()
  })
  it.each(['DRAFT', 'PENDING_VALIDATION', 'READY', 'IN_PRODUCTION'])('无操作权限的 %s 仍可阅读但不显示写入动作', async status => {
    permissionState.allowed = false
    const response = await api.fetchProductionTask('one')
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ ...response, data: { ...response.data, status } } as never)
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    expect(wrapper.get('.detail-heading__actions').text()).toBe('返回')
    expect(wrapper.find('.products-card').exists()).toBe(true)
    wrapper.unmount()
  })
  it.each([
    ['READY', '已接单', 2], ['PAUSED', '已暂停', 4], ['CANCELLED', '已取消', 0], ['COMPLETED', '已完成', 4],
  ])('交接进度保留 %s 的当前节点和已完成节点', async (status, label, completed) => {
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { id: 'one', task_number: 'HT26199', status, salesperson: { display_name: '业务员' }, products: [], followers: [], delivery_batches: [], current_boms: [], audit_timeline: [] }, etag: 'v1' } as never)
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    expect(wrapper.get('[aria-label="生产交接进度"] .is-current > span').text()).toBe(label)
    expect(wrapper.findAll('[aria-label="生产交接进度"] .is-done')).toHaveLength(Number(completed))
    wrapper.unmount()
  })
  it('首屏不读取选项，确认窗口加载失败可重试，未就绪不能提交', async () => {
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    expect(api.fetchProductionTaskOptions).not.toHaveBeenCalled()
    const vm = wrapper.vm as unknown as { openPmcDialog: (mode: 'CONFIRM' | 'RETURN') => void; loadPmcOptions: () => Promise<void>; decideByPmc: () => Promise<void>; optionsLoading: boolean; optionsError: string; options: unknown }
    vm.openPmcDialog('RETURN')
    expect(api.fetchProductionTaskOptions).not.toHaveBeenCalled()
    let fail!: (reason: Error) => void
    vi.mocked(api.fetchProductionTaskOptions).mockImplementationOnce(() => new Promise((_, reject) => { fail = reject }))
    vm.openPmcDialog('CONFIRM')
    expect(vm.optionsLoading).toBe(true)
    await vm.decideByPmc()
    expect(api.decideProductionTaskByPmc).not.toHaveBeenCalled()
    fail(new Error('选项加载失败'))
    await flushPromises()
    expect(vm.optionsError).toBe('选项加载失败')
    await vm.decideByPmc()
    expect(api.decideProductionTaskByPmc).not.toHaveBeenCalled()
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValueOnce({ employees: [] } as never)
    await vm.loadPmcOptions()
    expect(vm.optionsError).toBe('')
    expect(vm.options).toEqual({ employees: [] })
    wrapper.unmount()
  })
  it('详情保留服务端返回的未关联产品类别与手工快照', async () => {
    const task = { id: 'manual', task_number: 'HT26201', status: 'DRAFT', salesperson: { display_name: '业务员' }, followers: [], delivery_batches: [], current_boms: [], audit_timeline: [], products: [{ id: 'line', product_id: null, product_category_id: 'real-category', customer_product_name: '定制面板', customer_specification: '100×200', customer_color: '自由文本红', product_name: '定制面板', specification: '100×200', color_name: '自由文本红', color_code: '', quantity: 3, unit_name: '张', currency_code: 'CNY', unit_price: '12.3456', total_amount: '37.0368', local_unit_price: '12.3456', local_total_amount: '37.0368', exchange_rate: '1.00000000', packaging_method: '', special_requirements: '', details: [], images: [{ id: 'uploaded-file', name: '真实产品.png' }, { id: 'second-file', name: '产品背面.png' }] }] }
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: 'v1' } as never)
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: false } } })
    await flushPromises()
    const page = wrapper.vm as unknown as { task: { products: Array<{ product_category_id: string; product_id: string | null }> } }
    expect(page.task.products[0]).toMatchObject({ product_category_id: 'real-category', product_id: null })
    expect(wrapper.text()).toContain('定制面板')
    expect(wrapper.text()).toContain('自由文本红')
    const images = wrapper.findAllComponents(ProductImage)
    expect(images).toHaveLength(2)
    expect(images[0].props('src')).toContain('/production-tasks/manual/business-files/uploaded-file/')
    expect(images[0].props('name')).toBe('真实产品.png')
    expect(images[1].props('src')).toContain('/production-tasks/manual/business-files/second-file/')
    wrapper.unmount()
  })

  it('PMC选项加载中用已保存跟单员姓名显示，保持禁用与原ID', async () => {
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { id: 'one', task_number: 'HT26201', status: 'PENDING_VALIDATION', salesperson: { display_name: '业务员' }, products: [], followers: [{ id: 'employee-uuid', display_name: '工厂张三', employee_code: 'E1' }], delivery_batches: [], current_boms: [], audit_timeline: [] }, etag: 'v1' } as never)
    let resolveOptions!: (value: any) => void
    vi.mocked(api.fetchProductionTaskOptions).mockImplementationOnce(() => new Promise(resolve => { resolveOptions = resolve }))
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElDialog: { template: '<section><slot/></section>' }, AppWindowDialog: { template: '<section><slot/></section>' }, ElSelect: { name: 'ElSelect', props: ['disabled', 'modelValue'], template: '<div><slot/></div>' }, ElOption: { name: 'ElOption', props: ['label', 'value'], template: '<span>{{ label }}</span>' } } } })
    await flushPromises()
    const page = wrapper.vm as unknown as { openPmcDialog: (mode: 'CONFIRM') => void; pmcForm: { follower_ids: string[] }; optionsLoading: boolean }
    page.openPmcDialog('CONFIRM')
    await flushPromises()
    expect(page.optionsLoading).toBe(true)
    const follower = wrapper.findAllComponents({ name: 'ElSelect' }).find(select => Array.isArray(select.props('modelValue')))
    expect(follower?.props('disabled')).toBe(true)
    expect(follower?.text()).toContain('工厂张三')
    expect(page.pmcForm.follower_ids).toEqual(['employee-uuid'])
    resolveOptions({ employees: [{ id: 'employee-uuid', display_name: '最新姓名', employee_code: 'E1' }] })
    await flushPromises()
    expect(follower?.text()).toContain('最新姓名')
    wrapper.unmount()
  })

})
