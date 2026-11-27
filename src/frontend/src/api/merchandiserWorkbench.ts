import type { MerchandiserActivity, MerchandiserItems, MerchandiserItemsQuery, MerchandiserOverview, MerchandiserPeriod } from '@/types/merchandiserWorkbench'
import type { DataResponse } from '@/types/referenceData'
import { apiClient } from './request'

const base = '/api/v1/merchandiser-workbench/'

export async function getMerchandiserOverview(signal: AbortSignal) {
  return (await apiClient.get<DataResponse<MerchandiserOverview>>(base, { signal })).data.data
}

export async function getMerchandiserActivity(period: MerchandiserPeriod, signal: AbortSignal) {
  return (await apiClient.get<DataResponse<MerchandiserActivity>>(`${base}activity/`, { params: { period }, signal })).data.data
}

export async function getMerchandiserItems(query: MerchandiserItemsQuery, page: number, signal: AbortSignal) {
  const params = { category: query.category, date: query.date, period: query.period, supplier_id: query.supplier_id, page, page_size: 20 }
  return (await apiClient.get<MerchandiserItems>(`${base}items/`, { params, signal })).data
}
