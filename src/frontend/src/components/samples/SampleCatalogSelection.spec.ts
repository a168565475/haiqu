import { shallowMount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import Selection from './SampleCatalogSelection.vue'
import Panel from '@/components/products/MaterialSelectionPanel.vue'
import type { SampleMaterialLine } from '@/types/sampleMaterial'
import type { BomLineInput } from '@/types/bom'

const row = (): SampleMaterialLine => ({ key: 'a', category: 'hardware', name: '五金', specification: 'M8', material: '', color: '', quantity: '3', unitId: 'root', unitLabel: '根', notes: '',
  material_catalog_id: 'catalog', material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { specification: 'M8' }, unit_id: 'root' } })

describe('打样及手工入库复用U2选料', () => {
  it('打样流程传递窄源标记且不能打开独立维护窗', async () => {
    const wrapper = shallowMount(Selection, { props: { modelValue: row(), source: 'sample' } })
    const panel = wrapper.getComponent(Panel)
    expect(panel.props('source')).toBe('sample')
    panel.vm.$emit('maintain')
    await nextTick()
    expect(wrapper.findComponent({ name: 'RawMaterialManagementView' }).exists()).toBe(false)
    wrapper.unmount()
  })
  it('选择变化只更新当前草稿，不修改外部输入或调用保存接口', async () => {
    const original = row(), wrapper = shallowMount(Selection, { props: { modelValue: original } })
    const projected = wrapper.getComponent(Panel).props('line') as BomLineInput
    projected.material_selection!.attributes.specification = 'M10'
    projected.specification = 'M10'
    await nextTick()
    expect(original.material_selection!.attributes.specification).toBe('M8')
    const selected = wrapper.emitted('update:modelValue')!.at(-1)![0] as SampleMaterialLine
    expect(selected.material_selection!.attributes.specification).toBe('M10')
    expect(selected.quantity).toBe('3')
    wrapper.unmount()
  })
  it('只读时拒绝应用，分区映射仍为本类别', async () => {
    const wrapper = shallowMount(Selection, { props: { modelValue: row(), disabled: true } })
    const panel = wrapper.getComponent(Panel)
    expect(panel.props('sectionTitle')).toBe('五金件')
    ;(panel.props('line') as BomLineInput).part_name = '不应应用'
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })
})
