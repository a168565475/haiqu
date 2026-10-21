<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import * as api from '@/api/access'
import type { AccessDepartment, AccessEmployee, EmployeeDepartmentInput, EmployeeDepartments } from '@/types/access'

const props = defineProps<{ employee?: AccessEmployee; departments: AccessDepartment[] }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const loading = ref(false), saving = ref(false), error = ref('')
const history = ref<EmployeeDepartments>(), rows = ref<EmployeeDepartmentInput[]>([])
const primaryId = ref('')
let requestId = 0
const choices = computed(() => props.departments.filter(d => d.unit_code !== 'HAIQU' || rows.value.some(r => r.department_id === d.id)))
function close() { if (!saving.value) { requestId++; emit('close') } }
async function load() {
  const employee = props.employee
  if (!employee) return
  const request = ++requestId
  loading.value = true; error.value = ''; history.value = undefined; rows.value = []; primaryId.value = ''
  try {
    const result = await api.getEmployeeDepartments(employee)
    if (request !== requestId) return
    history.value = result
    const now = Date.now()
    rows.value = result.departments.filter(a => Date.parse(a.effective_from) <= now && (!a.effective_to || Date.parse(a.effective_to) > now))
      .map(a => ({ department_id: a.department_id, is_primary: a.is_primary, position_title: a.position_title }))
    primaryId.value = rows.value.find(r => r.is_primary)?.department_id || ''
  } catch (e) { if (request === requestId) error.value = api.accessError(e) } finally { if (request === requestId) loading.value = false }
}
watch(() => props.employee?.id, value => { if (value) void load(); else { requestId++; history.value = undefined; rows.value = [] } }, { immediate: true })
function toggle(id: string, checked: boolean) {
  if (checked) { rows.value.push({ department_id: id, is_primary: false, position_title: '' }); if (rows.value.length === 1) primaryId.value = id }
  else { rows.value = rows.value.filter(r => r.department_id !== id); if (primaryId.value === id) primaryId.value = '' }
}
async function save() {
  if (saving.value || loading.value || !history.value || !props.employee) return
  if (rows.value.length && !rows.value.some(r => r.department_id === primaryId.value)) { error.value = '请选择一个主部门。'; return }
  saving.value = true; error.value = ''
  try {
    await api.assignDepartments(props.employee, rows.value.map(r => ({ ...r, is_primary: r.department_id === primaryId.value })), history.value.etag)
    emit('close'); emit('saved'); ElMessage.success('员工部门已保存')
  } catch (e) { error.value = api.accessError(e) } finally { saving.value = false }
}
function time(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '长期有效' }
</script>

<template>
  <AppWindowDialog :model-value="!!employee" title="员工部门管理" :width="880" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog">
      <p>员工：{{ employee?.display_name }}</p>
      <p v-if="loading" role="status">正在读取部门与历史…</p>
      <div v-if="error" class="access-warning" role="alert">{{ error }}<button :disabled="saving || loading" @click="load">重新读取部门（丢弃修改）</button></div>
      <template v-if="history && !loading">
        <p class="muted">勾选当前部门并选择一个主部门。取消全部部门会结束当前归属；历史、角色与销售团队保留。</p>
        <div v-for="department in choices" :key="department.id" class="access-department-row">
          <label><input type="checkbox" :checked="rows.some(r => r.department_id === department.id)" :disabled="saving || (department.status !== 'ACTIVE' && !rows.some(r => r.department_id === department.id))" @change="toggle(department.id, ($event.target as HTMLInputElement).checked)">{{ department.unit_name }}{{ department.status === 'INACTIVE' ? '（已停用）' : '' }}</label>
          <template v-for="row in rows.filter(r => r.department_id === department.id)" :key="row.department_id">
            <label><input v-model="primaryId" type="radio" name="primary-department" :value="department.id" :disabled="saving">主部门</label>
            <input v-model="row.position_title" :aria-label="`${department.unit_name}岗位`" maxlength="150" :disabled="saving" placeholder="岗位名称（可留空）">
          </template>
        </div>
        <p v-if="!choices.length" class="muted">暂无部门，请先维护部门。</p>
        <h3>部门历史</h3>
        <div class="access-department-history"><table><thead><tr><th>部门 / 岗位</th><th>主部门</th><th>生效时间</th><th>结束时间</th></tr></thead><tbody><tr v-for="item in history.departments" :key="item.id"><td>{{ item.department_name }}<br>{{ item.position_title || '—' }}</td><td>{{ item.is_primary ? '是' : '否' }}</td><td>{{ time(item.effective_from) }}</td><td>{{ time(item.effective_to) }}</td></tr></tbody></table><p v-if="!history.departments.length" class="muted">暂无部门历史</p></div>
      </template>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="close">取消</button><button class="primary" :disabled="saving || loading || !history || employee?.status !== 'ACTIVE'" @click="save">{{ saving ? '保存中…' : '保存员工部门' }}</button></div></template>
  </AppWindowDialog>
</template>
