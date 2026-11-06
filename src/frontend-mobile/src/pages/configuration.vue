<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { isAxiosError, isCancel } from 'axios'
import { ActionSheet as VanActionSheet, Button as VanButton, Empty as VanEmpty, Field as VanField, Loading as VanLoading, Popup as VanPopup, Search as VanSearch, showConfirmDialog, showSuccessToast } from 'vant'
import 'vant/es/action-sheet/style'
import 'vant/es/button/style'
import 'vant/es/empty/style'
import 'vant/es/field/style'
import 'vant/es/loading/style'
import 'vant/es/popup/style'
import 'vant/es/search/style'
import WorkPage from '@/components/WorkPage.vue'
import { useAuthStore } from '@/stores/auth'
import { deleteWorkshopEmployee, fetchWorkshopEmployee, fetchWorkshopEmployeeOptions, fetchWorkshopEmployees, updateWorkshopEmployee } from '@/api/workshopEmployees'
import type { WorkshopEmployee, WorkshopEmployeeInput, WorkshopEmployeeOptions } from '@/types/workshopEmployees'
import { errorMessage } from '@/utils/errors'

const auth = useAuthStore()
const canView = computed(() => auth.hasPermission('workshop_config.view_workshopemployee'))
const canChange = computed(() => auth.hasPermission('workshop_config.change_workshopemployee'))
const rows = ref<WorkshopEmployee[]>([])
const options = ref<WorkshopEmployeeOptions>({ workshops: [], editable_workshops: [] })
const editableWorkshops = computed(() => options.value.editable_workshops.filter(item => item.status === 'ACTIVE'))
const search = ref('')
const workshop = ref('')
const viewMode = ref<'pending' | 'all'>('pending')
const page = ref(1)
const total = ref(0)
const totalPages = ref(0)
const loading = ref(false)
const message = ref('')
const busy = ref(false)
const editorOpen = ref(false)
const editing = ref<WorkshopEmployee | null>(null)
const etag = ref('')
const editorError = ref('')
const conflict = ref(false)
const form = reactive<WorkshopEmployeeInput>({ workshop: '', position: '', is_supervisor: false, status: 'ACTIVE' })
const actionEmployee = ref<WorkshopEmployee | null>(null)
const assignmentActions = computed(() => [
  { name: actionEmployee.value?.status === 'ACTIVE' ? '结束任职' : '恢复任职', value: 'status' as const },
  { name: '解除安排', value: 'clear' as const, color: '#b42318' },
])
let listController: AbortController | undefined
const lifetime = new AbortController()
let active = true

const canEdit = (row: WorkshopEmployee) => canChange.value && row.can_edit
const employeeName = (row: WorkshopEmployee) => row.employee_name || row.name
const statusLabel = (row: WorkshopEmployee) => !row.workshop ? '未安排' : row.status === 'ACTIVE' ? '任职中' : '已离岗'

function selectAssignmentAction(action: { value: 'status' | 'clear' }) {
  const row = actionEmployee.value
  actionEmployee.value = null
  if (row) void changeAssignment(row, action.value)
}

async function load(refreshOptions = false) {
  if (!canView.value) return
  listController?.abort()
  const current = new AbortController()
  listController = current
  loading.value = true
  message.value = ''
  try {
    if (refreshOptions) {
      const value = await fetchWorkshopEmployeeOptions(current.signal)
      if (!active || current !== listController) return
      options.value = value
      if (!value.workshops.some(item => item.id === workshop.value)) workshop.value = ''
    }
    const result = await fetchWorkshopEmployees({
      page: page.value,
      q: search.value.trim() || undefined,
      workshop: workshop.value || undefined,
      position_state: viewMode.value === 'pending' ? 'ROLE_PENDING' : 'ROLE_ALL',
    }, current.signal)
    if (!active || current !== listController) return
    if (page.value > 1 && result.meta.total_pages < page.value) {
      page.value = Math.max(1, result.meta.total_pages)
      await load()
      return
    }
    rows.value = result.data
    total.value = result.meta.total
    totalPages.value = result.meta.total_pages
  } catch (error) {
    if (active && current === listController && !isCancel(error)) {
      rows.value = []
      total.value = 0
      totalPages.value = 0
      message.value = errorMessage(error, '员工名单加载失败，请重试')
    }
  } finally {
    if (current === listController) { loading.value = false; listController = undefined }
  }
}

function searchList() { page.value = 1; void load() }
function changePage(value: number) { page.value = value; void load() }
function changeViewMode(value: 'pending' | 'all') {
  if (viewMode.value === value || busy.value) return
  viewMode.value = value
  page.value = 1
  void load()
}

async function openEditor(row: WorkshopEmployee) {
  if (busy.value || !canEdit(row)) return
  busy.value = true
  const wasOpen = editorOpen.value
  try {
    const detail = await fetchWorkshopEmployee(row.id, lifetime.signal)
    if (!active) return
    if (!canEdit(detail.data)) throw new Error('该员工已不在可修改范围，请刷新名单。')
    editing.value = detail.data
    etag.value = detail.etag
    Object.assign(form, { workshop: detail.data.workshop || detail.data.role_workshop || '', position: detail.data.position, is_supervisor: detail.data.is_supervisor, status: detail.data.status })
    conflict.value = false
    editorError.value = ''
    editorOpen.value = true
  } catch (error) {
    if (active && !isCancel(error)) {
      const text = errorMessage(error, '配置读取失败，请刷新后重试')
      if (wasOpen) editorError.value = text
      else message.value = text
    }
  } finally { if (active) busy.value = false }
}

async function reloadEditor() {
  if (!editing.value || busy.value) return
  try { await showConfirmDialog({ title: '重新读取配置？', message: '当前未保存的填写内容将被最新配置替换。' }) }
  catch { return }
  if (active) await openEditor(editing.value)
}

async function save() {
  if (!editing.value || busy.value || conflict.value || !canEdit(editing.value)) return
  editorError.value = ''
  if (!editableWorkshops.value.some(item => item.id === form.workshop)) { editorError.value = '请选择有修改权限的启用车间。'; return }
  if (editing.value.role_workshop && form.workshop !== editing.value.role_workshop) { editorError.value = '车间已按角色对应，不能更换。'; return }
  if (!form.position.trim()) { editorError.value = '请输入岗位。'; return }
  busy.value = true
  try {
    await updateWorkshopEmployee(editing.value.id, { workshop: form.workshop, position: form.position.trim(), is_supervisor: form.is_supervisor, status: form.status }, etag.value)
    if (!active) return
    editorOpen.value = false
    showSuccessToast('已保存车间配置')
    await load(true)
  } catch (error) {
    if (active && !isCancel(error)) {
      conflict.value = isAxiosError(error) && [409, 412].includes(error.response?.status || 0)
      editorError.value = errorMessage(error, '保存失败，请核对后重试')
    }
  } finally { if (active) busy.value = false }
}

async function changeAssignment(row: WorkshopEmployee, action: 'status' | 'clear') {
  if (busy.value || !canEdit(row) || !row.workshop) return
  busy.value = true
  message.value = ''
  try {
    const detail = await fetchWorkshopEmployee(row.id, lifetime.signal)
    if (!active) return
    if (!canEdit(detail.data)) throw new Error('该员工已不在可修改范围，请刷新名单。')
    const nextStatus = detail.data.status === 'ACTIVE' ? 'LEFT' : 'ACTIVE'
    const label = action === 'clear' ? '解除安排' : nextStatus === 'LEFT' ? '结束任职' : '恢复任职'
    try {
      await showConfirmDialog({ title: `${label}？`, message: action === 'clear'
        ? `清除“${employeeName(detail.data)}”的车间、岗位和主管安排，员工档案与角色保留。`
        : `确认${label}“${employeeName(detail.data)}”？仅改变车间任职，不修改行政员工状态。`, confirmButtonText: label })
    } catch { return }
    if (!active) return
    if (action === 'clear') await deleteWorkshopEmployee(row.id, detail.etag)
    else await updateWorkshopEmployee(row.id, { status: nextStatus }, detail.etag)
    if (!active) return
    showSuccessToast(`已${label}`)
    await load(true)
  } catch (error) {
    if (active && !isCancel(error)) message.value = errorMessage(error, '操作失败，请刷新后核对')
  } finally { if (active) busy.value = false }
}

onMounted(() => load(true))
onUnmounted(() => { active = false; listController?.abort(); lifetime.abort() })
</script>

<template>
  <WorkPage title="车间配置" :subtitle="options.workshops.map(item => item.name).join(' · ') || '按角色对应车间'" section="configuration" home class="employee-page">
    <VanEmpty v-if="!canView" description="无权查看车间员工，请联系管理员" />
    <template v-else>
      <div class="employee-view-switch" role="tablist" aria-label="员工名单范围">
        <button type="button" role="tab" :aria-selected="viewMode === 'pending'" :class="{ active: viewMode === 'pending' }" :disabled="loading || busy" @click="changeViewMode('pending')">待设置岗位</button>
        <button type="button" role="tab" :aria-selected="viewMode === 'all'" :class="{ active: viewMode === 'all' }" :disabled="loading || busy" @click="changeViewMode('all')">全部员工</button>
      </div>

      <section class="employee-tools" aria-label="查找车间员工">
        <div class="employee-search"><VanSearch v-model="search" aria-label="搜索员工" placeholder="姓名、角色或岗位" @search="searchList" @clear="searchList" /><button class="action-link" :disabled="busy" @click="searchList">搜索</button></div>
        <label v-if="options.workshops.length > 1" class="workshop-filter"><span>车间</span><select v-model="workshop" aria-label="筛选车间" :disabled="busy || loading" @change="searchList"><option value="">授权车间</option><option v-for="item in options.workshops" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
      </section>
      <div class="employee-list-heading"><h2>{{ viewMode === 'pending' ? '待设置岗位' : '车间员工' }} <span>{{ total }} 人</span></h2><button class="action-link" :disabled="loading || busy" @click="load(true)">刷新</button></div>
      <div v-if="message" class="error-panel" role="alert"><p>{{ message }}</p><VanButton size="small" plain :disabled="busy" @click="load(true)">重试</VanButton></div>
      <div v-if="loading" class="employee-loading" role="status"><VanLoading size="22">正在加载员工</VanLoading></div>
      <div v-else class="employee-list">
        <article v-for="row in rows" :key="row.id" class="employee-card">
          <div class="employee-main">
            <div class="employee-title"><h3>{{ employeeName(row) }}</h3><span class="employee-status" :class="{ 'is-active': row.workshop && row.status === 'ACTIVE' }">{{ statusLabel(row) }}</span></div>
            <p class="employee-assignment"><span>{{ row.workshop ? row.workshop_name : row.role_workshop_name || '未对应车间' }}</span><span class="assignment-divider" aria-hidden="true">/</span><strong :class="{ 'is-unset': !row.position }">{{ row.position || '待设置岗位' }}</strong></p>
            <p class="employee-role">角色：{{ row.roles || '未分配' }}</p>
            <p class="employee-meta"><span>{{ row.department || '未分配部门' }}</span><span>{{ row.is_supervisor ? '主管' : '非主管' }}</span></p>
          </div>
          <div v-if="canEdit(row)" class="employee-actions">
            <VanButton size="small" :type="row.position ? 'default' : 'primary'" :plain="!!row.position" :disabled="busy" @click="openEditor(row)">{{ row.position ? '编辑' : '设置岗位' }}</VanButton>
            <button v-if="row.workshop" class="action-link" :disabled="busy" :aria-label="`${employeeName(row)}的更多操作`" @click="actionEmployee = row">更多</button>
          </div>
        </article>
        <div v-if="!rows.length && !message" class="employee-empty">
          <h3>{{ viewMode === 'pending' && !search.trim() && !workshop ? '暂无待设置岗位员工' : '暂无符合条件的员工' }}</h3>
          <p>{{ viewMode === 'pending' && !search.trim() && !workshop ? '仅列出角色与车间明确对应的员工，可切换全部员工核对。' : '换个关键词或车间筛选条件试试。' }}</p>
          <VanButton v-if="viewMode === 'pending' && !search.trim() && !workshop" size="small" plain type="primary" :disabled="loading || busy" @click="changeViewMode('all')">查看全部员工</VanButton>
        </div>
      </div>
      <nav v-if="totalPages > 1" class="employee-pagination" aria-label="员工分页"><VanButton size="small" :disabled="page <= 1 || loading || busy" @click="changePage(page - 1)">上一页</VanButton><span>{{ page }} / {{ totalPages }}</span><VanButton size="small" :disabled="page >= totalPages || loading || busy" @click="changePage(page + 1)">下一页</VanButton></nav>
    </template>

    <VanActionSheet :show="!!actionEmployee" :title="actionEmployee ? employeeName(actionEmployee) : ''" :actions="assignmentActions" cancel-text="取消" @update:show="value => { if (!value) actionEmployee = null }" @select="selectAssignmentAction" />

    <VanPopup v-model:show="editorOpen" position="bottom" round class="employee-editor" :close-on-click-overlay="!busy" :closeable="!busy" :lock-scroll="true">
      <h2>编辑车间安排</h2>
      <template v-if="editing">
        <div class="employee-editor-identity"><strong>{{ employeeName(editing) }}</strong><span>部门：{{ editing.department || '未分配部门' }}</span><span>角色：{{ editing.roles || '未分配' }}</span></div>
        <form class="employee-editor-form" @submit.prevent="save">
          <div v-if="editing.role_workshop" class="employee-role-workshop"><span>角色对应车间</span><strong>{{ editing.role_workshop_name }}</strong><small>车间按角色自动对应，不能改到其他车间。</small></div>
          <label v-else class="employee-select"><span>车间</span><select v-model="form.workshop" aria-label="编辑车间" :disabled="busy"><option disabled value="">请选择车间</option><option v-for="item in editableWorkshops" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          <VanField v-model="form.position" label="岗位" placeholder="填写岗位" maxlength="100" :disabled="busy" />
          <label class="employee-select"><span>是否主管</span><select v-model="form.is_supervisor" aria-label="是否主管" :disabled="busy"><option :value="false">否</option><option :value="true">是</option></select></label>
          <label class="employee-select"><span>任职状态</span><select v-model="form.status" aria-label="车间任职状态" :disabled="busy"><option value="ACTIVE">任职中</option><option value="LEFT">已离岗</option></select></label>
          <p class="employee-editor-note">只修改车间安排；员工档案、部门和角色保持原样。</p>
          <div v-if="editorError" class="error-panel" role="alert"><p>{{ editorError }}</p><VanButton v-if="conflict" size="small" plain :disabled="busy" @click="reloadEditor">重新读取当前配置</VanButton></div>
          <div class="employee-editor-actions"><VanButton native-type="button" :disabled="busy" @click="editorOpen = false">取消</VanButton><VanButton native-type="submit" type="primary" :loading="busy" :disabled="conflict || !canChange">保存</VanButton></div>
        </form>
      </template>
    </VanPopup>
  </WorkPage>
</template>

<style scoped>
.employee-page { --employee-ink: #102a43; }
.employee-page :deep(.work-content) { padding: 12px 12px 28px; }
.employee-view-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-bottom: 8px; padding: 3px; border-radius: 10px; background: #e5ebf3; }
.employee-view-switch button { min-height: 44px; border: 0; border-radius: 7px; color: #465972; background: transparent; font-size: 14px; font-weight: 600; }
.employee-view-switch button.active { color: #174db6; background: var(--mobile-surface); box-shadow: 0 2px 4px rgb(16 42 67 / 8%); }
.employee-view-switch button:disabled { opacity: .55; }
.employee-search { display: flex; align-items: center; gap: 4px; }
.employee-search :deep(.van-search) { flex: 1; min-width: 0; padding: 0; background: transparent; }
.employee-search :deep(.van-search__content) { border: 1px solid var(--mobile-border); background: var(--mobile-surface); border-radius: 8px; }
.employee-search > button { flex-shrink: 0; }
.workshop-filter { display: flex; align-items: center; gap: 12px; padding-top: 8px; font-size: 14px; }
.workshop-filter select { flex: 1; min-width: 0; }
select { min-height: 44px; padding: 8px 10px; border: 1px solid var(--mobile-border); border-radius: 8px; background: var(--mobile-surface); color: var(--mobile-text); }
select:focus-visible { outline: 3px solid var(--mobile-primary); outline-offset: 3px; }
.employee-list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 4px; }
.employee-list-heading h2 { font-size: 14px; margin: 0; }
.employee-list-heading h2 span { font-size: 13px; font-weight: 400; color: #51637b; margin-left: 5px; font-variant-numeric: tabular-nums; }
.employee-loading { text-align: center; padding: 36px 0; }
.employee-list { border: 1px solid var(--mobile-border); border-radius: 12px; background: var(--mobile-surface); }
.employee-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; padding: 12px; }
.employee-card + .employee-card { border-top: 1px solid var(--mobile-border); }
.employee-main { min-width: 0; }
.employee-title { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.employee-title h3 { font-size: 17px; font-weight: 600; margin: 0; line-height: 24px; overflow-wrap: anywhere; }
.employee-status { font-size: 12px; color: #596b81; }
.employee-status.is-active { color: #147354; }
.employee-assignment { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 6px; margin: 4px 0; font-size: 14px; line-height: 21px; overflow-wrap: anywhere; }
.assignment-divider { color: #718096; }
.employee-assignment strong { font-weight: 600; }
.employee-assignment .is-unset { color: #a24b16; }
.employee-role, .employee-meta { margin: 0; color: #51637b; font-size: 12px; line-height: 18px; overflow-wrap: anywhere; }
.employee-meta { display: flex; flex-wrap: wrap; column-gap: 10px; }
.employee-actions { display: flex; flex-direction: column; align-items: stretch; align-self: center; min-width: 76px; }
.employee-actions :deep(.van-button) { padding-inline: 10px; font-size: 13px; border-radius: 8px; }
.employee-actions .action-link { font-size: 12px; font-weight: 400; }
.employee-empty { display: grid; justify-items: center; padding: 36px 18px; text-align: center; }
.employee-empty h3 { margin: 0 0 6px; font-size: 17px; }
.employee-empty p { margin: 0 0 16px; color: var(--mobile-muted); font-size: 13px; }
.employee-pagination { display: flex; justify-content: center; align-items: center; gap: 12px; margin-top: 16px; font-size: 14px; }
.employee-editor { width: min(100%, 640px); max-height: 90dvh; left: 0; right: 0; margin-inline: auto; padding: 20px 16px max(20px, env(safe-area-inset-bottom)); }
.employee-editor h2 { margin: 0 36px 16px 0; font-size: 19px; }
.employee-editor-identity { display: grid; gap: 3px; padding: 12px; border-radius: 8px; background: var(--mobile-canvas); overflow-wrap: anywhere; }
.employee-editor-identity span { font-size: 13px; color: var(--mobile-muted); }
.employee-role-workshop { display: grid; gap: 3px; margin: 12px 0 4px; padding: 12px 16px; border: 1px solid #c6d7f2; border-radius: 10px; background: var(--mobile-primary-soft); }
.employee-role-workshop span, .employee-role-workshop small { color: #38587f; font-size: 12px; }
.employee-role-workshop strong { color: var(--employee-ink); font-size: 16px; }
.employee-editor-form { margin-top: 12px; }
.employee-select { display: grid; grid-template-columns: 5.8em minmax(0, 1fr); align-items: center; gap: 12px; padding: 10px 16px; font-size: 14px; }
.employee-select select { width: 100%; }
.employee-editor-note { color: var(--mobile-muted); font-size: 13px; line-height: 1.7; margin: 12px 0; }
.employee-editor-actions { display: grid; grid-template-columns: 1fr 2fr; gap: 12px; margin-top: 16px; }
</style>
