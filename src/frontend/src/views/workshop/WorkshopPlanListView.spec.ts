import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('内部作业计划报工记录入口', () => {
  it('四个计划共用的操作菜单包含按排产产品查看报工记录的入口', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/WorkshopPlanListView.vue'),
      'utf8',
    )

    expect(source).toContain("auth.hasPermission('workshop_reporting.view_workreport')")
    expect(source).toContain('if (result.data.length)')
    expect(source).toContain("if (!status && wageStatusError.value) return '加载失败'")
    expect(source).toContain('function openWorkReportRecords(row: ScheduleItem)')
    expect(source).toContain("if (!wageStatuses.value[row.id]?.workshop_id) return")
    expect(source).toContain("name: 'work-report-days'")
    expect(source).toContain('schedule_product_id: row.id')
    expect(source).toContain('craft_id: wageStatuses.value[row.id]?.craft_id')
    expect(source).toContain(':disabled="!wageStatus(row)?.workshop_id"')
    expect(source).toContain('>查看报工记录</ElDropdownItem>')
    expect(source).toContain('label="完成进度"')
    expect(source).toContain('`${status.progress_percent}%`')
    expect(source).toContain('label="预计工价"')
    expect(source).toContain('formatWageMoney(wageStatus(row)?.estimated_wage)')
  })

  it('计划表格将任务单号、排产单号、规格和颜色拆成独立列且不显示产品图片', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/WorkshopPlanListView.vue'),
      'utf8',
    )

    const taskColumn = source.indexOf('label="生产任务单号"')
    const scheduleColumn = source.indexOf('label="排产单号"')
    const productColumn = source.indexOf('label="产品名称"')
    const specificationColumn = source.indexOf('label="规格"')
    const colorColumn = source.indexOf('label="颜色"')
    expect(taskColumn).toBeGreaterThan(-1)
    expect(scheduleColumn).toBeGreaterThan(taskColumn)
    expect(productColumn).toBeGreaterThan(scheduleColumn)
    expect(specificationColumn).toBeGreaterThan(productColumn)
    expect(colorColumn).toBeGreaterThan(specificationColumn)
    expect(source).not.toContain('排产单号 / 生产任务单号')
    expect(source).not.toContain('<img')
  })
})
