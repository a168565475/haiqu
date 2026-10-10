import { describe, expect, it } from 'vitest'
import type { SampleListItem } from '@/types/sample'
import type { SavedView } from '@/types/savedView'
import { sampleDateBounds, sampleProductsLabel, sampleQuantityLabel, sampleSavedQuery, sampleStatusTone } from './samplePresentation'

describe('打样列表业务展示适配', () => {
  it('日期覆盖所选自然日，空值、非法日期和反向范围不发出无效条件', () => {
    const range: [Date, Date] = [new Date(2026, 8, 1), new Date(2026, 8, 10)]
    const bounds = sampleDateBounds(range)
    expect(new Date(bounds.requested_from!)).toEqual(new Date(2026, 8, 1))
    expect(new Date(bounds.requested_to!)).toEqual(new Date(2026, 8, 10, 23, 59, 59, 999))
    expect(range[1].getHours()).toBe(0)
    expect(sampleDateBounds(null)).toEqual({})
    expect(sampleDateBounds([new Date('invalid'), range[1]])).toEqual({})
    expect(sampleDateBounds([range[1], range[0]])).toEqual({})
    expect(sampleSavedQuery({ filter_definition: bounds } as SavedView)).toMatchObject(bounds)
  })
  it('保存视图恢复 API 的 search 和排序，兼容历史 q', () => {
    const view = { filter_definition: { search: 'SRQ-12', q: '旧条件', ordering: 'requested_at', status: 'PMC_REVIEW' }, sort_definition: [] } as unknown as SavedView
    expect(sampleSavedQuery(view)).toMatchObject({ search: 'SRQ-12', ordering: 'requested_at', status: 'PMC_REVIEW' })
    expect(sampleSavedQuery({ ...view, filter_definition: { q: '旧条件', ordering: 'arbitrary_field' } })).toMatchObject({ search: '旧条件', ordering: '-requested_at' })
  })

  it('多产品申请数量合计且名称不丢失；没有数量事实时不伪造零', () => {
    const row = { products: [{ product_name: '椅子', total_sample_quantity: 2 }, { product_name: '桌子', total_sample_quantity: 3 }] } as SampleListItem
    expect(sampleProductsLabel(row)).toBe('椅子、桌子')
    expect(sampleQuantityLabel(row)).toBe('5 PCS')
    expect(sampleQuantityLabel({ ...row, products: [] })).toBe('—')
    expect(sampleQuantityLabel({ ...row, products: [{ total_sample_quantity: NaN }] as SampleListItem['products'] })).toBe('—')
  })

  it('未知状态保持中性色，不把新阶段假定成旧阶段或成功', () => {
    expect(sampleStatusTone('FUTURE_STAGE')).toBe('neutral')
    expect(sampleStatusTone('PMC_REVIEW')).toBe('warning')
    expect(sampleStatusTone('FINISHED')).toBe('success')
  })
})
