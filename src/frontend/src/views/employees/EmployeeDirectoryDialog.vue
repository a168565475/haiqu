<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElTooltip } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { getEmployees } from '@/api/access'
import * as api from '@/api/employeeDirectory'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'
import type { EmployeeDirectoryMember, EmployeeDirectoryPreviewResponse, EmployeeDirectoryResult } from '@/types/employeeDirectory'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const auth = useAuthStore()
const permitted = computed(() => auth.managementCan('access_control.manage_accounts'))
const canDepartments = computed(() => permitted.value && auth.managementCan('organizations.manage_organization'))
const preview = ref<EmployeeDirectoryPreviewResponse>(), loading = ref(false), saving = ref(false), error = ref('')
const applyDepartments = ref(false), selected = ref<string[]>([]), confirmedNew = ref<string[]>([])
const query = ref(''), action = ref('all'), page = ref(1), results = ref<EmployeeDirectoryResult[]>([])
const tab = ref<'members' | 'results'>('members'), blocked = ref(true), now = ref(Date.now())
const clock = window.setInterval(() => { now.value = Date.now() }, 30000)
const pageSize = 50
const matchMember = ref<EmployeeDirectoryMember>(), candidates = ref<AccessEmployee[]>([]), candidateLoading = ref(false)
const targetId = ref(''), confirmedSame = ref(false), matchError = ref('')
let sequence = 0, candidateSequence = 0
const actionNames = { CREATE: '可新建', EXISTING: '已存在', REVIEW: '待人工核对', SKIP: '不可同步' }
const resultNames = { CREATED: '已新建', MATCHED: '已关联', EXISTING: '已存在，未重复新建' }
const departmentNames = { APPLIED: '已补充部门', PENDING: '部门待核对', PRESERVED: '保留原部门' }
const filtered = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return (preview.value?.data.members || []).filter(member => `${member.name} ${member.userid}`.toLocaleLowerCase().includes(search) && (action.value === 'all' || member.action === action.value))
})
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const filteredSelectable = computed(() => filtered.value.filter(selectable))
const pageSelectable = computed(() => rows.value.filter(selectable))
const pageSelectedCount = computed(() => pageSelectable.value.filter(member => selected.value.includes(member.userid)).length)
const allPageSelected = computed(() => pageSelectable.value.length > 0 && pageSelectedCount.value === pageSelectable.value.length)
const target = computed(() => candidates.value.find(employee => employee.id === targetId.value))
const valid = computed(() => {
  const current = preview.value, snapshot = current?.data.snapshot
  return !blocked.value && !!current?.etag && !!current.data.preview_token && permitted.value && snapshot?.can_submit === true && !!snapshot.expires_at && Date.parse(snapshot.expires_at) > now.value && current.data.apply_departments === applyDepartments.value && (!applyDepartments.value || canDepartments.value)
})
const canRefresh = computed(() => permitted.value && preview.value?.data.snapshot.can_refresh === true)
const columns = computed(() => [
  ['姓名', 100], ['企业微信部门', 200], ['UserID', 140], ['企微状态', 90], ['同步分类', 110], ['ERP姓名', 100], ['ERP编码', 110], ['同名候选姓名', 140], ['候选编码', 140], ['候选状态', 100],
  ...(applyDepartments.value ? [['部门计划', 100], ['部门原因', 200], ['目标部门', 160]] : []),
] as [string, number][])
function memberDepartments(member: EmployeeDirectoryMember) {
  return (member.department || []).map(id => {
    const name = preview.value?.data.departments.find(item => item.id === id)?.name || `部门 #${id}`
    return name + (member.main_department === id ? '（主）' : '')
  }).join('；') || '—'
}
function cells(member: EmployeeDirectoryMember) {
  return [member.name || '姓名缺失', memberDepartments(member), member.userid, member.status_label, actionNames[member.action], member.employee?.display_name || '—', member.employee?.employee_code || '—', member.candidates.map(item => item.display_name).join('；') || '—', member.candidates.map(item => item.employee_code).join('；') || '—', member.candidates.map(item => item.archived ? '已归档' : { ACTIVE: '在职', INACTIVE: '停用', LEFT: '离职' }[item.status]).join('；') || '—',
    ...(applyDepartments.value ? [member.department_plan ? { READY: '可补充', PENDING: '待核对', PRESERVED: '保留原归属' }[member.department_plan.status] : '—', member.department_plan?.reason || '—', member.department_plan?.assignments.map(item => item.department_name + (item.is_primary ? '（主）' : '')).join('；') || '—'] : [])]
}
watch([query, action], () => { page.value = 1 })
watch(targetId, () => { confirmedSame.value = false })
function closeMatch() { candidateSequence++; matchMember.value = undefined; candidates.value = []; targetId.value = ''; confirmedSame.value = false; candidateLoading.value = false; matchError.value = '' }
function clearSelection() { selected.value = []; confirmedNew.value = []; closeMatch(); page.value = 1 }
function invalidate() { preview.value = undefined; blocked.value = true; clearSelection() }
function clearSensitive() { invalidate(); results.value = [] }
function close() { if (!saving.value) { sequence++; clearSensitive(); emit('update:modelValue', false) } }
async function load(refresh = false, afterWriteMessage = '', preserveBlocked = false) {
  if (!props.modelValue || !permitted.value || (saving.value && !afterWriteMessage) || (refresh && !canRefresh.value)) return
  const request = ++sequence
  loading.value = true; blocked.value = true
  if (!afterWriteMessage) error.value = ''
  try {
    const response = await (refresh ? api.refreshEmployeeDirectory(applyDepartments.value) : api.getEmployeeDirectoryPreview(applyDepartments.value))
    if (request !== sequence || !props.modelValue || !permitted.value) return
    preview.value = response; clearSelection(); blocked.value = preserveBlocked; now.value = Date.now()
  } catch (cause) {
    if (request === sequence) {
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
  try {
    const common = { preview_token: current.data.preview_token, apply_departments: current.data.apply_departments }
    const response = kind === 'sync'
      ? await api.syncEmployeeDirectory({ ...common, user_ids: [...selected.value], confirmed_new_user_ids: confirmedNew.value.filter(id => selected.value.includes(id)) }, current.etag)
      : [await api.matchEmployeeDirectory({ ...common, user_id: member!.userid, employee_id: employee!.id, employee_etag: employee!.etag, confirmed: true }, current.etag)]
    if (request !== sequence || !props.modelValue) return
    results.value = response; tab.value = 'results'; emit('saved')
    ElMessage.success(`员工保存完成：新增 ${response.filter(row => row.result === 'CREATED').length} 人，已存在 ${response.filter(row => row.result === 'EXISTING').length} 人，已关联 ${response.filter(row => row.result === 'MATCHED').length} 人。`)
    await load(false, '本次保存已完成。')
  } catch (cause) {
    if (request === sequence) {
      blocked.value = true; clearSelection(); error.value = `${api.employeeDirectoryError(cause)} 旧预览已失效；只读恢复用于核实，请先重新核对名单、确认保存状态后再选择。`
      if (api.directoryAccessDenied(cause)) clearSensitive()
      else await load(false, error.value, true)
    }
  } finally { saving.value = false }
}
watch(() => props.modelValue, value => {
  sequence++; invalidate(); error.value = ''; results.value = []; applyDepartments.value = false; query.value = ''; action.value = 'all'; tab.value = 'members'; loading.value = false
  if (value && permitted.value) void load()
}, { immediate: true })
watch(permitted, value => { if (!value) { sequence++; clearSensitive(); emit('update:modelValue', false) } })
watch(canDepartments, value => { if (!value && applyDepartments.value) { applyDepartments.value = false; changeDepartmentMode() } })
onBeforeUnmount(() => { sequence++; candidateSequence++; window.clearInterval(clock) })
</script>

<template>
  <AppWindowDialog class="employee-directory-window" :model-value="modelValue" height="80vh" title="从企业微信读取员工" width="min(1880px, calc(100vw - 64px))" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog directory-dialog">
      <div class="directory-toolbar">
        <label v-if="canDepartments"><input v-model="applyDepartments" type="checkbox" :disabled="saving || loading" @change="changeDepartmentMode">按已确认映射补充空白部门归属</label>
        <button :disabled="loading || saving || !canRefresh" @click="load(true)">{{ preview?.data.snapshot.fetched_at ? '重新读取预览' : '首次读取员工' }}</button><button v-if="error && (!preview || blocked)" :disabled="loading || saving" @click="load()">{{ preview ? '重新核对名单' : '重试恢复' }}</button>
      </div>
      <div v-if="error" class="access-warning" role="alert">{{ error }}</div><p v-if="loading" role="status">正在读取员工，请稍候…</p>
      <div class="directory-tabs" role="tablist" aria-label="员工读取结果"><button role="tab" :aria-selected="tab === 'members'" @click="tab = 'members'">员工名单</button><button role="tab" :aria-selected="tab === 'results'" @click="tab = 'results'">本次同步结果（{{ results.length }}）</button></div>
      <template v-if="tab === 'members'">
        <div class="directory-toolbar"><input v-model="query" aria-label="搜索企业微信成员" placeholder="姓名或 UserID"><select v-model="action" aria-label="同步分类"><option value="all">全部分类</option><option v-for="(label, key) in actionNames" :key="key" :value="key">{{ label }}</option></select><span>共 {{ filtered.length }} 人，已选 {{ selected.length }} 人</span><button :disabled="saving || loading || !filteredSelectable.length" @click="selectMembers(filteredSelectable, true)">全选可保存（{{ filteredSelectable.length }}）</button><button :disabled="saving || loading || !selected.length" @click="selected = []">取消全选</button></div>
        <div class="directory-table" :class="{ 'with-departments': applyDepartments }"><table v-if="preview?.data.members.length" aria-label="企业微信员工名单"><colgroup><col style="width:50px"><col v-for="([label, width]) in columns" :key="label" :style="{ width: label === '企业微信部门' ? undefined : width + 'px' }"><col style="width:180px"><col style="width:140px"></colgroup><thead><tr><th class="fixed-left"><input type="checkbox" aria-label="选择当前页可保存员工" title="选择当前页可保存员工" :checked="allPageSelected" :indeterminate="pageSelectedCount > 0 && !allPageSelected" :aria-checked="pageSelectedCount > 0 && !allPageSelected ? 'mixed' : allPageSelected" :disabled="saving || loading || !pageSelectable.length || (!pageSelectedCount && selected.length >= 500)" @change="selectMembers(pageSelectable, ($event.target as HTMLInputElement).checked)"></th><th v-for="([label]) in columns" :key="label">{{ label }}</th><th>确认不同人员</th><th class="fixed-right">人工关联</th></tr></thead>
          <tbody><tr v-for="member in rows" :key="member.userid" :data-userid="member.userid" :class="{ selected: selected.includes(member.userid) }">
            <td class="fixed-left"><input type="checkbox" :aria-label="`选择成员 ${member.userid}`" :checked="selected.includes(member.userid)" :disabled="saving || loading || !selectable(member) || (!selected.includes(member.userid) && selected.length >= 500)" @change="selectMember(member, ($event.target as HTMLInputElement).checked)"></td>
            <td v-for="(value, index) in cells(member)" :key="index"><ElTooltip :trigger="['hover', 'focus']" :content="value" :show-after="200"><span tabindex="0" class="cell-text" :class="{ 'name-cell': index === 0 }">{{ value }}</span></ElTooltip></td>
            <td><label v-if="member.action === 'REVIEW'" class="directory-confirm"><input type="checkbox" :aria-label="`确认不同人员 ${member.userid}`" :checked="confirmedNew.includes(member.userid)" :disabled="saving || loading || !valid" @change="confirmNew(member, ($event.target as HTMLInputElement).checked)">确为不同人员，新建</label><span v-else>—</span></td>
            <td class="fixed-right"><button v-if="member.action === 'CREATE' || member.action === 'REVIEW'" class="text-button" :disabled="saving || loading || !valid" @click="openMatch(member)">关联已有员工</button><span v-else>{{ member.action === 'SKIP' ? '不可强制建档' : '保留已有身份' }}</span></td>
          </tr></tbody></table><p v-if="!preview?.data.members.length" class="directory-empty">尚未保存读取结果</p><p v-else-if="!rows.length" class="directory-empty">没有符合条件的成员。<button @click="query = ''; action = 'all'">清空筛选</button></p>
        </div>
        <div class="directory-pagination"><span>每页50人</span><div class="access-actions"><button :disabled="page <= 1 || saving" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages || saving" @click="page++">下一页</button></div></div>
        <section v-if="matchMember" class="directory-match" aria-label="人工关联员工">
          <h3>关联已有员工：{{ matchMember.name }} · {{ matchMember.userid }}</h3>
          <p>请核实是同一人后选择员工。已有绑定由服务器复核，不覆盖他人绑定。</p><p v-if="candidateLoading" role="status">正在读取可关联员工…</p><p v-if="matchError" role="alert">{{ matchError }}</p>
          <label>ERP 员工 <select v-model="targetId" aria-label="选择关联员工" :disabled="saving || candidateLoading"><option value="">请选择员工</option><option v-for="employee in candidates" :key="employee.id" :value="employee.id">{{ employee.display_name }} · {{ employee.employee_code }} · {{ employee.department || '未分配部门' }}</option></select></label>
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
:global(.employee-directory-window > .app-window-dialog__body) { display: flex; flex-direction: column; overflow: hidden; }
.directory-dialog { display: flex; flex: 1 1 auto; flex-direction: column; min-width: 0; min-height: 0; color: #111; }
.directory-dialog > p, .directory-dialog > .access-warning { flex: none; }
.directory-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; flex: none; }
.directory-toolbar { margin: 14px 0; label { display: flex; align-items: center; gap: 6px; } }
.directory-tabs { display: flex; gap: 16px; flex: none; button[aria-selected='true'] { background: #d9e8f6; } }
.directory-dialog .directory-table { overflow: auto; min-height: 0; flex: 0 1 auto; border: 1px solid rgba(255,255,255,.72); border-radius: 5px; background: #eff7fc; margin-bottom: 14px;
  table { min-width: 1700px; border: 0; border-radius: 0; }
  th, td { box-sizing: border-box; height: 34px; padding: 0 10px; white-space: nowrap; overflow-wrap: normal; color: #111; border-bottom: 1px solid #dcebf5; }
  th { background: #d8e9f7; font-size: 12px; line-height: 18px; font-weight: 500; z-index: 2; }
  td { background: #eff7fc; font-size: 12px; line-height: 18px; }
  tr:last-child td { border-bottom: 0; }
  tr:hover td { background: #eaf2f9; }
  tr.selected td { background: #d9e8f6; }
  .fixed-left, .fixed-right { position: sticky; z-index: 1; }
  .fixed-left { left: 0; } .fixed-right { right: 0; }
  th.fixed-left, th.fixed-right { z-index: 3; }
  .cell-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .name-cell { font-size: 13px; line-height: 20px; }
  .cell-text:focus-visible { outline: 2px solid #3898ec; outline-offset: -2px; }
}
.directory-dialog .with-departments table { min-width: 2160px; }
.directory-dialog .result-table table { min-width: 1080px; }
.directory-pagination { display: flex; justify-content: space-between; align-items: center; flex: none; }
.directory-confirm { display: flex; gap: 6px; align-items: center; white-space: nowrap; }
.directory-match { border: 1px solid var(--erp-input-border); border-radius: 5px; padding: 12px; margin-top: 14px; flex: none; max-height: 220px; overflow: auto; h3 { margin: 0 0 8px; } label { margin: 8px 0; } select { max-width: 100%; } }
.directory-dialog .directory-empty { padding: 12px; }
</style>
