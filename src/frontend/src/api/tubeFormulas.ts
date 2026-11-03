import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { TubeCalculationFormula, TubeFormulaInput, VersionedTubeFormula } from '@/types/tubeFormulas'

const basePath = '/api/v1/reference-data/tube-calculation-formulas/'

function versioned(response: AxiosResponse<DataResponse<TubeCalculationFormula>>): VersionedTubeFormula {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchTubeFormulas(): Promise<TubeCalculationFormula[]> {
  const { data } = await apiClient.get<DataResponse<TubeCalculationFormula[]>>(basePath, { params: { page_size: 100 } })
  return data.data
}

export async function fetchTubeFormula(id: string): Promise<VersionedTubeFormula> {
  return versioned(await apiClient.get<DataResponse<TubeCalculationFormula>>(`${basePath}${encodeURIComponent(id)}/`))
}

export async function updateTubeFormula(id: string, payload: TubeFormulaInput, etag: string): Promise<VersionedTubeFormula> {
  return versioned(await apiClient.patch<DataResponse<TubeCalculationFormula>>(
    `${basePath}${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } },
  ))
}
