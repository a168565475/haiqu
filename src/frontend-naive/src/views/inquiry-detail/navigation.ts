export function inquiryListReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/inquiries')) return '/inquiries';
  try {
    if (/[\\\u0000-\u001f]/.test(decodeURIComponent(value))) return '/inquiries';
    const url = new URL(value, 'https://naive.local');
    return url.origin === 'https://naive.local' && url.pathname === '/inquiries'
      ? `${url.pathname}${url.search}${url.hash}`
      : '/inquiries';
  } catch {
    return '/inquiries';
  }
}
