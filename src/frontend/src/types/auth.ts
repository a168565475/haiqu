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
  employee: AuthEmployee | null
  permissions: string[]
  data_scope: string
}

export interface AuthResponse {
  authenticated: boolean
  user: AuthUser | null
}

export interface LoginCredentials {
  username: string
  password: string
}
