<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createWageScheme, createWageSchemeChange, fetchReportingContext, fetchWageScheme, fetchWageSchemeHistory, submitWageScheme, updateWageScheme } from '@/api/workshopReporting'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import WorkshopConfigManager from '@/components/workshop/WorkshopConfigManager.vue'
import { useAuthStore } from '@/stores/auth'
import type { ReportingContext, WageScheme, WageSchemeLineInput, WorkCountingMode } from '@/types/workshopReporting'
import { isPlainWageMoney, sumWageAmounts } from '@/utils/wageMoney'

const route = useRoute(); const router = useRouter()
const auth = useAuthStore()
const isChange = computed(() => Boolean(route.params.schemeId))
const canSubmit = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.submit_wagescheme'))
const context = ref<ReportingContext | null>(null)
const loading = ref(false); const saving = ref(false); const etag = ref('')
const hydrating = ref(false)
const sourceStatus = ref('')
const savedSchemeId = ref<string | null>(null)
let contextRequestSequence = 0
let historyRequestSequence = 0
const form = reactive({ scheduleProductId: String(route.query.schedule_product_id || ''), workshopId: String(route.query.workshop_id || ''), craftIds: route.query.craft_id ? [String(route.query.craft_id)] : [] as string[], operationProductName: '', remark: '', historySourceSchemeId: null as string | null, lines: [] as WageSchemeLineInput[] })
const historyVisible = ref(false); const historyLoading = ref(false); const historyRows = ref<WageScheme[]>([])
const operationManagerVisible = ref(false)
const scheduleProduct = computed(() => {
  const selected = context.value?.schedule_product
  if (selected?.id === form.scheduleProductId) return selected
  return context.value?.schedule_products.find(item => item.id === form.scheduleProductId) || null
})
const craftOptions = computed(() => context.value?.crafts.filter(item => item.workshop_id === form.workshopId) || [])
const selectedCraftId = computed({
  get: () => form.craftIds[0] || '',
  set: (value: string) => { form.craftIds = value ? [value] : [] },
})
const selectedCraft = computed(() => craftOptions.value.find(item => item.id === selectedCraftId.value) || null)
const isMetalCraft = (craft: ReportingContext['crafts'][number] | null | undefined) => (
  context.value?.workshops.find(item => item.id === craft?.workshop_id)?.name === '金工车间'
)
const isMetalWorkshop = computed(() => isMetalCraft(selectedCraft.value))
const selectedPlanCategory = computed(() => isMetalWorkshop.value ? 'METAL' : (selectedCraft.value?.plan_category || ''))
const usesBomName = computed(() => ['METAL', 'CUTTING', 'SEWING'].includes(selectedPlanCategory.value || ''))
const isSewingCraft = computed(() => selectedPlanCategory.value === 'SEWING')
const bomItemsForCraft = computed(() => (context.value?.bom_items || []).filter(item => (
  selectedPlanCategory.value === 'METAL' ? item.source_type === 'METAL' : item.source_type === 'CUTTING'
)))
const operationProductNameOptions = computed(() => [...new Set((context.value?.operations || []).filter(item => form.craftIds.includes(item.craft_id)).map(item => item.product_name))].sort())
const operationOptions = (craftId: string) => {
  const craft = context.value?.crafts.find(item => item.id === craftId)
  if (!craft || craft.workshop_id !== form.workshopId) return []
  return context.value?.operations.filter(item => (
    item.craft_id === craftId
    && (isMetalCraft(craft) || item.product_name === form.operationProductName)
  )) || []
}
const moneyTotal = computed(() => sumWageAmounts(
  form.lines.filter(item => item.status === 'ACTIVE').map(item => item.declared_price),
))
const errorText = (error: unknown) => (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message || '操作失败。'
function defaultCountingMode(): WorkCountingMode {
  if (selectedPlanCategory.value === 'METAL') return 'PIECE'
  if (selectedPlanCategory.value === 'CUTTING') return 'SET'
  if (selectedPlanCategory.value === 'SEWING') return 'SET'
  return 'ORDER'
}
function addLine() { form.lines.push({ bom_line_id: null, craft_id: form.craftIds[0] || '', operation_id: '', display_name: '', counting_mode: defaultCountingMode(), production_description: '', previous_price: null, revised_price: null, declared_price: '', status: 'ACTIVE', note: '' }) }
function operationChanged(line: WageSchemeLineInput) { const option = context.value?.operations.find(item => item.id === line.operation_id); if (option && !usesBomName.value && !line.display_name) line.display_name = option.name }
function openOperationManager() {
  if (!form.workshopId || !selectedCraftId.value) return ElMessage.warning('请先选择车间和工艺。')
  operationManagerVisible.value = true
}
async function refreshOperationsAfterSave() {
  try {
    context.value = await fetchReportingContext(form.scheduleProductId || undefined)
    operationManagerVisible.value = false
  } catch (error) {
    ElMessage.error(errorText(error))
  }
}
function bomChanged(line: WageSchemeLineInput) {
  const option = bomItemsForCraft.value.find(item => item.id === line.bom_line_id)
  line.display_name = option?.label || ''
}
function bomLineId(componentIdentity: string | null | undefined) {
  return (context.value?.bom_items || []).find(item => item.component_identity === componentIdentity)?.id || null
}
function requiredQuantity(line: WageSchemeLineInput) {
  const orderQuantity = Number(scheduleProduct.value?.order_quantity)
  if (!Number.isFinite(orderQuantity)) return null
  if (!usesBomName.value) return orderQuantity
  const option = bomItemsForCraft.value.find(item => item.id === line.bom_line_id)
  if (!option) return null
  if (selectedPlanCategory.value === 'METAL') return option.pieces_per_product ? orderQuantity * option.pieces_per_product : null
  if (!option.cutting_sets_per_product || !option.cutting_pieces_per_set) return null
  const setQuantity = orderQuantity * option.cutting_sets_per_product
  return line.counting_mode === 'PIECE' ? setQuantity * option.cutting_pieces_per_set : setQuantity
}
function quantityText(value: number | null) { return value === null ? '待完善 BOM' : value.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }
async function openHistory() {
  if (!form.workshopId) return ElMessage.warning('请先选择当前车间。')
  const workshopId = form.workshopId
  const current = ++historyRequestSequence
  historyRows.value = []; historyVisible.value = true; historyLoading.value = true
  try {
    const result = await fetchWageSchemeHistory({ workshop_id: workshopId, page: 1, page_size: 100 })
    if (current === historyRequestSequence && workshopId === form.workshopId) {
      historyRows.value = result.data.filter(item => item.workshop.id === workshopId)
    }
  } catch (error) {
    if (current === historyRequestSequence) ElMessage.error(errorText(error))
  } finally { if (current === historyRequestSequence) historyLoading.value = false }
}
function historyBomOption(line: WageScheme['lines'][number]) {
  const byIdentity = line.bom_component_identity
    ? bomItemsForCraft.value.filter(item => item.component_identity === line.bom_component_identity) : []
  if (byIdentity.length) return byIdentity.length === 1 ? byIdentity[0] : undefined
  // 不同产品的 BOM 部件编号不同；仅完整名称唯一相同时自动对应，不能按行号或近似名称套价。
  const byName = bomItemsForCraft.value.filter(item => item.label === line.display_name.trim())
  return byName.length === 1 ? byName[0] : undefined
}
async function useHistory(item: WageScheme) {
  const sameWorkshop = item.workshop.id === form.workshopId
  const selectedCraftIds = new Set(form.craftIds)
  const sameCrafts = item.crafts.length === selectedCraftIds.size && item.crafts.every(craft => selectedCraftIds.has(craft.id))
  const sameOperationProduct = isMetalWorkshop.value || item.operation_product_name === form.operationProductName
  if (!sameWorkshop || !sameCrafts || !sameOperationProduct) return ElMessage.warning('该历史方案的车间、工艺或工序品名与当前范围不匹配，不能直接引用。')
  if (form.lines.length) {
    try {
      await ElMessageBox.confirm(
        `引用后将替换当前 ${form.lines.length} 条工价明细，此操作尚未保存。是否继续？`,
        '确认替换明细',
        { type: 'warning', confirmButtonText: '继续引用', cancelButtonText: '取消' },
      )
    } catch { return }
  }
  form.historySourceSchemeId = item.id
  form.lines = item.lines.filter(line => line.status === 'ACTIVE').map(line => {
    const option = usesBomName.value ? historyBomOption(line) : undefined
    return { bom_line_id: option?.id || null, craft_id: line.craft_id, operation_id: line.operation_id, display_name: option?.label || line.display_name, counting_mode: line.counting_mode, production_description: line.production_description, previous_price: line.declared_price, revised_price: null, declared_price: line.declared_price, status: 'ACTIVE', note: line.note }
  })
  historyVisible.value = false
  const unmatched = usesBomName.value ? form.lines.filter(line => !line.bom_line_id).length : 0
  if (unmatched) ElMessage.warning(`已引用工价，${unmatched} 条名称 / 部位未能唯一对应当前 BOM，请手动选择后再提交。`)
  else ElMessage.success('已复制历史批准工价；当前方案仍需重新送审。')
}
watch(() => form.workshopId, () => {
  historyRequestSequence += 1
  historyRows.value = []; historyVisible.value = false; historyLoading.value = false
  form.historySourceSchemeId = null
})
watch(() => form.scheduleProductId, async (value, previous) => {
  if (hydrating.value || value === previous) return
  if (form.craftIds.length || form.lines.length) ElMessage.warning('排产产品已切换，原车间、工艺和工价明细已清空，请重新选择。')
  form.workshopId = ''; form.craftIds = []; form.operationProductName = ''; form.lines = []
  const current = ++contextRequestSequence
  loading.value = true
  try {
    const nextContext = await fetchReportingContext(value || undefined)
    if (current === contextRequestSequence) context.value = nextContext
  } catch (error) {
    if (current === contextRequestSequence) { context.value = null; ElMessage.error(errorText(error)) }
  } finally { if (current === contextRequestSequence) loading.value = false }
})
watch(() => form.workshopId, (value, previous) => {
  if (loading.value || !previous || value === previous) return
  if (form.craftIds.length || form.lines.length) ElMessage.warning('车间已切换，原工艺和工价明细已清空，请重新选择。')
  form.craftIds = []; form.operationProductName = ''; form.lines = []
})
watch(craftOptions, (options) => {
  if (!form.craftIds.length && options.length === 1) form.craftIds = [options[0]!.id]
}, { immediate: true })
watch(() => [...form.craftIds], (craftIds, previous) => {
  const currentCraft = (context.value?.crafts || []).find(item => item.id === craftIds[0])
  const previousCraft = (context.value?.crafts || []).find(item => item.id === previous[0])
  const isCurrentMetal = isMetalCraft(currentCraft)
  if (isCurrentMetal && currentCraft) form.operationProductName = currentCraft.name
  else if (isMetalCraft(previousCraft)) form.operationProductName = ''
  if (loading.value || !previous.length) return
  const allowed = new Set(craftIds)
  if (!isCurrentMetal) {
    const validProductNames = new Set((context.value?.operations || []).filter(item => allowed.has(item.craft_id)).map(item => item.product_name))
    if (form.operationProductName && !validProductNames.has(form.operationProductName)) form.operationProductName = ''
  }
  const removedCount = form.lines.filter(line => !allowed.has(line.craft_id)).length
  if (removedCount) {
    form.lines = form.lines.filter(line => allowed.has(line.craft_id))
    ElMessage.warning(`工艺已变化，已清除 ${removedCount} 条不再匹配的工价明细。`)
  }
})
watch(() => form.operationProductName, (value, previous) => {
  if (isMetalWorkshop.value || loading.value || !previous || value === previous) return
  const validOperationIds = new Set((context.value?.operations || []).filter(item => item.product_name === value && form.craftIds.includes(item.craft_id)).map(item => item.id))
  const removedCount = form.lines.filter(line => !validOperationIds.has(line.operation_id)).length
  if (removedCount) {
    form.lines = form.lines.filter(line => validOperationIds.has(line.operation_id))
    ElMessage.warning(`工序品名已变化，已清除 ${removedCount} 条不再匹配的工价明细。`)
  }
})
async function load() {
  const current = ++contextRequestSequence
  hydrating.value = true
  loading.value = true
  let loadedScheme: WageScheme | null = null
  try {
    if (isChange.value) {
      const result = await fetchWageScheme(String(route.params.schemeId)); etag.value = result.etag
      const scheme = result.data
      loadedScheme = scheme
      sourceStatus.value = scheme.status
      form.scheduleProductId = scheme.schedule_product_id || ''; form.workshopId = scheme.workshop.id
      form.craftIds = scheme.crafts.map(item => item.id); form.operationProductName = scheme.operation_product_name; form.remark = scheme.remark
      form.lines = scheme.lines.map(item => ({ work_item_id: item.work_item_id, bom_line_id: null, craft_id: item.craft_id, operation_id: item.operation_id, display_name: item.display_name, counting_mode: item.counting_mode, production_description: item.production_description, previous_price: item.declared_price, revised_price: null, declared_price: item.declared_price, status: item.status, note: item.note }))
    }
    const nextContext = await fetchReportingContext(form.scheduleProductId || undefined)
    if (current === contextRequestSequence) {
      context.value = nextContext
      if (loadedScheme) {
        form.lines.forEach((line, index) => { line.bom_line_id = bomLineId(loadedScheme?.lines[index]?.bom_component_identity) })
      }
    }
  } catch (error) { ElMessage.error(errorText(error)) }
  finally {
    if (current === contextRequestSequence) {
      hydrating.value = false
      loading.value = false
    }
  }
}
async function submitForApproval() {
  if (!canSubmit.value) return ElMessage.warning('当前账号没有提交工价审批的权限。')
  if (!scheduleProduct.value) return ElMessage.warning('请选择排产产品。')
  if (!form.workshopId) return ElMessage.warning('请选择车间。')
  if (!form.craftIds.length) return ElMessage.warning('至少选择一项工艺。')
  if (!isMetalWorkshop.value && !form.operationProductName) return ElMessage.warning('请选择工序品名。')
  if (usesBomName.value && !bomItemsForCraft.value.length) return ElMessage.warning(isMetalWorkshop.value ? '当前产品已确认 BOM 中没有可选的部件、材质和规格。' : '当前产品已确认 BOM 中没有可选的名称和规格。')
  if (!form.lines.length) return ElMessage.warning('至少添加一条工价明细。')
  if (form.lines.some(item => !item.craft_id || !item.operation_id || !item.display_name.trim() || item.declared_price === '')) return ElMessage.warning('请补齐工价明细。')
  if (usesBomName.value && form.lines.some(item => !item.bom_line_id)) return ElMessage.warning('名称 / 部位必须从当前产品 BOM 中选择。')
  if (isSewingCraft.value && form.lines.some(item => !['SET', 'PIECE'].includes(item.counting_mode))) return ElMessage.warning('请选择车缝计数方式。')
  if (form.lines.some(item => requiredQuantity(item) === null)) return ElMessage.warning('BOM 缺少计算需完成次数的数据，请先完善 BOM。')
  const hasInvalidMoney = form.lines.some(item => {
    const values = [item.declared_price, item.previous_price, item.revised_price]
    return values.some(value => value !== null && value !== undefined && value !== '' && !isPlainWageMoney(value))
  })
  if (hasInvalidMoney) return ElMessage.warning('工价金额仅支持普通数字格式，例如 0.5，不能使用科学计数法。')
  if (usesBomName.value) {
    const allowedDisplayNames = new Set(bomItemsForCraft.value.map(item => item.label))
    if (form.lines.some(item => !allowedDisplayNames.has(item.display_name))) return ElMessage.warning('名称 / 部位必须从当前产品 BOM 中选择。')
  }
  saving.value = true
  try {
    const payload = {
      product_line_id: scheduleProduct.value.product_line_id,
      schedule_product_id: scheduleProduct.value.id,
      workshop_id: form.workshopId,
      craft_ids: form.craftIds,
      ...(!isMetalWorkshop.value ? { operation_product_name: form.operationProductName } : {}),
      remark: form.remark.trim(),
      history_source_scheme_id: form.historySourceSchemeId,
      lines: form.lines,
    }
    if (savedSchemeId.value) {
      const latest = await fetchWageScheme(savedSchemeId.value)
      etag.value = latest.etag
      if (latest.data.status === 'PENDING_APPROVAL') {
        ElMessage.success('工价方案已提交厂长审批。')
        await router.replace({ name: 'wage-schemes', query: { detail: latest.data.id } })
        return
      }
    }
    const result = savedSchemeId.value
      ? await updateWageScheme(savedSchemeId.value, payload, etag.value)
      : !isChange.value
      ? await createWageScheme(payload)
      : sourceStatus.value === 'APPROVED'
        ? await createWageSchemeChange(String(route.params.schemeId), payload, etag.value)
        : await updateWageScheme(String(route.params.schemeId), payload, etag.value)
    savedSchemeId.value = result.data.id
    etag.value = result.etag
    try {
      const submitted = await submitWageScheme(result.data.id, result.etag)
      ElMessage.success('工价方案已提交厂长审批。')
      await router.replace({ name: 'wage-schemes', query: { detail: submitted.data.id } })
    } catch (error) {
      try {
        const latest = await fetchWageScheme(result.data.id)
        savedSchemeId.value = latest.data.id
        etag.value = latest.etag
        if (latest.data.status === 'PENDING_APPROVAL') {
          ElMessage.success('工价方案已提交厂长审批。')
          await router.replace({ name: 'wage-schemes', query: { detail: latest.data.id } })
          return
        }
      } catch {
        // 保留当前表单和已知版本，允许用户修正网络或业务问题后再次提交。
      }
      ElMessage.warning(`提交审批失败，请修正后重试：${errorText(error)}`)
    }
  } catch (error) { ElMessage.error(errorText(error)) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="wr-page wr-form-page erp-glass-form" :class="{ 'wr-form-page--change': isChange }" data-testid="wage-scheme-form">
    <header class="wr-heading wr-form-heading"><h1>{{ isChange ? '变更工价方案' : '新增工价方案' }}</h1></header>
    <div class="wr-form-grid"><section class="wr-card"><div class="wr-card-title"><h2>基本信息</h2></div><ElForm label-position="top">
      <ElFormItem label="排产产品" required><ElSelect v-model="form.scheduleProductId" filterable placeholder="选择排产产品" :disabled="isChange"><ElOption v-for="item in context?.schedule_products || []" :key="item.id" :label="`${item.task_number} · ${item.product_name}（${item.product_code || item.product_number}）`" :value="item.id" /></ElSelect></ElFormItem>
      <ElFormItem label="所属生产订单"><ElInput data-testid="production-order-input" :model-value="scheduleProduct?.order_number || ''" readonly placeholder="选择排产产品后自动带出" /></ElFormItem>
      <ElFormItem label="车间" required><ElSelect v-model="form.workshopId" :disabled="isChange" placeholder="选择车间"><ElOption v-for="item in context?.workshops || []" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></ElFormItem>
      <ElFormItem label="工艺" required><ElSelect v-model="selectedCraftId" data-testid="wage-craft-select" filterable :disabled="isChange" placeholder="选择工艺"><ElOption v-for="item in craftOptions" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></ElFormItem>
      <ElFormItem label="工序配置"><ElButton data-testid="add-operation-button" type="primary" @click="openOperationManager">添加工序</ElButton></ElFormItem>
      <ElFormItem v-if="!isMetalWorkshop" data-testid="operation-product-name-field" label="工序品名" required><ElSelect v-model="form.operationProductName" filterable placeholder="选择工序目录中的品名"><ElOption v-for="item in operationProductNameOptions" :key="item" :label="item" :value="item" /></ElSelect></ElFormItem>
      <ElFormItem label="备注"><ElInput v-model="form.remark" type="textarea" :rows="4" maxlength="2000" show-word-limit /></ElFormItem>
    </ElForm></section><section class="wr-card wr-card--wide"><div class="wr-card-title"><h2>工价明细</h2><div><ElButton class="wr-history-button" @click="openHistory">选择历史数据</ElButton><ElButton class="wr-add-line-button" type="primary" :icon="Plus" @click="addLine">添加明细</ElButton></div></div>
      <ElTable class="erp-table-editor wr-wage-line-table scroll-actions-table" :data="form.lines" border>
        <ElTableColumn label="名称 / 部位" min-width="190" align="left"><template #default="{ row }"><ElSelect v-if="usesBomName" v-model="row.bom_line_id" :data-testid="isMetalWorkshop ? 'metal-bom-display-select' : 'bom-display-select'" filterable :placeholder="!row.bom_line_id && row.display_name ? `未匹配：${row.display_name}，请选择` : (isMetalWorkshop ? '选择部件、材质和规格' : '选择 BOM 名称和规格')" @change="bomChanged(row)"><ElOption v-for="item in bomItemsForCraft" :key="item.id" :label="item.label" :value="item.id" /></ElSelect><ElInput v-else v-model="row.display_name" maxlength="200" /></template></ElTableColumn>
        <ElTableColumn label="申报工序" min-width="140" align="left"><template #default="{ row }"><ElSelect v-model="row.operation_id" data-testid="wage-operation-select" filterable @change="operationChanged(row)"><ElOption v-for="item in operationOptions(row.craft_id)" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></template></ElTableColumn>
        <ElTableColumn v-if="isSewingCraft" label="计数方式" width="106" align="left"><template #default="{ row }"><ElSelect v-model="row.counting_mode"><ElOption label="按套" value="SET" /><ElOption label="按片" value="PIECE" /></ElSelect></template></ElTableColumn>
        <ElTableColumn label="需完成次数" width="108" align="right"><template #default="{ row }">{{ quantityText(requiredQuantity(row)) }}</template></ElTableColumn>
        <ElTableColumn label="制作工序描述" min-width="150" align="left"><template #default="{ row }"><ElInput v-model="row.production_description" data-testid="wage-production-description-input" maxlength="500" /></template></ElTableColumn>
        <ElTableColumn label="申报工价" width="106" align="center" class-name="wr-centered-control"><template #default="{ row }"><ElInput v-model="row.declared_price" inputmode="decimal" /></template></ElTableColumn>
        <ElTableColumn label="状态" width="100" align="center"><template #default="{ row }"><ElSelect v-model="row.status" class="wr-status-select" :class="{ 'is-active': row.status === 'ACTIVE', 'is-void': row.status === 'VOID' }"><ElOption label="正常" value="ACTIVE" /><ElOption label="作废" value="VOID" /></ElSelect></template></ElTableColumn>
        <ElTableColumn label="以往工价" width="106" align="center" class-name="wr-centered-control"><template #default="{ row }"><ElInput v-model="row.previous_price" inputmode="decimal" /></template></ElTableColumn>
        <ElTableColumn label="修改工价" width="106" align="center" class-name="wr-centered-control"><template #default="{ row }"><ElInput v-model="row.revised_price" inputmode="decimal" /></template></ElTableColumn>
        <ElTableColumn label="备注" min-width="145" align="center" class-name="wr-centered-control"><template #default="{ row }"><ElInput v-model="row.note" data-testid="wage-line-note-input" maxlength="500" /></template></ElTableColumn>
        <ElTableColumn label="操作" width="80" align="center" fixed="right" class-name="wr-wage-actions"><template #default="{ $index }"><ElButton class="wr-delete-action" link type="primary" :icon="Delete" aria-label="删除明细" title="删除明细" @click="form.lines.splice($index, 1)" /></template></ElTableColumn>
      </ElTable><footer class="wr-total">工价合计：<strong>¥{{ moneyTotal }}</strong></footer>
    </section></div>
    <footer class="wr-form-actions"><ElButton @click="router.push({ name: 'wage-schemes' })">返回</ElButton><ElButton v-if="canSubmit" type="primary" :loading="saving" @click="submitForApproval">提交厂长审批</ElButton></footer>
    <AppWindowDialog v-model="historyVisible" title="引用历史批准工价" :width="1040" :height="680" destroy-on-close><ElTable v-loading="historyLoading" :data="historyRows" border height="540" empty-text="暂无可见的批准历史方案"><ElTableColumn prop="scheme_number" label="方案编号" width="170" /><ElTableColumn label="订单 / 产品" min-width="260"><template #default="{ row }">{{ row.production_task.task_number }} · {{ row.product.name }}</template></ElTableColumn><ElTableColumn label="车间 / 工艺" min-width="220"><template #default="{ row }">{{ row.workshop.name }} · {{ row.crafts.map((item: { name: string }) => item.name).join('、') }}</template></ElTableColumn><ElTableColumn label="有效期" width="190"><template #default="{ row }">{{ row.effective_from }} 至 {{ row.effective_to || '长期' }}</template></ElTableColumn><ElTableColumn label="操作" width="90" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="useHistory(row)">引用</ElButton></template></ElTableColumn></ElTable></AppWindowDialog>
    <AppWindowDialog v-model="operationManagerVisible" title="添加工序" :width="1100" :height="720" destroy-on-close><WorkshopConfigManager kind="operations" :initial-workshop="form.workshopId" initial-craft-type="INTERNAL" :initial-craft="selectedCraftId" @saved="refreshOperationsAfterSave" /></AppWindowDialog>
  </section>
</template>

<style lang="scss">
@use '@/styles/workshopReporting.scss';

.wr-form-page[data-testid='wage-scheme-form'] > .wr-form-heading { min-height: 44px; align-items: center; margin-bottom: 14px; }
.wr-form-page--change .wr-form-actions { margin-top: 14px; }
.wr-wage-line-table .wr-wage-actions .cell { white-space: nowrap; }
.wr-form-page .wr-wage-line-table .wr-delete-action.el-button.is-link { width: 32px; font-size: 16px; }
@media (max-width: 1440px) {
  [data-testid='wage-scheme-form'] > .wr-form-grid { grid-template-columns: 280px minmax(0, 1fr); overflow-x: visible; }
}
</style>
