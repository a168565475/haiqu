<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Check, DocumentChecked, InfoFilled } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

import {
  createMaterialIssue, fetchEligibleMaterialIssueProducts, fetchMaterialIssue, fetchMaterialIssueOptions,
  fetchMaterialRequirements, submitMaterialIssue, updateMaterialIssue,
} from '@/api/materialIssues'
import { scheduleProductImageUrl } from '@/api/productionScheduling'
import MaterialIssuePartitions from '@/components/workshop/MaterialIssuePartitions.vue'
import { issueSelectedQuantityError } from '@/utils/materialIssueQuantities'
import { decimalUnits } from '@/utils/outsourcingQuantities'
import type { MaterialIssueBatch } from '@/types/materialIssue'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import { router } from '@/router'
import type { MaterialIssueOptions, MaterialIssueProduct, MaterialRequirement, MaterialRequirementBlocker } from '@/types/materialIssue'

const route = useRoute()
const issueId = computed(() => String(route.params.issueId || ''))
const editing = computed(() => Boolean(issueId.value))
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const editLoadComplete = ref(false)
const clientRequestId = crypto.randomUUID()
const persistedIssueId = ref('')
const persistedEtag = ref('')
const options = ref<MaterialIssueOptions>({ production_tasks: [], workshops: [], recipients: [] })
const products = ref<MaterialIssueProduct[]>([])
const requirements = ref<MaterialRequirement[]>([])
const blockers = ref<MaterialRequirementBlocker[]>([])
const etag = ref('')
const selected = reactive<Record<string, string>>({})
const allocations = reactive<Record<string, MaterialIssueBatch[]>>({})
const originalTaskId = ref('')
const loadedIssueId = ref('')
function currentMinuteValue() {
  const now = new Date()
  now.setSeconds(0, 0)
  const pad = (value: number) => String(value).padStart(2, '0')
  const offsetMinutes = -now.getTimezoneOffset()
  const offsetSign = offsetMinutes >= 0 ? '+' : '-'
  const absoluteOffset = Math.abs(offsetMinutes)
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:00${offsetSign}${pad(Math.floor(absoluteOffset / 60))}:${pad(absoluteOffset % 60)}`
}
const form = reactive({ production_task_id: '', product_line_id: '', workshop_id: '', recipient_workshop_employee_id: '', issue_at: currentMinuteValue(), remark: '' })
const contextError = ref('')
const planCategory = computed(() => String(route.query.plan_category || '').toUpperCase())
const scheduleProductId = computed(() => String(route.query.schedule_product_id || ''))
const planWorkshopNames: Record<string, string> = {
  METAL: '金工车间', CUTTING: '车缝车间', SEWING: '车缝车间', ASSEMBLY: '装配车间',
}
const planCategoryLabels: Record<string, string> = {
  METAL: '金工计划', CUTTING: '裁剪计划', SEWING: '车缝计划', ASSEMBLY: '装配计划',
}
const planContextActive = computed(() => !editing.value && Boolean(planWorkshopNames[planCategory.value]))
const isAssemblyIssue = computed(() => {
  if (planCategory.value === 'ASSEMBLY') return true
  return options.value.workshops.find((item) => item.id === form.workshop_id)?.name === '装配车间'
})

const recipients = computed(() => options.value.recipients.filter((item) => !form.workshop_id || item.workshop_id === form.workshop_id))
const selectedRows = computed(() => requirements.value.filter((item) => item.requirement_id in selected))
function omittedQuantity(value: string | undefined): boolean {
  const text = String(value ?? '').trim()
  return text === '' || decimalUnits(text) === 0n
}
const recordedRows = computed(() => selectedRows.value.filter((item) => !omittedQuantity(selected[item.requirement_id])))
const currentProduct = computed(() => products.value.find((item) => item.id === form.product_line_id))
const productImageUrl = computed(() => {
  const imageId = currentProduct.value?.image_file_id
  return imageId && form.production_task_id
    ? scheduleProductImageUrl(form.production_task_id, imageId)
    : productImagePlaceholder
})
const blockerSummary = computed(() => {
  const groups = new Map<string, { detail: string; count: number }>()
  for (const blocker of blockers.value) {
    const detail = blocker.detail || 'BOM 材料未关联可用的库存原料。'
    const current = groups.get(detail)
    groups.set(detail, { detail, count: (current?.count || 0) + 1 })
  }
  return [...groups.values()]
})
function apiMessage(error: unknown, loadingData = false): string {
  const businessMessage = (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message
  if (businessMessage) return businessMessage
  if (isAxiosError(error) && (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT')) {
    return loadingData ? '领料数据加载超时，请重试。' : '请求超时，请先确认领料单状态再重试。'
  }
  return '操作失败，请稍后重试。'
}
const quantity = (value: string) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}

async function loadProducts(clear = true) {
  if (clear) { form.product_line_id = ''; requirements.value = []; Object.keys(selected).forEach((key) => delete selected[key]) }
  products.value = form.production_task_id ? await fetchEligibleMaterialIssueProducts(form.production_task_id) : []
}
async function loadRequirements(restore?: Map<string, string>) {
  requirements.value = []; blockers.value = []
  if (!form.production_task_id || !form.product_line_id || !form.workshop_id) return
  const data = await fetchMaterialRequirements(form.production_task_id, form.product_line_id, form.workshop_id, loadedIssueId.value || undefined, planCategory.value || undefined)
  requirements.value = data.items; blockers.value = data.blockers
  Object.keys(selected).forEach((key) => delete selected[key])
  if (restore) {
    for (const item of data.items) {
      const value = restore.get(item.requirement_id)
      if (value !== undefined) selected[item.requirement_id] = value
    }
  }

}
async function changeTask(value: string) {
  if (originalTaskId.value && originalTaskId.value !== value && selectedRows.value.length) {
    try { await ElMessageBox.confirm('切换生产订单会清空当前已选领料明细，是否继续？', '切换生产订单', { type: 'warning' }) }
    catch { form.production_task_id = originalTaskId.value; return }
  }
  originalTaskId.value = value
  try { await loadProducts() } catch (error) { ElMessage.error(apiMessage(error, true)) }
}
function validate(): string {
  if (!form.production_task_id) return '请选择生产订单。'
  if (!form.product_line_id) return '请选择订单产品。'
  if (!form.workshop_id) return '请选择领料车间。'
  if (!form.recipient_workshop_employee_id) return '请选择领料人。'
  if (!form.issue_at) return '请选择领料时间。'
  if (!recordedRows.value.length) return '请至少填写一项大于 0 的领料数量。'
  if (blockers.value.some((item) => item.section_code !== 'SEMI') && recordedRows.value.some((item) => item.line_type === 'RAW')) return '当前 BOM 存在未解析原材料，请先处理页面提示；仅领取已回库半成品不受此项影响。'
  for (const item of recordedRows.value) {
    const error = issueSelectedQuantityError(selected[item.requirement_id] || '', item, requirements.value, selected)
    if (error) return `${item.material_name}：${error}`
  }
  return ''
}
function payload() {
  const issueLines = recordedRows.value.flatMap((item) => {
    if (item.stock_mode === 'PUBLIC_V2' || item.line_type !== 'SEMI' || !item.semi_balance_allocations?.length) {
      return [{ requirement_id: item.requirement_id, requested_quantity: selected[item.requirement_id] }]
    }
    let remaining = decimalUnits(selected[item.requirement_id]) || 0n
    return item.semi_balance_allocations.flatMap((allocation) => {
      if (remaining <= 0n) return []
      const capacity = decimalUnits(allocation.max_issue_quantity) || 0n
      const amount = remaining < capacity ? remaining : capacity
      remaining -= amount
      if (amount <= 0n) return []
      const whole = `${amount / 10000n}.${String(amount % 10000n).padStart(4, '0')}`.replace(/\.?0+$/, '') || '0'
      return [{ requirement_id: allocation.balance_id, requested_quantity: whole }]
    })
  })
  const data: Record<string, unknown> = {
    ...form,
    production_task_id: form.production_task_id || null,
    product_line_id: form.product_line_id || null,
    workshop_id: form.workshop_id || null,
    recipient_workshop_employee_id: form.recipient_workshop_employee_id || null,
    issue_at: form.issue_at || null,
    lines: issueLines,
  }
  if (!editing.value) {
    data.schedule_product_id = scheduleProductId.value
    data.plan_category = planCategory.value
  }
  return data
}
async function save(submit: boolean) {
  if (editing.value && !editLoadComplete.value) { ElMessage.warning('编辑数据尚未完整加载，请先重试。'); return }
  if (submit) { const message = validate(); if (message) { ElMessage.warning(message); return } }
  saving.value = true
  try {
    const targetId = issueId.value || persistedIssueId.value
    const targetEtag = etag.value || persistedEtag.value
    const result = targetId
      ? await updateMaterialIssue(targetId, payload(), targetEtag)
      : await createMaterialIssue({ ...payload(), client_request_id: clientRequestId })
    etag.value = result.etag
    persistedIssueId.value = result.data.id
    persistedEtag.value = result.etag
    loadedIssueId.value = result.data.id
    if (submit) {
      try {
        const submitted = await submitMaterialIssue(result.data.id, result.etag)
        ElMessage.success('领料单已提交仓库审核。')
        await router.replace({ name: 'material-issue-detail', params: { issueId: submitted.data.id } })
      } catch (error) {
        if (!editing.value) {
          editLoadComplete.value = true
          await router.replace({ name: 'material-issue-edit', params: { issueId: result.data.id } })
        }
        throw error
      }
    } else {
      ElMessage.success('草稿已保存。')
      await router.replace({ name: 'material-issue-detail', params: { issueId: result.data.id } })
    }
  } catch (error) { ElMessage.error(apiMessage(error)) }
  finally { saving.value = false }
}
async function loadEdit() {
  if (!editing.value) return
  loading.value = true
  loadError.value = ''
  editLoadComplete.value = false
  try {
    const result = await fetchMaterialIssue(issueId.value)
    if (!['DRAFT', 'RETURNED'].includes(result.data.status)) { ElMessage.warning('当前状态不允许修改。'); await router.replace({ name: 'material-issue-detail', params: { issueId: issueId.value } }); return }
    etag.value = result.etag
    Object.assign(form, {
      production_task_id: result.data.production_task?.id || '', product_line_id: result.data.product?.id || '',
      workshop_id: result.data.workshop?.id || '', recipient_workshop_employee_id: result.data.recipient?.id || '',
      issue_at: result.data.issue_at || '', remark: result.data.remark,
    })
    originalTaskId.value = form.production_task_id
    loadedIssueId.value = result.data.id
    await loadProducts(false)
    await loadRequirements()
    const restored = new Map<string, string>()
    for (const line of result.data.lines) {
      const matching = requirements.value.find((item) => item.stock_mode !== 'PUBLIC_V2'
        && item.semi_balance_allocations?.some((allocation) => allocation.balance_id === line.requirement_id))
      const key = matching?.requirement_id || line.requirement_id
      const toScaled = (value: string) => {
        const [whole, fraction = ''] = String(value || '0').split('.')
        return BigInt(whole || '0') * 10000n + BigInt(fraction.padEnd(4, '0').slice(0, 4) || '0')
      }
      const scaled = toScaled(restored.get(key) || '0') + toScaled(line.requested_quantity || '0')
      restored.set(key, `${scaled / 10000n}.${String(scaled % 10000n).padStart(4, '0')}`.replace(/\.?0+$/, '') || '0')
    }
    for (const [key, value] of restored) selected[key] = value
    for (const line of result.data.lines) {
      if (result.data.stock_mode !== 'PUBLIC_V2' && line.stock_mode !== 'PUBLIC_V2' && line.batch_allocations?.length) allocations[line.requirement_id] = line.batch_allocations.map(batch => {
        const current = requirements.value.find(r => r.requirement_id === line.requirement_id)?.batch_candidates?.find(b => b.inbound_line_id === batch.inbound_line_id)
        return { ...batch, available_quantity: '0', available_meters: '0.00', ...current, requested_pieces: batch.requested_pieces }
      })
    }
    const availableRequirementIds = new Set(requirements.value.map((item) => item.requirement_id))
    const missingLines = result.data.lines.filter((line) => !availableRequirementIds.has(line.requirement_id)
      && !requirements.value.some((item) => item.stock_mode !== 'PUBLIC_V2'
        && item.semi_balance_allocations?.some((allocation) => allocation.balance_id === line.requirement_id)))
    if (missingLines.length) {
      loadError.value = `原领料单有 ${missingLines.length} 项明细已不在当前可领范围。为避免误删原数据，本页已停止保存，请返回详情核对 BOM 或库存变化。`
      return
    }
    persistedIssueId.value = result.data.id
    persistedEtag.value = result.etag
    editLoadComplete.value = true
  } catch (error) { loadError.value = apiMessage(error, true); ElMessage.error(loadError.value) }
  finally { loading.value = false }
}
async function loadPlanContext() {
  const taskId = String(route.query.production_task_id || '')
  const productLineId = String(route.query.product_line_id || '')
  const workshopName = planWorkshopNames[planCategory.value]
  if (!taskId || !productLineId || !scheduleProductId.value || !workshopName) {
    contextError.value = '请从金工、裁剪、车缝或装配作业计划中发起生产领料。'
    return
  }
  const workshop = options.value.workshops.find((item) => item.name === workshopName)
  const task = options.value.production_tasks.find((item) => item.id === taskId)
  if (!workshop || !task) {
    contextError.value = '作业计划对应的生产订单或领料车间当前不可用，请返回作业计划刷新后重试。'
    return
  }
  Object.assign(form, { production_task_id: taskId, product_line_id: productLineId, workshop_id: workshop.id })
  originalTaskId.value = taskId
  await loadProducts(false)
  if (!products.value.some((item) => item.id === productLineId)) {
    contextError.value = '作业计划中的产品当前不可领料，请返回作业计划刷新后重试。'
    return
  }
  await loadRequirements()
}
async function initialize() {
  loading.value = true
  loadError.value = ''
  contextError.value = ''
  try {
    options.value = await fetchMaterialIssueOptions(String(route.query.production_task_id || ''))
    if (editing.value) await loadEdit()
    else await loadPlanContext()
  } catch (error) {
    const message = apiMessage(error, true)
    loadError.value = message
    ElMessage.error(message)
  } finally { loading.value = false }
}
watch(() => form.workshop_id, () => { if (!recipients.value.some((item) => item.id === form.recipient_workshop_employee_id)) form.recipient_workshop_employee_id = '' })
onMounted(initialize)
</script>

<template>
  <section v-loading="loading" class="material-issue-page material-issue-form" data-testid="material-issue-form">
    <section v-if="loadError" class="mi-surface invalid-context">
      <ElResult icon="error" title="领料单数据未完整加载" :sub-title="loadError">
        <template #extra><div class="load-error-actions"><ElButton @click="router.back()">返回</ElButton><ElButton type="primary" @click="initialize">重试加载</ElButton></div></template>
      </ElResult>
    </section>
    <section v-else-if="contextError" class="mi-surface invalid-context">
      <ElEmpty :description="contextError"><ElButton type="primary" @click="router.push({ name: 'workshop-metalworking-plan' })">返回作业计划</ElButton></ElEmpty>
    </section>
    <template v-else>
      <div class="material-issue-scroll">
        <header class="form-titlebar">
          <div class="form-title-copy">
            <h1>{{ editing ? '修改生产领料单' : '新增生产领料单' }}</h1>
            <span v-if="planContextActive" class="plan-label">{{ planCategoryLabels[planCategory] }}</span>
          </div>
          <p><ElIcon><InfoFilled /></ElIcon>按生产订单限额领料，仓库确认出库后扣库存。</p>
        </header>

        <section class="mi-surface form-basic basic-card">
          <h2>基本信息</h2>
          <div class="basic-row basic-row--top">
            <div class="inline-field">
              <label>生产订单 <em>*</em></label>
              <ElSelect v-model="form.production_task_id" aria-label="生产订单" filterable :disabled="planContextActive || editing" placeholder="选择可领料的生产订单" @change="changeTask"><ElOption v-for="item in options.production_tasks" :key="item.id" :label="`${item.task_number} · ${item.customer_name}`" :value="item.id" /></ElSelect>
            </div>
            <div class="inline-field">
              <label>选择产品 <em>*</em></label>
              <ElSelect v-model="form.product_line_id" aria-label="选择产品" filterable :disabled="planContextActive || editing || !form.production_task_id" placeholder="仅显示当前订单产品" @change="loadRequirements()"><ElOption v-for="item in products" :key="item.id" :label="`${item.product_number} · ${item.product_name}`" :value="item.id" /></ElSelect>
            </div>
            <article v-if="currentProduct" class="product-preview">
              <img :src="productImageUrl" :class="{ 'is-placeholder': !currentProduct.image_file_id }" :alt="`${currentProduct.product_name}图片`" @error="useProductImageFallback" />
              <div><strong>{{ currentProduct.product_number }}　{{ currentProduct.product_name }}</strong><p>{{ currentProduct.color || '—' }}　订单数量 {{ quantity(String(currentProduct.quantity || '0')) }} {{ currentProduct.unit || '套' }}</p></div>
            </article>
          </div>
          <div class="basic-row basic-row--bottom">
            <div class="inline-field inline-field--aligned">
              <label>领料人 <em>*</em></label>
              <ElSelect v-model="form.recipient_workshop_employee_id" aria-label="领料人" filterable :disabled="!form.workshop_id" placeholder="选择在职车间人员"><ElOption v-for="item in recipients" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
            </div>
            <div class="inline-field inline-field--aligned">
              <label>领料车间 <em>*</em></label>
              <ElSelect v-model="form.workshop_id" aria-label="领料车间" :disabled="planContextActive || editing" placeholder="选择车间"><ElOption v-for="item in options.workshops" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
            </div>
            <div class="inline-field inline-field--aligned">
              <label>领料时间 <em>*</em></label>
              <ElDatePicker v-model="form.issue_at" aria-label="领料时间" type="datetime" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="选择实际领料时间" />
            </div>
            <div class="inline-field inline-field--aligned inline-field--remark">
              <label>备注</label>
              <ElInput v-model="form.remark" aria-label="备注" maxlength="2000" placeholder="备注（选填）" />
            </div>
          </div>
        </section>

        <details v-if="blockers.length" class="requirement-warning">
          <summary><span><strong>当前车间有 {{ blockers.length }} 项材料资料需要处理</strong><small>请先核对下方资料提示，系统按原材料与半成品分别校验。</small></span><em>查看明细</em></summary>
          <ul><li v-for="item in blockerSummary" :key="item.detail"><span>{{ item.detail }}</span><b v-if="item.count > 1">{{ item.count }} 项</b></li></ul>
        </details>

        <MaterialIssuePartitions
          v-if="form.product_line_id"
          :requirements="requirements"
          :selected="selected"
          :allocations="allocations"
          :show-pipe-deduction-columns="!isAssemblyIssue"
        />
        <section v-else class="mi-surface mi-empty empty-requirements">请先从作业计划带入生产订单与产品。</section>
      </div>

      <footer class="form-action-footer">
        <span><b>原材料 {{ recordedRows.filter(r => r.line_type === 'RAW').length }} 项 · 半成品 {{ recordedRows.filter(r => r.line_type === 'SEMI').length }} 项</b><i></i>不同单位的物料 / 半成品，按各自计量单位领料</span>
        <div>
          <ElButton :icon="ArrowLeft" @click="router.back()">{{ editing ? '返回详情' : '返回' }}</ElButton>
          <ElButton :loading="saving" :icon="DocumentChecked" @click="save(false)">保存草稿</ElButton>
          <ElButton type="primary" :loading="saving" :icon="Check" @click="save(true)">{{ editing ? '重新提交审核' : '提交仓库审核' }}</ElButton>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/materialIssue';
.material-issue-form { --el-color-primary: #c84e28; display: flex; flex-direction: column; overflow: hidden; }
.material-issue-scroll { flex: 1; min-height: 0; overflow: auto; padding-right: 2px; }
.form-titlebar { display: flex; min-height: 54px; align-items: flex-start; justify-content: space-between; gap: 20px; }
.form-title-copy { display: flex; align-items: center; gap: 18px; min-width: 0; }
.form-titlebar h1 { margin: 0; color: #1f1d18; font: 500 34px/44px 'Noto Serif SC', 'Songti SC', serif; letter-spacing: -0.6px; }
.form-titlebar p { display: flex; align-items: center; gap: 7px; margin: 15px 4px 0 0; color: #6f6a61; font-size: 13px; white-space: nowrap; }
.form-titlebar p :deep(.el-icon) { color: #817b72; font-size: 15px; }
.plan-label { margin-top: 4px; padding: 4px 10px; border-left: 3px solid #c84e28; color: #8b3c21; background: #f0eadf; font-size: 13px; line-height: 22px; white-space: nowrap; }
.form-basic { margin-bottom: 14px; padding: 8px 15px 12px; }
.form-basic h2, .category-panel h2, .pick-panel h2 { margin: 0; color: #26231f; font-size: 16px; font-weight: 600; line-height: 24px; }
.basic-row { display: grid; align-items: center; column-gap: 18px; }
.basic-row--top { grid-template-columns: repeat(2, 352px) minmax(280px, 1fr); min-height: 68px; }
.basic-row--bottom { grid-template-columns: 352px 18px 352px 26px 352px 18px 352px; column-gap: 0; }
.basic-row--bottom > :nth-child(1) { grid-column: 1; }
.basic-row--bottom > :nth-child(2) { grid-column: 3; }
.basic-row--bottom > :nth-child(3) { grid-column: 5; }
.basic-row--bottom > :nth-child(4) { grid-column: 7; }
.inline-field { display: grid; grid-template-columns: 106px 246px; align-items: center; min-width: 0; }
.basic-row--bottom .inline-field { grid-template-columns: 106px 246px; }
.basic-row--bottom .inline-field--aligned { grid-template-columns: 106px 246px; }
.inline-field label { color: #4d4c48; font-size: 14px; white-space: nowrap; }
.inline-field label em { color: #c84e28; font-style: normal; }
.inline-field :deep(.el-select), .inline-field :deep(.el-date-editor), .inline-field :deep(.el-input) { width: 100%; }
.basic-card :deep(.el-select__wrapper.is-disabled) { background-color: #fcfaf7; box-shadow: 0 0 0 1px #ddd8cf inset; cursor: not-allowed; }
.basic-card :deep(.el-select__wrapper.is-disabled .el-select__selected-item) { color: #4d4c48; -webkit-text-fill-color: #4d4c48; }
.product-preview { display: flex; align-self: start; align-items: center; gap: 12px; min-width: 0; margin-top: -4px; margin-left: 8px; }
.product-preview img { width: 70px; height: 70px; flex: none; object-fit: cover; border: 1px solid #ddd6c9; border-radius: 4px; background: #fff; }
.product-preview img.is-placeholder { object-fit: contain; padding: 7px; }
.product-preview div { min-width: 0; }
.product-preview strong, .product-preview p { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-preview strong { color: #26231f; font-size: 14px; font-weight: 600; }
.product-preview p { margin: 5px 0 0; color: #6f6a61; font-size: 13px; }
.issue-workspace { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 12px; min-width: 0; }
.category-panel { align-self: stretch; overflow: hidden; padding: 10px 0; }
.category-panel h2 { height: 35px; padding: 0 14px; }
.category-panel button { position: relative; display: flex; width: 100%; height: 46px; align-items: center; justify-content: space-between; padding: 0 14px 0 18px; border: 0; border-bottom: 1px solid #e7e0d5; border-radius: 0; color: #312e29; background: transparent; font: inherit; font-size: 14px; cursor: pointer; }
.category-panel button.selected { color: #c84e28; background: #fff3e9; font-weight: 600; }
.category-panel button.selected::before { position: absolute; inset: 0 auto 0 0; width: 4px; background: #c84e28; content: ''; }
.category-panel button small { display: grid; min-width: 22px; height: 20px; place-items: center; border-radius: 10px; color: #746f67; background: #eee8de; font-size: 11px; font-weight: 400; }
.material-panels { min-width: 0; }
.pick-panel { min-width: 0; overflow: hidden; }
.pick-panel > h2 { display: flex; min-height: 44px; align-items: center; gap: 18px; padding: 0 13px; }
.pick-panel h2 small { color: #777168; font-size: 12px; font-weight: 400; }
.pick-table-wrap { overflow: hidden; padding-bottom: 10px; border-top: 1px solid #ddd6c9; }
.pick-panel :deep(.el-table) { --el-table-border-color: #ddd6c9; --el-table-header-bg-color: #f0eadf; --el-table-row-hover-bg-color: #fff6ed; width: 100%; color: #4d4c48; font-size: 12px; }
.pick-panel :deep(.el-table th.el-table__cell) { height: 44px; padding: 0; color: #6f6a61; background: #f0eadf; font-size: 11px; font-weight: 400; line-height: 16px; }
.pick-panel :deep(.el-table td.el-table__cell) { height: 40px; padding: 0; font-weight: 400; }
.pick-panel :deep(.el-table .cell) { padding: 0 16px; line-height: 18px; white-space: nowrap; }
.pick-panel :deep(.el-input__wrapper) { background: #fffefb; }
.pick-panel :deep(.el-input__inner) { text-align: center; }
.material-identity { min-width: 0; }
.material-identity strong { display: block; overflow: hidden; color: #35322d; font-size: 13px; font-weight: 500; line-height: 20px; text-overflow: ellipsis; white-space: nowrap; }
.zone-copy { color: #8a847b; font-size: 11px; }
.zone-copy { margin-left: 6px; }
.craft-tag { display: inline-flex; min-height: 22px; align-items: center; padding: 0 9px; border-radius: 12px; color: #fff; background: #c96442; font-size: 11px; }
.empty-requirements { min-height: 320px; display: grid; place-items: center; }
.form-action-footer { min-height: 58px; display: flex; flex: none; align-items: center; justify-content: space-between; gap: 20px; border-top: 1px solid #ddd6c9; color: #6f6a61; background: #f6f3ec; font-size: 13px; }
.form-action-footer > span { display: flex; align-items: center; min-width: 0; }
.form-action-footer b { color: #28251f; font-size: 14px; }
.form-action-footer i { width: 1px; height: 20px; margin: 0 16px; background: #aaa398; }
.form-action-footer > div { display: flex; gap: 10px; }
.form-action-footer :deep(.el-button + .el-button) { margin-left: 0; }
.form-action-footer :deep(.el-button--primary) { min-width: 140px; border-color: #c84e28; background: #c84e28; }
.invalid-context { min-height: 360px; display: grid; place-items: center; }
.load-error-actions { display: flex; justify-content: center; gap: 10px; }
.requirement-warning { overflow: hidden; border: 1px solid #d9a09b; border-radius: 6px; background: #fff8f7; }
.requirement-warning { margin-bottom: 12px; }
.requirement-warning summary { min-height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 0 16px; cursor: pointer; list-style: none; }
.requirement-warning summary::-webkit-details-marker { display: none; }
.requirement-warning summary span { display: grid; gap: 2px; }
.requirement-warning summary strong { color: #9f342e; font-size: 14px; }
.requirement-warning summary small { color: #746964; font-size: 12px; }
.requirement-warning summary em { color: #9f342e; font-size: 13px; font-style: normal; white-space: nowrap; }
.requirement-warning ul { margin: 0; padding: 0; border-top: 1px solid #ecd4d1; list-style: none; }
.requirement-warning li { min-height: 38px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 16px; color: #625d55; font-size: 13px; }
.requirement-warning li + li { border-top: 1px solid #f0dfdc; }
.requirement-warning li b { color: #9f342e; font-size: 12px; font-weight: 500; white-space: nowrap; }
@media (max-width: 1750px) {
  .basic-row--bottom { grid-template-columns: 352px 18px 352px; justify-content: start; row-gap: 8px; padding-top: 4px; }
  .basic-row--bottom > :nth-child(1) { grid-column: 1; grid-row: 1; }
  .basic-row--bottom > :nth-child(2) { grid-column: 3; grid-row: 1; }
  .basic-row--bottom > :nth-child(3) { grid-column: 1; grid-row: 2; }
  .basic-row--bottom > :nth-child(4) { grid-column: 3; grid-row: 2; }
}
@media (max-width: 1400px) {
  .form-titlebar p { display: none; }
  .product-preview { align-self: center; margin-top: 0; margin-left: 0; }
  .product-preview img { width: 62px; height: 62px; }
  .issue-workspace { grid-template-columns: 150px minmax(0, 1fr); }
  .form-action-footer > span { font-size: 12px; }
}
@media (max-width: 1100px) {
  .basic-row--top { grid-template-columns: repeat(2, 352px); justify-content: space-between; }
  .product-preview { grid-column: span 2; min-height: 52px; }
  .product-preview img { width: 50px; height: 50px; }
  .basic-row--bottom { grid-template-columns: 352px 18px 352px; }
  .form-basic { padding-bottom: 14px; }
}
@media (max-width: 900px) {
  .form-titlebar { min-height: 50px; }
  .form-titlebar h1 { font-size: 28px; line-height: 38px; }
  .issue-workspace { grid-template-columns: 1fr; }
  .category-panel { display: flex; overflow-x: auto; padding: 0; }
  .category-panel h2 { display: none; }
  .category-panel button { width: auto; min-width: 120px; border-bottom: 0; border-right: 1px solid #e7e0d5; }
  .form-action-footer > span { display: none; }
  .form-action-footer { justify-content: flex-end; }
}
</style>
