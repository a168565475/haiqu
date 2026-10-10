import { mount } from '@vue/test-utils'
import ElementPlus, { ElButton, ElPagination } from 'element-plus'
import { describe, expect, it } from 'vitest'

import CustomerDetailListShell from './CustomerDetailListShell.vue'

function mountShell(saveViewEnabled = true) {
  return mount(CustomerDetailListShell, {
    props: {
      title: '客户询盘',
      description: '当前客户的询盘记录',
      metrics: [{ key: 'all', label: '全部询盘', value: 3 }],
      total: 42,
      page: 1,
      pageSize: 20,
      saveViewEnabled,
    },
    slots: { table: '<div class="test-table">真实列表</div>' },
    global: { plugins: [ElementPlus] },
  })
}

describe('客户详情列表公共壳层', () => {
  it('统一展示统计、标题、表格和分页', () => {
    const wrapper = mountShell()

    expect(wrapper.text()).toContain('全部询盘')
    expect(wrapper.text()).toContain('客户询盘')
    expect(wrapper.text()).toContain('真实列表')
    expect(wrapper.text()).toContain('共 42 条')
    expect(wrapper.findComponent(ElPagination).props('pageSize')).toBe(20)
  })

  it('后端不支持保存视图时保留原型按钮并明确禁用', () => {
    const wrapper = mountShell(false)
    const saveButton = wrapper.findAllComponents(ElButton).find(button => button.text() === '保存视图')

    expect(saveButton?.exists()).toBe(true)
    expect(saveButton?.props('disabled')).toBe(true)
    expect(saveButton?.attributes('title')).toBe('当前页面暂不支持保存视图')
  })

  it('按联系人布局把新建按钮放到表格上方的右侧工具栏', () => {
    const wrapper = mount(CustomerDetailListShell, {
      props: {
        title: '客户询盘', description: '当前客户的询盘记录', metrics: [], total: 0,
        page: 1, pageSize: 20, primaryLabel: '新建询盘', primaryInToolbar: true,
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.find('.customer-detail-list-shell__heading').text()).not.toContain('新建询盘')
    expect(wrapper.find('.customer-detail-list-shell__tools').text()).toContain('新建询盘')
  })

  it('向业务页面转发刷新与分页事件', async () => {
    const wrapper = mountShell()
    const refreshButton = wrapper.findAllComponents(ElButton).find(button => button.text() === '刷新')

    await refreshButton?.trigger('click')
    wrapper.findComponent(ElPagination).vm.$emit('update:current-page', 2)
    wrapper.findComponent(ElPagination).vm.$emit('update:page-size', 50)

    expect(wrapper.emitted('refresh')).toHaveLength(1)
    expect(wrapper.emitted('updatePage')).toEqual([[2]])
    expect(wrapper.emitted('updatePageSize')).toEqual([[50]])
  })
})
