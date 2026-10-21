import { isAxiosError } from 'axios'
import { apiClient } from './request'
import type { AccessAudit, AccessEmployee, AccessPage, AccessRole, CatalogEntry, EffectiveAccess, Grant, SalesTeam, ScopeOptions } from '@/types/access'
import type { AccessDepartment, EmployeeDepartmentInput, EmployeeDepartments } from '@/types/access'

const root = '/api/v1/access/'
const options = (etag?: string) => ({ timeout: 20000, ...(etag ? {headers: {'If-Match': etag}} : {}) })
async function all<T>(path: string): Promise<T[]> {
  const out: T[] = []
  let page = 1
  while (true) {
    const {data} = await apiClient.get<AccessPage<T>>(root + path, {...options(), params: {page, page_size: 100}})
    out.push(...data.data)
    if (page >= data.meta.total_pages) return out
    page++
  }
}
export const getCatalog = async () => (await apiClient.get<CatalogEntry[]>(root + 'catalog/', options())).data
export const getScopeOptions = async () => (await apiClient.get<ScopeOptions>(root + 'catalog/scope-options/', options())).data
export const getRoles = () => all<AccessRole>('roles/')
export const getDepartments = () => all<AccessDepartment>('departments/')
export const createDepartment = async (data: {unit_code: string; unit_name: string; parent_id: string | null; sort_order: number}) => (await apiClient.post<AccessDepartment>(root + 'departments/', data, options())).data
export const updateDepartment = async (department: AccessDepartment, data: {unit_name?: string; status?: 'ACTIVE' | 'INACTIVE'; sort_order?: number}) => (await apiClient.patch<AccessDepartment>(root + `departments/${department.id}/`, data, options(department.etag))).data
export const setRoleDepartment = async (role: AccessRole, department_id: string | null) => (await apiClient.put<AccessRole>(root + `roles/${role.id}/department/`, {department_id}, options(role.etag))).data
export const getEmployeeDepartments = async (employee: AccessEmployee) => (await apiClient.get<EmployeeDepartments>(root + `employees/${employee.id}/departments/`, options())).data
export const assignDepartments = async (employee: AccessEmployee, departments: EmployeeDepartmentInput[], etag: string) => (await apiClient.put<EmployeeDepartments>(root + `employees/${employee.id}/departments/`, {departments}, options(etag))).data
export const getEmployees = () => all<AccessEmployee>('employees/')
export const getTeams = () => all<SalesTeam>('sales-teams/')
export const getAudit = async (page = 1) => (await apiClient.get<AccessPage<AccessAudit>>(root + 'audit-events/', {...options(), params: {page}})).data
export const createRole = async (data: {role_code: string; display_name: string; description: string}) => (await apiClient.post<AccessRole>(root + 'roles/', data, options())).data
export const copyRole = async (role: AccessRole, data: {role_code: string; display_name: string; description: string}) => (await apiClient.post<AccessRole>(root + `roles/${role.id}/copy/`, data, options(role.etag))).data
export const updateRole = async (role: AccessRole, data: {display_name?: string; description?: string; archived?: boolean}) => (await apiClient.patch<AccessRole>(root + `roles/${role.id}/`, data, options(role.etag))).data
export const saveGrants = async (role: AccessRole, grants: Grant[]) => (await apiClient.put<AccessRole>(root + `roles/${role.id}/grants/`, {grants}, options(role.etag))).data
export const assignRoles = async (employee: AccessEmployee, role_ids: string[]) => (await apiClient.put<AccessEmployee>(root + `employees/${employee.id}/roles/`, {role_ids}, options(employee.etag))).data
export const createAccount = async (employee: AccessEmployee, data: {username: string; password: string}) => (await apiClient.post<AccessEmployee>(root + `employees/${employee.id}/account/`, data, options(employee.etag))).data
export const setAccountStatus = async (employee: AccessEmployee, is_active: boolean) => (await apiClient.patch<AccessEmployee>(root + `employees/${employee.id}/account/`, {is_active}, options(employee.etag))).data
export const resetPassword = async (employee: AccessEmployee, password: string) => (await apiClient.post<AccessEmployee>(root + `employees/${employee.id}/reset-password/`, {password}, options(employee.etag))).data
export const getEffectiveAccess = async (employee: AccessEmployee) => (await apiClient.get<EffectiveAccess>(root + `employees/${employee.id}/effective-access/`, options())).data
export const createTeam = async (data: {code: string; name: string; manager_id: string}) => (await apiClient.post<SalesTeam>(root + 'sales-teams/', data, options())).data
export const updateTeam = async (team: SalesTeam, data: {name?: string; is_active?: boolean}) => (await apiClient.patch<SalesTeam>(root + `sales-teams/${team.id}/`, data, options(team.etag))).data
export const addTeamMembers = async (team: SalesTeam, employee_ids: string[]) => (await apiClient.post<SalesTeam>(root + `sales-teams/${team.id}/members/`, {employee_ids}, options(team.etag))).data

export function accessError(error: unknown): string {
  if (!isAxiosError(error)) return '操作失败，请稍后重试。'
  if (!error.response) return '请求未确认完成，请刷新核实结果后再操作。'
  if (error.response.status === 412) return '配置已被修改，请先重新加载，核对最新内容后再保存。'
  return error.response.data?.error?.message || error.response.data?.detail || '操作未完成，请重试。'
}
