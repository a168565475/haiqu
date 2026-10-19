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

export interface AuthResponse {
  authenticated: boolean
  user: AuthUser | null
}

export interface LoginCredentials {
  username: string
  password: string
}
