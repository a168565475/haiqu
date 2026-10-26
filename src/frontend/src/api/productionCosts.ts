import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { CreateProductionTaskExpenseInput, ProductionTaskCostSummary, ProductionTaskExpense, ProductionTaskExpenseInput } from '@/types/productionCost'

const taskPath = (taskId: string) => `/api/v1/production-tasks/${encodeURIComponent(taskId)}/`
const expensesPath = (taskId: string) => `${taskPath(taskId)}cost-expenses/`
const expensePath = (taskId: string, expenseId: string) => `${expensesPath(taskId)}${encodeURIComponent(expenseId)}/`

export async function fetchProductionTaskCostSummary(taskId: string): Promise<ProductionTaskCostSummary> {
  const { data } = await apiClient.get<DataResponse<ProductionTaskCostSummary>>(`${taskPath(taskId)}cost-summary/`)
  return data.data
}
export async function fetchProductionTaskExpenses(taskId: string): Promise<ProductionTaskExpense[]> {
  const { data } = await apiClient.get<DataResponse<ProductionTaskExpense[]>>(expensesPath(taskId))
  return data.data
}
export async function createProductionTaskExpense(taskId: string, payload: CreateProductionTaskExpenseInput): Promise<ProductionTaskExpense> {
  const { data } = await apiClient.post<DataResponse<ProductionTaskExpense>>(expensesPath(taskId), payload)
  return data.data
}
export async function updateProductionTaskExpense(taskId: string, expenseId: string, payload: Partial<ProductionTaskExpenseInput>, etag: string): Promise<ProductionTaskExpense> {
  const { data } = await apiClient.patch<DataResponse<ProductionTaskExpense>>(expensePath(taskId, expenseId), payload, { headers: { 'If-Match': etag } })
  return data.data
}
export async function voidProductionTaskExpense(taskId: string, expenseId: string, etag: string): Promise<void> {
  await apiClient.delete(expensePath(taskId, expenseId), { headers: { 'If-Match': etag } })
}
