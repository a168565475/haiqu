import axios from 'axios'

export function isLocalProductionSyncAvailable() {
  return import.meta.env.DEV && window.location.port === '8080'
    && ['localhost', '127.0.0.1'].includes(window.location.hostname)
}

export async function syncLocalProduction() {
  const { data } = await axios.post<{ tasks: number; boms: number }>(
    `http://${window.location.hostname}:18724/sync`,
    undefined,
    { withCredentials: true, withXSRFToken: true, xsrfCookieName: 'csrftoken', xsrfHeaderName: 'X-CSRFToken' },
  )
  return data
}
