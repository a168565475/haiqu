export type CodexConnectionStatus = 'DISCONNECTED' | 'CONNECTED' | 'READY' | 'LOGIN_PENDING' | 'DRAINING' | 'ERROR' | 'UNKNOWN'
export type CodexConnectionAction = 'login' | 'login-cancel' | 'disconnect' | 'switch' | 'refresh' | 'test'

export interface CodexConnectionSnapshot {
  config_generation: number
  status: CodexConnectionStatus
  selected_model: string
  cli_version: string
  account: { display_name: string; plan_type: string | null } | null
  models: Array<{ id: string; display_name: string }>
  rate_limits: {
    windows: Array<{ name: string; used_percent: number | null; window_minutes: number | null; resets_at: string | null }>
    credits: { unlimited: boolean | null; has_credits: boolean | null; balance: string | null } | null
  } | null
  limits_updated_at: string | null
  last_checked_at: string | null
  last_test_at: string | null
  error_code: string
  paused: boolean
  operation: { id: string; action: string; state: 'QUEUED' | 'RUNNING' | 'CANCELING'; actor_id: string; can_cancel: boolean } | null
}

export interface CodexConnectionResponse {
  data: CodexConnectionSnapshot
  etag: string
}

export interface CodexLoginChallenge {
  operation_id: string
  verification_url: string
  user_code: string
  // 本地展示截止时间，不代表官方返回的验证码有效期；操作结果以快照终态为准。
  expires_at: string
}
