<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter, type LocationQuery } from 'vue-router'
import { ElDropdown, ElDropdownItem, ElDropdownMenu, ElMessage, ElSelect, ElOption, ElPagination } from 'element-plus'
import { isAxiosError } from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import PermissionCell from '@/components/access/PermissionCell.vue'
import DepartmentMaintenanceDialog from '@/components/access/DepartmentMaintenanceDialog.vue'
import EmployeeDepartmentsDialog from '@/components/access/EmployeeDepartmentsDialog.vue'
import EmployeeDirectoryDialog from '@/views/employees/EmployeeDirectoryDialog.vue'
import DepartmentMappingDialog from '@/views/employees/DepartmentMappingDialog.vue'
import DeleteManagementDialog from '@/components/access/DeleteManagementDialog.vue'
import type { DeletionKind, DeletionItem } from '@/types/access'
import { useAuthStore } from '@/stores/auth'
import { createClientUuid } from '@/utils/clientUuid'
import { accessMenuOptions, groupAccessCatalog, permissionMenu } from '@/utils/accessMenuGroups'
import * as api from '@/api/access'
import type { AccessAudit, AccessEmployee, AccessRole, AccessScope, CatalogEntry, EffectiveAccess, Grant, SalesTeam, ScopeOptions } from '@/types/access'
import type { AccessDepartment } from '@/types/access'

const props = defineProps<{ employeesOnly?: boolean; embedded?: boolean }>()
const auth = useAuthStore()
const route = useRoute(), router = useRouter()
const permitted = computed(() => auth.canReadAccessDirectory)
const canManageAccess = computed(() => auth.managementCan('access_control.manage_access'))
const canCreateAccount = computed(() => auth.user?.is_superuser === true && canManageAccounts.value)
const canManageAccounts = computed(() => auth.managementCan('access_control.manage_accounts'))
const canManageOrganization = computed(() => auth.managementCan('organizations.manage_organization'))
const canAdjustEmployees = computed(() => canManageOrganization.value && canManageAccess.value)
const canSelectEmployees = computed(() => canManageAccounts.value || canManageOrganization.value || canManageAccess.value)
const tab = ref(props.employeesOnly ? 'employees' : 'roles')
const directoryOpen = ref(false), mappingOpen = ref(false), employeeStatus = ref('all')
const fillDepartmentMode = ref(false), selectedEmployees = ref<string[]>([])
const employeeDepartmentFilter = ref('all'), wecomDepartmentFilter = ref('all')
const employeeRoleFilter = ref('all')
const employeeRoleIdFilter = ref('all')
const batchDepartments = ref<string[]>([]), batchRoles = ref<string[]>([]), batchSaving = ref(false), batchError = ref('')
const deleteKind = ref<DeletionKind>('employees'), deleteItems = ref<DeletionItem[]>([])
function requestDeletion(kind: DeletionKind, items: DeletionItem[]) { deleteKind.value = kind; deleteItems.value = items.map(item => ({ id: item.id, etag: item.etag })) }
async function deleted(selfDeleted: boolean) {
  selectedEmployees.value = []; deleteItems.value = []
  if (selfDeleted) { await auth.initialize(true); await router.replace('/login'); return }
  await load(true)
}
function readEmployees(fill = true) { fillDepartmentMode.value = fill; directoryOpen.value = true }
function selectPage(checked: boolean) {
  const ids = employeeRows.value.map(employee => employee.id)
  selectedEmployees.value = checked ? [...new Set([...selectedEmployees.value, ...ids])] : selectedEmployees.value.filter(id => !ids.includes(id))
}
const tabs = computed(() => [{id:'roles',name:'角色与权限'},
  ...(canManageAccess.value ? [{id:'teams',name:'销售团队'},{id:'history',name:'授权记录'}] : [])])
const roles = ref<AccessRole[]>([]), employees = ref<AccessEmployee[]>([]), teams = ref<SalesTeam[]>([]), catalog = ref<CatalogEntry[]>([])
const departments = ref<AccessDepartment[]>([]), departmentId = ref('all'), departmentMaintenance = ref(false), departmentEmployee = ref<AccessEmployee>()
const departmentList = computed(() => departments.value.filter(d => d.unit_code !== 'HAIQU'))
const batchEmployees = computed(() => employees.value.filter(employee => selectedEmployees.value.includes(employee.id)))
const batchRoleOptions = computed(() => roles.value.filter(role => !role.archived && role.department_id && batchDepartments.value.includes(role.department_id)))
watch([batchDepartments, selectedEmployees], () => {
  batchRoles.value = []; batchError.value = ''
  if (!selectedEmployees.value.length && batchDepartments.value.length) batchDepartments.value = []
})
watch(canManageOrganization, allowed => { if (!allowed) batchDepartments.value = [] })
watch(canManageAccess, allowed => { if (!allowed) batchRoles.value = [] })
async function adjustSelectedEmployees() {
  if (batchSaving.value || !batchEmployees.value.length || !canAdjustEmployees.value) return
  batchSaving.value = true; batchError.value = ''
  try {
    const result = await api.adjustEmployees({
      items: batchEmployees.value.map(employee => ({ id: employee.id, etag: employee.etag })),
      department_ids: [...batchDepartments.value],
      role_ids: [...batchRoles.value],
    })
    selectedEmployees.value = []; batchDepartments.value = []; batchRoles.value = []
    ElMessage.success(`已调整 ${result.updated_count} 名员工`)
    await load(true)
  } catch (e) { batchError.value = api.accessError(e) } finally { batchSaving.value = false }
}
function departmentName(id: string | null) { return id ? departments.value.find(d => d.id === id)?.unit_name || '历史部门' : '未分类' }
function chooseDepartment(id: string) {
  if (dirty.value) { ElMessage.warning('请先保存或撤销当前角色修改。'); return }
  departmentId.value = id
  chooseRole(visibleRoles.value.some(r => r.id === roleId.value) ? roleId.value : visibleRoles.value[0]?.id || '')
}
const logs = ref<AccessAudit[]>([]), auditPage = ref(1), auditPages = ref(1)
const roleId = ref(''), teamId = ref(''), grants = ref<Grant[]>([])
const role = computed(() => roles.value.find(r => r.id === roleId.value))
const team = computed(() => teams.value.find(t => t.id === teamId.value))
const loading = ref(false), saving = ref(false), error = ref(''), stale = ref(false)
const roleQuery = ref(''), roleFilter = ref(''), moduleQuery = ref(''), moduleFilter = ref(''), moduleGroup = ref('all')
const employeeQuery = ref(''), employeeFilter = ref(''), accountFilter = ref('all'), employeePage = ref(1)
const employeePageSize = ref(50)
function lastLoginText(employee: AccessEmployee) {
  if (!employee.username) return '—'
  if (employee.last_login === undefined) return 'UNKNOWN'
  return employee.last_login ? new Date(employee.last_login).toLocaleString('zh-CN', { hour12: false }) : '未登录'
}
const dialog = ref(''), dialogError = ref(''), subject = ref<AccessEmployee>(), effective = ref<EffectiveAccess>(), auditDetail = ref<AccessAudit>()
const assignableRoles = computed(() => roles.value.filter(role => role.department_id && subject.value?.department_ids?.includes(role.department_id)))
const retainedRoles = computed(() => roles.value.filter(role => subject.value?.role_ids.includes(role.id) && !assignableRoles.value.some(item => item.id === role.id)))
const specialResource = ref('')
const scopeOptions = ref<ScopeOptions>({enabled:false,workshops:[],crafts:[]})
const scopeCode = ref(''), scopeSelection = ref<string[]>([]), scopeReturnDialog = ref('')
const selectedScopeGrant = computed(() => grants.value.find(g=>g.permission===scopeCode.value && ['WORKSHOP','CRAFT'].includes(g.scope)))
const resourceOptions = computed(() => selectedScopeGrant.value?.scope==='WORKSHOP' ? scopeOptions.value.workshops : scopeOptions.value.crafts)
function resourceLabel(scope: AccessScope, ids: string[] = []) {
  const options = scope==='WORKSHOP'?scopeOptions.value.workshops:scopeOptions.value.crafts
  return ids.length ? ids.map(id=>options.find(o=>o.id===id)?.name||'历史资源').join('、') : '未选择（无可访问资源）'
}
function configureScope(code: string) {
  scopeCode.value=code
  scopeSelection.value=[...(selectedScopeGrant.value?.resource_ids||[])]
  scopeReturnDialog.value=dialog.value==='special'?'special':''
  dialogError.value='';dialog.value='resources'
}
function applyScope() {
  const grant=selectedScopeGrant.value
  if(grant) grant.resource_ids=[...scopeSelection.value].sort()
  dialog.value=scopeReturnDialog.value
}
let effectiveRequest = 0
const form = reactive({code:'', name:'', description:'', username:'', password:'', employeeId:'', managerId:'', departmentId:'', roleIds:[] as string[], memberIds:[] as string[]})
const scopeNames: Record<string,string> = {OWN:'本人',TEAM:'所管团队',ALL:'全部',MODULE:'按模块',WORKSHOP:'指定车间',CRAFT:'指定工艺',STOCK:'库存来源'}
const operationColumns = [{key:'view',label:'查看'},{key:'add',label:'新增'},{key:'change',label:'编辑'},{key:'delete',label:'删除'},{key:'submit',label:'提交'},{key:'approve',label:'审批'}]
const catalogByCode = computed(() => Object.fromEntries(catalog.value.map(c => [c.code,c])))
const normalize = (rows: Grant[]) => JSON.stringify([...rows].sort((a,b) => (a.permission+a.scope).localeCompare(b.permission+b.scope)))
const dirty = computed(() => !!role.value && normalize(grants.value) !== normalize(role.value.grants))
const visibleRoles = computed(() => roles.value.filter(r => r.display_name.includes(roleFilter.value) && (departmentId.value === 'all' || (departmentId.value === 'unclassified' ? !r.department_id : r.department_id === departmentId.value))))
const groups = computed(() => groupAccessCatalog(catalog.value))
const visibleGroups = computed(() => groups.value.filter(g => (moduleGroup.value === 'all' || g.module === moduleGroup.value) && (g.name+g.moduleName).includes(moduleFilter.value)))
const moduleOptions = computed(() => [
  ...accessMenuOptions.map(menu => [menu.key, menu.label]),
  ...(groups.value.some(group => group.module === 'unmapped') ? [['unmapped', '其他权限']] : []),
])
const moduleEntries = computed(() => catalog.value.filter(entry => permissionMenu(entry) === moduleGroup.value))
const emptyPermissionMessage = computed(() => ['workbench', 'boards'].includes(moduleGroup.value)
  ? '此菜单没有独立权限项，沿用对应业务页面的权限，请在生产、车间、仓库等分组中配置。'
  : '没有匹配的业务模块')
const grantsDisabled = computed(() => !role.value || role.value.archived || loading.value || saving.value || stale.value || !canManageAccess.value)
const selectedPermissionCodes = computed(() => new Set(grants.value.map(grant => grant.permission)))
function selectionState(entries: CatalogEntry[]) {
  const available = entries.filter(entry => entry.available)
  const selected = available.filter(entry => selectedPermissionCodes.value.has(entry.code)).length
  return { checked: available.length > 0 && selected === available.length, partial: selected > 0 && selected < available.length, empty: available.length === 0 }
}
function selectGrants(entries: CatalogEntry[], checked: boolean) {
  if (grantsDisabled.value) return
  const available = entries.filter(entry => entry.available)
  const codes = new Set(available.map(entry => entry.code))
  if (!checked) {
    grants.value = grants.value.filter(grant => !codes.has(grant.permission))
    return
  }
  const selected = new Set(grants.value.map(grant => grant.permission))
  // 只补充未勾选项，保留已有数据范围及指定车间/工艺；默认范围与单项勾选一致。
  grants.value = [...grants.value, ...available.filter(entry => !selected.has(entry.code)).map(entry => ({
    permission: entry.code, scope: (entry.scopes.includes('MODULE') ? 'MODULE' : 'OWN') as AccessScope,
  }))]
}
const specialEntries = computed(() => groups.value.find(g => g.key === specialResource.value)?.entries.filter(e => e.action === 'special') || [])
const wecomDepartmentOptions = computed(() => {
  const options = new Map<number, string>()
  employees.value.forEach(employee => employee.wecom_departments?.forEach(department => options.set(department.id, department.name || String(department.id))))
  return [...options].map(([id, name]) => ({ id: String(id), name })).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})
const employeeRoleOptions = computed(() => roles.value.filter(role => employeeDepartmentFilter.value === 'all' || role.department_id === employeeDepartmentFilter.value))
watch(employeeDepartmentFilter, () => { employeeRoleIdFilter.value = 'all' })
const filteredEmployees = computed(() => employees.value.filter(e =>
  `${e.display_name} ${e.employee_code} ${e.username || ''} ${e.department}`.toLocaleLowerCase().includes(employeeFilter.value.trim().toLocaleLowerCase())
  && (employeeStatus.value === 'all' || e.status === employeeStatus.value)
  && (employeeRoleFilter.value === 'all' || (employeeRoleFilter.value === 'assigned' ? e.role_ids.length > 0 : e.role_ids.length === 0))
  && (employeeRoleIdFilter.value === 'all' || e.role_ids.includes(employeeRoleIdFilter.value))
  && (accountFilter.value === 'all' || (accountFilter.value === 'none' ? !e.username : accountFilter.value === 'active' ? e.account_active : e.username && !e.account_active))
  && (employeeDepartmentFilter.value === 'all' || (employeeDepartmentFilter.value === 'none' ? e.department_ids?.length === 0 : e.department_ids?.includes(employeeDepartmentFilter.value)))
  && (wecomDepartmentFilter.value === 'all' || (wecomDepartmentFilter.value === 'none' ? e.wecom_departments?.length === 0 : e.wecom_departments?.some(department => String(department.id) === wecomDepartmentFilter.value)))
))
const employeePages = computed(() => Math.max(1,Math.ceil(filteredEmployees.value.length/employeePageSize.value)))
const employeeRows = computed(() => filteredEmployees.value.slice((employeePage.value-1)*employeePageSize.value,employeePage.value*employeePageSize.value))
const pageSelected = computed(() => employeeRows.value.length > 0 && employeeRows.value.every(employee => selectedEmployees.value.includes(employee.id)))
watch([employeeFilter, accountFilter, employeeStatus, employeeRoleFilter, employeeRoleIdFilter, employeeDepartmentFilter, wecomDepartmentFilter, employeePageSize], () => { employeePage.value = 1 }, { flush: 'sync' })
watch(employeePages, value => { employeePage.value = Math.min(employeePage.value, value) })
function wecomDepartmentNames(employee: AccessEmployee) {
  if (employee.wecom_departments == null) return 'UNKNOWN'
  return employee.wecom_departments.map(item => `${item.name?.trim() || 'UNKNOWN'}（${item.id}）`).join('、') || '未分配'
}
const teamMembers = computed(() => employees.value.filter(e => team.value?.member_ids.includes(e.id)))
const selectableEmployees = computed(() => employees.value.filter(e => e.status === 'ACTIVE'))
const businessEmployees = computed(() => {
  const department = departments.value.find(item => item.unit_code === 'DEPT_BUSINESS' && item.status === 'ACTIVE')
  return department ? selectableEmployees.value.filter(employee => employee.department_ids?.includes(department.id)) : []
})
const salesTeamCandidates = computed(() => businessEmployees.value.filter(employee => !employee.team_id))
const changes = computed(() => {
  const before = role.value?.grants || []
  const codes = new Set([...before,...grants.value].map(g=>g.permission))
  return [...codes].filter(code => normalize(before.filter(g=>g.permission===code)) !== normalize(grants.value.filter(g=>g.permission===code)))
    .map(code => ({label:catalogByCode.value[code]?.label || code, before:describe(before.filter(g=>g.permission===code)), after:describe(grants.value.filter(g=>g.permission===code))}))
})
function describe(rows: Grant[]) { return rows.length ? [...new Set(rows.map(g=>scopeNames[g.scope]+(['WORKSHOP','CRAFT'].includes(g.scope)?'：'+resourceLabel(g.scope,g.resource_ids):'')))].join(' + ') : '不允许' }
function effectiveDescription(entry: EffectiveAccess['actions'][string]) {
  return entry.scopes.map(scope=>scopeNames[scope]+(['WORKSHOP','CRAFT'].includes(scope)?'：'+resourceLabel(scope,[...new Set(entry.sources.filter(s=>s.scope===scope).flatMap(s=>s.resource_ids||[]))]):'')).join(' + ')
}
function sourceDescription(code: string, source: EffectiveAccess['actions'][string]['sources'][number]) {
  const name = roles.value.find(r => r.id === source.role_id)?.display_name || '超级管理员'
  return source.scope ? name + ' · ' + describe([{ permission: code, scope: source.scope, resource_ids: source.resource_ids }]) : name
}
function copyGrants(rows: Grant[] = []): Grant[] {
  return rows.map(g => ({ permission: g.permission, scope: g.scope,
    ...(g.resource_ids ? { resource_ids: [...g.resource_ids] } : {}),
  }))
}
function chooseRole(id: string) {
  if (dirty.value) { ElMessage.warning('请先保存或撤销当前角色修改。'); return }
  roleId.value=id; grants.value=copyGrants(role.value?.grants); stale.value=false
}
function resetDraft() { grants.value=copyGrants(role.value?.grants) }
function updateGrant(code: string, scopes: AccessScope[]) {
  if (!canManageAccess.value) return
  const previous=grants.value.filter(g=>g.permission===code)
  grants.value=[...grants.value.filter(g=>g.permission!==code),...scopes.map(scope=>({permission:code,scope,...(['WORKSHOP','CRAFT'].includes(scope)?{resource_ids:[...(previous.find(g=>g.scope===scope)?.resource_ids||[])]}:{})}))]
  if(scopes.some(s=>s==='WORKSHOP'||s==='CRAFT')) configureScope(code)
}
function basic(entries: CatalogEntry[], action: string) { return entries.find(e=>e.action===action) }
function specialCount(entries: CatalogEntry[]) { return entries.filter(e=>e.action==='special').length }
function roleNames(e: AccessEmployee) { return roles.value.filter(r=>e.role_ids.includes(r.id)).map(r=>r.display_name) }
function teamName(id: string | null) { return teams.value.find(t=>t.id===id)?.name || '未分组' }
function open(kind: string, employee?: AccessEmployee) {
  if (saving.value) return
  if (kind === 'account' && !canCreateAccount.value) return
  if (['account','password','status'].includes(kind) ? !canManageAccounts.value
    : ['roleDepartment','employeeName'].includes(kind) ? !canManageOrganization.value
      : !['effective','special'].includes(kind) && !canManageAccess.value) return
  dialogError.value=''; subject.value=employee
  effectiveRequest++
  Object.assign(form,{code:'',name:'',description:'',username:'',password:'',employeeId:employee?.id||'',managerId:'',roleIds:[...(employee?.role_ids||[])],memberIds:[]})
  form.departmentId = role.value?.department_id || ''
  if (kind==='editRole' && role.value) Object.assign(form,{name:role.value.display_name,description:role.value.description})
  if (kind==='employeeName' && employee) form.name=employee.display_name
  if (kind==='editTeam' && team.value) form.name=team.value.name
  if (['newRole','copyRole','newTeam'].includes(kind)) form.code=(kind==='newTeam'?'TEAM_':'ROLE_')+createClientUuid().replaceAll('-','').toUpperCase()
  dialog.value=kind
}
function close() { if (!saving.value) {effectiveRequest++;dialog.value=''; form.password=''; dialogError.value=''} }
function beforeClose(done: () => void) { if (!saving.value) {form.password='';dialogError.value='';done()} }
let employeesLoaded = false, handledEmployeeRoute = '', loadRequest = 0
function locateEmployeeFromRoute() {
  if (!permitted.value || !employeesLoaded || loading.value || saving.value || error.value) return
  const employeeId = route.query.employee_id
  const routeKey = JSON.stringify([route.query.tab, employeeId])
  if (routeKey === handledEmployeeRoute) return
  handledEmployeeRoute = routeKey
  if (route.query.tab !== 'employees' && employeeId === undefined) return
  if (!props.employeesOnly) {
    void router.replace({ path: '/employees', query: { ...route.query } })
    return
  }
  tab.value = 'employees'
  if (employeeId === undefined) return
  close()
  employeeQuery.value = ''; employeeFilter.value = ''; accountFilter.value = 'all'; employeeStatus.value = 'all'; employeePage.value = 1
  employeeDepartmentFilter.value = 'all'; wecomDepartmentFilter.value = 'all'
  employeeRoleFilter.value = 'all'; employeeRoleIdFilter.value = 'all'
  // 员工目标只消费一次，保存后的列表刷新和浏览器刷新都不重复打开分配弹窗。
  const query: LocationQuery = { ...route.query, tab: 'employees' }
  delete query.employee_id
  void router.replace({ query })
  if (typeof employeeId !== 'string' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(employeeId)) {
    ElMessage.warning('员工定位参数无效，请从员工管理重新进入。'); return
  }
  const index = employees.value.findIndex(employee => employee.id === employeeId.toLowerCase())
  const employee = employees.value[index]
  if (!employee) { ElMessage.warning('未找到该员工，可能已归档或记录已变化，请核对员工与账号列表。'); return }
  employeePage.value = Math.floor(index / employeePageSize.value) + 1
  if (employee.status !== 'ACTIVE') { ElMessage.warning('该员工当前非在职状态，不能分配角色。'); return }
  open('assign', employee)
}
watch(() => [route.query.tab, route.query.employee_id], () => {
  if (route.query.employee_id !== undefined) {
    if (dialog.value === 'assign') { close(); subject.value = undefined }
    void load()
  }
  else locateEmployeeFromRoute()
})
watch(permitted, value => {
  if (value) void load()
  else {
    loadRequest++; effectiveRequest++; employeesLoaded = false; loading.value = false
    employees.value = []; roles.value = []; teams.value = []; catalog.value = []; departments.value = []
    grants.value = []; selectedEmployees.value = []; deleteItems.value = []; dialog.value = ''
    directoryOpen.value = false; mappingOpen.value = false; departmentEmployee.value = undefined
  }
})
watch(canManageAccounts, value => { if (!value) { directoryOpen.value = false; selectedEmployees.value = []; if (deleteKind.value === 'employees') deleteItems.value = [] } })
watch(canManageAccess, value => { if (!value && deleteKind.value === 'roles') deleteItems.value = [] })
watch(canManageOrganization, value => { if (!value) { mappingOpen.value = false; departmentEmployee.value = undefined; departmentMaintenance.value = false } })
async function load(refreshAuth = false) {
  if (!permitted.value) return
  const request = ++loadRequest
  loading.value=true;error.value=''
  try {
    const [r,e,t,c,d]=await Promise.all([api.getRoles(),api.getEmployees(),canManageAccess.value ? api.getTeams() : Promise.resolve([]),api.getCatalog(),api.getDepartments()])
    const options=c.some(item=>item.scopes.some(s=>s==='WORKSHOP'||s==='CRAFT')) ? await api.getScopeOptions() : {enabled:false,workshops:[],crafts:[]}
    if (request !== loadRequest) return
    scopeOptions.value=options
    roles.value=r;employees.value=e;teams.value=t;catalog.value=c;departments.value=d;employeesLoaded=true
    selectedEmployees.value = selectedEmployees.value.filter(id => e.some(employee => employee.id === id))
    if (!['all','unclassified'].includes(departmentId.value) && !d.some(item => item.id === departmentId.value)) departmentId.value='all'
    const id=visibleRoles.value.some(x=>x.id===roleId.value)?roleId.value:visibleRoles.value[0]?.id||''
    roleId.value=id;grants.value=copyGrants(role.value?.grants);stale.value=false
    if (!t.some(x=>x.id===teamId.value)) teamId.value=t[0]?.id||''
    if(tab.value==='history') await loadHistory()
    if(refreshAuth) await auth.initialize(true)
  } catch(e) {if(request===loadRequest)error.value=api.accessError(e)} finally {if(request===loadRequest)loading.value=false}
  if(request===loadRequest) locateEmployeeFromRoute()
}
async function loadHistory(page=1) {
  const result=await api.getAudit(page);logs.value=result.data;auditPage.value=page;auditPages.value=Math.max(1,result.meta.total_pages)
}
async function changeTab(id: string) {
  if (!tabs.value.some(item => item.id === id)) return
  if(saving.value) return
  if(dirty.value) { ElMessage.warning('请先保存或撤销当前角色修改。'); return }
  tab.value=id
  if(id==='history') {loading.value=true;try{await loadHistory()}catch(e){error.value=api.accessError(e)}finally{loading.value=false}}
}
async function showEffective(employee: AccessEmployee) {
  open('effective',employee);effective.value=undefined
  const request=effectiveRequest
  try {const result=await api.getEffectiveAccess(employee);if(request===effectiveRequest&&dialog.value==='effective')effective.value=result}catch(e){if(request===effectiveRequest&&dialog.value==='effective')dialogError.value=api.accessError(e)}
}
async function submit() {
  if(saving.value) return
  if(dialog.value==='assign' && !subject.value?.department_ids?.length) return
  if(dialog.value==='employeeName' && !form.name.trim()) { dialogError.value='请输入员工姓名。'; return }
  saving.value=true;dialogError.value=''
  let succeeded=false
  try {
    const data={role_code:form.code.trim(),display_name:form.name.trim(),description:form.description.trim()}
    if(dialog.value==='newRole') {const added=await api.createRole(data);roleId.value=added.id;departmentId.value='unclassified'}
    else if(dialog.value==='copyRole' && role.value) {const added=await api.copyRole(role.value,data);roleId.value=added.id;departmentId.value='unclassified'}
    else if(dialog.value==='roleDepartment' && role.value) {await api.setRoleDepartment(role.value,form.departmentId||null);departmentId.value=form.departmentId||'unclassified'}
    else if(dialog.value==='editRole' && role.value) await api.updateRole(role.value,{display_name:data.display_name,description:data.description})
    else if(dialog.value==='archiveRole' && role.value) await api.updateRole(role.value,{archived:!role.value.archived})
    else if(dialog.value==='review' && role.value) await api.saveGrants(role.value,grants.value)
    else if(dialog.value==='employeeName' && subject.value) await api.renameEmployee(subject.value, data.display_name)
    else if(dialog.value==='assign' && subject.value) await api.assignRoles(subject.value,form.roleIds)
    else if(dialog.value==='account') {const e=employees.value.find(x=>x.id===form.employeeId);if(!e) throw new Error('employee');await api.createAccount(e,{username:form.username.trim(),password:form.password})}
    else if(dialog.value==='password' && subject.value) await api.resetPassword(subject.value,form.password)
    else if(dialog.value==='status' && subject.value) await api.setAccountStatus(subject.value,!subject.value.account_active)
    else if(dialog.value==='newTeam') {const added=await api.createTeam({code:form.code.trim(),name:form.name.trim(),manager_id:form.managerId});teamId.value=added.id}
    else if(dialog.value==='editTeam' && team.value) await api.updateTeam(team.value,{name:form.name.trim()})
    else if(dialog.value==='teamStatus' && team.value) await api.updateTeam(team.value,{is_active:!team.value.is_active})
    else if(dialog.value==='members' && team.value) await api.addTeamMembers(team.value,form.memberIds)
    succeeded=true;dialog.value='';form.password='';ElMessage.success('已保存')
    await load(true)
  } catch(e) {
    if(isAxiosError(e)&&e.response?.status===412) stale.value=true
    if(succeeded) error.value='保存已成功，但列表刷新失败。请重新加载查看最新结果。'
    else dialogError.value=api.accessError(e)
  } finally {saving.value=false}
}
const titles: Record<string,string>={employeeName:'修改员工姓名',roleDepartment:'调整角色所属部门',newRole:'新建角色',copyRole:'复制为新角色',editRole:'修改角色资料',archiveRole:'确认角色状态变更',review:'确认角色权限变更',assign:'分配员工角色',account:'关联员工并创建账号',password:'重置员工密码',status:'确认账号状态变更',effective:'员工有效权限',newTeam:'新建销售团队',editTeam:'修改团队名称',teamStatus:'确认团队状态变更',members:'添加未分组成员',special:'专项操作配置',audit:'授权变更详情'}
const readOnlyDialog = computed(()=>['effective','special','audit'].includes(dialog.value))
const auditNames: Record<string,string>={EMPLOYEE_NAME_UPDATE:'修改员工姓名',DEPARTMENT_CREATE:'新建部门',DEPARTMENT_UPDATE:'修改部门',ROLE_DEPARTMENT_UPDATE:'调整角色部门',EMPLOYEE_DEPARTMENTS_REPLACE:'调整员工部门',ROLE_CREATE:'新建角色',ROLE_UPDATE:'修改角色',ROLE_GRANTS_REPLACE:'调整角色权限',ROLE_COPY:'复制角色',EMPLOYEE_ROLES_REPLACE:'分配员工角色',ACCOUNT_CREATE:'创建账号',ACCOUNT_STATUS:'账号启停',ACCOUNT_PASSWORD_RESET:'重置密码',TEAM_CREATE:'新建团队',TEAM_UPDATE:'修改团队',TEAM_MEMBERS_ADD:'添加团队成员'}
function auditRows(data: Record<string,unknown>) {
  const labels: Record<string,string>={employee_name:'员工姓名',department_id:'所属部门',departments:'部门归属',unit_code:'部门编码',unit_name:'部门名称',sort_order:'排序',status:'状态',parent_id:'上级组织',role_code:'角色编号',code:'团队编号',display_name:'角色名称',description:'说明',archived:'已停用',name:'团队名称',username:'登录账号',is_active:'启用状态',password_reset:'密码已重置',manager_id:'客户经理',member_ids:'团队成员',role_ids:'分配角色',grants:'操作授权',copied_from_role_id:'复制来源'}
  return Object.entries(data).filter(([key])=>key!=='id').map(([key,value])=>{
    let text: string
    if(key==='grants'&&Array.isArray(value)) text=(value as Grant[]).map(g=>`${catalogByCode.value[g.permission]?.label||g.permission}：${describe([g])}`).join('\n')||'无授权'
    else if(['role_ids','member_ids'].includes(key)&&Array.isArray(value)) text=value.map(id=>(key==='role_ids'?roles.value.find(r=>r.id===id)?.display_name:employees.value.find(e=>e.id===id)?.display_name)||'历史对象').join('、')||'无'
    else if(key==='department_id'||key==='parent_id') text=departmentName(typeof value==='string'?value:null)
    else if(key==='departments'&&Array.isArray(value)) text=value.map(item=>{const a=item as Record<string,unknown>;return `${a.department_name||departmentName(String(a.department_id))}${a.is_primary?'（主部门）':''} ${a.position_title||''} ${a.effective_from||''} 至 ${a.effective_to||'长期有效'}`}).join('\n')||'无'
    else if(key==='manager_id') text=employees.value.find(e=>e.id===value)?.display_name||'历史员工'
    else if(key==='copied_from_role_id') text=roles.value.find(r=>r.id===value)?.display_name||'历史角色'
    else text=typeof value==='boolean'?(value?'是':'否'):String(value||'—')
    return {label:labels[key]||key,value:text}
  })
}
const editingDialogOpen = computed(() => (!!dialog.value && !['effective', 'audit'].includes(dialog.value)) || departmentMaintenance.value || directoryOpen.value || mappingOpen.value || deleteItems.value.length > 0 || !!departmentEmployee.value)
function canClose() {
  if (dirty.value || saving.value) { ElMessage.warning('请先保存或撤销当前修改。'); return false }
  if (editingDialogOpen.value) { ElMessage.warning('请先完成或关闭当前编辑窗口。'); return false }
  return true
}
defineExpose({ canClose })
function leaving(event: BeforeUnloadEvent) {if(dirty.value||saving.value||editingDialogOpen.value){event.preventDefault();event.returnValue=''}}
onBeforeRouteLeave(()=>props.embedded ? true : canClose())
onBeforeRouteUpdate(()=>{if(dirty.value||saving.value){ElMessage.warning('请先保存或撤销当前修改。');return false}return true})
onMounted(()=>{void load();window.addEventListener('beforeunload',leaving)})
onBeforeUnmount(()=>{loadRequest++;form.password='';window.removeEventListener('beforeunload',leaving)})
</script>

<template>
  <div class="access-page">
    <div v-if="!employeesOnly" class="access-title" :class="{ 'access-title--embedded': props.embedded }"><div v-if="!props.embedded"><div class="access-title-line"><h1>权限管理</h1><span>{{ roles.length }} 个角色</span></div></div>
      <button v-if="permitted && !error && canManageAccess && (tab === 'roles' || tab === 'teams')" class="primary" :disabled="loading||saving||dirty" @click="open(tab==='roles'?'newRole':'newTeam')">{{ tab==='roles'?'＋ 新建角色':'＋ 新建团队' }}</button>
    </div>
    <div v-if="!permitted" class="access-state"><h2>无权限管理权限</h2><p>当前账号不能查看或维护授权，请联系 admin。</p></div>
    <template v-else>
      <nav v-if="!employeesOnly" class="access-tabs" aria-label="权限管理分区"><button v-for="item in tabs" :key="item.id" :class="{active:tab===item.id}" :disabled="loading||saving" @click="changeTab(item.id)">{{ item.name }}</button></nav>
      <div v-if="loading" class="access-state" role="status">正在加载权限配置…</div>
      <div v-else-if="error" class="access-state" role="alert"><h2>暂时无法加载权限管理</h2><p>{{ error }}</p><button @click="load()">重新加载</button></div>
      <template v-else>
        <div v-if="stale" class="access-warning" role="alert">配置版本已变化，请重新加载后核对。<button @click="load()">丢弃本页修改并重新加载</button></div>
        <section v-if="tab==='roles'" class="access-role-layout access-department-layout">
          <aside class="access-box access-role-list access-department-list"><div class="access-boxhead"><b>部门</b><button :disabled="dirty||saving||!canManageOrganization" @click="departmentMaintenance=true">部门管理</button></div><div class="access-role-scroll"><button class="access-role" :class="{current:departmentId==='all'}" @click="chooseDepartment('all')">全部部门 <small>{{ roles.length }}</small></button><button v-for="item in departmentList" :key="item.id" class="access-role" :class="{current:departmentId===item.id}" @click="chooseDepartment(item.id)"><span>{{ item.unit_name }}<small v-if="item.status==='INACTIVE'">（停用）</small></span><small>{{ roles.filter(r=>r.department_id===item.id).length }}</small></button><button class="access-role" :class="{current:departmentId==='unclassified'}" @click="chooseDepartment('unclassified')">未分类 <small>{{ roles.filter(r=>!r.department_id).length }}</small></button></div><footer>部门只做分类，不自动授予权限。车间与工序范围保持独立。</footer></aside>
          <aside class="access-box access-role-list"><div class="access-boxhead"><b>岗位角色</b></div><input v-model="roleQuery" aria-label="搜索角色" placeholder="搜索角色，回车确认" @keyup.enter="roleFilter=roleQuery"><div class="access-role-scroll"><button v-for="item in visibleRoles" :key="item.id" class="access-role" :class="{current:roleId===item.id}" @click="chooseRole(item.id)"><span>{{ item.display_name }}</span><small v-if="item.archived">已停用</small></button><p v-if="!visibleRoles.length" class="muted">{{ roleFilter ? '没有匹配的角色' : '此部门暂无角色' }}</p></div><footer>新角色默认未分类且无权限，分类不会改变原授权。</footer></aside>
          <section v-if="role" class="access-box access-editor">
            <div class="access-editorhead"><div><h2>{{ role.display_name }} <span class="access-tag" :class="{neutral:role.archived}">{{ role.archived?'已停用':'已启用' }}</span></h2></div><div class="access-actions"><button :disabled="dirty||!canManageAccess" @click="open('editRole')">修改资料</button><button :disabled="dirty||!canManageOrganization" @click="open('roleDepartment')">调整部门</button><button :disabled="dirty||role.archived||!canManageAccess" @click="open('copyRole')">复制为新角色</button><button :disabled="dirty||!canManageAccess" @click="open('archiveRole')">{{ role.archived?'启用角色':'停用角色' }}</button><button :disabled="dirty||!canManageAccess" @click="requestDeletion('roles', [role])">删除角色</button></div></div>
            <div class="access-toolbar"><div class="access-module-controls"><ElSelect v-model="moduleGroup" class="access-module-filter" aria-label="业务分区"><ElOption value="all" label="全部模块" /><ElOption v-for="[value,label] in moduleOptions" :key="value" :value="value" :label="label" /></ElSelect><label class="access-bulk-check" :title="moduleGroup === 'all' ? '请先选择一个业务模块' : '选择本模块全部可用权限，包含专项操作及搜索未显示的行'"><input type="checkbox" aria-label="本模块全选" :checked="selectionState(moduleEntries).checked" :indeterminate.prop="selectionState(moduleEntries).partial" :aria-checked="selectionState(moduleEntries).partial ? 'mixed' : selectionState(moduleEntries).checked" :disabled="grantsDisabled || selectionState(moduleEntries).empty" @change="selectGrants(moduleEntries, ($event.target as HTMLInputElement).checked)">本模块全选</label></div><input v-model="moduleQuery" aria-label="搜索模块" placeholder="搜索模块，回车确认" @keyup.enter="moduleFilter=moduleQuery"></div>
            <p class="access-bulk-hint muted">全选包含专项操作；已有数据范围保留，新增权限沿用单项勾选的默认范围。</p>
            <div v-horizontal-overflow class="access-tablewrap access-standard-table scroll-actions-container"><table class="access-matrix erp-list-native-table"><colgroup><col><col v-for="column in operationColumns" :key="column.key" style="width:160px"><col style="width:88px"></colgroup><thead><tr><th>业务模块</th><th v-for="column in operationColumns" :key="column.key">{{ column.label }}</th><th class="scroll-actions-cell">专项操作</th></tr></thead><tbody><tr v-for="group in visibleGroups" :key="group.key"><td class="access-main-cell"><label class="access-row-select" title="全选本行权限，包含专项操作"><input type="checkbox" :aria-label="group.name + '本行全选'" :checked="selectionState(group.entries).checked" :indeterminate.prop="selectionState(group.entries).partial" :aria-checked="selectionState(group.entries).partial ? 'mixed' : selectionState(group.entries).checked" :disabled="grantsDisabled || selectionState(group.entries).empty" @change="selectGrants(group.entries, ($event.target as HTMLInputElement).checked)"><span><span>{{ group.name }}</span><small>{{ group.moduleName }}</small></span></label></td><td v-for="column in operationColumns" :key="column.key"><PermissionCell v-if="basic(group.entries,column.key)" :entry="basic(group.entries,column.key)!" :grants="grants" :disabled="role.archived||saving||stale||!canManageAccess" @change="updateGrant" @configure="configureScope"/><span v-else class="muted">—</span></td><td class="scroll-actions-cell"><button v-if="specialCount(group.entries)" class="text-button" @click="specialResource=group.key;open('special')">配置 {{ specialCount(group.entries) }}</button><span v-else class="muted">—</span></td></tr></tbody></table><p v-if="!visibleGroups.length" class="access-empty">{{ emptyPermissionMessage }}</p></div>
            <footer class="access-editorfoot"><span class="muted">{{ dirty?`有 ${changes.length} 项未保存变更`:'当前配置已保存' }}</span><div class="access-actions"><button :disabled="!dirty||saving" @click="resetDraft">撤销修改</button><button class="primary" :disabled="!dirty||role.archived||saving||stale||!canManageAccess" @click="open('review')">查看变更并保存</button></div></footer>
          </section><div v-else class="access-box access-empty">此部门暂无角色，可新建角色后调整所属部门。</div>
        </section>
        <template v-if="tab==='employees'">
          <section class="access-box employee-filters" data-testid="employee-filters">
            <header class="access-title"><h1>员工</h1><div class="access-actions">
              <button v-if="canManageOrganization" @click="mappingOpen=true">部门映射</button>
              <button v-if="canManageAccounts && canManageOrganization" @click="readEmployees(true)">按映射补充部门</button>
              <button v-if="canCreateAccount" @click="open('account')">创建账号</button>
              <button v-if="canManageAccounts" class="primary" @click="readEmployees()">从企业微信读取</button>
            </div></header>
            <div class="access-toolbar"><div class="access-actions">
              <input v-model="employeeQuery" aria-label="搜索员工" placeholder="姓名、员工编码、账号或部门" @keyup.enter="employeeFilter=employeeQuery">
              <ElSelect v-model="employeeStatus" aria-label="员工状态筛选"><ElOption value="all" label="全部员工状态" /><ElOption value="ACTIVE" label="在职" /><ElOption value="INACTIVE" label="停用" /><ElOption value="LEFT" label="离职" /></ElSelect>
              <ElSelect v-model="accountFilter" aria-label="账号状态"><ElOption value="all" label="全部账号状态" /><ElOption value="active" label="已启用" /><ElOption value="inactive" label="已停用" /><ElOption value="none" label="未建账号" /></ElSelect>
              <ElSelect v-model="employeeRoleFilter" aria-label="角色分配筛选"><ElOption value="all" label="全部角色分配" /><ElOption value="unassigned" label="未分配角色" /><ElOption value="assigned" label="已分配角色" /></ElSelect>
              <ElSelect v-model="wecomDepartmentFilter" filterable aria-label="企业微信部门筛选"><ElOption value="all" label="全部企业微信部门" /><ElOption value="none" label="未分配企业微信部门" /><ElOption v-for="department in wecomDepartmentOptions" :key="department.id" :value="department.id" :label="department.name" /></ElSelect>
              <ElSelect v-model="employeeDepartmentFilter" filterable aria-label="部门筛选"><ElOption value="all" label="全部部门" /><ElOption value="none" label="未分配部门" /><ElOption v-for="department in departments" :key="department.id" :value="department.id" :label="department.unit_name" /></ElSelect>
              <ElSelect v-model="employeeRoleIdFilter" filterable aria-label="角色筛选"><ElOption value="all" label="全部角色" /><ElOption v-for="role in employeeRoleOptions" :key="role.id" :value="role.id" :label="`${role.display_name}${role.archived ? '（已停用）' : ''}`" /></ElSelect>
              <button @click="employeeFilter=employeeQuery">查询</button>
            </div><button @click="load()">刷新员工</button></div>
          </section>
          <section class="access-box access-widebox access-employee-list" data-testid="employee-list">
            <div v-if="canSelectEmployees" class="access-toolbar employee-batch-toolbar"><div class="access-actions">
              <span>已选 {{ selectedEmployees.length }} 人</span>
              <button v-if="canManageAccounts" :disabled="!selectedEmployees.length || batchSaving" @click="requestDeletion('employees', employees.filter(employee => selectedEmployees.includes(employee.id)))">删除所选</button>
              <ElSelect v-if="canAdjustEmployees" v-model="batchDepartments" multiple collapse-tags collapse-tags-tooltip filterable clearable placeholder="调整部门" aria-label="批量调整部门" :disabled="!selectedEmployees.length || batchSaving"><ElOption v-for="department in departments.filter(item => item.status === 'ACTIVE')" :key="department.id" :value="department.id" :label="department.unit_name" /></ElSelect>
              <ElSelect v-if="canAdjustEmployees" v-model="batchRoles" multiple collapse-tags collapse-tags-tooltip filterable clearable placeholder="调整角色" aria-label="批量调整角色" :disabled="!selectedEmployees.length || batchSaving" no-data-text="请先选择部门；所选部门需有可用角色"><ElOption v-for="role in batchRoleOptions" :key="role.id" :value="role.id" :label="role.display_name" /></ElSelect>
              <button v-if="canAdjustEmployees" class="primary" :disabled="!selectedEmployees.length || batchSaving" title="以本次选择覆盖部门和角色，留空会清空对应设置" @click="adjustSelectedEmployees">{{ batchSaving ? '调整中…' : '调整' }}</button>
              <button v-if="selectedEmployees.length" class="text-button" :disabled="batchSaving" @click="selectedEmployees=[]">取消选择</button>
            </div></div>
            <p v-if="batchError" class="access-warning" role="alert">{{ batchError }}</p>
            <div v-horizontal-overflow class="access-tablewrap employee-table-scroll"><table>
              <colgroup><col v-if="canSelectEmployees" style="width:42px"><col style="width:140px"><col style="width:170px"><col style="width:150px"><col style="width:200px"><col style="width:120px"><col style="width:90px"><col style="width:100px"><col style="width:110px"><col style="width:190px"><col style="width:100px"><col style="width:300px"><col style="width:270px"><col style="width:90px"></colgroup>
              <thead><tr><th v-if="canSelectEmployees" class="employee-select"><input type="checkbox" aria-label="选择本页员工" :disabled="batchSaving" :checked="pageSelected" @change="selectPage(($event.target as HTMLInputElement).checked)"></th><th>姓名</th><th>已分配角色</th><th>部门</th><th>企业微信部门</th><th>销售团队</th><th>员工状态</th><th>账号状态</th><th>登录方式</th><th>最后登录时间</th><th title="自统一登录记录启用后累计，不含此前未记录的历史次数">登录次数</th><th>员工编码</th><th>登录账号</th><th class="scroll-actions-cell">操作</th></tr></thead>
              <tbody><tr v-for="employee in employeeRows" :key="employee.id" :data-employee-id="employee.id" :class="{ selected: selectedEmployees.includes(employee.id) }">
                <td v-if="canSelectEmployees" class="employee-select"><input v-model="selectedEmployees" type="checkbox" :disabled="batchSaving" :value="employee.id" :aria-label="'选择员工 '+employee.employee_code"></td>
                <td :title="employee.display_name">{{ employee.display_name }}</td>
                <td class="access-role-tags" :title="roleNames(employee).join('、')||'未分配角色'"><span v-for="name in roleNames(employee)" :key="name" class="access-tag neutral">{{ name }}</span><span v-if="!roleNames(employee).length" class="muted">未分配角色</span></td>
                <td :title="employee.department||'未分配'">{{ employee.department||'未分配' }}</td><td class="employee-wecom-department" :title="wecomDepartmentNames(employee)">{{ wecomDepartmentNames(employee) }}</td><td :title="teamName(employee.team_id)">{{ teamName(employee.team_id) }}</td>
                <td><span class="erp-list-tag" :class="`erp-list-tag--${employee.status==='ACTIVE'?'success':employee.status==='INACTIVE'?'warning':'neutral'}`">{{ { ACTIVE:'在职', INACTIVE:'停用', LEFT:'离职' }[employee.status] || employee.status }}</span></td>
                <td><span class="erp-list-tag" :class="`erp-list-tag--${!employee.username?'neutral':employee.account_active?'success':'warning'}`">{{ !employee.username?'未开通':employee.account_active?'启用':'停用' }}</span></td><td>{{ employee.username?'账号密码':'—' }}</td>
                <td class="employee-last-login" :title="lastLoginText(employee)">{{ lastLoginText(employee) }}</td><td class="employee-login-count" title="自统一登录记录启用后累计，不含此前未记录的历史次数">{{ !employee.username ? '—' : employee.login_count ?? 'UNKNOWN' }}</td>
                <td :title="employee.employee_code">{{ employee.employee_code }}</td><td class="employee-account" :title="employee.username||'未开通'">{{ employee.username||'未开通' }}</td>
                <td class="scroll-actions-cell">
                  <ElDropdown trigger="click" :persistent="false">
                    <button class="text-button" :aria-label="`${employee.employee_code} 更多操作`">更多 ▾</button>
                    <template #dropdown><ElDropdownMenu>
                      <ElDropdownItem v-if="canManageOrganization" @click="open('employeeName',employee)">修改姓名</ElDropdownItem>
                      <ElDropdownItem :disabled="!canManageOrganization || employee.status!=='ACTIVE'" @click="departmentEmployee=employee">部门管理</ElDropdownItem>
                      <ElDropdownItem @click="showEffective(employee)">有效权限</ElDropdownItem>
                      <ElDropdownItem :disabled="employee.status!=='ACTIVE'||!canManageAccess" @click="open('assign',employee)">分配角色</ElDropdownItem>
                      <template v-if="employee.username"><ElDropdownItem :disabled="employee.account_protected||!canManageAccounts" @click="open('password',employee)">重置密码</ElDropdownItem><ElDropdownItem :disabled="employee.account_protected||!canManageAccounts" @click="open('status',employee)">{{ employee.account_active?'停用':'启用' }}</ElDropdownItem></template>
                      <ElDropdownItem v-else :disabled="employee.status!=='ACTIVE'||!canCreateAccount" @click="open('account',employee)">创建账号</ElDropdownItem>
                      <ElDropdownItem v-if="canManageAccounts" divided @click="requestDeletion('employees', [employee])">删除</ElDropdownItem>
                    </ElDropdownMenu></template>
                  </ElDropdown>
                </td>
              </tr></tbody></table><p v-if="!employeeRows.length" class="access-empty">没有符合条件的员工</p>
            </div>
            <footer class="access-pagination erp-employee-pagination"><span>共 {{ filteredEmployees.length }} 人</span><ElPagination v-model:current-page="employeePage" v-model:page-size="employeePageSize" :total="filteredEmployees.length" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" /></footer>
          </section>
        </template>
        <section v-if="tab==='teams'" class="access-team-layout"><aside class="access-box access-role-list"><div class="access-boxhead"><b>销售团队</b></div><div class="access-role-scroll"><button v-for="item in teams" :key="item.id" class="access-role" :class="{current:teamId===item.id}" @click="teamId=item.id">{{ item.name }}<small v-if="!item.is_active">已停用</small></button><p v-if="!teams.length" class="muted">暂无团队</p></div><footer>成员来自业务部，一人只加入一个团队。</footer></aside><section v-if="team" class="access-box access-widebox"><div class="access-editorhead"><div><h2>{{ team.name }} <span class="access-tag" :class="{neutral:!team.is_active}">{{ team.is_active?'已启用':'已停用' }}</span></h2><p class="muted">客户经理：{{ team.manager_name }} · {{ team.member_ids.length }} 位成员</p></div><div class="access-actions"><button @click="open('editTeam')">修改名称</button><button @click="open('teamStatus')">{{ team.is_active?'停用团队':'启用团队' }}</button><button :disabled="!team.is_active" @click="open('members')">＋ 添加未分组成员</button></div></div><div class="access-toolbar muted">查看范围取自团队成员的业务归属，编辑、删除及审批需在角色中另外授权。</div><div class="access-tablewrap access-standard-table access-team-table"><table><colgroup><col style="width:25%"><col style="width:25%"><col style="width:35%"><col style="width:15%"></colgroup><thead><tr><th>成员</th><th>所属部门</th><th>角色</th><th>状态</th></tr></thead><tbody><tr v-for="member in teamMembers" :key="member.id"><td>{{ member.display_name }}</td><td>{{ member.department||'未分配部门' }}</td><td>{{ roleNames(member).join('、')||'未分配角色' }}</td><td><span class="access-tag" :class="{neutral:member.status!=='ACTIVE'}">{{ member.status==='ACTIVE'?'在职':'非在职' }}</span></td></tr></tbody></table><p v-if="!teamMembers.length" class="access-empty">暂无成员，请添加尚未分组的员工。</p></div><footer class="access-pagination">当前不提供成员换团队流程。</footer></section><div v-else class="access-box access-empty">暂无团队，请新建销售团队。</div></section>
        <section v-if="tab==='history'" class="access-box access-widebox"><div class="access-toolbar"><b>授权变更记录</b><span class="muted">记录变更前后内容与操作者</span></div><div class="access-tablewrap"><table><colgroup><col style="width:240px"><col style="width:180px"><col style="width:220px"><col><col style="width:100px"></colgroup><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>对象</th><th>详情</th></tr></thead><tbody><tr v-for="log in logs" :key="log.id"><td>{{ new Date(log.occurred_at).toLocaleString('zh-CN',{hour12:false}) }}</td><td>{{ log.actor_name_snapshot }}</td><td>{{ auditNames[log.action]||'授权变更' }}</td><td>{{ log.after_data.employee_name||log.after_data.display_name||log.after_data.name||log.after_data.username||employees.find(e=>e.id===log.object_id)?.display_name||roles.find(r=>r.id===log.object_id)?.display_name||'授权对象' }}</td><td><button class="text-button" @click="auditDetail=log;open('audit')">查看详情</button></td></tr></tbody></table><p v-if="!logs.length" class="access-empty">暂无授权变更记录</p></div><footer class="access-pagination"><span>授权日志只读；不记录密码正文。</span><div class="access-actions"><button :disabled="auditPage<=1" @click="loadHistory(auditPage-1).catch(e=>error=api.accessError(e))">上一页</button><span>{{ auditPage }} / {{ auditPages }}</span><button :disabled="auditPage>=auditPages" @click="loadHistory(auditPage+1).catch(e=>error=api.accessError(e))">下一页</button></div></footer></section>
      </template>
    </template>

    <DepartmentMaintenanceDialog v-model="departmentMaintenance" :departments="departments" @saved="load(true)" />
    <EmployeeDirectoryDialog v-if="canManageAccounts" v-model="directoryOpen" :initial-apply-departments="fillDepartmentMode" @saved="load(true)" />
    <DepartmentMappingDialog v-if="canManageOrganization" v-model="mappingOpen" @apply-departments="readEmployees(true)" />
    <DeleteManagementDialog v-if="deleteItems.length" :kind="deleteKind" :items="deleteItems" @close="deleteItems = []" @deleted="deleted" />
    <EmployeeDepartmentsDialog :employee="departmentEmployee" :departments="departments" @close="departmentEmployee=undefined" @saved="load(true)" />
    <AppWindowDialog :model-value="!!dialog" :title="dialog==='resources'?'选择操作范围':titles[dialog]||'权限管理'" :width="dialog==='effective'?900:720" :before-close="beforeClose" destroy-on-close @update:model-value="value=>{if(!value)close()}">
      <div class="access-dialog" :class="{ 'employee-role-dialog': dialog === 'assign', 'employee-name-dialog': ['employeeName','members'].includes(dialog) }">
        <template v-if="dialog==='resources'"><p><b>{{ catalogByCode[scopeCode]?.label }}</b></p><p class="muted">选择此操作可访问的{{ selectedScopeGrant?.scope==='WORKSHOP'?'车间':'外协工艺' }}，其他操作独立配置。未选择任何资源时，此授权不提供访问范围。</p><div class="access-check-grid scope-resource-options"><label v-for="option in resourceOptions" :key="option.id"><input v-model="scopeSelection" type="checkbox" :value="option.id">{{ option.name }}{{ option.active?'':'（已停用）' }}</label></div><p v-if="!resourceOptions.length" class="muted">暂无可选资源</p></template>
        <div v-if="dialogError" class="access-warning" role="alert">{{ dialogError }}<button v-if="stale" :disabled="saving" @click="close();load()">重新加载</button></div>
        <template v-if="dialog==='employeeName'"><label>姓名<input v-model="form.name" aria-label="员工姓名" maxlength="150" :disabled="saving"></label></template>
        <template v-if="dialog==='roleDepartment'"><p>角色：{{ role?.display_name }}</p><label>所属部门<ElSelect v-model="form.departmentId" filterable :empty-values="[null, undefined]" placeholder="请选择所属部门" aria-label="所属部门"><ElOption value="" label="未分类" /><ElOption v-for="item in departmentList" :key="item.id" :value="item.id" :label="`${item.unit_name}${item.status==='INACTIVE'?'（已停用）':''}`" :disabled="item.status!=='ACTIVE'" /></ElSelect></label><p class="muted">只调整分类，原有操作权限、车间/工序范围和员工兼岗保持不变。</p></template>
        <template v-if="['newRole','copyRole','editRole'].includes(dialog)"><label>角色名称<input v-model="form.name" maxlength="150"></label><label>角色说明<textarea v-model="form.description" rows="3" maxlength="5000"></textarea></label><p class="muted">{{ dialog==='copyRole'?'仅复制授权配置，不复制员工或账号。':'新角色默认未分类且无权限，创建后可调整部门并逐项配置。' }}</p></template>
        <template v-if="dialog==='archiveRole' && role"><p>确认{{ role.archived?'启用':'停用' }}“{{ role.display_name }}”？</p><p class="muted">影响 {{ role.assigned_employee_count }} 名当前分配此角色的员工。停用后此角色不再提供授权，其他角色与旧授权仍独立生效。</p></template>
        <template v-if="dialog==='review'"><p><b>{{ role?.display_name }}</b> · {{ changes.length }} 项变化 · 影响 {{ employees.filter(e=>e.role_ids.includes(roleId)).length }} 名员工</p><div v-for="change in changes" :key="change.label" class="access-diff"><b>{{ change.label }}</b><p class="muted">{{ change.before }} → {{ change.after }}</p></div></template>
        <template v-if="dialog==='special'"><div v-for="entry in specialEntries" :key="entry.code" class="access-special-row"><span>{{ entry.action_name }}</span><PermissionCell :entry="entry" :grants="grants" :disabled="role?.archived||saving||stale||!canManageAccess" @change="updateGrant" @configure="configureScope"/></div><p class="muted">专项操作的修改将在角色页统一确认保存。</p></template>
        <template v-if="dialog==='assign'"><p>员工：{{ subject?.display_name }}。所属部门：{{ subject?.department || '未分配' }}。</p><p v-if="!subject?.department_ids?.length" class="muted">请先设置员工部门，再分配对应部门的角色。</p><p v-else-if="!assignableRoles.length" class="muted">员工所属部门暂无角色，请先在角色与权限中设置角色所属部门。</p><div class="access-check-grid"><label v-for="item in assignableRoles" :key="item.id"><input v-model="form.roleIds" type="checkbox" :value="item.id" :disabled="item.archived">{{ item.display_name }}{{ item.archived?'（已停用）':'' }}</label></div><p v-if="retainedRoles.length" class="muted">已分配的其他部门角色：{{ retainedRoles.map(item => item.display_name).join('、') }}（本次保留）。</p><p class="muted">可选择所属部门的多个角色，各操作范围分别合并。</p></template>
        <template v-if="dialog==='account'"><label>员工<ElSelect v-model="form.employeeId" filterable placeholder="请选择现有员工" aria-label="创建账号员工"><ElOption v-for="e in selectableEmployees.filter(e=>!e.username)" :key="e.id" :value="e.id" :label="`${e.display_name} · ${e.employee_code}`" /></ElSelect></label><label>登录账号<input v-model="form.username" autocomplete="off" maxlength="150"></label><label>初始密码<input v-model="form.password" type="password" autocomplete="new-password" maxlength="128"></label><p class="muted">不新建员工档案。账号创建后按该员工已分配的角色使用权限。</p></template>
        <template v-if="dialog==='password'"><p>员工：{{ subject?.display_name }}（{{ subject?.username }}）</p><label>新密码<input v-model="form.password" type="password" autocomplete="new-password" maxlength="128"></label><p class="muted">保存后，原密码和原有登录会话失效，员工需重新登录。</p></template>
        <template v-if="dialog==='status'"><p>确认{{ subject?.account_active?'停用':'启用' }} {{ subject?.display_name }} 的登录账号？</p><p class="muted">停用会阻止后续访问，已分配角色和业务归属保留。</p></template>
        <template v-if="['newTeam','editTeam'].includes(dialog)"><label>团队名称<input v-model="form.name" maxlength="150"></label><label v-if="dialog==='newTeam'">客户经理<ElSelect v-model="form.managerId" filterable placeholder="请选择在职员工" aria-label="客户经理"><ElOption v-for="e in businessEmployees" :key="e.id" :value="e.id" :label="e.department ? `${e.display_name} · ${e.department}` : e.display_name" /></ElSelect></label><p class="muted">团队身份不自动授予操作权限，请另行分配角色。</p></template>
        <template v-if="dialog==='teamStatus'"><p>确认{{ team?.is_active?'停用':'启用' }}“{{ team?.name }}”？</p><p class="muted">成员归属保留。停用团队不提供团队范围，个人及其他有效授权仍保留。</p></template>
        <template v-if="dialog==='members'"><label>业务部员工<ElSelect v-model="form.memberIds" multiple filterable collapse-tags collapse-tags-tooltip placeholder="请选择业务部员工" aria-label="销售团队成员" no-data-text="暂无未分组的业务部在职员工" :disabled="saving"><ElOption v-for="employee in salesTeamCandidates" :key="employee.id" :value="employee.id" :label="employee.display_name" /></ElSelect></label></template>
        <template v-if="dialog==='effective'"><p>员工：{{ subject?.display_name }}</p><p v-if="!effective && !dialogError" role="status">正在读取有效权限…</p><template v-if="effective"><p v-if="effective.is_superuser" class="access-notice">超级管理员拥有全部业务权限。</p><p v-else-if="!Object.keys(effective.actions).length" class="access-notice">当前没有角色操作授权。</p><table><colgroup><col><col style="width:180px"><col style="width:220px"></colgroup><thead><tr><th>操作</th><th>有效范围</th><th>授权角色</th></tr></thead><tbody><tr v-for="(entry,code) in effective.actions" :key="code"><td>{{ catalogByCode[code]?.label||code }}</td><td>{{ effectiveDescription(entry) }}</td><td><p v-for="(source,index) in entry.sources" :key="index">{{ sourceDescription(code,source) }}</p></td></tr></tbody></table><h3>旧授权来源（{{ effective.legacy_sources.length }}）</h3><p v-if="!effective.legacy_sources.length" class="muted">没有旧的直接或分组授权。</p><p v-for="(source,index) in effective.legacy_sources" :key="index">{{ source.type==='DIRECT'?'直接授权':source.name||'历史角色' }} · {{ catalogByCode[source.permission]?.label||source.permission }}</p></template></template>
        <template v-if="dialog==='audit' && auditDetail"><p>{{ auditNames[auditDetail.action]||'授权变更' }} · {{ auditDetail.actor_name_snapshot }}</p><div class="access-audit-columns"><section><h3>变更前</h3><p v-for="row in auditRows(auditDetail.before_data)" :key="row.label" class="access-audit-value"><b>{{ row.label }}</b><br>{{ row.value }}</p><p v-if="!Object.keys(auditDetail.before_data).length" class="muted">无</p></section><section><h3>变更后</h3><p v-for="row in auditRows(auditDetail.after_data)" :key="row.label" class="access-audit-value"><b>{{ row.label }}</b><br>{{ row.value }}</p></section></div></template>
      </div>
      <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="close">{{ readOnlyDialog?'关闭':'取消' }}</button><button v-if="dialog==='resources'" class="primary" :disabled="saving||stale" @click="applyScope">应用到待保存配置</button><button v-else-if="!readOnlyDialog" class="primary" :disabled="saving||stale||(dialog==='assign'&&!subject?.department_ids?.length)" @click="submit">{{ saving?'保存中…':'确认保存' }}</button></div></template>
    </AppWindowDialog>
  </div>
</template>

<style lang="scss" src="@/styles/accessManagement.scss"></style>

<style scoped lang="scss">
.access-module-filter { width: 160px; flex: 0 0 160px; }
.access-standard-table {
  padding: 0;
  margin: 0 16px 14px;
  border: 1px solid var(--erp-table-frame-border);
  border-radius: var(--erp-radius-control);
  background: var(--erp-table-background);
  table { border: 0; border-radius: 0; background: var(--erp-table-background); }
  th, td {
    box-sizing: border-box;
    padding: 0 16px;
    border: 0;
    border-right: 1px solid var(--erp-table-border);
    border-bottom: 1px solid var(--erp-table-border);
    font-size: 12px;
    line-height: 18px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  th { height: 38px; background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-weight: 600; z-index: 2; }
  td { height: 40px; background: var(--erp-table-background); color: var(--erp-table-text); }
  th:last-child, td:last-child { border-right: 0; }
  tr:last-child td { border-bottom: 0; }
  tbody tr:hover td { background: var(--erp-table-hover); }
  .scroll-actions-cell { text-align: center; }
  &[data-horizontal-overflow='true'] .scroll-actions-cell { position: sticky; right: 0; z-index: 1; }
  &[data-horizontal-overflow='true'] th.scroll-actions-cell { z-index: 3; }
  .text-button, .text-button:hover, .text-button:focus { background: transparent; color: var(--erp-table-text); }
}
.access-team-table table { min-width: 580px; }
.employee-role-dialog { display: flow-root; } // 将段落外边距包含在正文高度中，供弹窗自动测量。
.employee-name-dialog { display: flow-root; }
.employee-name-dialog > label { margin-bottom: 0; }
.access-title--embedded { justify-content: flex-end; margin-bottom: 8px; }
.access-title--embedded:empty { display: none; }
.access-employee-list {
  padding: var(--erp-list-card-padding);
  .employee-table-scroll {
    padding: 0;
    border: 1px solid var(--erp-table-frame-border);
    border-radius: var(--erp-radius-control);
    background: var(--erp-table-background);
  }
  table { min-width: 2180px; border: 0; border-radius: 0; background: var(--erp-table-background); }
  th, td {
    box-sizing: border-box;
    padding: 0 16px;
    border: 0;
    border-right: 1px solid var(--erp-table-border);
    border-bottom: 1px solid var(--erp-table-border);
    font-size: 12px;
    line-height: 18px;
    white-space: nowrap;
    overflow-wrap: normal;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  th { height: 38px; background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-weight: 600; z-index: 2; }
  td { height: 40px; background: var(--erp-table-background); color: var(--erp-table-text); }
  th:last-child, td:last-child { border-right: 0; }
  .employee-select { padding: 0; text-align: center; text-overflow: clip; }
  tr:last-child td { border-bottom: 0; }
  .scroll-actions-cell { text-align: center; }
  .employee-table-scroll[data-horizontal-overflow='true'] .scroll-actions-cell { position: sticky; right: 0; z-index: 1; }
  .employee-table-scroll[data-horizontal-overflow='true'] th.scroll-actions-cell { z-index: 3; }
  .text-button, .text-button:hover, .text-button:focus, .text-button:focus-visible { color: var(--erp-table-text); background: transparent; }
  tbody tr:hover td { background: var(--erp-table-hover); }
  tbody tr.selected td, tbody tr.selected:hover td { background: var(--erp-table-selected); }
  .access-pagination { padding: 0; border-top: 0; }
}
.employee-filters { margin-bottom: 14px; flex: none; }
.employee-filters .access-title { margin: 0; padding: 14px 16px 0; gap: 12px; flex-wrap: wrap; }
.employee-filters .access-title h1 { font-size: 18px; line-height: 28px; }
.employee-filters .access-toolbar, .employee-filters .access-actions { flex-wrap: wrap; }
.employee-filters .access-toolbar .access-actions > input { width: 260px; }
.employee-filters .access-toolbar .el-select { width: 140px; flex: 0 0 140px; }
.employee-batch-toolbar { flex: none; padding: 0 0 8px; }
.employee-batch-toolbar .access-actions { flex-wrap: wrap; }
.employee-batch-toolbar .el-select { width: 170px; flex: 0 0 170px; }
.access-employee-list .employee-select { width: 42px; }
</style>
