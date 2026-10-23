<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElTooltip, ElPagination, ElSelect, ElOption } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { getEmployees } from '@/api/access'
import * as api from '@/api/employeeDirectory'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'
import type { EmployeeDirectoryMember, EmployeeDirectoryPreviewResponse, EmployeeDirectoryResult, EmployeeDirectoryProgress, EmployeeDirectoryProgressObserver } from '@/types/employeeDirectory'

const props = defineProps<{ modelValue: boolean; initialApplyDepartments?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const auth = useAuthStore()
const permitted = computed(() => auth.managementCan('access_control.manage_accounts'))
const canDepartments = computed(() => permitted.value && auth.managementCan('organizations.manage_organization'))
const preview = ref<EmployeeDirectoryPreviewResponse>(), loading = ref(false), saving = ref(false), error = ref('')
const applyDepartments = ref(false), selected = ref<string[]>([]), confirmedNew = ref<string[]>([])
const query = ref(''), action = ref('all'), page = ref(1), results = ref<EmployeeDirectoryResult[]>([])
const tab = ref<'members' | 'results'>('members'), blocked = ref(true), now = ref(Date.now())
const clock = window.setInterval(() => { now.value = Date.now() }, 30000)
const progress = ref<EmployeeDirectoryProgress>(), progressUnavailable = ref(false), progressTitle = ref('')
let progressController: AbortController | undefined
const progressPercentage = computed(() => progress.value?.status === 'SUCCESS' ? 100 : Math.min(99, Math.floor((progress.value?.completed || 0) / (progress.value?.total || 1) * 100)))
function beginProgress(title: string): EmployeeDirectoryProgressObserver {
  progressController?.abort()
  const controller = new AbortController()
  progressController = controller; progressTitle.value = title; progressUnavailable.value = false
  progress.value = { status: 'RUNNING', completed: 0, total: 1, phase: '正在等待服务器处理' }
  return { signal: controller.signal, onProgress: value => {
    if (controller.signal.aborted) return
    progressUnavailable.value = value === null
    if (value) progress.value = { ...value, status: value.status === 'SUCCESS' ? 'RUNNING' : value.status }
  } }
}
function finishProgress(success: boolean) {
  progressController?.abort()
  if (progress.value) progress.value = { ...progress.value, status: success ? 'SUCCESS' : 'FAILED', phase: success ? '已完成' : '未完成' }
}
const pageSize = ref(50)
const matchMember = ref<EmployeeDirectoryMember>(), candidates = ref<AccessEmployee[]>([]), candidateLoading = ref(false)
const targetId = ref(''), confirmedSame = ref(false), matchError = ref('')
let sequence = 0, candidateSequence = 0
const actionNames = { CREATE: '可新建', RECREATE: '可重新建档', EXISTING: '已存在', REVIEW: '待人工核对', SKIP: '不可同步' }
const resultNames = { CREATED: '已新建', MATCHED: '已关联', EXISTING: '已存在，未重复新建' }
const departmentNames = { APPLIED: '已补充部门', PENDING: '部门待核对', PRESERVED: '保留原部门' }
const filtered = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return (preview.value?.data.members || []).filter(member => `${member.name} ${member.userid}`.toLocaleLowerCase().includes(search) && (action.value === 'all' || member.action === action.value))
})
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const filteredSelectable = computed(() => filtered.value.filter(selectable))
const pageSelectable = computed(() => rows.value.filter(selectable))
const pageSelectedCount = computed(() => pageSelectable.value.filter(member => selected.value.includes(member.userid)).length)
const allPageSelected = computed(() => pageSelectable.value.length > 0 && pageSelectedCount.value === pageSelectable.value.length)
const target = computed(() => candidates.value.find(employee => employee.id === targetId.value))
const valid = computed(() => {
  const current = preview.value, snapshot = current?.data.snapshot
  return !blocked.value && !!current?.etag && !!current.data.preview_token && permitted.value && auth.user?.is_superuser === true && snapshot?.can_submit === true && !!snapshot.expires_at && Date.parse(snapshot.expires_at) > now.value && current.data.apply_departments === applyDepartments.value && (!applyDepartments.value || canDepartments.value)
})
const canRefresh = computed(() => permitted.value && preview.value?.data.snapshot.can_refresh === true)
const columns = computed(() => [
  ['姓名', 100], ['企业微信部门', 200], ['UserID', 140], ['企微状态', 90], ['同步分类', 120], ['ERP姓名', 100], ['ERP编码', 110], ['同名候选姓名', 140], ['候选编码', 140], ['候选状态', 100],
  ...(applyDepartments.value ? [['部门计划', 120], ['部门原因', 200], ['目标部门', 160]] : []),
] as [string, number][])
function memberDepartments(member: EmployeeDirectoryMember) {
  return (member.department || []).map(id => {
    const name = preview.value?.data.departments.find(item => item.id === id)?.name || `部门 #${id}`
    return name + (member.main_department === id ? '（主部门）' : '')
  }).join('；') || '—'
}
function cells(member: EmployeeDirectoryMember) {
  return [member.name || '姓名缺失', memberDepartments(member), member.userid, member.status_label, actionNames[member.action], member.employee?.display_name || '—', member.employee?.employee_code || '—', member.candidates.map(item => item.display_name).join('；') || '—', member.candidates.map(item => item.employee_code).join('；') || '—', member.candidates.map(item => item.archived ? '已归档' : { ACTIVE: '在职', INACTIVE: '停用', LEFT: '离职' }[item.status]).join('；') || '—',
    ...(applyDepartments.value ? [member.department_plan ? { READY: '可补充', PENDING: '待核对', PRESERVED: '保留原归属' }[member.department_plan.status] : '—', member.department_plan?.reason || '—', member.department_plan?.assignments.map(item => item.department_name + (item.is_primary ? '（主部门）' : '')).join('；') || '—'] : [])]
}
function cellTagTone(member: EmployeeDirectoryMember, index: number) {
  if (index === 3) return member.status === 1 ? 'success' : member.status === 2 ? 'danger' : member.status === 4 ? 'warning' : 'neutral'
  if (index === 4) return { CREATE: 'info', RECREATE: 'info', EXISTING: 'success', REVIEW: 'warning', SKIP: 'neutral' }[member.action]
  if (index === 10 && member.department_plan) return { READY: 'success', PENDING: 'warning', PRESERVED: 'neutral' }[member.department_plan.status]
  return undefined
}
watch([query, action, pageSize], () => { page.value = 1 })
watch(targetId, () => { confirmedSame.value = false })
function closeMatch() { candidateSequence++; matchMember.value = undefined; candidates.value = []; targetId.value = ''; confirmedSame.value = false; candidateLoading.value = false; matchError.value = '' }
function clearSelection() { selected.value = []; confirmedNew.value = []; closeMatch(); page.value = 1 }
function invalidate() { preview.value = undefined; blocked.value = true; clearSelection() }
function clearSensitive() { progressController?.abort(); progress.value = undefined; invalidate(); results.value = [] }
function close() { if (!saving.value) { sequence++; clearSensitive(); emit('update:modelValue', false) } }
async function load(refresh = false, afterWriteMessage = '', preserveBlocked = false) {
  if (!props.modelValue || !permitted.value || (saving.value && !afterWriteMessage) || (refresh && !canRefresh.value)) return
  const request = ++sequence
  loading.value = true; blocked.value = true
  const observer = beginProgress(refresh ? '读取企业微信员工' : '读取员工预览')
  if (!afterWriteMessage) error.value = ''
  try {
    const response = await (refresh ? api.refreshEmployeeDirectory(applyDepartments.value, observer) : api.getEmployeeDirectoryPreview(applyDepartments.value, observer))
    if (request !== sequence || !props.modelValue || !permitted.value) return
    finishProgress(true)
    preview.value = response; clearSelection(); blocked.value = preserveBlocked; now.value = Date.now()
  } catch (cause) {
    if (request === sequence) {
      finishProgress(false)
      if (api.directoryAccessDenied(cause)) clearSensitive()
      error.value = `${afterWriteMessage ? afterWriteMessage + ' 名单恢复失败：' : refresh ? '重新读取失败，保留上次显示：' : '恢复已保存结果失败：'}${api.employeeDirectoryError(cause)}`
    }
  } finally { if (request === sequence) loading.value = false }
}
function changeDepartmentMode() {
  clearSelection(); blocked.value = true
  void load() // 只重算ERP计划，不重新调用企微。
}
function selectable(member: EmployeeDirectoryMember) {
  return valid.value && member.action !== 'SKIP' && (member.action !== 'REVIEW' || confirmedNew.value.includes(member.userid))
}
function selectMember(member: EmployeeDirectoryMember, checked: boolean) {
  if (saving.value || loading.value || !selectable(member)) return
  if (checked) {
    if (selected.value.length >= 500) { error.value = '单次最多选择 500 人，请分批处理。'; return }
    selected.value = [...selected.value, member.userid]
  } else selected.value = selected.value.filter(id => id !== member.userid)
}
function selectMembers(members: EmployeeDirectoryMember[], checked: boolean) {
  if (saving.value || loading.value || !valid.value) return
  const ids = members.map(member => member.userid)
  if (!checked) { selected.value = selected.value.filter(id => !ids.includes(id)); return }
  const additions = ids.filter(id => !selected.value.includes(id))
  if (selected.value.length + additions.length > 500) { error.value = '本次选择超过 500 人，原选择保持不变；请筛选或分批处理。'; return }
  selected.value = [...selected.value, ...additions]
}
function confirmNew(member: EmployeeDirectoryMember, checked: boolean) {
  if (saving.value || loading.value || !valid.value || member.action !== 'REVIEW') return
  confirmedNew.value = checked ? [...confirmedNew.value, member.userid] : confirmedNew.value.filter(id => id !== member.userid)
  if (!checked) selected.value = selected.value.filter(id => id !== member.userid)
}
async function openMatch(member: EmployeeDirectoryMember) {
  if (!valid.value || loading.value || saving.value || !['CREATE', 'REVIEW'].includes(member.action)) return
  selected.value = selected.value.filter(id => id !== member.userid)
  confirmedNew.value = confirmedNew.value.filter(id => id !== member.userid)
  closeMatch(); matchMember.value = member; candidateLoading.value = true
  const request = ++candidateSequence
  try {
    const employees = await getEmployees()
    if (request === candidateSequence && valid.value) candidates.value = employees.filter(employee => employee.status === 'ACTIVE' && employee.account_active !== false && !employee.account_protected)
  } catch (cause) { if (request === candidateSequence) { if (api.directoryAccessDenied(cause)) clearSensitive(); matchError.value = api.employeeDirectoryError(cause) } }
  finally { if (request === candidateSequence) candidateLoading.value = false }
}
async function submit(kind: 'sync' | 'match') {
  const current = preview.value, member = matchMember.value, employee = target.value
  if (!valid.value || !current || loading.value || saving.value) return
  if (kind === 'sync' && (!selected.value.length || selected.value.length > 500 || selected.value.some(id => !current.data.members.some(row => row.userid === id && selectable(row))))) return
  if (kind === 'match' && (!member || !employee || !confirmedSame.value || candidateLoading.value)) return
  const request = sequence
  saving.value = true; error.value = ''
  const observer = beginProgress('保存员工')
  try {
    const common = { preview_token: current.data.preview_token, apply_departments: current.data.apply_departments }
    const response = kind === 'sync'
      ? await api.syncEmployeeDirectory({ ...common, user_ids: [...selected.value], confirmed_new_user_ids: confirmedNew.value.filter(id => selected.value.includes(id)) }, current.etag, observer)
      : [await api.matchEmployeeDirectory({ ...common, user_id: member!.userid, employee_id: employee!.id, employee_etag: employee!.etag, confirmed: true }, current.etag, observer)]
    if (request !== sequence || !props.modelValue) return
    finishProgress(true)
    results.value = response; tab.value = 'results'; emit('saved')
    ElMessage.success(`员工保存完成：新增 ${response.filter(row => row.result === 'CREATED').length} 人，已存在 ${response.filter(row => row.result === 'EXISTING').length} 人，已关联 ${response.filter(row => row.result === 'MATCHED').length} 人。`)
    await load(false, '本次保存已完成。')
  } catch (cause) {
    if (request === sequence) {
      finishProgress(false)
      blocked.value = true; clearSelection(); error.value = `${api.employeeDirectoryError(cause)} 旧预览已失效；只读恢复用于核实，请先重新核对名单、确认保存状态后再选择。`
      if (api.directoryAccessDenied(cause)) clearSensitive()
      else await load(false, error.value, true)
    }
  } finally { saving.value = false }
}
watch(() => props.modelValue, value => {
  progressController?.abort(); progress.value = undefined
  sequence++; invalidate(); error.value = ''; results.value = []; applyDepartments.value = !!props.initialApplyDepartments && canDepartments.value; query.value = ''; action.value = 'all'; tab.value = 'members'; loading.value = false
  if (value && permitted.value) void load()
}, { immediate: true })
watch(permitted, value => { if (!value) { sequence++; clearSensitive(); emit('update:modelValue', false) } })
watch(canDepartments, value => { if (!value && applyDepartments.value) { applyDepartments.value = false; changeDepartmentMode() } })
onBeforeUnmount(() => { sequence++; candidateSequence++; progressController?.abort(); window.clearInterval(clock) })
</script>

<template>
  <AppWindowDialog class="employee-directory-window" :model-value="modelValue" height="80vh" title="从企业微信读取员工" width="min(1880px, calc(100vw - 64px))" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog directory-dialog">
      <div v-if="error" class="access-warning" role="alert">{{ error }}</div>
      <div v-if="progress" class="directory-progress" role="status"><span>{{ progressTitle }} · {{ progressUnavailable && progress.status === 'RUNNING' ? '暂时无法获取进度' : progress.phase }}</span><progress :aria-label="saving ? '员工保存进度' : '员工读取进度'" :value="progressPercentage" max="100" /><span>{{ progressPercentage }}%</span></div>
      <div class="directory-header">
        <div class="directory-tabs" role="tablist" aria-label="员工读取结果"><button role="tab" :aria-selected="tab === 'members'" @click="tab = 'members'">员工名单</button><button role="tab" :aria-selected="tab === 'results'" @click="tab = 'results'">本次同步结果（{{ results.length }}）</button></div>
        <div class="directory-toolbar directory-options">
          <label v-if="canDepartments"><input v-model="applyDepartments" type="checkbox" :disabled="saving || loading" @change="changeDepartmentMode">按已确认映射补充空白部门归属</label>
          <button :disabled="loading || saving || !canRefresh" @click="load(true)">{{ preview?.data.snapshot.fetched_at ? '重新读取预览' : '首次读取员工' }}</button><button v-if="error && (!preview || blocked)" :disabled="loading || saving" @click="load()">{{ preview ? '重新核对名单' : '重试恢复' }}</button>
        </div>
      </div>
      <template v-if="tab === 'members'">
        <div class="directory-toolbar"><input v-model="query" aria-label="搜索企业微信成员" placeholder="姓名或 UserID"><ElSelect v-model="action" class="directory-action-filter" aria-label="同步分类"><ElOption value="all" label="全部分类" /><ElOption v-for="(label, key) in actionNames" :key="key" :value="key" :label="label" /></ElSelect><span>共 {{ filtered.length }} 人，已选 {{ selected.length }} 人</span><button :disabled="saving || loading || !filteredSelectable.length" @click="selectMembers(filteredSelectable, true)">全选可保存（{{ filteredSelectable.length }}）</button><button :disabled="saving || loading || !selected.length" @click="selected = []">取消全选</button></div>
        <div class="directory-table" :class="{ 'with-departments': applyDepartments }"><table v-if="preview?.data.members.length" aria-label="企业微信员工名单"><colgroup><col style="width:50px"><col v-for="([label, width]) in columns" :key="label" :style="{ width: label === '企业微信部门' ? undefined : width + 'px' }"><col style="width:180px"><col style="width:140px"></colgroup><thead><tr><th class="fixed-left"><input type="checkbox" aria-label="选择当前页可保存员工" title="选择当前页可保存员工" :checked="allPageSelected" :indeterminate="pageSelectedCount > 0 && !allPageSelected" :aria-checked="pageSelectedCount > 0 && !allPageSelected ? 'mixed' : allPageSelected" :disabled="saving || loading || !pageSelectable.length || (!pageSelectedCount && selected.length >= 500)" @change="selectMembers(pageSelectable, ($event.target as HTMLInputElement).checked)"></th><th v-for="([label]) in columns" :key="label">{{ label }}</th><th>确认不同人员</th><th class="fixed-right">人工关联</th></tr></thead>
          <tbody><tr v-for="member in rows" :key="member.userid" :data-userid="member.userid" :class="{ selected: selected.includes(member.userid) }">
            <td class="fixed-left"><input type="checkbox" :aria-label="`选择成员 ${member.userid}`" :checked="selected.includes(member.userid)" :disabled="saving || loading || !selectable(member) || (!selected.includes(member.userid) && selected.length >= 500)" @change="selectMember(member, ($event.target as HTMLInputElement).checked)"></td>
            <td v-for="(value, index) in cells(member)" :key="index"><ElTooltip :trigger="['hover', 'focus']" :content="value" :show-after="200"><span tabindex="0" class="cell-text" :class="{ 'name-cell': index === 0 }"><span v-if="cellTagTone(member, index)" class="erp-list-tag" :class="`erp-list-tag--${cellTagTone(member, index)}`">{{ value }}</span><template v-else-if="index === 9 && member.candidates.length"><span v-for="candidate in member.candidates" :key="candidate.id" class="erp-list-tag candidate-status" :class="`erp-list-tag--${candidate.archived || candidate.status === 'LEFT' ? 'neutral' : candidate.status === 'ACTIVE' ? 'success' : 'warning'}`">{{ candidate.archived ? '已归档' : { ACTIVE: '在职', INACTIVE: '停用', LEFT: '离职' }[candidate.status] }}</span></template><template v-else>{{ value }}</template></span></ElTooltip></td>
            <td><label v-if="member.action === 'REVIEW'" class="directory-confirm"><input type="checkbox" :aria-label="`确认不同人员 ${member.userid}`" :checked="confirmedNew.includes(member.userid)" :disabled="saving || loading || !valid" @change="confirmNew(member, ($event.target as HTMLInputElement).checked)">确为不同人员，新建</label><span v-else>—</span></td>
            <td class="fixed-right"><button v-if="member.action === 'CREATE' || member.action === 'REVIEW'" class="text-button" :disabled="saving || loading || !valid" @click="openMatch(member)">关联已有员工</button><span v-else>{{ member.action === 'RECREATE' ? '重新建档并绑定' : member.action === 'SKIP' ? '不可强制建档' : '保留已有身份' }}</span></td>
          </tr></tbody></table><p v-if="!preview?.data.members.length" class="directory-empty">尚未保存读取结果</p><p v-else-if="!rows.length" class="directory-empty">没有符合条件的成员。<button @click="query = ''; action = 'all'">清空筛选</button></p>
        </div>
        <div class="directory-pagination erp-employee-pagination"><span>共 {{ filtered.length }} 人</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="filtered.length" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" :disabled="loading || saving" /></div>
        <section v-if="matchMember" class="directory-match" aria-label="人工关联员工">
          <h3>关联已有员工：{{ matchMember.name }} · {{ matchMember.userid }}</h3>
          <p>请核实是同一人后选择员工。已有绑定由服务器复核，不覆盖他人绑定。</p><p v-if="candidateLoading" role="status">正在读取可关联员工…</p><p v-if="matchError" role="alert">{{ matchError }}</p>
          <label>ERP 员工 <ElSelect v-model="targetId" filterable clearable placeholder="请选择员工" aria-label="选择关联员工" :disabled="saving || candidateLoading"><ElOption v-for="employee in candidates" :key="employee.id" :value="employee.id" :label="`${employee.display_name} · ${employee.employee_code} · ${employee.department || '未分配部门'}`" /></ElSelect></label>
          <label class="directory-confirm"><input v-model="confirmedSame" type="checkbox" :disabled="saving || !target" aria-label="确认是同一人">我已核实企业微信成员与所选 ERP 员工为同一人</label>
          <div class="access-actions"><button :disabled="saving" @click="closeMatch">取消关联</button><button class="primary" :disabled="saving || candidateLoading || !target || !confirmedSame || !valid" @click="submit('match')">确认关联此员工</button></div>
        </section>
      </template>
      <div v-else class="directory-table result-table" aria-label="本次同步结果"><table v-if="results.length"><colgroup><col style="width:160px"><col style="width:300px"><col style="width:180px"><col style="width:140px"><col></colgroup><thead><tr><th>UserID</th><th>ERP员工ID</th><th>同步结果</th><th>部门结果</th><th>部门原因</th></tr></thead><tbody><tr v-for="result in results" :key="result.user_id"><td v-for="(value, index) in [result.user_id, result.employee_id, resultNames[result.result], result.department_status ? departmentNames[result.department_status] : '—', result.department_reason || '—']" :key="index"><ElTooltip :trigger="['hover', 'focus']" :content="value"><span tabindex="0" class="cell-text">{{ value }}</span></ElTooltip></td></tr></tbody></table><p v-else class="directory-empty">当前窗口暂无明确完成的同步结果。</p></div>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="close">关闭</button><button class="primary" :disabled="saving || loading || !valid || !selected.length || !!matchMember" @click="submit('sync')">{{ saving ? '保存中…' : `保存所选员工（${selected.length}）` }}</button></div></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
:global(.employee-directory-window > .app-window-dialog__body) { display: flex; flex-direction: column; overflow: hidden; padding-top: 12px; }
.directory-dialog { display: flex; flex: 1 1 auto; flex-direction: column; min-width: 0; min-height: 0; color: #111; }
.directory-dialog > p, .directory-dialog > .access-warning { flex: none; }
.directory-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; flex: none; }
.directory-toolbar { margin: 14px 0; label { display: flex; align-items: center; gap: 6px; } }
.directory-action-filter { width: 140px; }
.directory-toolbar:first-child { margin-top: 0; }
.directory-header { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; flex: none; }
.directory-header .directory-options { margin: 0; }
.directory-progress { display: flex; flex: none; align-items: center; gap: 12px; margin-bottom: 14px; }
.directory-progress progress { flex: 1; height: 10px; accent-color: var(--erp-color-brand); }
.directory-tabs { display: flex; gap: 16px; flex: none; button[aria-selected='true'] { background: var(--erp-table-selected); } }
.directory-dialog .directory-table { overflow: auto; min-height: 0; flex: 0 1 auto; border: 1px solid var(--erp-table-frame-border); border-radius: var(--erp-radius-control); background: var(--erp-table-background); margin-bottom: 14px;
  table { min-width: 1700px; border: 0; border-radius: 0; }
  th, td { box-sizing: border-box; padding: 0 16px; white-space: nowrap; overflow-wrap: normal; color: var(--erp-table-text); border-right: 1px solid var(--erp-table-border); border-bottom: 1px solid var(--erp-table-border); }
  th { height: 38px; background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-size: 12px; line-height: 18px; font-weight: 600; z-index: 2; }
  td { height: 40px; background: var(--erp-table-background); font-size: 12px; line-height: 18px; }
  th:last-child, td:last-child { border-right: 0; }
  tr:last-child td { border-bottom: 0; }
  tr:hover td { background: var(--erp-table-hover); }
  tr.selected td { background: var(--erp-table-selected); }
  .text-button, .text-button:hover, .text-button:focus { background: transparent; color: var(--erp-table-text); }
  .fixed-left, .fixed-right { position: sticky; z-index: 1; }
  .fixed-left { left: 0; padding: 0; text-align: center; } .fixed-right { right: 0; }
  th.fixed-left, th.fixed-right { z-index: 3; }
  .cell-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .name-cell { font-size: 12px; line-height: 18px; }
  .candidate-status + .candidate-status { margin-left: 4px; }
  .cell-text:focus-visible { outline: 2px solid #3898ec; outline-offset: -2px; }
}
.directory-dialog .with-departments table { min-width: 2160px; }
.directory-dialog .result-table table { min-width: 1080px; }
.directory-pagination { display: flex; justify-content: space-between; align-items: center; flex: none; }
.directory-confirm { display: flex; gap: 6px; align-items: center; white-space: nowrap; }
.directory-match { border: 1px solid var(--erp-input-border); border-radius: 5px; padding: 12px; margin-top: 14px; flex: none; max-height: 220px; overflow: auto; h3 { margin: 0 0 8px; } label { margin: 8px 0; } }
.directory-dialog .directory-empty { padding: 12px; }
</style>
