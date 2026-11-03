import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { MaterialAttributeValue } from '@/types/materialCatalog'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'
import MaterialColorOptions from './MaterialColorOptions.vue'

const color = (id: string, card = '', code = '', name = '红色'): MaterialAttributeValue => ({
  id, scope: 'BASE', field_key: 'color', parent_id: null, value: name,
  product_color_id: id, color_card: card, color_code: code, color_name: name,
})
function setup(options: MaterialAttributeValue[] = [], readonly = false) {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const onUpdate = vi.fn().mockResolvedValue(undefined)
  const onRemove = vi.fn().mockResolvedValue(undefined)
  const wrapper = mount(MaterialColorOptions, { props: { label: '颜色', options,
    publicOptions: [color('public-a', '卡A', 'A1'), color('public-b', '卡B', 'B1')],
    readonly, disabled: false, onSave, onUpdate, onRemove,
  } })
  const editor = wrapper.vm as unknown as { flushDraft: () => Promise<boolean>; hasPendingEdit: () => boolean }
  return { wrapper, editor, onSave, onUpdate, onRemove }
}

describe('普通颜色三字段本地草稿', () => {
  it('只读表格显示三列，旧颜色缺少卡号时显示横线', () => {
    const { wrapper } = setup([{ id: 'legacy', scope: 'BASE', field_key: 'color', value: '旧红色', parent_id: null }], true)
    expect(wrapper.findAll('th').map(item => item.text())).toEqual(['色卡', '色号', '颜色'])
    expect(wrapper.findAll('tbody td').map(item => item.text())).toEqual(['—', '—', '旧红色'])
    expect(wrapper.find('button').exists()).toBe(false)
    wrapper.unmount()
  })

  it('连续添加保留多个输入，公共同名不同卡号独立选择，只有统一收集时提交', async () => {
    const { wrapper, editor, onSave } = setup()
    await wrapper.get('[data-action="add"]').trigger('click')
    await wrapper.get('[data-action="add"]').trigger('click')
    const selects = wrapper.findAllComponents(MaterialCatalogSelect)
    expect(selects).toHaveLength(2)
    expect(selects[0]!.props('options').map(item => item.value)).toEqual(['public:public-a', 'public:public-b'])
    selects[0]!.vm.$emit('update:modelValue', 'public:public-a')
    selects[1]!.vm.$emit('update:modelValue', 'public:public-b')
    await flushPromises()
    await wrapper.findAll('.color-editor')[0]!.trigger('keydown', { key: 'Enter' })
    expect(onSave).not.toHaveBeenCalled()
    expect(editor.hasPendingEdit()).toBe(true)
    await wrapper.setProps({ disabled: true })
    expect(await editor.flushDraft()).toBe(true)
    expect(onSave.mock.calls.map(call => call[0])).toMatchObject([
      { product_color_id: 'public-a', color_card: '卡A', color_code: 'A1', color_name: '红色', value: '红色' },
      { product_color_id: 'public-b', color_card: '卡B', color_code: 'B1', color_name: '红色', value: '红色' },
    ])
    expect(editor.hasPendingEdit()).toBe(false)
    wrapper.unmount()
  })

  it('手动修改公共颜色卡号变为新三字段草稿，保留品名属性项ID', async () => {
    const { wrapper, editor, onUpdate } = setup([{ ...color('public-a', '卡A', 'A1'), id: 'catalog-color' }])
    await wrapper.get('[data-action="edit"]').trigger('click')
    await wrapper.get('[aria-label="色卡"]').setValue('  新卡  ')
    await wrapper.get('[aria-label="色号"]').setValue('  N2  ')
    expect(onUpdate).not.toHaveBeenCalled()
    expect(await editor.flushDraft()).toBe(true)
    expect(onUpdate).toHaveBeenCalledWith('catalog-color', expect.objectContaining({
      id: 'catalog-color', product_color_id: null, color_card: '新卡', color_code: 'N2', color_name: '红色',
    }))
    wrapper.unmount()
  })

  it('只拒绝重复三元组与空颜色，取消某行不会丢失其他输入', async () => {
    const { wrapper, editor, onSave } = setup([color('existing', '卡A', 'A1')])
    await wrapper.get('[data-action="add"]').trigger('click')
    await wrapper.get('[data-action="add"]').trigger('click')
    wrapper.findAllComponents(MaterialCatalogSelect)[0]!.vm.$emit('update:modelValue', 'public:public-a')
    await flushPromises()
    expect(await editor.flushDraft()).toBe(false)
    expect(onSave).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('该色卡、色号和颜色组合已存在')
    expect(wrapper.text()).toContain('请输入颜色')
    await wrapper.findAll('[aria-label="取消添加"]')[0]!.trigger('click')
    expect(wrapper.findAllComponents(MaterialCatalogSelect)).toHaveLength(1)
    await wrapper.get('input[aria-label="添加颜色"]').setValue('  新颜色  ')
    expect(await editor.flushDraft()).toBe(true)
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ product_color_id: null, color_card: '', color_code: '', color_name: '新颜色' }))
    wrapper.unmount()
  })

  it('收集失败保留三字段草稿，取消不调用保存', async () => {
    const { wrapper, editor, onSave } = setup()
    onSave.mockRejectedValueOnce(new Error('当前品名不可编辑'))
    await wrapper.get('[data-action="add"]').trigger('click')
    await wrapper.get('[aria-label="色卡"]').setValue('新卡')
    await wrapper.get('input[aria-label="添加颜色"]').setValue('蓝色')
    expect(await editor.flushDraft()).toBe(false)
    expect((wrapper.get('[aria-label="色卡"]').element as HTMLInputElement).value).toBe('新卡')
    expect(wrapper.text()).toContain('当前品名不可编辑')
    await wrapper.get('[aria-label="取消添加"]').trigger('click')
    expect(editor.hasPendingEdit()).toBe(false)
    expect(onSave).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
