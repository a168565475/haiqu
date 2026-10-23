<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DropdownInstance, FormInstance, FormRules } from 'element-plus'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchFinanceAccounts, fetchFinanceAccount, createFinanceAccount, updateFinanceAccount, deleteFinanceAccount } from '@/api/financeAccounts'
import { fetchMasterDataList } from '@/api/referenceData'
import type { Currency } from '@/types/referenceData'
import type { FinanceAccount, FinanceAccountInput, FinanceAccountQuery } from '@/types/financeAccounts'

const auth = useAuthStore()
const can = (action: string) => auth.user?.is_superuser === true || auth.hasPermission(`finance.${action}_financeaccount`)
const rows = ref<FinanceAccount[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')
const status = ref<'' | 'ACTIVE' | 'INACTIVE'>('')
const applied = reactive({ q: '', status: '' as '' | 'ACTIVE' | 'INACTIVE' })
const loading = ref(false)
const loaded = ref(false)
const listError = ref('')
const forbidden = ref(false)
let listRequest = 0
let listController: AbortController | undefined
let detailRequest = 0
let detailController: AbortController | undefined
let disposed = false
const busyRow = ref('')
const dialog = ref(false)
const mode = ref<'create' | 'edit' | 'detail'>('create')
const record = ref<FinanceAccount>()
const latest = ref<FinanceAccount>()
const detailLoading = ref(false)
const formRef = ref<FormInstance>()
const blank = (): FinanceAccountInput => ({ account_type: '', category: '', name: '', account_number: '', currency_id: '', status: 'ACTIVE' })
const form = reactive<FinanceAccountInput>(blank())
const original = ref('')
const dirty = computed(() => dialog.value && mode.value !== 'detail' && JSON.stringify(form) !== original.value)
const submitting = ref(false)
const formError = ref('')
const fieldErrors = ref<Record<string, string>>({})
const conflict = ref(false)
const currencies = ref<Currency[]>([])
const currencyLoading = ref(false)
const currencyError = ref('')
let currencyRequest = 0
let creationKey = ''
const uncertain = ref(false)
let submittedBody: FinanceAccountInput | undefined
const title = computed(() => mode.value === 'detail' ? '公司账户详情' : mode.value === 'edit' ? '编辑公司账户' : '新增公司账户')
const rules: FormRules = Object.fromEntries(['account_type', 'category', 'name', 'account_number', 'currency_id'].map(key => [key, [{ required: true, message: '请填写此项', trigger: 'blur' }]]))
const statusText = (value: string) => value === 'ACTIVE' ? '启用' : '停用'

function message(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.error?.message || '请求未完成，请检查网络后重试。'
  return error instanceof Error ? error.message : '请求失败，请重试。'
}

async function loadList() {
  if (!can('view')) return
  const request = ++listRequest
  listController?.abort()
  listController = new AbortController()
  loading.value = true
  listError.value = ''
  const query: FinanceAccountQuery = { page: page.value, page_size: pageSize.value, q: applied.q, ...(applied.status ? { status: applied.status } : {}) }
  try {
    const result = await fetchFinanceAccounts(query, listController.signal)
    if (request !== listRequest || disposed) return
    rows.value = result.data
    total.value = result.meta.total
    page.value = result.meta.page
    loaded.value = true
    forbidden.value = false
  } catch (error) {
    if (request !== listRequest || disposed || axios.isCancel(error)) return
    if (axios.isAxiosError(error) && [401, 403].includes(error.response?.status || 0)) {
      forbidden.value = true
      rows.value = []
      total.value = 0
    }
    listError.value = `${loaded.value && !forbidden.value ? '刷新失败，保留上次结果。' : ''}${message(error)}`
  } finally {
    if (request === listRequest && !disposed) loading.value = false
  }
}
function filter(reset = false) {
  if (reset) { search.value = ''; status.value = '' }
  applied.q = search.value.trim(); applied.status = status.value; page.value = 1
  void loadList()
}

async function loadCurrencies(q = '') {
  const request = ++currencyRequest
  currencyLoading.value = true
  currencyError.value = ''
  try {
    const result = await fetchMasterDataList<Currency>('currencies', { q, status: 'ACTIVE', page: 1, page_size: 100 })
    if (request === currencyRequest && !disposed) currencies.value = result.data
  } catch (error) {
    if (request === currencyRequest && !disposed) currencyError.value = message(error)
  } finally { if (request === currencyRequest && !disposed) currencyLoading.value = false }
}

async function openEditor(action: 'create' | 'edit' | 'detail', row?: FinanceAccount) {
  if (!can(action === 'create' ? 'add' : action === 'edit' ? 'change' : 'view')) return
  mode.value = action; record.value = undefined; latest.value = undefined
  formError.value = ''; fieldErrors.value = {}; conflict.value = false; uncertain.value = false
  submittedBody = undefined; creationKey = crypto.randomUUID()
  Object.assign(form, blank()); delete form.code
  original.value = JSON.stringify(form)
  dialog.value = true
  const request = ++detailRequest
  detailController?.abort(); detailController = new AbortController()
  if (action !== 'detail') void loadCurrencies()
  if (!row) return
  detailLoading.value = true
  try {
    const result = await fetchFinanceAccount(row.id, detailController.signal)
    if (request !== detailRequest || !dialog.value || disposed) return
    record.value = result
    Object.assign(form, { account_type: result.account_type, category: result.category, name: result.name,
      account_number: result.account_number, currency_id: result.currency_id, status: result.status })
    original.value = JSON.stringify(form)
  } catch (error) {
    if (request === detailRequest && !disposed && !axios.isCancel(error)) formError.value = message(error)
  } finally { if (request === detailRequest && !disposed) detailLoading.value = false }
}

async function confirmLeave() {
  if (submitting.value || uncertain.value) {
    ElMessage.warning(uncertain.value ? '提交结果尚未确认，请先重试原提交以核实结果。' : '正在提交，请稍候。')
    return false
  }
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的账户信息，确定放弃修改？', '离开未保存表单', { confirmButtonText: '放弃修改', cancelButtonText: '继续填写', customClass: 'finance-account-confirm' })
    return true
  } catch { return false }
}
async function closeDialog(done?: () => void) {
  if (!await confirmLeave()) return
  ++detailRequest; detailController?.abort(); detailLoading.value = false
  if (done) done(); else dialog.value = false
}

async function save() {
  if (submitting.value || detailLoading.value || (mode.value === 'edit' && !record.value)) return
  if (!can(mode.value === 'create' ? 'add' : 'change')) return
  if (!uncertain.value && !await formRef.value?.validate().catch(() => false)) return
  if (submitting.value) return
  submitting.value = true; formError.value = ''; fieldErrors.value = {}; conflict.value = false
  if (!uncertain.value) submittedBody = { ...form }
  try {
    const result = mode.value === 'create'
      ? await createFinanceAccount(submittedBody!, creationKey)
      : await updateFinanceAccount(record.value!.id, submittedBody!, record.value!.etag)
    uncertain.value = false; original.value = JSON.stringify(form); dialog.value = false
    ElMessage.success(`账户${mode.value === 'create' ? '新增' : '修改'}成功`)
    record.value = result
    await loadList()
  } catch (error) {
    formError.value = message(error)
    const httpStatus = axios.isAxiosError(error) ? error.response?.status : undefined
    // 创建超时保留原键和原体，只重放该请求；不因网络错误生成第二条账户。
    uncertain.value = mode.value === 'create' && (!httpStatus || httpStatus >= 500)
    if (!uncertain.value) creationKey = crypto.randomUUID()
    conflict.value = httpStatus === 412 || httpStatus === 409
    if (axios.isAxiosError(error)) {
      const errors = error.response?.data?.error?.field_errors || {}
      fieldErrors.value = Object.fromEntries(Object.entries(errors).map(([key, value]) => [key, Array.isArray(value) ? value.join('；') : String(value)]))
    }
  } finally { submitting.value = false }
}

async function compareLatest() {
  if (!record.value) return
  try { latest.value = await fetchFinanceAccount(record.value.id) } catch (error) { formError.value = message(error) }
}
function acceptLatestVersion() {
  if (!latest.value || !record.value) return
  record.value = { ...record.value, etag: latest.value.etag }
  latest.value = undefined; conflict.value = false
  formError.value = '已确认最新版本；当前输入保留，请核对后重新保存。'
}

async function mutateRow(action: 'toggle' | 'delete', row: FinanceAccount) {
  if (busyRow.value || !can(action === 'delete' ? 'delete' : 'change')) return
  if (action === 'delete' && !row.can_delete) { ElMessage.warning(row.delete_block_reason || '已引用账户不可删除。'); return }
  try {
    await ElMessageBox.confirm(action === 'delete' ? `删除未引用账户“${row.name}”？此操作不能撤销。`
      : row.status === 'ACTIVE' ? `停用“${row.name}”后将不能用于新收款，历史记录保留。` : `重新启用“${row.name}”？`,
    action === 'delete' ? '删除公司账户' : '更改账户状态', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning', customClass: 'finance-account-confirm' })
  } catch { return }
  busyRow.value = row.id
  try {
    if (action === 'delete') await deleteFinanceAccount(row.id, row.etag)
    else await updateFinanceAccount(row.id, { status: row.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' }, row.etag)
    ElMessage.success(action === 'delete' ? '账户已删除' : row.status === 'ACTIVE' ? '账户已停用' : '账户已启用')
    if (action === 'delete' && rows.value.length === 1 && page.value > 1) page.value--
    await loadList()
  } catch (error) { listError.value = `${message(error)} 请刷新列表核对当前状态。` }
  finally { busyRow.value = '' }
}

const rowMenus = new Map<string, DropdownInstance>()
let pendingAction: { id: string; run: () => void } | undefined
function command(action: string, row: FinanceAccount) {
  pendingAction = { id: row.id, run: () => {
    if (action === 'detail' || action === 'edit') void openEditor(action, row)
    else if (action === 'toggle' || action === 'delete') void mutateRow(action, row)
  } }
}
async function menuVisibility(visible: boolean, id: string) {
  if (visible || pendingAction?.id !== id) return
  const action = pendingAction.run; pendingAction = undefined
  await nextTick()
  document.querySelector<HTMLButtonElement>(`[data-account-menu="${id}"]`)?.focus({ preventScroll: true })
  action()
}
function closeMenu(id: string) {
  rowMenus.get(id)?.handleClose()
  document.querySelector<HTMLButtonElement>(`[data-account-menu="${id}"]`)?.focus({ preventScroll: true })
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value || submitting.value || uncertain.value) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(confirmLeave)
onMounted(() => { void loadList(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => {
  disposed = true; ++listRequest; ++detailRequest; ++currencyRequest
  listController?.abort(); detailController?.abort(); pendingAction = undefined; rowMenus.clear()
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
    <section class="finance-accounts erp-glass-list">
      <el-alert v-if="!can('view') || forbidden" title="没有公司账户查看权限，请联系授权管理员。" type="warning" :closable="false" />
      <template v-else>
        <div class="erp-list-filter">
          <div class="erp-list-heading"><div class="erp-list-title-row"><h1>公司账户信息</h1><span class="erp-list-count">{{ loaded ? `${total} 条账户` : '尚未加载' }}</span></div></div>
          <div class="erp-list-filters">
            <label>搜索 <el-input v-model="search" placeholder="编码 / 名称 / 账号" clearable @keyup.enter="filter()" /></label>
            <label>状态 <el-select v-model="status" aria-label="筛选状态" placeholder="全部状态"><el-option label="全部状态" value=""/><el-option label="启用" value="ACTIVE"/><el-option label="停用" value="INACTIVE"/></el-select></label>
            <div class="erp-list-filter-actions"><el-button @click="filter(true)">重置</el-button><el-button @click="filter()">应用筛选</el-button><el-divider direction="vertical"/><el-button v-if="can('add')" type="primary" @click="openEditor('create')">新增账户</el-button></div>
          </div>
        </div>
        <div class="erp-list-data">
          <div class="erp-list-toolbar"><span>仅本公司账户；人民币收款只选启用的 CNY 账户</span><el-button :loading="loading" @click="loadList">刷新</el-button></div>
          <el-alert v-if="listError" :title="listError" type="error" :closable="false" show-icon><el-button link @click="loadList">重试</el-button></el-alert>
          <div v-loading="loading" class="erp-list-table-frame" :aria-busy="loading">
            <el-table :data="rows" height="100%" row-key="id" border highlight-current-row>
              <el-table-column prop="account_type" label="账户类型" min-width="120" show-overflow-tooltip/>
              <el-table-column prop="code" label="账户编码" min-width="160" show-overflow-tooltip/>
              <el-table-column prop="category" label="账户类别" min-width="110" show-overflow-tooltip/>
              <el-table-column prop="name" label="账户名称" min-width="220" show-overflow-tooltip/>
              <el-table-column prop="account_number" label="账户账号" min-width="250"><template #default="{row}"><span class="full-account-number">{{ row.account_number }}</span></template></el-table-column>
              <el-table-column label="账户状态" width="100"><template #default="{row}"><el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ statusText(row.status) }}</el-tag></template></el-table-column>
              <el-table-column prop="currency_code" label="币种" width="90"/>
              <el-table-column label="操作" width="100" fixed="right" align="center"><template #default="{row}">
                <el-dropdown :ref="(el: unknown) => { if (el) rowMenus.set(row.id, el as DropdownInstance); else rowMenus.delete(row.id) }" trigger="click" placement="bottom-end" popper-class="finance-account-popper" @command="command($event,row)" @visible-change="menuVisibility($event,row.id)">
                  <el-button link :disabled="!!busyRow" :data-account-menu="row.id" @keydown.esc.stop.prevent="closeMenu(row.id)">更多<svg viewBox="0 0 12 12" aria-hidden="true" class="more-arrow"><path d="m3 4 3 3 3-3"/></svg></el-button>
                  <template #dropdown><el-dropdown-menu @keydown.esc.stop.prevent="closeMenu(row.id)">
                    <el-dropdown-item command="detail">详情</el-dropdown-item>
                    <el-dropdown-item v-if="can('change')" command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item v-if="can('change')" command="toggle">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-dropdown-item>
                    <el-dropdown-item v-if="can('delete')" command="delete" divided :disabled="!row.can_delete" :title="row.delete_block_reason || ''"><span class="danger-action">{{ row.can_delete ? '删除' : '已引用，不可删除' }}</span></el-dropdown-item>
                  </el-dropdown-menu></template>
                </el-dropdown>
              </template></el-table-column>
              <template #empty><span v-if="loading">正在加载账户…</span><span v-else-if="listError">账户数据尚未成功加载</span><div v-else-if="applied.q || applied.status">没有匹配账户 <el-button link @click="filter(true)">清除筛选</el-button></div><div v-else>暂无公司账户 <el-button v-if="can('add')" link @click="openEditor('create')">新增账户</el-button></div></template>
            </el-table>
          </div>
          <div class="erp-list-footer"><span>账号按原始文本完整显示</span><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="loadList" /></div>
        </div>
      </template>
    </section>
    <AppWindowDialog v-model="dialog" :title="title" :width="680" :min-width="280" :before-close="closeDialog" :minimizable="false" destroy-on-close modal-class="finance-account-overlay">
      <div v-loading="detailLoading" class="finance-account-dialog">
        <el-alert v-if="formError" :title="formError" type="error" :closable="false" show-icon/>
        <el-alert v-if="uncertain" title="提交结果尚未确认，输入已保留。请重试原提交，不会重复创建账户。" type="warning" :closable="false"/>
        <template v-if="mode === 'detail' && record">
          <div class="document-heading"><div><h2>{{ record.name }}</h2><p>{{ record.code }} · 公司账户</p></div><el-tag :type="record.status === 'ACTIVE' ? 'success' : 'info'">{{ statusText(record.status) }}</el-tag></div>
          <dl class="document-facts"><div><dt>账户类型</dt><dd>{{record.account_type}}</dd></div><div><dt>账户类别</dt><dd>{{record.category}}</dd></div><div><dt>币种</dt><dd>{{record.currency_code}} · {{record.currency_name}}</dd></div><div class="wide"><dt>账户账号</dt><dd class="full-account-number">{{record.account_number}}</dd></div></dl>
          <p class="document-note">账户维护不会改变历史收款快照；已引用的账户可以停用，不可删除。</p>
        </template>
        <template v-else-if="mode !== 'detail' && (mode === 'create' || record)">
          <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="form-grid" :disabled="submitting || uncertain" @submit.prevent="save">
            <el-form-item label="账户类型" prop="account_type" :error="fieldErrors.account_type"><el-input v-model="form.account_type" maxlength="80"/></el-form-item>
            <el-form-item label="账户编码"><el-input :model-value="record?.code || '保存时自动生成'" readonly/><small>已有编码保留，新增自动编号</small></el-form-item>
            <el-form-item label="账户类别" prop="category" :error="fieldErrors.category"><el-input v-model="form.category" maxlength="80"/></el-form-item>
            <el-form-item label="账户名称" prop="name" :error="fieldErrors.name"><el-input v-model="form.name" maxlength="200"/></el-form-item>
            <el-form-item label="账户账号" prop="account_number" class="wide" :error="fieldErrors.account_number"><el-input v-model="form.account_number" inputmode="text" maxlength="100"/><small>按文本保存，保留完整账号及前导零</small></el-form-item>
            <el-form-item label="币种" prop="currency_id" :error="fieldErrors.currency_id"><el-select v-model="form.currency_id" aria-label="账户币种" filterable remote :remote-method="loadCurrencies" :loading="currencyLoading" popper-class="finance-account-popper"><el-option v-for="item in currencies" :key="item.id" :value="item.id" :label="`${item.code} · ${item.chinese_name}`"/><el-option v-if="record && !currencies.some(item=>item.id===record?.currency_id)" :value="record.currency_id" :label="`${record.currency_code} · 当前币种（请核对有效状态）`" disabled/></el-select><span v-if="currencyError" role="alert">{{currencyError}} <el-button link @click="loadCurrencies()">重试</el-button></span></el-form-item>
            <el-form-item label="账户状态" prop="status" :error="fieldErrors.status"><el-radio-group v-model="form.status"><el-radio value="ACTIVE">启用</el-radio><el-radio value="INACTIVE">停用</el-radio></el-radio-group></el-form-item>
          </el-form>
          <el-alert title="账户变更不改写历史收款快照。已引用账户不可删除，可停用。" type="info" :closable="false"/>
          <el-button v-if="conflict && record" @click="compareLatest">查看最新版本并比较</el-button>
          <div v-if="latest" class="latest-version"><strong>服务器最新版本（当前输入未替换）</strong><dl class="document-facts"><div><dt>名称 / 类型 / 类别</dt><dd>{{latest.name}} / {{latest.account_type}} / {{latest.category}}</dd></div><div><dt>币种 / 状态</dt><dd>{{latest.currency_code}} / {{statusText(latest.status)}}</dd></div><div class="wide"><dt>账户账号</dt><dd class="full-account-number">{{latest.account_number}}</dd></div></dl><el-button @click="acceptLatestVersion">已比较，保留当前输入继续修改</el-button></div>
        </template>
      </div>
      <template #footer><el-button :disabled="submitting || uncertain" @click="closeDialog()">{{mode === 'detail' ? '关闭' : '取消'}}</el-button><el-button v-if="mode !== 'detail'" type="primary" :loading="submitting" :disabled="detailLoading || (mode === 'edit' && !record)" @click="save">{{uncertain ? '重试原提交' : '保存账户'}}</el-button></template>
    </AppWindowDialog>
</template>

<style scoped lang="scss">
.more-arrow { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.5; margin-left: 4px; }
.finance-accounts .erp-list-filters label:first-child .el-input { width: 250px; }
.finance-accounts .erp-list-filters .el-select { width: 140px; }
.finance-accounts .erp-list-filters > label { white-space: nowrap; }
.erp-list-toolbar { color: var(--erp-color-text-secondary); }
.erp-list-toolbar > .el-button { margin-left: auto; }
.full-account-number { white-space: normal; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.finance-accounts :deep(.el-table__header .cell) { font-weight: 500; }
.finance-accounts :deep(.el-table__body .cell:has(.full-account-number)) { padding-block: 8px; }
.finance-account-dialog { display: grid; gap: 16px; color: var(--erp-color-text-primary); }
.form-grid, .document-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 20px; }
.form-grid .el-form-item { margin-bottom: 0; min-width: 0; }
.wide { grid-column: 1 / -1; }
.form-grid small, .document-note, dt, .document-heading p { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.document-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid var(--erp-color-border); padding-bottom: 16px; }
.document-heading h2 { margin: 0; font-size: 22px; line-height: 30px; overflow-wrap: anywhere; }
.document-heading p { margin: 6px 0 0; }
.document-facts { margin: 0; }
.document-facts dd { margin: 4px 0 0; font-size: 14px; line-height: 24px; overflow-wrap: anywhere; }
.document-note { margin: 0; }
.latest-version { padding-top: 16px; border-top: 1px solid var(--erp-color-border); }
@media (max-width: 900px) {
  .finance-accounts .erp-list-heading h1 { font-size: 28px !important; line-height: 36px !important; }
  .finance-accounts .erp-list-footer { height: auto; flex-wrap: wrap; }
}
@media (max-width: 600px) {
  .finance-accounts .erp-list-heading h1 { font-size: 24px !important; line-height: 32px !important; }
  .finance-accounts .erp-list-filters > label { width: 100%; }
  .finance-accounts .erp-list-filters label:first-child .el-input, .finance-accounts .erp-list-filters .el-select { width: 100%; }
  .finance-accounts .erp-list-filter-actions { margin-left: 0; flex-wrap: wrap; }
  .form-grid, .document-facts { grid-template-columns: 1fr; }
  .finance-accounts :deep(.el-table-fixed-column--right) { position: static !important; }
}
@media (prefers-reduced-motion: reduce) {
  .finance-accounts, .finance-account-dialog { &, :deep(*), :deep(*::before), :deep(*::after) { animation: none !important; transition: none !important; } }
}
</style>
<style>
.finance-account-popper .danger-action { color: var(--el-color-danger); }
@media (prefers-reduced-motion: reduce) {
  .finance-account-popper, .finance-account-popper *, .finance-account-confirm, .finance-account-confirm *, .finance-account-overlay, .finance-account-overlay * { animation: none !important; transition: none !important; }
}
</style>
