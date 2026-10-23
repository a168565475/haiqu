import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElInputNumber, ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import InquiryHandlingSettingsView from './InquiryHandlingSettingsView.vue'

const api = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), canEdit: true }))
vi.mock('@/api/inquiryHandlingSettings', () => ({ fetchInquiryHandlingSettings: api.load, saveInquiryHandlingSettings: api.save }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => api.canEdit }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
const data = () => ({ stage_minutes: { ASSIGNMENT: 30, FIRST_RESPONSE: 240, REQUIREMENT_CONFIRMATION: 120, QUOTE_CREATION: 60, QUOTE_DELIVERY: 240, CUSTOMER_FOLLOW_UP: 450, POST_ACCEPTANCE: 120, SAMPLE_FOLLOW_UP: 450 }, work_calendar: { mode: 'ALTERNATING_WEEKS_V1', timezone: 'Asia/Shanghai', rest_saturday: '2026-09-05', periods: [[510, 720], [810, 1050]] } })
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(InquiryHandlingSettingsView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
const saveButton = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('button').find(button => button.text() === '保存规则')!
beforeEach(() => {
  vi.clearAllMocks()
  api.canEdit = true
  api.load.mockResolvedValue({ data: data(), etag: 'v1' })
  api.save.mockImplementation(async payload => ({ data: payload, etag: 'v2' }))
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('询盘时限规则设置', () => {
  it('嵌入配置窗口时未修改直接关闭，修改后支持继续编辑与明确放弃', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel').mockResolvedValueOnce('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
    const wrapper = await render()
    expect(await wrapper.vm.canClose()).toBe(true)
    expect(confirm).not.toHaveBeenCalled()
    await wrapper.find('input[aria-label="下午开始"]').setValue('14:00')
    expect(await wrapper.vm.canClose()).toBe(false)
    expect((wrapper.find('input[aria-label="下午开始"]').element as HTMLInputElement).value).toBe('14:00')
    expect(await wrapper.vm.canClose()).toBe(true)
    expect(api.save).not.toHaveBeenCalled()
  })

  it('保存进行中阻止父窗口关闭，保存成功后不再提示未保存', async () => {
    let finish!: (value: unknown) => void
    api.save.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    const wrapper = await render()
    await wrapper.find('input[aria-label="下午开始"]').setValue('14:00')
    await saveButton(wrapper).trigger('click')
    expect(await wrapper.vm.canClose()).toBe(false)
    expect(confirm).not.toHaveBeenCalled()
    finish({ data: api.save.mock.calls[0]![0], etag: 'v2' }); await flushPromises()
    expect(await wrapper.vm.canClose()).toBe(true)
    expect(confirm).not.toHaveBeenCalled()
  })

  it('展示八个环节和已确认日历，保存改动时携带版本', async () => {
    const wrapper = await render()
    expect(wrapper.findAllComponents(ElInputNumber)).toHaveLength(8)
    expect((wrapper.find('input[aria-label="上午开始"]').element as HTMLInputElement).value).toBe('08:30')
    wrapper.findAllComponents(ElInputNumber)[1]!.vm.$emit('update:modelValue', 300)
    await wrapper.find('input[aria-label="下午开始"]').setValue('14:00')
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ stage_minutes: expect.objectContaining({ FIRST_RESPONSE: 300 }), work_calendar: expect.objectContaining({ periods: [[510, 720], [840, 1050]] }) }), 'v1')
    expect(ElMessage.success).toHaveBeenCalled()
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.save.mock.calls[1]![1]).toBe('v2')
  })
  it('重叠时段、分配时限超过回复时限都不能保存', async () => {
    const wrapper = await render()
    await wrapper.find('input[aria-label="下午开始"]').setValue('11:00')
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('不重叠')
    expect(api.save).not.toHaveBeenCalled()
    await wrapper.find('input[aria-label="下午开始"]').setValue('13:30')
    wrapper.findAllComponents(ElInputNumber)[0]!.vm.$emit('update:modelValue', 300)
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('不能超过首次回复')
    expect(api.save).not.toHaveBeenCalled()
  })
  it('只读账号不能修改或保存，读取失败有明确提示', async () => {
    api.canEdit = false
    const wrapper = await render()
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.findAllComponents(ElInputNumber).every(input => input.props('disabled'))).toBe(true)
    api.load.mockRejectedValueOnce(new Error('规则加载失败'))
    const failed = await render()
    expect(failed.text()).toContain('规则加载失败')
    expect(saveButton(failed).attributes('disabled')).toBeDefined()
  })
  it('版本冲突保留输入并提示重新加载，不显示成功', async () => {
    api.save.mockRejectedValueOnce(new AxiosError('conflict', undefined, undefined, undefined, { status: 412 } as never))
    const wrapper = await render()
    wrapper.findAllComponents(ElInputNumber)[1]!.vm.$emit('update:modelValue', 300)
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('规则已被其他人修改')
    expect(wrapper.findAllComponents(ElInputNumber)[1]!.props('modelValue')).toBe(300)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })
})
