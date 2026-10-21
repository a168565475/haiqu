<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import * as api from '@/api/access'
import type { AccessDepartment } from '@/types/access'

const props = defineProps<{ modelValue: boolean; departments: AccessDepartment[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const selectedId = ref(''), saving = ref(false), error = ref('')
const options = computed(() => props.departments.filter(d => d.unit_code !== 'HAIQU'))
const selected = computed(() => options.value.find(d => d.id === selectedId.value))
const form = reactive({ code: '', name: '', sort: 0, status: 'ACTIVE' as 'ACTIVE' | 'INACTIVE' })
function reset() {
  const item = selected.value
  Object.assign(form, { code: item?.unit_code || '', name: item?.unit_name || '', sort: item?.sort_order || 0, status: item?.status || 'ACTIVE' })
  error.value = ''
}
watch(selectedId, reset)
watch(() => props.modelValue, value => { if (value) { selectedId.value = ''; reset() } })
function close() { if (!saving.value) emit('update:modelValue', false) }
async function save() {
  if (saving.value) return
  error.value = ''
  if (!form.name.trim() || (!selected.value && !/^[A-Z0-9][A-Z0-9._-]*$/.test(form.code))) { error.value = '请填写部门名称和有效的大写编码。'; return }
  if (!Number.isInteger(form.sort) || form.sort < 0 || form.sort > 2147483647) { error.value = '排序必须是非负整数。'; return }
  const root = props.departments.find(d => d.unit_code === 'HAIQU')
  if (!selected.value && !root) { error.value = '缺少海趣根组织，请重新加载核对。'; return }
  saving.value = true
  try {
    if (selected.value) await api.updateDepartment(selected.value, { unit_name: form.name.trim(), sort_order: form.sort, status: form.status })
    else await api.createDepartment({ unit_code: form.code, unit_name: form.name.trim(), sort_order: form.sort, parent_id: root!.id })
    emit('update:modelValue', false); emit('saved'); ElMessage.success('部门已保存')
  } catch (e) { error.value = api.accessError(e) } finally { saving.value = false }
}
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="部门维护" :width="640" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog">
      <p v-if="error" class="access-warning" role="alert">{{ error }}</p>
      <label>选择部门<select v-model="selectedId" :disabled="saving"><option value="">＋ 新建部门</option><option v-for="item in options" :key="item.id" :value="item.id">{{ item.unit_name }}{{ item.status === 'INACTIVE' ? '（已停用）' : '' }}</option></select></label>
      <label>部门编码<input v-model="form.code" :disabled="saving || !!selected" maxlength="50" placeholder="如 DEPT_SUPPORT"></label>
      <label>部门名称<input v-model="form.name" :disabled="saving" maxlength="200"></label>
      <label>排序<input v-model.number="form.sort" :disabled="saving" type="number" min="0" max="2147483647"></label>
      <label v-if="selected">状态<select v-model="form.status" :disabled="saving"><option value="ACTIVE">启用</option><option value="INACTIVE">停用</option></select></label>
      <p class="muted">部门只做组织分类，不自动授予角色权限。存在角色、下级或有效员工关系时不能停用；历史记录保留。</p>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button :disabled="saving" @click="close">取消</button><button class="primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存部门' }}</button></div></template>
  </AppWindowDialog>
</template>
