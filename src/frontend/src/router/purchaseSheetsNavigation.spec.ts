import { describe, expect, it } from 'vitest'
import { router } from './index'

describe('采购确认后直接进入供应商采购表', () => {
  it('旧模板选择地址保留订单范围并跳过中间页面', () => {
    const record = router.getRoutes().find(item => item.name === 'purchase-sheet-template-select')
    expect(record?.components?.default).toBeUndefined()
    if (typeof record?.redirect !== 'function') throw new Error('旧模板地址应直接跳转供应商采购表')
    expect(record.redirect(router.resolve('/purchase-orders/order-1/templates'), router.currentRoute.value)).toEqual({
      name: 'supplier-purchase-sheets', query: { purchase_order_id: 'order-1' },
    })
  })
})
