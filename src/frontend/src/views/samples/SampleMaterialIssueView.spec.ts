import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { AxiosError } from 'axios'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleMaterialIssueView from './SampleMaterialIssueView.vue'

enableAutoUnmount(afterEach)
const mocks = vi.hoisted(() => ({ sample: vi.fn(), issue: vi.fn(), confirm: vi.fn(), initiate: vi.fn(), push: vi.fn() }))
const route = { name: 'sample-material-issue-confirm', params: { sampleId: 'sample-1' } }
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: mocks.push }) }))
vi.mock('@/api/samples', () => ({ fetchSample: mocks.sample }))
vi.mock('@/api/sampleMaterialIssue', () => ({
  fetchSampleMaterialIssue: mocks.issue, confirmSampleMaterialIssue: mocks.confirm, initiateSampleMaterialIssue: mocks.initiate,
}))

const line = {
  id: 'line-1', lineKey: 'key-1', category: 'tube', name: '圆管', specification: '25×1.2', material: '铝', color: '', unitLabel: '米',
  requestedQuantity: '8', warehouseQuantity: '0', procurementQuantity: '8', arrivedQuantity: '12', availableQuantity: '12.0000',
  issuedQuantity: null, shortageQuantity: '0', barCount: 2,
  pipeBatches: [{ balanceId: 'balance-1', warehouseName: '材料仓', zoneName: '一区', rawBarLengthM: '6', barCount: 2, meterQuantity: '12' }],
}
const pending = {
  available: true, status: 'PENDING_CONFIRMATION', statusLabel: '待仓库确认', canConfirm: true, canInitiate: false,
  etag: 'preview-v1', blockers: [], lines: [line],
}

async function render() {
  const wrapper = mount(SampleMaterialIssueView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}
function submitButton(wrapper: Awaited<ReturnType<typeof render>>) {
  return wrapper.findAll('button').find(button => button.text() === '全部领料')!
}

beforeEach(() => {
  vi.resetAllMocks()
  route.name = 'sample-material-issue-confirm'
  mocks.sample.mockResolvedValue({ data: { id: 'sample-1', request_number: 'SRQ-1', status: 'MATERIAL_ISSUE_REVIEW', status_display: '待仓库确认领料', products: [] } })
  mocks.issue.mockResolvedValue({ data: pending, etag: 'preview-v1' })
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
})
afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })

describe('样品全部领料页面', () => {
  it('保留原列并只读展示根米、仓库可供和冻结采购量', async () => {
    const wrapper = await render()
    const cells = wrapper.findAll('.issue-table tbody td')
    expect(wrapper.findAll('.issue-table thead th')).toHaveLength(13)
    expect(cells[6]!.text()).toBe('0')
    expect(cells[7]!.text()).toBe('8')
    expect(cells[8]!.text()).toBe('12')
    expect(wrapper.find('[data-testid="readonly-issued-quantity"]').text()).toBe('2 根 / 12 米')
    expect(cells[9]!.attributes('title')).toBe('材料仓 / 一区：2 根 × 6 米 = 12 米')
    expect(wrapper.find('.issue-table input').exists()).toBe(false)
    expect(submitButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('全部领料只传请求标识和版本，成功显示服务端已领状态', async () => {
    mocks.confirm.mockResolvedValueOnce({ data: { ...pending, status: 'ISSUED', statusLabel: '已领料', canConfirm: false, lines: [{ ...line, issuedQuantity: '12.0000' }] }, etag: 'done-v2' })
    const wrapper = await render()
    await submitButton(wrapper).trigger('click')
    await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('按页面数量扣减库存'), '全部领料', expect.objectContaining({ confirmButtonText: '确认全部领料' }))
    expect(mocks.confirm).toHaveBeenCalledWith('sample-1', 'preview-v1', expect.stringMatching(/^[0-9a-f-]{36}$/i))
    expect(mocks.confirm.mock.calls[0]).toHaveLength(3)
    expect(wrapper.text()).toContain('已领料')
    expect(wrapper.findAll('button').some(button => button.text() === '全部领料')).toBe(false)
    expect(wrapper.find('[data-testid="readonly-issued-quantity"]').text()).toBe('2 根 / 12 米')
  })

  it.each([['4.0000', '4'], ['4.5000', '4.5']])('实际领料米数 %s 去掉无意义尾零且保留有效小数', async (quantity, display) => {
    mocks.issue.mockResolvedValueOnce({ data: { ...pending, lines: [{ ...line, arrivedQuantity: quantity, availableQuantity: quantity }] }, etag: 'v1' })
    const wrapper = await render()
    expect(wrapper.find('[data-testid="readonly-issued-quantity"]').text()).toBe(`2 根 / ${display} 米`)
    expect(wrapper.findAll('.issue-table tbody td')[8]!.text()).toBe(quantity)
  })

  it('网络失败重试沿用同一请求标识与原ETag', async () => {
    mocks.confirm.mockRejectedValueOnce(new AxiosError('网络中断')).mockResolvedValueOnce({ data: { ...pending, status: 'ISSUED', canConfirm: false }, etag: 'done' })
    const wrapper = await render()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.find('.action-error').text()).toContain('提交失败')
    const firstCall = mocks.confirm.mock.calls[0]!
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(mocks.confirm.mock.calls[1]).toEqual(firstCall)
  })

  it('提交等待期间禁用按钮，不重复发送', async () => {
    let resolve!: (value: unknown) => void
    mocks.confirm.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = await render()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    await submitButton(wrapper).trigger('click')
    expect(mocks.confirm).toHaveBeenCalledOnce()
    resolve({ data: { ...pending, status: 'ISSUED', canConfirm: false }, etag: 'done' })
    await flushPromises()
  })

  it('库存不足显示服务端原因并禁用确认，不伪造管材根数', async () => {
    mocks.issue.mockResolvedValueOnce({ data: { ...pending, canConfirm: false, blockers: ['管材库存不足，请核对。'], lines: [{ ...line, barCount: 0, pipeBatches: [] }] }, etag: 'v1' })
    const wrapper = await render()
    expect(wrapper.find('[role="alert"]').text()).toContain('管材库存不足')
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="readonly-issued-quantity"]').text()).toBe('— 根 / 12 米')
    await submitButton(wrapper).trigger('click')
    expect(mocks.confirm).not.toHaveBeenCalled()
  })

  it('无确认权限保持只读，已领且有缺口时保留真实数量', async () => {
    mocks.issue.mockResolvedValueOnce({ data: { ...pending, canConfirm: false }, etag: 'v1' })
    const readonly = await render()
    expect(submitButton(readonly).attributes('disabled')).toBeDefined()
    readonly.unmount()
    mocks.issue.mockResolvedValueOnce({ data: { ...pending, status: 'ISSUED', statusLabel: '已领料', canConfirm: false, lines: [{ ...line, category: 'hardware', warehouseQuantity: '2', procurementQuantity: '2', availableQuantity: '2', issuedQuantity: '2', shortageQuantity: '2', unitLabel: '个', barCount: null, pipeBatches: [] }] }, etag: 'v2' })
    const done = await render()
    expect(done.find('[data-testid="readonly-issued-quantity"]').text()).toBe('2')
    expect(done.findAll('.issue-table tbody td')[10]!.text()).toBe('2')
    expect(done.text()).toContain('已领料')
    expect(done.find('.issue-table input').exists()).toBe(false)
  })

  it('发起页面继续允许先领现有可供材料', async () => {
    route.name = 'sample-material-issue'
    mocks.issue.mockResolvedValueOnce({ data: { ...pending, status: 'NOT_STARTED', canConfirm: false, canInitiate: true, lines: [{ ...line, category: 'hardware', warehouseQuantity: '2', arrivedQuantity: '0', availableQuantity: '2', shortageQuantity: '6', barCount: null, pipeBatches: [] }] }, etag: 'v1' })
    mocks.initiate.mockResolvedValueOnce({ data: pending, etag: 'v2' })
    const wrapper = await render()
    expect(wrapper.find('[data-testid="readonly-issued-quantity"]').text()).toBe('2')
    const button = wrapper.findAll('button').find(item => item.text() === '发起领料')!
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click'); await flushPromises()
    expect(mocks.initiate).toHaveBeenCalledWith('sample-1', 'v1', '')
  })
})
