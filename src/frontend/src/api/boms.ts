import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  BomCreationMethod,
  BomAuxiliaryProductOption,
  BomDetail,
  BomDraftLineImage,
  BomEditorReferenceOptions,
  BomHardwareMaterialGroup,
  BomHardwareMaterialQuery,
  BomLineImage,
  BomMaterialPickerQuery,
  BomOptions,
  BomFilterOptions,
  BomPlasticMaterialQuery,
  BomQuery,
  BomSectionInput,
  BomStats,
  BomWorkbookPreview,
  PaginatedBoms,
  PaginatedBomHardwareMaterials,
  PaginatedBomPackagingMaterials,
  PaginatedBomPlasticMaterials,
  PaginatedBomSemiFinishedMaterials,
  VersionedBom,
} from '@/types/bom'
import type { ProductionTaskProductInput } from '@/types/productionTask'

const basePath = '/api/v1/boms/'
const workbookRequestTimeout = 180_000

export async function fetchBomFilterOptions(): Promise<BomFilterOptions> {
  const { data } = await apiClient.get<DataResponse<BomFilterOptions>>(`${basePath}options/`, { params: { scope: 'filters' } })
  return data.data
}

export async function fetchBoms(query: BomQuery): Promise<PaginatedBoms> {
  const { data } = await apiClient.get<PaginatedBoms>(basePath, { params: query })
  return data
}

export async function exportBoms(query: BomQuery, ids: string[] = []): Promise<{ blob: Blob; count: number | null }> {
  const config = {
    params: { ...query, page: undefined, page_size: undefined },
    responseType: 'blob' as const,
    timeout: 60_000,
  }
  const response = ids.length
    ? await apiClient.post<Blob>(`${basePath}export/`, { ids }, config)
    : await apiClient.get<Blob>(`${basePath}export/`, config)
  const parsedCount = Number(response.headers['x-export-count'])
  return { blob: response.data, count: Number.isInteger(parsedCount) && parsedCount >= 0 ? parsedCount : null }
}

export async function fetchBomHardwareMaterials(query: BomHardwareMaterialQuery): Promise<PaginatedBomHardwareMaterials> {
  const { data } = await apiClient.get<PaginatedBomHardwareMaterials>(`${basePath}hardware-materials/`, { params: query })
  return data
}

export async function fetchBomHardwareMaterialGroups(): Promise<BomHardwareMaterialGroup[]> {
  const { data } = await apiClient.get<DataResponse<BomHardwareMaterialGroup[]>>(`${basePath}hardware-material-groups/`)
  return data.data
}

export async function fetchBomPlasticMaterials(query: BomPlasticMaterialQuery): Promise<PaginatedBomPlasticMaterials> {
  const { data } = await apiClient.get<PaginatedBomPlasticMaterials>(`${basePath}plastic-materials/`, { params: query })
  return data
}

export async function fetchBomPlasticMaterialGroups(): Promise<BomHardwareMaterialGroup[]> {
  const { data } = await apiClient.get<DataResponse<BomHardwareMaterialGroup[]>>(`${basePath}plastic-material-groups/`)
  return data.data
}

export async function fetchBomPackagingMaterials(query: BomMaterialPickerQuery): Promise<PaginatedBomPackagingMaterials> {
  const { data } = await apiClient.get<PaginatedBomPackagingMaterials>(`${basePath}packaging-materials/`, { params: query })
  return data
}

export async function fetchBomPackagingMaterialGroups(): Promise<BomHardwareMaterialGroup[]> {
  const { data } = await apiClient.get<DataResponse<BomHardwareMaterialGroup[]>>(`${basePath}packaging-material-groups/`)
  return data.data
}

export async function fetchBomSemiFinishedMaterials(query: BomMaterialPickerQuery): Promise<PaginatedBomSemiFinishedMaterials> {
  const { data } = await apiClient.get<PaginatedBomSemiFinishedMaterials>(`${basePath}semi-finished-materials/`, { params: query })
  return data
}

export async function fetchBomSemiFinishedMaterialGroups(): Promise<BomHardwareMaterialGroup[]> {
  const { data } = await apiClient.get<DataResponse<BomHardwareMaterialGroup[]>>(`${basePath}semi-finished-material-groups/`)
  return data.data
}

export async function fetchBomEditorReferenceOptions(): Promise<BomEditorReferenceOptions> {
  const { data } = await apiClient.get<DataResponse<BomEditorReferenceOptions>>(`${basePath}editor-reference-options/`)
  return data.data
}

export async function createBomAuxiliaryReference(payload: {
  product_name: string
  unit_name: string
  specification: string
  color: string
  material: string
}): Promise<BomAuxiliaryProductOption> {
  const { data } = await apiClient.post<DataResponse<BomAuxiliaryProductOption>>(
    `${basePath}create-auxiliary-reference/`,
    payload,
  )
  return data.data
}

export async function fetchBom(id: string): Promise<BomDetail> {
  const { data } = await apiClient.get<DataResponse<BomDetail>>(`${basePath}${encodeURIComponent(id)}/`)
  return data.data
}

function versionedBom(response: { data: DataResponse<BomDetail>; headers: Record<string, unknown> }): VersionedBom {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchBomForEdit(id: string): Promise<VersionedBom> {
  return versionedBom(await apiClient.get<DataResponse<BomDetail>>(`${basePath}${encodeURIComponent(id)}/`))
}

export async function archiveBom(id: string, etag: string): Promise<void> {
  await apiClient.post(
    `${basePath}${encodeURIComponent(id)}/archive/`,
    {},
    { headers: { 'If-Match': etag } },
  )
}

export async function saveBomDraft(id: string, sections: BomSectionInput[], etag: string): Promise<VersionedBom> {
  const writableSections = sections.map((section) => ({
    ...section,
    lines: section.lines.map((line) => {
      const { images, draft_images: draftImages, draft_key: draftKey, ...writableLine } = line
      void images
      void draftKey
      const draftImageIds = line.id ? [] : (draftImages || []).map((image) => image.id)
      return draftImageIds.length ? { ...writableLine, draft_image_ids: draftImageIds } : writableLine
    }),
  }))
  return versionedBom(await apiClient.patch<DataResponse<BomDetail>>(
    `${basePath}${encodeURIComponent(id)}/`,
    { sections: writableSections },
    { headers: { 'If-Match': etag } },
  ))
}

export async function syncBomOrderQuantity(id: string, etag: string): Promise<VersionedBom> {
  return versionedBom(await apiClient.post<DataResponse<BomDetail>>(
    `${basePath}${encodeURIComponent(id)}/sync-order-quantity/`,
    {},
    { headers: { 'If-Match': etag } },
  ))
}

export async function verifyBom(id: string, quantityConfirmationReason: string, etag: string): Promise<VersionedBom> {
  return versionedBom(await apiClient.post<DataResponse<BomDetail>>(
    `${basePath}${encodeURIComponent(id)}/verify/`,
    { quantity_confirmation_reason: quantityConfirmationReason },
    { headers: { 'If-Match': etag } },
  ))
}

export async function confirmBomProduct(
  id: string,
  payload: { product_id: string; product_color_id: string; color_code?: string },
  etag: string,
): Promise<VersionedBom> {
  return versionedBom(await apiClient.post<DataResponse<BomDetail>>(
    `${basePath}${encodeURIComponent(id)}/confirm-product/`,
    payload,
    { headers: { 'If-Match': etag } },
  ))
}

interface BomLineImagesPayload {
  images?: BomLineImage[]
}

function imageMutationResult(
  response: { data?: DataResponse<BomLineImage[] | BomLineImagesPayload>; headers?: Record<string, unknown> },
): { images: BomLineImage[] | null; etag: string } {
  const payload = response.data?.data
  return {
    images: Array.isArray(payload) ? payload : payload?.images || null,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function uploadBomLineImages(
  bomId: string,
  lineId: string,
  files: File[],
  etag: string,
): Promise<{ images: BomLineImage[] | null; etag: string }> {
  const body = new FormData()
  for (const file of files) body.append('files', file)
  const response = await apiClient.post<DataResponse<BomLineImage[] | BomLineImagesPayload>>(
    `${basePath}${encodeURIComponent(bomId)}/lines/${encodeURIComponent(lineId)}/images/`,
    body,
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  )
  return imageMutationResult(response)
}

export async function deleteBomLineImage(
  bomId: string,
  lineId: string,
  imageId: string,
  etag: string,
): Promise<{ images: BomLineImage[] | null; etag: string }> {
  const response = await apiClient.delete<DataResponse<BomLineImage[] | BomLineImagesPayload>>(
    `${basePath}${encodeURIComponent(bomId)}/lines/${encodeURIComponent(lineId)}/images/${encodeURIComponent(imageId)}/`,
    { headers: { 'If-Match': etag } },
  )
  return imageMutationResult(response)
}

interface BomDraftLineImagesPayload {
  images?: BomDraftLineImage[]
}

function draftImageMutationResult(
  response: { data?: DataResponse<BomDraftLineImage[] | BomDraftLineImagesPayload>; headers?: Record<string, unknown> },
): { images: BomDraftLineImage[] | null; etag: string } {
  const payload = response.data?.data
  return {
    images: Array.isArray(payload) ? payload : payload?.images || null,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function uploadBomDraftLineImages(
  bomId: string,
  draftKey: string,
  files: File[],
  etag: string,
): Promise<{ images: BomDraftLineImage[] | null; etag: string }> {
  const body = new FormData()
  body.append('draft_key', draftKey)
  for (const file of files) body.append('files', file)
  const response = await apiClient.post<DataResponse<BomDraftLineImage[] | BomDraftLineImagesPayload>>(
    `${basePath}${encodeURIComponent(bomId)}/draft-line-images/`,
    body,
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  )
  return draftImageMutationResult(response)
}

export async function deleteBomDraftLineImage(
  bomId: string,
  imageId: string,
  etag: string,
): Promise<{ etag: string }> {
  const response = await apiClient.delete<DataResponse<{ deleted_id: string }>>(
    `${basePath}${encodeURIComponent(bomId)}/draft-line-images/${encodeURIComponent(imageId)}/`,
    { headers: { 'If-Match': etag } },
  )
  return { etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '' }
}

export function bomLineImageUrl(relativeUrl: string): string {
  return new URL(relativeUrl, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}

export async function fetchBomStats(query: BomQuery = {}): Promise<BomStats> {
  const { data } = await apiClient.get<DataResponse<BomStats>>(`${basePath}stats/`, { params: query })
  return data.data
}

export async function fetchBomOptions(taskQuery = ''): Promise<BomOptions> {
  const params = taskQuery.trim() ? { task_q: taskQuery.trim() } : undefined
  const { data } = await apiClient.get<DataResponse<BomOptions>>(`${basePath}options/`, { params })
  return data.data
}

export async function previewBomWorkbook(
  productionTaskProductId: string,
  workbook: File,
  productUpdate?: ProductionTaskProductInput | null,
): Promise<BomWorkbookPreview> {
  const form = new FormData()
  form.append('production_task_product_id', productionTaskProductId)
  form.append('workbook', workbook)
  if (productUpdate) form.append('production_task_product_update', JSON.stringify(productUpdate))
  const { data } = await apiClient.post<DataResponse<BomWorkbookPreview>>(`${basePath}preview-import/`, form, {
    timeout: workbookRequestTimeout,
  })
  return data.data
}

export async function createBom(input: {
  productionTaskProductId: string
  creationMethod: BomCreationMethod
  workbook?: File | null
  sourceBomId?: string
  productUpdate?: ProductionTaskProductInput | null
  productImages?: File[]
  detailImages?: Record<string, File | null>
  taskEtag?: string
  quantityDifferenceReason?: string
}): Promise<BomDetail> {
  const form = new FormData()
  form.append('production_task_product_id', input.productionTaskProductId)
  form.append('creation_method', input.creationMethod)
  if (input.workbook) form.append('workbook', input.workbook)
  if (input.sourceBomId) form.append('source_bom_id', input.sourceBomId)
  if (input.quantityDifferenceReason?.trim()) {
    form.append('quantity_difference_reason', input.quantityDifferenceReason.trim())
  }
  if (input.productUpdate) {
    form.append('production_task_product_update', JSON.stringify(input.productUpdate))
    for (const file of input.productImages || []) {
      form.append(`product_image_${input.productUpdate.client_key}`, file)
    }
    Object.entries(input.detailImages || {}).forEach(([key, file]) => {
      if (file) form.append(`detail_image_${key}`, file)
    })
  }
  const { data } = await apiClient.post<DataResponse<BomDetail>>(basePath, form, {
    timeout: workbookRequestTimeout,
    headers: input.productUpdate && input.taskEtag ? { 'If-Match': input.taskEtag } : undefined,
  })
  return data.data
}

export async function fetchBomFlowMaterials(kind: 'pipe' | 'fabric', q = ''): Promise<PaginatedBomHardwareMaterials> {
  const { data } = await apiClient.get<PaginatedBomHardwareMaterials>(`${basePath}${kind}-materials/`, { params: { q, page_size: 100 } })
  return data
}

export async function previewBomMaterialFlow(input: { kind: 'PIPE' | 'FABRIC'; order_quantity: string; cutting_length_mm?: string; pieces_per_product?: string; pieces_per_bar?: string; unit_consumption?: string }) {
  const { data } = await apiClient.post<DataResponse<{ suggested_purchase_meters: string; raw_bar_length_m?: string; suggested_bar_count?: number }>>(`${basePath}material-flow-preview/`, input)
  return data.data
}
