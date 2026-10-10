import axios from 'axios'

function resolveApiBaseUrl(): string {
  const configuredUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

  if (configuredUrl === 'same-origin' && typeof window !== 'undefined') {
    return window.location.origin
  }

  if (!import.meta.env.DEV || typeof window === 'undefined') {
    return configuredUrl
  }

  try {
    const developmentUrl = new URL(configuredUrl)
    developmentUrl.hostname = window.location.hostname
    return developmentUrl.toString().replace(/\/$/, '')
  } catch {
    return configuredUrl
  }
}

export const apiClient = axios.create({
  baseURL: resolveApiBaseUrl(),
  timeout: 5000,
  withCredentials: true,
  withXSRFToken: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
  headers: {
    Accept: 'application/json',
  },
})
