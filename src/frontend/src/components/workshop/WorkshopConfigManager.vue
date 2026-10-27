<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import {
  createWorkshopConfig,
  deleteWorkshopEmployee,
  fetchWorkshopConfigDetail,
  fetchWorkshopConfigList,
  updateWorkshopConfig,
} from '@/api/workshopConfig'
import { useAuthStore } from '@/stores/auth'
import type {
  Craft,
  CraftType,
  EditableResourceKind,
  Operation,
  OutsourcingCode,
  PlanCategory,
  RecordStatus,
  Workshop,
  WorkshopConfigInput,
  WorkshopConfigRecord,
  WorkshopEmployee,
  WorkshopEmployeeStatus,
} from '@/types/workshopConfig'

const props = defineProps<{
  kind: EditableResourceKind
  initialWorkshop?: string
  initialCraftType?: CraftType
  initialCraft?: string
}>()
const emit = defineEmits<{ (event: 'saved'): void }>()

const auth = useAuthStore()
const permissionModel = computed(() => ({
  employees: 'workshopemployee',
  crafts: 'craft',
  operations: 'operation',
})[props.kind])
const can = (action: 'view' | 'add' | 'change') => (
  auth.user?.is_superuser === true || auth.hasPermission(`workshop_config.${action}_${permissionModel.value}`)
)
const canView = computed(() => can('view'))
const canAdd = computed(() => props.kind !== 'employees' && can('add'))
const canChange = computed(() => can('change'))

const metadata = computed(() => ({
  employees: { title: '车间员工管理', createLabel: '新增员工', search: '搜索姓名、工号或岗位' },
  crafts: { title: '工艺信息管理', createLabel: '新增工艺', search: '搜索工艺或车间' },
  operations: { title: '工序信息管理', createLabel: '新增工序', search: '搜索品名、工艺或工序' },
})[props.kind])

const rows = ref<WorkshopConfigRecord[]>([])
const employeeRows = computed(() => rows.value as WorkshopEmployee[])
const craftRows = computed(() => rows.value as Craft[])
const operationRows = computed(() => rows.value as Operation[])
const workshops = ref<Workshop[]>([])
const crafts = ref<Craft[]>([])
const loading = ref(false)
const loadError = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
let requestSequence = 0

const filters = reactive({
  keyword: '',
  status: '',
  workshop: props.initialWorkshop || '',
  position: '',
  isSupervisor: '' as '' | boolean,
  craftType: props.initialCraftType || '' as '' | CraftType,
  craft: props.initialCraft || '',
})

const editorVisible = ref(false)
const saving = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const editingId = ref('')
const editingEtag = ref('')
const editingEmployee = ref<WorkshopEmployee | null>(null)
const form = reactive({
  name: '',
  employee: '',
  status: 'ACTIVE' as RecordStatus | WorkshopEmployeeStatus,
  workshop: '',
  position: '',
  isSupervisor: false,
  craftType: 'INTERNAL' as CraftType,
  planCategory: null as PlanCategory | null,
  outsourcingCode: null as OutsourcingCode | null,
  craft: '',
  productName: '',
})

const selectedFormCraft = computed(() => crafts.value.find((item) => item.id === form.craft) || null)
const isMetalCraft = (craft: Craft | null | undefined) => (
  craft?.workshop_name === '金工车间'
)
const editorHeight = computed(() => ({ employees: 360, crafts: 670, operations: 700 })[props.kind])

function apiErrorMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, unknown> } } } })?.response?.data
  const fields = data?.error?.field_errors
  if (fields) {
    const first = Object.values(fields)[0]
    if (Array.isArray(first) && first.length) return String(first[0])
    if (first) return String(first)
  }
  return data?.error?.message || fallback
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replaceAll('/', '-')
}

function employeeLabel(employee: WorkshopEmployee): string {
  if (!employee.employee) return `${employee.name}（待关联）`
  return employee.employee_name || employee.name
}




function buildQuery(): Record<string, string | number | boolean | undefined> {
  const query: Record<string, string | number | boolean | undefined> = {
    page: page.value,
    page_size: pageSize.value,
    q: filters.keyword.trim() || undefined,
    status: filters.status || undefined,
  }
  query.workshop = filters.workshop || undefined
  if (props.kind === 'employees') {
    query.position = filters.position.trim() || undefined
    query.is_supervisor = filters.isSupervisor === '' ? undefined : filters.isSupervisor
  }
  if (props.kind === 'crafts' || props.kind === 'operations') query.craft_type = filters.craftType || undefined
  if (props.kind === 'operations') query.craft = filters.craft || undefined
  return query
}

async function loadList(): Promise<void> {
  const currentSequence = ++requestSequence
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetchWorkshopConfigList(props.kind, buildQuery())
    if (currentSequence !== requestSequence) return
    rows.value = response.data
    total.value = response.meta.total
  } catch (error) {
    if (currentSequence !== requestSequence) return
    rows.value = []
    total.value = 0
    loadError.value = apiErrorMessage(error, `${metadata.value.title}加载失败，请稍后重试。`)
  } finally {
    if (currentSequence === requestSequence) loading.value = false
  }
}

async function loadDependencies(): Promise<void> {
  const tasks: Promise<unknown>[] = [
    fetchWorkshopConfigList<Workshop>('workshops', { page: 1, page_size: 100 }).then((result) => {
      workshops.value = result.data
    }),
  ]
  if (props.kind === 'operations') {
    tasks.push(fetchWorkshopConfigList<Craft>('crafts', { page: 1, page_size: 100 }).then((result) => {
      crafts.value = result.data
    }))
  }
  await Promise.all(tasks)
}

async function reloadAll(): Promise<void> {
  if (!canView.value) return
  try {
    await Promise.all([
      loadList(),
      loadDependencies(),
    ])
  } catch (error) {
    loadError.value = apiErrorMessage(error, `${metadata.value.title}加载失败，请稍后重试。`)
  }
}

function search(): void {
  page.value = 1
  void loadList()
}

function resetFilters(): void {
  filters.keyword = ''
  filters.status = ''
  filters.workshop = ''
  filters.position = ''
  filters.isSupervisor = ''
  filters.craftType = ''
  filters.craft = ''
  search()
}

function resetForm(): void {
  form.name = ''
  form.employee = ''
  editingEmployee.value = null
  form.status = 'ACTIVE'
  form.workshop = ''
  form.position = ''
  form.isSupervisor = false
  form.craftType = 'INTERNAL'
  form.planCategory = null
  form.outsourcingCode = null
  form.craft = ''
  form.productName = ''
  editingId.value = ''
  editingEtag.value = ''
}

function openCreate(): void {
  resetForm()
  editorMode.value = 'create'
  editorVisible.value = true
}

async function openEdit(row: WorkshopConfigRecord): Promise<void> {
  try {
    const detail = await fetchWorkshopConfigDetail(props.kind, row.id)
    const value = detail.data
    resetForm()
    editorMode.value = 'edit'
    editingId.value = value.id
    editingEtag.value = detail.etag
    form.name = value.name
    form.status = value.status
    if (props.kind === 'employees') {
      const employee = value as WorkshopEmployee
      editingEmployee.value = employee
      form.employee = employee.employee || ''
      form.workshop = employee.workshop || ''
      form.position = employee.position
      form.isSupervisor = employee.is_supervisor
    } else if (props.kind === 'crafts') {
      const craft = value as Craft
      form.craftType = craft.craft_type
      form.planCategory = craft.plan_category
      form.outsourcingCode = craft.outsourcing_code
      form.workshop = craft.workshop || ''
    } else if (props.kind === 'operations') {
      const operation = value as Operation
      form.productName = operation.product_name
      form.craft = operation.craft
    }
    editorVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '配置详情加载失败，请刷新后重试。'))
  }
}

function validateForm(): string {
  if (props.kind === 'employees') {
    if (!form.workshop) return '请选择车间。'
    if (!form.position.trim()) return '请输入岗位。'
  }
  if (props.kind === 'crafts') {
    if (!form.name.trim()) return '请输入工艺名称。'
    if (form.craftType === 'INTERNAL' && !form.workshop) return '厂内工艺必须选择车间。'
    if (form.planCategory === 'METAL' && workshops.value.find(item => item.id === form.workshop)?.name !== '金工车间') return '金工计划只能映射金工车间的工艺。'
  }
  if (props.kind === 'operations') {
    if (!form.craft) return '请选择工艺。'
    if (!isMetalCraft(selectedFormCraft.value) && !form.productName.trim()) return '请输入品名。'
    if (!form.name.trim()) return '请输入工序名称。'
  }
  return ''
}

function buildPayload(): WorkshopConfigInput {
  if (props.kind === 'employees') {
    return {
      workshop: form.workshop,
      position: form.position.trim(),

      is_supervisor: form.isSupervisor,
      status: form.status as WorkshopEmployeeStatus,
    }
  }
  if (props.kind === 'crafts') {
    return {
      craft_type: form.craftType,
      plan_category: form.craftType === 'INTERNAL' ? form.planCategory : null,
      outsourcing_code: form.craftType === 'EXTERNAL' ? form.outsourcingCode : null,
      workshop: form.craftType === 'INTERNAL' ? form.workshop : null,
      name: form.name.trim(),
      status: form.status as RecordStatus,
    }
  }
  return {
    product_name: isMetalCraft(selectedFormCraft.value) ? '' : form.productName.trim(),
    craft: form.craft,
    name: form.name.trim(),
    status: form.status as RecordStatus,
  }
}

async function save(): Promise<void> {
  const message = validateForm()
  if (message) {
    ElMessage.warning(message)
    return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    if (editorMode.value === 'create') await createWorkshopConfig(props.kind, payload)
    else await updateWorkshopConfig(props.kind, editingId.value, payload, editingEtag.value)
    editorVisible.value = false
    ElMessage.success(editorMode.value === 'create' ? '新增成功。' : '保存成功。')
    emit('saved')
    await reloadAll()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '保存失败，请检查填写内容后重试。'))
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: WorkshopConfigRecord): Promise<void> {
  const active = row.status === 'ACTIVE'
  const nextStatus = props.kind === 'employees'
    ? (active ? 'LEFT' : 'ACTIVE')
    : (active ? 'INACTIVE' : 'ACTIVE')
  const actionLabel = props.kind === 'employees'
    ? (active ? '结束车间任职' : '恢复车间任职')
    : (active ? '停用' : '启用')
  const name = props.kind === 'employees' ? employeeLabel(row as WorkshopEmployee) : row.name
  let note = `确认${actionLabel}“${name}”吗？`
  if (props.kind === 'employees') note += ' 仅修改车间任职状态，不修改统一员工状态。'
  if (active && props.kind === 'crafts') note += ' 若仍有启用工序，系统会阻止操作。'
  try {
    await ElMessageBox.confirm(note, `${actionLabel}确认`, { type: active ? 'warning' : 'info' })
    const detail = await fetchWorkshopConfigDetail(props.kind, row.id)
    await updateWorkshopConfig(props.kind, row.id, { status: nextStatus } as Partial<WorkshopConfigInput>, detail.etag)
    ElMessage.success(`${actionLabel}成功。`)
    await reloadAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, `${actionLabel}失败，请稍后重试。`))
  }
}

function handleRowAction(command: unknown, row: WorkshopConfigRecord): void {
  const action = String(command)
  if (action === 'edit') void openEdit(row)
  if (action === 'toggle') void toggleStatus(row)
  if (action === 'delete' && props.kind === 'employees') void removeEmployee(row as WorkshopEmployee)
}

async function removeEmployee(row: WorkshopEmployee): Promise<void> {
  if (!canChange.value || saving.value) return
  try {
    const detail = await fetchWorkshopConfigDetail('employees', row.id)
    await ElMessageBox.confirm(`清除“${employeeLabel(row)}”的车间和岗位安排？`, '清除车间安排', { type: 'warning' })
    saving.value = true
    await deleteWorkshopEmployee(row.id, detail.etag)
    ElMessage.success('已清除车间和岗位安排。')
    await reloadAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '删除失败，请刷新后重试。'))
  } finally {
    saving.value = false
  }
}

function beforeEditorClose(done: () => void): void {
  if (!saving.value) done()
}

function craftTypeChanged(value: CraftType): void {
  if (value === 'EXTERNAL') {
    form.workshop = ''
    form.planCategory = null
  } else {
    form.outsourcingCode = null
  }
}

onMounted(() => { void reloadAll() })
</script>

<template>
  <section class="manager" :data-testid="`workshop-manager-${kind}`">
    <div v-if="!canView" class="manager-state">
      <h2>无权查看{{ metadata.title }}</h2>
      <p>请联系管理员开通对应的模型查看权限。</p>
    </div>

    <template v-else>
      <ElAlert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="load-error" />

      <div class="filter-panel">
        <div class="field field--search">
          <ElInput v-model="filters.keyword" clearable :prefix-icon="Search" :placeholder="metadata.search" aria-label="关键词" @keyup.enter="search" />
        </div>
        <div class="field">
          <ElSelect v-model="filters.workshop" clearable placeholder="全部车间" aria-label="车间" @change="search">
            <ElOption v-for="item in workshops" :key="item.id" :label="item.name" :value="item.id" />
          </ElSelect>
        </div>
        <div v-if="kind === 'employees'" class="field">
          <ElInput v-model="filters.position" clearable placeholder="全部岗位" aria-label="岗位" />
        </div>
        <div v-if="kind === 'employees'" class="field field--small">
          <ElSelect v-model="filters.isSupervisor" clearable placeholder="是否主管" aria-label="是否主管" @change="search">
            <ElOption label="是" :value="true" /><ElOption label="否" :value="false" />
          </ElSelect>
        </div>
        <div v-if="kind === 'crafts' || kind === 'operations'" class="field field--small">
          <ElSelect v-model="filters.craftType" clearable placeholder="全部类型" aria-label="类型" @change="search">
            <ElOption label="厂内" value="INTERNAL" /><ElOption label="厂外" value="EXTERNAL" />
          </ElSelect>
        </div>
        <div v-if="kind === 'operations'" class="field">
          <ElSelect v-model="filters.craft" clearable filterable placeholder="全部工艺" aria-label="工艺" @change="search">
            <ElOption v-for="item in crafts" :key="item.id" :label="item.name" :value="item.id" />
          </ElSelect>
        </div>
        <div class="field field--small">
          <ElSelect v-model="filters.status" clearable placeholder="全部状态" :aria-label="kind === 'employees' ? '车间任职状态' : '状态'" @change="search">
            <ElOption :label="kind === 'employees' ? '任职中' : '启用'" value="ACTIVE" />
            <ElOption :label="kind === 'employees' ? '已离岗' : '停用'" :value="kind === 'employees' ? 'LEFT' : 'INACTIVE'" />
          </ElSelect>
        </div>
        <div class="filter-actions">
          <ElButton type="primary" @click="search">查询</ElButton>
          <ElButton @click="resetFilters">重置</ElButton>
          <ElButton :icon="Refresh" aria-label="刷新" @click="reloadAll">刷新</ElButton>
        </div>
        <ElButton v-if="canAdd" class="filter-create" type="primary" :icon="Plus" @click="openCreate">{{ metadata.createLabel }}</ElButton>
      </div>

      <div class="table-card">
        <div class="table-region">
        <ElTable v-if="kind === 'employees'" v-loading="loading" :data="employeeRows" row-key="id" height="100%">
          <ElTableColumn prop="workshop_name" label="车间" min-width="180" fixed />
          <ElTableColumn prop="position" label="岗位" min-width="180" />
          <ElTableColumn label="姓名" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ employeeLabel(row) }}</template></ElTableColumn>
          <ElTableColumn prop="department" label="部门" min-width="160" show-overflow-tooltip />
          <ElTableColumn prop="roles" label="角色" min-width="180" show-overflow-tooltip />
          <ElTableColumn label="是否为主管" width="130"><template #default="{ row }"><ElTag :type="row.is_supervisor ? 'success' : 'info'" effect="dark">{{ row.is_supervisor ? '是' : '否' }}</ElTag></template></ElTableColumn>
          <ElTableColumn label="车间任职" width="110"><template #default="{ row }"><ElTag :type="!row.workshop ? 'info' : row.status === 'ACTIVE' ? 'success' : 'warning'" effect="dark">{{ !row.workshop ? '未安排' : row.status === 'ACTIVE' ? '任职中' : '已离岗' }}</ElTag></template></ElTableColumn>
          <ElTableColumn label="更新时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template></ElTableColumn>
          <ElTableColumn v-if="canChange" label="操作" width="80" fixed="right"><template #default="{ row }"><ElDropdown trigger="click" @command="handleRowAction($event, row)"><ElButton text circle :icon="MoreFilled" aria-label="更多操作" class="row-action-trigger" /><template #dropdown><ElDropdownMenu><ElDropdownItem command="edit">编辑</ElDropdownItem><ElDropdownItem command="toggle" :disabled="!row.workshop">{{ row.status === 'ACTIVE' ? '结束车间任职' : '恢复车间任职' }}</ElDropdownItem><ElDropdownItem command="delete" divided :disabled="saving || !row.workshop">清除安排</ElDropdownItem></ElDropdownMenu></template></ElDropdown></template></ElTableColumn>
          <template #empty><ElEmpty description="暂无生产部员工" /></template>
        </ElTable>

        <ElTable v-else-if="kind === 'crafts'" v-loading="loading" :data="craftRows" row-key="id" height="100%">
          <ElTableColumn prop="craft_type_display" label="类型" width="110" fixed />
          <ElTableColumn label="计划分类" width="110"><template #default="{ row }">{{ row.plan_category_display || '—' }}</template></ElTableColumn>
          <ElTableColumn label="委外分类" width="110"><template #default="{ row }">{{ row.outsourcing_code_display || '—' }}</template></ElTableColumn>
          <ElTableColumn label="车间" min-width="180"><template #default="{ row }">{{ row.workshop_name || '—' }}</template></ElTableColumn>
          <ElTableColumn prop="name" label="工艺名称" min-width="240" />
          <ElTableColumn label="状态" width="100"><template #default="{ row }"><ElTag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="dark">{{ row.status_display }}</ElTag></template></ElTableColumn>
          <ElTableColumn prop="operation_count" label="工序数" width="110" />
          <ElTableColumn label="更新时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template></ElTableColumn>
          <ElTableColumn v-if="canChange" label="操作" width="80" fixed="right"><template #default="{ row }"><ElDropdown trigger="click" @command="handleRowAction($event, row)"><ElButton text circle :icon="MoreFilled" aria-label="更多操作" class="row-action-trigger" /><template #dropdown><ElDropdownMenu><ElDropdownItem command="edit">编辑</ElDropdownItem><ElDropdownItem command="toggle">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</ElDropdownItem></ElDropdownMenu></template></ElDropdown></template></ElTableColumn>
          <template #empty><ElEmpty description="暂无工艺资料" /></template>
        </ElTable>

        <ElTable v-else v-loading="loading" :data="operationRows" row-key="id" height="100%">
          <ElTableColumn prop="product_name" label="品名" min-width="210" show-overflow-tooltip />
          <ElTableColumn prop="craft_name" label="工艺" min-width="160" />
          <ElTableColumn prop="craft_type_display" label="类型" width="90" />
          <ElTableColumn label="车间" min-width="150"><template #default="{ row }">{{ row.workshop_name || '—' }}</template></ElTableColumn>
          <ElTableColumn prop="name" label="工序名称" min-width="210" show-overflow-tooltip />
          <ElTableColumn label="状态" width="90"><template #default="{ row }"><ElTag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="dark">{{ row.status_display }}</ElTag></template></ElTableColumn>
          <ElTableColumn label="更新时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template></ElTableColumn>
          <ElTableColumn v-if="canChange" label="操作" width="80" fixed="right"><template #default="{ row }"><ElDropdown trigger="click" @command="handleRowAction($event, row)"><ElButton text circle :icon="MoreFilled" aria-label="更多操作" class="row-action-trigger" /><template #dropdown><ElDropdownMenu><ElDropdownItem command="edit">编辑</ElDropdownItem><ElDropdownItem command="toggle">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</ElDropdownItem></ElDropdownMenu></template></ElDropdown></template></ElTableColumn>
          <template #empty><ElEmpty description="暂无工序资料" /></template>
        </ElTable>
        </div>

        <footer v-if="total > 0" class="pagination-bar"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @current-change="loadList" @size-change="page = 1; loadList()" /></footer>
      </div>
    </template>

    <AppWindowDialog v-model="editorVisible" :title="`${editorMode === 'create' ? '新增' : '编辑'}${metadata.title.replace('管理', '')}`" :width="900" :height="editorHeight" destroy-on-close class="workshop-editor-dialog" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :before-close="beforeEditorClose">
      <ElForm label-position="top" class="editor-form">
        <template v-if="kind === 'employees'">
          <ElFormItem label="车间" required><ElSelect v-model="form.workshop" filterable placeholder="请选择车间"><ElOption v-for="item in workshops" :key="item.id" :label="item.name" :value="item.id" :disabled="item.status !== 'ACTIVE'" /></ElSelect></ElFormItem>
          <ElFormItem label="岗位" required><ElInput v-model="form.position" maxlength="100" placeholder="请输入岗位" /></ElFormItem>
          <ElFormItem label="员工"><span>{{ editingEmployee ? employeeLabel(editingEmployee) : '' }}</span></ElFormItem>
          <ElFormItem label="是否为主管" required><ElSelect v-model="form.isSupervisor"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect></ElFormItem>
          <ElFormItem label="车间任职状态" required><ElSelect v-model="form.status"><ElOption label="任职中" value="ACTIVE"  /><ElOption label="已离岗" value="LEFT" /></ElSelect></ElFormItem>
          <ElAlert title="主管为必选“是/否”，同一车间允许多名主管；状态变化不会覆盖主管值。此处状态仅表示车间任职，不修改统一员工状态。" type="success" :closable="false" />
        </template>
        <template v-else-if="kind === 'crafts'">
          <ElFormItem label="类型" required><ElSelect v-model="form.craftType" @change="craftTypeChanged"><ElOption label="厂内" value="INTERNAL" /><ElOption label="厂外" value="EXTERNAL" /></ElSelect></ElFormItem>
          <ElFormItem label="车间" :required="form.craftType === 'INTERNAL'"><ElSelect v-model="form.workshop" :disabled="form.craftType === 'EXTERNAL'" clearable filterable :placeholder="form.craftType === 'EXTERNAL' ? '厂外工艺无需填写' : '请选择车间'"><ElOption v-for="item in workshops" :key="item.id" :label="item.name" :value="item.id" :disabled="item.status !== 'ACTIVE'" /></ElSelect></ElFormItem>
          <ElFormItem label="计划分类"><ElSelect v-model="form.planCategory" :disabled="form.craftType === 'EXTERNAL'" clearable placeholder="可选，用于归入四类计划"><ElOption label="金工计划" value="METAL" /><ElOption label="裁剪计划" value="CUTTING" /><ElOption label="车缝计划" value="SEWING" /><ElOption label="装配计划" value="ASSEMBLY" /></ElSelect></ElFormItem>
          <ElFormItem label="委外分类"><ElSelect v-model="form.outsourcingCode" :disabled="form.craftType === 'INTERNAL'" clearable placeholder="核对真实工艺后选择"><ElOption label="喷塑" value="POWDER_COATING" /><ElOption label="丝印" value="SCREEN_PRINTING" /><ElOption label="刺绣" value="EMBROIDERY" /><ElOption label="裁剪" value="CUTTING" /><ElOption label="车缝" value="SEWING" /></ElSelect></ElFormItem>
          <ElFormItem label="工艺名称" required><ElInput v-model="form.name" maxlength="100" placeholder="请输入工艺名称" /></ElFormItem>
          <ElFormItem label="状态" required><ElSelect v-model="form.status"><ElOption label="启用" value="ACTIVE" /><ElOption label="停用" value="INACTIVE" /></ElSelect></ElFormItem>
          <ElAlert title="厂内必须选择车间，计划分类用于归入金工、裁剪、车缝或装配计划；厂外工艺不参与四类计划。" type="warning" :closable="false" />
        </template>
        <template v-else>
          <ElFormItem label="工艺" required><ElSelect v-model="form.craft" filterable placeholder="请选择工艺"><ElOption v-for="item in crafts" :key="item.id" :label="`${item.name}（${item.craft_type_display}）`" :value="item.id" :disabled="item.status !== 'ACTIVE'" /></ElSelect></ElFormItem>
          <ElFormItem v-if="!isMetalCraft(selectedFormCraft)" label="品名" required><ElInput v-model="form.productName" maxlength="200" placeholder="本期使用独立文本" /></ElFormItem>
          <ElFormItem label="类型（自动）"><ElInput :model-value="selectedFormCraft?.craft_type_display || ''" disabled /></ElFormItem>
          <ElFormItem label="车间（自动）"><ElInput :model-value="selectedFormCraft?.workshop_name || '—'" disabled /></ElFormItem>
          <ElFormItem label="工序名称" required><ElInput v-model="form.name" maxlength="150" placeholder="请输入工序名称" /></ElFormItem>
          <ElFormItem label="状态" required><ElSelect v-model="form.status"><ElOption label="启用" value="ACTIVE" /><ElOption label="停用" value="INACTIVE" /></ElSelect></ElFormItem>
        </template>
      </ElForm>
      <template #footer><ElButton :disabled="saving" @click="editorVisible = false">取消</ElButton><ElButton type="primary" :loading="saving" @click="save">保存</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.manager {
  box-sizing: border-box;
  display: flex;
  min-width: 0;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  padding: 14px;
  overflow: hidden;
  color: token.$crm-text-primary;
  background: token.$crm-color-page;
  font-family: token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary};
  --el-border-color: #{token.$crm-border-default};
  --el-fill-color-blank: #{token.$crm-color-surface};
  --el-text-color-primary: #{token.$crm-text-primary};
  --el-text-color-regular: #{token.$crm-text-regular};
}

.filter-panel {
  display: flex;
  min-height: 0;
  flex: none;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  overflow-x: auto;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
}
.field { width: 142px; min-width: 100px; }
.field--search { width: 300px; min-width: 200px; }
.field--small { width: 130px; min-width: 96px; }
.field :deep(.el-select), .field :deep(.el-input) { width: 100%; }
.filter-actions { display: flex; flex: none; gap: 8px; }
.filter-actions :deep(.el-button + .el-button) { margin-left: 0; }
.filter-create { min-width: 140px; flex: none; margin-left: auto; }

.manager :deep(.el-button),
.manager :deep(.el-input:not(.el-textarea) .el-input__wrapper),
.manager :deep(.el-select__wrapper),
.manager :deep(.el-input-number),
.manager :deep(.el-input-number .el-input__wrapper) {
  box-sizing: border-box;
  height: 32px !important;
  min-height: 32px !important;
  border-radius: token.$crm-radius-2;
}
.manager :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); color: var(--erp-color-text-inverse); background: var(--erp-button-primary-surface); }
.manager :deep(.el-button--primary:hover) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-hover-surface); }
.manager :deep(.el-input:not(.el-textarea) .el-input__wrapper),
.manager :deep(.el-select__wrapper),
.manager :deep(.el-input-number),
.manager :deep(.el-input-number .el-input__wrapper) {
  border-radius: var(--erp-radius-control);
  background: var(--erp-input-surface);
  box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset;
}
.manager :deep(.el-input:not(.el-textarea) .el-input__wrapper.is-focus),
.manager :deep(.el-select__wrapper.is-focused),
.manager :deep(.el-input-number .el-input__wrapper.is-focus) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.manager :deep(.el-input.is-disabled .el-input__wrapper),
.manager :deep(.el-select__wrapper.is-disabled) { background: var(--erp-input-disabled-background); }

.load-error { flex: none; margin: 0 0 10px; }
.table-card { display: flex; min-height: 0; flex: 1; flex-direction: column; margin-top: 14px; overflow: hidden; border: 1px solid token.$crm-border-default; border-radius: token.$crm-radius-2; background: token.$crm-color-surface; }
.table-region { min-height: 0; flex: 1; }
.table-region > :deep(.el-table) { height: 100%; }
.table-card :deep(.el-table) { --el-table-border-color: var(--erp-table-grid); --el-table-header-bg-color: var(--erp-table-header-fill); --el-table-tr-bg-color: var(--erp-table-body-fill); --el-table-row-hover-bg-color: var(--erp-color-hover); color: var(--erp-table-text); font-size: 12px; }
.table-card :deep(.el-table__header-wrapper th.el-table__cell) { height: 44px; padding: 0; color: var(--erp-table-header-text); background: var(--erp-table-header-fill); font-size: 11px; line-height: 16px; }
.table-card :deep(.el-table__body-wrapper td.el-table__cell) { height: 40px; padding: 0; }
.table-card :deep(.cell) { padding-right: 16px; padding-left: 16px; line-height: 18px; }
.table-card :deep(.el-tag) { min-width: 56px; height: 24px; padding: 0 8px; border: 0; border-radius: token.$crm-radius-pill; color: var(--erp-color-text-inverse); font-size: 12px; font-weight: 500; line-height: 24px; }
.table-card :deep(.el-tag--success) { background: var(--erp-tag-success-background); }
.table-card :deep(.el-tag--warning) { background: var(--erp-tag-warning-background); }
.table-card :deep(.el-tag--info) { background: var(--erp-tag-neutral-background); }
.row-action-trigger { width: 32px !important; padding: 0 !important; color: token.$crm-text-secondary; }
.pagination-bar { box-sizing: border-box; display: flex; height: 48px; flex: none; align-items: center; justify-content: space-between; padding: 8px 12px 8px 16px; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; font-size: 12px; }
.pagination-bar :deep(.el-pagination) { height: 32px; margin: 0; }
.pagination-bar :deep(.el-pagination button), .pagination-bar :deep(.el-pager li), .pagination-bar :deep(.el-select__wrapper) { min-height: 32px; }

.manager-state { display: grid; height: 100%; place-content: center; text-align: center; }
.manager-state h2 { margin: 0 0 8px; font-family: token.$crm-font-display; }
.manager-state p { margin: 0; color: token.$crm-text-muted; }
.editor-form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 16px; }
.employee-identity-note, .employee-identity-error { display: block; width: 100%; margin-top: 6px; line-height: 1.5; overflow-wrap: anywhere; }
.employee-identity-note { color: var(--el-text-color-secondary); }
.employee-identity-error { color: var(--el-color-danger); }
.editor-form :deep(.el-select), .editor-form :deep(.el-input-number) { width: 100%; }
.editor-form :deep(.el-alert) { grid-column: 1 / -1; border-radius: token.$crm-radius-2; }
.editor-form :deep(.el-textarea__inner) { border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.editor-form :deep(.el-textarea__inner:focus) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }

:global(.workshop-editor-dialog .editor-form .el-input:not(.el-textarea) .el-input__wrapper),
:global(.workshop-editor-dialog .editor-form .el-select__wrapper),
:global(.workshop-editor-dialog .editor-form .el-input-number),
:global(.workshop-editor-dialog .editor-form .el-input-number .el-input__wrapper) {
  box-sizing: border-box;
  height: 32px !important;
  min-height: 32px !important;
}

@media (max-width: 900px) {
  .editor-form { grid-template-columns: 1fr; }
}
</style>
