import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  archiveBom,
  createBomAuxiliaryReference,
  createBom,
  deleteBomDraftLineImage,
  deleteBomLineImage,
  exportBoms,
  fetchBomForEdit,
  fetchBomHardwareMaterialGroups,
  fetchBomHardwareMaterials,
  fetchBomPipeMaterialMatches,
  fetchBomOptions,
  fetchBoms,
  previewBomWorkbook,
  previewBomMaterialSave,
  saveBomDraft,
  syncBomOrderQuantity,
  uploadBomLineImages,
  uploadBomDraftLineImages,
  verifyBom,
} from '@/api/boms'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({
  apiClient: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPatch = vi.mocked(apiClient.patch)
const mockedPost = vi.mocked(apiClient.post)
const mockedDelete = vi.mocked(apiClient.delete)

describe('BOM API', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPatch.mockReset()
    mockedPost.mockReset()
    mockedDelete.mockReset()
  })

  it('新增原料预检与确认使用相同整单字段，预检只发 POST，确认只发一次 PATCH', async () => {
    const preview = { confirmation_token: 'approved', new_materials: [] }
    mockedPost.mockResolvedValueOnce({ data: { data: preview } })
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'bom-1', status: 'VERIFIED' } }, headers: { etag: 'v2' } })
    const pending = { material_number: 'NEW-1', item_type: 'SEMI_FINISHED', material_name: '床面' }
    const sections = [{ title: '裁剪明细', section_type: 'FABRIC', lines: [{ client_key: 'draft-id', source_cutting_material_id: null, pending_raw_material: pending, images: [], draft_key: 'images-draft', draft_images: [{ id: 'image-1' }] }] }]
    const intent = { intent: 'verify' as const, quantity_confirmation_reason: '核对完成' }
    expect(await previewBomMaterialSave('bom-1', sections as never, 'v1', intent)).toEqual(preview)
    expect(mockedPatch).not.toHaveBeenCalled()
    const body = { ...intent, sections: [{ title: '裁剪明细', section_type: 'FABRIC', lines: [{ client_key: 'draft-id', source_cutting_material_id: null, pending_raw_material: pending, draft_image_ids: ['image-1'] }] }] }
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/boms/bom-1/material-save-preview/', body, { headers: { 'If-Match': 'v1' } })
    await saveBomDraft('bom-1', sections as never, 'v1', { ...intent, confirmation_token: 'approved' })
    expect(mockedPatch).toHaveBeenCalledWith('/api/v1/boms/bom-1/', { ...body, confirmation_token: 'approved' }, { headers: { 'If-Match': 'v1' } })
    expect(mockedPost).toHaveBeenCalledTimes(1)
    expect(sections[0]!.lines[0]!.draft_images).toEqual([{ id: 'image-1' }])
  })

  it('管材匹配通过只读接口发送精确参数并保留后端自动匹配决定', async () => {
    const result = { candidates: [{ id: 'raw-1', length: '6' }], automatic_source_id: null, reason: 'needs_review' }
    mockedGet.mockResolvedValueOnce({ data: { data: result } })
    const query = { material: '铁-硬管', diameter: '25×15', thickness: '1.5', tube_shape: '矩形', raw_bar_length_m: '5.73' }
    expect(await fetchBomPipeMaterialMatches(query)).toEqual(result)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/boms/pipe-material-matches/', { params: query })
    expect(mockedPost).not.toHaveBeenCalled()
  })

  it('裁剪保存和预检省略历史耗米字段，面料采购单耗仍原样提交', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { confirmation_token: null, new_materials: [] } } })
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'bom-1' } }, headers: { etag: 'v2' } })
    const sections = [
      { title: '面料类', section_type: 'FABRIC', lines: [{ unit_consumption: '1.5', total_consumption: '150' }] },
      { title: '裁剪明细', section_type: 'FABRIC', lines: [{ cutting_pieces_per_set: 2, cutting_sets_per_product: 3, fabric_meters_per_piece: '0.5', fabric_meters_per_set: '1', unit_consumption: '0.5', total_consumption: '300' }] },
    ]
    await previewBomMaterialSave('bom-1', sections as never, 'v1', { intent: 'draft' })
    await saveBomDraft('bom-1', sections as never, 'v1', { intent: 'draft' })
    const expected = { sections: [sections[0], { title: '裁剪明细', section_type: 'FABRIC', lines: [{ cutting_pieces_per_set: 2, cutting_sets_per_product: 3 }] }], intent: 'draft' }
    expect(mockedPost.mock.calls[0]![1]).toEqual(expected)
    expect(mockedPatch.mock.calls[0]![1]).toEqual(expected)
    expect(sections[1]!.lines[0]).toHaveProperty('fabric_meters_per_set', '1')
  })

  it('同一保存请求保留面料临时标识与裁剪引用，不传图片草稿 key', async () => {
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'bom-1', sections: [] } }, headers: { etag: 'v2' } })
    const key = '11111111-1111-4111-8111-111111111111'
    const sections = [
      { title: '面料类', section_type: 'FABRIC', lines: [{ part_name: '牛津布', client_key: key, draft_key: 'image-key' }] },
      { title: '裁剪明细', section_type: 'FABRIC', lines: [{ part_name: '床面', fabric_source_line_id: null, fabric_source_client_key: key }] },
    ]
    await saveBomDraft('bom-1', sections as never, 'v1')
    expect(mockedPatch).toHaveBeenCalledTimes(1)
    expect(mockedPatch).toHaveBeenCalledWith('/api/v1/boms/bom-1/', {
      sections: [
        { title: '面料类', section_type: 'FABRIC', lines: [{ part_name: '牛津布', client_key: key }] },
        sections[1],
      ],
    }, { headers: { 'If-Match': 'v1' } })
  })

  it('列表筛选参数原样交给后端', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } } })

    await fetchBoms({ q: 'HT-26134', status: 'PENDING_CONFIRMATION', page: 1, page_size: 20 })

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/boms/', {
      params: { q: 'HT-26134', status: 'PENDING_CONFIRMATION', page: 1, page_size: 20 },
    })
  })

  it('导出当前筛选全部时移除分页且不伪造勾选范围', async () => {
    mockedGet.mockResolvedValueOnce({ data: new Blob(['csv']), headers: {} })

    await exportBoms({ page: 2, page_size: 50, q: 'HT-26134', status: 'VERIFIED' })

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/boms/export/', {
      params: { page: undefined, page_size: undefined, q: 'HT-26134', status: 'VERIFIED' },
      responseType: 'blob',
      timeout: 60_000,
    })
  })

  it('预览与创建均以 multipart 上传原始 Excel', async () => {
    const workbook = new File(['test'], 'HT26134.xls', { type: 'application/vnd.ms-excel' })
    mockedPost
      .mockResolvedValueOnce({ data: { data: { file_name: workbook.name } } })
      .mockResolvedValueOnce({ data: { data: { id: 'bom-1', bom_number: 'BOM-HT26134-V1' } } })

    await previewBomWorkbook('product-line-1', workbook)
    await createBom({
      productionTaskProductId: 'product-line-1',
      creationMethod: 'IMPORT',
      workbook,
      quantityDifferenceReason: 'Excel原表多100件，按当前任务数量生产。',
    })

    const previewBody = mockedPost.mock.calls[0]?.[1]
    const createBody = mockedPost.mock.calls[1]?.[1]
    const previewConfig = mockedPost.mock.calls[0]?.[2]
    const createConfig = mockedPost.mock.calls[1]?.[2]
    expect(previewBody).toBeInstanceOf(FormData)
    expect((previewBody as FormData).get('production_task_product_id')).toBe('product-line-1')
    expect((previewBody as FormData).get('workbook')).toBe(workbook)
    expect(createBody).toBeInstanceOf(FormData)
    expect((createBody as FormData).get('production_task_product_id')).toBe('product-line-1')
    expect((createBody as FormData).get('creation_method')).toBe('IMPORT')
    expect((createBody as FormData).get('workbook')).toBe(workbook)
    expect((createBody as FormData).get('quantity_difference_reason')).toBe('Excel原表多100件，按当前任务数量生产。')
    expect(previewConfig).toMatchObject({ timeout: 180_000 })
    expect(createConfig).toMatchObject({ timeout: 180_000 })
  })

  it('更换产品时把生产任务明细、图片和任务 ETag 与 BOM 一次提交', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'bom-1', bom_number: 'BOM0000352' } } })
    const productImage = new File(['product'], 'product.png', { type: 'image/png' })
    const detailImage = new File(['detail'], 'detail.png', { type: 'image/png' })
    const productUpdate = {
      client_key: 'line-1', product_id: 'product-2', product_color_id: 'color-1', color_code: 'G01',
      quantity: '20', unit_id: 'unit-1', currency_id: 'currency-1', unit_price: '5.0000', exchange_rate: '1.000',
      special_requirements: '', packaging_method: '', retained_image_ids: [],
      details: [{ client_key: 'detail-1', template_key: 'tube', detail_type: '材料', category_label: '管材', is_selected: true, description: '要求' }],
    }

    await createBom({
      productionTaskProductId: 'line-1', creationMethod: 'BLANK', productUpdate,
      productImages: [productImage], detailImages: { 'detail-1': detailImage }, taskEtag: '"task-v1"',
    })

    const body = mockedPost.mock.calls[0]?.[1] as FormData
    expect(JSON.parse(String(body.get('production_task_product_update')))).toEqual(productUpdate)
    expect(body.getAll('product_image_line-1')).toEqual([productImage])
    expect(body.get('detail_image_detail-1')).toBe(detailImage)
    expect(mockedPost.mock.calls[0]?.[2]).toMatchObject({ headers: { 'If-Match': '"task-v1"' } })
  })

  it('生产任务下拉搜索把订单号交给后端匹配', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { production_task_products: [] } } })

    await fetchBomOptions(' ORDER-BOM-001 ')

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/boms/options/', {
      params: { task_q: 'ORDER-BOM-001' },
    })
  })

  it('五金列表传递精确品名分组并读取分组数量', async () => {
    mockedGet
      .mockResolvedValueOnce({ data: { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } } })
      .mockResolvedValueOnce({ data: { data: [{ material_name: '铆钉', count: 110 }] } })

    await fetchBomHardwareMaterials({ page: 1, page_size: 20, q: 'M4', material_name: '铆钉' })
    const groups = await fetchBomHardwareMaterialGroups()

    expect(mockedGet).toHaveBeenNthCalledWith(1, '/api/v1/boms/hardware-materials/', {
      params: { page: 1, page_size: 20, q: 'M4', material_name: '铆钉' },
    })
    expect(mockedGet).toHaveBeenNthCalledWith(2, '/api/v1/boms/hardware-material-groups/')
    expect(groups).toEqual([{ material_name: '铆钉', count: 110 }])
  })

  it('编辑读取、保存、同步数量和提交校验均传递 ETag', async () => {
    const response = { data: { data: { id: 'bom-1' } }, headers: { etag: '"bom-etag"' } }
    mockedGet.mockResolvedValueOnce(response)
    mockedPatch.mockResolvedValueOnce(response)
    mockedPost.mockResolvedValue(response)

    const detail = await fetchBomForEdit('bom-1')
    await saveBomDraft('bom-1', [], detail.etag)
    await syncBomOrderQuantity('bom-1', detail.etag)
    await verifyBom('bom-1', '按订单数量执行', detail.etag)

    expect(detail.etag).toBe('"bom-etag"')
    expect(mockedPatch).toHaveBeenCalledWith('/api/v1/boms/bom-1/', { sections: [] }, {
      headers: { 'If-Match': '"bom-etag"' },
    })
    expect(mockedPost).toHaveBeenNthCalledWith(1, '/api/v1/boms/bom-1/sync-order-quantity/', {}, {
      headers: { 'If-Match': '"bom-etag"' },
    })
    expect(mockedPost).toHaveBeenNthCalledWith(2, '/api/v1/boms/bom-1/verify/', {
      quantity_confirmation_reason: '按订单数量执行',
    }, {
      headers: { 'If-Match': '"bom-etag"' },
    })
  })

  it('列表删除使用归档接口并携带当前 BOM ETag', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'bom-1', archived: true } } })

    await archiveBom('bom-1', '"bom-etag"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/boms/bom-1/archive/', {}, {
      headers: { 'If-Match': '"bom-etag"' },
    })
  })

  it('辅料新增提交到 BOM 专用基础配置入口', async () => {
    const created = {
      id: 'accessory-1',
      product_name: '测试辅料',
      unit_name: '个',
      pinyin_search: 'ceshifuliao csfl',
      specifications: [{ id: 'spec-1', specification_value: '10mm' }],
      colors: [{ id: 'color-1', color_name: '黑色' }],
    }
    mockedPost.mockResolvedValueOnce({ data: { data: created } })
    const payload = {
      product_name: '测试辅料',
      unit_name: '个',
      specification: '10mm',
      color: '黑色',
      material: '尼龙',
    }

    await expect(createBomAuxiliaryReference(payload)).resolves.toEqual(created)
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/boms/create-auxiliary-reference/', payload)
  })

  it('裁剪图片批量上传和删除均使用当前 BOM ETag', async () => {
    const image = {
      id: 'image-1',
      file_id: 'file-1',
      position: 1,
      name: 'cutting.png',
      content_type: 'image/png',
      size_bytes: 128,
      content_url: '/api/v1/boms/bom-1/lines/line-1/images/image-1/content/',
    }
    mockedPost.mockResolvedValueOnce({ data: { data: [image] }, headers: { etag: '"v2"' } })
    mockedDelete.mockResolvedValueOnce({ data: { data: { deleted_id: image.id } }, headers: { etag: '"v3"' } })
    const first = new File(['first'], 'first.png', { type: 'image/png' })
    const second = new File(['second'], 'second.jpg', { type: 'image/jpeg' })

    const uploaded = await uploadBomLineImages('bom-1', 'line-1', [first, second], '"v1"')
    const uploadBody = mockedPost.mock.calls[0]?.[1] as FormData
    const deleted = await deleteBomLineImage('bom-1', 'line-1', image.id, uploaded.etag)

    expect(uploadBody.getAll('files')).toEqual([first, second])
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/boms/bom-1/lines/line-1/images/',
      uploadBody,
      { headers: { 'If-Match': '"v1"' }, timeout: 120_000 },
    )
    expect(uploaded).toEqual({ images: [image], etag: '"v2"' })
    expect(mockedDelete).toHaveBeenCalledWith(
      '/api/v1/boms/bom-1/lines/line-1/images/image-1/',
      { headers: { 'If-Match': '"v2"' } },
    )
    expect(deleted).toEqual({ images: null, etag: '"v3"' })
  })

  it('未保存裁剪行按稳定标识上传暂存图片并支持清理', async () => {
    const image = {
      id: 'draft-image-1',
      draft_key: 'd172f63d-789d-49ee-a85f-e5948ef839fd',
      position: 1,
      name: 'draft.png',
      content_type: 'image/png',
      size_bytes: 256,
      content_url: '/api/v1/boms/bom-1/draft-line-images/draft-image-1/content/',
      expires_at: '2026-09-06T10:00:00+08:00',
    }
    mockedPost.mockResolvedValueOnce({ data: { data: [image] }, headers: { etag: '"v1"' } })
    mockedDelete.mockResolvedValueOnce({ data: { data: { deleted_id: image.id } }, headers: { etag: '"v1"' } })
    const file = new File(['draft'], 'draft.png', { type: 'image/png' })

    const uploaded = await uploadBomDraftLineImages('bom-1', image.draft_key, [file], '"v1"')
    const uploadBody = mockedPost.mock.calls[0]?.[1] as FormData
    const deleted = await deleteBomDraftLineImage('bom-1', image.id, uploaded.etag)

    expect(uploadBody.get('draft_key')).toBe(image.draft_key)
    expect(uploadBody.getAll('files')).toEqual([file])
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/boms/bom-1/draft-line-images/',
      uploadBody,
      { headers: { 'If-Match': '"v1"' }, timeout: 120_000 },
    )
    expect(uploaded).toEqual({ images: [image], etag: '"v1"' })
    expect(mockedDelete).toHaveBeenCalledWith(
      '/api/v1/boms/bom-1/draft-line-images/draft-image-1/',
      { headers: { 'If-Match': '"v1"' } },
    )
    expect(deleted).toEqual({ etag: '"v1"' })
  })

  it('保存 BOM 时只提交未保存裁剪行的暂存图片 ID', async () => {
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'bom-1' } }, headers: { etag: '"v2"' } })
    const sections = [{
      section_type: 'FABRIC',
      title: '裁剪明细',
      lines: [{
        source_cutting_material_id: 'material-1',
        part_name: '裁片 A',
        images: [],
        draft_key: 'd172f63d-789d-49ee-a85f-e5948ef839fd',
        draft_images: [
          { id: 'draft-image-1' },
          { id: 'draft-image-2' },
        ],
      }, {
        id: 'line-existing',
        source_cutting_material_id: 'material-2',
        part_name: '已保存裁片',
        images: [{ id: 'formal-image-1' }],
        draft_key: '85714da5-b275-41cf-aa1f-92728d64128b',
        draft_images: [{ id: 'should-not-submit' }],
      }],
    }] as unknown as Parameters<typeof saveBomDraft>[1]

    await saveBomDraft('bom-1', sections, '"v1"')

    expect(mockedPatch).toHaveBeenCalledWith('/api/v1/boms/bom-1/', {
      sections: [{
        section_type: 'FABRIC',
        title: '裁剪明细',
        lines: [{
          source_cutting_material_id: 'material-1',
          part_name: '裁片 A',
          draft_image_ids: ['draft-image-1', 'draft-image-2'],
        }, {
          id: 'line-existing',
          source_cutting_material_id: 'material-2',
          part_name: '已保存裁片',
        }],
      }],
    }, { headers: { 'If-Match': '"v1"' } })
  })

  it('未保存的管材用料行也会提交暂存图片 ID', async () => {
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'bom-1' } }, headers: { etag: '"v2"' } })
    const sections = [{
      section_type: 'PROFILE',
      title: '管材类',
      lines: [{
        part_name: '横管',
        images: [],
        draft_key: '43d621cc-792c-453a-a9a8-98511a4f6f44',
        draft_images: [{ id: 'profile-draft-image-1' }],
      }],
    }] as unknown as Parameters<typeof saveBomDraft>[1]

    await saveBomDraft('bom-1', sections, '"v1"')

    expect(mockedPatch).toHaveBeenCalledWith('/api/v1/boms/bom-1/', {
      sections: [{
        section_type: 'PROFILE',
        title: '管材类',
        lines: [{
          part_name: '横管',
          draft_image_ids: ['profile-draft-image-1'],
        }],
      }],
    }, { headers: { 'If-Match': '"v1"' } })
  })
})
