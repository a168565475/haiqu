export function normalizePinyinSearch(value: unknown): string {
  return String(value ?? '')
    .toLocaleLowerCase()
    .replace(/[\s'’_./-]+/g, '')
}

export function matchesPinyinSearch(
  label: unknown,
  pinyinSearch: unknown,
  query: unknown,
): boolean {
  const keyword = normalizePinyinSearch(query)
  if (!keyword) return true
  return [label, pinyinSearch].some((value) => normalizePinyinSearch(value).includes(keyword))
}
