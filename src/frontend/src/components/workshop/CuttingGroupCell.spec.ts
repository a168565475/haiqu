import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import CuttingGroupCell from './CuttingGroupCell.vue'

const parts = [
  { component_identity: 'front', name: '床面', quantity_per_group: 1, unit: '片' },
  { component_identity: 'side-left', name: '侧片', quantity_per_group: 2, unit: '片' },
  { component_identity: 'side-right', name: '侧片', quantity_per_group: 1, unit: '片' },
]

describe('裁片组展示', () => {
  it('表格只显示第一个裁片和剩余数量，悬浮后每片单独一行', async () => {
    const wrapper = mount(CuttingGroupCell, {
      attachTo: document.body,
      props: { label: '床面、侧片、侧片', components: parts },
      global: { plugins: [ElementPlus] },
    })
    try {
      const cell = wrapper.get('.cutting-group-cell')
      expect(cell.get('.cutting-group-cell__name').text()).toBe('床面')
      expect(cell.get('.cutting-group-cell__count').text()).toBe('+2')
      await cell.trigger('mouseenter')
      await vi.waitFor(() => {
        const list = document.body.querySelector('.cutting-group-cell__parts')
        expect(list).not.toBeNull()
        expect(getComputedStyle(list!.closest('.el-popper')!).display).not.toBe('none')
        expect([...list!.querySelectorAll('li')].map(item => item.textContent?.trim())).toEqual([
          '床面 1片', '侧片 2片', '侧片 1片',
        ])
        expect(list!.closest('.el-popper')?.textContent).toContain('所列裁片全部做齐才算 1 套。')
      })
    } finally {
      wrapper.unmount()
    }
  })

  it('单裁片省略加号，普通部位按原名称展示', async () => {
    const wrapper = mount(CuttingGroupCell, {
      props: { label: '普通部位', components: [parts[0]!] },
      global: { plugins: [ElementPlus] },
    })
    try {
      expect(wrapper.text()).toBe('床面')
      expect(wrapper.find('.cutting-group-cell__count').exists()).toBe(false)
      await wrapper.setProps({ components: undefined })
      expect(wrapper.text()).toBe('普通部位')
      expect(wrapper.find('.cutting-group-cell').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })
})
