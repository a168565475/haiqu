import { apiClient } from '@/utils/request'
import type { CreateReportPayload, ReportPage, ReportingContext, ReportingRecordScope, ReportingScheme, ReportingScope, WorkReport } from '@/types/reporting'

const base = '/api/v1/workshop-reporting/'

export async function fetchReportingContext(scheduleProductId: string, signal?: AbortSignal): Promise<ReportingContext> {
  const response = await apiClient.get<{ data: ReportingContext }>(`${base}context/`, {
    params: { schedule_product_id: scheduleProductId, purpose: 'work_report' }, signal,
  })
  if (!response.data.data?.schedule_product || !Array.isArray(response.data.data.employees)
    || !Array.isArray(response.data.data.workshops) || !Array.isArray(response.data.data.crafts)) {
    throw new Error('生产任务信息不完整，请返回列表重新选择。')
  }
  return response.data.data
}

export async function fetchReportingScheme(scope: ReportingScope, productLineId: string, productionDate: string, signal?: AbortSignal): Promise<ReportingScheme> {
  const response = await apiClient.get<{ data: ReportingScheme }>(`${base}work-reports/price-context/`, {
    params: {
      product_line_id: productLineId, schedule_product_id: scope.schedule_product_id,
      workshop_id: scope.workshop_id, craft_id: scope.craft_id, production_date: productionDate,
    }, signal,
  })
  const scheme = response.data.data
  if (!scheme || !Array.isArray(scheme.lines) || scheme.status !== 'APPROVED'
    || scheme.product_line_id !== productLineId || scheme.workshop?.id !== scope.workshop_id
    || scheme.scope_craft?.id !== scope.craft_id || !Number.isInteger(scheme.revision) || scheme.revision < 1) {
    throw new Error('适用工价信息不完整或已经变化，请刷新核对。')
  }
  return scheme
}

export async function createWorkReport(payload: CreateReportPayload): Promise<WorkReport> {
  const response = await apiClient.post<{ data: WorkReport }>(`${base}work-reports/`, payload, { timeout: 30000 })
  if (!response.data.data?.id || !Array.isArray(response.data.data.lines)) throw new Error('未收到报工结果，请重试核对本次提交。')
  return response.data.data
}

export async function fetchWorkReports(scope: ReportingRecordScope, page: number, signal?: AbortSignal): Promise<ReportPage> {
  const response = await apiClient.get<ReportPage>(`${base}work-reports/`, {
    params: { schedule_product_id: scope.schedule_product_id, workshop_id: scope.workshop_id, plan_category: scope.plan_category, ...(scope.craft_id ? { craft_id: scope.craft_id } : {}), page, page_size: 20 }, signal,
  })
  const result = response.data
  if (!Array.isArray(result.data) || !result.data.every(report => report.id && Array.isArray(report.lines))
    || !result.meta || !Number.isInteger(result.meta.page) || result.meta.page < 1
    || !Number.isInteger(result.meta.total_pages) || result.meta.total_pages < 0
    || !Number.isInteger(result.meta.total) || result.meta.total < 0) {
    throw new Error('报工记录返回不完整，请重新加载。')
  }
  return result
}
