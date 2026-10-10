import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorkReport } from '@/types/workshopReporting'
import WorkReportDeleteDialog from './WorkReportDeleteDialog.vue'

const api = vi.hoisted(() => ({ remove: vi.fn(), fetch: vi.fn() }))
vi.mock('@/api/workshopReporting', () => ({ deleteWorkReport: api.remove, fetchWorkReport: api.fetch }))
const report = { id: 'report-1', report_number: 'BG-001', workshop: { id: 'metal', name: '金工车间' },
  total_amount: '23.45', etag: '"revision-1"', can_delete: true } as WorkReport
async function open() {
  const wrapper = mount(WorkReportDeleteDialog, { props: { modelValue: false, report }, global: { stubs: {
    AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot/><slot name="footer"/></section>' },
  } } })
  await wrapper.setProps({ modelValue: true }); return wrapper
}
const button = (w: Awaited<ReturnType<typeof open>>, label: string) => w.findAll('button').find(b => b.text() === label)!
beforeEach(() => { vi.resetAllMocks(); api.remove.mockResolvedValue(undefined) })
describe('报工删除确认', () => {
  it('拒绝空白原因并携带当前版本提交一次', async () => {
    const w = await open(); expect(button(w, '确认删除').attributes('disabled')).toBeDefined()
    await w.get('textarea').setValue('   '); expect(button(w, '确认删除').attributes('disabled')).toBeDefined()
    await w.get('textarea').setValue('  重复录入  '); await button(w, '确认删除').trigger('click'); await flushPromises()
    expect(api.remove).toHaveBeenCalledExactlyOnceWith('report-1', '重复录入', '"revision-1"')
    expect(w.emitted('deleted')).toHaveLength(1); w.unmount()
  })
  it('提交期间禁止再次提交和关闭', async () => {
    let finish!: () => void; api.remove.mockReturnValue(new Promise<void>(resolve => { finish = resolve }))
    const w = await open(); await w.get('textarea').setValue('误录'); await button(w, '确认删除').trigger('click')
    expect(button(w, '处理中…').attributes('disabled')).toBeDefined()
    expect(button(w, '取消').attributes('disabled')).toBeDefined()
    expect(w.get('textarea').attributes('disabled')).toBeDefined()
    await button(w, '处理中…').trigger('click'); expect(api.remove).toHaveBeenCalledTimes(1)
    finish(); await flushPromises(); w.unmount()
  })
  it('失败保留原因且不自动重试，核对后使用新 ETag', async () => {
    api.remove.mockRejectedValueOnce({ isAxiosError: true, response: { status: 412, data: { error: { message: '记录已变化' } } } })
    api.fetch.mockResolvedValue({ data: { ...report, total_amount: '46.90' }, etag: '"revision-2"' })
    const w = await open(); await w.get('textarea').setValue('误录'); await button(w, '确认删除').trigger('click'); await flushPromises()
    expect(w.get('textarea').element.value).toBe('误录'); expect(w.text()).toContain('记录已变化')
    expect(api.remove).toHaveBeenCalledTimes(1); expect(button(w, '确认删除').attributes('disabled')).toBeDefined()
    await button(w, '核对当前记录').trigger('click'); await flushPromises()
    expect(w.text()).toContain('46.90'); await button(w, '确认删除').trigger('click'); await flushPromises()
    expect(api.remove).toHaveBeenLastCalledWith('report-1', '误录', '"revision-2"'); w.unmount()
  })
  it('核对发现记录已删除时仅刷新列表，不再次删除', async () => {
    api.remove.mockRejectedValueOnce({ isAxiosError: true, code: 'ECONNABORTED' })
    api.fetch.mockRejectedValue({ isAxiosError: true, response: { status: 404 } })
    const w = await open(); await w.get('textarea').setValue('误录'); await button(w, '确认删除').trigger('click'); await flushPromises()
    await button(w, '核对当前记录').trigger('click'); await flushPromises()
    expect(api.remove).toHaveBeenCalledTimes(1); expect(w.emitted('deleted')).toHaveLength(1); w.unmount()
  })
})
