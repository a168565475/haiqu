import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EmployeeDirectoryDialog from './EmployeeDirectoryDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'
import type { EmployeeDirectoryMember, EmployeeDirectoryPreviewResponse } from '@/types/employeeDirectory'

const message = vi.hoisted(() => ({ success: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessage: message }))
const api = vi.hoisted(() => ({ getEmployeeDirectoryPreview: vi.fn(), refreshEmployeeDirectory: vi.fn(), syncEmployeeDirectory: vi.fn(), matchEmployeeDirectory: vi.fn(), getEmployees: vi.fn() }))
vi.mock('@/api/employeeDirectory', async original => ({ ...await original<object>(), ...api }))
vi.mock('@/api/access', async original => ({ ...await original<object>(), getEmployees: api.getEmployees }))
const dialog = { inheritAttrs: false, props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' }
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
function member(userid: string, action: EmployeeDirectoryMember['action'] = 'CREATE'): EmployeeDirectoryMember {
  return { userid, name: '来源员工', department: [1], main_department: 1, status: 1, status_label: '已激活', action, reason: `${action}分类原因`, employee: null, candidates: [] }
}
function preview(members = [member('new'), member('review', 'REVIEW'), member('existing', 'EXISTING'), member('skip', 'SKIP')], apply = false): EmployeeDirectoryPreviewResponse {
  return { data: { snapshot: { status: 'VALID', message: '有效', can_submit: true, can_refresh: true, fetched_at: '2026-10-21T00:00:00Z', expires_at: '2099-01-01T00:00:00Z' }, corp_id: 'corp', departments: [{ id: 1, parentid: 0, name: '生产部' }], members, preview_token: 'preview-token', apply_departments: apply }, etag: '"preview-v1"' }
}
function employee(id: string, overrides: Partial<AccessEmployee> = {}): AccessEmployee {
  return { id, employee_code: `EMP-${id}`, display_name: '同名员工', status: 'ACTIVE', username: `user-${id}`, account_active: true, account_protected: false, team_id: null, department: '', role_ids: [], etag: `"employee-${id}"`, ...overrides }
}
function grant(...permissions: string[]) {
  const auth = useAuthStore()
  auth.user = { ...auth.user!, username: 'ordinary-manager', is_superuser: false, effective_access: { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'v1', actions: Object.fromEntries(permissions.map(permission => [permission, { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE' }] }])) } }
}
async function render(open = true) {
  const wrapper = mount(EmployeeDirectoryDialog, { props: { modelValue: open }, global: { plugins: [pinia], stubs: { AppWindowDialog: dialog, ElTooltip: { inheritAttrs: false, template: '<slot />' } } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label)! }
function saveButton(wrapper: ReturnType<typeof mount>) { return wrapper.findAll('button').find(element => element.text().startsWith('保存所选员工'))! }
beforeEach(() => {
  vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getEmployeeDirectoryPreview.mockImplementation(async apply => preview(undefined, apply)); api.refreshEmployeeDirectory.mockResolvedValue(preview()); api.getEmployees.mockResolvedValue([employee('1'), employee('2')])
  api.syncEmployeeDirectory.mockResolvedValue([{ user_id: 'new', employee_id: '1', result: 'CREATED' }])
  api.matchEmployeeDirectory.mockResolvedValue({ user_id: 'review', employee_id: '1', result: 'MATCHED' })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('企业微信员工同步弹窗', () => {
  it('未打开不读来源，打开后默认不补部门、不选员工、不确认重名', async () => {
    const wrapper = await render(false)
    expect(api.getEmployeeDirectoryPreview).not.toHaveBeenCalled()
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledExactlyOnceWith(false)
    expect(wrapper.findAll('input[type="checkbox"]').every(input => !(input.element as HTMLInputElement).checked)).toBe(true)
    expect(wrapper.get('[aria-label="选择成员 review"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="选择成员 skip"]').attributes('disabled')).toBeDefined()
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('可新建'); expect(wrapper.text()).toContain('待人工核对')
    expect(wrapper.find('.directory-meta').exists()).toBe(false)
    expect(wrapper.findAll('th').map(cell => cell.text())).not.toContain('分类原因')
    expect(wrapper.text()).not.toContain('CREATE分类原因')
  })
  it('姓名后显示真实企微部门，保留多部门/主部门/未知ID，不用拟分配ERP部门替代', async () => {
    const row = member('source'); row.department = [1, 2, 99]; row.main_department = 2
    row.department_plan = { status: 'READY', reason: '计划', assignments: [{ department_id: 'erp-target', department_name: '拟分配ERP部门', is_primary: true }] }
    const data = preview([row]); data.data.departments.push({ id: 2, parentid: 0, name: '销售部' })
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(data)
    const wrapper = await render()
    expect(wrapper.findAll('th').slice(1, 4).map(cell => cell.text())).toEqual(['姓名', '企业微信部门', 'UserID'])
    expect(wrapper.get('[data-userid="source"]').findAll('td')[2]!.text()).toBe('生产部；销售部（主部门）；部门 #99')
    expect(wrapper.text()).not.toContain('拟分配ERP部门')
  })
  it.each([false, true])('部门列表为空或未返回%s时显示破折号，不猜测主部门', async missing => {
    const row = member('empty'); row.department = []; row.main_department = 999
    if (missing) delete (row as Partial<EmployeeDirectoryMember>).department
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview([row]))
    const wrapper = await render()
    expect(wrapper.get('[data-userid="empty"]').findAll('td')[2]!.text()).toBe('—')
  })
  it('全选覆盖当前筛选的全部页，REVIEW先确认、SKIP不可选，取消全选不提交', async () => {
    const members = Array.from({ length: 60 }, (_, index) => member(`bulk-${index}`, index === 58 ? 'REVIEW' : index === 59 ? 'SKIP' : index === 0 ? 'EXISTING' : 'CREATE'))
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview(members))
    const wrapper = await render()
    await button(wrapper, '全选可保存（58）').trigger('click')
    expect(saveButton(wrapper).text()).toBe('保存所选员工（58）')
    await button(wrapper, '下一页').trigger('click')
    expect((wrapper.get('[aria-label="选择成员 bulk-50"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[aria-label="选择成员 bulk-58"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="确认不同人员 bulk-58"]').setValue(true)
    await button(wrapper, '全选可保存（59）').trigger('click')
    expect(saveButton(wrapper).text()).toBe('保存所选员工（59）')
    expect(wrapper.get('[aria-label="选择成员 bulk-59"]').attributes('disabled')).toBeDefined()
    await button(wrapper, '取消全选').trigger('click'); expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
    expect(api.syncEmployeeDirectory).not.toHaveBeenCalled()
  })
  it('表头只切换当前页，保留其他页选择和混合选中状态', async () => {
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview(Array.from({ length: 51 }, (_, index) => member(`page-select-${index}`))))
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 page-select-0"]').setValue(true)
    expect((wrapper.get('[aria-label="选择当前页可保存员工"]').element as HTMLInputElement).indeterminate).toBe(true)
    await wrapper.get('[aria-label="选择当前页可保存员工"]').setValue(true)
    await button(wrapper, '下一页').trigger('click'); await wrapper.get('[aria-label="选择当前页可保存员工"]').setValue(true)
    expect(saveButton(wrapper).text()).toBe('保存所选员工（51）')
    await button(wrapper, '上一页').trigger('click'); await wrapper.get('[aria-label="选择当前页可保存员工"]').setValue(false)
    expect(saveButton(wrapper).text()).toBe('保存所选员工（1）')
  })
  it('全选超过500不截取，保留原选择，筛选后可以分批选', async () => {
    const members = Array.from({ length: 501 }, (_, index) => ({ ...member(`limit-${index}`), name: index < 50 ? '本批' : '其他批' }))
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview(members))
    const wrapper = await render(); await button(wrapper, '全选可保存（501）').trigger('click')
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）'); expect(wrapper.get('[role="alert"]').text()).toContain('超过 500 人')
    await wrapper.get('[aria-label="搜索企业微信成员"]').setValue('本批'); await button(wrapper, '全选可保存（50）').trigger('click')
    expect(saveButton(wrapper).text()).toBe('保存所选员工（50）')
    await wrapper.get('[aria-label="搜索企业微信成员"]').setValue(''); await button(wrapper, '全选可保存（501）').trigger('click')
    expect(saveButton(wrapper).text()).toBe('保存所选员工（50）')
  })
  it('普通新建和已存在成员明确选择后带预览ETag提交，成功重读并清空旧选择', async () => {
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 existing"]').setValue(true)
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledExactlyOnceWith({ preview_token: 'preview-token', user_ids: ['new', 'existing'], confirmed_new_user_ids: [], apply_departments: false }, '"preview-v1"')
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).toContain('已新建')
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）'); expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(message.success).toHaveBeenCalledExactlyOnceWith('员工保存完成：新增 1 人，已存在 0 人，已关联 0 人。')
  })
  it('保存中禁用防双击，成功汇总结果并通知主列表刷新，读回期间不显示成功alert', async () => {
    let finish!: (value: unknown) => void, restore!: (value: EmployeeDirectoryPreviewResponse) => void
    api.syncEmployeeDirectory.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview()).mockImplementationOnce(() => new Promise(resolve => { restore = resolve }))
    const wrapper = await render(); await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await wrapper.get('[aria-label="选择成员 existing"]').setValue(true)
    const submit = saveButton(wrapper); await submit.trigger('click'); await submit.trigger('click')
    expect(submit.text()).toBe('保存中…'); expect(submit.attributes('disabled')).toBeDefined(); expect(api.syncEmployeeDirectory).toHaveBeenCalledOnce()
    finish([{ user_id: 'new', employee_id: '1', result: 'CREATED' }, { user_id: 'existing', employee_id: '2', result: 'EXISTING' }]); await flushPromises()
    expect(wrapper.emitted('saved')).toHaveLength(1); expect(message.success).toHaveBeenCalledExactlyOnceWith('员工保存完成：新增 1 人，已存在 1 人，已关联 0 人。')
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).toContain('已存在，未重复新建')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    restore(preview()); await flushPromises()
  })
  it('重名必须逐人确认新建，取消确认也撤销选择', async () => {
    const wrapper = await render()
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 review"]').setValue(true)
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(false)
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 review"]').setValue(true)
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledWith(expect.objectContaining({ user_ids: ['review'], confirmed_new_user_ids: ['review'] }), '"preview-v1"')
    await button(wrapper, '员工名单').trigger('click')
    expect((wrapper.get('[aria-label="确认不同人员 review"]').element as HTMLInputElement).checked).toBe(false)
  })
  it('关联候选排除离职停用与保护账号，同名显示编码，选择目标不默认确认', async () => {
    api.getEmployees.mockResolvedValue([employee('1'), employee('2', { username: null, account_active: null }), employee('left', { status: 'LEFT' }), employee('disabled', { account_active: false }), employee('protected', { account_protected: true })])
    const wrapper = await render()
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 review"]').setValue(true)
    await wrapper.get('[data-userid="review"] button').trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="确认不同人员 review"]').element as HTMLInputElement).checked).toBe(false)
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
    const options = wrapper.get('[aria-label="选择关联员工"]').findAll('option')
    expect(options.map(option => option.text())).toEqual(['请选择员工', '同名员工 · EMP-1 · 未分配部门', '同名员工 · EMP-2 · 未分配部门'])
    await wrapper.get('[aria-label="选择关联员工"]').setValue('1')
    expect(button(wrapper, '确认关联此员工').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="确认是同一人"]').setValue(true)
    await wrapper.get('[aria-label="选择关联员工"]').setValue('2')
    expect((wrapper.get('[aria-label="确认是同一人"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[aria-label="确认是同一人"]').setValue(true)
    await button(wrapper, '确认关联此员工').trigger('click'); await flushPromises()
    expect(api.matchEmployeeDirectory).toHaveBeenCalledExactlyOnceWith({ preview_token: 'preview-token', apply_departments: false, user_id: 'review', employee_id: '2', employee_etag: '"employee-2"', confirmed: true }, '"preview-v1"')
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[aria-label="人工关联员工"]').exists()).toBe(false)
  })
  it.each([400, 409, 412, undefined])('提交失败%s后废弃预览，不允许使用旧确认重试', async status => {
    api.syncEmployeeDirectory.mockRejectedValueOnce({ isAxiosError: true, ...(status ? { response: { status, data: {} } } : {}) })
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('旧预览已失效')
    expect(message.success).not.toHaveBeenCalled()
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeDefined()
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(2)
    await button(wrapper, '重新读取预览').trigger('click'); await flushPromises()
    expect(api.refreshEmployeeDirectory).toHaveBeenCalledOnce()
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
  })
  it('保存成功但后续预览读取失败时保留逐项结果并说明已完成', async () => {
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview()).mockRejectedValueOnce({ isAxiosError: true })
    api.syncEmployeeDirectory.mockResolvedValueOnce([{ user_id: 'new', employee_id: '1', result: 'CREATED', department_status: 'PENDING', department_reason: '来源部门尚未映射' }])
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('本次保存已完成。 名单恢复失败')
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).toContain('来源部门尚未映射')
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
  })
  it('切换补部门只用GET重算计划，不调用企微刷新', async () => {
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true)
    await wrapper.get('.directory-toolbar input[type="checkbox"]').setValue(true); await flushPromises()
    expect(api.getEmployeeDirectoryPreview).toHaveBeenLastCalledWith(true)
    expect(api.refreshEmployeeDirectory).not.toHaveBeenCalled()
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledWith(expect.objectContaining({ apply_departments: true }), '"preview-v1"')
  })
  it('只有账号权限不能开启补部门，撤权后旧响应不恢复预览', async () => {
    grant('access_control.manage_accounts')
    const wrapper = await render()
    expect(wrapper.find('.directory-toolbar input[type="checkbox"]').exists()).toBe(false)
    let finish!: (value: EmployeeDirectoryPreviewResponse) => void
    api.refreshEmployeeDirectory.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await button(wrapper, '重新读取预览').trigger('click')
    grant(); await flushPromises(); finish(preview()); await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([false])
    expect(wrapper.find('[data-userid="new"]').exists()).toBe(false)
  })
  it('来源读取失败没有可提交预览，不用本地员工伪装来源成功', async () => {
    api.getEmployeeDirectoryPreview.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { error: { code: 'CONFLICT', message: '企业微信尚未配置。' } } } })
    const wrapper = await render()
    expect(wrapper.get('[role="alert"]').text()).toContain('企业微信尚未配置')
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined(); expect(api.getEmployees).not.toHaveBeenCalled()
  })
  it('跨页选择仍最多500人，剩余行不可再选', async () => {
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview(Array.from({ length: 501 }, (_, index) => member(`member-${index}`))))
    const wrapper = await render()
    for (let page = 0; page < 10; page++) {
      await Promise.all(wrapper.findAll('tbody input[type="checkbox"]').map(checkbox => checkbox.setValue(true)))
      await button(wrapper, '下一页').trigger('click')
    }
    expect(saveButton(wrapper).text()).toBe('保存所选员工（500）')
    expect(wrapper.get('[aria-label="选择成员 member-500"]').attributes('disabled')).toBeDefined()
    await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory.mock.calls[0]![0].user_ids).toHaveLength(500)
  }, 20000)
  it('固定50人分页，筛选后回到第一页', async () => {
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview(Array.from({ length: 51 }, (_, index) => member(`page-${index}`))))
    const wrapper = await render()
    expect(wrapper.findAll('[data-userid]')).toHaveLength(50); expect(wrapper.text()).toContain('每页50人')
    await button(wrapper, '下一页').trigger('click'); expect(wrapper.findAll('[data-userid]')).toHaveLength(1)
    await wrapper.get('[aria-label="搜索企业微信成员"]').setValue('page-0')
    expect(wrapper.text()).toContain('1 / 1'); expect(wrapper.find('[data-userid="page-0"]').exists()).toBe(true)
  })
  it('刷新期间及失败保留旧名单，成功才替换并清空选择', async () => {
    let reject!: (error: unknown) => void
    api.refreshEmployeeDirectory.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const wrapper = await render(); await wrapper.get('[aria-label="选择成员 new"]').setValue(true)
    await button(wrapper, '重新读取预览').trigger('click')
    expect(wrapper.find('[data-userid="new"]').exists()).toBe(true); expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    reject({ isAxiosError: true, response: { status: 502 } }); await flushPromises()
    expect(wrapper.find('[data-userid="new"]').exists()).toBe(true); expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    api.refreshEmployeeDirectory.mockResolvedValueOnce(preview([member('replacement')]))
    await button(wrapper, '重新读取预览').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-userid="new"]').exists()).toBe(false); expect(wrapper.find('[data-userid="replacement"]').exists()).toBe(true)
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
  })
  it.each(['EXPIRED', 'MISSING', 'CONFIG_CHANGED', 'CONFIG_UNAVAILABLE'] as const)('%s不能提交或人工确认', async status => {
    const data = preview(); data.data.preview_token = ''; data.data.snapshot.status = status; data.data.snapshot.can_submit = false; data.data.snapshot.can_refresh = false
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(data)
    const wrapper = await render()
    expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="确认不同人员 review"]').attributes('disabled')).toBeDefined()
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    if (status === 'CONFIG_UNAVAILABLE') expect(button(wrapper, '重新读取预览').attributes('disabled')).toBeDefined()
  })
  it('可信持久副本允许保存但不能刷新，不用CONFIG_UNAVAILABLE状态覆盖独立能力', async () => {
    const data = preview(); data.data.snapshot.status = 'CONFIG_UNAVAILABLE'; data.data.snapshot.can_submit = true; data.data.snapshot.can_refresh = false
    api.getEmployeeDirectoryPreview.mockResolvedValue(data)
    const wrapper = await render()
    expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeUndefined()
    expect(button(wrapper, '重新读取预览').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledWith(expect.objectContaining({ user_ids: ['new'], apply_departments: false }), '"preview-v1"')
    expect(api.refreshEmployeeDirectory).not.toHaveBeenCalled()
    expect(message.success).toHaveBeenCalledOnce()
  })
  it('不可刷新企微的副本保存失败后，可用GET重新核对并重新选择，不自动重放保存', async () => {
    const data = preview(); data.data.snapshot.status = 'CONFIG_UNAVAILABLE'; data.data.snapshot.can_refresh = false
    api.getEmployeeDirectoryPreview.mockResolvedValue(data); api.syncEmployeeDirectory.mockRejectedValueOnce({ isAxiosError: true, response: { status: 412 } })
    const wrapper = await render(); await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeDefined()
    await button(wrapper, '重新核对名单').trigger('click'); await flushPromises()
    expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeUndefined()
    expect(saveButton(wrapper).text()).toBe('保存所选员工（0）')
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(3)
    expect(api.refreshEmployeeDirectory).not.toHaveBeenCalled(); expect(api.syncEmployeeDirectory).toHaveBeenCalledOnce(); expect(message.success).not.toHaveBeenCalled()
  })
  it.each(['capability', 'token', 'etag', 'expiry', 'mode'] as const)('可信副本缺少有效%s也不能保存或全选', async missing => {
    const data = preview(); data.data.snapshot.status = 'CONFIG_UNAVAILABLE'; data.data.snapshot.can_refresh = false
    if (missing === 'capability') { data.data.snapshot.can_submit = false; data.data.snapshot.message = '副本已过期，不能保存员工' }
    if (missing === 'token') data.data.preview_token = ''
    if (missing === 'etag') data.etag = ''
    if (missing === 'expiry') data.data.snapshot.expires_at = '2000-01-01T00:00:00Z'
    if (missing === 'mode') data.data.apply_departments = true
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(data)
    const wrapper = await render()
    expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '全选可保存（0）').attributes('disabled')).toBeDefined()
    if (missing === 'capability') expect(wrapper.get('[role="alert"]').text()).toContain('副本已过期，不能保存员工')
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    expect(api.syncEmployeeDirectory).not.toHaveBeenCalled()
  })
  it('VALID但缺令牌也不能提交', async () => {
    const data = preview(); data.data.preview_token = ''; api.getEmployeeDirectoryPreview.mockResolvedValueOnce(data)
    const wrapper = await render(); expect(wrapper.get('[aria-label="选择成员 new"]').attributes('disabled')).toBeDefined()
  })
  it.each([401, 403])('刷新%s清空名单与最近结果', async status => {
    const wrapper = await render(); await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    api.refreshEmployeeDirectory.mockRejectedValueOnce({ isAxiosError: true, response: { status } })
    await button(wrapper, '重新读取预览').trigger('click'); await flushPromises()
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).not.toContain('已新建')
    await button(wrapper, '员工名单').trigger('click'); expect(wrapper.find('[data-userid]').exists()).toBe(false)
  })
  it('后续提交未知不覆盖最近明确成功结果，不重复发送', async () => {
    const wrapper = await render(); await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    await button(wrapper, '员工名单').trigger('click')
    api.syncEmployeeDirectory.mockRejectedValueOnce({ isAxiosError: true })
    await wrapper.get('[aria-label="选择成员 existing"]').setValue(true); await saveButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledTimes(2)
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).toContain('已新建')
    expect(wrapper.get('[role="alert"]').text()).toContain('未确认完成')
  })

})
