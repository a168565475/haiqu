export function wecomRouteRedirect(name: unknown, authenticated: boolean, waiting: boolean) {
  if (!authenticated || name === 'wecom-error') return
  if (waiting && name !== 'waiting-role') return { name: 'waiting-role' }
  if (!waiting && name === 'waiting-role') return { name: 'home' }
}
