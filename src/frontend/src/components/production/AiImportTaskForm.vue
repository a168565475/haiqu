<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { fetchProductionTaskOptions, reserveProductionTaskContractNumber } from '@/api/productionTasks'
import type { ProductionTaskOptions } from '@/types/productionTask'
import { applyTaskOptions, extractedText, restoreTaskDraft, sourceObject, taskDraftFromResult, taskPayload, type AiTaskDraft } from './AiImportTaskFormData'

const props = defineProps<{ result: Record<string, unknown>; modelValue: Record<string, unknown> | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const draft = ref<AiTaskDraft>(props.modelValue ? restoreTaskDraft(props.result, props.modelValue) : taskDraftFromResult(props.result))
const options = ref<ProductionTaskOptions | null>(null)
const loading = ref(false)
const loadError = ref('')
const fieldError = ref('')
const savedInitially = Boolean(props.modelValue)
let draftPublished = false
const showMore = ref(false)
const showProductionDetails = ref(false)
const editingProductKey = ref('')
const pendingOpen = ref(false)
let reservedOrderDate = props.modelValue?.contract_number_token ? String(props.modelValue.order_date || '') : ''

type FieldKey = Exclude<keyof AiTaskDraft, 'products' | 'delivery_batches'>
interface FormField { key: FieldKey; label: string; type?: 'date' | 'boolean' | 'salesperson' | 'followers' | 'delivery' | 'tax' | 'priority'; optional?: boolean }
const fields: FormField[] = [
  { key: 'task_number', label: '生产任务单号' },
  { key: 'follower_ids', label: '生产跟单员', type: 'followers' },
  { key: 'salesperson_id', label: '业务员', type: 'salesperson' },
  { key: 'order_date', label: '下单日期', type: 'date' },
  { key: 'delivery_date', label: '交期', type: 'date' },
  { key: 'includes_tax', label: '是否含税', type: 'boolean', optional: true },
  { key: 'tax_rate', label: '税率', type: 'tax', optional: true },
  { key: 'order_tolerance_percent', label: '订单误差（%）' },
  { key: 'is_repeat_order', label: '是否返单', type: 'boolean' },
  { key: 'delivery_method', label: '交货方式', type: 'delivery' },
  { key: 'preproduction_sample_required', label: '产前确认样', type: 'boolean' },
  { key: 'production_priority', label: '生产优先级', type: 'priority', optional: true },
  { key: 'planned_start_date', label: '计划开始', type: 'date', optional: true },
  { key: 'planned_end_date', label: '计划完工', type: 'date', optional: true },
  { key: 'production_batch_number', label: '生产批号', optional: true },
]
const present = (value: unknown) => value !== '' && value !== null && value !== undefined && (!Array.isArray(value) || value.length > 0)
const mainFieldKeys: FieldKey[] = ['task_number', 'order_date', 'delivery_date', 'salesperson_id', 'follower_ids', 'order_tolerance_percent', 'is_repeat_order', 'delivery_method', 'preproduction_sample_required', 'includes_tax', 'planned_start_date', 'planned_end_date']
const groups = [
  { key: 'main', fields: mainFieldKeys.map(key => fields.find(field => field.key === key)!) },
  { key: 'more', fields: fields.filter(field => !mainFieldKeys.includes(field.key)) },
]
const pendingFields = computed(() => fields.filter(field => !present(draft.value[field.key]) && (!field.optional || field.key === 'tax_rate' && draft.value.includes_tax === true)))
const sourceNotes = computed(() => fields.map(field => ({ label: field.label, note: sourceNote(field) })).filter(field => field.note))
const rawTask = computed(() => sourceObject(props.result.task))
const sourceContract = computed(() => extractedText(rawTask.value.contract_number))
const productSources = computed(() => Array.isArray(props.result.products) ? props.result.products.map(sourceObject) : [])
const mappedSourceKeys = new Set([...fields.map(field => field.key), 'contract_number', 'special_requirements', 'special_requirements_html', 'salesperson_name', 'salesperson', 'follower_names', 'followers', 'follower_name', 'freight_amount', 'other_fee_amount', 'delivery_batches'])
const unmapped = computed(() => Object.entries(rawTask.value).filter(([name, value]) => {
  const field = sourceObject(value)
  return !mappedSourceKeys.has(name as FieldKey) && field.status !== 'MISSING' && present('value' in field ? field.value : value)
}))
const unmappedTargets = ref<Record<string, FieldKey | ''>>({})
const unmappedValues = ref<Record<string, string>>({})
const sourceFieldLabels: Record<string, string> = { customer_name: '客户名称', packaging_requirements: '订单包装要求', currency: '币种', item_number: '货号' }
const totalQuantity = computed(() => draft.value.products.some(row => !/^[1-9]\d*$/.test(String(row.quantity))) ? '待补齐' : draft.value.products.reduce((total, row) => total + Number(row.quantity), 0))

function publish() { draftPublished = true; emit('update:modelValue', copy(draft.value) as unknown as Record<string, unknown>) }
watch(draft, publish, { deep: true })
watch(() => props.modelValue, value => {
  if (value && JSON.stringify(value) !== JSON.stringify(draft.value)) {
    draft.value = restoreTaskDraft(props.result, value)
  }
}, { deep: true })

function updateField(field: FormField, value: unknown) {
  const target = draft.value as unknown as Record<string, unknown>
  target[field.key] = field.type === 'followers' ? (Array.isArray(value) ? value : []) : field.type === 'boolean' || field.type === 'tax' ? value ?? null : value ?? ''
  if (field.key === 'includes_tax' && value !== true) draft.value.tax_rate = null
  if (field.key === 'order_date' && reservedOrderDate && value !== reservedOrderDate) {
    draft.value.contract_number = ''; draft.value.contract_number_token = ''; reservedOrderDate = ''
  }
}

function sourceNote(field: FormField): string {
  const aliases: Partial<Record<FieldKey, string>> = { salesperson_id: 'salesperson_name', follower_ids: 'follower_names' }
  const fallback: Partial<Record<FieldKey, string>> = { salesperson_id: 'salesperson', follower_ids: 'followers' }
  const source = sourceObject(rawTask.value[aliases[field.key] || field.key] ?? rawTask.value[fallback[field.key] || field.key])
  if (source.status === 'CONFLICT') return `原表有冲突：${String(source.value ?? source.note ?? '')}`
  if (source.status === 'UNREADABLE') return `待确认：${String(source.note || '原表内容未能读取')}`
  if (source.status === 'DEFAULTED') return String(source.note || '按已确认的缺失规则填写')
  if ((field.type === 'salesperson' || field.type === 'followers') && present(source.value)) return `原表：${String(source.value)}`
  return ''
}

function choices(field: FormField): Array<{ value: string | number | boolean; label: string }> {
  if (field.type === 'boolean') return [{ value: true, label: field.key === 'includes_tax' ? '含税' : '是' }, { value: false, label: field.key === 'includes_tax' ? '不含税' : '否' }]
  if (field.type === 'salesperson') return (options.value?.salespeople || []).map(row => ({ value: row.id, label: row.display_name }))
  if (field.type === 'followers') return (options.value?.employees || []).map(row => ({ value: row.id, label: row.display_name }))
  if (field.type === 'delivery') return [{ value: 'SINGLE', label: '一次交货' }, { value: 'SPLIT', label: '分批交货' }]
  if (field.type === 'tax') return [3, 5, 7].map(value => ({ value, label: `${value}%` }))
  if (field.type === 'priority') return [{ value: 'URGENT', label: '紧急' }, { value: 'HIGH', label: '高' }, { value: 'NORMAL', label: '普通' }, { value: 'LOW', label: '低' }]
  return []
}

function selectProduct(index: number, id: string | null) {
  const row = draft.value.products[index]
  if (!row) return
  row.product_id = id || null
  const product = options.value?.products.find(item => item.id === id)
  if (!product) return
  if (!row.customer_product_name) row.customer_product_name = product.product_name
  if (!row.customer_specification) row.customer_specification = product.specification
  if (!row.unit_id) row.unit_id = product.default_unit_id
}

function sourceText(index: number): string {
  return Object.entries(productSources.value[index] || {}).filter(([key]) => key !== 'product_key').map(([key, value]) => {
    const field = sourceObject(value)
    const label: Record<string, string> = { ...sourceFieldLabels, name: '名称', specification: '规格', color: '颜色', color_card: '色卡', color_code: '色号', material: '材质', quantity: '数量', unit: '单位', unit_price: '单价', unit_price_cny: '人民币单价', special_requirements: '生产要求', packaging_method: '包装要求', product_code: '产品编码' }
    return present(field.value ?? value) && typeof (field.value ?? value) !== 'object' ? `${label[key] || key}：${String(field.value ?? value)}${field.status === 'CONFLICT' ? '（冲突）' : ''}` : ''
  }).filter(Boolean).join('\n')
}

function addDetail(index: number) {
  draft.value.products[index]?.details.push({ client_key: crypto.randomUUID(), template_key: '', detail_type: '', category_label: '', is_selected: null, description: '' })
}

function selectCurrency(index: number, id: string | null) {
  const row = draft.value.products[index]
  if (!row) return
  row.currency_id = id || ''
  row.exchange_rate = options.value?.currencies.find(item => item.id === id)?.code === 'CNY' ? '1.00000000' : ''
  const values = [...new Set(draft.value.products.map(item => item.currency_id))]
  draft.value.currency_id = values.length === 1 ? values[0]! : ''
}

function addBatch() {
  draft.value.delivery_batches.push({ batch_key: crypto.randomUUID(), product_key: '', color: '', packaging_method: '', carton_quantity: '', quantity: '', delivery_date: '', note: '' })
}

function assignUnmapped(name: string, source: unknown) {
  const field = fields.find(item => item.key === unmappedTargets.value[name])
  if (!field) return
  const value = unmappedValues.value[name] ?? extractedText(source)
  if (field.type === 'boolean') updateField(field, ['是', '含税', 'true'].includes(value) ? true : ['否', '不含税', 'false'].includes(value) ? false : null)
  else if (field.type === 'salesperson' || field.type === 'followers') {
    const matches = choices(field).filter(item => item.label === value)
    if (matches.length === 1) updateField(field, field.type === 'followers' ? [matches[0]!.value] : matches[0]!.value)
    else fieldError.value = '人员名称无法唯一对应，请在上方选择。'
  } else if (field.type === 'tax') updateField(field, [3, 5, 7].includes(Number(value)) ? Number(value) : null)
  else if (['delivery', 'priority'].includes(field.type || '')) {
    const choice = choices(field).find(item => item.label === value || item.value === value)
    updateField(field, choice?.value || '')
  } else updateField(field, value)
}

async function loadOptions() {
  loading.value = true; loadError.value = ''
  try {
    options.value = await fetchProductionTaskOptions({ timeout: 30_000 })
  } catch (error) {
    const status = isAxiosError(error) ? error.response?.status : undefined
    loadError.value = status === 401 ? '登录已失效，请重新登录后加载基础资料。'
      : status === 403 ? '当前账号没有读取生产基础资料的权限。'
        : isAxiosError(error) && ['ECONNABORTED', 'ETIMEDOUT'].includes(error.code || '')
          ? '基础资料加载超时，请重试。当前填写内容已保留。'
          : '基础资料加载失败，请检查连接后重试。当前填写内容已保留。'
    return
  } finally { loading.value = false }
  if (!savedInitially && !props.modelValue && !draftPublished) applyTaskOptions(draft.value, props.result, options.value)
  publish()
}

async function buildPayload(): Promise<Record<string, unknown>> {
  fieldError.value = ''
  try {
    if (!options.value || loadError.value) throw new Error('请先成功加载基础资料。')
    const payload = taskPayload(copy(draft.value), options.value)
    // 只有全部必填项校验通过后才申请编号，避免预览消耗合同号。
    if (!payload.contract_number_token || !payload.contract_number || reservedOrderDate !== payload.order_date) {
      const reserved = await reserveProductionTaskContractNumber(payload.order_date)
      payload.contract_number = reserved.contract_number; payload.contract_number_token = reserved.token
      draft.value.contract_number = reserved.contract_number; draft.value.contract_number_token = reserved.token
      reservedOrderDate = payload.order_date; publish()
    }
    return payload as unknown as Record<string, unknown>
  } catch (error) {
    fieldError.value = error instanceof Error ? error.message : '生产任务校验失败，请重试。'
    throw error
  }
}
defineExpose({ buildPayload })
onMounted(loadOptions)
</script>

<template>
  <section v-loading="loading" class="ai-task-form" aria-label="生产任务单表单">
    <div class="task-heading">
      <h2>生产任务单</h2>
      <button type="button" class="task-text-button" :aria-expanded="showMore" @click="showMore = !showMore">更多任务信息 <span aria-hidden="true">{{ showMore ? '⌃' : '⌄' }}</span></button>
    </div>
    <div v-if="loadError" class="form-error" role="alert">{{ loadError }} <el-button link @click="loadOptions">重新加载</el-button></div>
    <el-alert v-if="fieldError" :title="fieldError" type="error" :closable="false" />
    <fieldset :disabled="disabled || loading" class="form-body">
      <section v-for="group in groups" v-show="group.key === 'main' || showMore" :key="group.key" class="task-fields" :class="{ 'more-fields': group.key === 'more' }" :aria-label="group.key === 'main' ? '任务信息' : '更多任务信息'">
        <div class="field-grid">
          <template v-for="field in group.fields" :key="field.key">
            <label v-if="field.key !== 'tax_rate' || draft.includes_tax" :class="{ missing: !field.optional && !present(draft[field.key]) }">
              <span class="field-label"><i v-if="!field.optional">*</i>{{ field.label }}
                <el-tooltip v-if="sourceNote(field)" :content="sourceNote(field)" placement="top">
                  <button type="button" class="source-note" :aria-label="`${field.label}：${sourceNote(field)}`">i</button>
                </el-tooltip>
              </span>
              <el-date-picker v-if="field.type === 'date'" :model-value="draft[field.key]" type="date" value-format="YYYY-MM-DD" :aria-label="field.label" :disabled="disabled || loading" placeholder="请选择日期" @update:model-value="updateField(field, $event)" />
              <el-select v-else-if="field.type" :model-value="draft[field.key]" :multiple="field.type === 'followers'" collapse-tags collapse-tags-tooltip filterable clearable :aria-label="field.label" :disabled="disabled || loading" placeholder="待选择" @update:model-value="updateField(field, $event)">
                <el-option v-for="option in choices(field)" :key="String(option.value)" :value="option.value" :label="option.label" />
              </el-select>
              <el-input v-else :model-value="draft[field.key]" :aria-label="field.label" :disabled="disabled || loading" :placeholder="field.key === 'task_number' ? '例如 HT26199' : field.optional ? '选填' : '待补充'" @update:model-value="updateField(field, $event)" />
            </label>
          </template>
        </div>
      </section>
      <div v-show="showMore" class="task-extra">
        <div class="contract-note">ERP 合同号：{{ draft.contract_number || '确认创建时生成' }}<span v-if="sourceContract"> · 原表合同号：{{ sourceContract }}</span></div>
        <div class="totals"><span>数量合计：{{ totalQuantity }}</span><label>运费 <el-input v-model="draft.freight_amount" aria-label="运费" placeholder="待补充" :disabled="disabled" /></label><label>其他费用 <el-input v-model="draft.other_fee_amount" aria-label="其他费用" placeholder="待补充" :disabled="disabled" /></label></div>
        <label class="order-requirements"><span>订单特殊要求</span><el-input v-model="draft.special_requirements_html" aria-label="订单特殊要求" type="textarea" :rows="2" :disabled="disabled" /></label>
      </div>

      <div class="product-heading"><h3>产品明细</h3><button type="button" class="task-text-button" :aria-expanded="showProductionDetails" @click="showProductionDetails = !showProductionDetails">生产明细 <span aria-hidden="true">{{ showProductionDetails ? '⌃' : '›' }}</span></button></div>
      <el-table :data="draft.products" class="erp-table-editor product-table" row-key="client_key" empty-text="没有识别到产品，请核对原表" border>
        <el-table-column type="index" label="序号" width="54" align="center" />
        <el-table-column label="产品名称" min-width="150"><template #default="{ row }"><el-input v-model="row.customer_product_name" aria-label="产品名称" :disabled="disabled" @change="row.product_id = null" /></template></el-table-column>
        <el-table-column label="规格" min-width="210"><template #default="{ row }"><el-input v-model="row.customer_specification" aria-label="产品规格" :disabled="disabled" @change="row.product_id = null" /></template></el-table-column>
        <el-table-column label="颜色" min-width="110"><template #default="{ row }"><el-input v-model="row.customer_color" aria-label="产品颜色" :disabled="disabled" @change="row.product_color_id = null; row.color_code = ''" /></template></el-table-column>
        <el-table-column min-width="105"><template #header><span class="required">*</span>数量</template><template #default="{ row }"><el-input v-model="row.quantity" aria-label="产品数量" inputmode="numeric" placeholder="待补充" :disabled="disabled" /></template></el-table-column>
        <el-table-column min-width="105"><template #header><span class="required">*</span>单位</template><template #default="{ row }"><el-select v-model="row.unit_id" clearable filterable aria-label="产品单位" placeholder="请选择" :disabled="disabled"><el-option v-for="unit in options?.units || []" :key="unit.id" :value="unit.id" :label="unit.unit_name" /></el-select></template></el-table-column>
        <el-table-column label="包装要求" min-width="180"><template #default="{ row }"><el-input v-model="row.packaging_method" aria-label="产品包装要求" :disabled="disabled" /></template></el-table-column>
        <el-table-column min-width="140"><template #header><span class="price-heading">单价<el-tooltip content="按原表币种填写，未知价税留待补充；币种和汇率在编辑中核对。"><button type="button" class="source-note" aria-label="按原表币种填写，未知价税留待补充；币种和汇率在编辑中核对。">i</button></el-tooltip></span></template><template #default="{ row }"><el-input v-model="row.unit_price" aria-label="产品单价" inputmode="decimal" placeholder="待补充" :disabled="disabled"><template #suffix>{{ options?.currencies.find(item => item.id === row.currency_id)?.code || row.source_currency }}</template></el-input></template></el-table-column>
        <el-table-column label="操作" width="74" align="center"><template #default="{ row }"><button type="button" class="task-text-button" :aria-label="`编辑${row.customer_product_name || '产品'}资料`" :aria-expanded="editingProductKey === row.client_key" @click="editingProductKey = editingProductKey === row.client_key ? '' : row.client_key">{{ editingProductKey === row.client_key ? '收起' : '编辑' }}</button></template></el-table-column>
      </el-table>

      <template v-for="(product, index) in draft.products" :key="product.client_key">
        <section v-show="editingProductKey === product.client_key" class="product-extra" :aria-label="`${product.customer_product_name || `产品 ${index + 1}`}补充资料`">
          <div class="subsection-heading"><h3>{{ product.customer_product_name || `产品 ${index + 1}` }} · 补充资料</h3><button type="button" class="task-text-button" @click="editingProductKey = ''">收起</button></div>
          <div class="field-grid">
            <label class="wide-field"><span>对应 ERP 产品</span><el-select :model-value="product.product_id" clearable filterable aria-label="对应 ERP 产品" placeholder="可选择现有产品" :disabled="disabled" @update:model-value="selectProduct(index, $event)"><el-option v-for="item in options?.products || []" :key="item.id" :value="item.id" :label="[item.product_name, item.product_code, item.specification].filter(Boolean).join(' · ')" /></el-select></label>
            <label><span>色卡</span><el-input v-model="product.source_color_card" aria-label="产品色卡" :disabled="disabled" @change="product.product_color_id = null" /></label>
            <label><span>色号</span><el-input v-model="product.color_code" aria-label="产品色号" :disabled="disabled" @change="product.product_color_id = null" /></label>
            <label><span>材质</span><el-input v-model="product.material" aria-label="产品材质" :disabled="disabled" /></label>
            <label><span>币种 <el-tooltip v-if="product.source_currency" :content="`原表：${product.source_currency}`"><button type="button" class="source-note" :aria-label="`币种原表：${product.source_currency}`">i</button></el-tooltip></span><el-select :model-value="product.currency_id" clearable aria-label="产品币种" placeholder="待确认" :disabled="disabled" @update:model-value="selectCurrency(index, $event)"><el-option v-for="currency in options?.currencies || []" :key="currency.id" :value="currency.id" :label="currency.code" /></el-select></label>
            <label><span>汇率</span><el-input v-model="product.exchange_rate" aria-label="产品汇率" inputmode="decimal" placeholder="待补充" :disabled="disabled || options?.currencies.find(item => item.id === product.currency_id)?.code === 'CNY'" /></label>
            <label><span>本次金额</span><output class="amount-value">{{ product.quantity !== '' && product.unit_price !== '' && Number.isFinite(Number(product.quantity) * Number(product.unit_price)) ? (Number(product.quantity) * Number(product.unit_price)).toFixed(2) : '—' }}</output></label>
          </div>
          <details class="source-details"><summary>原表识别内容</summary><pre class="source-text">{{ sourceText(index) }}</pre></details>
        </section>
      </template>

      <section v-if="draft.delivery_method === 'SPLIT' || draft.delivery_batches.length" class="delivery-batches" aria-label="交货批次">
        <div class="subsection-heading"><h3>交货批次</h3><el-button link :disabled="disabled" @click="addBatch">添加批次</el-button></div>
        <el-table :data="draft.delivery_batches" class="erp-table-editor" border>
          <el-table-column label="产品" min-width="180"><template #default="{ row }"><el-select v-model="row.product_key" clearable aria-label="批次产品" placeholder="任务整体或选择产品" :disabled="disabled"><el-option v-for="product in draft.products" :key="product.client_key" :value="product.client_key" :label="product.customer_product_name || product.client_key" /></el-select></template></el-table-column>
          <el-table-column label="颜色" min-width="110"><template #default="{ row }"><el-input v-model="row.color" aria-label="批次颜色" :disabled="disabled" /></template></el-table-column>
          <el-table-column label="数量" min-width="110"><template #default="{ row }"><el-input v-model="row.quantity" aria-label="批次数量" :disabled="disabled" /></template></el-table-column>
          <el-table-column label="箱数" min-width="110"><template #default="{ row }"><el-input v-model="row.carton_quantity" aria-label="批次箱数" :disabled="disabled" /></template></el-table-column>
          <el-table-column label="交期" min-width="160"><template #default="{ row }"><el-date-picker v-model="row.delivery_date" type="date" value-format="YYYY-MM-DD" aria-label="批次交期" :disabled="disabled" /></template></el-table-column>
          <el-table-column label="包装方式" min-width="190"><template #default="{ row }"><el-input v-model="row.packaging_method" aria-label="批次包装方式" :disabled="disabled" /></template></el-table-column>
          <el-table-column label="备注" min-width="190"><template #default="{ row }"><el-input v-model="row.note" aria-label="批次备注" :disabled="disabled" /></template></el-table-column>
          <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link type="danger" :disabled="disabled" @click="draft.delivery_batches.splice($index, 1)">移除</el-button></template></el-table-column>
        </el-table>
      </section>
      <div v-show="showProductionDetails" class="production-details" aria-label="全部生产明细">
        <div v-for="(product, index) in draft.products" :key="product.client_key" class="product-requirements">
          <h3>{{ product.customer_product_name || `产品 ${index + 1}` }} · 生产要求</h3>
          <div class="requirement-grid"><label><span>生产要求</span><el-input v-model="product.special_requirements" aria-label="产品生产要求" type="textarea" :rows="2" :disabled="disabled" /></label><label><span>包装要求</span><el-input v-model="product.packaging_method" aria-label="完整包装要求" type="textarea" :rows="2" :disabled="disabled" /></label></div>
          <el-collapse><el-collapse-item :title="`生产明细（${product.details?.length || 0} 项）`"><el-table :data="product.details" class="erp-table-editor" border>
            <el-table-column min-width="160"><template #header><span class="required">*</span>类型</template><template #default="{ row }"><el-input v-model="row.detail_type" aria-label="生产明细类型" :disabled="disabled" /></template></el-table-column>
            <el-table-column label="类别项" min-width="130"><template #default="{ row }"><el-input v-model="row.category_label" aria-label="生产明细类别项" :disabled="disabled" /></template></el-table-column>
            <el-table-column label="是否" width="130"><template #default="{ row }"><el-select v-model="row.is_selected" clearable placeholder="待确认" aria-label="明细是否需要" :disabled="disabled" @clear="row.is_selected = null"><el-option :value="true" label="是" /><el-option :value="false" label="否" /></el-select></template></el-table-column>
            <el-table-column label="描述" min-width="260"><template #default="{ row }"><div class="detail-description"><el-input v-model="row.description" aria-label="生产明细描述" :disabled="disabled" /><el-tooltip v-if="row.source_note" :content="row.source_note"><button type="button" class="source-note" :aria-label="`生产明细来源：${row.source_note}`">i</button></el-tooltip></div></template></el-table-column>
            <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button link type="danger" :disabled="disabled" @click="product.details.splice($index, 1)">移除</el-button></template></el-table-column>
          </el-table><el-button class="add-detail" :disabled="disabled" @click="addDetail(index)">添加明细</el-button></el-collapse-item></el-collapse>
        </div>
      </div>

      <details class="pending-content" @toggle="pendingOpen = ($event.target as HTMLDetailsElement).open">
        <summary><span class="pending-label">待补与未对应内容</span><span class="pending-summary">{{ [...pendingFields.map(field => field.label), ...unmapped.map(([name]) => sourceFieldLabels[name] || name)].slice(0, 3).join('、') || '无必填待补项' }}{{ pendingFields.length + unmapped.length > 3 ? '等' : '' }}</span><span class="pending-action">{{ pendingOpen ? '收起核对' : '展开核对' }}</span></summary>
        <div class="pending-body">
          <div v-if="pendingFields.length" class="pending-list"><h3>待选与补充</h3><p v-for="field in pendingFields" :key="field.key">{{ field.label }}：待补充<span v-if="sourceNote(field)"> · {{ sourceNote(field) }}</span><button v-if="!mainFieldKeys.includes(field.key)" type="button" class="task-text-button" @click="showMore = true">打开更多任务信息</button></p></div>
          <div v-if="unmapped.length" class="unmapped-fields"><h3>尚未对应的原表信息</h3><div v-for="[name, value] in unmapped" :key="name" class="unmapped-row"><span>{{ sourceFieldLabels[name] || name }}</span><el-input :model-value="unmappedValues[name] ?? extractedText(value)" :aria-label="`${sourceFieldLabels[name] || name}原文`" :disabled="disabled" @update:model-value="unmappedValues[name] = $event" /><el-select v-model="unmappedTargets[name]" aria-label="选择对应字段" placeholder="选择对应字段" clearable :disabled="disabled"><el-option v-for="field in fields" :key="field.key" :value="field.key" :label="field.label" /></el-select><el-button :disabled="disabled || !unmappedTargets[name]" @click="assignUnmapped(name, value)">填入</el-button></div></div>
          <details v-if="sourceNotes.length" class="source-details"><summary>字段来源与规则说明</summary><p v-for="field in sourceNotes" :key="field.label">{{ field.label }}：{{ field.note }}</p></details>
        </div>
      </details>
    </fieldset>
  </section>
</template>

<style scoped>
.ai-task-form { min-width: 0; color: var(--erp-color-text-primary); font-size: 13px; }
.task-heading, .product-heading, .subsection-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.task-heading { min-height: 44px; }
.task-heading h2 { margin: 0; font-size: 18px; line-height: 26px; font-weight: 650; }
.task-text-button { display: inline-flex; align-items: center; gap: 6px; padding: 0 4px; min-height: 28px; border: 0; background: none; box-shadow: none; color: var(--el-color-primary); font: inherit; font-size: 12px; white-space: nowrap; cursor: pointer; }
.task-text-button:focus-visible, .source-note:focus-visible, summary:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.task-text-button:disabled, .source-note:disabled { cursor: default; color: var(--erp-color-text-disabled); }
.form-body { min-width: 0; border: 0; padding: 0; margin: 0; }
h3 { font-size: 13px; line-height: 20px; font-weight: 600; margin: 0; }
.field-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); column-gap: 18px; row-gap: 10px; }
.field-grid label, .requirement-grid label, .order-requirements { display: grid; gap: 5px; min-width: 0; }
label > span { font-size: 12px; line-height: 18px; color: var(--erp-color-text-secondary); }
.field-label, .price-heading { display: inline-flex; align-items: center; gap: 4px; }
label i, .required { color: var(--el-color-danger); font-style: normal; margin-right: 3px; }
.source-note { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; padding: 0; border: 1px solid currentColor; border-radius: 50%; color: var(--erp-color-text-secondary); background: none; box-shadow: none; font-size: 10px; line-height: 1; cursor: help; vertical-align: middle; flex: 0 0 16px; }
.field-grid :deep(.el-select), .field-grid :deep(.el-date-editor), .erp-table-editor :deep(.el-select), .erp-table-editor :deep(.el-date-editor) { width: 100%; }
.ai-task-form :deep(.el-input), .ai-task-form :deep(.el-date-editor), .ai-task-form :deep(.el-select) { --el-component-size: 32px; --el-input-height: 32px; font-size: 13px; }
.ai-task-form :deep(.el-input__wrapper), .ai-task-form :deep(.el-select__wrapper) { min-height: 32px; box-sizing: border-box; border-radius: 5px; padding: 0 10px; }
.ai-task-form :deep(.el-input__inner), .ai-task-form :deep(.el-select__selected-item) { font-size: 13px; }
.ai-task-form :deep(.el-textarea__inner) { font-size: 13px; border-radius: 5px; }
.missing :deep(.el-input__wrapper), .missing :deep(.el-select__wrapper) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; }
.more-fields, .task-extra, .product-extra { margin-top: 12px; }
.contract-note { color: var(--erp-color-text-secondary); font-size: 12px; }
.form-error { color: var(--el-color-danger); margin: 8px 0; }
.ai-task-form :deep(.el-alert) { margin-bottom: 10px; }
.product-heading { height: 34px; margin-top: 7px; }
.subsection-heading { min-height: 34px; }
.product-table { width: 100%; }
.ai-task-form :deep(.erp-table-editor) { --el-table-header-bg-color: var(--erp-table-header-fill); --el-table-tr-bg-color: var(--erp-table-body-fill); --el-table-bg-color: var(--erp-table-body-fill); --el-table-border-color: var(--erp-table-grid); --el-table-row-hover-bg-color: var(--erp-table-hover); --el-table-text-color: var(--erp-table-text); --el-table-header-text-color: var(--erp-table-header-text); font-size: 12px; }
.ai-task-form :deep(.erp-table-editor th.el-table__cell) { height: 44px; padding: 0; font-weight: 500; background: var(--erp-table-header-fill); }
.ai-task-form :deep(.erp-table-editor td.el-table__cell) { height: 34px; padding: 0; }
.ai-task-form :deep(.erp-table-editor .cell) { padding: 0 10px; font-size: 12px; line-height: 18px; white-space: nowrap; }
.ai-task-form :deep(.erp-table-editor .el-input__wrapper), .ai-task-form :deep(.erp-table-editor .el-select__wrapper) { min-height: 30px; height: 30px; box-shadow: none; background: transparent; padding: 0 2px; }
.ai-task-form :deep(.erp-table-editor .el-input__wrapper.is-focus), .ai-task-form :deep(.erp-table-editor .el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px var(--el-color-primary) inset; }
.ai-task-form :deep(.erp-table-editor .el-input__inner) { height: 30px; }
/* 主产品表以单元格呈现；局部覆盖共享编辑器的实色底和边缘，聚焦时仍显示编辑边缘。 */
.ai-task-form :deep(.product-table .el-input:not(.is-disabled) .el-input__wrapper), .ai-task-form :deep(.product-table .el-select__wrapper:not(.is-disabled)) { background: transparent !important; box-shadow: none !important; }
.ai-task-form :deep(.product-table .el-input:not(.is-disabled) .el-input__wrapper.is-focus), .ai-task-form :deep(.product-table .el-select__wrapper.is-focused:not(.is-disabled)) { box-shadow: 0 0 0 1px var(--el-color-primary) inset !important; }
.ai-task-form :deep(.product-table .cell) { padding: 0 16px; }
.ai-task-form :deep(.product-table th:first-child .cell), .ai-task-form :deep(.product-table td:first-child .cell) { padding: 0 6px; }
.source-text { white-space: pre-wrap; margin: 8px 0 0; font: inherit; line-height: 1.6; max-height: 180px; overflow: auto; }
.source-details { margin-top: 10px; color: var(--erp-color-text-secondary); font-size: 12px; }
.source-details summary { cursor: pointer; min-height: 24px; line-height: 24px; }
.source-details p, .pending-list p { margin: 6px 0; line-height: 20px; }
.totals { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; margin: 10px 0; font-size: 12px; }
.totals label { display: flex; gap: 8px; align-items: center; }
.totals .el-input { width: 130px; }
.wide-field { grid-column: span 2; }
.amount-value { height: 32px; line-height: 32px; font-variant-numeric: tabular-nums; }
.requirement-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 8px 0; }
.product-requirements, .delivery-batches { margin-top: 12px; }
.detail-description { display: flex; align-items: center; gap: 6px; }
.add-detail { margin-top: 8px; }
.production-details :deep(.el-collapse) { --el-collapse-header-height: 34px; --el-collapse-header-font-size: 12px; --el-collapse-header-bg-color: transparent; --el-collapse-content-bg-color: transparent; }
.production-details :deep(.el-collapse-item__content) { padding-bottom: 8px; }
.pending-content { margin-top: 0; }
.pending-content > summary { display: flex; align-items: center; gap: 14px; min-height: 37px; font-size: 12px; cursor: pointer; list-style: none; }
.pending-content > summary::-webkit-details-marker { display: none; }
.pending-label { color: var(--erp-color-text-secondary); flex-shrink: 0; }
.pending-summary { color: var(--erp-color-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pending-action { margin-left: auto; color: var(--el-color-primary); flex-shrink: 0; }
.pending-body { padding: 4px 0 12px; }
.unmapped-row { display: grid; grid-template-columns: 120px minmax(0, 1fr) 200px auto; gap: 12px; align-items: center; margin: 8px 0; }
@media (max-width: 1280px) { .field-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .field-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.requirement-grid, .unmapped-row { grid-template-columns: 1fr; }.pending-summary { display: none; } }
@media (max-width: 480px) { .field-grid { grid-template-columns: 1fr; }.wide-field { grid-column: auto; }.task-heading { align-items: flex-start; flex-direction: column; padding-bottom: 8px; gap: 0; } }
</style>
