<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import EmployeeDepartmentsDialog from '@/components/access/EmployeeDepartmentsDialog.vue'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/access'
import type { AccessDepartment, AccessEmployee } from '@/types/access'
import EmployeeDirectoryDialog from './EmployeeDirectoryDialog.vue'
import DepartmentMappingDialog from './DepartmentMappingDialog.vue'

const auth = useAuthStore(), router = useRouter()
const permitted = computed(() => auth.canReadAccessDirectory)
const canAccounts = computed(() => auth.managementCan('access_control.manage_accounts'))
const canOrganization = computed(() => auth.managementCan('organizations.manage_organization'))
const canAccess = computed(() => auth.managementCan('access_control.manage_access'))
const employees = ref<AccessEmployee[]>([]), loading = ref(false), error = ref('')
const query = ref(''), appliedQuery = ref(''), status = ref('all'), account = ref('all'), page = ref(1)
const directoryOpen = ref(false), mappingOpen = ref(false)
const departmentEmployee = ref<AccessEmployee>(), departments = ref<AccessDepartment[]>([]), departmentLoading = ref(false)
const statusNames: Record<string, string> = { ACTIVE: '在职', INACTIVE: '停用', LEFT: '离职' }
let loadSequence = 0, departmentSequence = 0
const filtered = computed(() => {
  const search = appliedQuery.value.trim().toLocaleLowerCase()
  return employees.value.filter(employee =>
    `${employee.employee_code} ${employee.display_name} ${employee.username || ''} ${employee.department}`.toLocaleLowerCase().includes(search)
    && (status.value === 'all' || employee.status === status.value)
    && (account.value === 'all' || (account.value === 'none' ? !employee.username
      : account.value === 'active' ? employee.account_active === true : employee.account_active === false)))
})
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)))
const rows = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
watch([appliedQuery, status, account], () => { page.value = 1 })
watch(pages, count => { page.value = Math.min(page.value, count) })
async function load() {
  if (!permitted.value) return
  const sequence = ++loadSequence
  loading.value = true; error.value = ''
  try {
    const result = await api.getEmployees()
    if (sequence === loadSequence && permitted.value) employees.value = result
  } catch (cause) {
    if (sequence === loadSequence) { employees.value = []; error.value = api.accessError(cause) }
  } finally { if (sequence === loadSequence) loading.value = false }
}
async function editDepartments(employee: AccessEmployee) {
  if (!canOrganization.value || departmentLoading.value || employee.status !== 'ACTIVE') return
  const sequence = ++departmentSequence
  departmentLoading.value = true; error.value = ''
  try {
    const result = await api.getDepartments()
    if (sequence !== departmentSequence || !canOrganization.value) return
    departments.value = result; departmentEmployee.value = employee
  } catch (cause) { if (sequence === departmentSequence) error.value = api.accessError(cause) }
  finally { if (sequence === departmentSequence) departmentLoading.value = false }
}
function openAccess(employee: AccessEmployee) {
  if (canAccess.value) void router.push({ name: 'access-management', query: { tab: 'employees', employee_id: employee.id } })
  else if (canAccounts.value) void router.push({ name: 'access-management', query: { tab: 'employees' } })
}
function departmentsSaved() { departmentEmployee.value = undefined; void load() }
watch(permitted, value => {
  if (value) void load()
  else { loadSequence++; departmentSequence++; employees.value = []; directoryOpen.value = false; mappingOpen.value = false; departmentEmployee.value = undefined; loading.value = false; departmentLoading.value = false; error.value = '' }
}, { immediate: true })
watch(canAccounts, value => { if (!value) directoryOpen.value = false })
watch(canOrganization, value => { if (!value) { departmentSequence++; mappingOpen.value = false; departmentEmployee.value = undefined; departmentLoading.value = false } })
onBeforeUnmount(() => { loadSequence++; departmentSequence++ })
</script>

<template>
  <div class="access-page employee-page" data-testid="employee-list">
    <header class="access-title">
      <div><h1>员工</h1><p>统一员工档案供账号、考勤与车间配置使用。</p></div>
      <div v-if="permitted" class="access-actions">
        <button v-if="canOrganization" :disabled="directoryOpen || !!departmentEmployee" @click="mappingOpen = true">部门映射</button>
        <button v-if="canAccounts" class="primary" :disabled="mappingOpen || !!departmentEmployee" @click="directoryOpen = true">从企业微信读取</button>
      </div>
    </header>
    <div v-if="!permitted" class="access-state">没有员工目录查看权限。</div>
    <section v-else class="access-box access-widebox">
      <div class="access-toolbar">
        <div class="access-actions">
          <input v-model="query" aria-label="搜索员工" placeholder="姓名、员工编码、账号或部门" @keyup.enter="appliedQuery = query">
          <button @click="appliedQuery = query">查询</button>
          <select v-model="status" aria-label="员工状态筛选"><option value="all">全部员工状态</option><option value="ACTIVE">在职</option><option value="INACTIVE">停用</option><option value="LEFT">离职</option></select>
          <select v-model="account" aria-label="账号状态"><option value="all">全部账号状态</option><option value="active">已启用</option><option value="inactive">已停用</option><option value="none">未建账号</option></select>
        </div>
        <button :disabled="loading" @click="load">刷新员工</button>
      </div>
      <p class="access-notice">部门归属不会自动分配角色；账号已启用也不代表已获得 ERP 访问权限。</p>
      <div v-if="error" class="access-warning" role="alert">{{ error }}</div>
      <div v-if="loading" class="access-empty" role="status">正在读取员工…</div>
      <div v-else class="access-tablewrap employee-tablewrap">
        <table><colgroup><col style="width:140px"><col style="width:150px"><col><col style="width:90px"><col style="width:160px"><col style="width:100px"><col v-if="canOrganization || canAccess || canAccounts" style="width:190px"></colgroup>
          <thead><tr><th>员工编码</th><th>姓名</th><th>部门</th><th>员工状态</th><th>账号</th><th>账号状态</th><th v-if="canOrganization || canAccess || canAccounts">操作</th></tr></thead>
          <tbody><tr v-for="employee in rows" :key="employee.id" :data-employee-id="employee.id"><td>{{ employee.employee_code }}</td><td>{{ employee.display_name }}</td><td>{{ employee.department || '未分配' }}</td><td>{{ statusNames[employee.status] || employee.status }}</td><td>{{ employee.username || '—' }}</td><td>{{ !employee.username ? '未建账号' : employee.account_active ? '已启用' : '已停用' }}</td>
            <td v-if="canOrganization || canAccess || canAccounts"><div class="access-actions access-row-actions"><button v-if="canOrganization" class="text-button" :disabled="departmentLoading || directoryOpen || mappingOpen || employee.status !== 'ACTIVE'" @click="editDepartments(employee)">部门管理</button><button v-if="canAccess || canAccounts" class="text-button" @click="openAccess(employee)">{{ canAccess ? '权限管理' : '账号管理' }}</button></div></td>
          </tr></tbody>
        </table>
        <p v-if="!rows.length && !error" class="access-empty">{{ employees.length ? '没有符合条件的员工。' : '暂无员工。' }}</p>
      </div>
      <footer class="access-pagination"><span>共 {{ filtered.length }} 人</span><div class="access-actions"><button :disabled="page <= 1 || loading" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages || loading" @click="page++">下一页</button></div></footer>
    </section>
    <EmployeeDirectoryDialog v-if="canAccounts" v-model="directoryOpen" @saved="load" />
    <DepartmentMappingDialog v-if="canOrganization" v-model="mappingOpen" />
    <EmployeeDepartmentsDialog v-if="canOrganization" :employee="departmentEmployee" :departments="departments" @close="departmentEmployee = undefined" @saved="departmentsSaved" />
  </div>
</template>

<style lang="scss" src="@/styles/accessManagement.scss"></style>
<style scoped lang="scss">
.employee-page .access-title { margin-bottom: 16px; flex-wrap: wrap; gap: 14px; }
.employee-page .access-toolbar input { width: 260px; max-width: 100%; }
.employee-page .access-warning { margin: 12px 16px 0; }
.employee-tablewrap { margin-top: 14px; table { min-width: 850px; } td { overflow-wrap: anywhere; } }
</style>
