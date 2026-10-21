import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EmployeeDirectoryDialog from './EmployeeDirectoryDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'
import type { EmployeeDirectoryMember, EmployeeDirectoryPreviewResponse } from '@/types/employeeDirectory'

const api = vi.hoisted(() => ({ getEmployeeDirectoryPreview: vi.fn(), syncEmployeeDirectory: vi.fn(), matchEmployeeDirectory: vi.fn(), getEmployees: vi.fn() }))
vi.mock('@/api/employeeDirectory', async original => ({ ...await original<object>(), ...api }))
vi.mock('@/api/access', async original => ({ ...await original<object>(), getEmployees: api.getEmployees }))
const dialog = { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' }
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
function member(userid: string, action: EmployeeDirectoryMember['action'] = 'CREATE'): EmployeeDirectoryMember {
  return { userid, name: '来源员工', department: [1], main_department: 1, status: 1, status_label: '已激活', action, reason: `${action}分类原因`, employee: null, candidates: [] }
}
function preview(members = [member('new'), member('review', 'REVIEW'), member('existing', 'EXISTING'), member('skip', 'SKIP')], apply = false): EmployeeDirectoryPreviewResponse {
  return { data: { corp_id: 'corp', departments: [{ id: 1, parentid: 0, name: '生产部' }], members, preview_token: 'preview-token', apply_departments: apply }, etag: '"preview-v1"' }
}
function employee(id: string, overrides: Partial<AccessEmployee> = {}): AccessEmployee {
  return { id, employee_code: `EMP-${id}`, display_name: '同名员工', status: 'ACTIVE', username: `user-${id}`, account_active: true, account_protected: false, team_id: null, department: '', role_ids: [], etag: `"employee-${id}"`, ...overrides }
}
function grant(...permissions: string[]) {
  const auth = useAuthStore()
  auth.user = { ...auth.user!, username: 'ordinary-manager', is_superuser: false, effective_access: { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'v1', actions: Object.fromEntries(permissions.map(permission => [permission, { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE' }] }])) } }
}
async function render(open = true) {
  const wrapper = mount(EmployeeDirectoryDialog, { props: { modelValue: open }, global: { plugins: [pinia], stubs: { AppWindowDialog: dialog } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label)! }
function syncButton(wrapper: ReturnType<typeof mount>) { return wrapper.findAll('button').find(element => element.text().startsWith('同步所选'))! }
beforeEach(() => {
  vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getEmployeeDirectoryPreview.mockResolvedValue(preview()); api.getEmployees.mockResolvedValue([employee('1'), employee('2')])
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
    expect(syncButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('CREATE分类原因'); expect(wrapper.text()).toContain('REVIEW分类原因')
  })
  it('普通新建和已存在成员明确选择后带预览ETag提交，成功重读并清空旧选择', async () => {
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 existing"]').setValue(true)
    await syncButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledExactlyOnceWith({ preview_token: 'preview-token', user_ids: ['new', 'existing'], confirmed_new_user_ids: [], apply_departments: false }, '"preview-v1"')
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).toContain('已新建')
    expect(syncButton(wrapper).text()).toBe('同步所选 0 人'); expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it('重名必须逐人确认新建，取消确认也撤销选择', async () => {
    const wrapper = await render()
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 review"]').setValue(true)
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(false)
    expect(syncButton(wrapper).text()).toBe('同步所选 0 人')
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 review"]').setValue(true)
    await syncButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledWith(expect.objectContaining({ user_ids: ['review'], confirmed_new_user_ids: ['review'] }), '"preview-v1"')
    expect((wrapper.get('[aria-label="确认不同人员 review"]').element as HTMLInputElement).checked).toBe(false)
  })
  it('关联候选排除离职停用与保护账号，同名显示编码，选择目标不默认确认', async () => {
    api.getEmployees.mockResolvedValue([employee('1'), employee('2', { username: null, account_active: null }), employee('left', { status: 'LEFT' }), employee('disabled', { account_active: false }), employee('protected', { account_protected: true })])
    const wrapper = await render()
    await wrapper.get('[aria-label="确认不同人员 review"]').setValue(true)
    await wrapper.get('[aria-label="选择成员 review"]').setValue(true)
    await wrapper.get('[data-userid="review"] button').trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="确认不同人员 review"]').element as HTMLInputElement).checked).toBe(false)
    expect(syncButton(wrapper).text()).toBe('同步所选 0 人')
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
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await syncButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('旧预览已失效')
    expect(syncButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('[aria-label="选择成员 new"]').exists()).toBe(false)
    await button(wrapper, '重新读取预览').trigger('click'); await flushPromises()
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(2)
    expect(syncButton(wrapper).text()).toBe('同步所选 0 人')
  })
  it('保存成功但后续预览读取失败时保留逐项结果并说明已完成', async () => {
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview()).mockRejectedValueOnce({ isAxiosError: true })
    api.syncEmployeeDirectory.mockResolvedValueOnce([{ user_id: 'new', employee_id: '1', result: 'CREATED', department_status: 'PENDING', department_reason: '来源部门尚未映射' }])
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await syncButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('本次提交已完成，重新读取预览失败')
    expect(wrapper.get('[aria-label="本次同步结果"]').text()).toContain('来源部门尚未映射')
    expect(syncButton(wrapper).attributes('disabled')).toBeDefined()
  })
  it('切换补部门废弃预览，重新读取后请求模式与签名一致', async () => {
    const wrapper = await render()
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true)
    const departmentMode = wrapper.get('.directory-toolbar input[type="checkbox"]')
    await departmentMode.setValue(true)
    expect(wrapper.find('[aria-label="选择成员 new"]').exists()).toBe(false)
    expect(api.getEmployeeDirectoryPreview).toHaveBeenCalledTimes(1)
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview([member('new')], true))
    await button(wrapper, '重新读取预览').trigger('click'); await flushPromises()
    expect(api.getEmployeeDirectoryPreview).toHaveBeenLastCalledWith(true)
    await wrapper.get('[aria-label="选择成员 new"]').setValue(true); await syncButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory).toHaveBeenCalledWith(expect.objectContaining({ apply_departments: true }), '"preview-v1"')
  })
  it('只有账号权限不能开启补部门，撤权后旧响应不恢复预览', async () => {
    grant('access_control.manage_accounts')
    const wrapper = await render()
    expect(wrapper.find('.directory-toolbar input[type="checkbox"]').exists()).toBe(false)
    let finish!: (value: EmployeeDirectoryPreviewResponse) => void
    api.getEmployeeDirectoryPreview.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await button(wrapper, '重新读取预览').trigger('click')
    grant(); await flushPromises(); finish(preview()); await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([false])
    expect(wrapper.find('[data-userid="new"]').exists()).toBe(false)
  })
  it('来源读取失败没有可提交预览，不用本地员工伪装来源成功', async () => {
    api.getEmployeeDirectoryPreview.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { error: { code: 'CONFLICT', message: '企业微信尚未配置。' } } } })
    const wrapper = await render()
    expect(wrapper.get('[role="alert"]').text()).toContain('企业微信尚未配置')
    expect(syncButton(wrapper).attributes('disabled')).toBeDefined(); expect(api.getEmployees).not.toHaveBeenCalled()
  })
  it('跨页选择仍最多500人，剩余行不可再选', async () => {
    api.getEmployeeDirectoryPreview.mockResolvedValueOnce(preview(Array.from({ length: 501 }, (_, index) => member(`member-${index}`))))
    const wrapper = await render()
    for (let page = 0; page < 25; page++) {
      for (const checkbox of wrapper.findAll('tbody input[type="checkbox"]')) await checkbox.setValue(true)
      await button(wrapper, '下一页').trigger('click')
    }
    expect(syncButton(wrapper).text()).toBe('同步所选 500 人')
    expect(wrapper.get('[aria-label="选择成员 member-500"]').attributes('disabled')).toBeDefined()
    await syncButton(wrapper).trigger('click'); await flushPromises()
    expect(api.syncEmployeeDirectory.mock.calls[0]![0].user_ids).toHaveLength(500)
  }, 20000)
})
