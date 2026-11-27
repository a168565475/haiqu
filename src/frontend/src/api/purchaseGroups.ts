import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedPurchaseGroups,
  PurchaseBatchInput,
  PurchaseBatchPageConfirmationInput,
  PurchaseGroup,
  PurchaseGroupFilterOptions,
  PurchaseGroupInput,
  PurchaseGroupQuery,
  PackagingPurchaseSource,
  PurchaseSupplierBatchResult,
  VersionedPurchaseGroup,
} from '@/types/purchaseGroup'
import type { PurchaseOrderDetail, PurchaseOrderOptions, VersionedPurchaseOrder } from '@/types/purchaseOrder'

const basePath = '/api/v1/purchase-groups/'
const packagingPath = '/api/v1/packaging-purchase-groups/'
const groupPath = (packaging?: boolean) => packaging ? packagingPath : basePath

function versionedGroup(response: AxiosResponse<DataResponse<PurchaseGroup>>): VersionedPurchaseGroup {
  return {
    data: response.data.data,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchPurchaseGroups(query: PurchaseGroupQuery = {}, packaging?: boolean): Promise<PaginatedPurchaseGroups> {
  const { data } = await apiClient.get<PaginatedPurchaseGroups>(groupPath(packaging), { params: query })
  return data
}

export async function fetchPurchaseGroupFilterOptions(packaging?: boolean): Promise<PurchaseGroupFilterOptions> {
  const { data } = await apiClient.get<DataResponse<PurchaseGroupFilterOptions>>(`${groupPath(packaging)}filter-options/`)
  return data.data
}

export async function fetchVersionedPurchaseGroup(id: string, batchSessionId?: string, packaging?: boolean): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.get<DataResponse<PurchaseGroup>>(`${groupPath(packaging)}${id}/`,
    batchSessionId ? { params: { batch_session_id: batchSessionId } } : undefined,
  ))
}

export async function createPurchaseGroup(payload: PurchaseGroupInput): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.post<DataResponse<PurchaseGroup>>(basePath, payload, { timeout: 60000 }))
}

export async function deletePurchaseGroup(id: string, etag: string, packaging?: boolean): Promise<void> {
  if (!etag) throw new Error('采购需求版本信息缺失，请刷新后重试。')
  await apiClient.delete(`${groupPath(packaging)}${id}/`, { headers: { 'If-Match': etag } })
}

export async function completePurchaseGroup(id: string, remark: string, etag: string, packaging?: boolean): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.post<DataResponse<PurchaseGroup>>(
    `${groupPath(packaging)}${id}/complete/`,
    { remark },
    { headers: { 'If-Match': etag } },
  ))
}

export async function createPurchaseBatch(
  groupId: string,
  payload: PurchaseBatchInput,
  groupEtag: string,
): Promise<VersionedPurchaseOrder> {
  const response = await apiClient.post<DataResponse<PurchaseOrderDetail>>(
    `${basePath}${groupId}/batches/`,
    payload,
    { headers: groupEtag ? { 'If-Match': groupEtag } : {}, timeout: 30000 },
  )
  return {
    data: response.data.data,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function submitPurchaseSupplierBatch(
  groupId: string,
  payload: PurchaseBatchInput,
  groupEtag: string,
): Promise<PurchaseSupplierBatchResult> {
  const response = await apiClient.post<DataResponse<PurchaseSupplierBatchResult['data']>>(
    `${basePath}${groupId}/submit-supplier-batch/`,
    payload,
    { headers: { 'If-Match': groupEtag }, timeout: 30000 },
  )
  return {
    data: response.data.data,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function confirmPurchaseBatchPage(
  groupId: string,
  payload: PurchaseBatchPageConfirmationInput,
  groupEtag: string,
): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.post<DataResponse<PurchaseGroup>>(
    `${basePath}${groupId}/confirm-batch-page/`, payload, { headers: { 'If-Match': groupEtag }, timeout: 30000 },
  ))
}

export async function fetchPackagingPurchaseSources(): Promise<PackagingPurchaseSource[]> {
  const { data } = await apiClient.get<DataResponse<PackagingPurchaseSource[]>>(`${packagingPath}sources/`)
  return data.data
}

export async function fetchPackagingPurchaseOptions(): Promise<PurchaseOrderOptions> {
  const { data } = await apiClient.get<DataResponse<PurchaseOrderOptions>>(`${packagingPath}options/`)
  return data.data
}

export async function preparePackagingPurchase(sources: PackagingPurchaseSource[]): Promise<PurchaseGroup[]> {
  const { data } = await apiClient.post<DataResponse<PurchaseGroup[]>>(`${packagingPath}prepare/`, {
    sources: packagingSourceRows(sources),
  })
  return data.data
}

function packagingSourceRows(sources: PackagingPurchaseSource[]) {
  return sources.map(({ production_task_id, bom_id, source_revision }) => ({ production_task_id, bom_id, source_revision }))
}

function versionedPackagingPage(response: AxiosResponse<DataResponse<PurchaseGroup[]>>) {
  return {
    groups: response.data.data,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function preparePackagingPurchasePage(sources: PackagingPurchaseSource[], groupIds: string[], sessionId: string) {
  return versionedPackagingPage(await apiClient.post<DataResponse<PurchaseGroup[]>>(`${packagingPath}prepare/`, {
    sources: packagingSourceRows(sources), group_ids: groupIds, batch_session_id: sessionId,
  }))
}

export async function fetchPackagingPurchasePage(groupIds: string[], sessionId: string) {
  const params = new URLSearchParams({ batch_session_id: sessionId })
  for (const id of groupIds) params.append('group_ids', id)
  return versionedPackagingPage(await apiClient.get<DataResponse<PurchaseGroup[]>>(`${packagingPath}batch-page/`, { params }))
}

export async function writePackagingPurchasePage(action: 'save' | 'confirm', groupIds: string[], sessionId: string, etag: string, batch?: PurchaseBatchInput) {
  return versionedPackagingPage(await apiClient.post<DataResponse<PurchaseGroup[]>>(
    `${packagingPath}${action}-page/`,
    { group_ids: groupIds, batch_session_id: sessionId, ...(batch ? { batch } : {}) },
    { headers: { 'If-Match': etag }, timeout: 30000 },
  ))
}
