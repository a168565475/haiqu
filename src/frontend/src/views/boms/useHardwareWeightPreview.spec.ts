import { effectScope, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { previewBomHardwareWeight } from '@/api/boms'
import type { BomLine, BomLineInput } from '@/types/bom'
import { blankLine, editableLine } from './bomEditorHelpers'
import { calculateHardwareWeight, initializeHardwareWeight, selectHardwareWeight, setManualHardwareWeight, useHardwareWeightPreview } from './useHardwareWeightPreview'

vi.mock('@/api/boms', () => ({ previewBomHardwareWeight: vi.fn() }))
const result = { unit_material_weight_kg: '0.00312345', unit_weight_g: '3.12345', calculation_snapshot: { formula_version: '1' } }
const scopes: ReturnType<typeof effectScope>[] = []
function line(values: Partial<BomLineInput> = {}): BomLineInput {
  return { ...blankLine('个'), part_name: '铆钉', material: 'Q235', specification: 'Φ4×35', ...values }
}
function setup(values: Partial<BomLineInput> = {}) {
  const scope = effectScope()
  scopes.push(scope)
  const draft = ref<BomLineInput | null>(line(values))
  const active = ref(false)
  const state = scope.run(() => useHardwareWeightPreview(draft, active, (error, fallback) => error instanceof Error ? error.message : fallback))!
  active.value = true
  return { draft, active, state }
}
beforeEach(() => { vi.mocked(previewBomHardwareWeight).mockReset().mockResolvedValue(result) })
afterEach(() => scopes.splice(0).forEach(scope => scope.stop()))

describe('五金单重计算', () => {
  it('新钢制铆钉自动预览，保持足够小数位，数量不参与请求', async () => {
    const { draft, state } = setup({ unit_consumption: '12' })
    expect(draft.value!.hardware_weight_mode).toBe('AUTO')
    expect(await state.calculate()).toBe(true)
    expect(draft.value!.unit_material_weight_kg).toBe('0.00312345')
    expect(previewBomHardwareWeight).toHaveBeenCalledWith({ kind: 'RIVET_GB873_STEEL', material: 'Q235', specification: 'Φ4×35' })
    draft.value!.unit_consumption = '20'
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenCalledTimes(1)
  })

  it('65Mn 铆钉按钢制类型自动启用', async () => {
    const { draft, state } = setup({ material: '65Mn', specification: 'Φ4-40' })
    expect(draft.value!.hardware_weight_mode).toBe('AUTO')
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenCalledWith({ kind: 'RIVET_GB873_STEEL', material: '65Mn', specification: 'Φ4-40' })
  })

  it('选择品名属性后同步 BOM 行字段和重量计算参数', async () => {
    const { draft, state } = setup({
      material: '旧材质',
      specification: '旧规格',
      material_selection: {
        catalog_version: 'v1',
        scope: 'BASE',
        processing_state: 'RAW',
        attributes: { material: '65Mn', specification: 'Φ4-40' },
      },
    })
    selectHardwareWeight(draft.value!, 'RIVET_GB873_STEEL')
    expect(draft.value).toMatchObject({ material: '65Mn', specification: 'Φ4-40' })
    expect(draft.value!.hardware_weight_input).toMatchObject({
      kind: 'RIVET_GB873_STEEL', material: '65Mn', specification: 'Φ4-40',
    })
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenCalledWith({
      kind: 'RIVET_GB873_STEEL', material: '65Mn', specification: 'Φ4-40',
    })
  })

  it.each([
    ['铆钉', 'RIVET_GB873_STEEL', 'Φ4-40', '4×40'],
    ['平垫片', 'PLAIN_WASHER', 'M6', '12×6.4×1.6'],
  ] as const)('目录多个规格属性全部参与%s预览，与保存相同', async (partName, kind, specification, size) => {
    const { draft, state } = setup({
      part_name: partName,
      material_selection: {
        catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW',
        attributes: { material: '65Mn', specification, size },
      },
    })
    selectHardwareWeight(draft.value!, kind)
    expect(draft.value!.specification).toBe(`${specification} / ${size}`)
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenLastCalledWith({
      kind, material: '65Mn', specification: `${specification} / ${size}`,
    })
    draft.value!.material_selection!.attributes.size = '不同尺寸'
    vi.mocked(previewBomHardwareWeight).mockRejectedValueOnce(new Error('规格属性中的尺寸不一致'))
    expect(await state.calculate()).toBe(false)
    expect(state.error.value).toContain('尺寸不一致')
    expect(previewBomHardwareWeight).toHaveBeenLastCalledWith({
      kind, material: '65Mn', specification: `${specification} / 不同尺寸`,
    })
  })

  it('目录规格变化时清除旧铆钉尺寸，避免新规格被旧参数拦截', async () => {
    const { draft, state } = setup({
      material: '旧材质',
      specification: '旧规格',
      material_selection: {
        catalog_version: 'v1',
        scope: 'BASE',
        processing_state: 'RAW',
        attributes: { material: '65Mn', specification: 'Φ4-40' },
      },
      hardware_weight_mode: 'AUTO',
      hardware_weight_input: {
        kind: 'RIVET_GB873_STEEL', material: '旧材质', specification: '旧规格', diameter_mm: '4', length_mm: '35',
      },
    })
    expect(draft.value).toMatchObject({ material: '65Mn', specification: 'Φ4-40' })
    expect(draft.value!.hardware_weight_input).toEqual({
      kind: 'RIVET_GB873_STEEL', material: '65Mn', specification: 'Φ4-40',
    })
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenCalledWith({
      kind: 'RIVET_GB873_STEEL', material: '65Mn', specification: 'Φ4-40',
    })
  })

  it.each([{ id: 'saved' }, { unit_material_weight_kg: '0.002' }, { hardware_weight_mode: 'MANUAL' as const }])('不主动启用已有行或手填重量 %j', async values => {
    const { draft, state } = setup(values)
    expect(await state.calculate()).toBe(true)
    expect(draft.value!.hardware_weight_mode).not.toBe('AUTO')
    expect(previewBomHardwareWeight).not.toHaveBeenCalled()
  })

  it.each(['抽芯铆钉', '空心铆钉', '实心铆钉', '沉头铆钉', '弹簧垫片', '波形垫圈'])('不套用不支持类型：%s', name => {
    const value = line({ part_name: name })
    initializeHardwareWeight(value)
    expect(value.hardware_weight_mode).not.toBe('AUTO')
  })

  it('垫片不拆猜三数字，明确参数与未知材质密度直接传给后端', async () => {
    const value = line({ part_name: '平垫片', material: '客户合金', specification: '12×6×1' })
    initializeHardwareWeight(value)
    Object.assign(value.hardware_weight_input!, { outer_diameter_mm: '12', inner_diameter_mm: '6', thickness_mm: '1', density_g_cm3: '8.2' })
    expect(await calculateHardwareWeight(value)).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenCalledWith({ kind: 'PLAIN_WASHER', material: '客户合金', specification: '12×6×1', outer_diameter_mm: '12', inner_diameter_mm: '6', thickness_mm: '1', density_g_cm3: '8.2' })
  })

  it('迟到结果不能覆盖新规格或新行', async () => {
    let resolveOld!: (value: typeof result) => void
    vi.mocked(previewBomHardwareWeight).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const { draft, state } = setup()
    const pending = state.calculate()
    draft.value!.specification = 'Φ4×40'
    vi.mocked(previewBomHardwareWeight).mockResolvedValueOnce({ ...result, unit_material_weight_kg: '0.004' })
    expect(await state.calculate()).toBe(true)
    resolveOld(result)
    expect(await pending).toBe(false)
    expect(draft.value!.unit_material_weight_kg).toBe('0.004')
  })

  it('手工修改立即退出自动，待返回结果不能覆盖，改规格提示核对', async () => {
    let resolveOld!: (value: typeof result) => void
    vi.mocked(previewBomHardwareWeight).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const { draft, state } = setup()
    const pending = state.calculate()
    draft.value!.unit_material_weight_kg = '0.007'
    setManualHardwareWeight(draft.value!)
    resolveOld(result)
    expect(await pending).toBe(false)
    draft.value!.specification = 'Φ5×35'
    expect(draft.value!.unit_material_weight_kg).toBe('0.007')
    expect(state.manualNotice.value).toContain('核对手填重量')
    expect(await state.calculate()).toBe(true)
  })

  it('自动计算错误不填零、不覆盖原值，保持失败阻止应用', async () => {
    const { draft, state } = setup({ unit_material_weight_kg: '0.005' })
    selectHardwareWeight(draft.value!, 'PLAIN_WASHER')
    vi.mocked(previewBomHardwareWeight).mockRejectedValue(new Error('请填写外径、内径、厚度'))
    expect(await state.calculate()).toBe(false)
    expect(state.error.value).toContain('外径')
    expect(draft.value!.unit_material_weight_kg).toBe('0.005')
    expect(draft.value!.hardware_weight_mode).toBe('AUTO')
  })

  it('重开已保存自动行不刷新公式，修改规格后重新计算并清除旧显式尺寸', async () => {
    const saved = editableLine({ ...line(), id: 'saved', hardware_weight_mode: 'AUTO', unit_material_weight_kg: '0.006',
      hardware_weight_input: { kind: 'RIVET_GB873_STEEL', material: 'Q235', specification: 'Φ4×35', diameter_mm: '4', length_mm: '35' }, hardware_weight_snapshot: { version: 'old' } } as unknown as BomLine)
    const { draft, state } = setup(saved)
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).not.toHaveBeenCalled()
    expect(draft.value!.unit_material_weight_kg).toBe('0.006')
    draft.value!.specification = 'Φ5×40'
    expect(draft.value!.hardware_weight_input?.diameter_mm).toBeUndefined()
    expect(await state.calculate()).toBe(true)
    expect(previewBomHardwareWeight).toHaveBeenCalledTimes(1)
    draft.value!.specification = 'Φ4×35'
    Object.assign(draft.value!.hardware_weight_input!, { diameter_mm: '4', length_mm: '35' })
    expect(await state.calculate()).toBe(true)
    expect(draft.value!.unit_material_weight_kg).toBe('0.006')
    expect(previewBomHardwareWeight).toHaveBeenCalledTimes(1)
  })

  it('关闭或切换行时不回填旧请求', async () => {
    let resolveOld!: (value: typeof result) => void
    vi.mocked(previewBomHardwareWeight).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const { draft, active, state } = setup()
    const pending = state.calculate()
    const previous = draft.value!
    active.value = false
    draft.value = line({ unit_material_weight_kg: '0.009' })
    resolveOld(result)
    expect(await pending).toBe(false)
    expect(previous.unit_material_weight_kg).toBe('')
    expect(draft.value.unit_material_weight_kg).toBe('0.009')
  })
})
