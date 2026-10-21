import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DepartmentMappingDialog from './DepartmentMappingDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { DepartmentMappingOrganization, DepartmentMappingPreviewResponse } from '@/types/employeeDirectory'

const api = vi.hoisted(() => ({ getDepartmentMappings: vi.fn(), saveDepartmentMapping: vi.fn() }))
vi.mock('@/api/employeeDirectory', async original => ({ ...await original<object>(), ...api }))
const dialog = { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' }
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
const organization: DepartmentMappingOrganization = { id: 'department-1', unit_code: 'DEPT_1', unit_name: '生产部', status: 'ACTIVE', archived: false, etag: '"organization-v1"' }
function preview(): DepartmentMappingPreviewResponse {
  return { etag: '"mapping-v1"', data: { corp_id: 'corp', preview_token: 'mapping-token', organizations: [organization, { ...organization, id: 'inactive', status: 'INACTIVE' }, { ...organization, id: 'archived', archived: true }], departments: [{ id: 1, parentid: 0, name: '生产部', candidates: [organization], mapping: { id: 'mapping-1', wecom_department_id: 1, organization_unit_id: 'department-1', organization_etag: '"organization-v1"', organization_active: true, organization_name: '生产部', updated_at: '2026-10-21T00:00:00Z' } }] } }
}
async function render(open = true) {
  const wrapper = mount(DepartmentMappingDialog, { props: { modelValue: open }, global: { plugins: [pinia], stubs: { AppWindowDialog: dialog } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label)! }
async function selectTarget(wrapper: ReturnType<typeof mount>, target = 'department-1') {
  await button(wrapper, '设置映射').trigger('click')
  await wrapper.get('[aria-label="映射目标部门"]').setValue(target)
  await wrapper.get('[aria-label="确认部门映射"]').setValue(true)
}
beforeEach(() => {
  vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getDepartmentMappings.mockResolvedValue(preview()); api.saveDepartmentMapping.mockResolvedValue(preview().data.departments[0]!.mapping)
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('企业微信部门映射弹窗', () => {
  it('进入本地页面时不读映射，打开才读取；同名提示不预选或自动确认', async () => {
    const wrapper = await render(false)
    expect(api.getDepartmentMappings).not.toHaveBeenCalled()
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(api.getDepartmentMappings).toHaveBeenCalledOnce()
    await button(wrapper, '设置映射').trigger('click')
    expect((wrapper.get('[aria-label="映射目标部门"]').element as HTMLSelectElement).value).toBe('')
    expect((wrapper.get('[aria-label="确认部门映射"]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.get('[aria-label="映射目标部门"]').findAll('option').map(option => option.attributes('value'))).toEqual(['', '__clear__', 'department-1'])
    expect(button(wrapper, '确认保存映射').attributes('disabled')).toBeDefined()
  })
  it('明确目标和确认后同时携带预览、目标部门ETag，保存后重读和清空确认', async () => {
    const wrapper = await render()
    await selectTarget(wrapper)
    await button(wrapper, '确认保存映射').trigger('click'); await flushPromises()
    expect(api.saveDepartmentMapping).toHaveBeenCalledExactlyOnceWith(1, { preview_token: 'mapping-token', organization_unit_id: 'department-1', organization_etag: '"organization-v1"', confirmed: true }, '"mapping-v1"')
    expect(api.getDepartmentMappings).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(wrapper.find('[aria-label="设置部门映射"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('员工现有部门与角色保持不变')
  })
  it('清除必须选择清除并另行确认，发送null且不带目标版本', async () => {
    const wrapper = await render()
    await selectTarget(wrapper)
    await wrapper.get('[aria-label="映射目标部门"]').setValue('__clear__')
    expect((wrapper.get('[aria-label="确认部门映射"]').element as HTMLInputElement).checked).toBe(false)
    expect(button(wrapper, '确认保存映射').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="确认部门映射"]').setValue(true)
    await button(wrapper, '确认保存映射').trigger('click'); await flushPromises()
    expect(api.saveDepartmentMapping).toHaveBeenCalledExactlyOnceWith(1, { preview_token: 'mapping-token', organization_unit_id: null, confirmed: true }, '"mapping-v1"')
    expect(wrapper.text()).toContain('映射已清除')
  })
  it.each([412, undefined])('保存失败%s使旧预览失效，重读前不能继续提交', async status => {
    api.saveDepartmentMapping.mockRejectedValueOnce({ isAxiosError: true, ...(status ? { response: { status, data: {} } } : {}) })
    const wrapper = await render()
    await selectTarget(wrapper); await button(wrapper, '确认保存映射').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('旧预览已失效')
    expect(wrapper.find('[aria-label="设置部门映射"]').exists()).toBe(false)
    expect(button(wrapper, '确认保存映射').attributes('disabled')).toBeDefined()
    await button(wrapper, '重新读取映射').trigger('click'); await flushPromises()
    expect(api.getDepartmentMappings).toHaveBeenCalledTimes(2)
    expect(button(wrapper, '确认保存映射').attributes('disabled')).toBeDefined()
  })
  it('已保存而刷新失败同时展示成功事实和读取错误，不重放写请求', async () => {
    api.getDepartmentMappings.mockResolvedValueOnce(preview()).mockRejectedValueOnce({ isAxiosError: true })
    const wrapper = await render()
    await selectTarget(wrapper); await button(wrapper, '确认保存映射').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('生产部的映射已保存')
    expect(wrapper.get('[role="alert"]').text()).toContain('映射已保存，重新读取预览失败')
    expect(api.saveDepartmentMapping).toHaveBeenCalledOnce()
  })
  it('关闭后晚到的旧读取不能覆盖重新打开的新预览', async () => {
    let finish!: (value: DepartmentMappingPreviewResponse) => void
    api.getDepartmentMappings.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    const old = preview(); old.data.departments[0]!.name = '旧读取部门'
    finish(old); await flushPromises()
    expect(wrapper.get('tbody').text()).not.toContain('旧读取部门')
    expect(wrapper.get('tbody').text()).toContain('生产部')
  })
  it('没有组织权限时不读取，也不能保存映射', async () => {
    useAuthStore().user!.is_superuser = false
    const wrapper = await render()
    expect(api.getDepartmentMappings).not.toHaveBeenCalled()
    expect(button(wrapper, '确认保存映射').attributes('disabled')).toBeDefined()
  })
})
