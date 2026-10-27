import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OutsourcingPrintDialog from './OutsourcingPrintDialog.vue'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'

const api = vi.hoisted(() => ({ tube: vi.fn(), regular: vi.fn(), tubeDocument: vi.fn(), regularDocument: vi.fn() }))
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: api.tube }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingOrder: api.regular }))
vi.mock('@/utils/outsourcingPrint', () => ({ buildTubePrintDocument: api.tubeDocument, buildRegularPrintDocument: api.regularDocument }))
const wrappers: ReturnType<typeof mount>[] = []
const record = { id: 'tube-1', record_type: 'TUBE', source_kind: 'TUBE_METAL', detail_access: 'TUBE' } as UnifiedOutsourcingOrder
function create(kind: 'processing' | 'spray' = 'processing', row = record, warehouse = false) {
  const wrapper = mount(OutsourcingPrintDialog, { props: { record: row, kind, warehouse }, global: { stubs: {
    AppWindowDialog: { template: '<section><slot/><slot name="footer"/></section>' },
    OutsourcingPrintDocument: { props: ['document'], template: '<article>{{ document.title }}</article>' },
    ElButton: { template: '<button><slot/></button>' }, ElAlert: { props: ['title'], template: '<div>{{ title }}</div>' }, ElSkeleton: true,
  } } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.spyOn(window, 'print').mockImplementation(() => {})
  api.tube.mockResolvedValue({ id: 'tube-1', category: 'tube', source_kind: 'METAL' })
  api.tubeDocument.mockReturnValue({ title: '真实管材打印单' })
  api.regular.mockResolvedValue({ data: { id: 'regular-1' } })
  api.regularDocument.mockReturnValue({ title: '普通委外加工单' })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('外发打印只读加载与失败恢复', () => {
  it('仓库打印沿用对应动作读取范围，不能退回车间查看范围', async () => {
    create('processing', record, true)
    await flushPromises()
    expect(api.tube).toHaveBeenCalledWith('tube-1', true)
    create('processing', { ...record, id: 'regular-1', record_type: 'ORIGINAL', detail_access: 'REGULAR' }, true)
    await flushPromises()
    expect(api.regular).toHaveBeenCalledWith('regular-1', true)
  })
  it('读取最新管材详情，分别选择模板且每次仅调用一次打印', async () => {
    const wrapper = create('spray')
    expect(window.print).not.toHaveBeenCalled()
    await flushPromises()
    expect(api.tube).toHaveBeenCalledExactlyOnceWith('tube-1')
    expect(api.tubeDocument).toHaveBeenCalledWith(expect.objectContaining({ id: 'tube-1' }), 'spray')
    expect(wrapper.text()).toContain('真实管材打印单')
    expect(window.print).toHaveBeenCalledTimes(1)
    expect(api.regular).not.toHaveBeenCalled()
  })

  it('普通单读取普通详情，不请求管材接口', async () => {
    create('processing', { ...record, id: 'regular-1', record_type: 'ORIGINAL', detail_access: 'REGULAR' })
    await flushPromises()
    expect(api.regular).toHaveBeenCalledExactlyOnceWith('regular-1')
    expect(api.regularDocument).toHaveBeenCalledWith({ id: 'regular-1' })
    expect(window.print).toHaveBeenCalledTimes(1)
    expect(api.tube).not.toHaveBeenCalled()
  })

  it('加载失败保留错误提示，不打印空单，重试后才打印', async () => {
    api.tube.mockRejectedValueOnce(new Error('offline'))
    const wrapper = create()
    await flushPromises()
    expect(wrapper.text()).toContain('打印数据读取失败')
    expect(window.print).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="print-retry"]').trigger('click')
    await flushPromises()
    expect(api.tube).toHaveBeenCalledTimes(2)
    expect(window.print).toHaveBeenCalledTimes(1)
  })

  it('关闭后迟到的响应不能打开系统打印，也不能打印裁片喷塑单', async () => {
    let resolve!: (value: unknown) => void
    api.tube.mockReturnValueOnce(new Promise(value => { resolve = value }))
    const wrapper = create()
    wrapper.unmount()
    resolve({ id: 'tube-1', category: 'tube', source_kind: 'METAL' })
    await flushPromises()
    expect(window.print).not.toHaveBeenCalled()
    api.tube.mockResolvedValue({ category: 'cutting', source_kind: 'SEWING' })
    const invalid = create('spray')
    await flushPromises()
    expect(invalid.text()).toContain('仅支持管材喷塑单')
    expect(window.print).not.toHaveBeenCalled()
  })
})
