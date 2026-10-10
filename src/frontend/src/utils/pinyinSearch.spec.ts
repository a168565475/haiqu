import { describe, expect, it } from 'vitest'

import { matchesPinyinSearch, normalizePinyinSearch } from './pinyinSearch'

describe('pinyinSearch', () => {
  const hiddenSearchValue = 'bianyuanguan bian yuan guan byg'

  it.each(['B', 'BYG', 'bianyuan', 'bian yuan', '扁圆'])(
    '支持通过 %s 匹配扁圆管',
    (query) => {
      expect(matchesPinyinSearch('扁圆管', hiddenSearchValue, query)).toBe(true)
    },
  )

  it('忽略大小写、空格和常见分隔符', () => {
    expect(normalizePinyinSearch(' Tie-Zhong_Guang ')).toBe('tiezhongguang')
  })

  it('缺少拼音字段时仍可按中文检索', () => {
    expect(matchesPinyinSearch('铁-中光', undefined, '铁中光')).toBe(true)
    expect(matchesPinyinSearch('铁-中光', undefined, 'tzg')).toBe(false)
  })
})
