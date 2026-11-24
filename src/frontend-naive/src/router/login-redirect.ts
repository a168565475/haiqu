import type { Router } from 'vue-router';

/** 登录只返回本前端已注册的页面，避免外部跳转和登录循环。 */
export function getLoginRedirect(redirect: unknown, routeExists: (path: string) => boolean): string {
  const fallback = '/customers';
  if (typeof redirect !== 'string' || !redirect.startsWith('/')) return fallback;

  let decoded: string;
  try {
    decoded = decodeURIComponent(redirect);
  } catch {
    return fallback;
  }
  if (decoded.startsWith('//') || /[\\\u0000-\u001f]/.test(decoded)) return fallback;

  const url = new URL(redirect, 'https://naive.local');
  const pathname = decodeURIComponent(url.pathname).toLowerCase();
  if (url.origin !== 'https://naive.local' || /^\/login(?:\/|$)/.test(pathname)) return fallback;

  const target = `${url.pathname}${url.search}${url.hash}`;
  return routeExists(target) ? target : fallback;
}

export function resolveLoginRedirect(router: Pick<Router, 'resolve'>, redirect: unknown) {
  const target = getLoginRedirect(redirect, path => {
    const resolved = router.resolve(path);
    return resolved.matched.length > 0 && resolved.name !== 'not-found' && !resolved.meta.href;
  });
  const resolved = router.resolve(target);
  // 守卫返回对象时，Vue Router 不会从 path 中保留 query/hash，必须显式传递。
  return { path: resolved.path, query: resolved.query, hash: resolved.hash, replace: true };
}
