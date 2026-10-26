import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  confirmPurchaseOrder,
  completePurchaseOrder,
  batchPublishSupplierPurchaseSheets,
  createPurchaseOrder,
  deletePurchaseOrder,
  deleteSupplierPurchaseSheetSealImage,
  deleteSupplierPurchaseSheetLineImage,
  downloadSupplierPurchaseSheetXlsx,
  downloadSupplierPurchaseSheetPdf,
  batchDownloadSupplierPurchaseSheets,
  fetchPurchaseOrder,
  fetchPurchaseSheetOptions,
  fetchSupplierPurchaseSheet,
  fetchSupplierPurchaseSheetOptions,
  fetchPurchaseOrderOptions,
  fetchPurchaseOrderSupplierOptions,
  fetchPurchaseOrders,
  fetchPurchaseOrderSource,
  generatePurchaseSheets,
  saveSupplierPurchaseSheet,
  updatePurchaseContractTemplate,
  updatePurchaseOrder,
  uploadSupplierPurchaseSheetSealImage,
  uploadSupplierPurchaseSheetLineImage,
} from '@/api/purchaseOrders'
import { apiClient } from '@/api/request'
import type { PurchaseOrderInput } from '@/types/purchaseOrder'

vi.mock('@/api/request', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)
const mockedPatch = vi.mocked(apiClient.patch)
const mockedDelete = vi.mocked(apiClient.delete)

describe('采购订单 API', () => {
  it('单张PDF下载与已发布预览请求当前统一版式', async () => {
    const blob = new Blob(['pdf'], { type: 'application/pdf' })
    const signal = new AbortController().signal
    mockedGet.mockResolvedValueOnce({ data: blob })
    expect(await downloadSupplierPurchaseSheetPdf('sheet-1', signal)).toBe(blob)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/supplier-purchase-sheets/sheet-1/download-pdf/', {
      params: { layout: 'current' }, responseType: 'blob', signal,
    })
  })
  it('批量PDF下载使用相同当前版式', async () => {
    const blob = new Blob(['zip'], { type: 'application/zip' })
    mockedPost.mockResolvedValueOnce({ data: blob })
    expect(await batchDownloadSupplierPurchaseSheets(['sheet-1'])).toBe(blob)
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/supplier-purchase-sheets/batch-download/', { ids: ['sheet-1'] }, {
      params: { layout: 'current' }, responseType: 'blob',
    })
  })
  it('确认页仅请求供应商选项', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { suppliers: [] } } })
    expect(await fetchPurchaseOrderSupplierOptions()).toEqual({ suppliers: [] })
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/options/', { params: { scope: 'suppliers' } })
  })
  it('完成采购保留备注与并发版本，返回新的采购状态和版本', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'order-1', status: 'COMPLETED' } }, headers: { etag: 'new-version' } })
    const result = await completePurchaseOrder('order-1', '退货已完成', 'reviewed-version')
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/purchase-orders/order-1/complete/', { remark: '退货已完成' }, { headers: { 'If-Match': 'reviewed-version' } })
    expect(result.data.status).toBe('COMPLETED')
    expect(result.etag).toBe('new-version')
  })
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPost.mockReset()
    mockedPatch.mockReset()
    mockedDelete.mockReset()
  })

  it('列表筛选参数原样交给后端', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } },
    })

    await fetchPurchaseOrders({ page: 2, page_size: 20, q: 'CGD', status: 'DRAFT' })

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/', {
      params: { page: 2, page_size: 20, q: 'CGD', status: 'DRAFT' },
    })
  })

  it('下拉选项使用采购订单专用接口', async () => {
    mockedGet
      .mockResolvedValueOnce({ data: { data: { production_tasks: [], suppliers: [], currencies: [] } } })

    await fetchPurchaseOrderOptions()

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/options/')
  })

  it('创建采购分阶段请求轻量选项', async () => {
    mockedGet
      .mockResolvedValueOnce({ data: { data: { production_tasks: [], sample_requests: [] } } })
      .mockResolvedValueOnce({ data: { data: { suppliers: [], currencies: [], default_currency_id: null } } })

    await fetchPurchaseOrderOptions('sources')
    await fetchPurchaseOrderOptions('detail')

    expect(mockedGet).toHaveBeenNthCalledWith(1, '/api/v1/purchase-orders/options/', { params: { scope: 'sources' } })
    expect(mockedGet).toHaveBeenNthCalledWith(2, '/api/v1/purchase-orders/options/', { params: { scope: 'detail' } })
  })

  it('按生产订单读取采购来源', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { production_task_id: 'task-1', lines: [] } } })

    await fetchPurchaseOrderSource('task-1')

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/source/', {
      params: { production_task_id: 'task-1' },
    })
  })

  it('按生产订单和选中的 BOM 读取采购来源', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { production_task_id: 'task-1', lines: [] } } })

    await fetchPurchaseOrderSource('task-1', 'bom-1')

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/source/', {
      params: { production_task_id: 'task-1', bom_id: 'bom-1' },
    })
  })

  it('创建草稿保留空白采购字段并读取 ETag', async () => {
    const payload: PurchaseOrderInput = {
      production_task_id: 'task-1',
      bom_id: 'bom-1',
      source_revision: 'a'.repeat(64),
      currency_id: null,
      is_mailed: null,
      lines: [{
        bom_line_id: 'bom-line-1',
        supplier_id: null,
        delivery_date: null,
        actual_purchase_quantity: null,
        unit_price: null,
      }],
    }
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'purchase-order-1' } },
      headers: { etag: '"purchase-order-v1"' },
    })

    const result = await createPurchaseOrder(payload)

    expect(result.etag).toBe('"purchase-order-v1"')
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/purchase-orders/', payload)
  })

  it('删除采购订单调用详情删除接口', async () => {
    mockedDelete.mockResolvedValueOnce({ status: 204 })

    await deletePurchaseOrder('purchase-order-1')

    expect(mockedDelete).toHaveBeenCalledWith('/api/v1/purchase-orders/purchase-order-1/')
  })

  it('采购订单详情兼容后端直接返回订单对象', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { id: 'purchase-order-1', order_number: 'CGDD2026090801', lines: [] },
    })

    const result = await fetchPurchaseOrder('purchase-order-1')

    expect(result.id).toBe('purchase-order-1')
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/purchase-order-1/')
  })

  it('确认后按供应商生成采购表', async () => {
    mockedPost
      .mockResolvedValueOnce({ data: { data: { id: 'purchase-order-1', status: 'SUBMITTED' } } })
      .mockResolvedValueOnce({ data: { data: [{ id: 'sheet-1' }] } })
    mockedGet.mockResolvedValueOnce({ data: { data: { suppliers: [], templates: [] } } })

    await confirmPurchaseOrder('purchase-order-1')
    await fetchPurchaseSheetOptions('purchase-order-1')
    await generatePurchaseSheets('purchase-order-1', [{ supplier_id: 'supplier-1', template_version_id: 'template-v1' }])

    expect(mockedPost).toHaveBeenNthCalledWith(1, '/api/v1/purchase-orders/purchase-order-1/confirm/')
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-orders/purchase-order-1/sheet-options/')
    expect(mockedPost).toHaveBeenNthCalledWith(2, '/api/v1/purchase-orders/purchase-order-1/generate-sheets/', {
      assignments: [{ supplier_id: 'supplier-1', template_version_id: 'template-v1' }],
    })
  })

  it('已确认采购订单仍通过 ETag 保存当前采购明细', async () => {
    const payload = {
      is_mailed: true,
      lines: [{
        id: 'line-1',
        supplier_id: 'supplier-1',
        delivery_date: '2026-09-18',
        actual_purchase_quantity: '10',
        unit_price: '2.5',
      }],
    }
    mockedPatch.mockResolvedValueOnce({
      data: { data: { id: 'purchase-order-1', status: 'SUBMITTED', lines: [] } },
      headers: { etag: '"purchase-order-v2"' },
    })

    const result = await updatePurchaseOrder('purchase-order-1', payload, '"purchase-order-v1"')

    expect(result.etag).toBe('"purchase-order-v2"')
    expect(mockedPatch).toHaveBeenCalledWith(
      '/api/v1/purchase-orders/purchase-order-1/',
      payload,
      { headers: { 'If-Match': '"purchase-order-v1"' } },
    )
  })

  it('采购表编辑通过 ETag 防止覆盖他人修改', async () => {
    const content = { title: '采购合同', lines: [] } as never
    mockedGet.mockResolvedValueOnce({
      data: { data: { id: 'sheet-1', content_snapshot: content } },
      headers: { etag: '"sheet-v1"' },
    })
    mockedPatch.mockResolvedValueOnce({
      data: { data: { id: 'sheet-1', content_snapshot: content } },
      headers: { etag: '"sheet-v2"' },
    })

    const loaded = await fetchSupplierPurchaseSheet('sheet-1')
    const saved = await saveSupplierPurchaseSheet('sheet-1', content, loaded.etag)

    expect(saved.etag).toBe('"sheet-v2"')
    expect(mockedPatch).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/sheet-1/',
      { content },
      { headers: { 'If-Match': '"sheet-v1"' } },
    )
  })

  it('供应商采购表筛选项使用采购表专用供应商接口', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { data: { suppliers: [{ id: 'supplier-1', supplier_number: 'GYS00110', supplier_name: '测试供应商' }] } },
    })

    const options = await fetchSupplierPurchaseSheetOptions()

    expect(options.suppliers).toHaveLength(1)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/supplier-purchase-sheets/options/')
  })

  it('供应商采购表支持批量发布', async () => {
    mockedPost.mockResolvedValueOnce({
      data: { data: [{ id: 'sheet-1', status: 'PUBLISHED' }, { id: 'sheet-2', status: 'PUBLISHED' }] },
    })

    const result = await batchPublishSupplierPurchaseSheets(['sheet-1', 'sheet-2'])

    expect(result).toHaveLength(2)
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/batch-publish/',
      { ids: ['sheet-1', 'sheet-2'] },
    )
  })

  it('采购表明细图片上传和删除都携带 ETag', async () => {
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'sheet-1', line_images: [] } },
      headers: { etag: '"sheet-v2"' },
    })
    mockedDelete.mockResolvedValueOnce({
      data: { data: { id: 'sheet-1', line_images: [] } },
      headers: { etag: '"sheet-v3"' },
    })
    const file = new File(['image'], 'part.png', { type: 'image/png' })

    await uploadSupplierPurchaseSheetLineImage('sheet-1', 'line-1', file, '"sheet-v1"')
    await deleteSupplierPurchaseSheetLineImage('sheet-1', 'line-1', '"sheet-v2"')

    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/sheet-1/line-images/line-1/',
      expect.any(FormData),
      { headers: { 'If-Match': '"sheet-v1"' } },
    )
    expect(mockedDelete).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/sheet-1/line-images/line-1/',
      { headers: { 'If-Match': '"sheet-v2"' } },
    )
  })

  it('采购表支持 Excel 导出和盖章图片维护', async () => {
    const blob = new Blob(['xlsx'])
    mockedGet.mockResolvedValueOnce({ data: blob })
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'sheet-1', seal_image: { image_file_id: 'file-1' } } },
      headers: { etag: '"sheet-v2"' },
    })
    mockedDelete.mockResolvedValueOnce({
      data: { data: { id: 'sheet-1', seal_image: null } },
      headers: { etag: '"sheet-v3"' },
    })
    const file = new File(['seal'], 'seal.png', { type: 'image/png' })

    expect(await downloadSupplierPurchaseSheetXlsx('sheet-1')).toBe(blob)
    await uploadSupplierPurchaseSheetSealImage('sheet-1', file, '"sheet-v1"')
    await deleteSupplierPurchaseSheetSealImage('sheet-1', '"sheet-v2"')

    expect(mockedGet).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/sheet-1/download-xlsx/',
      { responseType: 'blob' },
    )
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/sheet-1/seal-image/',
      expect.any(FormData),
      { headers: { 'If-Match': '"sheet-v1"' } },
    )
    expect(mockedDelete).toHaveBeenCalledWith(
      '/api/v1/supplier-purchase-sheets/sheet-1/seal-image/',
      { headers: { 'If-Match': '"sheet-v2"' } },
    )
  })

  it('模板保存方式会明确传递覆盖当前版或建立新版本', async () => {
    mockedPatch.mockResolvedValue({ data: { data: { id: 'template-1' } } })
    const basePayload = {
      template_name: '辅料采购合同',
      version_name: '交期变量版',
      supplier_categories: ['AUXILIARY'],
      status: 'ACTIVE' as const,
      content_config: { payment_and_delivery: '月结。' },
      change_summary: '测试保存',
    }

    await updatePurchaseContractTemplate('template-1', { ...basePayload, save_mode: 'CURRENT' }, '"template-v1"')
    await updatePurchaseContractTemplate('template-1', { ...basePayload, save_mode: 'NEW_VERSION' }, '"template-v1"')

    expect(mockedPatch.mock.calls[0]?.[1]).toMatchObject({ save_mode: 'CURRENT' })
    expect(mockedPatch.mock.calls[1]?.[1]).toMatchObject({ save_mode: 'NEW_VERSION' })
  })
})
