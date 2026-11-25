import type { ReportingOption, WorkReportPlanCategory } from '@/types/workshopReporting'

interface WorkshopChoice {
  key: string
  workshopId: string
  name: string
  planCategory?: WorkReportPlanCategory
}

export function workReportWorkshopChoices(workshops: ReportingOption[]): WorkshopChoice[] {
  return workshops.filter(workshop => workshop.name !== '敲布孔').flatMap((workshop): WorkshopChoice[] => {
    if (workshop.name === '车缝车间') {
      return [
        { key: `${workshop.id}:CUTTING`, workshopId: workshop.id, name: '裁剪', planCategory: 'CUTTING' },
        { key: `${workshop.id}:SEWING`, workshopId: workshop.id, name: workshop.name, planCategory: 'SEWING' },
      ]
    }
    return [{ key: workshop.id, workshopId: workshop.id, name: workshop.name }]
  })
}
