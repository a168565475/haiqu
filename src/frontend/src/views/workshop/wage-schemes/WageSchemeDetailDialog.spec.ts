import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WageSchemeDetailDialog from './WageSchemeDetailDialog.vue'

const api = vi.hoisted(() => ({ detail: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const auth = vi.hoisted(() => ({
  isSuperuser: false,
  permissions: new Set<string>(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => router,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { get is_superuser() { return auth.isSuperuser } },
    hasPermission: (permission: string) => auth.permissions.has(permission),
  }),
}))

vi.mock('@/api/workshopReporting', () => ({
  fetchWageScheme: api.detail,
}))

const scheme = {
  id: 'scheme-1',
  scheme_number: 'GJFA-20260918-001',
  status: 'APPROVED',
  status_display: '已批准',
  can_create_change: true,
  lines: [{
    id: 'line-1', line_number: 1, operation_name: '下料', operation_number: 'GX-001',
    display_name: '桌腿', production_description: '按定位线精准下料', unit_name: '件',
    previous_price: '2.0000', revised_price: '2.2000', declared_price: '2.2000',
    status: 'ACTIVE', note: '首件确认后批量制作',
  }],
  events: [{
    id: 'event-1', action: 'APPROVED', action_display: '已批准', actor: '王主管', scheme_revision: 2,
    comment: '同意执行', created_at: '2026-09-18T15:20:00+08:00',
  }],
}

beforeEach(() => {
  auth.isSuperuser = false
  auth.permissions = new Set([
    'workshop_reporting.change_wagescheme',
    'workshop_reporting.submit_wagescheme',
  ])
  api.detail.mockResolvedValue({ data: scheme, etag: '"1"' })
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('工价详情弹窗', () => {
  it('将表格颜色与超紧凑行高直接覆盖到 ElTable', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/workshop/wage-schemes/WageSchemeDetailDialog.vue'), 'utf8')
    expect(source).toMatch(/\.wage-detail-dialog__table\s*\{[\s\S]*?--el-table-header-bg-color:\s*#f0eadf;/)
    expect(source).toMatch(/\.wage-detail-dialog__table\s*\{[\s\S]*?--el-table-border-color:\s*#ddd6c9;/)
    expect(source).toMatch(/\.wage-detail-dialog__table\s*\{[\s\S]*?--el-table-row-hover-bg-color:\s*#fff6ea;/)
    expect(source).toMatch(/\.el-table__body tr:hover > td\.el-table__cell\s*\{[\s\S]*?background:\s*#fff6ea !important;/)
    expect(source).toMatch(/\.el-table__body tr\s*\{[\s\S]*?height:\s*36px !important;/)
    expect(source).toMatch(/\.el-table__body-wrapper td\.el-table__cell\s*\{[\s\S]*?box-sizing:\s*border-box;[\s\S]*?height:\s*36px !important;/)
    expect(source).not.toContain('max-height="calc(100% - 34px)"')
    expect(source).toContain(':max-height="tableMaxHeight"')
    expect(source).toContain('label="状态" width="72" align="center"')
    expect(source).not.toContain('height="100%"')
    expect(source).not.toContain('prop="operation_number"')
    expect(source).not.toContain('prop="line_number"')
    expect(source).toContain('prop="display_name" label="名称 / 部位" min-width="150"')
    expect(source).toContain('prop="operation_name" label="申报工序" min-width="100"')
    expect(source).toContain('prop="production_description" label="制作工序描述" min-width="170"')
    expect(source).toContain('prop="note" label="备注" min-width="120"')
    expect(source).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\) 320px;/)
    expect(source).toMatch(/@media \(max-width: 1280px\)[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) 280px;/)
  })

  it('按统一窗口展示规范表格，并为可变更方案提供变更入口', async () => {
    const wrapper = mount(WageSchemeDetailDialog, {
      attachTo: document.body,
      props: { modelValue: true, schemeId: 'scheme-1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const dialog = document.body.querySelector('[data-testid="wage-scheme-detail-dialog"]')
    expect(api.detail).toHaveBeenCalledWith('scheme-1')
    expect(dialog?.textContent).toContain('工价详情')
    expect(dialog?.textContent).toContain('工价明细')
    expect(dialog?.textContent).toContain('审批记录')
    expect(dialog?.textContent).not.toContain('基本信息')
    expect(dialog?.textContent).not.toContain('内容版本')
    expect(dialog?.textContent).not.toContain('单位')
    expect(dialog?.textContent).not.toContain('工序编号')
    expect(dialog?.textContent).not.toContain('序号')
    expect(dialog?.textContent).not.toContain('GX-001')
    expect(dialog?.textContent).toContain('按定位线精准下料')
    expect(dialog?.textContent).toContain('首件确认后批量制作')
    expect(dialog?.textContent).not.toContain('保存草稿')
    expect(dialog?.textContent).toContain('关闭')
    expect(dialog?.textContent).toContain('变更')
    expect(dialog?.classList.contains('app-window-dialog')).toBe(true)
    expect(dialog?.querySelectorAll('.wage-detail-dialog__table')).toHaveLength(1)
    expect(dialog?.querySelector('.wage-detail-dialog__approval-list')).not.toBeNull()
    expect(dialog?.querySelector('.wage-detail-dialog__event')?.textContent).toContain('同意执行')
    expect(dialog?.querySelector('.wage-status-tag.is-success')).not.toBeNull()

    const headers = Array.from(dialog?.querySelectorAll('.wage-detail-dialog__table th') || [])
      .map(cell => cell.textContent?.trim())
      .filter(Boolean)
    expect(headers).toEqual([
      '名称 / 部位', '申报工序', '需完成次数', '制作工序描述', '申报工价', '状态',
      '以往工价', '修改工价', '备注',
    ])
    expect(dialog?.textContent).toContain('¥2.2')
    expect(dialog?.textContent).not.toContain('¥2.2000')

    const table = dialog?.querySelector<HTMLElement>('.wage-detail-dialog__table')
    const headerCell = table?.querySelector<HTMLElement>('th.el-table__cell')
    const bodyCell = table?.querySelector<HTMLElement>('td.el-table__cell')
    expect(getComputedStyle(table!).getPropertyValue('--el-table-header-bg-color').trim()).toBe('#f0eadf')
    expect(getComputedStyle(table!).getPropertyValue('--el-table-border-color').trim()).toBe('#ddd6c9')
    expect(getComputedStyle(table!).getPropertyValue('--el-table-row-hover-bg-color').trim()).toBe('#fff6ea')
    expect(getComputedStyle(headerCell!).height).toBe('44px')
    expect(getComputedStyle(headerCell!).backgroundColor).toBe('rgb(240, 234, 223)')
    expect(getComputedStyle(bodyCell!).height).toBe('36px')
    expect(table?.style.maxHeight).toBe('560px')

    const changeButton = document.body.querySelector<HTMLButtonElement>('[data-testid="wage-scheme-change-button"]')
    expect(changeButton).not.toBeNull()
    changeButton?.click()
    await flushPromises()
    expect(router.push).toHaveBeenCalledWith({
      name: 'wage-scheme-change',
      params: { schemeId: 'scheme-1' },
    })

    wrapper.unmount()
  })

  it('非已批准方案或权限不足时不显示变更入口', async () => {
    api.detail.mockResolvedValueOnce({
      data: { ...scheme, status: 'RETURNED', status_display: '已退回' },
      etag: '"2"',
    })
    const returnedWrapper = mount(WageSchemeDetailDialog, {
      attachTo: document.body,
      props: { modelValue: true, schemeId: 'scheme-1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(document.body.querySelector('[data-testid="wage-scheme-change-button"]')).toBeNull()
    returnedWrapper.unmount()

    auth.permissions.delete('workshop_reporting.submit_wagescheme')
    api.detail.mockResolvedValueOnce({ data: scheme, etag: '"3"' })
    const unauthorizedWrapper = mount(WageSchemeDetailDialog, {
      attachTo: document.body,
      props: { modelValue: true, schemeId: 'scheme-1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(document.body.querySelector('[data-testid="wage-scheme-change-button"]')).toBeNull()
    unauthorizedWrapper.unmount()
  })

  it('明细和审批记录为空时显示各自空态', async () => {
    api.detail.mockResolvedValueOnce({
      data: { ...scheme, lines: [], events: [] },
      etag: '"4"',
    })
    const wrapper = mount(WageSchemeDetailDialog, {
      attachTo: document.body,
      props: { modelValue: true, schemeId: 'scheme-1' },
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const dialog = document.body.querySelector('[data-testid="wage-scheme-detail-dialog"]')
    expect(dialog?.textContent).toContain('暂无工价明细')
    expect(dialog?.textContent).toContain('暂无审批记录')

    wrapper.unmount()
  })
})
