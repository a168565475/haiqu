import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createInquiry, saveInquiryDraft } from './inquiries'
import { createQuotationLine, updateQuotationLine } from './quotations'
import { createSalesOrder, updateSalesOrder, changeConfirmedSalesOrder } from './salesOrders'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), defaults: {} }))
vi.mock('./request', () => ({ apiClient: client }))
const selection = { catalog_version: 'v2', color_id: 'blue', material: '铝', thickness: '1.2' }
const snapshot = { catalog_id: 'catalog1', name: '历史品名', catalog_version: 'v1' }
beforeEach(() => { vi.resetAllMocks(); client.post.mockResolvedValue({ data: { data: {} }, headers: { etag: '"v3"' } }); client.patch.mockResolvedValue({ data: { data: {} }, headers: { etag: '"v3"' } }) })
describe('新产品库商业请求边界', () => {
  it('全手填产品没有目录 ID 时仍传递字段来源，并移除旧产品关联', async () => {
    const draftSelection = { draft: { category_id: null, category_name: '新品类', name_id: null, name: '新椅子',
      item_number: 'A-1', specification: '60×80', product_code: 'P-1', unit_id: null, unit_name: '新单位',
      color_id: null, color_name: '酒红', material: '新材质', sources: { category_name: 'typed', name: 'typed', item_number: 'typed', specification: 'typed', product_code: 'typed', unit_name: 'typed', color_name: 'typed', material: 'typed' } } }
    const line = { product_catalog_id: null, product_selection: draftSelection, product_id: 'old', product_category_id: 'old-category', product_color_id: 'old-color', quantity: '2', unit_price: '10' }
    await createInquiry({ items: [line] } as never)
    await createQuotationLine('version', line as never, 'v1')
    await createSalesOrder({ lines: [line], delivery_batches: [] } as never)
    const payloads = [client.post.mock.calls[0]![1].items[0], client.post.mock.calls[1]![1], client.post.mock.calls[2]![1].lines[0]]
    for (const payload of payloads) expect(payload).toMatchObject({ product_catalog_id: null, product_selection: draftSelection, product_id: null, product_category_id: null, product_color_id: null, quantity: '2' })
  })
  it('询盘新选择传独立selection；旧行保存仅catalogID，快照不回写', async () => {
    const item = { product_catalog_id: 'catalog1', product_id: 'old', product_category_id: 'old-category', product_color_id: 'old-color', quantity: '8', product_selection: selection, product_selection_snapshot: snapshot }
    await createInquiry({ customer_account_id: 'customer', items: [item] } as never)
    expect(client.post.mock.calls[0]![1].items[0]).toEqual({ product_catalog_id: 'catalog1', product_id: null, product_category_id: null, product_color_id: null, quantity: '8', product_selection: selection })
    await saveInquiryDraft('inquiry1', { items: [{ ...item, product_selection: null }] } as never, '"v1"')
    expect(client.patch.mock.calls[0]![1].items[0]).not.toHaveProperty('product_selection')
    expect(client.patch.mock.calls[0]![1].items[0]).not.toHaveProperty('product_selection_snapshot')
    expect(client.patch.mock.calls[0]![2]).toEqual({ headers: { 'If-Match': '"v1"' } })
  })

  it('报价新建和编辑都保留选中的ID，普通编辑不重构历史selection', async () => {
    const line = { product_catalog_id: 'catalog1', product_selection: selection, product_selection_snapshot: snapshot, quantity: '3', unit_price: '20' }
    await createQuotationLine('version1', line as never, '"v1"')
    expect(client.post.mock.calls[0]![1]).toMatchObject({ product_catalog_id: 'catalog1', product_selection: selection, quantity: '3', unit_price: '20', product_id: null, product_color_id: null })
    expect(client.post.mock.calls[0]![1]).not.toHaveProperty('product_selection_snapshot')
    await updateQuotationLine('line1', { ...line, product_selection: null } as never, '"v2"')
    expect(client.patch.mock.calls[0]![1]).not.toHaveProperty('product_selection')
    expect(client.patch.mock.calls[0]![1].product_catalog_id).toBe('catalog1')
  })

  it('销售新选带selection，报价继承/确认后普通变更保留catalogID并剔除只读快照', async () => {
    const line = { client_key: 'line1', product_catalog_id: 'catalog1', product_selection: selection, product_selection_snapshot: snapshot, quantity: '4', unit_price: '30' }
    await createSalesOrder({ lines: [line], delivery_batches: [] } as never)
    expect(client.post.mock.calls[0]![1].lines[0].product_selection).toEqual(selection)
    const inherited = { lines: [{ ...line, product_selection: null, source_quotation_line_id: 'quote-line' }], delivery_batches: [] }
    await updateSalesOrder('order1', inherited as never, '"v1"')
    expect(client.patch.mock.calls[0]![1].lines[0]).not.toHaveProperty('product_selection')
    expect(client.patch.mock.calls[0]![1].lines[0]).not.toHaveProperty('product_selection_snapshot')
    await changeConfirmedSalesOrder('order1', { order: inherited, change_reason: '改交期' } as never, '"v2"')
    expect(client.post.mock.calls[1]![1].order.lines[0]).toMatchObject({ product_catalog_id: 'catalog1', source_quotation_line_id: 'quote-line', quantity: '4', unit_price: '30' })
    expect(client.post.mock.calls[1]![1].order.lines[0]).not.toHaveProperty('product_selection')
  })
})
