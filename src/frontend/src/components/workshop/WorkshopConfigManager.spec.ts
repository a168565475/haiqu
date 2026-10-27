import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElDropdown, ElFormItem, ElInput, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Craft, Operation, WorkshopEmployee } from '@/types/workshopConfig'
import WorkshopConfigManager from './WorkshopConfigManager.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() }))
const feedback = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn(), success: vi.fn(), confirm: vi.fn() }))
const auth = vi.hoisted(() => ({ user: { is_superuser: false }, hasPermission: vi.fn() }))
vi.mock('@/api/workshopConfig', () => ({
  fetchWorkshopConfigList: api.list,
  fetchWorkshopConfigDetail: api.detail,
  createWorkshopConfig: api.create,
  updateWorkshopConfig: api.update,
  deleteWorkshopEmployee: api.remove,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: feedback,
  ElMessageBox: { confirm: feedback.confirm },
}))

const legacy: WorkshopEmployee = {
  id: 'assignment-1', workshop: 'workshop-1', workshop_name: '金工车间', position: '组长',
  name: '同名员工', employee: 'assignment-1', employee_code: 'E001', employee_name: '同名员工', employee_status: 'ACTIVE',
  employee_archived: false, department: '生产部', roles: '生产主管', is_supervisor: true, status: 'ACTIVE', status_display: '在职',
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
}
const operation: Operation = {
  id: 'operation-1', operation_number: 'OP-LEGACY-001', product_name: '', craft: 'craft-1', craft_name: '管材加工',
  craft_type: 'INTERNAL', craft_type_display: '厂内', workshop: 'workshop-1', workshop_name: '金工车间', name: '弯管',
  reporting_unit: null, reporting_unit_name: null, status: 'ACTIVE', status_display: '启用',
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
}
const operationCraft: Craft = {
  id: 'craft-1', craft_type: 'INTERNAL', craft_type_display: '厂内', plan_category: 'METAL', plan_category_display: '金工计划',
  outsourcing_code: null, outsourcing_code_display: null, workshop: 'workshop-1', workshop_name: '金工车间', name: '管材加工',
  status: 'ACTIVE', status_display: '启用', operation_count: 1, active_operation_count: 1,
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
}
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
beforeEach(() => {
  vi.resetAllMocks()
  auth.hasPermission.mockReturnValue(true)
  api.create.mockResolvedValue({})
  api.update.mockResolvedValue({})
  feedback.confirm.mockResolvedValue(undefined)
})
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

describe('车间直接配置行政生产员工', () => {
  it('员工表显示行政部门和角色', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('生产部')
    expect(wrapper.text()).toContain('生产主管')
  })

  it('不提供新增员工入口，也不加载或更换员工身份', async () => {
    const wrapper = await render()
    expect(button(wrapper, '新增员工')).toBeUndefined()
    await edit(wrapper)
    expect(field(wrapper, '员工').text()).toContain('同名员工')
    expect(field(wrapper, '员工').findComponent(ElSelect).exists()).toBe(false)
    expect(api.options).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })

  it('按行政员工ID更新车间字段，保持姓名和部门不进入写入参数', async () => {
    const wrapper = await render()
    await edit(wrapper)
    field(wrapper, '岗位').getComponent(ElInput).vm.$emit('update:modelValue', '操作工')
    await setSelect(wrapper, '是否为主管', false)
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.update).toHaveBeenCalledExactlyOnceWith('employees', legacy.id, {
      workshop: 'workshop-1', position: '操作工', is_supervisor: false, status: 'ACTIVE',
    }, '"assignment-v1"')
    expect(api.create).not.toHaveBeenCalled()
  })

  it('未配置员工仍列出，编辑时必须同时选择车间和岗位', async () => {
    const wrapper = await render({ ...legacy, workshop: null, workshop_name: '未安排', position: '' })
    expect(wrapper.text()).toContain('未安排')
    await edit(wrapper)
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.update).not.toHaveBeenCalled()
    expect(feedback.warning).toHaveBeenCalledWith('请选择车间。')
    await setSelect(wrapper, '车间', 'workshop-1')
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(feedback.warning).toHaveBeenCalledWith('请输入岗位。')
  })

  it('清除安排使用版本控制，取消或失败不提示成功', async () => {
    const wrapper = await render()
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'delete'); await flushPromises()
    expect(api.remove).toHaveBeenCalledExactlyOnceWith(legacy.id, '"assignment-v1"')
    expect(feedback.confirm.mock.calls[0]?.[0]).toContain('清除')
    feedback.success.mockClear(); api.remove.mockClear()
    feedback.confirm.mockRejectedValueOnce('cancel')
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'delete'); await flushPromises()
    expect(api.remove).not.toHaveBeenCalled(); expect(feedback.success).not.toHaveBeenCalled()
    api.remove.mockRejectedValueOnce(new Error('failed'))
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'delete'); await flushPromises()
    expect(feedback.error).toHaveBeenCalled(); expect(feedback.success).not.toHaveBeenCalled()
  })

  it('只读用户没有修改入口', async () => {
    auth.hasPermission.mockImplementation((permission: string) => permission === 'workshop_config.view_workshopemployee')
    const wrapper = await render()
    expect(button(wrapper, '新增员工')).toBeUndefined()
    expect(wrapper.findComponent(ElDropdown).exists()).toBe(false)
  })

  it('版本冲突保留岗位输入，不自动重试写入', async () => {
    api.update.mockRejectedValueOnce({ response: { status: 412, data: { error: { message: '配置已变化，请重新读取' } } } })
    const wrapper = await render(); await edit(wrapper)
    field(wrapper, '岗位').getComponent(ElInput).vm.$emit('update:modelValue', '新岗位')
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.update).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(field(wrapper, '岗位').getComponent(ElInput).props('modelValue')).toBe('新岗位')
    expect(feedback.error).toHaveBeenCalledWith('配置已变化，请重新读取')
  })

  it('结束车间任职只提交车间状态', async () => {
    const wrapper = await render()
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'toggle'); await flushPromises()
    expect(api.update).toHaveBeenCalledExactlyOnceWith('employees', legacy.id, { status: 'LEFT' }, '"assignment-v1"')
  })
})

describe('工序配置自动编号与快捷筛选', () => {
  async function renderOperations(props: Record<string, unknown> = {}) {
    api.list.mockImplementation((kind: string) => Promise.resolve({
      data: kind === 'workshops' ? [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }] : kind === 'crafts' ? [operationCraft] : [operation],
      meta: { page: 1, page_size: 20, total: 1, total_pages: 1 },
    }))
    api.detail.mockResolvedValue({ data: operation, etag: '"operation-v1"' })
    const wrapper = mount(WorkshopConfigManager, {
      props: { kind: 'operations', ...props },
      global: {
        plugins: [ElementPlus],
        stubs: { AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue" role="dialog"><slot/><slot name="footer"/></section>' } },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()
    return wrapper
  }

  it('工序列表和表单不显示编号，创建请求由页面省略编号', async () => {
    const wrapper = await renderOperations()
    expect(wrapper.text()).not.toContain('工序编号')
    await button(wrapper, '新增工序').trigger('click')
    expect(wrapper.findAllComponents(ElFormItem).some((item) => item.props('label') === '工序编号')).toBe(false)
    await setSelect(wrapper, '工艺', 'craft-1')
    field(wrapper, '工序名称').getComponent(ElInput).vm.$emit('update:modelValue', '新增弯管')
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.create).toHaveBeenCalledExactlyOnceWith('operations', {
      product_name: '', craft: 'craft-1', name: '新增弯管', status: 'ACTIVE',
    })
  })

  it('按当前车间、厂内类型和工艺初始化筛选，并在保存后发出 saved 事件', async () => {
    const wrapper = await renderOperations({ initialWorkshop: 'workshop-1', initialCraftType: 'INTERNAL', initialCraft: 'craft-1' })
    expect(api.list.mock.calls.some(([kind, query]) => kind === 'operations' && query.workshop === 'workshop-1' && query.craft_type === 'INTERNAL' && query.craft === 'craft-1')).toBe(true)
    await button(wrapper, '新增工序').trigger('click')
    await setSelect(wrapper, '工艺', 'craft-1')
    field(wrapper, '工序名称').getComponent(ElInput).vm.$emit('update:modelValue', '新增冲孔')
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
