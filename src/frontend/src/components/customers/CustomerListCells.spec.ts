import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CustomerActivityTag from './CustomerActivityTag.vue'
import CustomerIdentityCell from './CustomerIdentityCell.vue'
import type { CustomerListItem } from '@/types/customer'

describe('客户列表单元格', () => {
  it('使用后端活跃度口径展示风险状态与原因', () => {
    const wrapper = mount(CustomerActivityTag, {
      props: {
        activity: {
          id: 'activity-1',
          activity_status: 'HIGH_RISK',
          display_name: '高风险',
          source_type: 'SYSTEM',
          reason: '存在逾期任务',
          formula_version: 'v1',
          effective_from: '2026-09-08T00:00:00Z',
          effective_to: null,
        },
      },
    })

    expect(wrapper.text()).toBe('高风险')
    expect(wrapper.classes()).toContain('is-danger')
    expect(wrapper.attributes('title')).toBe('存在逾期任务')
  })

  it('支持原型定义的 Strong 标签色调', () => {
    const wrapper = mount(CustomerActivityTag, {
      props: {
        label: '今日跟进',
        tone: 'warning',
      },
    })

    expect(wrapper.text()).toBe('今日跟进')
    expect(wrapper.classes()).toContain('is-warning')
    expect(wrapper.attributes('title')).toBe('今日跟进')
  })

  it('只展示客户全名并保留可打开详情的按钮', async () => {
    const customer = {
      id: 'customer-1',
      account_name: '示例贸易有限公司',
      account_code: 'CUS-00001',
      short_name: '示例贸易',
      english_name: '',
    } as CustomerListItem
    const wrapper = mount(CustomerIdentityCell, { props: { customer } })

    expect(wrapper.text()).toContain('示例贸易有限公司')
    expect(wrapper.text()).not.toContain('CUS-00001')
    expect(wrapper.get('button').attributes('title')).toBe('示例贸易有限公司')

    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
  })
})
