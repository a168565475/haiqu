import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedPurchaseGroups,
  PurchaseBatchInput,
  PurchaseGroup,
  PurchaseGroupFilterOptions,
  PurchaseGroupInput,
  PurchaseGroupQuery,
  VersionedPurchaseGroup,
} from '@/types/purchaseGroup'
import type { PurchaseOrderDetail, VersionedPurchaseOrder } from '@/types/purchaseOrder'

const basePath = '/api/v1/purchase-groups/'

function versionedGroup(response: AxiosResponse<DataResponse<PurchaseGroup>>): VersionedPurchaseGroup {
  return {
    data: response.data.data,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchPurchaseGroups(query: PurchaseGroupQuery = {}): Promise<PaginatedPurchaseGroups> {
  const { data } = await apiClient.get<PaginatedPurchaseGroups>(basePath, { params: query })
  return data
}

export async function fetchPurchaseGroupFilterOptions(): Promise<PurchaseGroupFilterOptions> {
  const { data } = await apiClient.get<DataResponse<PurchaseGroupFilterOptions>>(`${basePath}filter-options/`)
  return data.data
}

export async function fetchVersionedPurchaseGroup(id: string): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.get<DataResponse<PurchaseGroup>>(`${basePath}${id}/`))
}

export async function createPurchaseGroup(payload: PurchaseGroupInput): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.post<DataResponse<PurchaseGroup>>(basePath, payload))
}

export async function completePurchaseGroup(id: string, remark: string, etag: string): Promise<VersionedPurchaseGroup> {
  return versionedGroup(await apiClient.post<DataResponse<PurchaseGroup>>(
    `${basePath}${id}/complete/`,
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
    { headers: groupEtag ? { 'If-Match': groupEtag } : {} },
  )
  return {
    data: response.data.data,
    etag: typeof response.headers?.etag === 'string' ? response.headers.etag : '',
  }
}
