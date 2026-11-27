import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WageSchemeDetailView from './WageSchemeDetailView.vue'

const api = vi.hoisted(() => ({
  approve: vi.fn(),
  detail: vi.fn(),
  returnScheme: vi.fn(),
  submit: vi.fn(),
  withdraw: vi.fn(),
}))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const auth = vi.hoisted(() => ({
  user: { is_superuser: true, employee: { id: 'employee-1' }, effective_access: {
    actions: {} as Record<string, { scopes: string[] }>,
  } },
  hasPermission: () => true,
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { schemeId: 'scheme-1' } }),
  useRouter: () => router,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => auth,
}))

vi.mock('@/api/workshopReporting', () => ({
  approveWageScheme: api.approve,
  fetchWageScheme: api.detail,
  returnWageScheme: api.returnScheme,
  submitWageScheme: api.submit,
  withdrawWageScheme: api.withdraw,
}))

const scheme = {
  id: 'scheme-1',
  scheme_number: 'GJ-202609-000002',
  status: 'PENDING_APPROVAL',
  status_display: '待审批',
  version: 1,
  revision: 2,
  can_create_change: false,
  created_by_id: 'employee-1',
  production_task: { task_number: 'SC-001' },
  product: { name: '围炉桌' },
  workshop: { name: '金工车间' },
  crafts: [{ id: 'craft-1', name: '管材加工' }],
  effective_from: null,
  effective_to: null,
  declared_total: '0.6000',
  operation_product_name: '管材加工',
  remark: '首件确认后批量制作',
  created_by: '业务员 A',
  updated_at: '2026-09-28T07:20:00+08:00',
  lines: [{
    id: 'line-1',
    work_item_id: 'work-item-1',
    craft_id: 'craft-1',
    craft_name: '管材加工',
    operation_id: 'operation-1',
    operation_number: 'GX-001',
    operation_name: '切管',
    display_name: '前脚管-20*1.0*500',
    production_description: '按定位线精准下料',
    required_quantity: '4000.0000',
    previous_price: '0.5000',
    revised_price: null,
    declared_price: '0.6000',
    status: 'ACTIVE',
    status_display: '正常',
    note: '首件确认后批量制作',
  }],
  events: [{
    id: 'event-submit', action: 'SUBMITTED', action_display: '送审', scheme_revision: 2,
    actor: '业务员 A', comment: '', created_at: '2026-09-28T06:58:00+08:00',
  }],
}

beforeEach(() => {
  auth.user.is_superuser = true
  auth.user.employee.id = 'employee-1'
  auth.user.effective_access.actions = {}
  api.detail.mockResolvedValue({ data: scheme, etag: '"2"' })
  api.approve.mockResolvedValue({
    data: { ...scheme, status: 'APPROVED', status_display: '已批准', effective_from: '2026-09-28' },
    etag: '"3"',
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('工价方案审批确认', () => {
  it('待审批时从修改进入原申请，使用当前版本完成撤回', async () => {
    api.detail.mockResolvedValueOnce({ data: { ...scheme, can_withdraw: true, scope_craft: { plan_category: 'CUTTING' }, lines: [{
      ...scheme.lines[0], counting_mode: 'GROUP', counting_mode_display: '按组', cutting_components: [
        { component_identity: 'front', name: '床面', quantity_per_group: 1, unit: '片' },
        { component_identity: 'side', name: '侧片', quantity_per_group: 2, unit: '片' },
      ],
    }] }, etag: '"2"' })
    api.withdraw.mockResolvedValueOnce({
      data: { ...scheme, status: 'DRAFT', can_withdraw: false, withdrawn_by_me: true }, etag: '"3"',
    })
    const wrapper = mount(WageSchemeDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.get('.cutting-group-cell').text()).toBe('床面+1')
    expect(wrapper.get('.wr-approval-table').text()).toContain('按套')
    const actions = wrapper.findAll('button')
    expect(actions.some(button => button.text().trim() === '提交')).toBe(false)
    await actions.find(button => button.text().trim() === '修改')!.trigger('click')
    await flushPromises()
    expect(api.withdraw).toHaveBeenCalledExactlyOnceWith('scheme-1', '"2"')
    expect(router.push).toHaveBeenCalledExactlyOnceWith({ name: 'wage-scheme-change', params: { schemeId: 'scheme-1' } })
    wrapper.unmount()
  })

  it('有全模块修改授权的普通管理者可代办，车间授权不扩大为他人草稿', async () => {
    auth.user.is_superuser = false
    auth.user.employee.id = 'manager'
    auth.user.effective_access.actions['workshop_reporting.change_wagescheme'] = { scopes: ['MODULE'] }
    api.detail.mockResolvedValue({ data: { ...scheme, status: 'DRAFT' }, etag: '"1"' })
    const manager = mount(WageSchemeDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(manager.findAll('button').some(button => button.text().trim() === '编辑')).toBe(true)
    manager.unmount()
    auth.user.effective_access.actions['workshop_reporting.change_wagescheme'] = { scopes: ['WORKSHOP'] }
    const director = mount(WageSchemeDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(director.findAll('button').some(button => button.text().trim() === '编辑')).toBe(false)
    director.unmount()
  })
  it('确认弹窗按钮使用车间模块设计规范', () => {
    const styles = readFileSync(resolve(process.cwd(), 'src/styles/workshopReporting.scss'), 'utf8')
    expect(styles).toMatch(/\.wr-confirm-message-box \.el-message-box__btns \.el-button \{[^}]*height:\s*32px;[^}]*border-radius:\s*5px;/)
    expect(styles).toMatch(/\.wr-confirm-message-box \.el-message-box__btns \.el-button--primary \{[^}]*background:\s*var\(--erp-button-primary-surface\);/)
  })

  it('不再填写生效日期，按统一按钮规范确认后直接批准', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(
      'confirm' as unknown as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )
    const prompt = vi.spyOn(ElMessageBox, 'prompt')
    const wrapper = mount(WageSchemeDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('制作工序描述')
    expect(wrapper.text()).toContain('按定位线精准下料')
    expect(wrapper.text()).toContain('4000')
    expect(wrapper.text()).not.toContain('4000.0000')
    expect(wrapper.text()).toContain('备注')
    expect(wrapper.text()).toContain('首件确认后批量制作')
    expect(wrapper.text()).not.toContain('版本')
    expect(wrapper.text()).toContain('申报工序')
    const nameCell = wrapper.get('.wr-approval-table .el-table__body tbody tr:first-child td:first-child .cell')
    expect(nameCell.text()).toBe(scheme.lines[0]!.display_name)
    expect(nameCell.classes()).not.toContain('el-tooltip')
    expect(wrapper.text()).toContain('¥0.6')
    expect(wrapper.text()).not.toContain('¥0.6000')
    expect(wrapper.text()).toContain('2026-09-28 06:58')

    const approveButton = wrapper.findAll('button').find(button => button.text().trim() === '批准')
    expect(approveButton).toBeDefined()
    await approveButton!.trigger('click')
    await flushPromises()

    expect(prompt).not.toHaveBeenCalled()
    expect(confirm).toHaveBeenCalledWith(
      '确认批准当前工价方案？系统将自动确定生效日期。',
      '批准工价方案',
      expect.objectContaining({
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        customClass: 'wr-confirm-message-box',
      }),
    )
    expect(api.approve).toHaveBeenCalledWith('scheme-1', '"2"')
    expect(router.push).toHaveBeenCalledWith({ name: 'wage-schemes', query: { detail: 'scheme-1' } })

    wrapper.unmount()
  })
})
