import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse } from '@/types/customer'
import type {
  Complaint,
  ComplaintAttachment,
  ComplaintInput,
  ComplaintOptions,
  ComplaintPage,
  ComplaintProgressInput,
  ComplaintQuery,
  ComplaintStats,
  ComplaintUpdateInput,
  VersionedComplaint,
} from '@/types/complaint'

const complaintPath = '/api/v1/complaints/'

function detailPath(complaintId: string, suffix = ''): string {
  return `${complaintPath}${encodeURIComponent(complaintId)}/${suffix}`
}

function versioned(response: AxiosResponse<ApiDataResponse<Complaint>>): VersionedComplaint {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : null,
  }
}

export async function fetchComplaints(params: ComplaintQuery): Promise<ComplaintPage> {
  const { data } = await apiClient.get<ComplaintPage>(complaintPath, { params })
  return data
}

export async function fetchComplaintOptions(): Promise<ComplaintOptions> {
  const { data } = await apiClient.get<ApiDataResponse<ComplaintOptions>>(`${complaintPath}options/`)
  return data.data
}

export async function fetchComplaintStats(params: ComplaintQuery = {}): Promise<ComplaintStats> {
  const { data } = await apiClient.get<ApiDataResponse<ComplaintStats>>(`${complaintPath}stats/`, { params })
  return data.data
}

export async function fetchComplaint(complaintId: string): Promise<VersionedComplaint> {
  return versioned(await apiClient.get<ApiDataResponse<Complaint>>(detailPath(complaintId)))
}

export async function createComplaint(payload: ComplaintInput): Promise<VersionedComplaint> {
  return versioned(await apiClient.post<ApiDataResponse<Complaint>>(complaintPath, payload))
}

export async function updateComplaint(
  complaintId: string,
  payload: ComplaintUpdateInput,
  etag: string,
): Promise<VersionedComplaint> {
  return versioned(
    await apiClient.patch<ApiDataResponse<Complaint>>(detailPath(complaintId), payload, {
      headers: { 'If-Match': etag },
    }),
  )
}

export async function updateComplaintProgress(
  complaintId: string,
  payload: ComplaintProgressInput,
  etag: string,
): Promise<VersionedComplaint & { progressId: string | null }> {
  const response = await apiClient.post<ApiDataResponse<Complaint>>(
    detailPath(complaintId, 'progress/'),
    payload,
    { headers: { 'If-Match': etag } },
  )
  return {
    ...versioned(response),
    progressId:
      typeof response.headers['complaint-progress-id'] === 'string'
        ? response.headers['complaint-progress-id']
        : null,
  }
}

export async function uploadComplaintImage(
  complaintId: string,
  file: File,
  progressId?: string | null,
  caption = '',
): Promise<ComplaintAttachment> {
  const body = new FormData()
  body.append('file', file)
  if (progressId) body.append('progress_id', progressId)
  if (caption) body.append('caption', caption)
  const { data } = await apiClient.post<ApiDataResponse<ComplaintAttachment>>(
    detailPath(complaintId, 'attachments/'),
    body,
    { timeout: 120_000 },
  )
  return data.data
}

export function complaintPreviewUrl(relativeUrl: string): string {
  return new URL(relativeUrl, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}
