export interface AuthEmployee {
  id: string
  employee_code: string
  display_name: string
  status: string
}

export interface AuthUser {
  id: number
  username: string
  display_name: string
  is_superuser: boolean
  employee: AuthEmployee | null
  permissions: string[]
  data_scope: string
  waiting_for_role?: boolean
  sales_access_enabled?: boolean
  module_access_enabled?: boolean
  effective_access?: import('./access').EffectiveAccess
}

export interface AccountSwitchState {
  active: boolean
  can_return: boolean
  identity_version: string
}

export interface AuthResponse {
  authenticated: boolean
  user: AuthUser | null
  account_switch?: AccountSwitchState
}

export interface SwitchTargetChoice {
  id: string
  name: string
}

export interface SwitchTargetFilters {
  department_id?: string
  role_id?: string
}

export interface SwitchTarget {
  employee_id: string
  user_id: number
  username: string
  employee_code: string
  display_name: string
  departments?: SwitchTargetChoice[]
  roles?: SwitchTargetChoice[]
}

export interface SwitchTargetsResponse {
  results: SwitchTarget[]
  departments?: SwitchTargetChoice[]
  roles?: SwitchTargetChoice[]
  has_more?: boolean
  identity_version: string
}

export interface LoginCredentials {
  username: string
  password: string
}

export interface WeComQrSession {
  login_type: 'CorpApp'
  appid: string
  agentid: string
  redirect_uri: string
  state: string
  expires_at: string
}
