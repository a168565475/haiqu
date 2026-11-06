import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import ElementPlus from 'element-plus'
import { blankLine } from '@/views/boms/bomEditorHelpers'
import BomLineEditorForm from './BomLineEditorForm.vue'

vi.mock('@/components/production/PinyinFilterSelect.vue', () => ({ default: { template: '<select />' } }))
vi.mock('@/api/materialCatalog', () => ({ fetchMaterialCatalog: vi.fn(), fetchMaterialCatalogOptions: vi.fn(), fetchMaterialCatalogs: vi.fn(), fetchPublicMaterialOptions: vi.fn(), materialCatalogError: String }))
vi.mock('@/api/boms', () => ({ fetchBomCatalogSelectionOptions: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))

describe('BOM管材沿原根米支输入流程', () => {
  it('采购余量回显自动档，任何数量均能手动换档，数量变化不覆盖手动选择', async () => {
    const line = reactive({ ...blankLine('根'), purchase_allowance_mode: 'AUTO' as 'AUTO' | 'MANUAL', purchase_allowance_rule: '' as '' | 'PERCENT_0_5' })
    const calculations = { base_purchase_bar_count: '500', purchase_allowance_bar_count: '5', branch_count: '505', purchase_allowance_rule: 'PLUS_5' }
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '管材类', section_type: 'PROFILE', lines: [] },
      editingLineDraft: line, editingLineCalculations: calculations,
    } as never, global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    const allowanceField = wrapper.findAll('.drawer-field').find(field => field.find('span').text() === '采购余量')!
    const selector = allowanceField.findComponent({ name: 'ElSelect' })
    expect(selector.props('modelValue')).toBe('AUTO')
    expect(allowanceField.findAllComponents({ name: 'ElOption' }).map((option: { props: () => Record<string, unknown> }) => option.props().value)).toEqual(['AUTO', 'NONE', 'PLUS_5', 'PLUS_8', 'PERCENT_0_5', 'PERCENT_1'])
    expect(allowanceField.findComponent({ name: 'ElOption' }).props('label')).toBe('自动（+5 根）')
    expect(wrapper.text()).toContain('采购根数500')
    expect(wrapper.text()).toContain('采购余量（根）5')
    expect(wrapper.text()).toContain('建议采购根数505')
    selector.vm.$emit('change', 'PLUS_5')
    await wrapper.vm.$nextTick()
    expect(line).toMatchObject({ purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'PLUS_5' })
    selector.vm.$emit('change', 'PERCENT_0_5')
    await wrapper.vm.$nextTick()
    expect(line).toMatchObject({ purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'PERCENT_0_5' })
    await wrapper.setProps({ editingLineCalculations: { ...calculations, purchase_allowance_rule: 'PERCENT_1', base_purchase_bar_count: '5001' } })
    expect(selector.props('modelValue')).toBe('PERCENT_0_5')
    selector.vm.$emit('change', 'AUTO')
    await wrapper.vm.$nextTick()
    expect(line).toMatchObject({ purchase_allowance_mode: 'AUTO', purchase_allowance_rule: '' })
    expect(selector.props('modelValue')).toBe('AUTO')
    expect(allowanceField.findComponent({ name: 'ElOption' }).props('label')).toBe('自动（+1%）')
    wrapper.unmount()
  })

  it('历史行打开时保持原规则，用户选项后才切换新模式', async () => {
    const line = reactive(blankLine('根'))
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '管材类', section_type: 'PROFILE', lines: [] },
      editingLineDraft: line, editingLineCalculations: null,
    } as never, global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    const selector = wrapper.find('[aria-label="采购余量"]')
    expect(selector.attributes('placeholder')).toBe('沿用已保存规则')
    expect(line.purchase_allowance_mode).toBeUndefined()
    wrapper.findAll('.drawer-field').find(field => field.find('span').text() === '采购余量')!.findComponent({ name: 'ElSelect' }).vm.$emit('change', 'NONE')
    await wrapper.vm.$nextTick()
    expect(line).toMatchObject({ purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'NONE' })
    wrapper.unmount()
  })

  it('包材行编辑按当前订单与用量显示需求，缺少用量提示待填写', async () => {
    const line = { ...blankLine('个'), units_per_box: '10', unit_consumption: '999', packaging_material_number: 'PK-001', raw_material: 'PK-OLD' }
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '包材类', section_type: 'ACCESSORY', lines: [] },
      editingLineDraft: line,
      bom: { order_quantity: '25' }, editingLineCalculations: null,
    } as never })
    expect(wrapper.find('[aria-label="单个用量"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('需求数量3')
    expect(wrapper.find('[aria-label="用量（多少成品用一份）"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('订单数量 ÷')
    expect(wrapper.text()).not.toContain('每箱')
    expect(wrapper.text()).not.toContain('品号')
    expect(wrapper.text()).not.toContain('PK-001')
    expect(line.packaging_material_number).toBe('PK-001')
    await wrapper.setProps({ editingLineDraft: { ...line, units_per_box: '' } })
    expect(wrapper.text()).toContain('需求数量待填写')
    wrapper.unmount()
  })

  it('只在BOM PROFILE调用固定根，不再提供任意单位显式总量', () => {
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '管材类', section_type: 'PROFILE', lines: [] },
      editingLineDraft: { ...blankLine('公斤'), material_catalog_id: 'A' }, editingLineCalculations: null,
    } as never })
    const selector = wrapper.findComponent({ name: 'MaterialSelectionPanel' })
    expect(selector.props('fixedUnit')).toBe('根')
    expect(selector.props('presentation')).toBe('dropdown')
    expect(wrapper.find('.line-drawer-form').element.firstElementChild).toBe(selector.element)
    expect(wrapper.text()).toContain('原材料单位根')
    expect(wrapper.find('[aria-label="所选数量单位的本次数量"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="切割长度（mm）"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="单个用量"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="切割支数"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('管材已选属性直接显示，不展示属性长度且不回填旧字段', () => {
    const line = {
      ...blankLine('根'), material_catalog_id: 'A', material: '旧字段材质', tube_shape: '旧字段形状',
      material_selection: { catalog_version: 'v2', scope: 'BASE', processing_state: 'RAW', attributes: { material: '铝', shape: '方管', section_size: '25*15', thickness: '1.2', color: '银色', length: '6000' } },
    }
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '管材类', section_type: 'PROFILE', lines: [] },
      editingLineDraft: line, editingLineCalculations: null,
    } as never })
    const values = wrapper.findAll('.drawer-readonly-value').map(item => item.text())
    expect(values).toEqual(expect.arrayContaining(['铝', '方管', '25*15', '1.2', '银色']))
    expect(values).not.toContain('6000')
    expect(wrapper.text()).not.toContain('原管长度')
    expect(line.material_selection.attributes.length).toBe('6000')
    expect(values).not.toContain('旧字段材质')
    expect(values).not.toContain('旧字段形状')
    expect(line.material).toBe('旧字段材质')
    expect(wrapper.find('[aria-label="喷塑颜色"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('面料目录快照显示为只读内容，不再使用旧source选择器或重复编辑品名', () => {
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '面料类', section_type: 'FABRIC', lines: [] },
      editingLineDraft: { ...blankLine('米'), material_catalog_id: 'F', source_fabric_material_id: 'legacy-id',
        material_selection_snapshot: { color_card: 'A色卡', color_code: '102', color_name: '蓝色',
          attributes: { material: '涤纶', fabric_spec: '600D', color: '蓝色', width: '1.5' } } },
      editingLineCalculations: null,
    } as never })
    const values = wrapper.findAll('.drawer-readonly-value').map(item => item.text())
    expect(values).toEqual(expect.arrayContaining(['涤纶', '600D / 1.5', 'A色卡', '102', '蓝色', '1.5']))
    expect(wrapper.findComponent({ name: 'MaterialSelectionPanel' }).props('fixedUnit')).toBe('米')
    expect(wrapper.find('[aria-label="单耗"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="单个用量"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('单位米')
    for (const label of ['面料规格', '面料材质', '面料色卡颜色色号', '面料门幅', '裁片']) {
      expect(wrapper.find(`[aria-label="${label}"]`).exists()).toBe(false)
    }
    wrapper.unmount()
  })
  it.each([['五金件', 'HARDWARE', '个'], ['辅料类', 'FABRIC', '码'], ['裁剪明细', 'FABRIC', '套']])('%s不启用面料固定米，保留原单位和用量名称', (title, sectionType, unit) => {
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      isPipeCuttingLine: () => false, legacyPipeCuttingValues: () => null, number: String,
      catalogMode: true, editingSection: { title, section_type: sectionType, lines: [] },
      editingLineDraft: { ...blankLine(unit), material_catalog_id: 'B' }, editingLineCalculations: null,
    } as never })
    if (title === '裁剪明细') {
      expect(wrapper.findComponent({ name: 'MaterialSelectionPanel' }).exists()).toBe(false)
      expect(wrapper.findComponent({ name: 'BomCuttingCatalogSelect' }).exists()).toBe(true)
      expect(wrapper.text()).not.toContain('流转单位')
    } else {
      expect(wrapper.findComponent({ name: 'MaterialSelectionPanel' }).props('fixedUnit')).toBeUndefined()
      expect(wrapper.text()).toContain(`单位${unit}`)
    }
    expect(wrapper.props('editingLineDraft')?.unit).toBe(unit)
    expect(wrapper.find('[aria-label="单耗"]').exists()).toBe(false)
    if (title !== '裁剪明细') expect(wrapper.find('[aria-label="单个用量"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('管材喷塑颜色只回显共享行的选中值，读取公共候选不赋默认值', async () => {
    const line = reactive(blankLine('根'))
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      displayLineImages: () => [], formatHardwareColor: String,
      catalogMode: true, editingSection: { title: '管材类', section_type: 'PROFILE', lines: [] },
      editingLineDraft: line, editingLineCalculations: null,
    } as never })
    const coating = wrapper.findAll('.drawer-field').find(field => field.find('span').text() === '喷塑颜色')!
    const selector = wrapper.findComponent({ name: 'MaterialSelectionPanel' })
    selector.vm.$emit('loaded', { id: 'A', spray_enabled: true })
    selector.vm.$emit('public-options', { values: [{ id: 'C', field_key: 'color', value: '黑色' }] })
    await wrapper.vm.$nextTick()
    expect(coating.get('.drawer-readonly-value').text()).toBe('—')
    expect(line.tube_coating_color).toBe('')
    expect(coating.findComponent({ name: 'ElSelect' }).exists()).toBe(false)
    line.tube_coating_color = '黑色'
    await wrapper.vm.$nextTick()
    expect(coating.get('.drawer-readonly-value').text()).toBe('黑色')
    line.tube_coating_color = ''
    await wrapper.vm.$nextTick()
    expect(coating.get('.drawer-readonly-value').text()).toBe('—')
    wrapper.unmount()
  })
  it.each([
    ['五金件', 'HARDWARE'],
  ])('%s喷塑颜色只选公共候选，未启用半成品时隐藏', async (title, sectionType) => {
    const line = blankLine('根')
    const wrapper = shallowMount(BomLineEditorForm, {
      props: {
        displayLineImages: () => [], formatHardwareColor: String,
        catalogMode: true, editingSection: { title, section_type: sectionType, lines: [] },
        editingLineDraft: line, editingLineCalculations: null,
      } as never,
      global: { plugins: [ElementPlus], renderStubDefaultSlot: true },
    })
    const selector = wrapper.findComponent({ name: 'MaterialSelectionPanel' })
    expect(wrapper.findComponent({ name: 'ElSelect' }).exists()).toBe(false)
    await wrapper.setProps({ editingLineDraft: { ...line, material_catalog_id: 'A' } })
    selector.vm.$emit('loaded', { id: 'A', spray_enabled: false })
    selector.vm.$emit('public-options', { values: [{ id: 'C', field_key: 'color', value: '黑色' }] })
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent({ name: 'ElSelect' }).exists()).toBe(false)
    selector.vm.$emit('loaded', { id: 'A', spray_enabled: true })
    await wrapper.vm.$nextTick()
    const coating = wrapper.findComponent({ name: 'ElSelect' })
    expect(coating.props()).toMatchObject({ disabled: false, filterable: false, allowCreate: false, placeholder: '选择喷塑颜色' })
    expect(wrapper.findComponent({ name: 'ElOption' }).props()).toMatchObject({ label: '黑色', value: '黑色' })
    selector.vm.$emit('public-options', { values: [] })
    await wrapper.vm.$nextTick()
    expect(coating.props('placeholder')).toBe('暂无喷塑颜色，请到维护配置新增')
    expect(coating.props('noDataText')).toContain('维护配置')
    wrapper.unmount()
  })
})
