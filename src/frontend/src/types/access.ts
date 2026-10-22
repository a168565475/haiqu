export type AccessScope = 'OWN' | 'TEAM' | 'ALL' | 'MODULE' | 'WORKSHOP' | 'CRAFT' | 'STOCK'
export interface Grant { permission: string; scope: AccessScope; resource_ids?: string[] }
export interface ScopeOption { id: string; name: string; active: boolean }
export interface ScopeOptions { enabled: boolean; workshops: ScopeOption[]; crafts: ScopeOption[] }
export interface AccessRole { id: string; role_code: string; display_name: string; description: string; department_id: string | null; archived: boolean; assigned_employee_count: number; grants: Grant[]; etag: string }
export interface CatalogEntry { code: string; module: string; module_name: string; label: string; resource: string; resource_name: string; action: string; action_name: string; scopes: AccessScope[]; available: boolean; integration_stage: number; implied_permissions: string[] }
export interface AccessEmployee { id: string; employee_code: string; display_name: string; status: string; username: string | null; account_active: boolean | null; account_protected: boolean; team_id: string | null; department: string; wecom_departments?: { id: number; name: string | null }[] | null; role_ids: string[]; etag: string }
export interface SalesTeam { id: string; code: string; name: string; manager_id: string; manager_name: string; is_active: boolean; member_ids: string[]; etag: string }
export interface EffectiveAccess { active: boolean; is_superuser: boolean; roles: {id: string; name: string; code: string}[]; actions: Record<string, {scopes: AccessScope[]; sources: {type: string; role_id?: string; scope?: AccessScope; resource_ids?: string[]}[]}>; legacy_sources: {type: string; permission: string; name?: string}[]; version: string }
export interface AccessAudit { id: string; actor_name_snapshot: string; object_type: string; object_id: string; action: string; before_data: Record<string, unknown>; after_data: Record<string, unknown>; occurred_at: string }
export interface AccessPage<T> { data: T[]; meta: {page: number; page_size: number; total: number; total_pages: number} }
export interface AccessDepartment { id: string; unit_code: string; unit_name: string; parent_id: string | null; status: 'ACTIVE' | 'INACTIVE'; sort_order: number; etag: string }
export interface EmployeeDepartmentInput { department_id: string; is_primary: boolean; position_title: string }
export interface EmployeeDepartmentAssignment extends EmployeeDepartmentInput { id: string; department_name: string; effective_from: string; effective_to: string | null }
export interface EmployeeDepartments { employee_id: string; etag: string; departments: EmployeeDepartmentAssignment[] }
