import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { Paginated } from '@/types/outsourcing'
import type { UnifiedOutsourcingOptions, UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'

const path = '/api/v1/unified-outsourcing-orders/'

export async function fetchUnifiedOutsourcingOrders(params: Record<string, unknown>): Promise<Paginated<UnifiedOutsourcingOrder>> {
  const { data } = await apiClient.get<Paginated<UnifiedOutsourcingOrder>>(path, { params })
  return data
}

export async function fetchUnifiedOutsourcingOptions(): Promise<UnifiedOutsourcingOptions> {
  const { data } = await apiClient.get<DataResponse<UnifiedOutsourcingOptions>>(`${path}options/`)
  return data.data
}

export function unifiedOutsourcingDetailPath(row: UnifiedOutsourcingOrder): string {
  if (row.record_type === 'TUBE') return `/workshop/outsourcing/tube/${encodeURIComponent(row.id)}`
  if (row.record_type === 'REWORK') return `/workshop/outsourcing/rework/${encodeURIComponent(row.id)}`
  const target = `/workshop/outsourcing/${encodeURIComponent(row.id)}`
  return row.detail_access === 'METAL' ? `${target}?view=metal` : target
}
