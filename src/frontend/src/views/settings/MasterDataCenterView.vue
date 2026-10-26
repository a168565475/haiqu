<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { AxiosError } from 'axios'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import {
  Collection,
  Download,
  Edit,
  Lock,
  Plus,
  Refresh,
  Warning,
} from '@element-plus/icons-vue'

import {
  archiveMasterDataRecord,
  changeMasterDataStatus,
  correctExchangeRate,
  createMasterDataRecord,
  fetchAllMasterDataRecords,
  fetchMasterDataList,
  fetchMasterDataRecord,
  fetchMasterDataSummary,
  updateMasterDataRecord,
} from '@/api/referenceData'
import { useAuthStore } from '@/stores/auth'
import type {
  CodedMasterData,
  MasterDataInput,
  MasterDataRecord,
  MasterDataResource,
  MasterDataSummary,
  ReferenceDataApiError,
  ReferenceStatus,
} from '@/types/referenceData'

interface CategoryDefinition {
  key: string
  label: string
  resource: MasterDataResource
  permissionModel: string
  countKey: string
  title: string
}

interface ColumnDefinition {
  key: string
  label: string
  minWidth?: number
  compactHidden?: boolean
}

interface FieldDefinition {
  key: string
  label: string
  type?: 'text' | 'number' | 'date' | 'textarea' | 'select'
  required?: boolean
  placeholder?: string
  options?: Array<{ value: string | number; label: string }>
  lookup?: 'countries' | 'currencies'
  min?: number
  max?: number
}

const categories: CategoryDefinition[] = [
  { key: 'country', label: '国家 / 地区', resource: 'countries', permissionModel: 'country', countKey: 'countries', title: '国家 / 地区' },
  { key: 'currency', label: '币种', resource: 'currencies', permissionModel: 'currency', countKey: 'currencies', title: '币种' },
  { key: 'exchangeRate', label: '汇率', resource: 'exchange-rates', permissionModel: 'exchangerate', countKey: 'exchange_rates', title: '汇率历史' },
  { key: 'unit', label: '单位', resource: 'units', permissionModel: 'unit', countKey: 'units', title: '单位' },
  { key: 'incoterm', label: 'Incoterms', resource: 'incoterms', permissionModel: 'incoterm', countKey: 'incoterms', title: 'Incoterms' },
  { key: 'paymentMethod', label: '付款方式', resource: 'payment-methods', permissionModel: 'paymentmethod', countKey: 'payment_methods', title: '付款方式' },
  { key: 'transportMethod', label: '运输方式', resource: 'transport-methods', permissionModel: 'transportmethod', countKey: 'transport_methods', title: '运输方式' },
  { key: 'port', label: '港口', resource: 'ports', permissionModel: 'port', countKey: 'ports', title: '港口' },
  { key: 'courier', label: '快递公司', resource: 'couriers', permissionModel: 'courier', countKey: 'couriers', title: '快递公司' },
]

const columnsByCategory: Record<string, ColumnDefinition[]> = {
  country: [
    { key: 'code', label: 'Alpha-2', minWidth: 90 },
    { key: 'chinese_name', label: '中文名称', minWidth: 130 },
    { key: 'continent', label: '洲别', minWidth: 90 },
    { key: 'english_name', label: '英文名称', minWidth: 180, compactHidden: true },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'alpha3_code', label: 'Alpha-3', minWidth: 90 },
    { key: 'numeric_code', label: '数字码', minWidth: 90, compactHidden: true },
    { key: 'source_version', label: '标准版本', minWidth: 180 },
  ],
  currency: [
    { key: 'code', label: '字母码', minWidth: 90 },
    { key: 'chinese_name', label: '中文名称', minWidth: 130 },
    { key: 'english_name', label: '英文名称', minWidth: 170, compactHidden: true },
    { key: 'symbol', label: '符号', minWidth: 80 },
    { key: 'numeric_code', label: '数字码', minWidth: 90 },
    { key: 'decimal_places', label: '小数位', minWidth: 80 },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'source_version', label: '标准版本', minWidth: 180 },
  ],
  exchangeRate: [
    { key: 'effective_date', label: '生效日期', minWidth: 110 },
    { key: 'base_currency_code', label: '基础币种', minWidth: 90 },
    { key: 'quote_currency_code', label: '目标币种', minWidth: 90 },
    { key: 'rate', label: '汇率', minWidth: 130 },
    { key: 'source_name', label: '来源', minWidth: 130 },
    { key: 'source_version', label: '来源版本', minWidth: 140, compactHidden: true },
    { key: 'entered_by_name', label: '录入人', minWidth: 110 },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'created_at', label: '录入时间', minWidth: 160 },
  ],
  unit: [
    { key: 'code', label: '代码', minWidth: 100 },
    { key: 'chinese_name', label: '中文名称', minWidth: 130 },
    { key: 'english_name', label: '英文名称', minWidth: 160, compactHidden: true },
    { key: 'symbol', label: '符号', minWidth: 90 },
    { key: 'category', label: '类别', minWidth: 120 },
    { key: 'decimal_places', label: '允许小数位', minWidth: 100 },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'source_version', label: '标准版本', minWidth: 170 },
  ],
  incoterm: [
    { key: 'code', label: '代码', minWidth: 90 },
    { key: 'chinese_name', label: '中文名称', minWidth: 150 },
    { key: 'english_name', label: '英文名称', minWidth: 180, compactHidden: true },
    { key: 'rules_version', label: '规则版本', minWidth: 110 },
    { key: 'transport_scope', label: '适用运输', minWidth: 170 },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'source_version', label: '标准版本', minWidth: 150 },
  ],
  paymentMethod: commonColumns(),
  transportMethod: commonColumns(),
  port: [
    { key: 'code', label: 'UN/LOCODE', minWidth: 110 },
    { key: 'country_name', label: '国家 / 地区', minWidth: 130 },
    { key: 'chinese_name', label: '中文名称', minWidth: 140 },
    { key: 'english_name', label: '英文名称', minWidth: 170, compactHidden: true },
    { key: 'administrative_area', label: '行政区', minWidth: 130 },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'source_version', label: '标准版本', minWidth: 150 },
  ],
  courier: [
    { key: 'code', label: '代码', minWidth: 100 },
    { key: 'chinese_name', label: '名称', minWidth: 150 },
    { key: 'english_name', label: '英文名称', minWidth: 160, compactHidden: true },
    { key: 'tracking_url_template', label: '查询地址模板', minWidth: 260 },
    { key: 'status', label: '状态', minWidth: 86 },
  ],
}

function commonColumns(): ColumnDefinition[] {
  return [
    { key: 'code', label: '代码', minWidth: 110 },
    { key: 'chinese_name', label: '中文名称', minWidth: 150 },
    { key: 'english_name', label: '英文名称', minWidth: 180, compactHidden: true },
    { key: 'status', label: '状态', minWidth: 86 },
    { key: 'description', label: '说明', minWidth: 220 },
  ]
}

const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const selectedKey = ref(categories[0].key)
const selectedCategory = computed(() => categories.find((item) => item.key === selectedKey.value) ?? categories[0])

function permission(category: CategoryDefinition, action: 'view' | 'add' | 'change'): string {
  return `reference_data.${action}_${category.permissionModel}`
}

function can(permissionCode: string): boolean {
  return isSuperuser.value || authStore.hasPermission(permissionCode)
}

function canView(category: CategoryDefinition): boolean {
  return can(permission(category, 'view'))
}

const canViewPage = computed(() => categories.some(canView))
const canViewSelected = computed(() => canView(selectedCategory.value))
const canAddSelected = computed(() => can(permission(selectedCategory.value, 'add')))
const canChangeSelected = computed(() => can(permission(selectedCategory.value, 'change')))
const isExchangeRate = computed(() => selectedCategory.value.resource === 'exchange-rates')

const summary = ref<MasterDataSummary>({
  category_counts: {},
  standard_source_count: 5,
  standard_sources: ['ISO 3166', 'ISO 4217', 'UN/CEFACT Rec.20', 'ICC 2020', 'UN/LOCODE'],
  base_currency: null,
  config_version: null,
})
const records = ref<MasterDataRecord[]>([])
const recordsLoading = ref(false)
const summaryLoading = ref(false)
const loading = computed(() => recordsLoading.value || summaryLoading.value)
let recordsRequest = 0
let summaryRequest = 0
let disposed = false
const loadError = ref('')
const permissionDenied = ref(false)
const keyword = ref('')
const statusFilter = ref<ReferenceStatus | ''>('')
const sourceFilter = ref('')
const props = defineProps<{ embedded?: boolean }>()
const continentFilter = ref('')
const compactViewport = ref(window.innerWidth < 1600)

const currentColumns = computed(() => {
  const columns = columnsByCategory[selectedCategory.value.key] ?? commonColumns()
  return compactViewport.value ? columns.filter((column) => !column.compactHidden) : columns
})

function syncViewport(): void {
  compactViewport.value = window.innerWidth < 1600
}

function categoryCount(category: CategoryDefinition): number {
  return summary.value.category_counts[category.countKey] ?? 0
}

function statusCode(error: unknown): number | undefined {
  return error instanceof AxiosError ? error.response?.status : undefined
}

function apiPayload(error: unknown): ReferenceDataApiError | undefined {
  return error instanceof AxiosError ? error.response?.data as ReferenceDataApiError : undefined
}

function apiMessage(error: unknown, fallback: string): string {
  return apiPayload(error)?.error?.message || fallback
}

async function loadSummary(): Promise<void> {
  if (disposed) return
  const request = ++summaryRequest
  summaryLoading.value = true
  try {
    const result = await fetchMasterDataSummary()
    if (!disposed && request === summaryRequest) summary.value = result
  } finally {
    if (!disposed && request === summaryRequest) summaryLoading.value = false
  }
}

async function loadRecords(): Promise<void> {
  if (disposed) return
  const request = ++recordsRequest
  records.value = []
  recordsLoading.value = false
  loadError.value = ''
  permissionDenied.value = false
  if (!canViewSelected.value) {
    permissionDenied.value = true
    return
  }
  recordsLoading.value = true
  try {
    const result = await fetchAllMasterDataRecords(selectedCategory.value.resource, {
      q: keyword.value.trim() || undefined,
      status: statusFilter.value || undefined,
      source: sourceFilter.value || undefined,
    })
    if (!disposed && request === recordsRequest) records.value = result
  } catch (error) {
    if (disposed || request !== recordsRequest) return
    if (statusCode(error) === 403) permissionDenied.value = true
    else loadError.value = apiMessage(error, '基础资料加载失败，请检查网络后重试。')
  } finally {
    if (!disposed && request === recordsRequest) recordsLoading.value = false
  }
}

async function loadPage(): Promise<void> {
  if (disposed || !canViewPage.value) return
  const recordsPromise = loadRecords()
  const request = recordsRequest
  try {
    await Promise.all([loadSummary(), recordsPromise])
  } catch (error) {
    // 汇总失败属于发起时的列表上下文，不能覆盖用户刚切换的分类或筛选。
    if (disposed || request !== recordsRequest) return
    if (statusCode(error) === 403) permissionDenied.value = true
    else loadError.value = apiMessage(error, '基础资料中心加载失败，请稍后重试。')
  }
}

async function selectCategory(category: CategoryDefinition): Promise<void> {
  selectedKey.value = category.key
  keyword.value = ''
  statusFilter.value = ''
  sourceFilter.value = ''
  continentFilter.value = ''
  await loadRecords()
}

async function searchRecords(): Promise<void> {
  await loadRecords()
}

async function resetFilters(): Promise<void> {
  keyword.value = ''
  statusFilter.value = ''
  sourceFilter.value = ''
  continentFilter.value = ''
  await loadRecords()
}

function formatDateTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function transportScopeLabel(value: unknown): string {
  if (value === 'ANY_MODE') return '任意运输方式'
  if (value === 'SEA_INLAND_WATERWAY') return '海运及内河运输'
  return String(value || '—')
}

function cellValue(row: MasterDataRecord, key: string): string | number {
  const value = (row as unknown as Record<string, unknown>)[key]
  if (key === 'created_at' || key === 'updated_at') return formatDateTime(value)
  if (key === 'transport_scope') return transportScopeLabel(value)
  if (key === 'rate' && typeof value === 'string') return value.replace(/0+$/, '').replace(/\.$/, '')
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

const continentLabels: Record<string, string> = {
  Africa: '非洲',
  Americas: '美洲',
  Asia: '亚洲',
  Europe: '欧洲',
  Oceania: '大洋洲',
  Antarctica: '南极洲',
  SOUTHEAST_ASIA: '亚洲',
}

function countryContinent(row: MasterDataRecord): string {
  const extraData = (row as unknown as { extra_data?: Record<string, unknown> }).extra_data
  const region = typeof extraData?.region_name === 'string'
    ? extraData.region_name
    : typeof extraData?.region === 'string' ? extraData.region : ''
  return continentLabels[region] || region || '其他'
}

function countryFlag(code: unknown): string {
  if (typeof code !== 'string' || !/^[A-Za-z]{2}$/.test(code)) return '🌐'
  return code.toUpperCase().split('').map((letter) => String.fromCodePoint(127397 + letter.charCodeAt(0))).join('')
}

function countryFlagUrl(code: unknown): string {
  if (typeof code !== 'string' || !/^[A-Za-z]{2}$/.test(code)) return ''
  return `https://flagcdn.com/24x18/${code.toLowerCase()}.png`
}

const visibleRecords = computed(() => {
  if (selectedCategory.value.key !== 'country' || !continentFilter.value) return records.value
  return records.value.filter((row) => countryContinent(row) === continentFilter.value)
})

const continentOptions = computed(() => {
  if (selectedCategory.value.key !== 'country') return []
  return [...new Set(records.value.map(countryContinent))].sort((left, right) => left.localeCompare(right, 'zh-CN'))
})

async function fetchAllCurrentRecords(): Promise<MasterDataRecord[]> {
  return fetchAllMasterDataRecords(selectedCategory.value.resource, {
    q: keyword.value.trim() || undefined,
    status: statusFilter.value || undefined,
    source: sourceFilter.value || undefined,
  })
}

async function exportRecords(): Promise<void> {
  if (!canViewSelected.value) return
  try {
    const data = await fetchAllCurrentRecords()
    const content = {
      exported_at: new Date().toISOString(),
      config_version: summary.value.config_version,
      category: selectedCategory.value.key,
      data,
    }
    const blob = new Blob([JSON.stringify(content, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `master-data-${selectedCategory.value.resource}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('当前分类已导出')
  } catch (error) {
    ElMessage.error(apiMessage(error, '导出失败'))
  }
}

const dialogVisible = ref(false)
const saving = ref(false)
const pendingActions = ref(0)

function canClose(): boolean {
  if (saving.value || pendingActions.value) {
    ElMessage.warning('基础资料操作进行中，请稍候再关闭。')
    return false
  }
  if (dialogVisible.value) {
    ElMessage.warning('请先保存或取消当前基础资料编辑。')
    return false
  }
  return true
}

defineExpose({ canClose })
const editingId = ref('')
const currentEtag = ref('')
const correctionMode = ref(false)
const formRef = ref<FormInstance>()
const formData = reactive<Record<string, unknown>>({})
const countryChoices = ref<CodedMasterData[]>([])
const currencyChoices = ref<CodedMasterData[]>([])

function baseFields(): FieldDefinition[] {
  return [
    { key: 'code', label: '代码', required: true, placeholder: '请输入大写稳定编码' },
    { key: 'chinese_name', label: '中文名称', required: true },
    { key: 'english_name', label: '英文名称' },
    { key: 'sort_order', label: '排序', type: 'number', min: 0 },
    { key: 'source_version', label: '标准 / 来源版本' },
    { key: 'description', label: '说明', type: 'textarea' },
  ]
}

const formFields = computed<FieldDefinition[]>(() => {
  if (isExchangeRate.value) {
    const fields: FieldDefinition[] = correctionMode.value ? [] : [
      { key: 'base_currency', label: '基础币种', type: 'select', lookup: 'currencies', required: true },
      { key: 'quote_currency', label: '目标币种', type: 'select', lookup: 'currencies', required: true },
    ]
    return [
      ...fields,
      { key: 'rate', label: '汇率', required: true, placeholder: '必须大于 0' },
      { key: 'effective_date', label: '生效日期', type: 'date', required: true },
      { key: 'source_name', label: '来源', required: true },
      { key: 'source_version', label: '来源版本' },
      { key: 'description', label: correctionMode.value ? '更正原因' : '说明', type: 'textarea', required: correctionMode.value },
    ]
  }
  const common = baseFields()
  const insert = (fields: FieldDefinition[]) => [common[0], ...fields, ...common.slice(1)]
  switch (selectedCategory.value.key) {
    case 'country':
      return insert([
        { key: 'alpha3_code', label: 'Alpha-3', required: true },
        { key: 'numeric_code', label: '数字码', required: true, placeholder: '三位数字，如 156' },
      ])
    case 'currency':
      return insert([
        { key: 'numeric_code', label: '数字码', required: true, placeholder: '三位数字，如 840' },
        { key: 'decimal_places', label: '小数位', type: 'number', min: 0, max: 6, required: true },
        { key: 'symbol', label: '符号' },
      ])
    case 'unit':
      return insert([
        { key: 'symbol', label: '符号' },
        { key: 'category', label: '类别' },
        { key: 'decimal_places', label: '允许小数位', type: 'number', min: 0, max: 6, required: true },
      ])
    case 'incoterm':
      return insert([
        { key: 'rules_version', label: '规则版本', required: true, placeholder: '如 2020' },
        {
          key: 'transport_scope', label: '适用运输', type: 'select', required: true,
          options: [
            { value: 'ANY_MODE', label: '任意运输方式' },
            { value: 'SEA_INLAND_WATERWAY', label: '海运及内河运输' },
          ],
        },
      ])
    case 'port':
      return insert([
        { key: 'country', label: '国家 / 地区', type: 'select', lookup: 'countries', required: true },
        { key: 'administrative_area', label: '行政区' },
      ])
    case 'courier':
      return insert([{ key: 'tracking_url_template', label: '查询地址模板', placeholder: 'https://example.com/track/{number}' }])
    default:
      return common
  }
})

const formRules = computed<FormRules>(() => {
  const rules: FormRules = {}
  for (const field of formFields.value) {
    if (field.required) rules[field.key] = [{ required: true, message: `请填写${field.label}`, trigger: 'change' }]
  }
  return rules
})

function resetFormData(): void {
  for (const key of Object.keys(formData)) delete formData[key]
  Object.assign(formData, {
    sort_order: 0,
    decimal_places: selectedCategory.value.key === 'currency' ? 2 : 0,
    effective_date: new Date().toISOString().slice(0, 10),
  })
}

async function loadLookup(resource: 'countries' | 'currencies', query = ''): Promise<void> {
  if (!can(`reference_data.view_${resource === 'countries' ? 'country' : 'currency'}`)) return
  const response = await fetchMasterDataList<CodedMasterData>(resource, {
    page_size: 100,
    q: query || undefined,
    status: 'ACTIVE',
  })
  if (resource === 'countries') countryChoices.value = response.data
  else currencyChoices.value = response.data
}

function fieldOptions(field: FieldDefinition): Array<{ value: string | number; label: string }> {
  if (field.options) return field.options
  const choices = field.lookup === 'countries' ? countryChoices.value : currencyChoices.value
  return choices.map((item) => ({ value: item.id, label: `${item.code} · ${item.chinese_name || item.english_name}` }))
}

async function remoteLookup(field: FieldDefinition, query: string): Promise<void> {
  if (field.lookup) await loadLookup(field.lookup, query)
}

async function openCreate(): Promise<void> {
  if (!canAddSelected.value) return
  if (isExchangeRate.value && !can('reference_data.view_currency')) {
    ElMessage.warning('新增汇率前需要币种查看权限')
    return
  }
  if (selectedCategory.value.key === 'port' && !can('reference_data.view_country')) {
    ElMessage.warning('新增港口前需要国家 / 地区查看权限')
    return
  }
  resetFormData()
  editingId.value = ''
  currentEtag.value = ''
  correctionMode.value = false
  try {
    if (isExchangeRate.value) await loadLookup('currencies')
    if (selectedCategory.value.key === 'port') await loadLookup('countries')
  } catch (error) {
    ElMessage.error(apiMessage(error, '关联基础资料加载失败'))
    return
  }
  dialogVisible.value = true
}

async function ensureCurrentLookup(row: MasterDataRecord): Promise<void> {
  if (selectedCategory.value.key === 'port') {
    await loadLookup('countries', String((row as unknown as Record<string, unknown>).country_code ?? ''))
  }
  if (isExchangeRate.value) await loadLookup('currencies')
}

async function openEdit(row: MasterDataRecord): Promise<void> {
  if (!canChangeSelected.value) return
  try {
    const response = await fetchMasterDataRecord(selectedCategory.value.resource, row.id)
    resetFormData()
    editingId.value = row.id
    currentEtag.value = response.etag
    correctionMode.value = isExchangeRate.value
    await ensureCurrentLookup(response.data)
    for (const field of formFields.value) {
      const value = (response.data as unknown as Record<string, unknown>)[field.key]
      if (value !== undefined) formData[field.key] = value
    }
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '记录详情加载失败'))
  }
}

function normalizePayload(): MasterDataInput {
  const payload: MasterDataInput = {}
  for (const field of formFields.value) {
    let value = formData[field.key]
    if (['code', 'alpha3_code'].includes(field.key) && typeof value === 'string') value = value.trim().toUpperCase()
    payload[field.key] = value ?? ''
  }
  return payload
}

function updateFormField(key: string, value: unknown): void {
  formData[key] = value
}

async function saveRecord(): Promise<void> {
  if (!formRef.value || saving.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const payload = normalizePayload()
  if (isExchangeRate.value && payload.base_currency && payload.base_currency === payload.quote_currency) {
    ElMessage.warning('基础币种和目标币种不能相同')
    return
  }
  saving.value = true
  try {
    if (correctionMode.value) {
      await correctExchangeRate(editingId.value, payload, currentEtag.value)
      ElMessage.success('汇率更正已追加，原记录已保留并停用')
    } else if (editingId.value) {
      await updateMasterDataRecord(selectedCategory.value.resource, editingId.value, payload, currentEtag.value)
      ElMessage.success('基础资料已更新')
    } else {
      await createMasterDataRecord(selectedCategory.value.resource, payload)
      ElMessage.success(isExchangeRate.value ? '汇率记录已新增' : '基础资料已新增')
    }
    dialogVisible.value = false
    await Promise.all([loadSummary(), loadRecords()])
  } catch (error) {
    if (statusCode(error) === 412) {
      dialogVisible.value = false
      await ElMessageBox.alert('该记录已被其他用户更新，请重新加载后再编辑。', '并发编辑冲突', { type: 'warning' })
      await loadRecords()
    } else if (statusCode(error) === 428) {
      ElMessage.error('缺少记录版本，请关闭窗口后重新编辑')
    } else {
      ElMessage.error(apiMessage(error, '保存失败，请检查填写内容'))
    }
  } finally {
    saving.value = false
  }
}

async function changeStatus(row: MasterDataRecord): Promise<void> {
  if (!canChangeSelected.value || isExchangeRate.value) return
  const target = row.status === 'ACTIVE' ? 'deactivate' : 'activate'
  const actionLabel = target === 'deactivate' ? '停用' : '启用'
  pendingActions.value++
  try {
    const detail = await fetchMasterDataRecord(selectedCategory.value.resource, row.id)
    const result = await ElMessageBox.prompt(
      target === 'deactivate'
        ? '停用后历史数据继续显示，但新建业务不可再选择。请输入原因。'
        : '请输入重新启用原因。',
      `${actionLabel}${selectedCategory.value.label}`,
      { inputValidator: (value) => Boolean(value.trim()) || '原因不能为空', confirmButtonText: actionLabel },
    )
    await changeMasterDataStatus(
      selectedCategory.value.resource as Exclude<MasterDataResource, 'exchange-rates'>,
      row.id,
      target,
      detail.etag,
      result.value.trim(),
    )
    ElMessage.success(`${actionLabel}成功`)
    await Promise.all([loadSummary(), loadRecords()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (statusCode(error) === 412) {
      ElMessage.warning('记录已被其他用户修改，请刷新后重试')
      await loadRecords()
    } else if (statusCode(error) === 409) {
      await ElMessageBox.alert(apiMessage(error, '该资料仍被业务引用，当前操作已阻止。'), '引用中的资料', { type: 'warning' })
    } else {
      ElMessage.error(apiMessage(error, `${actionLabel}失败`))
    }
  } finally {
    pendingActions.value--
  }
}

async function archiveRecord(row: MasterDataRecord): Promise<void> {
  if (!canChangeSelected.value || isExchangeRate.value) return
  pendingActions.value++
  try {
    const detail = await fetchMasterDataRecord(selectedCategory.value.resource, row.id)
    const result = await ElMessageBox.prompt('归档后默认列表不再显示该资料，请输入归档原因。', '归档资料', {
      type: 'warning', inputValidator: (value) => Boolean(value.trim()) || '原因不能为空', confirmButtonText: '确认归档',
    })
    await archiveMasterDataRecord(
      selectedCategory.value.resource as Exclude<MasterDataResource, 'exchange-rates'>,
      row.id,
      detail.etag,
      result.value.trim(),
    )
    ElMessage.success('资料已归档')
    await Promise.all([loadSummary(), loadRecords()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (statusCode(error) === 409) {
      await ElMessageBox.alert(apiMessage(error, '该资料仍被业务引用，不能归档。'), '引用中的资料', { type: 'warning' })
    } else {
      ElMessage.error(apiMessage(error, '归档失败'))
    }
  } finally {
    pendingActions.value--
  }
}

onMounted(async () => {
  window.addEventListener('resize', syncViewport)
  const firstAccessible = categories.find(canView)
  if (firstAccessible) selectedKey.value = firstAccessible.key
  await loadPage()
})

onBeforeUnmount(() => {
  disposed = true
  recordsRequest++
  summaryRequest++
  recordsLoading.value = false
  summaryLoading.value = false
  window.removeEventListener('resize', syncViewport)
})
</script>

<template>
  <section class="master-data-page system-settings-theme erp-glass-list" data-testid="master-data-center">
    <div v-if="!canViewPage" class="state-page">
      <el-icon><Lock /></el-icon>
      <h1>无配置权限</h1>
      <p>当前账号没有九类基础资料的查看权限，请联系管理员授权。</p>
    </div>

    <template v-else>
      <section v-if="!props.embedded" v-glass-spotlight class="erp-list-filter">
      <header class="page-heading erp-list-heading">
        <div>
          <h1>基础资料中心</h1>
        </div>

      </header>
          <div class="filter-card erp-list-filters" aria-label="基础资料筛选">
            <label><span>关键词</span><el-input v-model="keyword" placeholder="输入名称或编码" clearable @keyup.enter="searchRecords" /></label>
            <label><span>状态</span><el-select v-model="statusFilter" placeholder="全部状态" clearable>
              <el-option label="启用" value="ACTIVE" /><el-option label="停用" value="INACTIVE" />
            </el-select></label>
            <label><span>标准来源</span><el-select v-model="sourceFilter" placeholder="全部来源" clearable>
              <el-option v-for="source in summary.standard_sources" :key="source" :label="source" :value="source" />
            </el-select></label>
            <label v-if="selectedCategory.key === 'country'"><span>洲别</span><el-select v-model="continentFilter" placeholder="全部洲别" clearable>
              <el-option v-for="continent in continentOptions" :key="continent" :label="continent" :value="continent" />
            </el-select></label>
            <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button class="erp-button-motion" type="primary" @click="searchRecords">应用筛选</el-button></div>
          </div>

      </section>

      <div class="page-grid">
        <aside class="category-card erp-list-filter erp-list-catalog-nav">
          <h2>资料分类</h2>
          <button
            v-for="category in categories"
            :key="category.key"
            type="button"
            class="category-item"
            :class="{ 'is-active': selectedKey === category.key, 'is-locked': !canView(category) }"
            @click="selectCategory(category)"
          >
            <span>{{ category.label }}</span>
            <span>{{ categoryCount(category) }}</span>
          </button>
        </aside>

        <main class="main-column">
          <section class="data-card erp-list-data" v-loading="loading">
            <div class="data-card__header erp-list-toolbar">
        <div class="page-heading__actions">
          <el-button v-if="!props.embedded" class="erp-button-motion" :icon="Download" :disabled="!canViewSelected" @click="exportRecords">导出数据</el-button>
          <el-button class="erp-button-motion" v-if="canAddSelected" type="primary" :icon="Plus" @click="openCreate">新增资料</el-button>
        </div>
              <div v-if="props.embedded && selectedCategory.key === 'country'" class="continent-buttons" aria-label="洲别筛选">
                <el-button :type="continentFilter === '' ? 'primary' : 'default'" :aria-pressed="continentFilter === ''" @click="continentFilter = ''">全部</el-button>
                <el-button v-for="continent in continentOptions" :key="continent" :type="continentFilter === continent ? 'primary' : 'default'" :aria-pressed="continentFilter === continent" @click="continentFilter = continent">{{ continent }}</el-button>
              </div>
              <div><h2>{{ selectedCategory.title }}</h2><span>共 {{ visibleRecords.length }} 项</span></div>
            </div>

            <div v-if="permissionDenied" class="card-state">
              <el-icon><Lock /></el-icon><h3>无查看权限</h3><p>当前账号不能查看此类基础资料。</p>
            </div>
            <div v-else-if="loadError" class="card-state">
              <el-icon><Warning /></el-icon><h3>资料加载失败</h3><p>{{ loadError }}</p>
              <el-button type="primary" :icon="Refresh" @click="loadRecords">重新加载</el-button>
            </div>
            <div v-else-if="!loading && records.length === 0" class="card-state">
              <el-icon><Collection /></el-icon>
              <h3>{{ isExchangeRate ? '暂无汇率历史' : '暂无基础资料' }}</h3>
              <p v-if="isExchangeRate && !summary.base_currency">可人工维护外币兑人民币汇率，供生产任务折算使用。公司本位币尚未配置，不影响生产任务的人民币换算。</p>
              <p v-else>当前筛选条件下没有记录，可调整筛选或新增资料。</p>
              <el-button v-if="canAddSelected" type="primary" :icon="Plus" @click="openCreate">{{ isExchangeRate ? '新增汇率' : '新增资料' }}</el-button>
            </div>
            <template v-else-if="!permissionDenied && !loadError">
              <el-alert
                v-if="isExchangeRate && !summary.base_currency"
                class="base-currency-alert"
                type="warning"
                :closable="false"
                show-icon
                title="公司本位币未配置；生产任务仍按已维护的兑人民币汇率换算，汇率不会自动更新。"
              />
              <div class="erp-list-table-frame"><el-table :data="visibleRecords" class="master-table" data-testid="master-data-table" height="100%" row-key="id">
                <el-table-column
                  v-for="column in currentColumns"
                  :key="column.key"
                  :label="column.label"
                  :min-width="column.minWidth"
                  :class-name="column.compactHidden ? 'compact-hidden' : ''"
                  :label-class-name="column.compactHidden ? 'compact-hidden' : ''"
                >
                  <template #default="{ row }">
                    <template v-if="selectedCategory.key === 'country' && column.key === 'chinese_name'">
                      <span class="country-name-cell"><img v-if="countryFlagUrl(row.code)" class="country-flag" data-testid="country-flag" :src="countryFlagUrl(row.code)" :alt="`${row.chinese_name}国旗`" loading="lazy"><span v-else class="country-flag" data-testid="country-flag" :aria-label="`${row.chinese_name}国旗`">{{ countryFlag(row.code) }}</span><span>{{ row.chinese_name }}</span></span>
                    </template>
                    <span v-else-if="selectedCategory.key === 'country' && column.key === 'continent'">{{ countryContinent(row) }}</span>
                    <el-tag v-if="column.key === 'status'" class="settings-tag erp-list-tag" :class="row.status === 'ACTIVE' ? 'erp-list-tag--success' : 'erp-list-tag--neutral'" :type="row.status === 'ACTIVE' ? 'success' : 'info'" round>
                      {{ row.status === 'ACTIVE' ? '启用' : '停用' }}
                    </el-tag>
                    <span v-else-if="!(selectedCategory.key === 'country' && ['chinese_name', 'continent'].includes(column.key))">{{ cellValue(row, column.key) }}</span>
                  </template>
                </el-table-column>
                <el-table-column v-if="canChangeSelected" label="操作" width="150" fixed="right" align="center" header-align="center">
                  <template #default="{ row }">
                    <span class="master-row-actions">
                    <el-button link :icon="Edit" @click="openEdit(row)">{{ isExchangeRate ? '更正' : '编辑' }}</el-button>
                    <el-dropdown v-if="!isExchangeRate" trigger="click">
                      <el-button link>更多</el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item @click="changeStatus(row)">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-dropdown-item>
                          <el-dropdown-item divided @click="archiveRecord(row)">归档</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                    </span>
                  </template>
                </el-table-column>
              </el-table></div>
            </template>
          </section>
        </main>
      </div>
    </template>

    <el-dialog
      v-model="dialogVisible"
      :title="correctionMode ? '追加汇率更正' : editingId ? `编辑${selectedCategory.label}` : `新增${selectedCategory.label}`"
      width="640px"
      class="system-settings-dialog"
      draggable
      destroy-on-close
    >
      <el-alert v-if="correctionMode" type="warning" :closable="false" show-icon title="原汇率记录不会被覆盖；保存后原记录停用，并新增一条可追溯的更正记录。" />
      <el-form ref="formRef" :model="formData" :rules="formRules" label-position="top" class="master-form">
        <el-form-item v-for="field in formFields" :key="field.key" :label="field.label" :prop="field.key">
          <el-select
            v-if="field.type === 'select'"
            :model-value="formData[field.key] as string | number | undefined"
            @update:model-value="updateFormField(field.key, $event)"
            filterable
            :remote="Boolean(field.lookup)"
            :remote-method="field.lookup ? (query: string) => remoteLookup(field, query) : undefined"
            placeholder="请选择"
            style="width: 100%"
          >
            <el-option v-for="option in fieldOptions(field)" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-input-number
            v-else-if="field.type === 'number'"
            :model-value="formData[field.key] as number | undefined"
            @update:model-value="updateFormField(field.key, $event)"
            :min="field.min ?? 0"
            :max="field.max ?? 999999"
            controls-position="right"
            style="width: 100%"
          />
          <el-date-picker
            v-else-if="field.type === 'date'"
            :model-value="formData[field.key] as string | undefined"
            @update:model-value="updateFormField(field.key, $event)"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="请选择日期"
            style="width: 100%"
          />
          <el-input
            v-else
            :model-value="formData[field.key] as string | number | undefined"
            @update:model-value="updateFormField(field.key, $event)"
            :type="field.type === 'textarea' ? 'textarea' : 'text'"
            :rows="field.type === 'textarea' ? 3 : undefined"
            :placeholder="field.placeholder"
            :disabled="Boolean(editingId && field.key === 'code')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRecord">{{ correctionMode ? '保存更正' : '保存' }}</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.page-heading__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.continent-buttons { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.continent-buttons .el-button + .el-button { margin-left: 0; }
.master-row-actions { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.page-grid { display: grid; flex: 1; min-height: 0; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; }
.category-card { min-height: 0; overflow-y: auto; }
.category-card h2 { margin: 0 5px 10px; font-size: 14px; font-weight: 600; }
.category-item { width: 100%; display: flex; align-items: center; justify-content: space-between; font: inherit; font-size: 13px; }
.category-item > span:last-child, .category-item.is-locked:not(.is-active) { color: var(--erp-color-text-secondary); font-size: 12px; }
.main-column { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.filter-card { align-items: flex-end; }
.filter-card label { width: 220px; display: flex; flex-direction: column; gap: 5px; color: var(--erp-color-text-secondary); font-size: 12px; }
.data-card__header > div:last-child { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.data-card__header h2 { margin: 0; font-size: 14px; }
.data-card__header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.base-currency-alert { margin: 4px 0 10px; }
.country-name-cell { display: inline-flex; align-items: center; gap: 7px; }
.country-flag { display: inline-flex; width: 16px; height: 12px; justify-content: center; object-fit: cover; font-size: 15px; line-height: 1; }
.card-state, .state-page { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--erp-color-text-secondary); text-align: center; }
.card-state > .el-icon, .state-page > .el-icon { font-size: 34px; color: var(--erp-color-warning); }
.card-state h3 { margin: 12px 0 6px; color: var(--erp-color-text-primary); font-size: 17px; }
.card-state p { max-width: 560px; margin: 0 0 16px; font-size: 13px; line-height: 1.7; }
.master-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; margin-top: 16px; }
.master-form :deep(.el-form-item:has(textarea)) { grid-column: 1 / -1; }


@media (max-width: 1599px) and (min-width: 769px) { .page-grid { grid-template-columns: 156px minmax(0, 1fr); } .data-card :deep(.compact-hidden) { display: none; } }
@media (max-width: 900px) { .page-grid { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); } .category-card { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); } .category-card h2 { grid-column: 1 / -1; } .filter-card label { width: min(220px, 100%); } }
@media (max-width: 640px) { .category-card { grid-template-columns: 1fr 1fr; } .master-form { grid-template-columns: 1fr; } }
</style>
