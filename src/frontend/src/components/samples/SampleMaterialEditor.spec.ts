import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Editor from './SampleMaterialEditor.vue'
import Drawer from './SampleMaterialLineDrawer.vue'
import Picker from './SampleMaterialPicker.vue'
import Field from './SampleMaterialFieldInput.vue'
import { ElCascader, ElSelect } from 'element-plus'
import type { SampleMaterialLine } from '@/types/sampleMaterial'

const api = vi.hoisted(() => ({ references: vi.fn(), candidates: vi.fn() }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterialReferences: api.references, fetchSampleMaterialCandidates: api.candidates }))
const line = (): SampleMaterialLine => ({ key: 'a', category: 'tube', rawMaterialId: 'raw', cuttingLengthMm: '500', piecesPerBar: '6', name: '圆管', specification: '25×1.2', material: '铝', color: '黑色', quantity: '12', unitId: 'm', notes: '' })
const units = [{ id: 'm', label: '米', decimalPlaces: 4 }]
const references = { tube: {}, fabric: {}, accessory: {}, accessories: [] }
const wrappers: ReturnType<typeof mount>[] = []
// 单元测试只替换弹层外壳；保留 Select 自身 Teleport，避免测试桩改变选项注册生命周期。
const overlay = { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' }
const global = { plugins: [ElementPlus], stubs: { AppWindowDialog: overlay, ElDrawer: overlay, ElDialog: overlay } }
async function editor(lines = [line()]) {
  const wrapper = mount(Editor, { props: { modelValue: lines, units, fullscreen: false, 'onUpdate:modelValue': (value: SampleMaterialLine[]) => wrapper.setProps({ modelValue: value }) }, global })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => { vi.clearAllMocks(); api.references.mockResolvedValue(references) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('用料需求复用 BOM 编辑交互', () => {
  it('仅sidebar模式采用左分类右明细，切换保留全部行并复用行编辑删除全屏', async () => {
    const fabric = { ...line(), key: 'fabric-1', category: 'fabric' as const, name: '面料' }
    const wrapper = await editor([line(), fabric])
    await wrapper.setProps({ layout: 'sidebar' })
    expect(wrapper.find('.material-tabs').exists()).toBe(false)
    expect(wrapper.findAll('.section-sidebar .section-tabs button')).toHaveLength(6)
    expect(wrapper.find('.material-main .material-table').exists()).toBe(true)
    await wrapper.findAll('.section-sidebar button').find(button => button.text().startsWith('面料类'))!.trigger('click')
    expect(wrapper.findAll('tbody tr[data-line-key]').map(row => row.attributes('data-line-key'))).toEqual(['fabric-1'])
    await wrapper.get('[aria-label="放大编辑当前行"]').trigger('click')
    expect(wrapper.findComponent(Drawer).props('line').key).toBe('fabric-1')
    expect(wrapper.findAll('.section-sidebar button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('.action-cell .row-delete').exists()).toBe(true)
    wrapper.findComponent(Drawer).vm.$emit('update:modelValue', false); await flushPromises()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    await wrapper.get('[aria-label="删除当前行"]').trigger('click'); await flushPromises()
    expect(wrapper.props('modelValue').map(item => item.key)).toEqual(['a'])
    await wrapper.get('.fullscreen-toggle').trigger('click')
    expect(wrapper.emitted('toggle-fullscreen')).toHaveLength(1)
    await wrapper.setProps({ layout: undefined })
    expect(wrapper.find('.section-sidebar').exists()).toBe(false)
    expect(wrapper.find('.material-tabs').exists()).toBe(true)
  })
  it('四种选材分区不提供手动添加入口，管材字段使用配置选择', async () => {
    const wrapper = await editor()
    const fields = wrapper.findAllComponents(Field)
    expect(fields[0]!.props('selectionOnly')).toBe(true)
    expect(fields[1]!.props('tubeSpecification')).toBe(true)
    for (const label of ['五金件', '塑料件类', '辅料类', '包材类']) {
      await wrapper.findAll('.material-tabs button').find(button => button.text().startsWith(label))!.trigger('click')
      expect(wrapper.find('.add-row').exists()).toBe(false)
      expect(wrapper.findAll('.material-toolbar button').some(button => button.text().includes('添加材料'))).toBe(false)
    }
  })
  it('规格使用配置的直径厚度，不清空历史规格', async () => {
    const wrapper = mount(Field, { props: { modelValue: '历史规格', label: '规格', placeholder: '规格', maxlength: 500, tubeSpecification: true, references: { ...references, tubeDiameters: [{ label: '25' }], tubeThicknesses: [{ label: '1.2' }] } }, global })
    wrappers.push(wrapper)
    const cascader = wrapper.findComponent(ElCascader)
    expect(cascader.props('options')).toMatchObject([{ value: '历史规格', disabled: true }, { children: [{ value: '25 × 1.2' }] }])
    cascader.vm.$emit('update:modelValue', '25 × 1.2')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['25 × 1.2'])
  })
  it('按品名分组调用服务端精确过滤，同时保留跨组选择', async () => {
    api.candidates.mockResolvedValue({ data: [], meta: { total: 0 } })
    const wrapper = mount(Picker, { props: { modelValue: false, category: 'hardware', references: { ...references, catalogNames: { hardware: ['螺钉', '自攻螺钉'] } }, units }, global })
    wrappers.push(wrapper); await wrapper.setProps({ modelValue: true }); await flushPromises()
    const select = wrapper.findComponent(ElSelect)
    select.vm.$emit('update:modelValue', '螺钉'); select.vm.$emit('change', '螺钉'); await flushPromises()
    expect(api.candidates).toHaveBeenLastCalledWith('hardware', '', 1, '螺钉')
  })
  it('放大编辑下一条只先应用当前行，取消待新增行不产生空行', async () => {
    const wrapper = await editor()
    await wrapper.find('[aria-label="放大编辑当前行"]').trigger('click')
    const drawer = wrapper.findComponent(Drawer)
    drawer.vm.$emit('apply', { ...line(), quantity: '15' }, true)
    await flushPromises()
    expect(wrapper.props('modelValue')).toHaveLength(1)
    expect(wrapper.props('modelValue')[0]?.quantity).toBe('15')
    expect(drawer.props('line')).toMatchObject({ name: '圆管', unitId: 'm', quantity: '' })
    expect(drawer.props('line').key).not.toBe('a')
    drawer.vm.$emit('update:modelValue', false)
    await flushPromises()
    expect(wrapper.props('modelValue')).toHaveLength(1)
  })
  it('保存编辑下一条定位同分区后续行，保留其他分区内容', async () => {
    const other = { ...line(), key: 'other', category: 'fabric' as const, name: '布料' }
    const wrapper = await editor([line(), other, { ...line(), key: 'next', quantity: '6' }])
    await wrapper.find('[aria-label="放大编辑当前行"]').trigger('click')
    const drawer = wrapper.findComponent(Drawer)
    expect(drawer.props('hasNext')).toBe(true)
    drawer.vm.$emit('apply', { ...line(), quantity: '10' }, true)
    await flushPromises()
    expect(drawer.props('line').key).toBe('next')
    expect(wrapper.props('modelValue')[1]).toEqual(other)
  })
  it('批量导入跳过相同材料，数量留空；只读时拒绝修改', async () => {
    const wrapper = await editor([])
    const item = { id: 'r', number: 'R1', name: '管件', specification: '25mm', material: '铝', color: '黑', unitId: 'm', unitLabel: '米' }
    wrapper.findComponent(Picker).vm.$emit('choose', [item, item])
    await flushPromises()
    expect(wrapper.props('modelValue')).toHaveLength(1)
    expect(wrapper.props('modelValue')[0]?.quantity).toBe('')
    await wrapper.setProps({ disabled: true })
    wrapper.findComponent(Picker).vm.$emit('choose', [{ ...item, id: 'r2', specification: '30mm' }])
    await flushPromises()
    expect(wrapper.props('modelValue')).toHaveLength(1)
    expect(wrapper.find('[aria-label="放大编辑当前行"]').attributes('disabled')).toBeDefined()
  })
  it('抽屉本地修改取消须确认，校验失败不应用，双击下一条不重复写入', async () => {
    const wrapper = mount(Drawer, { props: { modelValue: true, line: line(), units, references, hasNext: false, canAddNext: true }, global })
    wrappers.push(wrapper); await flushPromises()
    await wrapper.find('input[aria-label="放大编辑需求数量"]').setValue('0')
    const button = (text: string) => wrapper.findAll('button').find(item => item.text() === text)!
    await button('应用修改').trigger('click')
    expect(wrapper.emitted('apply')).toBeUndefined()
    expect(wrapper.text()).toContain('需求数量必须大于 0')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    await button('取消').trigger('click'); await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.find('input[aria-label="放大编辑需求数量"]').setValue('2')
    await button('保存新增下一条').trigger('click')
    await button('保存新增下一条').trigger('click')
    expect(wrapper.emitted('apply')).toHaveLength(1)
    expect(wrapper.emitted('apply')?.[0]?.[0]).toMatchObject({ quantity: '2' })
  })
  it('选择数据跨页保留选择，搜索失败可重试', async () => {
    const first = { id: '1', number: 'R1', name: '螺钉', specification: 'M4', material: '钢', color: '黑', unitId: 'm', unitLabel: '米' }
    api.candidates.mockResolvedValueOnce({ data: [first], meta: { total: 51 } }).mockResolvedValueOnce({ data: [{ ...first, id: '2', specification: 'M6' }], meta: { total: 51 } })
    const wrapper = mount(Picker, { props: { modelValue: false, category: 'hardware', references, units }, global })
    wrappers.push(wrapper); await wrapper.setProps({ modelValue: true }); await flushPromises()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('.btn-next').trigger('click'); await flushPromises()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    expect(wrapper.text()).toContain('已选 2 项')
    await wrapper.findAll('button').find(item => item.text().includes('添加所选'))!.trigger('click')
    expect(wrapper.emitted('choose')?.[0]?.[0]).toHaveLength(2)
    api.candidates.mockRejectedValueOnce(new Error('材料读取失败'))
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('材料读取失败')
    api.candidates.mockResolvedValueOnce({ data: [first], meta: { total: 1 } })
    await wrapper.findAll('button').find(item => item.text() === '重试')!.trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
