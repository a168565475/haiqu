import { apiClient } from './request'
import type { PowderCoatingQuery, PowderCoatingRow } from '@/types/powderCoating'
import type { PaginatedReferenceData } from '@/types/referenceData'

export async function fetchPowderCoatingMovements(
  params: PowderCoatingQuery, signal: AbortSignal,
) {
  const { data } = await apiClient.get<PaginatedReferenceData<PowderCoatingRow>>(
    '/api/v1/powder-coating-movements/', { params, signal },
  )
  return data
}
