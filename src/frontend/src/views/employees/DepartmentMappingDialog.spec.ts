import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DepartmentMappingDialog from './DepartmentMappingDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { DepartmentMappingOrganization, DepartmentMappingPreviewResponse } from '@/types/employeeDirectory'

const message = vi.hoisted(() => ({ success: vi.fn(), info: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessage: message }))
const api = vi.hoisted(() => ({ getDepartmentMappings: vi.fn(), refreshDepartmentMappings: vi.fn(), saveDepartmentMapping: vi.fn() }))
vi.mock('@/api/employeeDirectory', async original => ({ ...await original<object>(), ...api }))
const dialog = { inheritAttrs: false, props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' }
const select = { props: ['modelValue', 'disabled'], emits: ['change'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'change\', $event.target.value)"><option value="">请选择</option><slot /></select>' }
const option = { props: ['value', 'label', 'disabled'], template: '<option :value="value" :disabled="disabled">{{ label }}</option>' }
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
const organization: DepartmentMappingOrganization = { id: 'department-1', unit_code: 'DEPT_1', unit_name: '生产部', status: 'ACTIVE', archived: false, etag: '"organization-v1"' }
function preview(): DepartmentMappingPreviewResponse {
  return { etag: '"mapping-v1"', data: { can_save_mapping: true, snapshot: { status: 'VALID', message: '有效', can_submit: true, fetched_at: '2026-10-21T00:00:00Z', expires_at: '2099-01-01T00:00:00Z' }, corp_id: 'corp', preview_token: 'mapping-token', organizations: [organization, { ...organization, id: 'department-2', unit_code: 'DEPT_2' }, { ...organization, id: 'inactive', status: 'INACTIVE' }, { ...organization, id: 'archived', archived: true }], departments: [{ id: 1, parentid: 0, name: '生产部', candidates: [organization], mapping: { id: 'mapping-1', wecom_department_id: 1, organization_unit_id: 'department-1', organization_etag: '"organization-v1"', organization_active: true, organization_name: '生产部', updated_at: '2026-10-21T00:00:00Z' } }] } }
}
async function render(open = true) {
  const wrapper = mount(DepartmentMappingDialog, { props: { modelValue: open }, global: { plugins: [pinia], stubs: { AppWindowDialog: dialog, ElSelect: select, ElOption: option, ElTooltip: { inheritAttrs: false, template: '<slot />' } } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label)! }
function target(wrapper: ReturnType<typeof mount>) { return wrapper.get('[aria-label="映射目标部门 1"]') }
beforeEach(() => {
  vi.resetAllMocks(); message.info.mockImplementation(() => ({ close: vi.fn() })); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getDepartmentMappings.mockImplementation(async () => preview()); api.refreshDepartmentMappings.mockResolvedValue(preview())
  api.saveDepartmentMapping.mockResolvedValue(preview().data.departments[0]!.mapping)
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('企业微信部门映射弹窗', () => {
  it('读取时只显示一条常驻浮动提示，成功结束关闭且没有行内加载文字', async () => {
    let finish!: (value: DepartmentMappingPreviewResponse) => void
    api.getDepartmentMappings.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    expect(message.info).toHaveBeenCalledExactlyOnceWith({ message: '正在读取部门，请稍候…', duration: 0 })
    const handle = message.info.mock.results[0]!.value
    expect(handle.close).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('正在读取部门，请稍候')
    finish(preview()); await flushPromises()
    expect(handle.close).toHaveBeenCalledOnce()
    expect(message.info).toHaveBeenCalledOnce()
  })
  it('读取失败关闭自己的浮动提示，保留真实错误', async () => {
    api.getDepartmentMappings.mockRejectedValueOnce({ isAxiosError: true, response: { status: 503 } })
    const wrapper = await render()
    expect(message.info.mock.results[0]!.value.close).toHaveBeenCalledOnce()
    expect(wrapper.get('[role="alert"]').text()).toContain('服务尚未就绪')
  })
  it.each(['close', 'permission', 'unmount'] as const)('%s时清理自身加载提示，晚到响应不重复关闭', async reason => {
    let finish!: (value: DepartmentMappingPreviewResponse) => void
    api.getDepartmentMappings.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render(), handle = message.info.mock.results[0]!.value
    if (reason === 'close') await button(wrapper, '关闭').trigger('click')
    if (reason === 'permission') { useAuthStore().user!.is_superuser = false; await flushPromises() }
    if (reason === 'unmount') { wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1) }
    expect(handle.close).toHaveBeenCalledOnce()
    finish(preview()); await flushPromises()
    expect(handle.close).toHaveBeenCalledOnce()
    expect(message.info).toHaveBeenCalledOnce()
  })
  it('关闭重开创建新提示，旧响应不会关闭或替换新请求提示', async () => {
    let first!: (value: DepartmentMappingPreviewResponse) => void, second!: (value: DepartmentMappingPreviewResponse) => void
    api.getDepartmentMappings.mockImplementationOnce(() => new Promise(resolve => { first = resolve })).mockImplementationOnce(() => new Promise(resolve => { second = resolve }))
    const wrapper = await render(), oldHandle = message.info.mock.results[0]!.value
    await wrapper.setProps({ modelValue: false }); expect(oldHandle.close).toHaveBeenCalledOnce()
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    const newHandle = message.info.mock.results[1]!.value
    expect(message.info).toHaveBeenCalledTimes(2)
    first(preview()); await flushPromises()
    expect(newHandle.close).not.toHaveBeenCalled()
    expect(message.info).toHaveBeenCalledTimes(2)
    second(preview()); await flushPromises(); expect(newHandle.close).toHaveBeenCalledOnce()
  })
  it('打开只恢复快照，按持久绑定回显，只有显式刷新才POST', async () => {
    const wrapper = await render(false)
    expect(api.getDepartmentMappings).not.toHaveBeenCalled()
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(api.getDepartmentMappings).toHaveBeenCalledOnce(); expect(api.refreshDepartmentMappings).not.toHaveBeenCalled()
    expect((target(wrapper).element as HTMLSelectElement).value).toBe('department-1')
    expect(api.saveDepartmentMapping).not.toHaveBeenCalled()
    expect(target(wrapper).findAll('option').map(item => item.attributes('value'))).toEqual(['', '__clear__', 'department-1', 'department-2'])
    expect(wrapper.text()).not.toContain('确认保存映射')
    await button(wrapper, '重新读取映射').trigger('click'); await flushPromises()
    expect(api.refreshDepartmentMappings).toHaveBeenCalledOnce()
  })
  it('选中新目标即带完整预览和目标ETag保存，随后只读恢复', async () => {
    const wrapper = await render()
    await target(wrapper).setValue('department-2'); await flushPromises()
    expect(api.saveDepartmentMapping).toHaveBeenCalledExactlyOnceWith(1, { preview_token: 'mapping-token', organization_unit_id: 'department-2', organization_etag: '"organization-v1"', confirmed: true }, '"mapping-v1"')
    expect(api.getDepartmentMappings).toHaveBeenCalledTimes(2); expect(api.refreshDepartmentMappings).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(message.success).toHaveBeenCalledExactlyOnceWith('生产部的映射已保存。')
    expect(wrapper.find('.mapping-notice').exists()).toBe(false)
  })
  it('共享预览串行保存，保存前保留旧编码并禁止其他行写入', async () => {
    const data = preview(); data.data.departments.push({ ...data.data.departments[0]!, id: 2, name: '第二部门' })
    api.getDepartmentMappings.mockResolvedValueOnce(data)
    let finish!: (value: unknown) => void
    api.saveDepartmentMapping.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render(); await target(wrapper).setValue('department-2')
    expect(target(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="映射目标部门 2"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-department="1"]').text()).toContain('DEPT_1')
    expect(wrapper.get('[data-department="1"]').text()).toContain('保存中')
    finish(preview().data.departments[0]!.mapping); await flushPromises()
    expect(api.saveDepartmentMapping).toHaveBeenCalledOnce()
  })
  it('明确选择清除发送null，不带目标版本', async () => {
    const wrapper = await render(); await target(wrapper).setValue('__clear__'); await flushPromises()
    expect(api.saveDepartmentMapping).toHaveBeenCalledExactlyOnceWith(1, { preview_token: 'mapping-token', organization_unit_id: null, confirmed: true }, '"mapping-v1"')
    expect(message.success).toHaveBeenCalledExactlyOnceWith('生产部的映射已清除。')
  })
  it.each([412, undefined])('保存失败%s只读读回，不重放写入或假成功', async status => {
    api.saveDepartmentMapping.mockRejectedValueOnce({ isAxiosError: true, ...(status ? { response: { status, data: {} } } : {}) })
    const wrapper = await render(); await target(wrapper).setValue('department-2'); await flushPromises()
    expect(api.getDepartmentMappings).toHaveBeenCalledTimes(2); expect(api.saveDepartmentMapping).toHaveBeenCalledOnce()
    expect(wrapper.get('[role="alert"]').text()).toContain('只读核实')
    expect(wrapper.text()).toContain('已读回当前绑定：生产部'); expect(wrapper.emitted('saved')).toBeUndefined()
    expect(message.success).not.toHaveBeenCalled()
  })
  it('保存成功读回期间只弹统一成功提示，不把成功信息作为错误展示', async () => {
    let restore!: (value: DepartmentMappingPreviewResponse) => void
    api.getDepartmentMappings.mockResolvedValueOnce(preview()).mockImplementationOnce(() => new Promise(resolve => { restore = resolve }))
    const wrapper = await render(); await target(wrapper).setValue('department-2'); await flushPromises()
    expect(message.success).toHaveBeenCalledExactlyOnceWith('生产部的映射已保存。')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('.mapping-notice').exists()).toBe(false)
    restore(preview()); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
  it('保存成功弹统一提示，读回失败明确区分且保持禁用', async () => {
    api.getDepartmentMappings.mockResolvedValueOnce(preview()).mockRejectedValueOnce({ isAxiosError: true, response: { status: 503 } })
    const wrapper = await render(); await target(wrapper).setValue('department-2'); await flushPromises()
    expect(message.success).toHaveBeenCalledExactlyOnceWith('生产部的映射已保存。')
    expect(wrapper.get('[role="alert"]').text()).toContain('映射已保存。 只读恢复失败')
    expect(target(wrapper).attributes('disabled')).toBeDefined()
    expect(api.saveDepartmentMapping).toHaveBeenCalledOnce()
  })
  it('未知保存且无法读回时保留旧表并禁止再写', async () => {
    api.saveDepartmentMapping.mockRejectedValueOnce({ isAxiosError: true })
    api.getDepartmentMappings.mockResolvedValueOnce(preview()).mockRejectedValueOnce({ isAxiosError: true })
    const wrapper = await render(); await target(wrapper).setValue('department-2'); await flushPromises()
    expect(wrapper.get('tbody').text()).toContain('生产部'); expect(target(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('[role="alert"]').text()).toContain('只读恢复失败')
  })
  it('刷新加载及失败保留旧表，禁止提交，成功后恢复', async () => {
    let reject!: (reason: unknown) => void
    api.refreshDepartmentMappings.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const wrapper = await render(); await button(wrapper, '重新读取映射').trigger('click')
    expect(wrapper.get('tbody').text()).toContain('生产部'); expect(target(wrapper).attributes('disabled')).toBeDefined()
    reject({ isAxiosError: true, response: { status: 502 } }); await flushPromises()
    expect(target(wrapper).attributes('disabled')).toBeDefined(); expect(wrapper.get('[role="alert"]').text()).toContain('重新读取失败')
    await button(wrapper, '重新读取映射').trigger('click'); await flushPromises(); expect(target(wrapper).attributes('disabled')).toBeUndefined()
  })
  it.each(['MISSING', 'CONFIG_UNAVAILABLE'] as const)('%s仍显示本地ERP部门，无虚假来源', async status => {
    const data = preview(); data.data.departments = []; data.data.preview_token = ''; data.data.can_save_mapping = false; data.data.snapshot = { ...data.data.snapshot, status, can_submit: false, fetched_at: null }
    api.getDepartmentMappings.mockResolvedValueOnce(data)
    const wrapper = await render()
    expect(wrapper.get('[aria-label="本地ERP部门"]').text()).toContain('DEPT_1'); expect(wrapper.text()).toContain('尚未保存读取结果')
    if (status === 'CONFIG_UNAVAILABLE') expect(button(wrapper, '首次读取部门').attributes('disabled')).toBeDefined()
  })
  it.each(['EXPIRED', 'CONFIG_CHANGED'] as const)('%s或空令牌禁止保存', async status => {
    const data = preview(); data.data.preview_token = ''; data.data.snapshot.status = status; data.data.snapshot.can_submit = false; data.data.can_save_mapping = false
    api.getDepartmentMappings.mockResolvedValueOnce(data)
    const wrapper = await render(); expect(target(wrapper).attributes('disabled')).toBeDefined()
  })
  it('合规导入副本允许本地绑定，但不能刷新企微', async () => {
    const data = preview(); data.data.snapshot.status = 'CONFIG_UNAVAILABLE'; data.data.snapshot.can_submit = false
    api.getDepartmentMappings.mockResolvedValue(data)
    const wrapper = await render()
    expect(target(wrapper).attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.mapping-meta').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('数据来源：')
    expect(wrapper.text()).not.toContain('CorpID：')
    expect(wrapper.text()).not.toContain('读取时间：')
    expect(button(wrapper, '重新读取映射').attributes('disabled')).toBeDefined()
    await target(wrapper).setValue('department-2'); await flushPromises()
    expect(api.saveDepartmentMapping).toHaveBeenCalledExactlyOnceWith(1, { preview_token: 'mapping-token', organization_unit_id: 'department-2', organization_etag: '"organization-v1"', confirmed: true }, '"mapping-v1"')
    expect(api.refreshDepartmentMappings).not.toHaveBeenCalled()
    expect(button(wrapper, '重新读取映射').attributes('disabled')).toBeDefined()
  })
  it('独立映射能力为false时，即使通用快照有效也禁止写入', async () => {
    const data = preview(); data.data.can_save_mapping = false; api.getDepartmentMappings.mockResolvedValueOnce(data)
    const wrapper = await render(); expect(target(wrapper).attributes('disabled')).toBeDefined()
    await target(wrapper).setValue('department-2'); await flushPromises(); expect(api.saveDepartmentMapping).not.toHaveBeenCalled()
  })
  it.each(['token', 'etag', 'expiry'] as const)('导入能力为true但缺少有效%s仍禁止保存', async missing => {
    const data = preview(); data.data.snapshot.status = 'CONFIG_UNAVAILABLE'; data.data.snapshot.can_submit = false
    if (missing === 'token') data.data.preview_token = ''
    if (missing === 'etag') data.etag = ''
    if (missing === 'expiry') data.data.snapshot.expires_at = '2000-01-01T00:00:00Z'
    api.getDepartmentMappings.mockResolvedValueOnce(data)
    const wrapper = await render(); expect(target(wrapper).attributes('disabled')).toBeDefined()
    await target(wrapper).setValue('department-2'); await flushPromises(); expect(api.saveDepartmentMapping).not.toHaveBeenCalled()
  })
  it('历史不可用目标仍回显，不自动清空', async () => {
    const data = preview(); data.data.departments[0]!.mapping!.organization_unit_id = 'inactive'; data.data.departments[0]!.mapping!.organization_active = false
    api.getDepartmentMappings.mockResolvedValueOnce(data)
    const wrapper = await render(); expect((target(wrapper).element as HTMLSelectElement).value).toBe('inactive'); expect(wrapper.text()).toContain('目标不可用')
  })
  it.each([401, 403])('刷新%s清空敏感表', async status => {
    api.refreshDepartmentMappings.mockRejectedValueOnce({ isAxiosError: true, response: { status } })
    const wrapper = await render(); await button(wrapper, '重新读取映射').trigger('click'); await flushPromises()
    expect(wrapper.find('tbody').exists()).toBe(false); expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })
  it('关闭晚到响应不能覆盖重开快照，无权限不读取', async () => {
    let finish!: (value: DepartmentMappingPreviewResponse) => void
    api.getDepartmentMappings.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render(); await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    const old = preview(); old.data.departments[0]!.name = '旧读取部门'; finish(old); await flushPromises()
    expect(wrapper.get('tbody').text()).not.toContain('旧读取部门')
    useAuthStore().user!.is_superuser = false; await flushPromises()
    expect(wrapper.find('tbody').exists()).toBe(false)
  })
})
