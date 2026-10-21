import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElButton, ElDropdown, ElDropdownItem, ElFormItem, ElInput, ElOption, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkshopEmployee, WorkshopEmployeeOption, WorkshopEmployeeOptions } from '@/types/workshopConfig'
import WorkshopConfigManager from './WorkshopConfigManager.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), create: vi.fn(), update: vi.fn() }))
const feedback = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn(), success: vi.fn(), confirm: vi.fn() }))
const auth = vi.hoisted(() => ({ user: { is_superuser: false }, hasPermission: vi.fn() }))
vi.mock('@/api/workshopConfig', () => ({
  fetchWorkshopConfigList: api.list,
  fetchWorkshopConfigDetail: api.detail,
  fetchWorkshopEmployeeOptions: api.options,
  createWorkshopConfig: api.create,
  updateWorkshopConfig: api.update,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: feedback,
  ElMessageBox: { confirm: feedback.confirm },
}))

const legacy: WorkshopEmployee = {
  id: 'assignment-1', workshop: 'workshop-1', workshop_name: '金工车间', position: '组长',
  name: '同名员工', employee: null, employee_code: null, employee_name: null, employee_status: null,
  employee_archived: false, is_supervisor: true, status: 'ACTIVE', status_display: '在职',
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
}
const candidates: WorkshopEmployeeOption[] = [
  { id: 'employee-a', employee_code: 'E001', display_name: '同名员工', status: 'ACTIVE', etag: '"a1"' },
  { id: 'employee-b', employee_code: 'E002', display_name: '同名员工', status: 'ACTIVE', etag: '"b1"' },
]
const optionResult = (data = candidates): WorkshopEmployeeOptions => ({
  data, meta: { page: 1, page_size: 50, total: data.length, total_pages: data.length ? 1 : 0 },
})
const wrappers: VueWrapper[] = []

async function render(record = legacy) {
  api.list.mockImplementation((kind: string) => Promise.resolve({
    data: kind === 'workshops' ? [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }] : [record],
    meta: { page: 1, page_size: 20, total: 1, total_pages: 1 },
  }))
  api.detail.mockResolvedValue({ data: record, etag: '"assignment-v1"' })
  const wrapper = mount(WorkshopConfigManager, {
    props: { kind: 'employees' },
    global: {
      plugins: [ElementPlus],
      stubs: {
        AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue" role="dialog"><slot/><slot name="footer"/></section>' },
      },
    },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

const button = (wrapper: VueWrapper, label: string) => wrapper.findAll('button').find((item) => item.text() === label)!
const field = (wrapper: VueWrapper, label: string) => wrapper.findAllComponents(ElFormItem).find((item) => item.props('label') === label)!
const identity = (wrapper: VueWrapper) => field(wrapper, '选择员工').getComponent(ElSelect)
async function setSelect(wrapper: VueWrapper, label: string, value: string | boolean) {
  const select = field(wrapper, label).getComponent(ElSelect)
  select.vm.$emit('update:modelValue', value)
  select.vm.$emit('change', value)
  await flushPromises()
}
async function edit(wrapper: VueWrapper) {
  wrapper.getComponent(ElDropdown).vm.$emit('command', 'edit')
  await flushPromises()
}
async function newAssignment(wrapper: VueWrapper) {
  await button(wrapper, '新增员工').trigger('click')
  await flushPromises()
  await setSelect(wrapper, '车间', 'workshop-1')
  field(wrapper, '岗位').getComponent(ElInput).vm.$emit('update:modelValue', '组长')
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  auth.hasPermission.mockReturnValue(true)
  api.options.mockResolvedValue(optionResult())
  api.create.mockResolvedValue({})
  api.update.mockResolvedValue({})
  feedback.confirm.mockResolvedValue(undefined)
})
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

describe('车间员工选择统一员工', () => {
  it('新建必须显式选人，同名候选按工号区分并仅提交所选 ID', async () => {
    const wrapper = await render()
    expect(api.options).not.toHaveBeenCalled()
    await newAssignment(wrapper)
    expect(identity(wrapper).props('modelValue')).toBe('')
    expect(identity(wrapper).findAllComponents(ElOption).map((option) => option.props('label'))).toEqual(['同名员工（E001）', '同名员工（E002）'])
    await button(wrapper, '保存').trigger('click')
    expect(api.create).not.toHaveBeenCalled()
    expect(feedback.warning).toHaveBeenCalledWith('请选择统一员工。')
    await setSelect(wrapper, '选择员工', 'employee-b')
    await setSelect(wrapper, '是否为主管', true)
    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(api.create).toHaveBeenCalledExactlyOnceWith('employees', {
      employee: 'employee-b', workshop: 'workshop-1', position: '组长', is_supervisor: true, status: 'ACTIVE',
    })
  })

  it('历史同名记录保持待关联，可只编辑车间配置而不自动选人或提交姓名', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('同名员工（待关联）')
    await edit(wrapper)
    expect(identity(wrapper).props('modelValue')).toBe('')
    expect(wrapper.text()).toContain('不会按姓名自动关联')
    expect(api.options).toHaveBeenCalledWith({ q: undefined, page: 1, page_size: 50 })
    await setSelect(wrapper, '车间任职状态', 'LEFT')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledExactlyOnceWith('employees', 'assignment-1', {
      workshop: 'workshop-1', position: '组长', is_supervisor: true, status: 'LEFT',
    }, '"assignment-v1"')
  })

  it('历史记录人工首次关联仍更新原记录，并保留 ETag', async () => {
    const wrapper = await render()
    await edit(wrapper)
    await setSelect(wrapper, '选择员工', 'employee-a')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledExactlyOnceWith('employees', 'assignment-1', {
      employee: 'employee-a', workshop: 'workshop-1', position: '组长', is_supervisor: true, status: 'ACTIVE',
    }, '"assignment-v1"')
  })

  it('已绑定但停用归档的员工仍回显当前姓名和工号，不能更换或解绑', async () => {
    const wrapper = await render({ ...legacy, employee: 'employee-a', employee_name: '现用姓名', employee_code: 'E001', employee_status: 'LEFT', employee_archived: true })
    expect(wrapper.text()).toContain('现用姓名（E001）')
    expect(wrapper.findAllComponents(ElDropdownItem).find((item) => item.props('command') === 'toggle')?.props('disabled')).toBe(false)
    await edit(wrapper)
    expect(identity(wrapper).props('disabled')).toBe(true)
    expect(identity(wrapper).props('clearable')).toBe(false)
    expect(identity(wrapper).props('modelValue')).toBe('employee-a')
    expect(identity(wrapper).getComponent(ElOption).props('label')).toBe('现用姓名（E001）')
    expect(wrapper.text()).toContain('该员工已停用或归档，请结束车间任职后保存。')
    expect(api.options).not.toHaveBeenCalled()
    const statusOptions = field(wrapper, '车间任职状态').findAllComponents(ElOption)
    expect(statusOptions.find((item) => item.props('value') === 'ACTIVE')?.props('disabled')).toBe(true)
    expect(statusOptions.find((item) => item.props('value') === 'LEFT')?.props('disabled')).toBe(false)
    await button(wrapper, '保存').trigger('click')
    expect(api.update).not.toHaveBeenCalled()
    expect(feedback.warning).toHaveBeenCalledWith('该员工已停用或归档，请结束车间任职后保存。')
    await setSelect(wrapper, '车间任职状态', 'LEFT')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(api.update.mock.calls[0]?.[2]).toHaveProperty('status', 'LEFT')
    expect(api.update.mock.calls[0]?.[2]).not.toHaveProperty('employee')
    expect(api.update.mock.calls[0]?.[2]).not.toHaveProperty('name')
  })

  it('已结束车间任职的停用员工仍可编辑岗位和主管', async () => {
    const wrapper = await render({ ...legacy, employee: 'employee-a', employee_name: '统一员工', employee_code: 'E001', employee_status: 'INACTIVE', status: 'LEFT' })
    expect(wrapper.findAllComponents(ElDropdownItem).find((item) => item.props('command') === 'toggle')?.props('disabled')).toBe(true)
    expect(wrapper.findAllComponents(ElDropdownItem).find((item) => item.props('command') === 'edit')?.props('disabled')).toBe(false)
    await edit(wrapper)
    field(wrapper, '岗位').getComponent(ElInput).vm.$emit('update:modelValue', '历史组长')
    await setSelect(wrapper, '是否为主管', false)
    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledExactlyOnceWith('employees', 'assignment-1', {
      workshop: 'workshop-1', position: '历史组长', is_supervisor: false, status: 'LEFT',
    }, '"assignment-v1"')
  })

  it('只读用户不请求候选，也没有新建或修改入口', async () => {
    auth.hasPermission.mockImplementation((permission: string) => permission === 'workshop_config.view_workshopemployee')
    const wrapper = await render()
    expect(button(wrapper, '新增员工')).toBeUndefined()
    expect(wrapper.findComponent(ElDropdown).exists()).toBe(false)
    expect(api.options).not.toHaveBeenCalled()
  })

  it('搜索结果乱序返回时保留最新结果及已选员工，不回退到旧搜索', async () => {
    const wrapper = await render()
    await newAssignment(wrapper)
    await setSelect(wrapper, '选择员工', 'employee-b')
    let finishOld!: (result: WorkshopEmployeeOptions) => void
    api.options.mockReturnValueOnce(new Promise<WorkshopEmployeeOptions>((resolve) => { finishOld = resolve }))
    const remoteSearch = identity(wrapper).props('remoteMethod') as (query: string) => Promise<void>
    const oldSearch = remoteSearch('旧')
    const latest = { id: 'employee-c', employee_code: 'E003', display_name: '最新员工', status: 'ACTIVE', etag: '"c1"' }
    api.options.mockResolvedValueOnce(optionResult([latest]))
    await remoteSearch('最新')
    finishOld(optionResult([candidates[0]!]))
    await oldSearch
    await flushPromises()
    expect(identity(wrapper).props('modelValue')).toBe('employee-b')
    expect(identity(wrapper).findAllComponents(ElOption).map((option) => option.props('label'))).toEqual(['同名员工（E002）', '最新员工（E003）'])
  })

  it('候选加载失败明确提示，重试后可选；空结果不会代填员工', async () => {
    api.options.mockRejectedValueOnce({ response: { status: 503, data: { error: { message: '员工目录暂不可用' } } } })
    const wrapper = await render()
    await newAssignment(wrapper)
    expect(wrapper.get('.employee-identity-error').text()).toBe('员工目录暂不可用')
    expect(identity(wrapper).props('modelValue')).toBe('')
    api.options.mockResolvedValueOnce(optionResult([]))
    await (identity(wrapper).props('remoteMethod') as (query: string) => Promise<void>)('不存在')
    await flushPromises()
    expect(wrapper.find('.employee-identity-error').exists()).toBe(false)
    expect(identity(wrapper).props('noDataText')).toBe('暂无可选的在职员工')
    expect(identity(wrapper).props('modelValue')).toBe('')
  })

  it('加载更多保留已有候选，并按下一页读取相同搜索条件', async () => {
    api.options.mockResolvedValueOnce({
      data: [candidates[0]!], meta: { page: 1, page_size: 50, total: 51, total_pages: 2 },
    })
    const wrapper = await render()
    await newAssignment(wrapper)
    api.options.mockResolvedValueOnce({
      data: [candidates[1]!], meta: { page: 2, page_size: 50, total: 51, total_pages: 2 },
    })
    const more = identity(wrapper).findAllComponents(ElButton).find((item) => item.text() === '加载更多员工')!
    await more.trigger('click')
    await flushPromises()
    expect(api.options).toHaveBeenLastCalledWith({ q: undefined, page: 2, page_size: 50 })
    expect(identity(wrapper).findAllComponents(ElOption).map((option) => option.props('value'))).toEqual(['employee-a', 'employee-b'])
    expect(identity(wrapper).findAllComponents(ElButton).some((item) => item.text() === '加载更多员工')).toBe(false)
  })

  it('版本冲突保留人工选择和编辑内容，不自动重试写入', async () => {
    api.update.mockRejectedValueOnce({ response: { status: 412, data: { error: { message: '配置已变化，请重新读取' } } } })
    const wrapper = await render()
    await edit(wrapper)
    await setSelect(wrapper, '选择员工', 'employee-b')
    await button(wrapper, '保存').trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(identity(wrapper).props('modelValue')).toBe('employee-b')
    expect(feedback.error).toHaveBeenCalledWith('配置已变化，请重新读取')
  })

  it('结束车间任职只提交本记录状态，并提示不改变统一员工状态', async () => {
    const wrapper = await render()
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'toggle')
    await flushPromises()
    expect(feedback.confirm.mock.calls[0]?.[0]).toContain('仅修改车间任职状态，不修改统一员工状态')
    expect(api.update).toHaveBeenCalledExactlyOnceWith('employees', 'assignment-1', { status: 'LEFT' }, '"assignment-v1"')
  })
})
