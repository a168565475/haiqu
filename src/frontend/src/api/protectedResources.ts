import { apiClient } from './request'

export type ResourceSource = string | null | undefined
export type ResourceLocation =
  | { kind: 'protected'; url: string; key: string }
  | { kind: 'public'; url: string; key: string }
  | { kind: 'invalid'; url: ''; key: string }

export interface ResourceReadOptions {
  signal?: AbortSignal
  timeout?: number
}

interface ResourceOrigins {
  apiBaseURL?: string
  browserURL?: string
}

/** Native consumers must never receive a rejected/ambiguous protected API URL. */
export function locateResource(source: ResourceSource, origins: ResourceOrigins = {}): ResourceLocation {
  const raw = source?.trim() ?? ''
  const invalid = (): ResourceLocation => ({ kind: 'invalid', url: '', key: `invalid:${raw}` })
  if (!raw || /[\u0000-\u001f\u007f\\]/.test(raw)) return invalid()
  // These URLs are caller-owned; displaying them as an image neither fetches an API
  // nor transfers ownership of the caller's upload preview to this utility.
  if (/^(blob:|data:)/i.test(raw)) return { kind: 'public', url: raw, key: raw }
  if (/^[a-z][a-z\d+.-]*:/i.test(raw) && !/^https?:\/\//i.test(raw)) return invalid()
  const browserURL = origins.browserURL ?? (typeof window === 'undefined' ? undefined : window.location.href)
  const apiBaseURL = origins.apiBaseURL ?? apiClient.defaults.baseURL
  try {
    const browser = browserURL ? new URL(browserURL) : undefined
    const api = apiBaseURL ? new URL(apiBaseURL, browserURL) : browser
    if (!api || !/^https?:$/.test(api.protocol) || api.username || api.password) return invalid()
    const value = /^api\//.test(raw) ? `/${raw}` : raw
    const target = new URL(value, browser ?? api)
    if (!/^https?:$/.test(target.protocol) || target.username || target.password) return invalid()
    let decoded = target.pathname
    // Do not misclassify an encoded API prefix as a public/static image.
    for (let index = 0; index < 2; index++) {
      try { decoded = decodeURIComponent(decoded) } catch { return invalid() }
    }
    const protectedPath = target.pathname.startsWith('/api/')
    if (!protectedPath && /^\/+api(?:\/|$)/i.test(decoded)) return invalid()
    if (!protectedPath) return { kind: 'public', url: raw, key: raw }
    if (target.origin !== api.origin && target.origin !== browser?.origin) return invalid()
    // Browser-proxy URLs and relative URLs use the configured client's trusted API
    // origin. This is what the existing identity interceptor guards; no extra client.
    const url = `${api.origin}${target.pathname}${target.search}`
    return { kind: 'protected', url, key: url }
  } catch {
    return invalid()
  }
}

export function safeResourceFilename(value: string | null | undefined, fallback = 'download'): string {
  const cleaned = (value ?? '').replace(/[\u0000-\u001f\u007f<>:"/\\|?*]/g, '_').trim().replace(/[. ]+$/, '')
  return cleaned && cleaned !== '.' && cleaned !== '..' ? cleaned : fallback
}

export function dispositionFilename(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const extended = /(?:^|;)\s*filename\*\s*=\s*(?:"([^\"]*)"|([^;]*))/i.exec(value)
  const encoded = (extended?.[1] ?? extended?.[2])?.trim()
  if (encoded) {
    const utf8 = /^utf-8'[^']*'(.*)$/i.exec(encoded)
    if (utf8) {
      try { return safeResourceFilename(decodeURIComponent(utf8[1]!)) } catch { /* use ordinary filename */ }
    }
  }
  const ordinary = /(?:^|;)\s*filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]*))/i.exec(value)
  const filename = (ordinary?.[1]?.replace(/\\(.)/g, '$1') ?? ordinary?.[2])?.trim()
  return filename ? safeResourceFilename(filename) : undefined
}

export async function fetchProtectedResource(source: string, options: ResourceReadOptions = {}) {
  const location = locateResource(source)
  if (location.kind !== 'protected') throw new Error('资源地址不是可信的受保护 API。')
  // Keep Accept, credentials, CSRF, timeout defaults and identity guards untouched.
  const response = await apiClient.get<Blob>(location.url, { ...options, responseType: 'blob' })
  if (!(response.data instanceof Blob) || response.data.size === 0
    || /^(?:application\/(?:json|[\w.+-]+\+json)|text\/html)(?:;|$)/i.test(response.data.type)) {
    throw new Error('资源响应不是有效文件。')
  }
  return {
    blob: response.data,
    filename: dispositionFilename(response.headers['content-disposition']),
  }
}

export function isSafeResourceImage(blob: Blob): boolean {
  // Never navigate an HTML/SVG/unknown document in an unisolated Blob window.
  return /^image\/(?:png|jpeg|gif|webp|avif|bmp|x-icon|vnd\.microsoft\.icon)$/i.test(blob.type.split(';')[0]!.trim())
}
