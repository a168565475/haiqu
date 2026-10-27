import { describe, expect, it } from 'vitest'
import type { NotificationRule } from '@/types/notifications'
import { groupNotificationRules } from './notificationMenuGroups'

const rule = (event_code: string) => ({ event_code }) as NotificationRule

describe('通知规则按业务菜单分组', () => {
  it('待外发通知归仓库，损耗和少回通知仍归车间且不遗漏重复规则', () => {
    const rules = [
      rule('OUTSOURCING_ORDER_CREATED'), rule('TUBE_OUTSOURCING_ORDER_CREATED'),
      rule('OUTSOURCING_LOSS_RECORDED'), rule('TUBE_OUTSOURCING_SHORTAGE_RECORDED'),
    ]
    const groups = groupNotificationRules(rules)
    expect(groups.map(group => [group.key, group.label])).toEqual([
      ['workshop-management', '车间'], ['warehouse-management', '仓库'],
    ])
    expect(groups[1]!.rules).toEqual(rules.slice(0, 2))
    expect(groups.flatMap(group => group.rules)).toHaveLength(rules.length)
    expect(new Set(groups.flatMap(group => group.rules)).size).toBe(rules.length)
  })

  it('采购到货和领料继续归仓库，采购完结及未知事件保留原分组', () => {
    const groups = groupNotificationRules([
      rule('MATERIAL_RECEIPT_RECORDED'), rule('MATERIAL_INSPECTION_CONFIRMED'),
      rule('MATERIAL_ISSUE_SUBMITTED'), rule('PURCHASE_ORDER_COMPLETED'), rule('UNKNOWN_EVENT'),
    ])
    expect(groups.map(group => [group.key, group.rules.length])).toEqual([
      ['procurement-management', 1], ['warehouse-management', 3], ['other', 1],
    ])
  })
})
