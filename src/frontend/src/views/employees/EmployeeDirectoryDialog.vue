<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)))
const rows = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
const target = computed(() => candidates.value.find(employee => employee.id === targetId.value))
const valid = computed(() => !!preview.value?.etag && !!preview.value.data.preview_token && permitted.value && (!applyDepartments.value || canDepartments.value))
watch([query, action], () => { page.value = 1 })
watch(targetId, () => { confirmedSame.value = false })
function closeMatch() { candidateSequence++; matchMember.value = undefined; candidates.value = []; targetId.value = ''; confirmedSame.value = false; candidateLoading.value = false; matchError.value = '' }
function invalidate() { preview.value = undefined; selected.value = []; confirmedNew.value = []; closeMatch(); page.value = 1 }
function close() { if (!saving.value) { sequence++; invalidate(); emit('update:modelValue', false) } }
async function load(afterWrite = false) {
  if (!props.modelValue || !permitted.value || (saving.value && !afterWrite)) return
  const request = ++sequence
  invalidate(); loading.value = true; error.value = ''
  try {
    const response = await api.getEmployeeDirectoryPreview(applyDepartments.value)
    if (request !== sequence || !props.modelValue || !permitted.value) return
    if (!response.etag || !response.data.preview_token) throw new Error('missing-preview-version')
    preview.value = response
  } catch (cause) { if (request === sequence) error.value = `${afterWrite ? '本次提交已完成，重新读取预览失败：' : ''}${api.employeeDirectoryError(cause)}` }
  finally { if (request === sequence) loading.value = false }
}
function changeDepartmentMode() {
  sequence++; loading.value = false; invalidate(); error.value = '部门选项已改变，请重新读取并核对预览。'
}
function selectable(member: EmployeeDirectoryMember) {
  return valid.value && member.action !== 'SKIP' && (member.action !== 'REVIEW' || confirmedNew.value.includes(member.userid))
}
function selectMember(member: EmployeeDirectoryMember, checked: boolean) {
  if (saving.value || !selectable(member)) return
  if (checked) {
    if (selected.value.length >= 500) { error.value = '单次最多选择 500 人，请分批处理。'; return }
    selected.value = [...selected.value, member.userid]
  } else selected.value = selected.value.filter(id => id !== member.userid)
}
function confirmNew(member: EmployeeDirectoryMember, checked: boolean) {
  if (saving.value || !valid.value || member.action !== 'REVIEW') return
  confirmedNew.value = checked ? [...confirmedNew.value, member.userid] : confirmedNew.value.filter(id => id !== member.userid)
  if (!checked) selected.value = selected.value.filter(id => id !== member.userid)
}
async function openMatch(member: EmployeeDirectoryMember) {
  if (!valid.value || saving.value || !['CREATE', 'REVIEW'].includes(member.action)) return
  selected.value = selected.value.filter(id => id !== member.userid)
  confirmedNew.value = confirmedNew.value.filter(id => id !== member.userid)
  closeMatch(); matchMember.value = member; candidateLoading.value = true
  const request = ++candidateSequence
  try {
    const employees = await getEmployees()
    if (request === candidateSequence && valid.value) candidates.value = employees.filter(employee => employee.status === 'ACTIVE' && employee.account_active !== false && !employee.account_protected)
  } catch (cause) { if (request === candidateSequence) matchError.value = api.employeeDirectoryError(cause) }
  finally { if (request === candidateSequence) candidateLoading.value = false }
}
async function submit(kind: 'sync' | 'match') {
  const current = preview.value, member = matchMember.value, employee = target.value
  if (!valid.value || !current || loading.value || saving.value) return
  if (kind === 'sync' && (!selected.value.length || selected.value.length > 500 || selected.value.some(id => !current.data.members.some(row => row.userid === id && selectable(row))))) return
  if (kind === 'match' && (!member || !employee || !confirmedSame.value || candidateLoading.value)) return
  const request = sequence
  saving.value = true; error.value = ''; results.value = []
  try {
    const common = { preview_token: current.data.preview_token, apply_departments: current.data.apply_departments }
    const response = kind === 'sync'
      ? await api.syncEmployeeDirectory({ ...common, user_ids: [...selected.value], confirmed_new_user_ids: confirmedNew.value.filter(id => selected.value.includes(id)) }, current.etag)
      : [await api.matchEmployeeDirectory({ ...common, user_id: member!.userid, employee_id: employee!.id, employee_etag: employee!.etag, confirmed: true }, current.etag)]
    if (request !== sequence || !props.modelValue) return
    results.value = response; emit('saved')
    await load(true)
  } catch (cause) {
    if (request === sequence) {
      invalidate(); error.value = `${api.employeeDirectoryError(cause)} 旧预览已失效，请重新读取核实后再操作。`
      emit('saved')
    }
  } finally { saving.value = false }
}
watch(() => props.modelValue, value => {
  sequence++; invalidate(); error.value = ''; results.value = []; applyDepartments.value = false; query.value = ''; action.value = 'all'; loading.value = false
  if (value && permitted.value) void load()
}, { immediate: true })
watch(permitted, value => { if (!value) { sequence++; invalidate(); emit('update:modelValue', false) } })
watch(canDepartments, value => { if (!value && applyDepartments.value) { applyDepartments.value = false; changeDepartmentMode() } })
onBeforeUnmount(() => { sequence++; candidateSequence++ })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="从企业微信读取员工" :width="1180" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog directory-dialog">
      <p class="access-notice">已关联的员工不会重复新建，已有资料由 ERP 维护。重名须逐人核对；部门不自动授予角色。</p>
      <div class="directory-toolbar">
        <label v-if="canDepartments"><input v-model="applyDepartments" type="checkbox" :disabled="saving" @change="changeDepartmentMode">按已确认映射补充空白部门归属</label>
        <span v-else class="muted">本次仅同步员工身份，不补充部门。</span>
        <button :disabled="loading || saving" @click="load()">重新读取预览</button>
      </div>
      <div v-if="error" class="access-warning" role="alert">{{ error }}</div>
      <section v-if="results.length" class="directory-results" aria-label="本次同步结果">
        <h3>本次结果</h3>
        <p v-for="result in results" :key="result.user_id"><b>{{ result.user_id }}</b>：{{ resultNames[result.result] }}<template v-if="result.department_status">；{{ departmentNames[result.department_status] }}：{{ result.department_reason }}</template></p>
        <p class="muted">建档或关联不会分配权限；新账号仍需管理员分配访问权限。</p>
      </section>
      <p v-if="loading" role="status">正在完整读取企业微信通讯录，请稍候…</p>
      <template v-if="preview && !loading">
        <div class="directory-toolbar"><input v-model="query" aria-label="搜索企业微信成员" placeholder="姓名或 UserID"><select v-model="action" aria-label="同步分类"><option value="all">全部分类</option><option v-for="(label, key) in actionNames" :key="key" :value="key">{{ label }}</option></select><span>共 {{ filtered.length }} 人，已选 {{ selected.length }} 人（每批最多 500 人）</span></div>
        <div class="directory-table"><table><colgroup><col style="width:48px"><col style="width:145px"><col style="width:210px"><col style="width:190px"><col v-if="applyDepartments" style="width:180px"><col style="width:210px"></colgroup><thead><tr><th>选择</th><th>来源成员</th><th>同步分类 / 原因</th><th>ERP 员工</th><th v-if="applyDepartments">部门计划</th><th>人工核对</th></tr></thead>
          <tbody><tr v-for="member in rows" :key="member.userid" :data-userid="member.userid">
            <td><input type="checkbox" :aria-label="`选择成员 ${member.userid}`" :checked="selected.includes(member.userid)" :disabled="saving || !selectable(member) || (!selected.includes(member.userid) && selected.length >= 500)" @change="selectMember(member, ($event.target as HTMLInputElement).checked)"></td>
            <td><b>{{ member.name || '姓名缺失' }}</b><br>{{ member.userid }}<br><small class="muted">{{ member.status_label }}</small></td>
            <td><b>{{ actionNames[member.action] }}</b><p>{{ member.reason }}</p></td>
            <td><template v-if="member.employee">{{ member.employee.display_name }}<br><small>{{ member.employee.employee_code }}</small></template><template v-else-if="member.candidates.length"><p v-for="candidate in member.candidates" :key="candidate.id">{{ candidate.display_name }} · {{ candidate.employee_code }}{{ candidate.archived ? '（已归档）' : candidate.status !== 'ACTIVE' ? '（非在职）' : '' }}</p></template><span v-else class="muted">尚未关联</span></td>
            <td v-if="applyDepartments"><template v-if="member.department_plan"><b>{{ { READY: '可补充', PENDING: '待核对', PRESERVED: '保留原归属' }[member.department_plan.status] }}</b><p>{{ member.department_plan.reason }}</p><p v-for="assignment in member.department_plan.assignments" :key="assignment.department_id">{{ assignment.department_name }}{{ assignment.is_primary ? '（主部门）' : '' }}</p></template></td>
            <td><label v-if="member.action === 'REVIEW'" class="directory-confirm"><input type="checkbox" :aria-label="`确认不同人员 ${member.userid}`" :checked="confirmedNew.includes(member.userid)" :disabled="saving" @change="confirmNew(member, ($event.target as HTMLInputElement).checked)">确为不同人员，新建</label><button v-if="member.action === 'CREATE' || member.action === 'REVIEW'" class="text-button" :disabled="saving" @click="openMatch(member)">关联已有员工</button><span v-else class="muted">{{ member.action === 'SKIP' ? '不可强制建档' : '保留已有身份' }}</span></td>
          </tr></tbody>
        </table></div>
        <div class="directory-toolbar"><span v-if="!rows.length">没有符合条件的成员。</span><div class="access-actions"><button :disabled="page <= 1 || saving" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page >= pages || saving" @click="page++">下一页</button></div></div>
        <section v-if="matchMember" class="directory-match" aria-label="人工关联员工">
          <h3>关联已有员工：{{ matchMember.name }} · {{ matchMember.userid }}</h3>
          <p>请核实是同一人后选择员工。已有绑定由服务器复核，不覆盖他人绑定。</p>
          <p v-if="candidateLoading" role="status">正在读取可关联员工…</p>
          <p v-if="matchError" role="alert">{{ matchError }}</p>
          <label>ERP 员工 <select v-model="targetId" aria-label="选择关联员工" :disabled="saving || candidateLoading"><option value="">请选择员工</option><option v-for="employee in candidates" :key="employee.id" :value="employee.id">{{ employee.display_name }} · {{ employee.employee_code }} · {{ employee.department || '未分配部门' }}</option></select></label>
          <label class="directory-confirm"><input v-model="confirmedSame" type="checkbox" :disabled="saving || !target" aria-label="确认是同一人">我已核实企业微信成员与所选 ERP 员工为同一人</label>
          <div class="access-actions"><button :disabled="saving" @click="closeMatch">取消关联</button><button class="primary" :disabled="saving || candidateLoading || !target || !confirmedSame || !valid" @click="submit('match')">确认关联此员工</button></div>
        </section>
      </template>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="close">关闭</button><button class="primary" :disabled="saving || loading || !valid || !selected.length || !!matchMember" @click="submit('sync')">{{ saving ? '提交中…' : `同步所选 ${selected.length} 人` }}</button></div></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.directory-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 14px 0; label { display: flex; align-items: center; gap: 6px; } }
.directory-table { overflow: auto; max-height: 420px; table { min-width: 810px; } td { padding: 10px; vertical-align: top; } }
.directory-confirm { display: flex; gap: 6px; align-items: flex-start; margin: 8px 0; input { margin-top: 3px; } }
.directory-match, .directory-results { border: 1px solid var(--erp-input-border); border-radius: 5px; padding: 12px; margin-top: 12px; h3 { margin: 0 0 8px; } }
.directory-match select { max-width: 100%; }
</style>
