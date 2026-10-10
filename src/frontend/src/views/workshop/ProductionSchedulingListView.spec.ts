import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('计划排产列表进度列', () => {
  it('在计划日期范围后显示四行对应进度，材料入库固定为 100%', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/ProductionSchedulingListView.vue'),
      'utf8',
    )
    const dateColumn = source.indexOf('label="计划日期范围"')
    const progressColumn = source.indexOf('label="进度"')

    expect(dateColumn).toBeGreaterThan(-1)
    expect(progressColumn).toBeGreaterThan(dateColumn)
    expect(source).toContain("if (key === 'MATERIAL') return '100%'")
    expect(source).toContain("progressDisplay(row, 'METAL')")
    expect(source).toContain("progressDisplay(row, 'SEWING')")
    expect(source).toContain("progressDisplay(row, 'ASSEMBLY')")
  })
})
