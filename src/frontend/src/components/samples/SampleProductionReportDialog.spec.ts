import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Dialog from './SampleProductionReportDialog.vue'
import type { SampleDetail } from '@/types/sample'
const api = vi.hoisted(() => ({ report: vi.fn() }))
vi.mock('@/api/samples', () => ({ reportSampleProduction: api.report }))
const wrappers: ReturnType<typeof mount>[] = []
async function render(workflow_actions?: Partial<SampleDetail['workflow_actions']>, itemOverrides: Partial<{ metalwork_completed: boolean; cutting_completed: boolean; metalwork_reported_quantity: number; cutting_reported_quantity: number }> = {}) {
  const wrapper = mount(Dialog, { props: { modelValue: false, etag: 'v1', sample: {
    id: 'sample', workflow_actions, items: [{ id: 'item', product_description_snapshot: '折叠椅', specification_snapshot: '50×60', sample_quantity: 3,
      metalwork_reported_quantity: 0, cutting_reported_quantity: 0, metalwork_completed: false, cutting_completed: false, ...itemOverrides }],
  } as SampleDetail }, global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await wrapper.setProps({ modelValue: true }); await flushPromises()
  return wrapper
}
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks(); document.body.innerHTML = '' })
describe('新版精简报工', () => {
  it('只有金工权限时裁剪只读且不提交裁剪字段', async () => {
    api.report.mockResolvedValue({ data: { id: 'sample' }, etag: 'v2' })
    await render({ can_report_production: true, can_report_metalwork: true, can_report_cutting: false })
    expect(document.querySelector<HTMLInputElement>('input[aria-label="裁剪报工数量"]')!.disabled).toBe(true)
    expect(document.querySelector<HTMLInputElement>('input[aria-label="金工报工数量"]')!.disabled).toBe(false)
    ;[...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes('保存报工'))!.click()
    await flushPromises()
    expect(api.report).toHaveBeenCalledWith('sample', 'v1', [{ id: 'item', metalwork_reported_quantity: 0, metalwork_completed: false }])
  })
  it('只发送报工字段和版本，失败保留输入并阻止重复提交', async () => {
    let reject!: (error: Error) => void
    api.report.mockImplementationOnce(() => new Promise((_ok, fail) => { reject = fail }))
    await render()
    const input = document.querySelector<HTMLInputElement>('input[aria-label="金工报工数量"]')!
    input.value = '2'; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    const save = [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes('保存报工'))!
    save.click(); await flushPromises(); save.click()
    expect(api.report).toHaveBeenCalledTimes(1)
    expect(api.report).toHaveBeenCalledWith('sample', 'v1', [{ id: 'item', metalwork_reported_quantity: 2, cutting_reported_quantity: 0, metalwork_completed: false, cutting_completed: false }])
    reject(new Error('版本冲突')); await flushPromises()
    expect(document.body.textContent).toContain('版本冲突')
    expect(input.value).toBe('2')
  })
  it('成功后交回服务端状态和新版本，不在前端推测完成', async () => {
    api.report.mockResolvedValue({ data: { id: 'sample', status: 'PRODUCTION_PENDING' }, etag: 'v2' })
    const wrapper = await render()
    ;[...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes('保存报工'))!.click()
    await flushPromises()
    expect(wrapper.emitted('saved')?.[0]).toEqual([{ id: 'sample', status: 'PRODUCTION_PENDING' }, 'v2'])
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
  })
  it('工序完成时数量为零会被前端拦截', async () => {
    await render(undefined, { metalwork_completed: true })
    const save = [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes('保存报工'))!
    save.click()
    await flushPromises()
    expect(api.report).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('报工数量必须大于 0')
  })
})
