import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { previewBomTubeCalculation } from '@/api/boms'
import { blankLine } from './bomEditorHelpers'
import { useTubeFormulaPreview } from './useTubeFormulaPreview'

vi.mock('@/api/boms', () => ({ previewBomTubeCalculation: vi.fn() }))
const result = { formula_version: '2026-10-29T01:00:00+00:00', coating_unit_area_sqm: '0.0314', purchase_unit_weight_kg: '0.2343', long_material_unit_weight_kg: '2.3663' }
const scopes: ReturnType<typeof effectScope>[] = []
function setup() {
  const scope = effectScope()
  scopes.push(scope)
  const draft = ref({ ...blankLine('根'), tube_shape: '圆管', tube_diameter: '20', tube_thickness: '1', length_value: '500', tube_cut_piece_count: '10' })
  const active = ref(false)
  const state = scope.run(() => useTubeFormulaPreview(draft, active, (_error, fallback) => fallback))!
  active.value = true
  return { draft, active, state }
}
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.clearAllMocks() })

describe('管材公式预览', () => {
  it('计算单支数值并标记应用时由后端重算，数量不进入请求', async () => {
    vi.mocked(previewBomTubeCalculation).mockResolvedValue(result)
    const { draft, state } = setup()
    expect(await state.calculate()).toBe(true)
    expect(draft.value.coating_unit_area_sqm).toBe('0.0314')
    expect(draft.value.purchase_unit_weight_kg).toBe('0.2343')
    expect(draft.value.recalculate_tube_metrics).toBe(true)
    expect(draft.value.expected_tube_formula_version).toBe(result.formula_version)
    draft.value.unit_consumption = '20'
    await nextTick()
    expect(await state.calculate()).toBe(true)
    expect(previewBomTubeCalculation).toHaveBeenCalledTimes(1)
    expect(previewBomTubeCalculation).toHaveBeenCalledWith({ tube_shape: '圆管', tube_diameter: '20', tube_thickness: '1', length_value: '500', tube_cut_piece_count: '10' })
  })

  it('输入变化后迟到的旧请求不能覆盖新结果', async () => {
    let resolveOld!: (value: typeof result) => void
    vi.mocked(previewBomTubeCalculation).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const { draft, state } = setup()
    const first = state.calculate()
    draft.value.length_value = '1000'
    vi.mocked(previewBomTubeCalculation).mockResolvedValueOnce({ ...result, purchase_unit_weight_kg: '0.4686' })
    expect(await state.calculate()).toBe(true)
    resolveOld(result)
    await first
    expect(draft.value.purchase_unit_weight_kg).toBe('0.4686')
  })

  it('计算失败进入手填，应用时不重试覆盖手填值，关闭后不再回填', async () => {
    vi.mocked(previewBomTubeCalculation).mockRejectedValue(new Error('400'))
    const { draft, active, state } = setup()
    expect(await state.calculate()).toBe(true)
    expect(state.error.value).toContain('计算失败')
    expect(draft.value.manual_tube_metrics).toBe(true)
    expect(state.readonly.value).toBe(false)
    expect(draft.value.purchase_unit_weight_kg).toBe('')
    expect(draft.value.recalculate_tube_metrics).toBe(false)
    draft.value.coating_unit_area_sqm = '0.1234'
    draft.value.purchase_unit_weight_kg = '0.5678'
    expect(await state.calculate()).toBe(true)
    expect(previewBomTubeCalculation).toHaveBeenCalledTimes(1)
    expect(draft.value.purchase_unit_weight_kg).toBe('0.5678')
    active.value = false
    await flushPromises()
    expect(state.loading.value).toBe(false)
  })

  it('重开失败的已保存手填行保留原值，参数变化后计算成功恢复只读', async () => {
    vi.mocked(previewBomTubeCalculation).mockRejectedValueOnce(new Error('400'))
    const { draft, active, state } = setup()
    active.value = false
    draft.value.manual_tube_metrics = true
    draft.value.coating_unit_area_sqm = '0.12'
    draft.value.purchase_unit_weight_kg = '0.34'
    active.value = true
    expect(await state.calculate()).toBe(true)
    expect(draft.value.purchase_unit_weight_kg).toBe('0.34')
    vi.mocked(previewBomTubeCalculation).mockResolvedValueOnce(result)
    draft.value.length_value = '501'
    expect(await state.calculate()).toBe(true)
    expect(state.readonly.value).toBe(true)
    expect(draft.value.manual_tube_metrics).toBe(false)
    expect(draft.value.purchase_unit_weight_kg).toBe(result.purchase_unit_weight_kg)
  })

  it('未配置的历史管型保留手填能力，不用其他形状的公式', async () => {
    const { draft, state } = setup()
    draft.value.tube_shape = 'D形管'
    draft.value.coating_unit_area_sqm = '0.8'
    draft.value.purchase_unit_weight_kg = '0.9'
    expect(await state.calculate()).toBe(true)
    expect(state.supported.value).toBe(false)
    expect(draft.value.purchase_unit_weight_kg).toBe('0.9')
    expect(draft.value.recalculate_tube_metrics).toBe(false)
    expect(previewBomTubeCalculation).not.toHaveBeenCalled()
  })
})
