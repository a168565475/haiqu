import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { previewBomHardwareWeight } from '@/api/boms'
import type { BomLineInput, HardwareWeightInput, HardwareWeightKind } from '@/types/bom'

// 与后端目录选料保存的规格顺序保持一致，所有属性都参与尺寸冲突检查。
const HARDWARE_SPECIFICATION_KEYS = ['fabric_spec', 'specification', 'section_size', 'size', 'model', 'width'] as const

function selectedHardwareAttributes(line: BomLineInput): Record<string, string> {
  return (line.material_selection ?? line.material_selection_snapshot)?.attributes ?? {}
}

export function hardwareWeightMaterial(line: BomLineInput): string {
  return selectedHardwareAttributes(line).material?.trim() || line.material.trim()
}

export function hardwareWeightSpecification(line: BomLineInput): string {
  const attributes = selectedHardwareAttributes(line)
  return HARDWARE_SPECIFICATION_KEYS.map(key => attributes[key]?.trim()).filter(Boolean).join(' / ') || line.specification.trim()
}

export function hardwareWeightInput(line: BomLineInput): HardwareWeightInput | undefined {
  if (!line.hardware_weight_input) return undefined
  return {
    ...line.hardware_weight_input,
    material: hardwareWeightMaterial(line),
    specification: hardwareWeightSpecification(line),
  }
}

function synchronizeHardwareCatalogFields(line: BomLineInput) {
  const attributes = selectedHardwareAttributes(line)
  const material = attributes.material?.trim()
  const specification = HARDWARE_SPECIFICATION_KEYS.map(key => attributes[key]?.trim()).filter(Boolean).join(' / ')
  if (material && line.material !== material) line.material = material
  if (specification && line.specification !== specification) line.specification = specification
}

function synchronizeHardwareWeightInput(line: BomLineInput) {
  synchronizeHardwareCatalogFields(line)
  const input = hardwareWeightInput(line)
  if (!input || !line.hardware_weight_input
    || (line.hardware_weight_input.material === input.material && line.hardware_weight_input.specification === input.specification)) return
  line.hardware_weight_input = {
    kind: input.kind,
    material: input.material,
    specification: input.specification,
  }
}

export function hardwareWeightKey(line: BomLineInput): string {
  return JSON.stringify(hardwareWeightInput(line)) || ''
}

export function setManualHardwareWeight(line: BomLineInput) {
  line.hardware_weight_mode = 'MANUAL'
  line.hardware_weight_preview = undefined
  line.hardware_weight_saved = undefined
}

export function selectHardwareWeight(line: BomLineInput, kind: HardwareWeightKind | 'MANUAL') {
  if (kind === 'MANUAL') {
    setManualHardwareWeight(line)
    return
  }
  synchronizeHardwareCatalogFields(line)
  line.hardware_weight_mode = 'AUTO'
  line.hardware_weight_input = { kind, material: hardwareWeightMaterial(line), specification: hardwareWeightSpecification(line) }
  line.hardware_weight_preview = undefined
  line.hardware_weight_saved = undefined
}

export function initializeHardwareWeight(line: BomLineInput) {
  if (line.id || line.hardware_weight_mode || String(line.unit_material_weight_kg || '').trim()
    || !line.material?.trim() || !line.specification?.trim()) return
  const name = line.part_name || ''
  if (/铆钉/.test(name) && !/抽芯|击芯|管状|实心|沉头|半圆头|扁平头|大扁圆|平头/.test(name)
    && !/空心/.test(name.replace('半空心', ''))
    && /钢|铁|65Mn|65锰|Q195|Q215|Q235|Q345|Q355|SPCC|SWRCH/i.test(line.material) && !/不锈/.test(line.material)) {
    selectHardwareWeight(line, 'RIVET_GB873_STEEL')
  } else if (/平垫|垫片|垫圈/.test(name) && !/弹|波|碟|齿|锥|开口|异形|方/.test(name)) {
    selectHardwareWeight(line, 'PLAIN_WASHER')
  }
}

/** 单行预览结果只可回填到参数、模式和手工重量都未变化的原行。 */
export async function calculateHardwareWeight(line: BomLineInput, stillActive: () => boolean = () => true): Promise<boolean> {
  if (line.hardware_weight_mode !== 'AUTO') return true
  const input = hardwareWeightInput(line)
  if (!input) throw new Error('请选择五金重量计算方式。')
  const key = hardwareWeightKey(line)
  if (line.hardware_weight_saved?.input_key === key) {
    line.unit_material_weight_kg = line.hardware_weight_saved.unit_material_weight_kg
    return true
  }
  if (line.hardware_weight_preview?.input_key === key
    && line.hardware_weight_preview.unit_material_weight_kg === line.unit_material_weight_kg) return true
  const originalWeight = line.unit_material_weight_kg
  const result = await previewBomHardwareWeight(input)
  if (!stillActive() || line.hardware_weight_mode !== 'AUTO' || hardwareWeightKey(line) !== key) return false
  if (line.unit_material_weight_kg !== originalWeight) {
    return line.hardware_weight_preview?.input_key === key
      && line.hardware_weight_preview.unit_material_weight_kg === line.unit_material_weight_kg
  }
  line.hardware_weight_preview = { ...result, input_key: key }
  line.unit_material_weight_kg = result.unit_material_weight_kg
  return true
}

export function useHardwareWeightPreview(
  draft: Ref<BomLineInput | null>, active: Ref<boolean>, errorMessage: (error: unknown, fallback: string) => string,
) {
  const loading = ref(false)
  const error = ref('')
  const manualNotice = ref('')
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: { line: BomLineInput; key: string; promise: Promise<boolean> } | null = null

  async function calculate(): Promise<boolean> {
    if (timer) clearTimeout(timer)
    const line = draft.value
    if (!active.value || !line) return false
    if (line.hardware_weight_mode !== 'AUTO') return true
    const key = hardwareWeightKey(line)
    if (pending?.line === line && pending.key === key) return pending.promise
    const requestGeneration = ++generation
    loading.value = true
    error.value = ''
    const promise = (async () => {
      try {
        return await calculateHardwareWeight(line, () => requestGeneration === generation && line === draft.value && active.value)
      } catch (reason) {
        if (requestGeneration === generation && line === draft.value && active.value) {
          error.value = errorMessage(reason, '重量计算失败，请核对参数，或切换手填重量。')
        }
        return false
      } finally {
        if (requestGeneration === generation) {
          loading.value = false
          pending = null
        }
      }
    })()
    pending = { line, key, promise }
    return promise
  }

  watch(() => [active.value, draft.value, draft.value?.part_name, draft.value?.material, draft.value?.specification,
    draft.value?.hardware_weight_mode, draft.value ? hardwareWeightKey(draft.value) : ''], (_current, previous) => {
    ++generation
    if (timer) clearTimeout(timer)
    pending = null
    loading.value = false
    error.value = ''
    const line = draft.value
    if (!active.value || !line) return
    if (line.hardware_weight_mode === 'AUTO' && line.hardware_weight_input) synchronizeHardwareWeightInput(line)
    const sameLine = previous?.[0] && previous[1] === line
    if (!sameLine) manualNotice.value = ''
    if (sameLine && line.hardware_weight_mode === 'AUTO' && line.hardware_weight_input
      && (previous[3] !== line.material || previous[4] !== line.specification)) {
      line.hardware_weight_input = {
        kind: line.hardware_weight_input.kind,
        material: hardwareWeightMaterial(line),
        specification: hardwareWeightSpecification(line),
      }
      return
    }
    if (sameLine && (previous[3] !== line.material || previous[4] !== line.specification)
      && line.hardware_weight_mode !== 'AUTO' && line.unit_material_weight_kg) {
      manualNotice.value = '材质或规格已变化，请核对手填重量。'
    }
    const previousMode = line.hardware_weight_mode
    initializeHardwareWeight(line)
    if (previousMode !== line.hardware_weight_mode) return
    if (line.hardware_weight_mode !== 'AUTO') return
    line.hardware_weight_preview = undefined
    loading.value = true
    timer = setTimeout(() => { void calculate() }, 250)
  }, { flush: 'sync' })

  onScopeDispose(() => {
    ++generation
    if (timer) clearTimeout(timer)
  })
  return { loading, error, manualNotice, calculate }
}
