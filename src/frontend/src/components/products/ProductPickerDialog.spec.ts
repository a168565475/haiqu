import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import ProductPickerDialog from './ProductPickerDialog.vue'

const products = [
  { id: 'p1', product_number: 'P-001', product_code: 'HTB-001', item_number: 'XY-001', product_name: '导演椅', specification: '50×60', default_unit_id: 'u1' },
  { id: 'p2', product_number: 'P-002', product_code: 'HTB-002', item_number: 'XY-002', product_name: '行军床', specification: '210×72', default_unit_id: 'u1' },
]
const units = [{ id: 'u1', unit_code: '03', unit_name: '张' }]
const wrappers: ReturnType<typeof mount>[] = []

afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('ProductPickerDialog', () => {
  it('统一展示产品字段并支持搜索和单选回填', async () => {
    const wrapper = mount(ProductPickerDialog, {
      attachTo: document.body,
      props: { modelValue: true, products, units, selectedId: 'p1', canCreate: false },
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await nextTick()
    await nextTick()

    const table = wrapper.findComponent({ name: 'ElTable' })
    expect(table.props('data')).toHaveLength(2)
    await wrapper.findComponent({ name: 'ElInput' }).find('input').setValue('行军床')
    await flushPromises()
    expect(table.props('data')).toEqual([products[1]])
    table.vm.$emit('row-click', products[1])
    expect(wrapper.emitted('select')?.[0]).toEqual([products[1]])
    expect(document.body.textContent).not.toContain('新增产品')
  })

  it('有权限时显示新增产品入口', async () => {
    const wrapper = mount(ProductPickerDialog, {
      attachTo: document.body,
      props: { modelValue: true, products, units, canCreate: true },
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await nextTick()
    await nextTick()
    const button = wrapper.findAllComponents({ name: 'ElButton' }).find((item) => item.text() === '新增产品')
    expect(button).toBeTruthy()
    await button?.trigger('click')
    expect(wrapper.emitted('create')).toHaveLength(1)
  })
})
