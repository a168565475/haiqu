import type { WeComQrSession } from '@/types/auth'

export interface WeComLoginPanel { el: HTMLIFrameElement; unmount(): void }
export interface WeComLoginSdk {
  createWWLoginPanel(options: {
    el: HTMLElement
    params: {
      login_type: 'CorpApp'
      appid: string
      agentid: string
      redirect_uri: string
      state: string
      redirect_type: 'callback'
      panel_size: 'small'
      lang: 'zh'
    }
    onCheckWeComLogin(result: { isWeComLogin: boolean }): void
    onLoginSuccess(result: { code: string }): void
    onLoginFail(result: { errCode?: number; errMsg?: string }): void
  }): WeComLoginPanel
}

declare global { interface Window { ww?: WeComLoginSdk } }

const sdkUrl = 'https://wwcdn.weixin.qq.com/node/wework/wwopen/js/wecom-jssdk-2.4.0.js'
let loadingSdk: Promise<WeComLoginSdk> | null = null

export class WeComQrError extends Error {}

export function loadWeComLoginSdk(): Promise<WeComLoginSdk> {
  if (typeof window.ww?.createWWLoginPanel === 'function') return Promise.resolve(window.ww)
  if (loadingSdk) return loadingSdk
  loadingSdk = new Promise<WeComLoginSdk>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = sdkUrl
    script.async = true
    script.dataset.wecomLoginSdk = 'true'
    const timeout = window.setTimeout(() => finish(new WeComQrError('企业微信登录组件加载超时，请刷新二维码重试')), 15_000)
    function finish(error?: Error) {
      window.clearTimeout(timeout)
      script.onload = null
      script.onerror = null
      if (error) {
        script.remove()
        loadingSdk = null
        reject(error)
      } else {
        resolve(window.ww!)
      }
    }
    script.onload = () => typeof window.ww?.createWWLoginPanel === 'function'
      ? finish()
      : finish(new WeComQrError('企业微信登录组件不可用，请刷新二维码重试'))
    script.onerror = () => finish(new WeComQrError('无法加载企业微信登录组件，请检查网络后重试'))
    document.head.append(script)
  })
  return loadingSdk
}

export function validateWeComQrSession(session: WeComQrSession, origin = window.location.origin): void {
  let callback: URL
  try { callback = new URL(session.redirect_uri) } catch { throw new WeComQrError('企业微信登录回调地址无效，请联系管理员') }
  if (callback.origin !== origin || callback.pathname !== '/api/auth/wecom/callback/'
    || callback.search || callback.hash || callback.username || callback.password) {
    throw new WeComQrError('企业微信登录回调必须使用当前 ERP 的固定地址，请联系管理员')
  }
  if (session.login_type !== 'CorpApp' || !session.appid || !/^\d+$/.test(session.agentid)
    || !/^[A-Za-z0-9_-]{43}$/.test(session.state) || !Number.isFinite(Date.parse(session.expires_at))) {
    throw new WeComQrError('企业微信扫码配置不完整，请联系管理员')
  }
  if (Date.parse(session.expires_at) <= Date.now()) throw new WeComQrError('二维码已失效，请刷新后重试')
}

export function buildWeComCallbackUrl(session: WeComQrSession, code: string): string {
  validateWeComQrSession(session)
  if (typeof code !== 'string' || !code || code.length > 1024 || /[\u0000-\u0020\u007f]/.test(code)) {
    throw new WeComQrError('企业微信返回的登录凭证无效，请重新扫码')
  }
  const url = new URL('/api/auth/wecom/callback/', window.location.origin)
  url.searchParams.set('code', code)
  url.searchParams.set('state', session.state)
  return url.toString()
}
