import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedPurchaseOrders,
  PurchaseBatchType,
  PurchaseSetPricing,
  PurchaseOrderDetail,
  PurchaseOrderInput,
  PurchaseOrderOptions,
  PurchaseOrderFilterOptions,
  PurchaseOrderQuery,
  PurchaseOrderSource,
  PurchaseSheetOptions,
  SupplierPurchaseSheet,
  SupplierPurchaseSheetContent,
  PurchaseSheetPreview,
  PaginatedSupplierPurchaseSheets,
  PurchaseContractTemplate,
  VersionedPurchaseOrder,
  VersionedSupplierPurchaseSheet,
} from '@/types/purchaseOrder'

const basePath = '/api/v1/purchase-orders/'

function versioned(
  response: AxiosResponse<DataResponse<PurchaseOrderDetail> | PurchaseOrderDetail>,
): VersionedPurchaseOrder {
  const payload = response.data as DataResponse<PurchaseOrderDetail> & PurchaseOrderDetail
  return {
    data: payload.data || payload,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchPurchaseOrders(query: PurchaseOrderQuery): Promise<PaginatedPurchaseOrders> {
  const { data } = await apiClient.get<PaginatedPurchaseOrders>(basePath, { params: query })
  return data
}

export type PurchaseOrderOptionsScope = 'full' | 'suppliers' | 'sources' | 'detail'

export async function fetchPurchaseOrderOptions(scope: PurchaseOrderOptionsScope = 'full'): Promise<PurchaseOrderOptions> {
  const response = scope === 'full'
    ? await apiClient.get<DataResponse<PurchaseOrderOptions>>(`${basePath}options/`)
    : await apiClient.get<DataResponse<PurchaseOrderOptions>>(`${basePath}options/`, { params: { scope } })
  const { data } = response
  return data.data
}

export async function fetchPurchaseOrderSupplierOptions(): Promise<Pick<PurchaseOrderOptions, 'suppliers'>> {
  const { data } = await apiClient.get<DataResponse<Pick<PurchaseOrderOptions, 'suppliers'>>>(`${basePath}options/`, {
    params: { scope: 'suppliers' },
  })
  return data.data
}

export async function fetchPurchaseOrderFilterOptions(): Promise<PurchaseOrderFilterOptions> {
  const { data } = await apiClient.get<DataResponse<PurchaseOrderFilterOptions>>(`${basePath}filter-options/`)
  return data.data
}

export async function fetchPurchaseOrderSource(productionTaskId: string, bomId?: string): Promise<PurchaseOrderSource> {
  const { data } = await apiClient.get<DataResponse<PurchaseOrderSource>>(`${basePath}source/`, {
    params: {
      production_task_id: productionTaskId,
      ...(bomId ? { bom_id: bomId } : {}),
    },
  })
  return data.data
}

export async function fetchSamplePurchaseOrderSource(procurementRequestId: string): Promise<PurchaseOrderSource> {
  const { data } = await apiClient.get<DataResponse<PurchaseOrderSource>>(`${basePath}source/`, {
    params: { sample_procurement_request_id: procurementRequestId },
  })
  return data.data
}

export async function createPurchaseOrder(payload: PurchaseOrderInput): Promise<VersionedPurchaseOrder> {
  return versioned(await apiClient.post<DataResponse<PurchaseOrderDetail>>(basePath, payload))
}

export async function deletePurchaseOrder(id: string, etag?: string): Promise<void> {
  if (etag) {
    await apiClient.delete(`${basePath}${id}/`, { headers: { 'If-Match': etag } })
  } else {
    await apiClient.delete(`${basePath}${id}/`)
  }
}

export async function submitPurchaseOrder(id: string): Promise<PurchaseOrderDetail> {
  const { data } = await apiClient.post<DataResponse<PurchaseOrderDetail>>(`${basePath}${id}/submit/`)
  return data.data
}

export async function fetchPurchaseOrder(id: string): Promise<PurchaseOrderDetail> {
  return (await fetchVersionedPurchaseOrder(id)).data
}

export async function fetchVersionedPurchaseOrder(id: string): Promise<VersionedPurchaseOrder> {
  return versioned(await apiClient.get<DataResponse<PurchaseOrderDetail>>(`${basePath}${id}/`))
}

export async function updatePurchaseOrder(
  id: string,
  payload: {
    batch_type?: PurchaseBatchType
    skipped_line_ids?: string[]
    lines: Array<{
      id: string
      set_pricing?: PurchaseSetPricing | null
      actual_bar_count?: number | string | null
      raw_bar_length_m?: string | null
      raw_bar_weight_kg?: string | null
      actual_purchase_weight_kg?: string | null
      supplier_id: string | null
      delivery_date: string | null
      actual_purchase_quantity: string | null
      unit_price: string | null
    }>
  },
  etag: string,
): Promise<VersionedPurchaseOrder> {
  return versioned(await apiClient.patch<DataResponse<PurchaseOrderDetail>>(
    `${basePath}${id}/`,
    payload,
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function confirmPurchaseOrder(id: string): Promise<PurchaseOrderDetail> {
  return (await confirmVersionedPurchaseOrder(id)).data
}

export async function completePurchaseOrder(id: string, remark: string, etag: string): Promise<VersionedPurchaseOrder> {
  return versioned(await apiClient.post<DataResponse<PurchaseOrderDetail>>(
    `${basePath}${id}/complete/`, { remark }, { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function confirmVersionedPurchaseOrder(id: string): Promise<VersionedPurchaseOrder> {
  return versioned(await apiClient.post<DataResponse<PurchaseOrderDetail>>(`${basePath}${id}/confirm/`))
}

export async function fetchPurchaseSheetOptions(id: string): Promise<PurchaseSheetOptions> {
  const { data } = await apiClient.get<DataResponse<PurchaseSheetOptions>>(`${basePath}${id}/sheet-options/`)
  return data.data
}

export async function generatePurchaseSheets(
  id: string,
  assignments: Array<{ supplier_id: string; template_version_id: string }>,
): Promise<SupplierPurchaseSheet[]> {
  const { data } = await apiClient.post<DataResponse<SupplierPurchaseSheet[]>>(
    `${basePath}${id}/generate-sheets/`,
    { assignments },
  )
  return data.data
}

export async function ensureDefaultPurchaseSheets(id: string): Promise<void> {
  const options = await fetchPurchaseSheetOptions(id)
  if (options.existing_sheet_count) return
  if (options.purchase_order.status !== 'SUBMITTED') return
  if (!options.suppliers.length) throw new Error('暂无可生成采购表的供应商，请先完善采购明细。')
  if (!options.templates.length) throw new Error('暂无可用采购合同模板，请先在合同模板管理中启用模板。')
  // 沿用原模板页的默认值：先按供应商类别推荐，再取首个启用模板。
  const templateIds = new Set(options.templates.map(item => item.version_id))
  const assignments = options.suppliers.map(item => ({
    supplier_id: item.supplier_id,
    template_version_id: item.recommended_template_version_id && templateIds.has(item.recommended_template_version_id)
      ? item.recommended_template_version_id : options.templates[0]!.version_id,
  }))
  try {
    await generatePurchaseSheets(id, assignments)
  } catch (error) {
    const response = (error as { response?: { status?: number } }).response
    if (!response || response.status === 409 || (response.status ?? 0) >= 500) {
      // 超时或并发冲突时只回读已提交结果，不再次创建。
      const current = await fetchPurchaseSheetOptions(id)
      if (current.existing_sheet_count) return
    }
    throw error
  }
}

const sheetBasePath = '/api/v1/supplier-purchase-sheets/'

function versionedSheet(
  response: AxiosResponse<DataResponse<SupplierPurchaseSheet> | SupplierPurchaseSheet>,
): VersionedSupplierPurchaseSheet {
  const payload = response.data as DataResponse<SupplierPurchaseSheet> & SupplierPurchaseSheet
  return {
    data: payload.data || payload,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchSupplierPurchaseSheets(query: {
  page?: number
  page_size?: number
  purchase_order_id?: string
  status?: string
  supplier_id?: string
  q?: string
  is_current?: boolean
} = {}): Promise<PaginatedSupplierPurchaseSheets> {
  const { data } = await apiClient.get<PaginatedSupplierPurchaseSheets>(sheetBasePath, { params: query })
  return data
}

export async function fetchSupplierPurchaseSheetOptions(): Promise<{
  suppliers: Array<{ id: string; supplier_number: string; supplier_name: string }>
}> {
  const { data } = await apiClient.get<DataResponse<{
    suppliers: Array<{ id: string; supplier_number: string; supplier_name: string }>
  }>>(`${sheetBasePath}options/`)
  return data.data
}

export async function fetchSupplierPurchaseSheet(id: string): Promise<VersionedSupplierPurchaseSheet> {
  return versionedSheet(await apiClient.get<DataResponse<SupplierPurchaseSheet>>(`${sheetBasePath}${id}/`))
}

export async function saveSupplierPurchaseSheet(
  id: string,
  content: SupplierPurchaseSheet['content_snapshot'],
  etag: string,
): Promise<VersionedSupplierPurchaseSheet> {
  return versionedSheet(await apiClient.patch<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${id}/`,
    { content },
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function publishSupplierPurchaseSheet(id: string, etag: string): Promise<VersionedSupplierPurchaseSheet> {
  return versionedSheet(await apiClient.post<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${id}/publish/`,
    {},
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function createSupplierPurchaseSheetVersion(id: string, etag: string): Promise<VersionedSupplierPurchaseSheet> {
  return versionedSheet(await apiClient.post<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${id}/new-version/`,
    {},
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export function supplierPurchaseSheetLineImageUrl(sheetId: string, lineId: string, revision = ''): string {
  const query = revision ? `?v=${encodeURIComponent(revision)}` : ''
  return `${sheetBasePath}${sheetId}/line-images/${lineId}/${query}`
}

export async function uploadSupplierPurchaseSheetLineImage(
  sheetId: string,
  lineId: string,
  file: File,
  etag: string,
): Promise<VersionedSupplierPurchaseSheet> {
  const formData = new FormData()
  formData.append('file', file)
  return versionedSheet(await apiClient.post<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${sheetId}/line-images/${lineId}/`,
    formData,
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function deleteSupplierPurchaseSheetLineImage(
  sheetId: string,
  lineId: string,
  etag: string,
): Promise<VersionedSupplierPurchaseSheet> {
  return versionedSheet(await apiClient.delete<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${sheetId}/line-images/${lineId}/`,
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function fetchSupplierPurchaseSheetPreview(id: string, content?: SupplierPurchaseSheetContent): Promise<PurchaseSheetPreview> {
  const response = content
    ? await apiClient.post<DataResponse<PurchaseSheetPreview>>(`${sheetBasePath}${id}/preview/`, { content })
    : await apiClient.get<DataResponse<PurchaseSheetPreview>>(`${sheetBasePath}${id}/preview/`)
  return response.data.data
}

export async function downloadSupplierPurchaseSheetXlsx(id: string): Promise<Blob> {
  const { data } = await apiClient.get<Blob>(`${sheetBasePath}${id}/download-xlsx/`, { responseType: 'blob' })
  return data
}

export function supplierPurchaseSheetSealImageUrl(sheetId: string, revision = ''): string {
  const query = revision ? `?v=${encodeURIComponent(revision)}` : ''
  return `${sheetBasePath}${sheetId}/seal-image/${query}`
}

export async function uploadSupplierPurchaseSheetSealImage(
  sheetId: string,
  file: File,
  etag: string,
): Promise<VersionedSupplierPurchaseSheet> {
  const formData = new FormData()
  formData.append('file', file)
  return versionedSheet(await apiClient.post<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${sheetId}/seal-image/`,
    formData,
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function deleteSupplierPurchaseSheetSealImage(
  sheetId: string,
  etag: string,
): Promise<VersionedSupplierPurchaseSheet> {
  return versionedSheet(await apiClient.delete<DataResponse<SupplierPurchaseSheet>>(
    `${sheetBasePath}${sheetId}/seal-image/`,
    { headers: etag ? { 'If-Match': etag } : {} },
  ))
}

export async function batchDownloadSupplierPurchaseSheets(ids: string[]): Promise<Blob> {
  const { data } = await apiClient.post<Blob>(`${sheetBasePath}batch-download/`, { ids }, { responseType: 'blob' })
  return data
}

export async function batchPublishSupplierPurchaseSheets(ids: string[]): Promise<SupplierPurchaseSheet[]> {
  const { data } = await apiClient.post<DataResponse<SupplierPurchaseSheet[]>>(
    `${sheetBasePath}batch-publish/`,
    { ids },
  )
  return data.data
}

const templateBasePath = '/api/v1/purchase-contract-templates/'

export async function fetchPurchaseContractTemplates(query: { q?: string; status?: string; page?: number; page_size?: number } = {}): Promise<{
  data: PurchaseContractTemplate[]
  meta: { total: number }
}> {
  const { data } = await apiClient.get<{ data: PurchaseContractTemplate[]; meta: { total: number } }>(templateBasePath, {
    params: { page_size: 100, ...query },
  })
  return data
}

export async function createPurchaseContractTemplate(payload: {
  template_name: string
  version_name: string
  supplier_categories: string[]
  status: 'ACTIVE' | 'INACTIVE'
  content_config: Record<string, unknown>
  change_summary: string
}): Promise<PurchaseContractTemplate> {
  const { data } = await apiClient.post<DataResponse<PurchaseContractTemplate>>(templateBasePath, payload)
  return data.data
}

export async function updatePurchaseContractTemplate(
  id: string,
  payload: {
    template_name: string
    version_name: string
    supplier_categories: string[]
    status: 'ACTIVE' | 'INACTIVE'
    content_config: Record<string, unknown>
    change_summary: string
    save_mode: 'CURRENT' | 'NEW_VERSION'
  },
  etag: string,
): Promise<PurchaseContractTemplate> {
  const { data } = await apiClient.patch<DataResponse<PurchaseContractTemplate>>(
    `${templateBasePath}${id}/`,
    payload,
    { headers: etag ? { 'If-Match': etag } : {} },
  )
  return data.data
}

export async function fetchPurchaseContractTemplate(id: string): Promise<{ data: PurchaseContractTemplate; etag: string }> {
  const response = await apiClient.get<DataResponse<PurchaseContractTemplate>>(`${templateBasePath}${id}/`)
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}
