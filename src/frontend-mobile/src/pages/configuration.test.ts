import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { Field } from 'vant'
import ConfigurationPage from './configuration.vue'

const mocks = vi.hoisted(() => ({ list: vi.fn(), options: vi.fn(), detail: vi.fn(), update: vi.fn(), remove: vi.fn(), permission: vi.fn(), push: vi.fn(), confirm: vi.fn(), success: vi.fn() }))
vi.mock('@/api/workshopEmployees', () => ({ fetchWorkshopEmployees: mocks.list, fetchWorkshopEmployeeOptions: mocks.options, fetchWorkshopEmployee: mocks.detail, updateWorkshopEmployee: mocks.update, deleteWorkshopEmployee: mocks.remove }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: mocks.permission }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('vant', async original => ({ ...await original<typeof import('vant')>(), showConfirmDialog: mocks.confirm, showSuccessToast: mocks.success }))
const employee = { id: 'worker-1', name: '员工甲', employee_name: '员工甲', employee_code: 'E001', employee: 'worker-1', employee_status: 'ACTIVE', employee_archived: false, workshop: 'metal', workshop_name: '金工车间', position: '操作工', department: '生产部', roles: '车间员工', role_workshop: null, role_workshop_name: null, is_supervisor: false, status: 'ACTIVE', status_display: '任职中', can_edit: true, created_at: '', updated_at: '' }
const workshop = { id: 'metal', name: '金工车间', status: 'ACTIVE' }
let wrapper: VueWrapper | undefined
async function open() { wrapper = mount(ConfigurationPage, { attachTo: document.body }); await flushPromises(); return wrapper }
async function click(view: VueWrapper, text: string) {
  const button = view.findAll('button').find(item => item.text() === text)
  expect(button, `按钮 ${text}`).toBeDefined()
  await button!.trigger('click'); await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  mocks.permission.mockReturnValue(true)
  mocks.list.mockResolvedValue({ data: [employee], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 } })
  mocks.options.mockResolvedValue({ workshops: [workshop], editable_workshops: [workshop] })
  mocks.detail.mockResolvedValue({ data: employee, etag: '"v1"' })
  mocks.update.mockResolvedValue({ data: employee, etag: '"v2"' })
  mocks.remove.mockResolvedValue(undefined)
  mocks.confirm.mockResolvedValue('confirm')
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.runOnlyPendingTimers(); vi.useRealTimers(); document.body.innerHTML = '' })

describe('手机车间员工配置', () => {
  it('显示身份和车间字段，单车间不切换，不提供新增员工', async () => {
    const view = await open()
    for (const text of ['员工甲', '金工车间', '操作工', '生产部', '车间员工', '任职中']) expect(view.text()).toContain(text)
    expect(view.text()).not.toContain('E001')
    expect(view.find('[aria-label="筛选车间"]').exists()).toBe(false)
    expect(view.text()).not.toContain('新增员工')
    expect(mocks.list).toHaveBeenCalledWith(expect.objectContaining({ position_state: 'ROLE_PENDING' }), expect.any(AbortSignal))
  })
  it('无查看权限不请求名单，只有查看权或行不可编辑均隐藏写入口', async () => {
    mocks.permission.mockReturnValue(false)
    let view = await open()
    expect(view.text()).toContain('无权查看')
    expect(mocks.list).not.toHaveBeenCalled()
    view.unmount(); wrapper = undefined
    mocks.permission.mockImplementation((code: string) => code === 'workshop_config.view_workshopemployee')
    view = await open()
    expect(view.findAll('button').some(item => item.text() === '编辑')).toBe(false)
    view.unmount(); wrapper = undefined
    mocks.permission.mockReturnValue(true)
    mocks.list.mockResolvedValue({ data: [{ ...employee, can_edit: false }], meta: { page: 1, total: 1, total_pages: 1 } })
    view = await open()
    expect(view.findAll('button').some(item => item.text() === '编辑')).toBe(false)
  })
  it('编辑只保存四项车间字段和原 ETag，身份只读', async () => {
    const view = await open(); await click(view, '编辑')
    const field = view.findAllComponents(Field).find(item => item.props('label') === '岗位')!
    await field.find('input').setValue('  组长  ')
    await view.get('[aria-label="是否主管"]').setValue('true')
    await click(view, '保存')
    expect(mocks.update).toHaveBeenCalledWith('worker-1', { workshop: 'metal', position: '组长', is_supervisor: true, status: 'ACTIVE' }, '"v1"')
    expect(mocks.success).toHaveBeenCalledOnce()
    expect(mocks.list).toHaveBeenCalledTimes(2)
  })
  it('角色待设置员工自动使用对应车间，编辑时不提供跨车间选择', async () => {
    const roleEmployee = {
      ...employee,
      workshop: null,
      workshop_name: '未安排',
      position: '',
      roles: '金工车间',
      role_workshop: 'metal',
      role_workshop_name: '金工车间',
    }
    mocks.list.mockResolvedValue({ data: [roleEmployee], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 } })
    mocks.detail.mockResolvedValue({ data: roleEmployee, etag: '"role-v1"' })
    const view = await open(); await click(view, '设置岗位')
    expect(view.text()).toContain('车间按角色自动对应')
    expect(view.find('[aria-label="编辑车间"]').exists()).toBe(false)
    const field = view.findAllComponents(Field).find(item => item.props('label') === '岗位')!
    await field.find('input').setValue('金工操作工'); await click(view, '保存')
    expect(mocks.update).toHaveBeenCalledWith('worker-1', { workshop: 'metal', position: '金工操作工', is_supervisor: false, status: 'ACTIVE' }, '"role-v1"')
  })
  it('旧版本失败保留输入，要求重新读取且不能自动重试', async () => {
    mocks.update.mockRejectedValue({ isAxiosError: true, response: { status: 412, data: { error: { message: '记录已变化' } } } })
    const view = await open(); await click(view, '编辑')
    const input = view.findAllComponents(Field).find(item => item.props('label') === '岗位')!.find('input')
    await input.setValue('组长'); await click(view, '保存')
    expect(input.element.value).toBe('组长')
    expect(view.text()).toContain('重新读取')
    expect(mocks.update).toHaveBeenCalledTimes(1)
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.list).toHaveBeenCalledTimes(1)
    mocks.detail.mockResolvedValue({ data: { ...employee, position: '新岗位' }, etag: '"v4"' })
    await click(view, '重新读取当前配置')
    expect(input.element.value).toBe('新岗位')
    mocks.update.mockResolvedValue({ data: employee, etag: '"v5"' })
    await click(view, '保存')
    expect(mocks.update).toHaveBeenLastCalledWith('worker-1', expect.objectContaining({ position: '新岗位' }), '"v4"')
  })
  it('只允许选有效修改车间，空岗位不提交，读取后失去修改权不能打开编辑', async () => {
    mocks.options.mockResolvedValue({ workshops: [workshop, { id: 'sewing', name: '车缝车间', status: 'ACTIVE' }], editable_workshops: [workshop, { id: 'inactive', name: '停用车间', status: 'INACTIVE' }] })
    const view = await open(); await click(view, '编辑')
    expect(view.get('[aria-label="编辑车间"]').findAll('option').map(item => item.attributes('value'))).toEqual(['', 'metal'])
    await view.findAllComponents(Field).find(item => item.props('label') === '岗位')!.find('input').setValue('  ')
    await click(view, '保存')
    expect(mocks.update).not.toHaveBeenCalled()
    expect(view.text()).toContain('请输入岗位')
    await click(view, '取消')
    mocks.detail.mockResolvedValue({ data: { ...employee, can_edit: false }, etag: '"v2"' })
    await click(view, '编辑')
    expect(view.text()).toContain('不在可修改范围')
    expect(mocks.update).not.toHaveBeenCalled()
  })
  it('结束和恢复任职使用详情最新状态与版本', async () => {
    const view = await open(); await click(view, '更多'); await click(view, '结束任职')
    expect(mocks.update).toHaveBeenCalledWith('worker-1', { status: 'LEFT' }, '"v1"')
    mocks.list.mockResolvedValue({ data: [{ ...employee, status: 'LEFT' }], meta: { page: 1, total: 1, total_pages: 1 } })
    mocks.detail.mockResolvedValue({ data: { ...employee, status: 'LEFT' }, etag: '"v3"' })
    await click(view, '刷新'); await click(view, '更多'); await click(view, '恢复任职')
    expect(mocks.update).toHaveBeenLastCalledWith('worker-1', { status: 'ACTIVE' }, '"v3"')
  })
  it('解除安排成功后重读范围，取消不删除且不提示成功', async () => {
    const view = await open()
    mocks.confirm.mockRejectedValueOnce('cancel')
    await click(view, '更多')
    await click(view, '解除安排')
    expect(mocks.remove).not.toHaveBeenCalled(); expect(mocks.success).not.toHaveBeenCalled()
    mocks.list.mockResolvedValue({ data: [], meta: { page: 1, total: 0, total_pages: 0 } })
    await click(view, '更多')
    await click(view, '解除安排')
    expect(mocks.remove).toHaveBeenCalledWith('worker-1', '"v1"')
    expect(view.text()).not.toContain('员工甲')
    expect(view.text()).toContain('暂无待设置岗位员工')
  })
  it('搜索重置分页，车间选择只传筛选不扩展名单', async () => {
    mocks.options.mockResolvedValue({ workshops: [workshop, { id: 'sewing', name: '车缝车间', status: 'ACTIVE' }], editable_workshops: [workshop] })
    mocks.list.mockResolvedValue({ data: [employee], meta: { page: 1, total: 21, total_pages: 2 } })
    const view = await open(); await click(view, '下一页')
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }), expect.any(AbortSignal))
    await view.get('[aria-label="搜索员工"] input').setValue('  甲  '); await click(view, '搜索')
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, q: '甲', position_state: 'ROLE_PENDING' }), expect.any(AbortSignal))
    await view.get('[aria-label="筛选车间"]').setValue('sewing'); await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, workshop: 'sewing', position_state: 'ROLE_PENDING' }), expect.any(AbortSignal))
  })
  it('默认打开待设置岗位，切换全部员工时去掉岗位筛选', async () => {
    const view = await open()
    await click(view, '全部员工')
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, position_state: 'ROLE_ALL' }), expect.any(AbortSignal))
    expect(view.text()).toContain('车间员工')
  })
  it('列表错误可重试，保存失败不关闭编辑器，页面离开后不消费旧结果', async () => {
    mocks.list.mockRejectedValueOnce(new Error('名单读取失败'))
    const view = await open(); expect(view.text()).toContain('名单读取失败')
    await click(view, '重试'); await click(view, '编辑')
    mocks.update.mockRejectedValueOnce(new Error('保存失败'))
    await click(view, '保存'); expect(view.text()).toContain('保存失败')
    expect(mocks.success).not.toHaveBeenCalled()
    let resolve!: (value: unknown) => void
    mocks.update.mockReturnValue(new Promise(done => { resolve = done }))
    await click(view, '保存')
    view.unmount(); wrapper = undefined
    resolve({ data: employee, etag: '"v3"' }); await flushPromises()
    expect(mocks.success).not.toHaveBeenCalled()
  })
})
