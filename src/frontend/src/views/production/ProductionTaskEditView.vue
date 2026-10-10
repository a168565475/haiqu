<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { Lock, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import InquiryWangEditor from '@/components/InquiryWangEditor.vue'
import {
  fetchProductionTask,
  fetchProductionTaskOptions,
  updateProductionTask,
} from '@/api/productionTasks'
import type {
  ProductionTask,
  ProductionTaskOptions,
  ProductionTaskPatchInput,
  ProductionTaskProduct,
  ProductionTaskProductInput,
} from '@/types/productionTask'

interface EditableProduct {
  id: string
  productName: string
  productCode: string
  specification: string
  colorLabel: string
  quantity: string
  originalQuantity: string
  unitName: string
  sourceLocked: boolean
}

const route = useRoute()
const router = useRouter()
const taskId = computed(() => typeof route.params.taskId === 'string' ? route.params.taskId : '')
const task = ref<ProductionTask | null>(null)
const options = ref<ProductionTaskOptions | null>(null)
const etag = ref('')
const loading = ref(true)
const saving = ref(false)
const loadError = ref('')
const allowLeave = ref(false)
const originalRequirementsHtml = ref('')
const bomSyncMode = ref<'SYNC' | 'KEEP'>('SYNC')
const products = ref<EditableProduct[]>([])
const form = reactive({
  delivery_date: '',
  follower_ids: [] as string[],
  special_requirements_html: '',
})

const isTerminal = computed(() => ['COMPLETED', 'CANCELLED'].includes(task.value?.status || ''))
const followerOptions = computed(() => (options.value?.employees || []).filter((employee) => employee.id !== task.value?.salesperson.id))
const employeeName = (id: string) => options.value?.employees.find((item) => item.id === id)?.display_name || id
const followerSummary = (ids: string[]) => ids.map(employeeName).join('、') || '未设置'
const productSummary = computed(() => [...new Set(products.value.map((item) => `${item.productName} ${item.productCode}`))].join('、') || '—')
const totalQuantity = computed(() => products.value.reduce((sum, item) => sum + Number(item.quantity || 0), 0).toLocaleString('zh-CN'))
const priorityLabel = computed(() => ({ URGENT: '紧急', HIGH: '高', NORMAL: '普通', LOW: '低' } as Record<string, string>)[task.value?.production_priority || 'NORMAL'])

function normalizedRequirementsHtml(value: string): string {
  const html = value.trim()
  if (!html) return ''
  const element = document.createElement('div')
  element.innerHTML = html
  const text = (element.textContent || '').replace(/[\u00a0\u200b\ufeff]/g, '').trim()
  return text || element.querySelector('img, video, audio, iframe, hr, input, table') ? html : ''
}

function sameRequirementsHtml(currentValue: string, originalValue: string): boolean {
  const current = normalizedRequirementsHtml(currentValue)
  const original = normalizedRequirementsHtml(originalValue)
  if (current === original) return true
  if (!original) return false

  // 旧数据可能是纯文本，富文本编辑器初始化时会自动包成一个普通段落。
  const originalContainer = document.createElement('div')
  originalContainer.innerHTML = original
  if (originalContainer.childElementCount > 0) return false
  const currentContainer = document.createElement('div')
  currentContainer.innerHTML = current
  const paragraph = currentContainer.firstElementChild
  return currentContainer.childNodes.length === 1
    && paragraph?.tagName === 'P'
    && paragraph.attributes.length === 0
    && paragraph.childNodes.length === 1
    && paragraph.firstChild?.nodeType === Node.TEXT_NODE
    && paragraph.textContent === original
}

const requirementsChanged = computed(() => !sameRequirementsHtml(form.special_requirements_html, originalRequirementsHtml.value))

const changes = computed(() => {
  if (!task.value) return []
  const result: Array<{ key: string; label: string; before: string; after: string; bomImpact: boolean }> = []
  if (form.delivery_date !== task.value.delivery_date) {
    result.push({ key: 'delivery', label: '预计交期', before: task.value.delivery_date, after: form.delivery_date, bomImpact: false })
  }
  const beforeFollowers = task.value.followers.map((item) => item.id).sort()
  const afterFollowers = [...form.follower_ids].sort()
  if (JSON.stringify(beforeFollowers) !== JSON.stringify(afterFollowers)) {
    result.push({
      key: 'followers', label: '跟单员',
      before: task.value.followers.map((item) => item.display_name).join('、') || '未设置',
      after: followerSummary(form.follower_ids), bomImpact: false,
    })
  }
  if (requirementsChanged.value) {
    result.push({ key: 'requirements', label: '生产要求', before: '原要求', after: '已修改', bomImpact: false })
  }
  products.value.forEach((row) => {
    if (row.quantity !== row.originalQuantity) {
      result.push({
        key: `quantity-${row.id}`,
        label: `${row.productName} / ${row.colorLabel}`,
        before: `${row.originalQuantity} ${row.unitName}`,
        after: `${row.quantity} ${row.unitName}`,
        bomImpact: Boolean(task.value?.current_boms?.some((bom) => bom.product_line_id === row.id)),
      })
    }
  })
  return result
})

const dirty = computed(() => changes.value.length > 0)
const bomAffectedChanges = computed(() => changes.value.filter((item) => item.bomImpact))

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查服务。'
  if (error.response.status === 412) return '数据已被其他人修改，请重新加载后再保存。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  return data.error?.message || data.detail || '保存失败，请检查填写内容。'
}

function productPayload(row: ProductionTaskProduct, quantity: string): ProductionTaskProductInput {
  return {
    client_key: row.id,
    product_id: row.product_id,
    product_color_id: row.product_color_id || '',
    color_code: row.color_code,
    quantity,
    unit_id: row.unit_id,
    currency_id: row.currency_id,
    unit_price: row.unit_price,
    exchange_rate: Number(row.exchange_rate).toFixed(3),
    special_requirements: row.special_requirements || '',
    packaging_method: row.packaging_method || '',
    retained_image_ids: (row.images || []).map((item) => item.id),
    details: row.details.map((detail) => ({
      client_key: detail.id,
      template_key: detail.template_key,
      detail_type: detail.detail_type,
      category_label: detail.category_label,
      is_selected: detail.is_selected,
      description: detail.description,
    })),
  }
}

function buildPatch(): ProductionTaskPatchInput {
  if (!task.value) return {}
  const patch: ProductionTaskPatchInput = {}
  if (form.delivery_date !== task.value.delivery_date) patch.delivery_date = form.delivery_date
  const originalFollowers = task.value.followers.map((item) => item.id).sort()
  if (JSON.stringify([...form.follower_ids].sort()) !== JSON.stringify(originalFollowers)) {
    patch.follower_ids = [...form.follower_ids]
  }
  if (requirementsChanged.value) {
    patch.special_requirements_html = normalizedRequirementsHtml(form.special_requirements_html)
  }
  if (products.value.some((row) => row.quantity !== row.originalQuantity)) {
    patch.products = task.value.products.map((row) => {
      const edited = products.value.find((item) => item.id === row.id)
      return productPayload(row, edited?.quantity || String(row.quantity))
    })
  }
  return patch
}

function validate() {
  if (!form.delivery_date) return '请选择预计交期。'
  if (task.value && form.delivery_date < task.value.order_date) return '预计交期不能早于下单日期。'
  for (const row of products.value) {
    if (!/^[1-9]\d*$/.test(row.quantity)) return `${row.productName} / ${row.colorLabel} 的数量必须是大于 0 的整数。`
    if (row.sourceLocked && row.quantity !== row.originalQuantity) return `${row.productName} / ${row.colorLabel} 来源于销售订单，数量不能在此修改。`
  }
  if (products.value.some((row) => row.quantity !== row.originalQuantity) && task.value?.products.some((row) => !row.product_color_id)) {
    return '存在缺少有效颜色的历史产品行，暂不能批量修改数量。'
  }
  return ''
}

function confirmationToken(error: unknown) {
  if (!(error instanceof AxiosError) || error.response?.status !== 409) return ''
  const data = error.response.data as { error?: { code?: string; meta?: { confirmation_token?: string } } }
  return data.error?.code === 'BOM_SYNC_CONFIRMATION_REQUIRED'
    ? data.error.meta?.confirmation_token || ''
    : ''
}

async function save() {
  const message = validate()
  if (message) { ElMessage.warning(message); return }
  const basePatch = buildPatch()
  if (!Object.keys(basePatch).length) { ElMessage.info('没有检测到需要保存的修改。'); return }
  try {
    await ElMessageBox.confirm(
      bomAffectedChanges.value.length
        ? `本次有 ${bomAffectedChanges.value.length} 项数量变更会影响关联 BOM。保存后任务将回到草稿并重新走 PMC；请选择的 BOM 处理方式为“${bomSyncMode.value === 'SYNC' ? '同步并生成必要的新版本' : '保留当前 BOM'}”。`
        : '保存后，待确认或已确认的任务将回到草稿，需要重新提交 PMC。',
      '确认保存修改',
      { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '取消' },
    )
  } catch { return }

  saving.value = true
  try {
    let patch = basePatch
    let result
    try {
      result = await updateProductionTask(taskId.value, patch, {}, {}, etag.value)
    } catch (error) {
      const token = confirmationToken(error)
      if (!token) throw error
      patch = { ...basePatch, bom_sync_mode: bomSyncMode.value, bom_sync_token: token }
      result = await updateProductionTask(taskId.value, patch, {}, {}, etag.value)
    }
    allowLeave.value = true
    ElMessage.success('生产任务单修改已保存。')
    await router.replace({ name: 'production-task-detail', params: { taskId: result.data.id } })
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [result, optionData] = await Promise.all([
      fetchProductionTask(taskId.value),
      fetchProductionTaskOptions(),
    ])
    task.value = result.data
    etag.value = result.etag
    options.value = optionData
    form.delivery_date = result.data.delivery_date
    form.follower_ids = result.data.followers.map((item) => item.id)
    originalRequirementsHtml.value = result.data.special_requirements_html || ''
    form.special_requirements_html = originalRequirementsHtml.value
    products.value = result.data.products.map((row) => ({
      id: row.id,
      productName: row.product_name,
      productCode: row.product_code,
      specification: row.specification,
      colorLabel: [row.color_name, row.color_code].filter(Boolean).join(' / ') || '未设置颜色',
      quantity: String(row.quantity),
      originalQuantity: String(row.quantity),
      unitName: row.unit_name,
      sourceLocked: Boolean(row.source_delivery_batch_line_id),
    }))
  } catch (error) {
    loadError.value = apiError(error)
  } finally {
    loading.value = false
  }
}

async function back() {
  await router.push({ name: 'production-task-detail', params: { taskId: taskId.value } })
}

onBeforeRouteLeave(async () => {
  if (!dirty.value || allowLeave.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，确认离开吗？', '未保存修改', {
      type: 'warning', confirmButtonText: '离开', cancelButtonText: '继续编辑',
    })
    return true
  } catch { return false }
})

onMounted(() => { void load() })
</script>

<template>
  <main class="production-edit-page" :class="{ 'is-loading': loading }" v-loading="loading" :aria-busy="loading">
    <template v-if="task && !loadError">
      <header class="page-heading">
        <div class="heading-title">
          <h1>编辑生产任务单</h1>
          <strong>{{ task.task_number }}</strong>
          <span :class="`task-status status-${task.status.toLowerCase()}`">{{ task.status_display }}</span>
        </div>
        <div class="heading-actions">
          <ElButton @click="back">取消</ElButton>
          <ElButton type="primary" :loading="saving" :disabled="isTerminal || !dirty" @click="save">保存修改</ElButton>
        </div>
      </header>

      <ElAlert
        type="warning" show-icon :closable="false" class="review-alert"
        title="修改待确认或已确认任务后将回到草稿，需重新提交 PMC 确认。"
      />

      <div class="edit-layout">
        <section class="edit-main">
          <article class="edit-section basic-section">
            <h2>基础信息</h2>
            <div class="info-grid">
              <label><span>生产任务单号</span><ElInput :model-value="task.task_number" disabled /></label>
              <label><span>来源订单</span><ElInput :model-value="task.source_sales_order_number || task.order_number" disabled /></label>
              <label><span>客户</span><ElInput :model-value="`${task.customer_code} · ${task.customer_name}`" disabled /></label>
              <label class="product-field"><span>产品</span><ElInput :model-value="productSummary" disabled /></label>
              <label><span>合计数量</span><ElInput :model-value="totalQuantity" disabled /></label>
              <label><span>预计交期</span><ElDatePicker v-model="form.delivery_date" type="date" value-format="YYYY-MM-DD" :disabled="isTerminal" /></label>
              <label><span>生产优先级</span><ElInput :model-value="priorityLabel" disabled /></label>
              <label><span>跟单员</span><ElSelect v-model="form.follower_ids" multiple filterable collapse-tags :disabled="isTerminal"><ElOption v-for="employee in followerOptions" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label>
              <label class="requirements-field"><span>生产要求</span><InquiryWangEditor v-model="form.special_requirements_html" upload-url="" upload-etag="" :show-upload-notice="false" :maxlength="4000" compact :inert="isTerminal" placeholder="填写生产要求、质量要求和注意事项" /></label>
            </div>
          </article>

          <article class="edit-section products-section">
            <div class="section-title-row"><h2>产品明细</h2><span><ElIcon><Lock /></ElIcon> 来源产品、颜色与数量按销售订单锁定</span></div>
            <div class="product-table-wrap">
              <table>
                <thead><tr><th>颜色</th><th>产品编码</th><th>产品名称</th><th>规格</th><th>生产数量</th><th>单位</th></tr></thead>
                <tbody>
                  <tr v-for="row in products" :key="row.id">
                    <td>{{ row.colorLabel }}</td><td>{{ row.productCode || '—' }}</td><td>{{ row.productName }}</td><td>{{ row.specification || '—' }}</td>
                    <td><ElInput v-model="row.quantity" inputmode="numeric" :disabled="row.sourceLocked || isTerminal" /></td>
                    <td>{{ row.unitName }}</td>
                  </tr>
                  <tr class="total-row"><td colspan="4">合计</td><td>{{ totalQuantity }}</td><td>{{ products[0]?.unitName || '—' }}</td></tr>
                </tbody>
              </table>
            </div>
          </article>

          <article class="edit-section bom-section">
            <h2>BOM同步设置</h2>
            <div class="bom-options">
              <span>修改后如何处理BOM *</span>
              <ElRadioGroup v-model="bomSyncMode">
                <ElRadio value="SYNC"><strong>修改任务并同步BOM</strong><small>同步已确认BOM将生成新版本，需单独重新确认BOM。</small></ElRadio>
                <ElRadio value="KEEP"><strong>仅保存任务</strong><small>仅保存生产任务，不同步BOM，现有BOM保持不变。</small></ElRadio>
              </ElRadioGroup>
            </div>
          </article>
        </section>

        <aside class="edit-aside">
          <article class="comparison-card">
            <div class="comparison-heading"><h2>变更对照</h2><span>仅显示本次修改的字段</span></div>
            <div v-if="!changes.length" class="no-changes">尚未修改任何字段</div>
            <table v-else class="comparison-table">
              <thead><tr><th>字段</th><th>修改前</th><th>修改后</th></tr></thead>
              <tbody><tr v-for="item in changes" :key="item.key"><td>{{ item.label }}</td><td>{{ item.before }}</td><td class="new-value">{{ item.after }}</td></tr></tbody>
            </table>
            <div class="impact-note">
              <ElIcon><WarningFilled /></ElIcon>
              <div><strong>修改影响提示</strong><p>1. 保存后任务回到草稿，需重新提交PMC。</p><p>2. 同步已确认BOM将生成新版本，需单独重新确认BOM。</p></div>
            </div>
            <div class="explanation-note">
              <strong>说明</strong>
              <p>• 本页面仅展示本次修改的字段变更对照。</p>
              <p>• 产品信息、来源订单等关键值不可修改。</p>
              <p>• 保存后如状态回到草稿，请重新提交PMC确认。</p>
            </div>
          </article>
        </aside>
      </div>
    </template>

    <ElResult v-else-if="loadError" icon="error" title="生产任务单加载失败" :sub-title="loadError">
      <template #extra><ElButton type="primary" @click="load">重新加载</ElButton><ElButton @click="back">返回详情</ElButton></template>
    </ElResult>
  </main>
</template>

<style scoped>
.production-edit-page { box-sizing: border-box; min-width: 1320px; min-height: 0; padding: 32px 28px 46px; color: #202124; background: var(--erp-page-background); --el-color-primary: #d7491c; }
.production-edit-page.is-loading { min-height: calc(100dvh - 84px); }
.page-heading { display: flex; height: 52px; align-items: flex-start; justify-content: space-between; }
.heading-title { display: flex; align-items: center; gap: 18px; }
.page-heading h1 { margin: 0; font-family: 'Noto Serif SC', 'Songti SC', serif; font-size: 32px; line-height: 42px; }
.heading-title > strong { font: 500 20px/32px 'Noto Sans SC', sans-serif; }
.heading-title > small { color: #68686a; font-size: 12px; }
.task-status { display: grid; min-width: 82px; height: 31px; padding: 0 10px; place-items: center; border-radius: 5px; color: #287abe; background: #d9eafa; font-size: 14px; }
.task-status.status-draft { color: #6f6a61; background: #ece9e2; }
.task-status.status-in_production { color: #17633c; background: #e5f5ec; }
.task-status.status-completed, .task-status.status-cancelled { color: #68686a; background: #eceff2; }
.heading-actions { display: flex; gap: 14px; padding-top: 3px; }
.heading-actions .el-button { min-width: 120px; height: 41px; margin: 0; }
.heading-actions :deep(.el-button--primary:not(.is-disabled)) { border-color: #d7491c; background: #d7491c; color: #fff; }
.review-alert { height: 45px; margin-bottom: 14px; border: 1px solid #e3dfd7; border-left: 3px solid #d7491c; border-radius: 5px; background: #fff3db; }
.edit-layout { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 10px; align-items: start; }
.edit-main, .comparison-card { box-sizing: border-box; min-height: calc(100vh - 217px); border: 1px solid #e3dfd7; border-radius: 5px; background: #fdfcf9; }
.edit-main { overflow: hidden; }
.edit-section { padding: 16px 20px 18px; border-bottom: 1px solid #e3dfd7; }
.edit-section:last-child { border-bottom: 0; }
.edit-section h2, .comparison-card h2 { margin: 0; font-family: 'Noto Serif SC', 'Songti SC', serif; font-size: 20px; line-height: 32px; }
.basic-section h2 { margin-bottom: 10px; border-bottom: 1px solid #e3dfd7; }
.info-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px 14px; }
.info-grid label > span { display: block; margin-bottom: 5px; color: #68686a; font-size: 12px; }
.info-grid :deep(.el-select), .info-grid :deep(.el-date-editor) { width: 100%; }
.info-grid :deep(.el-input__wrapper), .info-grid :deep(.el-textarea__inner) { border-radius: 5px; box-shadow: 0 0 0 1px #d9dbe0 inset; }
.info-grid :deep(.el-input.is-disabled .el-input__wrapper),
.product-table-wrap :deep(.el-input.is-disabled .el-input__wrapper) { background: #f0eadf; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.product-field { grid-column: span 2; }
.requirements-field { grid-column: 1 / -1; }
.requirements-field :deep(.inquiry-wang-editor__surface) { height: 78px; border-radius: 5px; border-color: #d9dbe0; }
.requirements-field :deep(.w-e-toolbar) { display: none; }
.requirements-field :deep(.w-e-text-container) { height: 76px !important; min-height: 0; }
.requirements-field :deep(.w-e-text-container [data-slate-editor]) { min-height: 76px; padding: 8px 11px; font-size: 14px; line-height: 22px; }
.section-title-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-title-row > span { display: flex; align-items: center; gap: 5px; color: #68686a; font-size: 12px; }
.product-table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px; }
th { height: 42px; padding: 0 14px; border: 1px solid #e3dfd7; color: #68686a; background: #efebe3; font-weight: 500; text-align: left; }
td { height: 46px; padding: 0 14px; border: 1px solid #e3dfd7; vertical-align: middle; }
th:nth-child(1) { width: 130px; } th:nth-child(2) { width: 160px; } th:nth-child(3) { width: 185px; }
th:nth-child(4) { width: 180px; } th:nth-child(5) { width: 170px; } th:nth-child(6) { width: 100px; }
.product-table-wrap :deep(.el-input__wrapper) { min-height: 34px; border-radius: 5px; }
.total-row td { font-weight: 600; }
.bom-section h2 { margin-bottom: 10px; }
.bom-options { display: grid; grid-template-columns: 175px 1fr; min-height: 94px; padding: 14px 17px; border: 1px solid #e3dfd7; border-radius: 5px; }
.bom-options > span { padding-top: 4px; font-size: 13px; }
.bom-options :deep(.el-radio-group) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.bom-options :deep(.el-radio) { height: auto; margin: 0; align-items: flex-start; white-space: normal; }
.bom-options :deep(.el-radio__label) { display: grid; gap: 4px; color: #202124; }
.bom-options :deep(.el-radio__label strong) { font-size: 13px; }
.bom-options :deep(.el-radio__label small) { color: #949498; font-size: 11px; line-height: 17px; }
.comparison-card { padding: 16px 22px 28px; }
.comparison-heading { display: flex; align-items: center; gap: 22px; margin-bottom: 10px; }
.comparison-heading span { color: #68686a; font-size: 12px; }
.no-changes { display: grid; min-height: 170px; place-items: center; border: 1px solid #e3dfd7; color: #949498; font-size: 13px; }
.comparison-table th, .comparison-table td { width: auto; }
.comparison-table .new-value { color: #d7491c; }
.impact-note, .explanation-note { margin-top: 32px; border: 1px solid #e3dfd7; border-radius: 5px; }
.impact-note { display: flex; gap: 14px; min-height: 137px; box-sizing: border-box; padding: 22px 16px; background: #f5eee3; }
.impact-note .el-icon { margin-top: 2px; color: #d7491c; font-size: 22px; }
.impact-note strong, .explanation-note strong { font-size: 15px; }
.impact-note p, .explanation-note p { margin: 8px 0 0; font-size: 13px; line-height: 22px; }
.explanation-note { min-height: 167px; padding: 20px 18px; color: #68686a; background: #f5f5f4; }
.explanation-note strong { color: #202124; }
@media (max-width: 1440px) { .production-edit-page { padding-inline: 20px; } }
</style>
