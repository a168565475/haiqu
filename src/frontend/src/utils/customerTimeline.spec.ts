import { describe, expect, it } from 'vitest'
import { getTimelineEventTypeLabel, getTimelineSourceTypeLabel } from './customerTimeline'

describe('客户时间线中文展示', () => {
  it('将已知事件编码转换为中文业务名称', () => {
    expect(getTimelineEventTypeLabel('CUSTOMER_CONTACT_CREATED')).toBe('已新增客户联系人')
    expect(getTimelineEventTypeLabel('CUSTOMER_ENTITY_ADDRESS_UPDATED')).toBe('已更新客户地址')
  })

  it('将来源编码转换为中文且不暴露未知英文编码', () => {
    expect(getTimelineSourceTypeLabel('CUSTOMER_CONTACT')).toBe('客户联系人')
    expect(getTimelineEventTypeLabel('FUTURE_EVENT_CODE')).toBe('系统记录')
    expect(getTimelineSourceTypeLabel('FUTURE_SOURCE')).toBe('业务记录')
  })
})
