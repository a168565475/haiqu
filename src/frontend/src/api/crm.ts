import { apiClient } from './request'
import type { ApiDataResponse, PaginatedResponse } from '@/types/customer'

export interface CommunicationItem {
  id: string
  customer_account: string
  customer_name: string
  communication_type: string
  direction: string
  direction_display: string
  subject: string
  occurred_at: string
  created_by: { id: string; display_name: string } | null
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface CommunicationCreateInput {
  customer_account_id: string
  communication_type: string
  direction: 'INBOUND' | 'OUTBOUND' | 'INTERNAL'
  subject: string
  content: string
  occurred_at: string
  contact_participant_ids?: string[]
}

export async function fetchCustomerCommunications(
  customerId: string,
  params: Record<string, unknown> = {},
): Promise<PaginatedResponse<CommunicationItem>> {
  const { data } = await apiClient.get<PaginatedResponse<CommunicationItem>>(
    '/api/v1/communications/',
    { params: { ...params, customer_id: customerId } },
  )
  return data
}

export async function createCommunication(
  payload: CommunicationCreateInput,
): Promise<CommunicationItem> {
  const { data } = await apiClient.post<ApiDataResponse<CommunicationItem>>(
    '/api/v1/communications/',
    payload,
  )
  return data.data
}
