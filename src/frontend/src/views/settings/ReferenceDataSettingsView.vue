<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, reactive, ref } from 'vue'
import { AxiosError } from 'axios'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import {
  Delete,
  Download,
  Lock,
  Plus,
  Refresh,
  Search,
  Setting,
  Sort,
  Warning,
} from '@element-plus/icons-vue'

import {
  archiveDictionaryItem,
  changeDictionaryItemStatus,
  createDictionaryItem,
  fetchConfigRelease,
  fetchConfigReleases,
  fetchDictionaryItem,
  fetchDictionaryItems,
  fetchDictionaryType,
  fetchDictionaryTypes,
  fetchReferenceDataSummary,
  fetchSystemParameter,
  fetchSystemParameters,
  publishReferenceData,
  updateDictionaryItem,
  updateDictionaryType,
  updateSystemParameter,
} from '@/api/referenceData'
import { useAuthStore } from '@/stores/auth'
import { useReferenceOptionsStore } from '@/stores/referenceOptions'
import type {
  ConfigRelease,
  DictionaryItem,
  DictionaryItemInput,
  DictionaryType,
  ReferenceDataApiError,
  ReferenceDataSummary,
  ReferenceStatus,
  SystemParameter,
} from '@/types/referenceData'

interface CategoryDefinition {
  key: string
  label: string
  groups: string[]
}

interface SortRow {
  id: string
  name: string
  original: number
  sortOrder: number
}

const props = withDefaults(defineProps<{
  section?: 'all' | 'dictionary' | 'parameters'
}>(), { section: 'all' })

const authStore = useAuthStore()
const referenceOptionsStore = useReferenceOptionsStore()

const permissions = {
  viewType: 'reference_data.view_dictionarytype',
  changeType: 'reference_data.change_dictionarytype',
  viewItem: 'reference_data.view_referencedictionary',
  addItem: 'reference_data.add_referencedictionary',
  changeItem: 'reference_data.change_referencedictionary',
  viewParameter: 'reference_data.view_systemparameterdefinition',
  changeParameter: 'reference_data.change_systemparameterdefinition',
  viewRelease: 'reference_data.view_configrelease',
  publishRelease: 'reference_data.publish_configrelease',
}

const categories: CategoryDefinition[] = [
  { key: 'CUSTOMER_CONTACT', label: '客户与联系人', groups: ['CUSTOMER', 'CONTACT'] },
  { key: 'INQUIRY', label: '询盘与来源', groups: ['INQUIRY'] },
  { key: 'QUOTATION_SAMPLE', label: '报价与样品', groups: ['QUOTATION', 'SAMPLE'] },
  { key: 'ORDER', label: '订单协同', groups: ['ORDER'] },
  { key: 'COMPLAINT', label: '客诉与风险', groups: ['COMPLAINT'] },
  { key: 'AUTOMATION', label: '自动化提醒', groups: ['AUTOMATION'] },
]

const loading = ref(false)
const loadError = ref('')
const permissionDenied = ref(false)
const dictionaryTypes = ref<DictionaryType[]>([])
const systemParameters = ref<SystemParameter[]>([])
const configReleases = ref<ConfigRelease[]>([])
const summary = ref<ReferenceDataSummary>({
  active_dictionary_items: 0,
  active_system_parameters: 0,
  pending_changes: 0,
  config_version: null,
})
const selectedCategoryKey = ref(categories[0].key)
const keyword = ref('')
const statusFilter = ref<ReferenceStatus | ''>('')
const appliedKeyword = ref('')
const appliedStatus = ref<ReferenceStatus | ''>('')

function applyFilters(): void {
  appliedKeyword.value = keyword.value
  appliedStatus.value = statusFilter.value
}

function resetFilters(): void {
  keyword.value = ''
  statusFilter.value = ''
  applyFilters()
}

const isSuperuser = computed(() => authStore.user?.is_superuser === true)
function can(permission: string): boolean {
  return isSuperuser.value || authStore.hasPermission(permission)
}

const canViewPage = computed(() => {
  if (props.section === 'parameters') return can(permissions.viewParameter)
  if (props.section === 'dictionary') return [permissions.viewType, permissions.viewItem].some(can)
  return [permissions.viewType, permissions.viewItem, permissions.viewParameter].some(can)
})
const pageTitle = computed(() => props.section === 'parameters' ? '业务参数' : props.section === 'dictionary' ? '字典配置' : '字典与业务参数')
const canViewMasterData = computed(() => [
  'reference_data.view_country',
  'reference_data.view_currency',
  'reference_data.view_exchangerate',
  'reference_data.view_unit',
  'reference_data.view_incoterm',
  'reference_data.view_paymentmethod',
  'reference_data.view_transportmethod',
  'reference_data.view_port',
  'reference_data.view_courier',
].some(can))
const canViewProductionData = computed(() => [
  'reference_data.view_productcategory',
  'reference_data.view_productionunit',
  'reference_data.view_productcolor',
  'reference_data.view_productitem',
  'reference_data.view_fabricmaterial',
  'reference_data.view_fabricspecification',
  'reference_data.view_fabricwidth',
].some(can))
const selectedCategory = computed(() => categories.find((item) => item.key === selectedCategoryKey.value) ?? categories[0])
const visibleDictionaryTypes = computed(() => {
  const query = appliedKeyword.value.trim().toLocaleLowerCase()
  return dictionaryTypes.value.filter((item) => {
    const inCategory = selectedCategory.value.groups.includes(item.group_code)
    const matchesStatus = !appliedStatus.value || item.status === appliedStatus.value
    const matchesQuery = !query || [item.code, item.chinese_name, item.english_name]
      .some((value) => value.toLocaleLowerCase().includes(query))
    return inCategory && matchesStatus && matchesQuery
  })
})
const latestRelease = computed(() => configReleases.value[0] ?? null)

function categoryCount(category: CategoryDefinition): number {
  return dictionaryTypes.value.filter((item) => category.groups.includes(item.group_code)).length
}

function statusCode(error: unknown): number | undefined {
  return error instanceof AxiosError ? error.response?.status : undefined
}

function apiMessage(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) return fallback
  const payload = error.response?.data as ReferenceDataApiError | undefined
  return payload?.error?.message || fallback
}

async function loadPage(): Promise<void> {
  if (!canViewPage.value) return
  loading.value = true
  loadError.value = ''
  try {
    const tasks: Promise<void>[] = []
    if (can(permissions.viewType)) {
      tasks.push(fetchDictionaryTypes().then((response) => { dictionaryTypes.value = response.data }))
      tasks.push(fetchReferenceDataSummary().then((response) => { summary.value = response }))
    }
    if (can(permissions.viewParameter)) {
      tasks.push(fetchSystemParameters().then((response) => { systemParameters.value = response.data }))
    }
    if (can(permissions.viewRelease)) {
      tasks.push(fetchConfigReleases().then((response) => { configReleases.value = response.data }))
    }
    await Promise.all(tasks)
  } catch (error) {
    if (statusCode(error) === 403) permissionDenied.value = true
    else loadError.value = apiMessage(error, '配置数据加载失败，请检查网络后重试。')
  } finally {
    loading.value = false
  }
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function formatParameterValue(parameter: SystemParameter): string {
  const value = parameter.draft_value ?? parameter.default_value
  if (value === null || value === undefined || value === '') return '未配置'
  if (parameter.value_type === 'BOOLEAN') return value ? '开启' : '关闭'
  if (parameter.code === 'DEFAULT_QUOTATION_VALIDITY_DAYS') return `${value} 天`
  return String(value)
}

async function exportConfiguration(): Promise<void> {
  try {
    const items = can(permissions.viewItem) ? (await fetchDictionaryItems({ page_size: 100 })).data : []
    const content = {
      exported_at: new Date().toISOString(),
      config_version: summary.value.config_version,
      dictionary_types: dictionaryTypes.value,
      dictionary_items: items,
      system_parameters: systemParameters.value,
    }
    const blob = new Blob([JSON.stringify(content, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `reference-data-v${summary.value.config_version ?? 0}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('配置已导出')
  } catch (error) {
    ElMessage.error(apiMessage(error, '配置导出失败'))
  }
}

const typeDialogVisible = ref(false)
const typeSaving = ref(false)
const typeEtag = ref('')
const typeFormRef = ref<FormInstance>()
const typeForm = reactive({
  id: '', code: '', chinese_name: '', english_name: '', group_code: '', sort_order: 0, description: '',
})
const typeRules: FormRules = {
  chinese_name: [{ required: true, message: '请输入中文名称', trigger: 'blur' }],
  english_name: [{ required: true, message: '请输入英文名称', trigger: 'blur' }],
  group_code: [{ required: true, message: '请输入配置分组', trigger: 'blur' }],
}

async function openTypeEditor(row: DictionaryType): Promise<void> {
  if (!can(permissions.changeType)) return
  try {
    const response = await fetchDictionaryType(row.id)
    Object.assign(typeForm, response.data)
    typeEtag.value = response.etag
    typeDialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '字典类型加载失败'))
  }
}

async function saveType(): Promise<void> {
  if (!await typeFormRef.value?.validate()) return
  typeSaving.value = true
  try {
    await updateDictionaryType(typeForm.id, {
      chinese_name: typeForm.chinese_name.trim(),
      english_name: typeForm.english_name.trim(),
      group_code: typeForm.group_code.trim().toUpperCase(),
      sort_order: typeForm.sort_order,
      description: typeForm.description.trim(),
    }, typeEtag.value)
    typeDialogVisible.value = false
    ElMessage.success('字典类型已保存为待发布变更')
    await loadPage()
  } catch (error) {
    await handleWriteError(error, '字典类型保存失败')
  } finally {
    typeSaving.value = false
  }
}

const itemDrawerVisible = ref(false)
const itemLoading = ref(false)
const managedType = ref<DictionaryType | null>(null)
const itemRows = ref<DictionaryItem[]>([])
const itemDialogVisible = ref(false)
const itemSaving = ref(false)
const itemActionPending = ref(false)
const itemEditing = ref(false)
const itemEtag = ref('')
const itemFormRef = ref<FormInstance>()
const itemForm = reactive<DictionaryItemInput & { id: string }>({
  id: '', dictionary_type: '', item_code: '', display_name: '', english_name: '', description: '',
  sort_order: 0, color: '', extra_data: {},
})
const itemRules: FormRules = {
  dictionary_type: [{ required: true, message: '请选择字典类型', trigger: 'change' }],
  item_code: [
    { required: true, message: '请输入稳定编码', trigger: 'blur' },
    { pattern: /^[A-Z0-9_\-]+$/, message: '编码只能使用大写字母、数字、下划线或短横线', trigger: 'blur' },
  ],
  display_name: [{ required: true, message: '请输入中文名称', trigger: 'blur' }],
}

async function loadManagedItems(): Promise<void> {
  if (!managedType.value) return
  itemLoading.value = true
  try {
    itemRows.value = (await fetchDictionaryItems({ type_code: managedType.value.code, page_size: 100 })).data
  } catch (error) {
    ElMessage.error(apiMessage(error, '字典项加载失败'))
  } finally {
    itemLoading.value = false
  }
}

async function openItemManager(row: DictionaryType): Promise<void> {
  managedType.value = row
  itemDrawerVisible.value = true
  await loadManagedItems()
}

function resetItemForm(typeId = ''): void {
  Object.assign(itemForm, {
    id: '', dictionary_type: typeId, item_code: '', display_name: '', english_name: '',
    description: '', sort_order: 0, color: '', extra_data: {},
  })
  itemEtag.value = ''
}

function openCreateItem(type?: DictionaryType): void {
  resetItemForm(type?.id ?? managedType.value?.id ?? '')
  itemEditing.value = false
  itemDialogVisible.value = true
}

async function openItemEditor(row: DictionaryItem): Promise<void> {
  try {
    const response = await fetchDictionaryItem(row.id)
    Object.assign(itemForm, response.data)
    itemEtag.value = response.etag
    itemEditing.value = true
    itemDialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '字典项加载失败'))
  }
}

async function saveItem(): Promise<void> {
  if (!await itemFormRef.value?.validate()) return
  itemSaving.value = true
  const payload: DictionaryItemInput = {
    dictionary_type: itemForm.dictionary_type,
    item_code: itemForm.item_code.trim().toUpperCase(),
    display_name: itemForm.display_name.trim(),
    english_name: itemForm.english_name.trim(),
    description: itemForm.description.trim(),
    sort_order: itemForm.sort_order,
    color: itemForm.color.trim(),
    extra_data: itemForm.extra_data,
  }
  try {
    if (itemEditing.value) await updateDictionaryItem(itemForm.id, payload, itemEtag.value)
    else await createDictionaryItem(payload)
    itemDialogVisible.value = false
    ElMessage.success(`字典项已${itemEditing.value ? '保存' : '新增'}，发布后业务页面生效`)
    await Promise.all([loadPage(), managedType.value ? loadManagedItems() : Promise.resolve()])
  } catch (error) {
    await handleWriteError(error, '字典项保存失败')
  } finally {
    itemSaving.value = false
  }
}

function canItemStatus(row: DictionaryItem): boolean {
  return authStore.user?.module_access_enabled
    ? can('access_control.' + (row.status === 'ACTIVE' ? 'deactivate' : 'activate') + '_reference_referencedictionary')
    : can(permissions.changeItem)
}
function canArchiveItem(): boolean {
  return authStore.user?.module_access_enabled ? can('access_control.archive_reference_referencedictionary') : can(permissions.changeItem)
}
async function changeItemStatus(row: DictionaryItem): Promise<void> {
  if (itemActionPending.value) return
  itemActionPending.value = true
  const action = row.status === 'ACTIVE' ? 'deactivate' : 'activate'
  const actionLabel = action === 'deactivate' ? '停用' : '启用'
  try {
    const prompt = await ElMessageBox.prompt(`请输入${actionLabel}原因，变更将在发布后生效。`, `${actionLabel}字典项`, {
      confirmButtonText: actionLabel,
      cancelButtonText: '取消',
      inputValidator: (value) => value.trim().length > 0 || '原因不能为空',
    })
    const detail = await fetchDictionaryItem(row.id)
    try {
      await changeDictionaryItemStatus(row.id, action, detail.etag, prompt.value.trim())
    } catch (error) {
      if (action === 'deactivate' && statusCode(error) === 409) {
        await ElMessageBox.confirm(
          `该字典项仍被 ${row.reference_count} 条业务数据引用。停用后历史数据继续显示，但新建业务不可再选。`,
          '停用引用确认',
          { type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消' },
        )
        const fresh = await fetchDictionaryItem(row.id)
        await changeDictionaryItemStatus(row.id, action, fresh.etag, prompt.value.trim(), true)
      } else throw error
    }
    ElMessage.success(`字典项已${actionLabel}`)
    await Promise.all([loadManagedItems(), loadPage()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    await handleWriteError(error, `${actionLabel}失败`)
  } finally {
    itemActionPending.value = false
  }
}

async function archiveItem(row: DictionaryItem): Promise<void> {
  if (row.reference_count > 0) {
    await ElMessageBox.alert(
      `该字典项仍被 ${row.reference_count} 条业务数据引用，只能停用，不能归档。`,
      '引用中不可删除',
      { type: 'warning', confirmButtonText: '我知道了' },
    )
    return
  }
  if (itemActionPending.value) return
  itemActionPending.value = true
  try {
    const prompt = await ElMessageBox.prompt('归档后该字典项不再出现在管理列表，请填写原因。', '归档字典项', {
      type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '取消',
      inputValidator: (value) => value.trim().length > 0 || '原因不能为空',
    })
    const detail = await fetchDictionaryItem(row.id)
    await archiveDictionaryItem(row.id, detail.etag, prompt.value.trim())
    ElMessage.success('字典项已归档')
    await Promise.all([loadManagedItems(), loadPage()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    await handleWriteError(error, '归档失败')
  } finally {
    itemActionPending.value = false
  }
}

const parameterDrawerVisible = ref(false)
const parameterDialogVisible = ref(false)
const parameterSaving = ref(false)
const parameterEditor = ref<SystemParameter | null>(null)
const parameterEtag = ref('')
const parameterForm = reactive({ stringValue: '', numberValue: null as number | null, booleanValue: false })

async function openParameterEditor(row: SystemParameter): Promise<void> {
  try {
    const response = await fetchSystemParameter(row.id)
    parameterEditor.value = response.data
    parameterEtag.value = response.etag
    const value = response.data.draft_value ?? response.data.default_value
    parameterForm.stringValue = value === null || value === undefined ? '' : String(value)
    parameterForm.numberValue = typeof value === 'number' ? value : value === null || value === undefined ? null : Number(value)
    parameterForm.booleanValue = Boolean(value)
    parameterDialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '业务参数加载失败'))
  }
}

function parameterValueForSave(): unknown {
  const parameter = parameterEditor.value
  if (!parameter) return null
  if (parameter.value_type === 'INTEGER') return parameterForm.numberValue
  if (parameter.value_type === 'BOOLEAN') return parameterForm.booleanValue
  return parameterForm.stringValue.trim() || null
}

async function saveParameter(): Promise<void> {
  const parameter = parameterEditor.value
  if (!parameter) return
  parameterSaving.value = true
  try {
    await updateSystemParameter(parameter.id, parameterValueForSave(), parameterEtag.value)
    parameterDialogVisible.value = false
    ElMessage.success('业务参数已保存为待发布变更')
    await loadPage()
  } catch (error) {
    if (statusCode(error) === 400) {
      await ElMessageBox.alert(apiMessage(error, '参数值不符合风险校验规则，请检查后重试。'), '参数风险校验', {
        type: 'warning', confirmButtonText: '返回修改',
      })
    } else await handleWriteError(error, '业务参数保存失败')
  } finally {
    parameterSaving.value = false
  }
}

const publishDialogVisible = ref(false)
const publishSaving = ref(false)
const releaseEtag = ref('')
const publishNotes = ref('')

async function openPublishDialog(): Promise<void> {
  if (!latestRelease.value) {
    ElMessage.warning('尚未找到可发布的配置基线')
    return
  }
  try {
    const response = await fetchConfigRelease(latestRelease.value.id)
    releaseEtag.value = response.etag
    publishNotes.value = ''
    publishDialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '发布基线加载失败'))
  }
}

async function confirmPublish(): Promise<void> {
  if (!publishNotes.value.trim()) {
    ElMessage.warning('请填写发布说明')
    return
  }
  publishSaving.value = true
  try {
    await publishReferenceData(publishNotes.value.trim(), releaseEtag.value)
    referenceOptionsStore.invalidate()
    publishDialogVisible.value = false
    ElMessage.success('配置发布成功，业务选项版本已更新')
    await loadPage()
  } catch (error) {
    if (statusCode(error) === 412) {
      await ElMessageBox.alert('其他管理员已发布了更新版本，请刷新页面核对差异后重新操作。', '并发发布冲突', {
        type: 'warning', confirmButtonText: '刷新配置',
      })
      await loadPage()
    } else await handleWriteError(error, '配置发布失败')
  } finally {
    publishSaving.value = false
  }
}

const sortDialogVisible = ref(false)
const sortSaving = ref(false)
const sortRows = ref<SortRow[]>([])

function openSortDialog(): void {
  sortRows.value = visibleDictionaryTypes.value.map((item) => ({
    id: item.id, name: item.chinese_name, original: item.sort_order, sortOrder: item.sort_order,
  }))
  sortDialogVisible.value = true
}

async function saveSortOrder(): Promise<void> {
  const changedRows = sortRows.value.filter((row) => row.sortOrder !== row.original)
  if (!changedRows.length) {
    sortDialogVisible.value = false
    return
  }
  sortSaving.value = true
  try {
    for (const row of changedRows) {
      const detail = await fetchDictionaryType(row.id)
      await updateDictionaryType(row.id, {
        chinese_name: detail.data.chinese_name,
        english_name: detail.data.english_name,
        group_code: detail.data.group_code,
        sort_order: row.sortOrder,
        description: detail.data.description,
      }, detail.etag)
    }
    sortDialogVisible.value = false
    ElMessage.success('排序已保存为待发布变更')
    await loadPage()
  } catch (error) {
    await handleWriteError(error, '批量排序保存失败')
  } finally {
    sortSaving.value = false
  }
}

async function handleWriteError(error: unknown, fallback: string): Promise<void> {
  if (statusCode(error) === 412) {
    await ElMessageBox.alert('数据已被其他管理员修改，请刷新后重新操作。', '并发编辑冲突', {
      type: 'warning', confirmButtonText: '刷新配置',
    })
    await loadPage()
    if (itemDrawerVisible.value) await loadManagedItems()
    return
  }
  if (statusCode(error) === 428) {
    ElMessage.error('缺少版本信息，请刷新页面后重试')
    return
  }
  if (statusCode(error) === 403) {
    await ElMessageBox.alert('当前账号没有配置管理权限，请联系管理员授权。', '无配置权限', {
      type: 'warning', confirmButtonText: '我知道了',
    })
    return
  }
  ElMessage.error(apiMessage(error, fallback))
}

function canClose(): boolean {
  if (typeSaving.value || itemSaving.value || itemActionPending.value || parameterSaving.value || publishSaving.value || sortSaving.value) {
    ElMessage.warning('正在处理配置变更，请稍后再关闭。')
    return false
  }
  if (typeDialogVisible.value || itemDialogVisible.value || parameterDialogVisible.value || publishDialogVisible.value || sortDialogVisible.value) {
    ElMessage.warning('请先保存或取消当前编辑，再关闭配置窗口。')
    return false
  }
  return true
}

defineExpose({ canClose })

onMounted(loadPage)
</script>

<template>
  <section class="reference-settings system-settings-theme erp-glass-list" data-testid="reference-settings-page">
    <div v-if="!canViewPage || permissionDenied" class="state-page">
      <div class="state-page__icon state-page__icon--locked"><el-icon><Lock /></el-icon></div>
      <h1>无配置权限</h1>
      <p>当前账号无法查看或维护系统配置，请联系管理员申请相应权限。</p>
    </div>

    <template v-else>
      <section v-if="section !== 'parameters'" v-glass-spotlight class="erp-list-filter">
      <header class="page-heading erp-list-heading">
        <div>
          <h1>{{ pageTitle }}</h1>
        </div>

      </header>
          <div v-if="!loading && !loadError" class="filter-card erp-list-filters">
            <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索字典编码、中英文名称" @input="applyFilters" @clear="applyFilters" @keyup.enter="applyFilters" />
            <el-select v-model="statusFilter" class="status-filter" placeholder="全部状态" @change="applyFilters">
              <el-option label="全部状态" value="" />
              <el-option label="启用" value="ACTIVE" />
              <el-option label="停用" value="INACTIVE" />
            </el-select>
            <span class="filter-card__version">当前版本 v{{ summary.config_version ?? 0 }}</span>
            <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button class="erp-button-motion" type="primary" @click="applyFilters">应用筛选</el-button></div>
          </div>

      </section>

      <div v-if="loadError" class="state-page state-page--compact">
        <div class="state-page__icon"><el-icon><Warning /></el-icon></div>
        <h2>配置加载失败</h2>
        <p>{{ loadError }}</p>
        <el-button type="primary" :icon="Refresh" @click="loadPage">重新加载</el-button>
      </div>

      <el-skeleton v-else-if="loading" :rows="10" animated class="loading-card" />

      <section v-else-if="section === 'parameters'" class="parameter-card card-shell erp-list-data" data-testid="parameters-section">
        <div class="section-heading erp-list-toolbar">
          <div><h2>全部业务参数</h2><span>共 {{ systemParameters.length }} 项</span></div>
          <el-button class="erp-button-motion" :icon="Download" @click="exportConfiguration">导出配置</el-button>
          <el-button v-if="summary.pending_changes > 0 && can(permissions.publishRelease)" class="erp-button-motion" type="primary" @click="openPublishDialog">发布配置</el-button>
        </div>
        <div class="erp-list-table-frame"><el-table :data="systemParameters" height="100%" table-layout="fixed">
          <el-table-column prop="chinese_name" label="参数" min-width="170" />
          <el-table-column label="当前草稿值" min-width="130"><template #default="{ row }">{{ formatParameterValue(row) }}</template></el-table-column>
          <el-table-column prop="code" label="编码" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="76" fixed="right"><template #default="{ row }"><el-button v-if="can(permissions.changeParameter)" link type="primary" @click="openParameterEditor(row)">编辑</el-button></template></el-table-column>
        </el-table></div>
      </section>

      <div v-else class="settings-layout">
        <aside class="category-panel card-shell erp-list-filter erp-list-catalog-nav">
          <div class="category-panel__title">配置分类</div>
          <button
            v-for="category in categories"
            :key="category.key"
            type="button"
            class="category-button"
            :class="{ 'is-active': selectedCategoryKey === category.key }"
            @click="selectedCategoryKey = category.key"
          >
            <span>{{ category.label }}</span>
            <span class="category-button__count">{{ categoryCount(category) }}</span>
          </button>
        </aside>

        <main class="settings-main">
          <section class="dictionary-card card-shell erp-list-data">
            <div class="section-heading erp-list-toolbar">
        <div class="page-heading__actions">
          <template v-if="section === 'all'">
          <el-button v-if="canViewProductionData" class="page-heading__link erp-button-motion" tag="a" href="/settings/production-data">生产维护</el-button>
          <el-button class="page-heading__link erp-button-motion" tag="a" href="/settings/email-accounts">邮件账户</el-button>
          <el-button v-if="authStore.hasPermission('workflow.view_slapolicy')" class="page-heading__link erp-button-motion" tag="a" href="/settings/inquiry-handling-time">询盘处理时限</el-button>
          <el-button v-if="canViewMasterData" class="page-heading__link erp-button-motion" tag="a" href="/settings/master-data">基础资料中心</el-button>
          <el-button v-if="authStore.user?.is_superuser || authStore.hasPermission('reference_data.view_numberrule')" class="page-heading__link erp-button-motion" tag="a" href="/settings/number-rules">编号规则</el-button>
          <el-button v-if="authStore.managementCan('access_control.manage_notifications')" class="page-heading__link erp-button-motion" tag="a" href="/settings/notifications">通知规则</el-button>
          <el-button class="page-heading__link erp-button-motion" tag="a" href="/settings/theme">界面主题</el-button>
          <el-button v-if="can(permissions.viewParameter)" class="page-heading__link erp-button-motion" data-testid="open-parameters" @click="parameterDrawerVisible = true">业务参数</el-button>
          </template>
          <el-button class="erp-button-motion" :icon="Download" @click="exportConfiguration">导出配置</el-button>
          <el-button class="erp-button-motion" v-if="summary.pending_changes > 0 && can(permissions.publishRelease)" type="primary" @click="openPublishDialog">发布配置</el-button>
          <el-button class="erp-button-motion" v-if="can(permissions.addItem)" type="primary" :icon="Plus" @click="openCreateItem()">新增字典项</el-button>
        </div>
              <div>
                <h2>{{ selectedCategory.label }}字典项</h2>
                <span>共 {{ visibleDictionaryTypes.length }} 类</span>
              </div>
              <el-button class="erp-button-motion" v-if="can(permissions.changeType)" :icon="Sort" @click="openSortDialog">批量排序</el-button>
            </div>

            <el-empty v-if="!visibleDictionaryTypes.length" description="当前分类暂无符合条件的字典配置" />
            <div v-else class="erp-list-table-frame"><el-table :data="visibleDictionaryTypes" height="100%" class="dictionary-table" table-layout="fixed">
              <el-table-column prop="code" label="字典编码" min-width="176" show-overflow-tooltip />
              <el-table-column prop="chinese_name" label="中文名称" min-width="140" show-overflow-tooltip />
              <el-table-column prop="english_name" label="英文名称" min-width="170" show-overflow-tooltip />
              <el-table-column label="状态" width="96" class-name="dictionary-status-column">
                <template #default="{ row }">
                  <el-tag class="settings-tag erp-list-tag" :class="row.status === 'ACTIVE' ? 'erp-list-tag--success' : 'erp-list-tag--neutral'" :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="light" round>
                    {{ row.status === 'ACTIVE' ? '启用' : '停用' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="引用数" width="92" align="right">
                <template #default="{ row }">{{ row.reference_count }}</template>
              </el-table-column>
              <el-table-column label="更新时间" width="154">
                <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="80" fixed="right" class-name="dictionary-operation-column">
                <template #default="{ row }">
                  <el-dropdown
                    v-if="can(permissions.changeType) || can(permissions.viewItem)"
                    trigger="click"
                    placement="bottom-end"
                  >
                    <el-button link data-testid="dictionary-row-more">更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item v-if="can(permissions.changeType)" @click="openTypeEditor(row)">编辑</el-dropdown-item>
                        <el-dropdown-item v-if="can(permissions.viewItem)" @click="openItemManager(row)">管理字典项</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
              </el-table-column>
            </el-table></div>
          </section>
        </main>
      </div>
    </template>

    <el-dialog v-model="typeDialogVisible" title="编辑字典类型" width="560px" class="system-settings-dialog" draggable destroy-on-close>
      <el-form ref="typeFormRef" :model="typeForm" :rules="typeRules" label-position="top">
        <el-form-item label="稳定编码"><el-input v-model="typeForm.code" disabled /></el-form-item>
        <div class="form-grid">
          <el-form-item label="中文名称" prop="chinese_name"><el-input v-model="typeForm.chinese_name" maxlength="100" /></el-form-item>
          <el-form-item label="英文名称" prop="english_name"><el-input v-model="typeForm.english_name" maxlength="100" /></el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item label="配置分组" prop="group_code"><el-input v-model="typeForm.group_code" maxlength="50" /></el-form-item>
          <el-form-item label="排序"><el-input-number v-model="typeForm.sort_order" :min="0" :max="9999" controls-position="right" /></el-form-item>
        </div>
        <el-form-item label="说明"><el-input v-model="typeForm.description" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="typeDialogVisible = false">取消</el-button><el-button type="primary" :loading="typeSaving" @click="saveType">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="itemDrawerVisible" :title="`${managedType?.chinese_name ?? ''} · 字典项管理`" width="760px" class="system-settings-dialog">
      <div class="drawer-toolbar">
        <span>停用项保留历史显示，新建业务不再可选。</span>
        <el-button v-if="can(permissions.addItem)" type="primary" :icon="Plus" @click="openCreateItem(managedType ?? undefined)">新增字典项</el-button>
      </div>
        <el-table v-loading="itemLoading" :data="itemRows" table-layout="fixed">
          <el-table-column prop="item_code" label="编码" min-width="130" />
          <el-table-column prop="display_name" label="名称" min-width="120" />
          <el-table-column label="状态" width="76"><template #default="{ row }"><el-tag class="settings-tag" :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">{{ row.status === 'ACTIVE' ? '启用' : '停用' }}</el-tag></template></el-table-column>
        <el-table-column prop="reference_count" label="引用" width="66" align="right" />
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button v-if="can(permissions.changeItem)" link type="primary" @click="openItemEditor(row)">编辑</el-button>
            <el-button v-if="canItemStatus(row)" link @click="changeItemStatus(row)">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-button>
            <el-button v-if="canArchiveItem()" link type="danger" :icon="Delete" @click="archiveItem(row)">归档</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="itemDialogVisible" :title="itemEditing ? '编辑字典项' : '新增字典项'" width="620px" class="system-settings-dialog" draggable destroy-on-close>
      <el-form ref="itemFormRef" :model="itemForm" :rules="itemRules" label-position="top">
        <el-form-item label="字典类型" prop="dictionary_type">
          <el-select v-model="itemForm.dictionary_type" filterable :disabled="itemEditing" placeholder="请选择">
            <el-option v-for="item in dictionaryTypes" :key="item.id" :label="`${item.chinese_name} (${item.code})`" :value="item.id" />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="稳定编码" prop="item_code"><el-input v-model="itemForm.item_code" :disabled="itemEditing" maxlength="100" @blur="itemForm.item_code = itemForm.item_code.toUpperCase()" /></el-form-item>
          <el-form-item label="排序"><el-input-number v-model="itemForm.sort_order" :min="0" :max="9999" controls-position="right" /></el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item label="中文名称" prop="display_name"><el-input v-model="itemForm.display_name" maxlength="100" /></el-form-item>
          <el-form-item label="英文名称"><el-input v-model="itemForm.english_name" maxlength="100" /></el-form-item>
        </div>
        <el-form-item label="颜色"><el-input v-model="itemForm.color" maxlength="30" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="itemForm.description" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="itemDialogVisible = false">取消</el-button><el-button type="primary" :loading="itemSaving" @click="saveItem">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-if="section === 'all'" v-model="parameterDrawerVisible" title="全部业务参数" width="680px" class="system-settings-dialog">
      <el-table :data="systemParameters">
        <el-table-column prop="chinese_name" label="参数" min-width="170" />
        <el-table-column label="当前草稿值" min-width="130"><template #default="{ row }">{{ formatParameterValue(row) }}</template></el-table-column>
        <el-table-column prop="code" label="编码" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="76" fixed="right"><template #default="{ row }"><el-button v-if="can(permissions.changeParameter)" link type="primary" @click="openParameterEditor(row)">编辑</el-button></template></el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="parameterDialogVisible" title="编辑业务参数" width="500px" class="system-settings-dialog" draggable destroy-on-close>
      <template v-if="parameterEditor">
        <div class="parameter-editor__name">{{ parameterEditor.chinese_name }}</div>
        <div class="parameter-editor__code">{{ parameterEditor.code }}</div>
        <el-input-number
          v-if="parameterEditor.value_type === 'INTEGER'"
          v-model="parameterForm.numberValue"
          :min="parameterEditor.validation_rules.min"
          :max="parameterEditor.validation_rules.max"
          controls-position="right"
        />
        <el-switch v-else-if="parameterEditor.value_type === 'BOOLEAN'" v-model="parameterForm.booleanValue" />
        <el-select v-else-if="parameterEditor.value_type === 'DATE_FORMAT'" v-model="parameterForm.stringValue">
          <el-option label="YYYY-MM-DD" value="YYYY-MM-DD" /><el-option label="DD/MM/YYYY" value="DD/MM/YYYY" /><el-option label="MM/DD/YYYY" value="MM/DD/YYYY" />
        </el-select>
        <el-input v-else v-model="parameterForm.stringValue" clearable placeholder="留空表示未配置" />
        <p class="parameter-editor__help">{{ parameterEditor.description || '该值发布后对全局业务生效。' }}</p>
      </template>
      <template #footer><el-button @click="parameterDialogVisible = false">取消</el-button><el-button type="primary" :loading="parameterSaving" @click="saveParameter">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="publishDialogVisible" title="发布配置版本" width="520px" class="system-settings-dialog" draggable destroy-on-close>
      <div class="publish-summary">
        <el-icon><Setting /></el-icon>
        <div><strong>将生成不可变版本 v{{ (summary.config_version ?? 0) + 1 }}</strong><p>业务页面只读取最近一次成功发布的配置。</p></div>
      </div>
      <el-form label-position="top">
        <el-form-item label="待发布变更"><strong>{{ summary.pending_changes }} 项</strong></el-form-item>
        <el-form-item label="发布说明"><el-input v-model="publishNotes" type="textarea" :rows="4" maxlength="500" show-word-limit placeholder="请说明本次配置变更内容" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="publishDialogVisible = false">取消</el-button><el-button type="primary" :loading="publishSaving" @click="confirmPublish">确认发布</el-button></template>
    </el-dialog>

    <el-dialog v-model="sortDialogVisible" title="批量排序" width="480px" class="system-settings-dialog" draggable destroy-on-close>
      <p class="sort-help">数字越小越靠前，保存后需发布才会对业务页面生效。</p>
      <div v-for="row in sortRows" :key="row.id" class="sort-row"><span>{{ row.name }}</span><el-input-number v-model="row.sortOrder" :min="0" :max="9999" controls-position="right" /></div>
      <template #footer><el-button @click="sortDialogVisible = false">取消</el-button><el-button type="primary" :loading="sortSaving" @click="saveSortOrder">保存排序</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.page-heading__actions { display: flex; flex: 1 0 100%; flex-wrap: wrap; gap: 8px; }
.page-heading__link { text-decoration: none; }
.settings-layout { display: grid; flex: 1; min-height: 0; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; }
.category-panel { min-height: 0; overflow-y: auto; }
.category-panel__title { padding: 0 12px 10px; color: var(--erp-color-text-secondary); font-size: 13px; }
.category-button { width: 100%; display: flex; align-items: center; justify-content: space-between; font: inherit; font-size: 13px; }
.category-button__count { font-size: 12px; }
.settings-main { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.filter-card > :deep(.el-input) { width: min(420px, 100%); }
.status-filter { width: 140px; }
.filter-card__version { color: var(--erp-color-text-secondary); font-size: 13px; }
.section-heading > div:not(.page-heading__actions) { display: flex; align-items: baseline; gap: 10px; margin-right: auto; }
.section-heading h2 { margin: 0; font-size: 14px; font-weight: 600; }
.section-heading span { color: var(--erp-color-text-secondary); font-size: 12px; }
.state-page { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.state-page__icon { font-size: 26px; color: var(--erp-color-warning); }
.state-page h1, .state-page h2 { margin: 18px 0 0; font-size: 20px; }
.state-page p { max-width: 480px; margin: 8px 0 20px; color: var(--erp-color-text-secondary); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.drawer-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: -4px 0 18px; color: var(--erp-color-text-secondary); font-size: 13px; }
.parameter-editor__name { margin-bottom: 4px; font-size: 16px; font-weight: 650; }
.parameter-editor__code { margin-bottom: 20px; color: var(--erp-color-text-muted); font-size: 12px; }
.parameter-editor__help, .sort-help { margin: 14px 0 0; color: var(--erp-color-text-secondary); font-size: 13px; line-height: 1.6; }
.publish-summary { display: flex; gap: 12px; margin-bottom: 20px; padding: 16px; border-radius: 8px; background: var(--erp-surface-background); }
.publish-summary > .el-icon { margin-top: 2px; color: var(--erp-color-info); font-size: 22px; }
.publish-summary strong { font-size: 15px; }
.publish-summary p { margin: 5px 0 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.sort-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 10px 0; border-bottom: 1px solid var(--erp-color-border-subtle); }


@media (max-width: 1599px) { .settings-layout { grid-template-columns: 220px minmax(0, 1fr); } }
@media (max-width: 1100px) { .settings-layout { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); } .category-panel { flex-direction: row; overflow-x: auto; } .category-panel__title { display: none; } .category-button { flex: 0 0 auto; width: auto; gap: 10px; } }
@media (max-width: 768px) { .form-grid { grid-template-columns: 1fr; } }
</style>
