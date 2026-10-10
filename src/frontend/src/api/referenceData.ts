import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type {
  ConfigRelease,
  DataResponse,
  DictionaryItem,
  DictionaryItemInput,
  DictionaryType,
  DictionaryTypeInput,
  ExchangeRate,
  MasterDataInput,
  MasterDataListQuery,
  MasterDataRecord,
  MasterDataResource,
  MasterDataSummary,
  NumberRule,
  PaginatedReferenceData,
  PublishedOptionsResponse,
  ReferenceDataSummary,
  ReferenceListQuery,
  SystemParameter,
  VersionedReferenceData,
} from '@/types/referenceData'

const basePath = '/api/v1/reference-data/'

export async function fetchPublishedConfigVersion(): Promise<{ config_version: number | null; config_revision: string }> {
  const { data } = await apiClient.get<{ data: { config_version: number | null; config_revision: string } }>(`${basePath}published-version/`)
  return data.data
}

type OptionsBatchResponse = {
  data: Record<string, PublishedOptionsResponse['data']>
  errors: Record<string, string>
  meta: PublishedOptionsResponse['meta']
}
type QueuedOptions = { code: string; resolve: (data: PublishedOptionsResponse) => void; reject: (error: unknown) => void }
let optionsQueue: QueuedOptions[] = []

async function flushOptionsQueue() {
  const queued = optionsQueue
  optionsQueue = []
  const codes = [...new Set(queued.map(item => item.code))]
  // 接口每批最多20类，避免配置页同时加载时生成过长请求。
  await Promise.all(Array.from({ length: Math.ceil(codes.length / 20) }, async (_, index) => {
    const group = codes.slice(index * 20, (index + 1) * 20)
    const listeners = queued.filter(item => group.includes(item.code))
    try {
      const { data } = await apiClient.get<OptionsBatchResponse>(`${basePath}options-batch/`, { params: { type_codes: group.join(',') } })
      for (const item of listeners) {
        const values = data.data[item.code]
        if (Array.isArray(values)) item.resolve({ data: values, meta: data.meta })
        else item.reject(new Error(data.errors?.[item.code] || '字典读取失败。'))
      }
    } catch (error) {
      for (const item of listeners) item.reject(error)
    }
  }))
}

export async function fetchPublishedOptions(
  typeCode: string,
  currentId?: string,
): Promise<PublishedOptionsResponse> {
  const normalizedTypeCode = typeCode.trim().toUpperCase()
  if (!normalizedTypeCode) {
    throw new Error('字典类型编码不能为空。')
  }
  if (!currentId) {
    return new Promise((resolve, reject) => {
      optionsQueue.push({ code: normalizedTypeCode, resolve, reject })
      if (optionsQueue.length === 1) queueMicrotask(() => { void flushOptionsQueue() })
    })
  }
  const { data } = await apiClient.get<PublishedOptionsResponse>(
    `${basePath}options/${encodeURIComponent(normalizedTypeCode)}/`,
    { params: currentId ? { current_id: currentId } : undefined },
  )
  return data
}

function etag(response: AxiosResponse<unknown>): string {
  return typeof response.headers.etag === 'string' ? response.headers.etag : ''
}

function versioned<T>(response: AxiosResponse<DataResponse<T>>): VersionedReferenceData<T> {
  return { data: response.data.data, etag: etag(response) }
}

export async function fetchReferenceDataSummary(): Promise<ReferenceDataSummary> {
  const { data } = await apiClient.get<DataResponse<ReferenceDataSummary>>(`${basePath}summary/`)
  return data.data
}

export async function fetchDictionaryTypes(): Promise<PaginatedReferenceData<DictionaryType>> {
  const { data } = await apiClient.get<PaginatedReferenceData<DictionaryType>>(
    `${basePath}dictionary-types/`,
    { params: { page_size: 100 } },
  )
  return data
}

export async function fetchDictionaryType(id: string): Promise<VersionedReferenceData<DictionaryType>> {
  const response = await apiClient.get<DataResponse<DictionaryType>>(
    `${basePath}dictionary-types/${encodeURIComponent(id)}/`,
  )
  return versioned(response)
}

export async function updateDictionaryType(
  id: string,
  payload: DictionaryTypeInput,
  currentEtag: string,
): Promise<VersionedReferenceData<DictionaryType>> {
  const response = await apiClient.patch<DataResponse<DictionaryType>>(
    `${basePath}dictionary-types/${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function fetchDictionaryItems(
  query: ReferenceListQuery = {},
): Promise<PaginatedReferenceData<DictionaryItem>> {
  const { data } = await apiClient.get<PaginatedReferenceData<DictionaryItem>>(
    `${basePath}dictionary-items/`,
    { params: { page_size: 100, ...query } },
  )
  return data
}

export async function fetchDictionaryItem(id: string): Promise<VersionedReferenceData<DictionaryItem>> {
  const response = await apiClient.get<DataResponse<DictionaryItem>>(
    `${basePath}dictionary-items/${encodeURIComponent(id)}/`,
  )
  return versioned(response)
}

export async function createDictionaryItem(payload: DictionaryItemInput): Promise<DictionaryItem> {
  const { data } = await apiClient.post<DataResponse<DictionaryItem>>(
    `${basePath}dictionary-items/`,
    payload,
  )
  return data.data
}

export async function updateDictionaryItem(
  id: string,
  payload: DictionaryItemInput,
  currentEtag: string,
): Promise<VersionedReferenceData<DictionaryItem>> {
  const response = await apiClient.patch<DataResponse<DictionaryItem>>(
    `${basePath}dictionary-items/${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function changeDictionaryItemStatus(
  id: string,
  action: 'activate' | 'deactivate',
  currentEtag: string,
  reason: string,
  confirmReferences = false,
): Promise<VersionedReferenceData<DictionaryItem>> {
  const response = await apiClient.post<DataResponse<DictionaryItem>>(
    `${basePath}dictionary-items/${encodeURIComponent(id)}/${action}/`,
    { reason, confirm_references: confirmReferences },
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function archiveDictionaryItem(
  id: string,
  currentEtag: string,
  reason: string,
): Promise<VersionedReferenceData<DictionaryItem>> {
  const response = await apiClient.post<DataResponse<DictionaryItem>>(
    `${basePath}dictionary-items/${encodeURIComponent(id)}/archive/`,
    { reason },
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function fetchSystemParameters(): Promise<PaginatedReferenceData<SystemParameter>> {
  const { data } = await apiClient.get<PaginatedReferenceData<SystemParameter>>(
    `${basePath}system-parameters/`,
    { params: { page_size: 100 } },
  )
  return data
}

export async function fetchSystemParameter(id: string): Promise<VersionedReferenceData<SystemParameter>> {
  const response = await apiClient.get<DataResponse<SystemParameter>>(
    `${basePath}system-parameters/${encodeURIComponent(id)}/`,
  )
  return versioned(response)
}

export async function updateSystemParameter(
  id: string,
  value: unknown,
  currentEtag: string,
): Promise<VersionedReferenceData<SystemParameter>> {
  const response = await apiClient.patch<DataResponse<SystemParameter>>(
    `${basePath}system-parameters/${encodeURIComponent(id)}/`,
    { draft_value: value },
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function fetchConfigReleases(): Promise<PaginatedReferenceData<ConfigRelease>> {
  const { data } = await apiClient.get<PaginatedReferenceData<ConfigRelease>>(
    `${basePath}config-releases/`,
    { params: { page_size: 20 } },
  )
  return data
}

export async function fetchNumberRules(): Promise<PaginatedReferenceData<NumberRule>> {
  const { data } = await apiClient.get<PaginatedReferenceData<NumberRule>>(
    `${basePath}number-rules/`,
    { params: { page_size: 100 } },
  )
  return data
}

export async function fetchConfigRelease(id: string): Promise<VersionedReferenceData<ConfigRelease>> {
  const response = await apiClient.get<DataResponse<ConfigRelease>>(
    `${basePath}config-releases/${encodeURIComponent(id)}/`,
  )
  return versioned(response)
}

export async function publishReferenceData(
  notes: string,
  currentEtag: string,
): Promise<VersionedReferenceData<ConfigRelease>> {
  const response = await apiClient.post<DataResponse<ConfigRelease>>(
    `${basePath}config-releases/`,
    { notes },
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function fetchMasterDataSummary(): Promise<MasterDataSummary> {
  const { data } = await apiClient.get<DataResponse<MasterDataSummary>>(`${basePath}master-data-summary/`)
  return data.data
}

export async function fetchMasterDataList<T extends MasterDataRecord>(
  resource: MasterDataResource,
  query: MasterDataListQuery = {},
): Promise<PaginatedReferenceData<T>> {
  const { data } = await apiClient.get<PaginatedReferenceData<T>>(
    `${basePath}${resource}/`,
    { params: query },
  )
  return data
}

export async function fetchAllMasterDataRecords<T extends MasterDataRecord>(
  resource: MasterDataResource,
  query: MasterDataListQuery = {},
): Promise<T[]> {
  const firstPage = await fetchMasterDataList<T>(resource, { ...query, page: 1, page_size: 100 })
  if (firstPage.meta.total_pages <= 1) return firstPage.data
  const remainingPages = await Promise.all(
    Array.from({ length: firstPage.meta.total_pages - 1 }, (_, index) => (
      fetchMasterDataList<T>(resource, { ...query, page: index + 2, page_size: 100 })
    )),
  )
  return [firstPage.data, ...remainingPages.map((page) => page.data)].flat()
}

export async function fetchMasterDataRecord<T extends MasterDataRecord>(
  resource: MasterDataResource,
  id: string,
): Promise<VersionedReferenceData<T>> {
  const response = await apiClient.get<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/`,
  )
  return versioned(response)
}

export async function createMasterDataRecord<T extends MasterDataRecord>(
  resource: MasterDataResource,
  payload: MasterDataInput,
): Promise<VersionedReferenceData<T>> {
  const response = await apiClient.post<DataResponse<T>>(`${basePath}${resource}/`, payload)
  return versioned(response)
}

export async function updateMasterDataRecord<T extends MasterDataRecord>(
  resource: MasterDataResource,
  id: string,
  payload: MasterDataInput,
  currentEtag: string,
): Promise<VersionedReferenceData<T>> {
  const response = await apiClient.patch<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function changeMasterDataStatus<T extends MasterDataRecord>(
  resource: Exclude<MasterDataResource, 'exchange-rates'>,
  id: string,
  action: 'activate' | 'deactivate',
  currentEtag: string,
  reason: string,
): Promise<VersionedReferenceData<T>> {
  const response = await apiClient.post<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/${action}/`,
    { reason },
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function archiveMasterDataRecord<T extends MasterDataRecord>(
  resource: Exclude<MasterDataResource, 'exchange-rates'>,
  id: string,
  currentEtag: string,
  reason: string,
): Promise<VersionedReferenceData<T>> {
  const response = await apiClient.post<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/archive/`,
    { reason },
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}

export async function correctExchangeRate(
  id: string,
  payload: MasterDataInput,
  currentEtag: string,
): Promise<VersionedReferenceData<ExchangeRate>> {
  const response = await apiClient.post<DataResponse<ExchangeRate>>(
    `${basePath}exchange-rates/${encodeURIComponent(id)}/correct/`,
    payload,
    { headers: { 'If-Match': currentEtag } },
  )
  return versioned(response)
}
