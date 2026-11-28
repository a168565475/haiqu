import { apiClient } from './request'
import type { MaterialStockRecordDirection, MaterialStockRecordPage, MaterialStockRecordSection } from '@/types/materialStockRecords'

export async function fetchMaterialStockRecords(params: {
  direction: MaterialStockRecordDirection
  section: MaterialStockRecordSection
  task_number: string
  q: string
  start_date?: string
  end_date?: string
  page: number
}, signal: AbortSignal) {
  const { data } = await apiClient.get<MaterialStockRecordPage>('/api/v1/material-stock-records/', { params, signal })
  return data
}
