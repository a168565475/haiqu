<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { ElButton, ElInput, ElMessage, ElSelect, ElOption } from 'element-plus'
import { isAxiosError } from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAccountSwitchFlow } from '@/composables/useAccountSwitchFlow'
import { useAuthStore } from '@/stores/auth'
import type { SwitchTarget, SwitchTargetChoice } from '@/types/auth'

const auth = useAuthStore()
// This is the sole UI owner of the identity-changing flow, including non-ERP routes.
const flow = useAccountSwitchFlow()
const { busy, phase, error: flowError } = flow
const pickerOpen = ref(false)
const query = ref('')
const departmentId = ref('')
const roleId = ref('')
const departments = ref<SwitchTargetChoice[]>([])
const roles = ref<SwitchTargetChoice[]>([])
const searchInput = ref<InstanceType<typeof ElInput>>()
const targets = ref<SwitchTarget[]>([])
const selectedEmployeeId = ref('')
const targetState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const targetError = ref('')
const targetNeedsVerification = ref(false)
const loadedContext = ref('')
const loadedVersion = ref('')
const fieldId = useId()
let sequence = 0
let controller: AbortController | undefined
let searchTimer: ReturnType<typeof setTimeout> | undefined

const identityContext = computed(() => JSON.stringify([
  auth.user?.id ?? null, auth.identityVersion, auth.identityGeneration,
  auth.identityRequestGeneration, auth.identityReady, auth.canSwitchAccount,
]))
const selectedTarget = computed(() => targets.value.find(item => item.employee_id === selectedEmployeeId.value))
const canConfirm = computed(() => !busy.value && auth.canSwitchAccount && targetState.value === 'ready'
  && loadedContext.value === identityContext.value && loadedVersion.value === auth.identityVersion
  && !!selectedTarget.value)
const showStatus = computed(() => busy.value || !auth.canSwitchAccount
  || targetState.value === 'idle' || targetState.value === 'loading'
  || (targetState.value === 'ready' && !targets.value.length))
const phaseLabel = computed(() => ({
  idle: '', confirming: '等待确认…', leaving: '正在安全离开当前页面…', switching: '正在切换身份…',
  returning: '正在返回管理员…', verifying: '正在核验当前身份…', landing: '正在打开安全页面…',
})[phase.value])

function invalidateTargets() {
  sequence += 1
  controller?.abort()
  controller = undefined
  if (searchTimer !== undefined) clearTimeout(searchTimer)
  searchTimer = undefined
  selectedEmployeeId.value = ''
  targets.value = []
  loadedContext.value = ''
  loadedVersion.value = ''
  targetError.value = ''
  targetNeedsVerification.value = false
  targetState.value = 'idle'
}

async function loadTargets() {
  invalidateTargets()
  if (!pickerOpen.value || busy.value || !auth.canSwitchAccount) return
  const requestSequence = sequence
  const context = identityContext.value
  const requestQuery = query.value
  const filters = { department_id: departmentId.value || undefined, role_id: roleId.value || undefined }
  const requestController = new AbortController()
  controller = requestController
  targetState.value = 'loading'
  const current = () => pickerOpen.value && !requestController.signal.aborted
    && requestSequence === sequence && context === identityContext.value && requestQuery === query.value
  try {
    const response = await auth.loadSwitchTargets(requestQuery.trim() || undefined, requestController.signal, filters)
    if (!current()) return
    if (response.identity_version !== auth.identityVersion) {
      targetState.value = 'error'
      targetNeedsVerification.value = true
      targetError.value = '身份版本已变化，请先核验当前身份，再重新查询员工。'
      return
    }
    targets.value = response.results
    departments.value = response.departments || []
    roles.value = response.roles || []
    loadedContext.value = context
    loadedVersion.value = response.identity_version
    targetState.value = 'ready'
  } catch (error) {
    if (!current()) return
    targetState.value = 'error'
    targetNeedsVerification.value = isAxiosError(error) && error.response?.status === 403
    targetError.value = targetNeedsVerification.value
      ? '当前身份无权查询可切换员工，请重新核验身份后重试。'
      : '员工列表加载失败，请检查网络后重试。'
  } finally {
    if (controller === requestController) controller = undefined
  }
}

watch([query, departmentId, roleId], () => {
  // Synchronous invalidation closes the debounce window for stale selections.
  invalidateTargets()
  if (pickerOpen.value && !busy.value && auth.canSwitchAccount) {
    searchTimer = setTimeout(() => { void loadTargets() }, 200)
  }
}, { flush: 'sync' })
watch(identityContext, () => { invalidateTargets(); departments.value = []; roles.value = [] }, { flush: 'sync' })
watch(busy, value => { if (value) invalidateTargets() }, { flush: 'sync' })

function openSwitchDialog() {
  if (busy.value || !auth.canSwitchAccount) return
  query.value = ''
  departmentId.value = ''
  roleId.value = ''
  departments.value = []
  roles.value = []
  pickerOpen.value = true
  void loadTargets()
}
function closePicker() {
  if (busy.value) return
  pickerOpen.value = false
  invalidateTargets()
}
function beforeClose(done: () => void) {
  if (busy.value) return
  invalidateTargets()
  done()
}
async function confirmSwitch() {
  if (!canConfirm.value || !selectedTarget.value) return
  const employeeId = selectedTarget.value.employee_id
  // Recheck the exact loaded identity immediately before handing off the write.
  if (loadedContext.value !== identityContext.value || loadedVersion.value !== auth.identityVersion) return
  if (await flow.switchAccount(employeeId)) {
    pickerOpen.value = false
    invalidateTargets()
    ElMessage.success('已切换员工身份')
  }
}
async function returnAdmin() {
  if (busy.value || !auth.canReturnAdmin) return
  if (await flow.returnAdmin()) {
    pickerOpen.value = false
    invalidateTargets()
    ElMessage.success('已返回管理员身份')
  }
}
async function verifyIdentity() {
  if (busy.value) return
  if (await flow.verifyIdentity()) {
    ElMessage.success('已核验当前身份')
    if (pickerOpen.value) void loadTargets()
  }
}

function clearFilters() { query.value = ''; departmentId.value = ''; roleId.value = '' }
const hasFilters = computed(() => !!(query.value.trim() || departmentId.value || roleId.value))
const names = (items?: SwitchTargetChoice[]) => items?.map(item => item.name).join('、') || '—'

onBeforeUnmount(invalidateTargets)
defineExpose({ openSwitchDialog, returnAdmin, verifyIdentity, busy, flowError })
</script>

<template>
  <AppWindowDialog
    :model-value="pickerOpen"
    title="切换员工账号"
    :width="680"
    height="auto"
    :before-close="beforeClose"
    :show-close="!busy"
    :minimizable="false"
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    destroy-on-close
    @update:model-value="value => { if (!value) closePicker() }"
    @opened="searchInput?.focus()"
  >
    <div class="account-switch-picker" :aria-busy="targetState === 'loading' || busy">
      <div class="account-switch-picker__filters">
        <div class="account-switch-picker__search">
          <label :for="`${fieldId}-search`" class="account-switch-picker__label">搜索员工</label>
          <ElInput :id="`${fieldId}-search`" ref="searchInput" v-model="query" clearable :disabled="busy || !auth.canSwitchAccount" placeholder="姓名、工号或用户名" :aria-describedby="showStatus ? `${fieldId}-status` : undefined" />
        </div>
        <div>
          <label :for="`${fieldId}-department`" class="account-switch-picker__label">部门</label>
          <ElSelect :id="`${fieldId}-department`" v-model="departmentId" clearable filterable placeholder="全部部门" :disabled="busy || !auth.canSwitchAccount" data-department-filter>
            <ElOption v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" />
          </ElSelect>
        </div>
        <div>
          <label :for="`${fieldId}-role`" class="account-switch-picker__label">角色</label>
          <ElSelect :id="`${fieldId}-role`" v-model="roleId" clearable filterable placeholder="全部角色" :disabled="busy || !auth.canSwitchAccount" data-role-filter>
            <ElOption v-for="item in roles" :key="item.id" :label="item.name" :value="item.id" />
          </ElSelect>
        </div>
      </div>
      <div v-if="showStatus" :id="`${fieldId}-status`" class="account-switch-picker__status" role="status" aria-live="polite">
        <template v-if="busy">{{ phaseLabel || '正在处理身份操作…' }}</template>
        <template v-else-if="!auth.canSwitchAccount">当前身份暂不可切换。请关闭窗口，并使用账号菜单核验当前身份。</template>
        <template v-else-if="targetState === 'loading'">正在查询员工…</template>
        <template v-else-if="targetState === 'ready'">{{ hasFilters ? '没有匹配的员工，请修改筛选条件。' : '暂无可切换员工，请联系管理员检查员工账号状态。' }}</template>
        <template v-else-if="targetState === 'idle'">搜索条件或身份上下文已更新，请等待查询或重新查询员工。</template>
      </div>
      <div v-if="targetState === 'error'" class="account-switch-picker__error" role="alert">
        <span>{{ targetError }}</span>
        <ElButton v-if="targetNeedsVerification" :disabled="busy" data-verify-targets @click="verifyIdentity">重新核验身份</ElButton>
        <ElButton v-else :disabled="busy || !auth.canSwitchAccount" data-retry-targets @click="loadTargets">重试</ElButton>
      </div>
      <ElButton v-else-if="targetState === 'idle' && auth.canSwitchAccount && !busy" data-reload-targets @click="loadTargets">重新查询员工</ElButton>
      <ElButton v-else-if="targetState === 'ready' && hasFilters" data-clear-query @click="clearFilters">清除筛选条件</ElButton>
      <div v-if="targetState === 'ready' && targets.length" class="account-switch-picker__targets">
        <table class="account-switch-table" aria-label="选择要切换的员工">
          <colgroup><col style="width: 36%"><col style="width: 30%"><col style="width: 34%"></colgroup>
          <thead><tr><th scope="col">名称</th><th scope="col">部门</th><th scope="col">角色</th></tr></thead>
          <tbody>
            <tr v-for="target in targets" :key="target.employee_id" class="account-switch-target" :class="{ 'is-selected': selectedEmployeeId === target.employee_id }" @click="!busy && auth.canSwitchAccount && (selectedEmployeeId = target.employee_id)">
              <td><label class="account-switch-target__name"><input v-model="selectedEmployeeId" type="radio" :name="`${fieldId}-employee`" :value="target.employee_id" :disabled="busy || !auth.canSwitchAccount" :aria-label="`选择${target.display_name || '未命名员工'}`"><span>{{ target.display_name || '—' }}</span></label></td>
              <td>{{ names(target.departments) }}</td>
              <td>{{ names(target.roles) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="flowError" class="account-switch-picker__error" role="alert">{{ flowError }}</p>
    </div>
    <template #footer>
      <ElButton data-cancel-switch :disabled="busy" @click="closePicker">取消</ElButton>
      <ElButton type="primary" data-confirm-switch :disabled="!canConfirm" :loading="busy" @click="confirmSwitch">{{ busy ? '处理中…' : '确认切换' }}</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.account-switch-picker { color: var(--erp-color-text-primary); font: 13px/20px var(--erp-font-body); }
.account-switch-picker__filters { display: grid; grid-template-columns: minmax(0, 1.5fr) repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
.account-switch-picker__filters :deep(.el-select) { width: 100%; }
.account-switch-picker__label { display: block; margin-bottom: 6px; font-weight: 500; }
.account-switch-picker__status { margin: 12px 0; color: var(--erp-color-text-secondary); overflow-wrap: anywhere; }
.account-switch-picker__error { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0 0; color: var(--erp-color-danger); overflow-wrap: anywhere; }
.account-switch-picker__targets { max-height: 380px; overflow-y: auto; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); }
.account-switch-table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.account-switch-table th, .account-switch-table td { padding: 8px 12px; text-align: left; overflow-wrap: anywhere; }
.account-switch-table th { position: sticky; top: 0; z-index: 1; height: 36px; box-sizing: border-box; background: var(--erp-color-surface); font-weight: 500; border-bottom: 1px solid var(--erp-color-border); }
.account-switch-table td { border-bottom: 1px solid var(--erp-color-border); }
.account-switch-table tr:last-child td { border-bottom: 0; }
.account-switch-target { cursor: pointer; }
.account-switch-target:hover { background: var(--erp-color-hover); }
.account-switch-target.is-selected { background: var(--erp-color-selected); }
.account-switch-target__name { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.account-switch-target input { flex: none; width: 14px; height: 14px; margin: 0; accent-color: var(--erp-color-brand); }
.account-switch-target input:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.account-switch-picker :deep(.el-button) { height: 32px; }
@media (max-width: 600px) {
  .account-switch-picker__filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .account-switch-picker__search { grid-column: 1 / -1; }
}
</style>
