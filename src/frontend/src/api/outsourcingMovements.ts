import { apiClient } from './request'
import type { OutsourcingMovementDirection, OutsourcingMovementProcess, OutsourcingMovementRow } from '@/types/outsourcingMovements'
import type { PaginatedReferenceData } from '@/types/referenceData'

export async function fetchOutsourcingMovements(params: {
  task_number: string
  direction: OutsourcingMovementDirection
  process: OutsourcingMovementProcess | ''
  page: number
}, signal: AbortSignal) {
  const { data } = await apiClient.get<PaginatedReferenceData<OutsourcingMovementRow>>(
    '/api/v1/outsourcing-movements/', { params, signal },
  )
  return data
}
