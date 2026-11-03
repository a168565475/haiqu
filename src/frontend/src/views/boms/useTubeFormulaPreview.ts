import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import { previewBomTubeCalculation } from '@/api/boms'
import type { BomLineInput, TubeCalculationInput } from '@/types/bom'

function inputs(line: BomLineInput): TubeCalculationInput {
  return {
    tube_shape: line.tube_shape, tube_diameter: line.tube_diameter, tube_thickness: line.tube_thickness,
    length_value: line.length_value, tube_cut_piece_count: line.tube_cut_piece_count,
  }
}

export function useTubeFormulaPreview(
  draft: Ref<BomLineInput | null>, active: Ref<boolean>, errorMessage: (error: unknown, fallback: string) => string,
) {
  const loading = ref(false)
  const error = ref('')
  const supported = computed(() => ['圆', '圆管', '方', '方管', '矩形', '矩形管', '椭圆', '椭圆管', '扁圆', '扁圆管'].includes(draft.value?.tube_shape.trim() || ''))
  const readonly = computed(() => supported.value && (loading.value || !draft.value?.manual_tube_metrics))
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: { key: string; promise: Promise<boolean> } | null = null
  let successfulKey = ''
  let failedKey = ''

  function useManualValues(line: BomLineInput, key: string, message: string) {
    error.value = message
    failedKey = key
    line.manual_tube_metrics = true
    line.recalculate_tube_metrics = false
    line.expected_tube_formula_version = undefined
    line.tube_calculation_preview = undefined
  }

  async function calculate(): Promise<boolean> {
    if (timer) clearTimeout(timer)
    const line = draft.value
    if (!active.value || !line) return false
    if (!supported.value) return true
    const payload = inputs(line)
    const key = JSON.stringify(payload)
    if (failedKey === key && line.manual_tube_metrics) return true
    if (successfulKey === key && line.tube_calculation_preview) return true
    if (pending?.key === key) return pending.promise
    if (![payload.tube_shape, payload.tube_diameter, payload.tube_thickness, payload.length_value].every(value => String(value ?? '').trim())) {
      useManualValues(line, key, '请补齐形状、规格、厚度和切割长度后计算。')
      loading.value = false
      return true
    }
    const requestGeneration = ++generation
    loading.value = true
    error.value = ''
    const promise = (async () => {
      try {
        const result = await previewBomTubeCalculation(payload)
        if (requestGeneration !== generation || line !== draft.value || key !== JSON.stringify(inputs(line)) || !active.value) return false
        line.coating_unit_area_sqm = result.coating_unit_area_sqm
        line.purchase_unit_weight_kg = result.purchase_unit_weight_kg
        line.tube_calculation_preview = result
        line.manual_tube_metrics = false
        line.recalculate_tube_metrics = true
        line.expected_tube_formula_version = result.formula_version
        successfulKey = key
        return true
      } catch (reason) {
        if (requestGeneration !== generation || line !== draft.value || key !== JSON.stringify(inputs(line)) || !active.value) return false
        useManualValues(line, key, errorMessage(reason, '管材公式计算失败，请手动填写。'))
        return true
      } finally {
        if (requestGeneration === generation) {
          loading.value = false
          pending = null
        }
      }
    })()
    pending = { key, promise }
    return promise
  }

  watch(() => [active.value, draft.value, draft.value && JSON.stringify(inputs(draft.value))], (_current, previous) => {
    ++generation
    if (timer) clearTimeout(timer)
    pending = null
    successfulKey = ''
    failedKey = ''
    loading.value = false
    error.value = ''
    if (!active.value || !draft.value) return
    const preserveManualValues = draft.value.manual_tube_metrics && (!previous?.[0] || previous[1] !== draft.value)
    draft.value.tube_calculation_preview = undefined
    draft.value.recalculate_tube_metrics = false
    draft.value.expected_tube_formula_version = undefined
    draft.value.manual_tube_metrics = false
    if (!supported.value) return
    if (!preserveManualValues) {
      draft.value.coating_unit_area_sqm = ''
      draft.value.purchase_unit_weight_kg = ''
    }
    loading.value = true
    timer = setTimeout(() => { void calculate() }, 250)
  }, { flush: 'sync' })

  onScopeDispose(() => {
    ++generation
    if (timer) clearTimeout(timer)
  })
  return { loading, error, supported, readonly, calculate }
}
