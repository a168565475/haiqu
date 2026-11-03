import axios, { AxiosHeaders, CanceledError, isAxiosError } from 'axios'

let identityVersion: string | null = null
let identityGeneration = 0
const requestGenerations = new WeakMap<object, number>()

export function setRequestIdentity(version: string | null, force = false) {
  if (identityVersion !== version || force) {
    identityVersion = version
    identityGeneration += 1
  }
}

export const apiClient = axios.create({
  baseURL: '/', timeout: 20000, withCredentials: true, withXSRFToken: true,
  xsrfCookieName: 'csrftoken', xsrfHeaderName: 'X-CSRFToken',
  headers: { Accept: 'application/json' },
})

function invalidateSession() {
  setRequestIdentity(null)
  window.dispatchEvent(new Event('mobile-session-invalid'))
}

apiClient.interceptors.request.use((config) => {
  // 所有业务请求保持同源，防止携带身份版本前往外部地址。
  if (!config.url?.startsWith('/api/')) throw new Error('无效的接口地址')
  config.headers = AxiosHeaders.from(config.headers)
  config.headers.delete('X-Identity-Version')
  if (identityVersion) config.headers.set('X-Identity-Version', identityVersion)
  requestGenerations.set(config, identityGeneration)
  return config
}, (error: unknown) => { throw error }, { synchronous: true })

apiClient.interceptors.response.use((response) => {
  if (requestGenerations.get(response.config) !== identityGeneration) throw new CanceledError('身份已变化')
  return response
}, (error: unknown) => {
  if (isAxiosError(error)) {
    if (error.config && requestGenerations.get(error.config) !== identityGeneration) throw new CanceledError('身份已变化')
    const code = error.response?.data?.error?.code || error.response?.data?.code
    if (code === 'WECOM_ROLE_REQUIRED') window.dispatchEvent(new Event('mobile-role-required'))
    if ((error.response?.status === 401 && !error.config?.url?.startsWith('/api/auth/'))
      || code === 'IDENTITY_VERSION_CONFLICT' || code === 'IDENTITY_VERSION_REQUIRED'
      || error.response?.status === 403 && code === 'IDENTITY_CONTEXT_INVALID') invalidateSession()
  }
  return Promise.reject(error)
})
