import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import { fetchNumberRules } from '@/api/referenceData'
import type { NumberRule } from '@/types/referenceData'
import NumberRulesView from './NumberRulesView.vue'

vi.mock('@/api/referenceData', () => ({ fetchNumberRules: vi.fn() }))

function rule(overrides: Partial<NumberRule>): NumberRule {
  return {
    id: 'daily-bom', number_type: 'BOM', chinese_name: 'BOM 编号', prefix: 'BOM',
    format_pattern: '{prefix}{short_date}{sequence}', sequence_name: '', sequence_padding: 3,
    date_granularity: 'DAY', reset_policy: 'DAILY', is_configured: true, status: 'ACTIVE',
    sort_order: 1, description: '', created_at: '', updated_at: '', ...overrides,
  }
}

describe('编号规则格式示例', () => {
  it('展示短日期日流水，并保留原月序列和未配置规则', async () => {
    vi.mocked(fetchNumberRules).mockResolvedValue({
      data: [
        rule({}),
        rule({ id: 'inquiry', number_type: 'INQUIRY', prefix: 'INQ', format_pattern: '{prefix}-{date}-{sequence}', sequence_name: 'haiqu_inquiry_number_seq', sequence_padding: 6, date_granularity: 'MONTH', reset_policy: 'NEVER' }),
        rule({ id: 'unconfigured', number_type: 'ORDER', is_configured: false }),
      ],
      meta: { total: 3, page: 1, page_size: 100, total_pages: 1 },
    })
    const wrapper = mount(NumberRulesView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      expect(wrapper.text()).toContain('BOM260820001')
      expect(wrapper.text()).toContain('年月日')
      expect(wrapper.text()).toContain('INQ-202608-000001')
      expect(wrapper.text()).toContain('未配置')
      expect(wrapper.text()).not.toContain('{short_date}')
    } finally {
      wrapper.unmount()
    }
  })
})
