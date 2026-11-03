import type { ReportingScope } from '@/types/reporting'

type EmployeeScope = Pick<ReportingScope, 'workshop_id' | 'craft_id'>

function storageKey(userId: number, scope: EmployeeScope) {
  return `haiqu-mobile:report-employees:${JSON.stringify([userId, scope.workshop_id, scope.craft_id])}`
}

export function loadReportEmployees(userId: number, scope: EmployeeScope): Record<string, string> {
  const saved = localStorage.getItem(storageKey(userId, scope))
  if (saved === null) return {}
  const employees: unknown = JSON.parse(saved)
  if (!employees || typeof employees !== 'object' || Array.isArray(employees)
    || Object.values(employees).some(value => typeof value !== 'string')) {
    throw new Error('保存的报工员工格式无效。')
  }
  return employees as Record<string, string>
}

export function saveReportEmployees(userId: number, scope: EmployeeScope, employees: Record<string, string>) {
  localStorage.setItem(storageKey(userId, scope), JSON.stringify(employees))
}
