<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import * as api from '@/api/employeeDirectory'
import { useAuthStore } from '@/stores/auth'
import type { DepartmentMappingPreviewResponse, DepartmentMappingSourceDepartment } from '@/types/employeeDirectory'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const auth = useAuthStore()
const permitted = computed(() => auth.managementCan('organizations.manage_organization'))
const preview = ref<DepartmentMappingPreviewResponse>(), loading = ref(false), saving = ref(false)
const error = ref(''), notice = ref(''), query = ref('')
const source = ref<DepartmentMappingSourceDepartment>(), targetId = ref(''), confirmed = ref(false)
let sequence = 0
const rows = computed(() => {
  const search = query.value.trim().toLocaleLowerCase()
  return (preview.value?.data.departments || []).filter(department => `${department.id} ${department.name}`.toLocaleLowerCase().includes(search))
})
const options = computed(() => (preview.value?.data.organizations || []).filter(department => department.status === 'ACTIVE' && !department.archived))
const target = computed(() => options.value.find(department => department.id === targetId.value))
const canSave = computed(() => permitted.value && !!preview.value?.etag && !!source.value && confirmed.value && (targetId.value === '__clear__' || !!target.value))
function invalidate() { preview.value = undefined; source.value = undefined; targetId.value = ''; confirmed.value = false }
function close() { if (!saving.value) { sequence++; invalidate(); emit('update:modelValue', false) } }
function chooseSource(department: DepartmentMappingSourceDepartment) {
  if (saving.value) return
  source.value = department; targetId.value = ''; confirmed.value = false
}
watch(targetId, () => { confirmed.value = false })
async function load(afterWrite = false) {
  if (!props.modelValue || !permitted.value || (saving.value && !afterWrite)) return
  const request = ++sequence
  invalidate(); loading.value = true; error.value = ''
  try {
    const response = await api.getDepartmentMappings()
    if (request !== sequence || !props.modelValue || !permitted.value) return
    if (!response.etag || !response.data.preview_token) throw new Error('missing-preview-version')
    preview.value = response
  } catch (cause) { if (request === sequence) error.value = `${afterWrite ? '映射已保存，重新读取预览失败：' : ''}${api.employeeDirectoryError(cause)}` }
  finally { if (request === sequence) loading.value = false }
}
async function save() {
  const current = preview.value, department = source.value, organization = target.value
  if (!canSave.value || !current || !department || saving.value || loading.value) return
  const request = sequence, clearing = targetId.value === '__clear__'
  saving.value = true; error.value = ''; notice.value = ''
  try {
    await api.saveDepartmentMapping(department.id, {
      preview_token: current.data.preview_token,
      organization_unit_id: clearing ? null : organization!.id,
      ...(clearing ? {} : { organization_etag: organization!.etag }),
      confirmed: true,
    }, current.etag)
    if (request !== sequence || !props.modelValue) return
    notice.value = `${department.name}的映射已${clearing ? '清除' : '保存'}。员工现有部门与角色保持不变。`
    emit('saved'); await load(true)
  } catch (cause) {
    if (request === sequence) { invalidate(); error.value = `${api.employeeDirectoryError(cause)} 旧预览已失效，请重新读取核实后再操作。` }
  } finally { saving.value = false }
}
watch(() => props.modelValue, value => {
  sequence++; invalidate(); error.value = ''; notice.value = ''; query.value = ''; loading.value = false
  if (value && permitted.value) void load()
}, { immediate: true })
watch(permitted, value => { if (!value) { sequence++; invalidate(); emit('update:modelValue', false) } })
onBeforeUnmount(() => { sequence++ })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="企业微信部门映射" :width="940" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog mapping-dialog">
      <p class="access-notice">为企业微信部门明确选择 ERP 部门；同名仅作为核对提示。映射不授予角色，也不会改写员工已有部门。</p>
      <div class="mapping-toolbar"><input v-model="query" aria-label="搜索来源部门" placeholder="企业微信部门名称或编号"><button :disabled="loading || saving" @click="load()">重新读取映射</button></div>
      <p v-if="notice" class="mapping-notice" role="status">{{ notice }}</p>
      <div v-if="error" class="access-warning" role="alert">{{ error }}</div>
      <p v-if="loading" role="status">正在读取企业微信部门与 ERP 部门…</p>
      <template v-if="preview && !loading">
        <div class="mapping-table"><table><colgroup><col style="width:210px"><col><col style="width:210px"><col style="width:90px"></colgroup><thead><tr><th>企业微信部门</th><th>当前 ERP 部门</th><th>同名提示</th><th>操作</th></tr></thead><tbody>
          <tr v-for="department in rows" :key="department.id"><td>{{ department.name }}<br><small class="muted">部门编号 {{ department.id }}</small></td><td>{{ department.mapping?.organization_unit_id ? department.mapping.organization_name || '历史部门' : '未映射' }}<span v-if="department.mapping?.organization_unit_id && !department.mapping.organization_active">（不可用）</span></td><td><template v-if="department.candidates.length"><p v-for="candidate in department.candidates" :key="candidate.id">{{ candidate.unit_name }} · {{ candidate.unit_code }}</p></template><span v-else class="muted">无同名部门</span></td><td><button class="text-button" :disabled="saving" @click="chooseSource(department)">设置映射</button></td></tr>
        </tbody></table><p v-if="!rows.length" class="muted">没有符合条件的来源部门。</p></div>
        <section v-if="source" class="mapping-editor" aria-label="设置部门映射">
          <h3>{{ source.name }} · 部门编号 {{ source.id }}</h3>
          <label>目标 ERP 部门 <select v-model="targetId" aria-label="映射目标部门" :disabled="saving"><option value="">请明确选择目标或清除</option><option value="__clear__">清除当前映射</option><option v-for="department in options" :key="department.id" :value="department.id">{{ department.unit_name }} · {{ department.unit_code }}</option></select></label>
          <label class="mapping-confirm"><input v-model="confirmed" type="checkbox" :disabled="saving || !targetId" aria-label="确认部门映射">{{ targetId === '__clear__' ? '确认清除该来源部门的映射' : '已核对来源与目标部门，确认保存映射' }}</label>
        </section>
      </template>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="close">关闭</button><button class="primary" :disabled="loading || saving || !canSave" @click="save">{{ saving ? '保存中…' : '确认保存映射' }}</button></div></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.mapping-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 14px 0; }
.mapping-table { overflow: auto; max-height: 390px; table { min-width: 670px; } td { padding: 10px; } }
.mapping-editor { border: 1px solid var(--erp-input-border); border-radius: 5px; padding: 12px; margin-top: 14px; h3 { margin: 0 0 10px; } select { max-width: 100%; } }
.mapping-confirm { display: flex; gap: 6px; align-items: center; margin-top: 14px; }
.mapping-notice { color: var(--erp-tag-success-text); }
</style>
