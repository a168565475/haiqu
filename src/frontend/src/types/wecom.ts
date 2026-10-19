export interface WeComConfig {
  corp_id: string
  agent_id: string
  erp_origin: string
  enabled: boolean
  has_secret: boolean
  has_callback_token: boolean
  has_callback_aes_key: boolean
  secret: string | null
  callback_token: string | null
  callback_aes_key: string | null
  credential_read_errors: string[]
  encryption_ready: boolean
  configuration_complete: boolean
  last_check_status: 'NOT_CHECKED' | 'SUCCESS' | 'FAILED'
  last_check_message: string
  last_checked_at: string | null
  login_url: string
  callback_url: string
  trusted_domain: string
}

export interface WeComConfigWrite {
  corp_id: string
  agent_id: string
  erp_origin: string
  enabled: boolean
  secret?: string
  callback_token?: string
  callback_aes_key?: string
}

export interface WeComBinding {
  id: string
  user_id: string
  member_name: string
  employee_id: string
  employee_code: string
  employee_name: string
  username: string
  role_status: 'waiting' | 'active' | 'inactive'
  source: string
  created_at: string
}

export interface WeComEmployeeOption {
  id: string
  employee_code: string
  display_name: string
  username: string | null
  etag: string
}

export interface WeComAudit {
  id: string
  occurred_at: string
  actor_name: string
  action: string
  user_id: string
  employee_name: string
  result: string
  message: string
}

export interface WeComPage<T> {
  data: T[]
  count: number
  page: number
  page_size: number
}

export interface WeComConfigResponse {
  data: WeComConfig
  etag: string
}
