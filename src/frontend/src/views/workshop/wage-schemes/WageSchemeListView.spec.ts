import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WageSchemeListView from './WageSchemeListView.vue'

const api = vi.hoisted(() => ({ context: vi.fn(), list: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => router }))
vi.mock('@/api/workshopReporting', () => ({
  fetchReportingContext: api.context,
  fetchWageSchemes: api.list,
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  api.context.mockResolvedValue({ workshops: [{ id: 'workshop-1', name: '金工车间' }] })
  api.list.mockResolvedValue({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } })
})

afterEach(() => vi.restoreAllMocks())

function selectByTestId(wrapper: ReturnType<typeof mount>, testId: string) {
  const select = wrapper.findAllComponents(ElSelect).find(item => item.attributes('data-testid') === testId)
  if (!select) throw new Error(`找不到下拉框：${testId}`)
  return select
}

describe('工价方案列表原型列结构', () => {
  it('每项信息独立成列且不展示版本', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/wage-schemes/WageSchemeListView.vue'),
      'utf8',
    )

    const labels = Array.from(source.matchAll(/<ElTableColumn[^>]*label="([^"]+)"/g))
      .map(match => match[1])

    expect(labels).toEqual([
      '方案编号', '生产任务单', '产品信息', '所属车间', '所属工艺',
      '类型', '工价合计', '审批状态', '更新日期', '操作',
    ])
    expect(source).not.toContain('wr-two-line')
    expect(source).not.toContain('label="版本"')
    expect(source).toContain('class="wr-status-tag"')
    const styles = readFileSync(resolve(process.cwd(), 'src/styles/workshopReporting.scss'), 'utf8')
    expect(styles).toMatch(/\.wr-list-card \.el-button\.is-link \{ color: #1685ed; \}/)
  })

  it('包含原型中的完整筛选区和列表工具栏', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/wage-schemes/WageSchemeListView.vue'),
      'utf8',
    )

    expect(source).toContain('placeholder="搜索方案号、订单号或产品"')
    expect(source).toContain('placeholder="车间：全部"')
    expect(source).toContain('placeholder="审批状态：全部"')
    expect(source).toContain('placeholder="类型：全部"')
    expect(source).toContain('更多筛选')
    expect(source).toContain('工价方案记录')
    expect(source).toContain('更新时间 ↓')
    expect(source).toContain('刷新')
    expect(source).toContain('workshop_id: workshopId.value || undefined')
    expect(source).toContain('scheme_type: schemeTypeFilter.value || undefined')
    expect(source).toContain('updated_from: updatedRangeApplied.value?.[0] || undefined')
    expect(source).toContain('updatedRangeApplied.value = updatedRangeDraft.value ? [...updatedRangeDraft.value] : null')
    expect(source).toContain('ordering: ordering.value')
  })

  it('金额最多显示三位小数并去掉末尾零', async () => {
    api.list.mockResolvedValueOnce({
      data: [{
        id: 'scheme-1', scheme_number: 'GJ-1', declared_total: '0.6000', status: 'APPROVED',
        status_display: '已批准', parent_scheme: null, can_create_change: true,
        production_task: { task_number: 'SC-1' }, product: { number: 'P-1', name: '产品', specification: '' },
        workshop: { name: '金工车间' }, crafts: [{ name: '管材加工' }], updated_at: '2026-09-28T07:20:00+08:00',
      }],
      meta: { page: 1, page_size: 20, total: 1, total_pages: 1 },
    })
    const wrapper = mount(WageSchemeListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.find('td.wr-money').text()).toBe('¥0.6')
    wrapper.unmount()
  })

  it('筛选和排序交互会把真实参数传给列表接口', async () => {
    const wrapper = mount(WageSchemeListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: '-updated_at' }))

    wrapper.findComponent({ name: 'ElPopover' }).vm.$emit('update:visible', true)
    await nextTick()
    const datePicker = wrapper.findComponent({ name: 'ElDatePicker' })
    expect(datePicker.exists()).toBe(true)
    datePicker.vm.$emit('update:modelValue', ['2026-09-01', '2026-09-30'])
    await nextTick()

    const workshop = selectByTestId(wrapper, 'wage-workshop-filter')
    workshop.vm.$emit('update:modelValue', 'workshop-1')
    await nextTick()
    workshop.vm.$emit('change', 'workshop-1')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({
      workshop_id: 'workshop-1',
      updated_from: undefined,
      updated_to: undefined,
    }))

    const type = selectByTestId(wrapper, 'wage-type-filter')
    type.vm.$emit('update:modelValue', 'CHANGE')
    await nextTick()
    type.vm.$emit('change', 'CHANGE')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ scheme_type: 'CHANGE' }))

    const sort = selectByTestId(wrapper, 'wage-ordering')
    sort.vm.$emit('update:modelValue', 'updated_at')
    await nextTick()
    sort.vm.$emit('change', 'updated_at')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'updated_at' }))

    wrapper.unmount()
  })
})
