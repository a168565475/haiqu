import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import WageSchemes from './wage-schemes.vue'
import type { SavedWageScheme, WageFormOptions, WageTarget } from '@/types/wageSchemes'

const api = vi.hoisted(() => ({
  fetchWageTargets: vi.fn(), fetchWageSubmissions: vi.fn(), fetchWageForm: vi.fn(), fetchWageScheme: vi.fn(),
  saveWageScheme: vi.fn(), createWageSchemeChange: vi.fn(), submitWageScheme: vi.fn(),
}))
const hasPermission = vi.hoisted(() => vi.fn())
vi.mock('@/api/wageSchemes', () => api)
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission }) }))

const target: WageTarget = {
  schedule_product_id: 'plan', product_line_id: 'product', task_number: 'HT001', schedule_date: '2026-11-24',
  product_name: '折叠椅', product_number: 'CHAIR-1', product_specification: '标准', product_color: '黑色',
  workshop_id: 'shop', workshop_name: '金工车间', craft_id: 'craft', craft_name: '管材加工', scheme: null,
}
const form: WageFormOptions = {
  target, order_quantity: '100', requires_product_name: false,
  bom_options: [{ id: 'part', identity: 'part-identity', name: '前脚管', required_quantity: '200.0000', problem: '' }],
  operations: [
    { id: 'cut', name: '切管', product_name: '', unit: '支' },
    { id: 'bend', name: '弯管', product_name: '', unit: '支' },
  ],
}
const draft: SavedWageScheme = {
  id: 'scheme', scheme_number: 'GJ-001', status: 'DRAFT', status_display: '草稿',
  can_create_change: false, parent_scheme: null, operation_product_name: '管材加工', remark: '', lines: [],
}
const pending = { ...draft, status: 'PENDING_APPROVAL', status_display: '待审批' }
const submittedRecord = {
  ...pending, change_target: null, production_task: { task_number: target.task_number }, product: { name: target.product_name },
  workshop: { name: target.workshop_name }, scope_craft: { name: target.craft_name },
}
let wrapper: VueWrapper

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.stubGlobal('scrollTo', vi.fn())
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  hasPermission.mockReturnValue(true)
  api.fetchWageTargets.mockResolvedValue({ data: [target] })
  api.fetchWageSubmissions.mockResolvedValue({ data: [submittedRecord] })
  api.fetchWageForm.mockResolvedValue(form)
  api.fetchWageScheme.mockResolvedValue({ data: draft, etag: 'v1' })
  api.saveWageScheme.mockResolvedValue({ data: draft, etag: 'v1' })
  api.submitWageScheme.mockResolvedValue(pending)
})

afterEach(() => {
  wrapper?.unmount()
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function openPage(query: Record<string, string> = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: WageSchemes }] })
  await router.push({ path: '/', query })
  wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router] } })
  await flushPromises()
}

async function search() {
  await wrapper.get('input').setValue(' HT001 ')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

async function openForm() {
  await search()
  await wrapper.get('.wage-target-action button').trigger('click')
  await flushPromises()
}

function choiceTrigger(label: string) {
  return wrapper.findAll('button.wage-option-trigger').find(button => button.element.firstElementChild?.textContent === label)!
}

function picker(label: string) {
  return new DOMWrapper(document.body).get(`.wage-picker[aria-label="选择${label}"]`)
}

async function choose(label: string, option: string) {
  await choiceTrigger(label).trigger('click')
  await picker(label).findAll('.wage-picker-option').find(button => button.text() === option)!.trigger('click')
}

describe('手机工价方案', () => {
  it('打开即列待填任务，送审后在已提交列表立即显示待审批方案', async () => {
    api.fetchWageTargets
      .mockResolvedValueOnce({ data: [target], meta: { page: 1, total_pages: 1 } })
      .mockResolvedValueOnce({ data: [], meta: { page: 1, total_pages: 1 } })
    await openPage()
    expect(api.fetchWageTargets).toHaveBeenCalledWith('', 1, expect.any(AbortSignal))
    const card = wrapper.get('.wage-target')
    expect(card.get('.wage-task-number').text()).toBe('HT001')
    expect(card.get('time').text()).toBe('2026-11-24')
    expect(card.get('time').attributes('datetime')).toBe('2026-11-24')
    await wrapper.get('.wage-target h3').trigger('click')
    await flushPromises()
    await choose('工序', '切管')
    await wrapper.get('.wage-price input').setValue('0.55')
    await wrapper.get('footer button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已提交厂长审批')
    expect(api.fetchWageSubmissions).toHaveBeenCalledWith('', 1, expect.any(AbortSignal))
    expect(wrapper.get('.wage-submission').text()).toContain('待厂长审批')
    expect(wrapper.get('.wage-submission').text()).toContain('GJ-001')
    expect(wrapper.get('.wage-submission-actions').text()).toBe('查看明细')
    await wrapper.get('.wage-submission button').trigger('click')
    await flushPromises()
    expect(api.fetchWageScheme).toHaveBeenCalledWith('scheme', expect.any(AbortSignal))
    await wrapper.get('.wage-tabs button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂无待填工价的生产任务')
    expect(wrapper.find('.wage-target').exists()).toBe(false)
  })

  it('从报工跳转时打开对应工艺的工价表单', async () => {
    api.fetchWageTargets.mockResolvedValueOnce({ data: [{ ...target, craft_id: 'other-craft' }, target] })
    await openPage({ task_number: 'HT001', schedule_product_id: 'plan', craft_id: 'craft' })
    expect(api.fetchWageTargets).toHaveBeenCalledWith('HT001', 1, expect.any(AbortSignal))
    expect(api.fetchWageForm).toHaveBeenCalledWith(target, expect.any(AbortSignal))
    expect(wrapper.get('h1').text()).toBe('HT001')
  })

  it('待填列表可以继续加载，清空搜索回到待填列表', async () => {
    const another = { ...target, task_number: 'HT002', schedule_product_id: 'another-plan' }
    api.fetchWageTargets.mockImplementation((term: string, page: number) => Promise.resolve(
      term ? { data: [] } : { data: [page === 1 ? target : another], meta: { page, total_pages: 2 } },
    ))
    await openPage()
    const more = wrapper.findAll('button').find(button => button.text() === '加载更多')!
    await more.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.wage-task-number').map(title => title.text())).toEqual(['HT001', 'HT002'])
    await search()
    expect(wrapper.text()).toContain('未找到可操作的任务 HT001')
    await wrapper.get('input').setValue('')
    await flushPromises()
    expect(wrapper.findAll('.wage-task-number').map(title => title.text())).toEqual(['HT001'])
  })

  it('按任务单号找单，同部位第二道工序带出可用选项，提交后显示待审', async () => {
    await openPage()
    await openForm()
    expect(api.fetchWageTargets).toHaveBeenCalledWith('HT001', 1, expect.any(AbortSignal))
    expect(wrapper.get('h1').text()).toBe('HT001')
    expect(wrapper.text()).toContain('前脚管')
    expect(wrapper.text()).toContain('需做 200')
    await wrapper.get('.wage-add-row').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toBe('请选择工序')
    expect(wrapper.findAll('.wage-line')).toHaveLength(1)
    await choose('工序', '切管')
    await wrapper.get('.wage-price input').setValue('1e3')
    await wrapper.get('footer button').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('工价请填 0 或正数')
    expect(api.saveWageScheme).not.toHaveBeenCalled()
    await wrapper.get('.wage-price input').setValue('0.1234')
    await wrapper.get('.wage-same-part').trigger('click')
    expect(wrapper.findAll('.wage-line-edit')).toHaveLength(1)
    expect(wrapper.get('.wage-line-brief').text()).toContain('前脚管 · 切管')
    expect(wrapper.get('.wage-line-brief').text()).toContain('0.1234 元/次')
    expect(choiceTrigger('工序').text()).toContain('弯管')
    await wrapper.get('.wage-price input').setValue('0.45')
    await wrapper.get('.wage-line-brief').trigger('click')
    expect((wrapper.get('.wage-price input').element as HTMLInputElement).value).toBe('0.1234')
    expect(wrapper.get('.wage-line-brief').text()).toContain('弯管')
    await wrapper.get('footer button').trigger('click')
    await flushPromises()
    expect(api.saveWageScheme).toHaveBeenCalledWith(expect.objectContaining({
      schedule_product_id: 'plan', craft_ids: ['craft'],
      lines: [
        expect.objectContaining({ bom_line_id: 'part', operation_id: 'cut', declared_price: '0.1234' }),
        expect.objectContaining({ bom_line_id: 'part', operation_id: 'bend', declared_price: '0.45' }),
      ],
    }), null)
    expect(api.saveWageScheme.mock.calls[0]![0]).not.toHaveProperty('operation_product_name')
    expect(api.submitWageScheme).toHaveBeenCalledWith({ data: draft, etag: 'v1' })
    expect(wrapper.text()).toContain('待厂长审批')
    expect(wrapper.text()).not.toContain('新建工价')
  })

  it('新建已保存但送审失败时保留工价，重试使用同一份方案', async () => {
    api.submitWageScheme.mockRejectedValueOnce(new Error('网络异常'))
    await openPage()
    await openForm()
    await choose('工序', '切管')
    await wrapper.get('.wage-price input').setValue('0.60')
    await wrapper.get('footer button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('网络异常')
    expect((wrapper.get('.wage-price input').element as HTMLInputElement).value).toBe('0.60')
    await wrapper.get('footer button').trigger('click')
    await flushPromises()
    expect(api.fetchWageScheme).toHaveBeenCalledWith('scheme')
    expect(api.saveWageScheme).toHaveBeenCalledTimes(1)
    expect(api.submitWageScheme).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('待厂长审批')
  })

  it('品名、部位和工序都能从底部选项点选，取消更换品名后保留已填内容', async () => {
    api.fetchWageForm.mockResolvedValueOnce({
      ...form,
      requires_product_name: true,
      bom_options: [...form.bom_options!, { id: 'arm', identity: 'arm-identity', name: '扶手', required_quantity: null, problem: '请补录扶手用量' }],
      operations: [
        ...form.operations.map(operation => ({ ...operation, product_name: '椅架' })),
        { id: 'seal', name: '封口', product_name: '靠背架', unit: '支' },
      ],
    })
    await openPage()
    await openForm()
    await choose('工序品名', '椅架')
    await choose('部位', '扶手（资料待补）')
    expect(wrapper.text()).toContain('请补录扶手用量')
    await choose('部位', '前脚管')
    await choose('工序', '切管')
    await wrapper.get('.wage-price input').setValue('0.80')
    await choiceTrigger('部位').trigger('click')
    expect(picker('部位').get('button[aria-pressed="true"]').text()).toBe('前脚管')
    await picker('部位').get('.wage-picker-close').trigger('click')
    expect(choiceTrigger('部位').attributes('aria-expanded')).toBe('false')
    await choose('工序品名', '靠背架')
    await new DOMWrapper(document.body).get('.van-dialog__cancel').trigger('click')
    await flushPromises()
    expect(choiceTrigger('工序品名').text()).toContain('椅架')
    expect(choiceTrigger('工序').text()).toContain('切管')
    expect((wrapper.get('.wage-price input').element as HTMLInputElement).value).toBe('0.80')
  })

  it('已批准工价可在搜索结果和已提交的明细旁发起变更', async () => {
    hasPermission.mockImplementation(code => code !== 'workshop_reporting.add_wagescheme')
    const approved: SavedWageScheme = {
      ...draft, status: 'APPROVED', status_display: '已批准', can_create_change: true,
      lines: form.operations.map(operation => ({
        work_item_id: `work-${operation.id}`, counting_mode: 'PIECE', operation_name: operation.name,
        bom_component_identity: 'part-identity', craft_id: 'craft', display_name: '前脚管', operation_id: operation.id,
        declared_price: operation.id === 'cut' ? '0.5500' : '0.7000', previous_price: null, revised_price: null,
        production_description: '', status: 'ACTIVE', note: '',
      })),
    }
    const approvedTarget: WageTarget = { ...target, scheme: {
      id: approved.id, number: approved.scheme_number, status: 'APPROVED', status_display: '已批准',
      can_edit: false, can_change: true, is_change: false,
    } }
    const source = { data: approved, etag: 'approved-v1' }
    const changeDraft = { data: { ...draft, id: 'change-1', parent_scheme: { id: approved.id } }, etag: 'change-v1' }
    api.fetchWageTargets.mockResolvedValueOnce({ data: [] }).mockResolvedValueOnce({ data: [approvedTarget] })
    api.fetchWageSubmissions.mockResolvedValueOnce({ data: [{ ...submittedRecord, ...approved, change_target: approvedTarget }] })
    api.fetchWageForm.mockResolvedValueOnce({ ...form, target: approvedTarget })
    api.fetchWageScheme.mockResolvedValueOnce(source).mockResolvedValueOnce(source)
    api.createWageSchemeChange.mockResolvedValueOnce(changeDraft)
    api.submitWageScheme.mockResolvedValueOnce({ ...changeDraft.data, status: 'PENDING_APPROVAL', status_display: '待审批' })

    await openPage()
    await search()
    expect(wrapper.get('.wage-target-action button').text()).toBe('变更工价')
    await wrapper.get('.wage-tabs button:last-child').trigger('click')
    await flushPromises()
    await wrapper.get('.wage-submission-actions button:first-child').trigger('click')
    await flushPromises()
    expect(wrapper.get('.wage-submission-actions button:first-child').text()).toBe('收起')
    const action = wrapper.get('.wage-submission-actions button:last-child')
    expect(action.text()).toBe('变更工价')
    await action.trigger('click')
    await flushPromises()
    const lines = wrapper.findAll('.wage-change-line')
    expect(lines.map(line => line.get('h3').text())).toEqual(['前脚管 · 切管', '前脚管 · 弯管'])
    expect(lines[0]!.text()).toContain('原工价 0.55 元/次')
    expect(lines.map(line => line.get('input').element.value)).toEqual(['0.55', '0.7'])
    expect(api.createWageSchemeChange).not.toHaveBeenCalled()

    await lines[0]!.get('input').setValue('0.62')
    await wrapper.get('footer button').trigger('click')
    await flushPromises()
    expect(api.createWageSchemeChange).toHaveBeenCalledWith(source, expect.objectContaining({ lines: [
      expect.objectContaining({ work_item_id: 'work-cut', bom_line_id: 'part', previous_price: '0.5500', declared_price: '0.62' }),
      expect.objectContaining({ work_item_id: 'work-bend', bom_line_id: 'part', previous_price: '0.7000', declared_price: '0.7' }),
    ] }))
    expect(api.saveWageScheme).not.toHaveBeenCalled()
    expect(api.submitWageScheme).toHaveBeenCalledWith(changeDraft)
    expect(wrapper.text()).toContain('待厂长审批')
  })

  it('没有送审权限的账号即使进入页面也看不到查询入口', async () => {
    hasPermission.mockImplementation(code => code !== 'workshop_reporting.submit_wagescheme')
    await openPage()
    expect(wrapper.text()).toContain('当前账号没有填写并提交工价方案的权限')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(api.fetchWageTargets).not.toHaveBeenCalled()
  })
})
