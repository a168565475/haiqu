import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OutsourcingPrintDialog from './OutsourcingPrintDialog.vue'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'

const api = vi.hoisted(() => ({ tube: vi.fn(), regular: vi.fn(), tubeDocument: vi.fn(), regularDocument: vi.fn(), pdf: vi.fn() }))
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: api.tube }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingOrder: api.regular }))
vi.mock('@/api/outsourcingPrint', () => ({ fetchOutsourcingPrintPdf: api.pdf }))
vi.mock('@/utils/outsourcingPrint', () => ({ buildTubePrintDocument: api.tubeDocument, buildRegularPrintDocument: api.regularDocument }))
const wrappers: ReturnType<typeof mount>[] = []
const record = { id: 'tube-1', record_type: 'TUBE', source_kind: 'TUBE_METAL', detail_access: 'TUBE' } as UnifiedOutsourcingOrder
function create(kind: 'processing' | 'spray' = 'processing', row = record, warehouse = false, previewOnly = false) {
  const wrapper = mount(OutsourcingPrintDialog, { props: { record: row, kind, warehouse, previewOnly }, global: { stubs: {
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
  api.tubeDocument.mockReturnValue({ title: '真实管材打印单', orderNumber: 'WF-1' })
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

  it('下载菜单打开预览，点击弹窗里的按钮才保存 PDF', async () => {
    api.pdf.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }))
    const createUrl = vi.fn(() => 'blob:outsourcing-pdf')
    const revokeUrl = vi.fn()
    const previousCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const previousRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl })
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download)
    })
    try {
      const wrapper = create('spray', record, true, true)
      await flushPromises()
      expect(wrapper.text()).toContain('真实管材打印单')
      expect(api.pdf).not.toHaveBeenCalled()
      expect(clicked).toEqual([])
      expect(window.print).not.toHaveBeenCalled()
      await wrapper.get('[data-testid="outsourcing-pdf-download"]').trigger('click')
      await flushPromises()
      expect(api.pdf).toHaveBeenCalledExactlyOnceWith(record, 'spray', true)
      expect(clicked).toEqual(['WF-1_管材喷塑计划.pdf'])
      expect(revokeUrl).toHaveBeenCalledWith('blob:outsourcing-pdf')
      expect(window.print).not.toHaveBeenCalled()
    } finally {
      if (previousCreate) Object.defineProperty(URL, 'createObjectURL', previousCreate)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (previousRevoke) Object.defineProperty(URL, 'revokeObjectURL', previousRevoke)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('下载失败时保留单据预览并能重试', async () => {
    api.pdf.mockRejectedValue(new Error('offline'))
    const wrapper = create('processing', record, false, true)
    await flushPromises()
    const download = wrapper.get('[data-testid="outsourcing-pdf-download"]')
    await download.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('PDF 下载失败')
    expect(wrapper.text()).toContain('真实管材打印单')
    await download.trigger('click')
    await flushPromises()
    expect(api.pdf).toHaveBeenCalledTimes(2)
    expect(window.print).not.toHaveBeenCalled()
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
