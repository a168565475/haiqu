import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElDropdown, ElFormItem, ElInput, ElOption, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Craft, Operation, WorkshopEmployee } from '@/types/workshopConfig'
import WorkshopConfigManager from './WorkshopConfigManager.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), create: vi.fn(), copyScheme: vi.fn(), update: vi.fn(), remove: vi.fn() }))
const feedback = vi.hoisted(() => ({ warning: vi.fn(), error: vi.fn(), success: vi.fn(), confirm: vi.fn(), prompt: vi.fn() }))
const auth = vi.hoisted(() => ({ user: { is_superuser: false }, hasPermission: vi.fn() }))
vi.mock('@/api/workshopConfig', () => ({
  fetchWorkshopConfigList: api.list,
  fetchWorkshopConfigDetail: api.detail,
  fetchWorkshopEmployeeOptions: api.options,
  createWorkshopConfig: api.create,
  copyOperationScheme: api.copyScheme,
  updateWorkshopConfig: api.update,
  deleteWorkshopEmployee: api.remove,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: feedback,
  ElMessageBox: { confirm: feedback.confirm, prompt: feedback.prompt },
}))

const legacy: WorkshopEmployee = {
  id: 'assignment-1', workshop: 'workshop-1', workshop_name: '金工车间', position: '组长',
  name: '同名员工', employee: 'assignment-1', employee_code: 'E001', employee_name: '同名员工', employee_status: 'ACTIVE',
  employee_archived: false, department: '生产部', roles: '生产主管', is_supervisor: true, status: 'ACTIVE', status_display: '在职',
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z', can_edit: true,
  role_workshop: null, role_workshop_name: null,
}
const operation: Operation = {
  id: 'operation-1', operation_number: 'OP-LEGACY-001', product_name: '', craft: 'craft-1', craft_name: '金属装配',
  craft_type: 'INTERNAL', craft_type_display: '厂内', workshop: 'workshop-1', workshop_name: '金工车间', name: '弯管',
  reporting_unit: null, reporting_unit_name: null, status: 'ACTIVE', status_display: '启用',
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
}
const operationCraft: Craft = {
  id: 'craft-1', craft_type: 'INTERNAL', craft_type_display: '厂内', plan_category: 'METAL', plan_category_display: '金工计划',
  outsourcing_code: null, outsourcing_code_display: null, workshop: 'workshop-1', workshop_name: '金工车间', name: '金属装配',
  status: 'ACTIVE', status_display: '启用', operation_count: 1, active_operation_count: 1,
  created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z',
}
const wrappers: VueWrapper[] = []

async function render(record = legacy) {
  api.list.mockImplementation((kind: string) => kind === 'workshops' && !auth.hasPermission('workshop_config.view_workshop')
    ? Promise.reject({ response: { status: 403, data: { error: { message: '无权读取完整车间目录' } } } }) : Promise.resolve({
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
  api.options.mockResolvedValue({ workshops: [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }], editable_workshops: [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }] })
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

  it('角色对应的未安排员工自动带入车间，车间只读且可保存岗位', async () => {
    const wrapper = await render({
      ...legacy, workshop: null, workshop_name: '未安排', position: '',
      roles: '金工车间', role_workshop: 'workshop-1', role_workshop_name: '金工车间',
    })
    await edit(wrapper)
    expect(field(wrapper, '车间').findComponent(ElSelect).exists()).toBe(false)
    expect(field(wrapper, '车间').getComponent(ElInput).props('disabled')).toBe(true)
    field(wrapper, '岗位').getComponent(ElInput).vm.$emit('update:modelValue', '金工')
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.update).toHaveBeenCalledWith('employees', legacy.id, {
      workshop: 'workshop-1', position: '金工', is_supervisor: true, status: 'ACTIVE',
    }, '"assignment-v1"')
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

  it('主任只需员工权限即可加载选项，筛选和编辑使用各自车间范围', async () => {
    auth.hasPermission.mockImplementation((permission: string) => ['workshop_config.view_workshopemployee', 'workshop_config.change_workshopemployee'].includes(permission))
    api.options.mockResolvedValue({
      workshops: [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }, { id: 'workshop-2', name: '车缝车间', status: 'ACTIVE' }],
      editable_workshops: [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }],
    })
    const wrapper = await render()
    expect(wrapper.text()).not.toContain('无权读取完整车间目录')
    expect(api.list.mock.calls.some(([kind]) => kind === 'workshops')).toBe(false)
    expect(api.options).toHaveBeenCalledOnce()
    const filter = wrapper.findAllComponents(ElSelect).find(item => item.props('placeholder') === '全部车间')!
    expect(filter.findAllComponents(ElOption).map(item => item.props('value'))).toEqual(['workshop-1', 'workshop-2'])
    await edit(wrapper)
    expect(field(wrapper, '车间').findAllComponents(ElOption).map(item => item.props('value'))).toEqual(['workshop-1'])
  })

  it('有修改权限但员工行不在修改范围时不显示操作，详情失权后不继续写入', async () => {
    const readonly = await render({ ...legacy, can_edit: false })
    expect(readonly.findComponent(ElDropdown).exists()).toBe(false)
    const wrapper = await render()
    api.detail.mockResolvedValue({ data: { ...legacy, can_edit: false }, etag: '"v2"' })
    await edit(wrapper)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'toggle'); await flushPromises()
    wrapper.getComponent(ElDropdown).vm.$emit('command', 'delete'); await flushPromises()
    expect(api.update).not.toHaveBeenCalled()
    expect(api.remove).not.toHaveBeenCalled()
  })
})

describe('工序配置自动编号与快捷筛选', () => {
  async function renderOperations(props: Record<string, unknown> = {}, craftRecords = [operationCraft], operationRecords = [operation]) {
    api.list.mockImplementation((kind: string, query: { craft_type?: string; craft?: string; status?: string; page?: number; page_size?: number }) => {
      const data = kind === 'workshops' ? [{ id: 'workshop-1', name: '金工车间', status: 'ACTIVE' }]
        : kind === 'crafts' ? (query.craft_type === 'INTERNAL' ? craftRecords : [
          ...craftRecords, { ...operationCraft, id: 'external-craft', name: '喷塑', craft_type: 'EXTERNAL', craft_type_display: '厂外' },
        ]) : operationRecords.filter(row => (!query.craft || row.craft === query.craft) && (!query.status || row.status === query.status))
      const { page = 1, page_size = 20 } = query
      return Promise.resolve({
        data: data.slice((page - 1) * page_size, page * page_size),
        meta: { page, page_size, total: data.length, total_pages: Math.ceil(data.length / page_size) },
      })
    })
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

  it('工序管理固定筛选厂内工艺，隐藏类型筛选、列和表单字段', async () => {
    const wrapper = await renderOperations()
    const query = expect.objectContaining({ craft_type: 'INTERNAL', craft: 'craft-1' })
    expect(api.list).toHaveBeenCalledWith('operations', query)
    expect(api.list).toHaveBeenCalledWith('crafts', expect.objectContaining({ craft_type: 'INTERNAL' }))
    const filters = wrapper.findAllComponents(ElSelect)
    expect(filters.some(select => select.props('ariaLabel') === '类型')).toBe(false)
    expect(filters.some(select => select.props('ariaLabel') === '工艺')).toBe(false)
    expect(filters.some(select => select.props('ariaLabel') === '车间')).toBe(false)
    expect(wrapper.findAll('[role="tab"]').map(tab => tab.text())).toEqual(['金属装配'])
    const columns = wrapper.findAllComponents({ name: 'ElTableColumn' }).map(column => column.props('label'))
    expect(columns).toContain('方案名称')
    expect(columns).not.toContain('类型')
    expect(columns).not.toContain('工艺')
    expect(columns).not.toContain('车间')
    expect(columns).not.toContain('品名')
    await button(wrapper, '重置').trigger('click')
    expect(api.list).toHaveBeenLastCalledWith('operations', query)

    await button(wrapper, '新增工序').trigger('click')
    expect(wrapper.findAllComponents(ElFormItem).map(item => item.props('label'))).not.toContain('类型（自动）')
    expect(field(wrapper, '工艺').findAllComponents(ElOption).map(option => option.props('label'))).toEqual(['金属装配'])
  })

  it('方案名称用于非金工工序的表单与校验', async () => {
    const sewing = { ...operationCraft, id: 'craft-sewing', name: '车缝加工', workshop_name: '车缝车间' }
    const wrapper = await renderOperations({}, [sewing], [])
    await button(wrapper, '新增工序').trigger('click')
    await setSelect(wrapper, '工艺', sewing.id)
    expect(field(wrapper, '方案名称').getComponent(ElInput).props('placeholder')).toBe('请输入方案名称')
    expect(field(wrapper, '车间（自动）')).toBeUndefined()
    await button(wrapper, '保存').trigger('click')
    expect(feedback.warning).toHaveBeenCalledWith('请输入方案名称。')
  })

  it('只在新增时使用入口传入的弹窗宽度', async () => {
    const wrapper = await renderOperations({ createDialogWidth: '80vw' })
    await edit(wrapper)
    expect(wrapper.get('[role="dialog"]').attributes('width')).toBe('900')
    await button(wrapper, '取消').trigger('click')
    await button(wrapper, '新增工序').trigger('click')
    expect(wrapper.get('[role="dialog"]').attributes('width')).toBe('80vw')
  })

  it('表格上方按工艺切换，每次只取所选工艺的工序', async () => {
    const welding = { ...operationCraft, id: 'craft-2', name: '焊接' }
    const weldingOperation = { ...operation, id: 'operation-2', craft: 'craft-2', craft_name: '焊接', name: '点焊' }
    const wrapper = await renderOperations({}, [operationCraft, welding], [operation, weldingOperation])
    const tableCard = wrapper.get('.table-card')
    expect(tableCard.element.firstElementChild).toBe(wrapper.get('.operation-craft-tabs').element)
    const tabs = tableCard.findAll('[role="tab"]')
    expect(tabs.map(tab => tab.text())).toEqual(['金属装配', '焊接'])
    expect(tabs[0]!.attributes('aria-selected')).toBe('true')
    expect(tableCard.get('.table-region').text()).toContain('弯管')
    expect(tableCard.get('.table-region').text()).not.toContain('点焊')

    await tabs[1]!.trigger('click')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith('operations', expect.objectContaining({
      page: 1, craft_type: 'INTERNAL', craft: 'craft-2',
    }))
    expect(tabs[1]!.attributes('aria-selected')).toBe('true')
    expect(tableCard.get('.table-region').text()).toContain('点焊')
    expect(tableCard.get('.table-region').text()).not.toContain('弯管')
  })

  it('管材加工跨接口分页显示工序标签，删除确认后停用，仍可筛选已停用工序', async () => {
    const tube = { ...operationCraft, name: '管材加工' }
    const tubeRows: Operation[] = Array.from({ length: 101 }, (_, index) => ({
      ...operation, id: `pipe-${index + 1}`, name: `管材工序 ${index + 1}`, craft_name: tube.name, product_name: '旧方案',
    }))
    const wrapper = await renderOperations({}, [tube], tubeRows)
    const tags = wrapper.get('.operation-tags')
    expect(tags.findAll('.operation-tag')).toHaveLength(101)
    expect(tags.text()).toContain('管材工序 101')
    expect(tags.text()).not.toContain('旧方案')
    expect(wrapper.find('.pagination-bar').exists()).toBe(false)
    expect(wrapper.find('.el-table').exists()).toBe(false)
    expect(api.list).toHaveBeenCalledWith('operations', expect.objectContaining({ page: 2, status: 'ACTIVE', craft: tube.id }))

    const remove = tags.get('[aria-label="删除工序 管材工序 1"]')
    feedback.confirm.mockRejectedValueOnce('cancel')
    await remove.trigger('click')
    await flushPromises()
    expect(api.update).not.toHaveBeenCalled()
    api.update.mockImplementationOnce(async () => { tubeRows[0]!.status = 'INACTIVE' })
    await remove.trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledExactlyOnceWith('operations', 'pipe-1', { status: 'INACTIVE' }, '"operation-v1"')
    expect(tags.findAll('.operation-tag')).toHaveLength(100)
    expect(tags.find('[aria-label="删除工序 管材工序 1"]').exists()).toBe(false)

    const status = wrapper.findAllComponents(ElSelect).find(select => select.props('ariaLabel') === '状态')!
    status.vm.$emit('update:modelValue', 'INACTIVE')
    status.vm.$emit('change', 'INACTIVE')
    await flushPromises()
    expect(tags.findAll('.operation-tag').map(tag => tag.text())).toEqual(['管材工序 1'])
    expect(tags.find('.operation-tag__remove').exists()).toBe(false)
  })

  it('管材工序查看权限只显示工序名', async () => {
    auth.hasPermission.mockImplementation((permission: string) => permission === 'workshop_config.view_operation')
    const wrapper = await renderOperations({}, [{ ...operationCraft, name: '管材加工' }])
    expect(wrapper.get('.operation-tag').text()).toBe('弯管')
    expect(wrapper.find('.operation-tag button').exists()).toBe(false)
  })

  it.each([
    ['裁剪', 'CUTTING'],
    ['车缝', 'SEWING'],
    ['装配/包装', 'ASSEMBLY'],
  ] as const)('%s 的方案卡片同页显示各自工序标签', async (name, plan_category) => {
    const craft = { ...operationCraft, name, plan_category }
    const records = [
      { ...operation, name: '定位', product_name: 'HQ-01' },
      { ...operation, id: 'operation-2', name: '复检', product_name: 'HQ-01' },
      { ...operation, id: 'operation-3', name: '封边', product_name: 'HQ-02' },
    ]
    const wrapper = await renderOperations({}, [craft], records)
    expect(wrapper.findAll('[role="tab"]').map(tab => tab.text())).toEqual([name])
    const cards = wrapper.findAll('.operation-scheme-card')
    expect(cards.map(card => card.get('h3').text())).toEqual(['HQ-01', 'HQ-02'])
    expect(cards.map(card => card.findAll('.operation-tag').map(tag => tag.text()))).toEqual([
      ['定位', '复检'], ['封边'],
    ])
    expect(wrapper.find('.pagination-bar').exists()).toBe(false)
  })

  it('选用并标出当前工艺允许的方案，兼容未设置计划分类的工艺', async () => {
    const assembly = { ...operationCraft, name: '装配/包装', plan_category: null }
    const sewing = { ...operationCraft, id: 'craft-sewing', name: '车缝', plan_category: 'SEWING' as const }
    const records = [
      { ...operation, product_name: 'HQ-01' },
      { ...operation, id: 'operation-selected', name: '装配', product_name: 'HQ-02' },
      { ...operation, id: 'operation-other-craft', name: '车缝', craft: sewing.id, product_name: 'HQ-02' },
    ]
    const wrapper = await renderOperations({ initialCraft: assembly.id, initialSchemeName: 'HQ-02', selectableSchemeNames: ['HQ-02'] }, [assembly, sewing], records)
    const selected = wrapper.get('.operation-scheme-card--selected')
    expect(selected.get('h3').text()).toBe('HQ-02')
    expect(selected.attributes('aria-current')).toBe('true')
    expect(selected.get('.operation-tag').text()).toBe('装配')
    expect(wrapper.find('[aria-label="选用工价方案 HQ-01"]').exists()).toBe(false)
    await selected.get('[aria-label="选用工价方案 HQ-02"]').trigger('click')
    expect(wrapper.emitted('select-scheme')).toEqual([['HQ-02']])

    await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.operation-scheme-card h3').text()).toBe('HQ-02')
    expect(wrapper.find('.operation-scheme-card--selected').exists()).toBe(false)
    expect(wrapper.find('[aria-label="选用工价方案 HQ-02"]').exists()).toBe(false)
  })

  it('卡片新增工序只提交名称，复制一次提交整组并通知表单刷新方案', async () => {
    const craft = { ...operationCraft, name: '装配/包装', plan_category: 'ASSEMBLY' as const }
    const wrapper = await renderOperations({}, [craft], [{ ...operation, product_name: 'HQ-01' }])

    feedback.prompt.mockResolvedValueOnce({ value: ' 补装 ' })
    await wrapper.get('[aria-label="新增工序 HQ-01"]').trigger('click')
    await flushPromises()
    expect(feedback.prompt).toHaveBeenLastCalledWith('当前方案 HQ-01', '新增工序', expect.objectContaining({ inputPlaceholder: '请输入工序名称' }))
    expect(api.create).toHaveBeenCalledExactlyOnceWith('operations', {
      craft: craft.id, product_name: 'HQ-01', name: '补装', status: 'ACTIVE',
    })

    feedback.prompt.mockResolvedValueOnce({ value: 'HQ-02' })
    await wrapper.get('[aria-label="复制方案 HQ-01"]').trigger('click')
    await flushPromises()
    expect(api.copyScheme).toHaveBeenCalledExactlyOnceWith(craft.id, 'HQ-01', 'HQ-02')
    expect(api.list).toHaveBeenLastCalledWith('operations', expect.objectContaining({ q: 'HQ-02' }))
    expect(wrapper.emitted('schemes-changed')).toHaveLength(2)
    expect(wrapper.emitted('saved')).toBeUndefined()
  })

  it('只剩停用的厂内工艺时显示空态', async () => {
    const wrapper = await renderOperations({}, [{ ...operationCraft, status: 'INACTIVE' }])
    expect(wrapper.find('[role="tab"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('暂无厂内工艺')
    expect(api.list.mock.calls.some(([kind]) => kind === 'operations')).toBe(false)
  })

  it('按当前车间、厂内类型和工艺初始化筛选，并在保存后发出 saved 事件', async () => {
    const wrapper = await renderOperations({ initialWorkshop: 'workshop-1', initialCraft: 'craft-1' })
    expect(api.list.mock.calls.some(([kind, query]) => kind === 'operations' && query.workshop === 'workshop-1' && query.craft_type === 'INTERNAL' && query.craft === 'craft-1')).toBe(true)
    await button(wrapper, '新增工序').trigger('click')
    expect(wrapper.get('[role="dialog"]').attributes('width')).toBe('900')
    await setSelect(wrapper, '工艺', 'craft-1')
    field(wrapper, '工序名称').getComponent(ElInput).vm.$emit('update:modelValue', '新增冲孔')
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
