import { isAxiosError } from 'axios'

import { apiClient } from './request'
import type { AuthResponse, LoginCredentials } from '@/types/auth'

export async function fetchCurrentUser(): Promise<AuthResponse> {
  const { data } = await apiClient.get<AuthResponse>('/api/auth/me/')
  return data
}

export async function login(credentials: LoginCredentials): Promise<AuthResponse> {
  const { data } = await apiClient.post<AuthResponse>('/api/auth/login/', credentials)
  return data
}

export async function requestDevelopmentAutoLogin(): Promise<AuthResponse> {
  const { data } = await apiClient.post<AuthResponse>('/api/auth/development-auto-login/')
  return data
}

export async function logout(): Promise<AuthResponse> {
  const { data } = await apiClient.post<AuthResponse>('/api/auth/logout/')
  return data
}

function firstFieldError(responseData: unknown): string | null {
  if (!responseData || typeof responseData !== 'object') {
    return null
  }

  for (const value of Object.values(responseData)) {
    if (Array.isArray(value) && typeof value[0] === 'string' && value[0]) {
      return value[0]
    }
  }

  return null
}

export function getAuthErrorMessage(error: unknown): string {
  if (!isAxiosError(error)) {
    return '登录失败，请稍后重试'
  }

  const responseData = error.response?.data
  if (responseData && typeof responseData === 'object' && 'detail' in responseData) {
    const detail = responseData.detail
    if (typeof detail === 'string' && detail) {
      return detail
    }
  }

  const fieldError = firstFieldError(responseData)
  if (fieldError) {
    return fieldError
  }

  if (!error.response) {
    return error.code === 'ECONNABORTED'
      ? '登录请求超时，请检查网络后重试'
      : '无法连接服务器，请确认系统服务已启动'
  }

  if (error.response.status === 401) {
    return '登录状态已失效，请重新登录'
  }

  if (error.response.status === 403) {
    return '登录请求已失效，请刷新页面后重试'
  }

  if (error.response.status >= 500) {
    return '服务器暂时无法处理登录，请稍后重试'
  }

  return '登录失败，请稍后重试'
}

export function getLogoutErrorMessage(error: unknown): string {
  if (!isAxiosError(error)) {
    return '退出失败，请稍后重试'
  }

  if (!error.response) {
    return error.code === 'ECONNABORTED'
      ? '退出请求超时，请检查网络后重试'
      : '无法连接服务器，暂时不能安全退出'
  }

  if (error.response.status === 403) {
    return '退出请求已失效，请刷新页面后重试'
  }

  if (error.response.status >= 500) {
    return '服务器暂时无法处理退出，请稍后重试'
  }

  return '退出失败，请稍后重试'
}
