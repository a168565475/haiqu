<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElOption, ElSelect, ElTooltip } from 'element-plus'
import type { MessageHandler } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import * as api from '@/api/employeeDirectory'
import { useAuthStore } from '@/stores/auth'
import type { DepartmentMappingPreviewResponse, DepartmentMappingSourceDepartment } from '@/types/employeeDirectory'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: []; 'apply-departments': [] }>()
const auth = useAuthStore()
const permitted = computed(() => auth.managementCan('organizations.manage_organization'))
const preview = ref<DepartmentMappingPreviewResponse>(), loading = ref(false), saving = ref(false)
const error = ref(''), notice = ref(''), query = ref(''), savingId = ref<number>(), blocked = ref(true)
const now = ref(Date.now())
const clock = window.setInterval(() => { now.value = Date.now() }, 30000)
let sequence = 0
let loadingMessage: MessageHandler | undefined
function closeLoadingMessage() { loadingMessage?.close(); loadingMessage = undefined }
watch(() => props.modelValue && permitted.value && loading.value, active => {
  if (active) {
    if (!loadingMessage) loadingMessage = ElMessage.info({ message: '正在读取部门，请稍候…', duration: 0 })
  } else closeLoadingMessage()
}, { flush: 'post' })
const rows = computed(() => (preview.value?.data.departments || []).filter(row => `${row.id} ${row.name}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const options = computed(() => (preview.value?.data.organizations || []).filter(row => row.status === 'ACTIVE' && !row.archived))
const valid = computed(() => {
  const current = preview.value, snapshot = current?.data.snapshot
  return permitted.value && !blocked.value && !!current?.etag && !!current.data.preview_token && current.data.can_save_mapping === true && !!snapshot?.expires_at && Date.parse(snapshot.expires_at) > now.value
})
const canRefresh = computed(() => permitted.value && preview.value?.data.snapshot.status !== 'CONFIG_UNAVAILABLE')
const columns = [['部门ID', 90], ['企业微信部门', 200], ['上级ID', 100], ['同名ERP部门', 180], ['同名部门编码', 160], ['已保存ERP编码', 130], ['映射状态', 120]] as const
function cells(row: DepartmentMappingSourceDepartment) {
  const mapping = row.mapping
  return [String(row.id), row.name, String(row.parentid), row.candidates.map(item => item.unit_name).join('；') || '—', row.candidates.map(item => item.unit_code).join('；') || '—', preview.value?.data.organizations.find(item => item.id === mapping?.organization_unit_id)?.unit_code || '—', savingId.value === row.id ? '保存中' : !mapping?.organization_unit_id ? '未绑定' : mapping.organization_active ? '已绑定' : '目标不可用']
}
function clearSensitive() { preview.value = undefined; blocked.value = true }
function close() { if (!saving.value) { sequence++; loading.value = false; clearSensitive(); emit('update:modelValue', false) } }
async function load(refresh = false, afterWrite = false, savedMessage = ''): Promise<boolean> {
  if (!props.modelValue || !permitted.value || (saving.value && !afterWrite) || (refresh && !canRefresh.value)) return false
  const request = ++sequence
  loading.value = true; blocked.value = true
  if (!afterWrite) { error.value = ''; notice.value = '' }
  try {
    const response = await (refresh ? api.refreshDepartmentMappings() : api.getDepartmentMappings())
    if (request !== sequence || !props.modelValue || !permitted.value) return false
    preview.value = response; blocked.value = false; now.value = Date.now()
    return true
  } catch (cause) {
    if (request === sequence) {
      if (api.directoryAccessDenied(cause)) clearSensitive()
      error.value = `${afterWrite ? (savedMessage || error.value) + ' 只读恢复失败：' : refresh ? '重新读取失败，保留上次显示：' : '恢复已保存结果失败：'}${api.employeeDirectoryError(cause)}`
    }
    return false
  } finally { if (request === sequence) loading.value = false }
}
async function save(row: DepartmentMappingSourceDepartment, value: string) {
  const current = preview.value, clearing = value === '__clear__', organization = options.value.find(item => item.id === value)
  if (!valid.value || !current || loading.value || saving.value || (!clearing && !organization) || (clearing ? !row.mapping?.organization_unit_id : row.mapping?.organization_unit_id === value)) return
  const request = sequence
  saving.value = true; savingId.value = row.id; error.value = ''; notice.value = ''
  try {
    const mapping = await api.saveDepartmentMapping(row.id, {
      preview_token: current.data.preview_token, organization_unit_id: clearing ? null : organization!.id,
      ...(clearing ? {} : { organization_etag: organization!.etag }), confirmed: true,
    }, current.etag)
    if (request !== sequence || !props.modelValue || !permitted.value) return
    row.mapping = mapping; ElMessage.success(`${row.name}的映射已${clearing ? '清除' : '保存'}。`); emit('saved')
    await load(false, true, '映射已保存。')
  } catch (cause) {
    if (request === sequence) {
      blocked.value = true; error.value = `${api.employeeDirectoryError(cause)} 已停止使用旧预览，正在只读核实当前绑定。`
      if (api.directoryAccessDenied(cause)) clearSensitive()
      else {
        const corp = current.data.corp_id, restored = await load(false, true)
        const row = preview.value?.data.departments.find(item => item.id === savingId.value)
        if (restored && preview.value?.data.corp_id === corp && row) notice.value = `已读回当前绑定：${row.mapping?.organization_unit_id ? row.mapping.organization_name : '未绑定'}。请核对后再操作。`
        else blocked.value = true
      }
    }
  } finally { saving.value = false; savingId.value = undefined }
}
watch(() => props.modelValue, value => {
  sequence++; clearSensitive(); error.value = ''; notice.value = ''; query.value = ''; loading.value = false
  if (value && permitted.value) void load()
}, { immediate: true })
watch(permitted, value => { if (!value) { sequence++; clearSensitive(); emit('update:modelValue', false) } })
onBeforeUnmount(() => { sequence++; closeLoadingMessage(); window.clearInterval(clock) })
</script>

<template>
  <AppWindowDialog class="department-mapping-window" :model-value="modelValue" height="80vh" title="企业微信部门映射" width="min(1440px, calc(100vw - 64px))" :before-close="done => { if (!saving) done() }" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="access-dialog mapping-dialog">
      <div class="mapping-toolbar"><input v-model="query" aria-label="搜索来源部门" placeholder="企业微信部门名称或编号"><button :disabled="loading || saving || !canRefresh" @click="load(true)">{{ preview?.data.snapshot.fetched_at ? '重新读取映射' : '首次读取部门' }}</button><button v-if="error && !preview" :disabled="loading || saving" @click="load()">重试恢复</button></div>
      <p v-if="notice" class="mapping-notice" role="status">{{ notice }}</p><div v-if="error" class="access-warning" role="alert">{{ error }}</div>
      <div v-if="preview" class="mapping-table">
        <table v-if="preview.data.departments.length" aria-label="企业微信部门映射"><colgroup><col v-for="([label, width]) in columns" :key="label" :style="{ width: label === '企业微信部门' ? undefined : width + 'px' }"><col style="width:250px"></colgroup><thead><tr><th v-for="([label]) in columns" :key="label">{{ label }}</th><th class="fixed-right">绑定本地部门</th></tr></thead><tbody>
          <tr v-for="row in rows" :key="`${preview.data.corp_id}:${row.id}`" :data-department="row.id">
            <td v-for="(value, index) in cells(row)" :key="index"><ElTooltip :trigger="['hover', 'focus']" :content="value" :show-after="200"><span tabindex="0" class="cell-text" :class="{ 'name-cell': index === 1 }">{{ value }}</span></ElTooltip></td>
            <td class="fixed-right"><ElSelect :model-value="row.mapping?.organization_unit_id || ''" :aria-label="`映射目标部门 ${row.id}`" filterable placeholder="选择本地部门" :disabled="saving || loading || !valid || !options.length" @change="value => save(row, String(value))"><ElOption v-if="row.mapping?.organization_unit_id" label="清除当前绑定" value="__clear__" /><ElOption v-if="row.mapping?.organization_unit_id && !options.some(item => item.id === row.mapping?.organization_unit_id)" :value="row.mapping.organization_unit_id" :label="`${row.mapping.organization_name || '历史部门'}（目标不可用）`" disabled /><ElOption v-for="item in options" :key="item.id" :value="item.id" :label="`${item.unit_name} · ${item.unit_code}`" /></ElSelect></td>
          </tr>
        </tbody></table>
        <p v-if="!preview.data.departments.length" class="mapping-empty">尚未保存读取结果</p><p v-else-if="!rows.length" class="mapping-empty">没有符合条件的来源部门。<button @click="query = ''">清空搜索</button></p>
      </div>
      <template v-if="preview && !preview.data.departments.length"><h3>本地 ERP 部门</h3><div class="mapping-table local-table"><table aria-label="本地ERP部门"><thead><tr><th>名称</th><th>编码</th><th>状态</th></tr></thead><tbody><tr v-for="item in preview.data.organizations" :key="item.id"><td><ElTooltip :trigger="['hover', 'focus']" :content="item.unit_name"><span tabindex="0" class="cell-text">{{ item.unit_name }}</span></ElTooltip></td><td><ElTooltip :trigger="['hover', 'focus']" :content="item.unit_code"><span tabindex="0" class="cell-text">{{ item.unit_code }}</span></ElTooltip></td><td>{{ item.archived ? '已归档' : item.status === 'ACTIVE' ? '启用' : '停用' }}</td></tr></tbody></table><p v-if="!preview.data.organizations.length">无可用本地部门。</p></div></template>
    </div>
    <template #footer><div class="access-actions access-dialog-footer"><button v-if="auth.managementCan('access_control.manage_accounts')" :disabled="saving || loading || !valid" @click="close(); emit('apply-departments')">按映射补充员工部门</button><button :disabled="saving" @click="close">关闭</button></div></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
:global(.department-mapping-window > .app-window-dialog__body) { display: flex; flex-direction: column; overflow: hidden; }
.mapping-dialog { display: flex; flex: 1 1 auto; flex-direction: column; min-width: 0; min-height: 0; color: #111; }
.mapping-dialog > p, .mapping-dialog > .access-warning, .mapping-dialog > h3 { flex: none; }
.mapping-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; flex: none; }
.mapping-toolbar { margin: 14px 0; }
.mapping-dialog .mapping-table { overflow: auto; min-height: 0; flex: 0 1 auto; border: 1px solid rgba(255,255,255,.72); border-radius: 5px; background: #eff7fc; margin-bottom: 14px;
  table { min-width: 1230px; border: 0; border-radius: 0; }
  th, td { box-sizing: border-box; height: 34px; padding: 0 10px; white-space: nowrap; overflow-wrap: normal; color: #111; border-bottom: 1px solid #dcebf5; }
  th { background: #d8e9f7; font-size: 12px; line-height: 18px; font-weight: 500; z-index: 2; }
  td { background: #eff7fc; font-size: 12px; line-height: 18px; }
  tr:last-child td { border-bottom: 0; }
  tr:hover td { background: #eaf2f9; }
  .fixed-right { position: sticky; right: 0; z-index: 1; }
  th.fixed-right { z-index: 3; }
  .cell-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .name-cell { font-size: 13px; line-height: 20px; }
  .cell-text:focus-visible { outline: 2px solid #3898ec; outline-offset: -2px; }
  :deep(.el-select) { width: 100%; }
  :deep(.el-select__wrapper) { min-height: 32px; height: 32px; padding: 0 10px; border: 0; border-radius: 5px; }
  :deep(.el-select__wrapper.is-focused) { outline: 2px solid #3898ec; outline-offset: -2px; }
  :deep(.el-select__wrapper.is-disabled) { background: #e2eaf2; color: #617182; }
  // 行内搜索输入由ElSelect布局，避免access-dialog原生输入框样式遮住回显文字。
  :deep(.el-select__input) { height: 20px !important; min-height: 0 !important; padding: 0 !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important; background: transparent !important; outline: none !important; }
}
.mapping-dialog .local-table table { min-width: 550px; }
.mapping-notice { color: var(--erp-tag-success-text); }
.mapping-dialog .mapping-empty { padding: 12px; }
</style>
