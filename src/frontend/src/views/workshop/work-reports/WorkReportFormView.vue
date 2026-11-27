<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createWorkReport, fetchPriceContext, fetchReportingContext, fetchWorkReport, updateWorkReport } from '@/api/workshopReporting'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import CuttingGroupCell from '@/components/workshop/CuttingGroupCell.vue'
import WorkshopConfigManager from '@/components/workshop/WorkshopConfigManager.vue'
import { useAuthStore } from '@/stores/auth'
import type { ReportingContext, WageScheme } from '@/types/workshopReporting'
import { focusTableInputBelow } from '@/utils/tableInputFocus'
import { formatWageMoney, reportLineAmount, sumWageAmounts } from '@/utils/wageMoney'

interface EntryLine { key: number; scheme_line_id: string; workshop_employee_id: string; production_line: number | null; quantity: string }
interface ReportRow {
  key: string | number
  scheme_line_id: string
  entries: EntryLine[]
  employeeIds: string[]
  employees: { id: string; entries: EntryLine[] }[]
}
const assemblyLines = [1, 2, 3]
const route = useRoute(); const router = useRouter()
const auth = useAuthStore()
const isEdit = computed(() => Boolean(route.params.reportId))
const context = ref<ReportingContext | null>(null); const scheme = ref<WageScheme | null>(null)
const loading = ref(false); const saving = ref(false); const etag = ref('')
const hydrating = ref(false)
const managerVisible = ref(false)
const inactiveEmployeeNames = ref<Record<string, string>>({})
let priceRequestSequence = 0
let nextRowKey = 0
const shanghaiToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const form = reactive({ scheduleProductId: String(route.query.schedule_product_id || ''), workshopId: String(route.query.workshop_id || ''), craftId: String(route.query.craft_id || ''), productionDate: shanghaiToday(), lines: [] as EntryLine[] })
const bulkAssemblyLine = ref<number | null>(null)
const commonAssemblyLine = computed(() => {
  const line = form.lines[0]?.production_line ?? null
  return form.lines.every(entry => entry.production_line === line) ? line : null
})
const originalQuantityBySchemeLine = ref<Record<string, number>>({})
let pendingRequestId = ''
let pendingPayloadKey = ''
const scheduleProduct = computed(() => {
  if (context.value?.schedule_product?.id === form.scheduleProductId) return context.value.schedule_product
  return context.value?.schedule_products.find(item => item.id === form.scheduleProductId) || null
})
const employeeOptions = computed(() => context.value?.employees.filter(item => item.workshop_id === form.workshopId) || [])
const craftOptions = computed(() => context.value?.crafts.filter(item => item.workshop_id === form.workshopId) || [])
const isAssembly = computed(() => route.query.plan_category === 'ASSEMBLY'
  || craftOptions.value.some(item => item.id === form.craftId && item.plan_category === 'ASSEMBLY')
  || context.value?.workshops.find(item => item.id === form.workshopId)?.name === '装配车间')
const canManageEmployees = computed(() => !isEdit.value && !!form.workshopId
  && (auth.user?.is_superuser || auth.hasPermission('workshop_config.view_workshopemployee')))
const quantityText = (value: string | number | null | undefined) => {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—'
}
function lineAmount(row: EntryLine) { return reportLineAmount(schemeLine(row.scheme_line_id)?.declared_price, row.quantity) }
const total = computed(() => sumWageAmounts(form.lines.map(lineAmount)))
const errorText = (error: unknown) => (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message || '操作失败。'
function schemeLine(id: string) { return scheme.value?.lines.find(item => item.id === id) }
function buildInitialLines(value: WageScheme) {
  bulkAssemblyLine.value = null
  originalQuantityBySchemeLine.value = {}
  form.lines = value.lines.filter(item => item.status === 'ACTIVE').flatMap(item => {
    const roster = item.last_employees ?? (item.last_workshop_employee_id
      ? [{ workshop_employee_id: item.last_workshop_employee_id, production_line: null }] : [])
    const available = roster.filter(member => employeeOptions.value.some(employee => employee.id === member.workshop_employee_id))
    const selected = isAssembly.value ? available : available.slice(0, 1)
    return selected.length
      ? selected.map(member => emptyEntry(item.id, member.workshop_employee_id, isAssembly.value ? member.production_line : null))
      : [emptyEntry(item.id)]
  })
}
function emptyEntry(id: string, employee = '', line: number | null = null): EntryLine {
  return { key: ++nextRowKey, scheme_line_id: id, workshop_employee_id: employee, production_line: line, quantity: '' }
}
const rowsByOperation = computed(() => {
  const grouped = new Map<string, EntryLine[]>()
  for (const row of form.lines) {
    const group = grouped.get(row.scheme_line_id)
    if (group) group.push(row)
    else grouped.set(row.scheme_line_id, [row])
  }
  return grouped
})
const reportRows = computed<ReportRow[]>(() => {
  if (!isAssembly.value) {
    return form.lines.map(entry => ({
      key: entry.key, scheme_line_id: entry.scheme_line_id, entries: [entry],
      employeeIds: entry.workshop_employee_id ? [entry.workshop_employee_id] : [], employees: [],
    }))
  }
  return Array.from(rowsByOperation.value, ([schemeLineId, entries]) => {
    const employeeIds = [...new Set(entries.map(entry => entry.workshop_employee_id))]
    const employees = employeeIds.map(id => ({ id, entries: entries.filter(entry => entry.workshop_employee_id === id) }))
    return {
      key: schemeLineId, scheme_line_id: schemeLineId, entries: employees.flatMap(employee => employee.entries),
      employeeIds: employeeIds.filter(Boolean), employees,
    }
  })
})
function selectEmployees(row: ReportRow, employeeIds: string | string[]) {
  if (typeof employeeIds === 'string') {
    row.entries[0]!.workshop_employee_id = employeeIds
    return
  }
  const unassigned = row.entries.filter(entry => !entry.workshop_employee_id)
  const selected = employeeIds.flatMap(id => {
    const existing = row.employees.find(employee => employee.id === id)
    if (existing) return existing.entries
    const draft = unassigned.shift()
    return [draft ? { ...draft, workshop_employee_id: id } : emptyEntry(row.scheme_line_id, id, bulkAssemblyLine.value)]
  })
  selected.push(...unassigned)
  if (!selected.length) selected.push(emptyEntry(row.scheme_line_id, '', bulkAssemblyLine.value))
  const first = row.entries[0]
  form.lines = form.lines.flatMap(entry => {
    if (entry.key === first?.key) return selected
    return entry.scheme_line_id === row.scheme_line_id ? [] : [entry]
  })
}
function setAssemblyLine(line: number) {
  bulkAssemblyLine.value = line
  for (const entry of form.lines) entry.production_line = line
}
function employeeName(id: string) {
  return employeeOptions.value.find(item => item.id === id)?.name || inactiveEmployeeNames.value[id] || '未选员工'
}
function quantitySummary(row: ReportRow) {
  const quantities = row.entries.map(entry => entry.quantity.trim().replace(/\.0+$/, ''))
  return quantities.some(Boolean) ? quantities.join(',') : ''
}
function productionLineSummary(row: ReportRow) {
  return row.entries.map(entry => entry.production_line ? `${entry.production_line}线` : '—').join(', ')
}
function focusEmployeeField(id: string) {
  document.getElementById(id)?.querySelector<HTMLElement>('input, select')?.focus()
}
async function refreshEmployees() {
  const current = context.value
  if (!current) return
  try {
    const updated = await fetchReportingContext(form.scheduleProductId || undefined, 'work_report')
    if (context.value !== current) return
    inactiveEmployeeNames.value = { ...inactiveEmployeeNames.value, ...Object.fromEntries(employeeOptions.value.map(item => [item.id, item.name])) }
    context.value = { ...current, employees: updated.employees }
  } catch (error) { ElMessage.error(errorText(error)) }
}
function isBlankOrZeroQuantity(row: EntryLine) {
  const value = row.quantity.trim()
  return value === '' || Number(value) === 0
}
function currentSubmitted(schemeLineId: string) { return (rowsByOperation.value.get(schemeLineId) || []).reduce((sum, item) => sum + (Number(item.quantity) || 0), 0) }
function baseCumulative(schemeLineId: string) { return Math.max(0, Number(schemeLine(schemeLineId)?.cumulative_quantity || 0) - (originalQuantityBySchemeLine.value[schemeLineId] || 0)) }
function remainingQuantity(schemeLineId: string) {
  const required = Number(schemeLine(schemeLineId)?.required_quantity)
  return Number.isFinite(required) ? Math.max(0, required - baseCumulative(schemeLineId)) : 0
}
function overReportMessage(row: ReportRow) {
  if (!row.entries.some(entry => entry.quantity)) return ''
  const required = Number(schemeLine(row.scheme_line_id)?.required_quantity)
  if (!Number.isFinite(required) || required <= 0) return ''
  if (currentSubmitted(row.scheme_line_id) <= remainingQuantity(row.scheme_line_id)) return ''
  const remaining = remainingQuantity(row.scheme_line_id)
  return `当前最多可报 ${quantityText(remaining)}，超出 ${quantityText(currentSubmitted(row.scheme_line_id) - remaining)} 次`
}
function progressPercent(schemeLineId: string) {
  const required = Number(schemeLine(schemeLineId)?.required_quantity)
  if (!Number.isFinite(required) || required <= 0) return 0
  return Math.min(100, Math.max(0, Math.round((baseCumulative(schemeLineId) + currentSubmitted(schemeLineId)) * 100 / required)))
}
function willCompletePlan() {
  const lines = scheme.value?.lines.filter(item => item.status === 'ACTIVE') || []
  return lines.length > 0 && lines.every(line => (
    baseCumulative(line.id) + currentSubmitted(line.id) >= Number(line.required_quantity || 0)
  ))
}
async function loadPrice() {
  if (hydrating.value) return
  const current = ++priceRequestSequence
  scheme.value = null
  if (!scheduleProduct.value || !form.workshopId || !form.craftId || !form.productionDate) { form.lines = []; return }
  try {
    const result = await fetchPriceContext({ product_line_id: scheduleProduct.value.product_line_id, schedule_product_id: scheduleProduct.value.id, workshop_id: form.workshopId, craft_id: form.craftId, production_date: form.productionDate })
    if (current !== priceRequestSequence) return
    if (form.lines.some(line => line.workshop_employee_id || line.quantity)) ElMessage.warning('报工范围或日期已变化，原填写行已按新适用方案重新生成。')
    scheme.value = result; buildInitialLines(result)
  }
  catch (error) { if (current === priceRequestSequence) ElMessage.warning(errorText(error)) }
}
watch(() => [form.scheduleProductId, form.workshopId, form.craftId, form.productionDate], () => { void loadPrice() })
watch(craftOptions, options => {
  if (!form.craftId && options.length === 1) form.craftId = options[0]!.id
}, { immediate: true })
async function load() {
  loading.value = true; hydrating.value = true
  try {
    if (isEdit.value) {
      const result = await fetchWorkReport(String(route.params.reportId))
      etag.value = result.etag
      form.scheduleProductId = result.data.schedule_product_id
      form.workshopId = result.data.workshop.id
      form.craftId = result.data.scope_craft.id
      form.productionDate = result.data.production_date
      context.value = await fetchReportingContext(form.scheduleProductId, 'work_report')
      const product = scheduleProduct.value
      if (!product) throw new Error('原排产产品已不可访问。')
      scheme.value = await fetchPriceContext({ product_line_id: product.product_line_id, schedule_product_id: product.id, workshop_id: form.workshopId, craft_id: form.craftId, production_date: form.productionDate })
      form.lines = result.data.lines.map(item => ({ ...emptyEntry(item.scheme_line_id, item.workshop_employee_id, item.production_line), quantity: item.quantity }))
      inactiveEmployeeNames.value = Object.fromEntries(result.data.lines
        .filter(item => item.workshop_employee_id).map(item => [item.workshop_employee_id, item.employee_name]))
      originalQuantityBySchemeLine.value = result.data.lines.reduce<Record<string, number>>((values, item) => {
        values[item.scheme_line_id] = (values[item.scheme_line_id] || 0) + Number(item.quantity)
        return values
      }, {})
    } else {
      context.value = await fetchReportingContext(form.scheduleProductId || undefined, 'work_report')
    }
  } catch (error) { ElMessage.error(errorText(error)) }
  finally { hydrating.value = false }
  if (!isEdit.value && context.value) await loadPrice()
  loading.value = false
}
async function save() {
  if (!scheme.value || !scheduleProduct.value) return ElMessage.warning('请先取得适用工价方案。')
  const submittedLines = form.lines.filter(item => !isBlankOrZeroQuantity(item))
  if (submittedLines.some(item => !Number.isInteger(Number(item.quantity)) || Number(item.quantity) <= 0)) return ElMessage.warning('请输入正整数完成次数。')
  if (!submittedLines.length) return ElMessage.warning('请至少填写一项大于 0 的本次报工数量。')
  if (submittedLines.some(item => !employeeOptions.value.some(employee => employee.id === item.workshop_employee_id))) return ElMessage.warning('请选择本车间有效员工。')
  if (isAssembly.value && submittedLines.some(item => !item.production_line)) return ElMessage.warning('请选择装配线。')
  const lineIds = new Set(submittedLines.map(item => item.scheme_line_id))
  for (const schemeLineId of lineIds) {
    const required = Number(schemeLine(schemeLineId)?.required_quantity)
    const remaining = required - baseCumulative(schemeLineId)
    if (!Number.isFinite(required) || required <= 0) return ElMessage.warning('工价方案缺少需完成次数，请先变更并重新批准。')
    if (currentSubmitted(schemeLineId) > remaining) {
      return ElMessage.warning(`本次合计 ${quantityText(currentSubmitted(schemeLineId))} 次，超出 ${quantityText(currentSubmitted(schemeLineId) - Math.max(0, remaining))} 次。`)
    }
  }
  let confirmPlanCompletion = false
  if (willCompletePlan()) {
    try {
      await ElMessageBox.confirm(
        '本次报工后所有工序均达到需完成次数，确认完成该生产计划吗？',
        '确认完成生产计划',
        {
          type: 'warning',
          confirmButtonText: '确认完成并提交',
          cancelButtonText: '取消',
          customClass: 'wr-confirm-message-box',
        },
      )
      confirmPlanCompletion = true
    } catch { return }
  }
  saving.value = true
  try {
    const businessPayload = { production_date: form.productionDate, schedule_product_id: scheduleProduct.value.id, scheme_id: scheme.value.id, scheme_revision: scheme.value.revision, confirm_plan_completion: confirmPlanCompletion, lines: submittedLines.map(({ key, ...row }) => row) }
    if (isEdit.value) {
      await updateWorkReport(String(route.params.reportId), businessPayload, etag.value)
      ElMessage.success('报工修改已保存并立即生效。')
    } else {
      const payloadKey = JSON.stringify(businessPayload)
      if (!pendingRequestId || pendingPayloadKey !== payloadKey) { pendingRequestId = crypto.randomUUID(); pendingPayloadKey = payloadKey }
      await createWorkReport({ client_request_id: pendingRequestId, ...businessPayload })
      ElMessage.success('报工已提交并立即生效。')
    }
    const returnToTask = isEdit.value && route.query.production_task_id === scheduleProduct.value.production_task_id
    const planCategory = route.query.plan_category
    const query = returnToTask
      ? { production_task_id: scheduleProduct.value.production_task_id, workshop_id: form.workshopId }
      : { schedule_product_id: form.scheduleProductId, workshop_id: form.workshopId, craft_id: form.craftId }
    await router.push({ name: 'work-report-days', query: {
      ...query, ...(planCategory === 'CUTTING' || planCategory === 'SEWING' ? { plan_category: planCategory } : {}),
    } })
  } catch (error) { ElMessage.error(errorText(error)) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="wr-page wr-form-page wr-report-form-page erp-glass-form" data-testid="work-report-form">
    <header class="wr-heading wr-form-heading"><h1>{{ isEdit ? '编辑报工' : '新增报工' }}</h1></header>

    <section class="wr-card wr-report-basic-card">
      <h2>基本信息</h2>
      <div class="wr-report-basic-grid">
        <div>
          <ElFormItem label="生产日期" required><ElDatePicker v-model="form.productionDate" type="date" value-format="YYYY-MM-DD" /></ElFormItem>
          <ElFormItem label="所属产品" required><ElSelect v-model="form.scheduleProductId" filterable :disabled="isEdit"><ElOption v-for="item in context?.schedule_products || []" :key="item.id" :label="`${item.product_number} · ${item.product_name}`" :value="item.id" /></ElSelect></ElFormItem>
        </div>
        <div>
          <ElFormItem label="生产任务单" required><ElInput :model-value="scheduleProduct?.task_number || ''" readonly /></ElFormItem>
          <ElFormItem label="所属车间" required><ElSelect v-model="form.workshopId" :disabled="isEdit"><ElOption v-for="item in context?.workshops || []" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></ElFormItem>
        </div>
        <div>
          <ElFormItem label="所属工艺" required><ElSelect v-model="form.craftId" :disabled="isEdit"><ElOption v-for="item in craftOptions" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></ElFormItem>
          <ElFormItem label="报工负责人" required><ElInput :model-value="auth.user?.display_name || auth.user?.username || ''" readonly /></ElFormItem>
        </div>
      </div>
    </section>

    <section class="wr-card wr-report-detail-card">
      <div class="wr-card-title"><h2>报工明细</h2><ElButton v-if="canManageEmployees" @click="managerVisible = true">员工管理</ElButton></div>
      <ElTable class="erp-table-editor wr-work-report-table" :data="reportRows" row-key="key" border empty-text="请先选择范围并取得工价方案" @keydown.down="focusTableInputBelow">
        <ElTableColumn type="index" label="#" width="48" />
        <ElTableColumn label="名称 / 部位" min-width="180"><template #default="{ row }">
          <CuttingGroupCell :label="schemeLine(row.scheme_line_id)?.display_name || '—'"
            :components="schemeLine(row.scheme_line_id)?.cutting_components" />
        </template></ElTableColumn>
        <ElTableColumn label="工序" min-width="140"><template #default="{ row }">{{ schemeLine(row.scheme_line_id)?.operation_name || '—' }}</template></ElTableColumn>
        <ElTableColumn label="制作工序描述" min-width="180"><template #default="{ row }">{{ schemeLine(row.scheme_line_id)?.production_description || '—' }}</template></ElTableColumn>
        <ElTableColumn label="员工" :min-width="isAssembly ? 180 : 150"><template #default="{ row }">
          <ElSelect :model-value="isAssembly ? row.employeeIds : row.entries[0].workshop_employee_id" filterable
            :multiple="isAssembly" :collapse-tags="isAssembly" :collapse-tags-tooltip="isAssembly"
            @update:model-value="selectEmployees(row, $event)">
            <template v-for="id in row.employeeIds" :key="id">
              <ElOption v-if="inactiveEmployeeNames[id] && !employeeOptions.some(employee => employee.id === id)"
                :label="`${inactiveEmployeeNames[id]}（已不可用）`" :value="id" :disabled="!isAssembly" />
            </template>
            <ElOption v-for="item in employeeOptions" :key="item.id" :label="item.name" :value="item.id" />
          </ElSelect>
        </template></ElTableColumn>
        <ElTableColumn v-if="isAssembly" label="装配线" width="156">
          <template #header>
            <div class="wr-report-assembly-line-header">
              <span>装配线</span>
              <ElSelect :model-value="commonAssemblyLine" :disabled="!scheme || !form.lines.length"
                placeholder="统一" aria-label="统一选择装配线" @update:model-value="setAssemblyLine">
                <ElOption v-for="line in assemblyLines" :key="line" :label="`${line}线`" :value="line" />
              </ElSelect>
            </div>
          </template>
          <template #default="{ row }">
            <ElPopover v-if="row.entries.length > 1" trigger="click" placement="bottom-start" width="max-content"
              :persistent="false" popper-class="wr-report-employee-popover wr-report-assembly-line-popover"
              @after-enter="focusEmployeeField(`wr-report-assembly-lines-${row.key}`)">
              <template #reference>
                <ElButton class="wr-report-line-summary" link type="primary" aria-label="调整员工装配线" :title="productionLineSummary(row)">
                  {{ productionLineSummary(row) }}
                </ElButton>
              </template>
              <div :id="`wr-report-assembly-lines-${row.key}`" class="wr-report-employee-columns erp-flat-form">
                <div v-for="employee in row.employees" :key="employee.id" class="wr-report-employee-column">
                  <strong :title="employeeName(employee.id)">{{ employeeName(employee.id) }}</strong>
                  <select v-for="entry in employee.entries" :key="entry.key" v-model="entry.production_line"
                    :aria-label="`${employeeName(employee.id)}装配线`">
                    <option :value="null" disabled>装配线</option>
                    <option v-for="line in assemblyLines" :key="line" :value="line">{{ line }}线</option>
                  </select>
                </div>
              </div>
            </ElPopover>
            <ElSelect v-else v-model="row.entries[0].production_line">
              <ElOption v-for="line in assemblyLines" :key="line" :label="`${line}线`" :value="line" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn label="工价" width="105"><template #default="{ row }">{{ formatWageMoney(schemeLine(row.scheme_line_id)?.declared_price) }}</template></ElTableColumn>
        <ElTableColumn label="订单数量" width="100"><template #default>{{ quantityText(scheduleProduct?.order_quantity) }}</template></ElTableColumn>
        <ElTableColumn label="需完成次数" width="110"><template #default="{ row }">{{ quantityText(schemeLine(row.scheme_line_id)?.required_quantity) }}</template></ElTableColumn>
        <ElTableColumn label="累计报工" width="105"><template #default="{ row }">{{ quantityText(schemeLine(row.scheme_line_id)?.cumulative_quantity || '0') }}</template></ElTableColumn>
        <ElTableColumn label="本次报工" width="158"><template #default="{ row }">
          <div class="wr-quantity-field" :class="{ 'is-error': overReportMessage(row) }">
            <ElPopover v-if="row.entries.length > 1" trigger="click" placement="bottom-end" width="max-content"
              :persistent="false" popper-class="wr-report-employee-popover wr-report-quantity-popover"
              @after-enter="focusEmployeeField(`wr-report-quantities-${row.key}`)">
              <template #reference>
                <ElInput class="wr-report-quantity-summary" :model-value="quantitySummary(row)" readonly data-table-focus
                  placeholder="填写数量" aria-label="填写员工报工数量" :title="quantitySummary(row)" :aria-invalid="Boolean(overReportMessage(row))">
                  <template v-if="schemeLine(row.scheme_line_id)?.counting_mode === 'GROUP'" #append>套</template>
                </ElInput>
              </template>
              <div :id="`wr-report-quantities-${row.key}`" class="wr-report-employee-columns erp-flat-form">
                <div v-for="employee in row.employees" :key="employee.id" class="wr-report-employee-column">
                  <strong :title="employeeName(employee.id)">{{ employeeName(employee.id) }}</strong>
                  <ElInput v-for="entry in employee.entries" :key="entry.key" v-model="entry.quantity"
                    inputmode="numeric" placeholder="数量" :aria-label="`${employeeName(employee.id)}报工数量`" />
                </div>
              </div>
            </ElPopover>
            <ElInput v-else v-model="row.entries[0].quantity" inputmode="numeric" :aria-invalid="Boolean(overReportMessage(row))">
              <template v-if="schemeLine(row.scheme_line_id)?.counting_mode === 'GROUP'" #append>套</template>
            </ElInput>
            <p v-if="overReportMessage(row)" class="wr-quantity-error">{{ overReportMessage(row) }}</p>
          </div>
        </template></ElTableColumn>
        <ElTableColumn label="进度" width="82" align="center"><template #default="{ row }">{{ progressPercent(row.scheme_line_id) }}%</template></ElTableColumn>
        <ElTableColumn label="金额" width="115"><template #default="{ row }"><strong>{{ formatWageMoney(sumWageAmounts(row.entries.map(lineAmount))) }}</strong></template></ElTableColumn>
      </ElTable>
      <footer class="wr-total">本次工费合计：<strong>{{ formatWageMoney(total) }}</strong></footer>
      <footer class="wr-report-actions">
        <p>提交后计入当日报工记录，无需审核。</p>
        <div><ElButton @click="router.back()">返回</ElButton><ElButton type="primary" :loading="saving" @click="save">{{ isEdit ? '保存修改' : '提交报工' }}</ElButton></div>
      </footer>
    </section>
    <AppWindowDialog v-model="managerVisible" title="员工管理" :width="1100" :height="720" destroy-on-close @closed="refreshEmployees">
      <WorkshopConfigManager v-if="managerVisible" kind="employees" :initial-workshop="form.workshopId" lock-workshop />
    </AppWindowDialog>
  </section>
</template>

<style lang="scss">
@use '@/styles/workshopReporting.scss';

.wr-report-form-page { gap: 14px; }
.wr-report-form-page > .wr-heading.wr-form-heading { min-height: 44px; margin-bottom: 0; }
.wr-report-basic-card { padding: 16px 20px 10px; }
.wr-report-basic-card > h2 { margin: 0 0 14px; }
.wr-report-basic-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.wr-report-basic-grid > div { min-width: 0; padding: 0 20px; border-right: 1px solid var(--erp-color-border); }
.wr-report-basic-grid > div:first-child { padding-left: 0; }
.wr-report-basic-grid > div:last-child { padding-right: 0; border-right: 0; }
.wr-report-basic-grid .el-form-item { display: grid; grid-template-columns: 112px minmax(0, 220px); align-items: center; margin-bottom: 12px; }
.wr-report-basic-grid .el-form-item__label { width: auto !important; justify-content: flex-start; }
.wr-report-basic-grid .el-form-item__content > :is(.el-input, .el-select, .el-date-editor) { width: 100%; }
.wr-report-detail-card { padding: 0; }
.wr-report-detail-card .wr-card-title { min-height: 36px; margin-bottom: 0; padding: 0 12px; }
.wr-work-report-table { width: 100%; }
.wr-report-form-page .wr-work-report-table .el-table__header th.el-table__cell { height: 44px !important; padding: 0 !important; }
.wr-report-form-page .wr-work-report-table .el-table__body td.el-table__cell { height: 40px !important; padding: 0 !important; }
.wr-quantity-field { padding: 4px 0; }
.wr-quantity-field.is-error .el-input__wrapper { box-shadow: 0 0 0 1px var(--el-color-danger) inset !important; }
.wr-quantity-error { margin: 2px 0 0; color: var(--el-color-danger); font-size: 12px; line-height: 16px; text-align: left; }
.wr-report-assembly-line-header { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.wr-report-assembly-line-header .el-select { min-width: 0; }
.wr-report-line-summary { max-width: 100%; }
.wr-report-line-summary > span, .wr-report-employee-column > strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wr-report-quantity-summary .el-input__inner { cursor: pointer; }
.el-popover.el-popper.wr-report-employee-popover {
  max-width: calc(100vw - 32px);
  box-sizing: border-box;
  border-color: var(--erp-table-grid);
  background: var(--erp-color-surface);
}
.wr-report-employee-columns { display: flex; gap: 12px; overflow-x: auto; padding: 1px; }
.wr-report-employee-column { display: grid; flex: 0 0 120px; min-width: 0; gap: 8px; align-content: start; }
.wr-report-employee-column .el-input { font-size: 13px; }
.wr-report-employee-column select { width: 100%; font-family: inherit; }
.wr-report-actions { min-height: 76px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-top: 1px solid var(--erp-color-border-subtle); }
.wr-report-actions p { margin: 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.wr-report-actions > div { display: flex; gap: 20px; }
.wr-report-actions .el-button { min-width: 110px; height: 32px; margin: 0; }
.wr-report-actions .el-button--primary { min-width: 140px; }

@media (max-width: 1440px) {
  .wr-report-basic-grid { grid-template-columns: 1fr; }
  .wr-report-basic-grid > div { padding: 0; border-right: 0; }
}
</style>
