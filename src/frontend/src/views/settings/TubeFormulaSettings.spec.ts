import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TubeFormulaSettings from './TubeFormulaSettings.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { TubeCalculationFormula } from '@/types/tubeFormulas'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), update: vi.fn() }))
vi.mock('@/api/tubeFormulas', () => ({
  fetchTubeFormulas: api.list, fetchTubeFormula: api.detail, updateTubeFormula: api.update,
}))

const formulas: TubeCalculationFormula[] = [
  { id: 'round', group_key: 'ROUND', area_expression: '直径*3.14*管材长度/1000000', weight_expression: '(直径-壁厚)*壁厚*3.14*7.854*管材长度/1000000', updated_at: '2026-10-29T01:00:00Z' },
  { id: 'rect', group_key: 'RECTANGULAR', area_expression: '(截面长+截面宽)*2*管材长度/1000000', weight_expression: '((截面长+截面宽)*2/3.14-壁厚)*壁厚*3.14*7.854*管材长度/1000000', updated_at: '2026-10-29T01:00:00Z' },
  { id: 'oval', group_key: 'OVAL', area_expression: '截面长/2*截面宽/2*3.14*管材长度/1000000', weight_expression: '(截面长*截面宽-(截面长-2*壁厚)*(截面宽-2*壁厚))/4*3.14*7.854*管材长度/1000000', updated_at: '2026-10-29T01:00:00Z' },
]

const mounted: VueWrapper[] = []
function create(canEdit = true) {
  const wrapper = mount(TubeFormulaSettings, {
    props: { canEdit }, attachTo: document.body,
    global: { plugins: [ElementPlus], stubs: { teleport: true } },
  })
  mounted.push(wrapper)
  return wrapper
}

async function editRound(wrapper: VueWrapper) {
  await flushPromises()
  await wrapper.get('[data-group="ROUND"] button').trigger('click')
  await flushPromises()
}

function saveButton(wrapper: VueWrapper) {
  return wrapper.findAll('button').find(button => button.text() === '保存公式')!
}

describe('TubeFormulaSettings', () => {
  beforeEach(() => {
    api.list.mockReset().mockResolvedValue(structuredClone(formulas))
    api.detail.mockReset().mockResolvedValue({ data: structuredClone(formulas[0]), etag: '"formula-v1"' })
    api.update.mockReset().mockImplementation((id, payload) => Promise.resolve({
      data: { ...formulas.find(row => row.id === id), ...payload }, etag: '"formula-v2"',
    }))
  })
  afterEach(() => {
    mounted.splice(0).forEach(wrapper => wrapper.unmount())
    document.body.innerHTML = ''
  })

  it('显示三组别名共用公式和单支口径，保持指定的椭圆面积表达式', async () => {
    const wrapper = create()
    await flushPromises()
    expect(wrapper.findAll('.formula-row')).toHaveLength(3)
    expect(wrapper.text()).toContain('方管 / 矩形管')
    expect(wrapper.text()).toContain('椭圆管 / 扁圆管')
    expect(wrapper.text()).toContain('公式不乘数量')
    expect(wrapper.text()).toContain(formulas[2].area_expression)
    expect(wrapper.text()).not.toContain('新增')
    expect(wrapper.text()).not.toContain('停用')
  })

  it('只读权限可查看公式但不显示编辑入口', async () => {
    const wrapper = create(false)
    await flushPromises()
    expect(wrapper.findAll('.formula-row')).toHaveLength(3)
    expect(wrapper.findAll('.formula-row button')).toHaveLength(0)
    expect(api.detail).not.toHaveBeenCalled()
  })

  it('编辑取得最新版本并携带ETag保存，成功后更新可见公式', async () => {
    const wrapper = create()
    await editRound(wrapper)
    expect(wrapper.vm.canClose()).toBe(false)
    expect(api.detail).toHaveBeenCalledWith('round')
    await wrapper.get('textarea[aria-label="喷塑单支面积公式"]').setValue('直径*3.14*管材长度/900000')
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledWith('round', {
      area_expression: '直径*3.14*管材长度/900000', weight_expression: formulas[0].weight_expression,
    }, '"formula-v1"')
    expect(wrapper.get('[data-group="ROUND"]').text()).toContain('/900000')
    expect(wrapper.findComponent(AppWindowDialog).props('modelValue')).toBe(false)
    expect(wrapper.vm.canClose()).toBe(true)
  })

  it('空公式阻止保存并保留编辑窗口', async () => {
    const wrapper = create()
    await editRound(wrapper)
    await wrapper.get('textarea[aria-label="喷塑单支面积公式"]').setValue('  ')
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('喷塑面积公式和重量公式都不能为空')
    expect(api.update).not.toHaveBeenCalled()
    expect(wrapper.findComponent(AppWindowDialog).props('modelValue')).toBe(true)
  })

  it('公式输入长度与后端500字符上限一致', async () => {
    const wrapper = create()
    await editRound(wrapper)
    expect(wrapper.get('textarea[aria-label="喷塑单支面积公式"]').attributes('maxlength')).toBe('500')
    expect(wrapper.get('textarea[aria-label="单支重量公式"]').attributes('maxlength')).toBe('500')
  })

  it('后台公式校验错误显示原原因且不修改已保存列表', async () => {
    api.update.mockRejectedValueOnce({ response: { status: 400, data: { error: { field_errors: { area_expression: ['不支持变量：数量'] } } } } })
    const wrapper = create()
    await editRound(wrapper)
    await wrapper.get('textarea[aria-label="喷塑单支面积公式"]').setValue('直径*数量')
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('不支持变量：数量')
    expect(wrapper.get('[data-group="ROUND"]').text()).toContain(formulas[0].area_expression)
    expect((wrapper.get('textarea[aria-label="喷塑单支面积公式"]').element as HTMLTextAreaElement).value).toBe('直径*数量')
  })

  it('并发冲突保留输入并提示重新获取版本', async () => {
    api.update.mockRejectedValueOnce({ response: { status: 412 } })
    const wrapper = create()
    await editRound(wrapper)
    await wrapper.get('textarea[aria-label="单支重量公式"]').setValue('管材长度/1000')
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('公式已被其他人修改')
    expect(wrapper.text()).toContain('本次输入已保留')
    expect((wrapper.get('textarea[aria-label="单支重量公式"]').element as HTMLTextAreaElement).value).toBe('管材长度/1000')
    expect(wrapper.findComponent(AppWindowDialog).props('modelValue')).toBe(true)
  })

  it('加载失败显示错误，可刷新恢复', async () => {
    api.list.mockRejectedValueOnce(new Error('network'))
    const wrapper = create()
    await flushPromises()
    expect(wrapper.text()).toContain('计算公式加载失败，请重试')
    expect(wrapper.findAll('.formula-row')).toHaveLength(0)
    await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.formula-row')).toHaveLength(3)
    expect(wrapper.text()).not.toContain('计算公式加载失败')
  })

  it('缺少一组真实配置时显示错误，不以默认公式冒充', async () => {
    api.list.mockResolvedValueOnce(formulas.slice(0, 2))
    const wrapper = create()
    await flushPromises()
    expect(wrapper.text()).toContain('管材公式配置不完整')
    expect(wrapper.findAll('.formula-row')).toHaveLength(0)
  })
})
