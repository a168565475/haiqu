import type { DataResponse } from '@/types/referenceData'
import type { DirectorActivity, DirectorCategory, DirectorDetail, DirectorJob, DirectorOverview, DirectorPage, DirectorPeriod, DirectorWorkshop } from '@/types/workshopDirectorWorkbench'
import { apiClient } from './request'

const base = '/api/v1/workshop-director-workbench/'

export async function getDirectorOverview(workshop: DirectorWorkshop | undefined, signal: AbortSignal) {
  return (await apiClient.get<DataResponse<DirectorOverview>>(base, { params: { workshop }, signal })).data.data
}

export async function getDirectorItems(workshop: DirectorWorkshop, category: DirectorCategory, date: string | undefined, page: number, signal: AbortSignal, pageSize = 20) {
  const params = { workshop, category, date, page, page_size: pageSize }
  return (await apiClient.get<DirectorPage<DirectorJob[]>>(base + 'items/', { params, signal })).data
}

export async function getDirectorDetail(workshop: DirectorWorkshop, id: string, signal: AbortSignal) {
  return (await apiClient.get<DataResponse<DirectorDetail>>(base + 'detail/', { params: { workshop, id }, signal })).data.data
}

export async function getDirectorActivity(workshop: DirectorWorkshop, period: DirectorPeriod, page: number, signal: AbortSignal, pageSize = 20) {
  const params = { workshop, period, page, page_size: pageSize }
  return (await apiClient.get<DirectorPage<DirectorActivity>>(base + 'activity/', { params, signal })).data
}
