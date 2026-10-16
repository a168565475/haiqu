<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import { confirmMaterialIssue, fetchMaterialIssue, materialIssueProductImageUrl, previewMaterialIssue, returnMaterialIssue } from '@/api/materialIssues'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BomAttributesTooltip from '@/components/common/BomAttributesTooltip.vue'
import { issueQuantityText } from '@/utils/materialIssueQuantities'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { MaterialIssue, MaterialIssueLine, MaterialIssuePreviewLine, MaterialIssueStatus } from '@/types/materialIssue'

const route = useRoute()
const auth = useAuthStore()
const issueId = computed(() => String(route.params.issueId || ''))
const issue = ref<MaterialIssue | null>(null)
const etag = ref('')
const loading = ref(false)
const acting = ref(false)
const returnVisible = ref(false)
const confirmVisible = ref(false)
const confirmRequestId = ref(crypto.randomUUID())
const loadError = ref('')
const previewError = ref('')
const previewLines = ref<MaterialIssuePreviewLine[]>([])
const previewReady = ref(false)
const returnReason = ref('')
const canReview = computed(() => auth.user?.is_superuser === true || auth.hasPermission('material_issues.review_materialissue'))
const canEdit = computed(() => auth.user?.is_superuser === true || (
  auth.hasPermission('material_issues.change_materialissue')
  && Boolean(issue.value)
  && auth.user?.employee?.id === issue.value?.created_by.id
))
const rawLines = computed(() => issue.value?.lines.filter((item) => item.line_type === 'RAW') || [])
const semiLines = computed(() => issue.value?.lines.filter((item) => item.line_type === 'SEMI') || [])
const isIssued = computed(() => issue.value?.status === 'ISSUED')
const isPublicIssue = computed(() => issue.value?.stock_mode === 'PUBLIC_V2')
const hasPublicSemi = computed(() => semiLines.value.some(line => isPublicLine(line)))
const confirmationRows = computed(() => (issue.value?.lines || []).map(line => {
  const current = previewLines.value.find(row => (row.line_id || row.id) === line.id)
  // 数量取本次预检；旧详情只提供不变的物料名称、申请数量和单位。
  return { ...line,
    required_quantity: current?.required_quantity,
    internal_issued_quantity: current?.internal_issued_quantity,
    outsourcing_issued_quantity: current?.outsourcing_issued_quantity,
    pending_issue_quantity: current?.pending_issue_quantity,
    order_remaining: current?.order_remaining,
    available_stock: current?.available_stock,
    max_issue_quantity: current?.max_issue_quantity,
    bar_count: current?.bar_count ?? (isPublicLine(line) ? undefined : line.bar_count),
    meters: current?.meters ?? (isPublicLine(line) ? undefined : line.meters),
  }
}))
const publicAllocations = computed(() => (issue.value?.lines || []).flatMap(line =>
  (line.public_stock_allocations || []).map(allocation => ({ ...allocation,
    material_name: line.conversion_snapshot?.part_name || line.material_name,
    bom_attributes: line.bom_attributes,
    material: materialValue(line),
    specification: specificationValue(line),
    color: line.line_type === 'SEMI' ? colorValue(line, true) : colorValue(line),
    line_type: line.line_type, request_unit: line.unit,
  }))))
const canOpenMetalProcessing = computed(() => isIssued.value && issue.value?.workshop?.name === '金工车间'
  && rawLines.value.some(line => line.conversion_snapshot?.kind === 'PIPE')
  && (auth.user?.is_superuser || auth.hasPermission('material_issues.view_metalprocessingsource')))
const isReturned = computed(() => issue.value?.status === 'RETURNED')
const returnEvent = computed(() => [...(issue.value?.audit_events || [])].reverse().find((item) => item.action === 'RETURNED'))
const conflictLine = computed(() => issue.value?.lines.find(overStock) || issue.value?.lines.find(overAllowance) || null)
const conflictKind = computed(() => conflictLine.value ? (overStock(conflictLine.value) ? 'stock' : 'allowance') : '')
const productImageUrl = computed(() => {
  const taskId = issue.value?.production_task?.id
  const imageId = issue.value?.product?.image_file_id
  return taskId && imageId ? materialIssueProductImageUrl(taskId, imageId) : productImagePlaceholder
})
function apiMessage(error: unknown, timeoutMessage = '操作超时，请稍后重试。'): string {
  const businessMessage = (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message
  if (businessMessage) return businessMessage
  if (isAxiosError(error) && (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT')) return timeoutMessage
  return '操作失败，请稍后重试。'
}
const numberText = (value: string | null | undefined) => value == null ? '—' : issueQuantityText(value)
const dateText = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const statusClass = (status?: MaterialIssueStatus) => ({ DRAFT: 'is-draft', PENDING_REVIEW: 'is-pending', RETURNED: 'is-returned', ISSUED: 'is-issued' }[status || 'DRAFT'])
const sectionLabels: Record<string, string> = {
  PROFILE: '管材类', HARDWARE: '五金件', PLASTIC: '塑料件类', AUXILIARY: '辅料类',
  FABRIC: '面料类', PACKAGING: '包材类', SEMI: '委外回库半成品',
}
const sectionText = (value: string | null | undefined) => value ? (sectionLabels[value] || value) : '—'
const tooltipKeys = ['part_name', 'material', 'specification', 'hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color']
const attributeValue = (row: MaterialIssueLine, keys: string[], fallback = '') => {
  const field = (row.bom_attributes || []).find(item => keys.includes(item.key) && String(item.value || '').trim())
  return field?.value || fallback || '—'
}
const materialValue = (row: MaterialIssueLine) => attributeValue(row, ['material'], row.material || '')
const specificationValue = (row: MaterialIssueLine) => attributeValue(row, ['specification'], row.specification || '')
const colorValue = (row: MaterialIssueLine, preferActual = false) => {
  if (preferActual && String(row.color || '').trim()) return row.color
  return attributeValue(row, ['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'], row.color || '')
}
const overStock = (line: MaterialIssueLine) => Number(line.requested_quantity) > Number(line.available_stock)
const overAllowance = (line: MaterialIssueLine) => Number(line.requested_quantity) > Number(line.order_remaining)
function isPublicLine(line: MaterialIssueLine): boolean { return line.stock_mode === 'PUBLIC_V2' || isPublicIssue.value }

async function load() {
  loading.value = true
  loadError.value = ''
  try { const result = await fetchMaterialIssue(issueId.value); issue.value = result.data; etag.value = result.etag }
  catch (error) { loadError.value = apiMessage(error); ElMessage.error(loadError.value) }
  finally { loading.value = false }
}
async function openConfirmation() {
  if (!issue.value || acting.value) return
  acting.value = true; previewError.value = ''; previewReady.value = false; previewLines.value = []
  try {
    const preview = await previewMaterialIssue(issue.value.id)
    previewLines.value = preview.lines || []
    previewReady.value = preview.can_confirm && issue.value.lines.every(line =>
      previewLines.value.some(row => (row.line_id || row.id) === line.id))
    if (!preview.can_confirm) previewError.value = preview.errors?.map(e => e.detail).join('；') || '库存、额度或来源已变化，请刷新核对。'
    else if (!previewReady.value) previewError.value = '出库预检明细不完整，请重新核对后再确认。'
    confirmVisible.value = true
  } catch (error) { previewError.value = apiMessage(error, '出库预检超时，请稍后重试。'); ElMessage.error(previewError.value) }
  finally { acting.value = false }
}
async function confirmIssue() {
  if (!issue.value || issue.value.status !== 'PENDING_REVIEW' || !canReview.value || acting.value || !previewReady.value || previewError.value) return
  acting.value = true
  try {
    const result = await confirmMaterialIssue(issue.value.id, confirmRequestId.value, etag.value)
    issue.value = result.data; etag.value = result.etag; confirmVisible.value = false
    ElMessage.success('已确认出库，库存按明细扣减。')
  } catch (error) {
    previewError.value = apiMessage(error, '出库处理时间较长，请刷新页面核实单据状态，勿重复点击。')
    ElMessage.error(previewError.value)
  }
  finally { acting.value = false }
}
async function submitReturn() {
  if (!issue.value || returnReason.value.trim().length < 2) { ElMessage.warning('请填写至少 2 个字的退回原因。'); return }
  acting.value = true
  try {
    const result = await returnMaterialIssue(issue.value.id, returnReason.value.trim(), etag.value)
    issue.value = result.data; etag.value = result.etag; returnVisible.value = false; returnReason.value = ''; ElMessage.success('领料单已退回申请人修改。')
  } catch (error) { ElMessage.error(apiMessage(error)) }
  finally { acting.value = false }
}
function back() { void router.push({ name: 'material-issues', query: route.query }) }
function edit() { void router.push({ name: 'material-issue-edit', params: { issueId: issueId.value } }) }
function openMetalProcessing() {
  if (!canOpenMetalProcessing.value) return
  void router.push({ name: 'workshop-outsourcing', query: { tab: 'sources', issue_id: issueId.value } })
}
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="material-issue-page material-issue-detail" data-testid="material-issue-detail">
    <div class="detail-scroll">
      <header class="detail-title">
        <h1>领料单详情</h1>
        <span v-if="issue" class="issue-status" :class="statusClass(issue.status)">{{ issue.status_display }}</span>
      </header>

      <ElAlert v-if="loadError" :title="loadError" type="error" :closable="false"><ElButton @click="load">重新加载</ElButton></ElAlert>
      <template v-if="issue">
        <section v-if="isReturned" class="return-banner">
          <strong>退回原因：{{ returnEvent?.reason || '请修改后重新提交。' }}</strong>
          <p>退回人　{{ returnEvent?.actor.name || '—' }}　·　退回时间　{{ dateText(returnEvent?.created_at) }}</p>
        </section>
        <section v-else-if="issue.status === 'PENDING_REVIEW' && conflictLine" class="error-banner">
          <div>
            <strong>无法出库：{{ conflictLine.material_name }}{{ conflictKind === 'stock' ? '库存不足。' : '超过订单可领数量。' }}</strong>
            <p v-if="conflictKind === 'stock'">本次申请 {{ numberText(conflictLine.requested_quantity) }} {{ conflictLine.unit }}，公共可用库存 {{ numberText(conflictLine.available_stock) }} {{ conflictLine.unit }}。整张领料单尚未扣库存。</p>
            <p v-else>订单剩余可领 {{ numberText(conflictLine.order_remaining) }} {{ conflictLine.unit }}，本次申请 {{ numberText(conflictLine.requested_quantity) }} {{ conflictLine.unit }}。整张领料单尚未扣库存。</p>
          </div>
          <ElButton link type="primary" @click="load">刷新{{ conflictKind === 'stock' ? '库存' : '额度' }}</ElButton>
        </section>

        <section class="mi-surface detail-basic">
          <h2>基本信息</h2>
          <div class="detail-fields">
            <div class="field-column">
              <label><span>领料单号</span><b>{{ issue.issue_number }}</b></label>
              <label><span>生产订单</span><b>{{ issue.production_task?.task_number || '—' }}</b></label>
              <label><span>产品颜色</span><b>{{ issue.product?.color || '—' }}</b></label>
            </div>
            <div class="field-column">
              <label><span>产品</span><b>{{ issue.product?.product_number }} · {{ issue.product?.product_name }}</b></label>
              <label><span>领料车间</span><b>{{ issue.workshop?.name || '—' }}</b></label>
              <label><span>订单数量</span><b>{{ numberText(issue.product?.quantity) }} {{ issue.product?.unit || '' }}</b></label>
            </div>
            <div class="field-column">
              <label><span>领料人</span><b>{{ issue.recipient?.name || '—' }}</b></label>
              <label><span>{{ isIssued ? '实际领料时间' : '领料时间' }}</span><b>{{ dateText(isIssued ? issue.issued_at : issue.issue_at) }}</b></label>
              <label><span>备注</span><b>{{ issue.remark || '—' }}</b></label>
            </div>
            <div class="product-preview">
              <img :src="productImageUrl" :class="{ 'is-placeholder': !issue.product?.image_file_id }" :alt="`${issue.product?.product_name || '产品'}图片`" @error="useProductImageFallback" />
              <div><strong>{{ issue.product?.product_number || '—' }}<br />{{ issue.product?.product_name || '—' }}</strong><p>{{ issue.product?.color || '—' }}</p></div>
            </div>
          </div>
        </section>

        <section class="mi-surface detail-table">
          <h2>原材料领料明细</h2>
          <ElTable :data="rawLines" border row-key="id" empty-text="本次没有原材料领料明细">
            <ElTableColumn type="index" label="序号" width="68" align="center" />
            <ElTableColumn label="物料分类" width="120"><template #default="{ row }">{{ sectionText(row.section_code) }}</template></ElTableColumn>
            <ElTableColumn label="物料 / 部位" min-width="160"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.conversion_snapshot?.part_name || row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
            <ElTableColumn label="材质" min-width="110"><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
            <ElTableColumn label="规格" min-width="180" class-name="specification-cell"><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
            <ElTableColumn v-if="rawLines.some(r => r.conversion_snapshot?.kind === 'PIPE')" label="管材扣库换算" min-width="230"><template #default="{ row }"><span v-if="row.conversion_snapshot?.kind === 'PIPE'">{{ numberText(row.requested_quantity) }} 支 → {{ numberText(row.bar_count) }} 根 / {{ numberText(row.meters) }} 米</span><span v-else>—</span></template></ElTableColumn>
            <ElTableColumn label="颜色" min-width="90" align="center"><template #default="{ row }">{{ colorValue(row) }}</template></ElTableColumn>
            <ElTableColumn prop="unit" label="单位" width="76" align="center" />
            <ElTableColumn label="本订单需求" min-width="110" align="center"><template #default="{ row }">{{ numberText(row.required_quantity) }}</template></ElTableColumn>
            <template v-if="isIssued">
              <ElTableColumn label="本次实领" min-width="105" align="center"><template #default="{ row }">{{ numberText(row.issued_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="累计厂内已领" min-width="120" align="center"><template #default="{ row }">{{ numberText(row.internal_issued_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="累计委外已发" min-width="120" align="center"><template #default="{ row }">{{ numberText(row.outsourcing_issued_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="剩余可领" min-width="105" align="center"><template #default="{ row }">{{ numberText(row.order_remaining) }}</template></ElTableColumn>
            </template>
            <template v-else>
              <ElTableColumn label="厂内已领" min-width="100" align="center"><template #default="{ row }">{{ numberText(row.internal_issued_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="委外已发" min-width="100" align="center"><template #default="{ row }">{{ numberText(row.outsourcing_issued_quantity) }}</template></ElTableColumn>
              <ElTableColumn v-if="isPublicIssue" label="本订单待审核" min-width="120" align="center"><template #default="{ row }">{{ numberText(row.pending_issue_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="订单可领" min-width="105" align="center"><template #default="{ row }"><span :class="{ conflict: overAllowance(row) }">{{ numberText(row.order_remaining) }}</span></template></ElTableColumn>
              <ElTableColumn label="公共可用库存" min-width="120" align="center"><template #default="{ row }"><span :class="{ conflict: overStock(row) }">{{ numberText(row.available_stock) }}</span></template></ElTableColumn>
              <ElTableColumn label="本次领取" min-width="105" align="center"><template #default="{ row }"><span :class="{ conflict: overStock(row) || overAllowance(row) }">{{ numberText(row.requested_quantity) }}</span></template></ElTableColumn>
            </template>
          </ElTable>
        </section>

        <section class="mi-surface detail-table">
          <h2>外发回库半成品领料</h2>
          <ElTable :data="semiLines" border row-key="id" empty-text="本次没有半成品领料明细">
            <ElTableColumn label="半成品 / 部位" min-width="170"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
            <ElTableColumn label="材质" min-width="110"><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
            <ElTableColumn label="规格" min-width="180" class-name="specification-cell"><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
            <ElTableColumn label="颜色" min-width="100"><template #default="{ row }">{{ colorValue(row, true) }}</template></ElTableColumn>
            <ElTableColumn prop="unit" label="单位" width="76" align="center" />
            <template v-if="hasPublicSemi">
              <ElTableColumn label="本订单需求" min-width="110" align="center"><template #default="{ row }">{{ isPublicLine(row) ? numberText(row.required_quantity) : '—' }}</template></ElTableColumn>
              <ElTableColumn label="本订单已领" min-width="110" align="center"><template #default="{ row }">{{ isPublicLine(row) ? numberText(row.internal_issued_quantity) : '—' }}</template></ElTableColumn>
              <ElTableColumn label="本订单待审核" min-width="120" align="center"><template #default="{ row }">{{ isPublicLine(row) ? numberText(row.pending_issue_quantity) : '—' }}</template></ElTableColumn>
              <ElTableColumn label="本订单剩余" min-width="110" align="center"><template #default="{ row }">{{ isPublicLine(row) ? numberText(row.order_remaining) : '—' }}</template></ElTableColumn>
            </template>
            <ElTableColumn :label="isIssued ? '本单出库前库存' : '公共可用库存'" min-width="140" align="center"><template #default="{ row }">{{ numberText(isIssued ? (isPublicLine(row) ? row.stock_before : row.required_quantity) : row.available_stock) }}</template></ElTableColumn>
            <ElTableColumn label="申请数量" min-width="110" align="center"><template #default="{ row }">{{ numberText(row.requested_quantity) }}</template></ElTableColumn>
            <ElTableColumn :label="isIssued ? '实际扣库' : '预计扣库'" min-width="110" align="center"><template #default="{ row }">{{ numberText(isIssued ? row.issued_quantity : row.requested_quantity) }}</template></ElTableColumn>
            <ElTableColumn v-if="isIssued" label="出库后结余" min-width="120" align="center"><template #default="{ row }">{{ numberText(isPublicLine(row) ? row.stock_after : row.order_remaining) }}</template></ElTableColumn>
          </ElTable>
          <p class="snapshot-note">管材半成品按正整数支领取，裁片按正整数套领取；只扣半成品库存，不扣原材料根数和米数。<template v-if="isIssued">表内库存及扣库数量为本单出库时记录。</template></p>
        </section>

        <section v-if="isIssued && publicAllocations.length" class="mi-surface detail-table" data-testid="public-stock-deductions">
          <h2>实际扣库明细</h2>
          <ElTable :data="publicAllocations" border>
            <ElTableColumn label="分区 / 物料部位" min-width="210"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.line_type === 'SEMI' ? '半成品' : '原材料' }} · {{ row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
            <ElTableColumn prop="material" label="材质" min-width="110" />
            <ElTableColumn prop="specification" label="规格" min-width="180" class-name="specification-cell" />
            <ElTableColumn prop="color" label="颜色" min-width="100" />
            <ElTableColumn prop="warehouse_zone" label="扣库库区" min-width="200" />
            <ElTableColumn label="实际领用" min-width="130"><template #default="{ row }">{{ numberText(row.requested_quantity) }} {{ row.request_unit }}</template></ElTableColumn>
            <ElTableColumn label="实际扣库" min-width="200"><template #default="{ row }">{{ numberText(row.stock_quantity) }} {{ row.stock_unit }}<template v-if="row.meter_quantity != null"> / {{ numberText(row.meter_quantity) }} 米</template></template></ElTableColumn>
            <ElTableColumn label="库区扣前 / 扣后" min-width="220"><template #default="{ row }">{{ numberText(row.before_quantity) }} / {{ numberText(row.after_quantity) }} {{ row.stock_unit }}</template></ElTableColumn>
          </ElTable>
        </section>

        <section v-if="isIssued || isReturned" class="mi-surface audit-panel">
          <h2>审核记录</h2>
          <div class="audit-timeline" :class="{ 'is-returned': isReturned, 'is-issued': isIssued }">
            <article v-for="(item, index) in issue.audit_events" :key="item.id" :class="{ current: index === issue.audit_events.length - 1 }">
              <i></i><strong>{{ item.action_display }}</strong><span>{{ item.actor.name }}</span><time>{{ dateText(item.created_at) }}</time>
            </article>
          </div>
        </section>
        <p v-else class="submission-meta">制单人　{{ issue.created_by.name }}　·　提交时间　{{ dateText(issue.submitted_at) }}</p>
      </template>
    </div>

    <footer v-if="issue" class="detail-footer">
      <span><b>共 {{ issue.line_count }} 项</b><i></i>{{ isIssued ? (isPublicIssue ? '已从公共库存扣减；半成品领用不重复扣原料。' : '已扣减库存；半成品领用不重复扣原料。') : isReturned ? '已退回，未扣库存。' : '仓库审核确认后扣库存；本期不允许超领。' }}</span>
      <div>
        <ElButton @click="back">返回列表</ElButton>
        <ElButton v-if="canOpenMetalProcessing" data-testid="issue-metal-processing-entry" @click="openMetalProcessing">金工完成登记</ElButton>
        <ElButton v-if="isReturned && canEdit" type="primary" @click="edit">修改领料单</ElButton>
        <ElButton v-else-if="issue.status === 'DRAFT' && canEdit" type="primary" @click="edit">修改领料单</ElButton>
        <template v-else-if="issue.status === 'PENDING_REVIEW' && canReview">
          <ElButton :disabled="acting" @click="returnVisible = true">退回修改</ElButton>
          <ElButton type="primary" :loading="acting" :disabled="Boolean(conflictLine)" @click="openConfirmation">审核通过并出库</ElButton>
        </template>
      </div>
    </footer>

    <AppWindowDialog v-model="confirmVisible" title="仓库确认出库" :width="1200" :height="650" :show-close="!acting" :close-on-click-modal="!acting" :close-on-press-escape="!acting">
      <ElAlert v-if="previewError" :title="previewError" type="error" :closable="false" />
      <p>请核对每项物料和数量。确认时将重新检查合格库存、额度与来源，并由系统自动分配库存，任一明细失败均不会部分扣账。</p>
      <ElTable :data="confirmationRows" border max-height="420" data-testid="issue-live-preview">
        <ElTableColumn label="分区 / 物料部位" min-width="220"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.line_type === 'SEMI' ? '半成品' : '原材料' }} · {{ row.conversion_snapshot?.part_name || row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
        <ElTableColumn label="材质" min-width="110"><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
        <ElTableColumn label="规格" min-width="140"><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
        <ElTableColumn label="颜色" min-width="100"><template #default="{ row }">{{ row.line_type === 'SEMI' ? colorValue(row, true) : colorValue(row) }}</template></ElTableColumn>
        <ElTableColumn label="申请数量" width="150"><template #default="{ row }">{{ numberText(row.requested_quantity) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn label="公共可用量" min-width="120"><template #default="{ row }">{{ numberText(row.available_stock) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn label="本订单剩余" min-width="120"><template #default="{ row }">{{ numberText(row.order_remaining) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn v-if="isPublicIssue" label="本次可领" min-width="120"><template #default="{ row }">{{ numberText(row.max_issue_quantity) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn label="预计扣库" min-width="320"><template #default="{ row }"><span v-if="row.conversion_snapshot?.kind === 'PIPE'">{{ numberText(row.requested_quantity) }} 支 → {{ numberText(row.bar_count) }} 根 / {{ numberText(row.meters) }} 米 · 系统自动分配库存</span><span v-else>{{ numberText(row.requested_quantity) }} {{ row.unit }} · {{ row.warehouse_zone || '合格公共库存' }}</span></template></ElTableColumn>
      </ElTable>
      <template #footer><ElButton :disabled="acting" @click="confirmVisible = false">取消</ElButton><ElButton :disabled="acting" @click="openConfirmation">重新核对</ElButton><ElButton type="primary" :loading="acting" :disabled="acting || !previewReady || Boolean(previewError)" @click="confirmIssue">确认出库</ElButton></template>
    </AppWindowDialog>
    <AppWindowDialog v-model="returnVisible" title="退回修改" :width="560" :height="380" :close-on-click-modal="!acting" :close-on-press-escape="!acting" :show-close="!acting" destroy-on-close>
      <dl class="return-summary"><div><dt>领料单号</dt><dd>{{ issue?.issue_number }}</dd></div><div><dt>生产订单</dt><dd>{{ issue?.production_task?.task_number || '—' }}</dd></div></dl>
      <ElForm label-position="top"><ElFormItem label="退回原因" required><ElInput v-model="returnReason" type="textarea" :rows="5" maxlength="1000" show-word-limit autofocus placeholder="说明需要申请人核对或修改的内容" /></ElFormItem></ElForm>
      <p class="return-tip">退回后由申请人修改并重新提交，本次不会扣减库存。</p>
      <template #footer><ElButton :disabled="acting" @click="returnVisible = false">取消</ElButton><ElButton type="primary" :loading="acting" @click="submitReturn">确认退回</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/materialIssue';
.material-issue-detail { display: flex; flex-direction: column; overflow: hidden; }
.detail-table :deep(td.specification-cell .cell) { padding-top: 8px; padding-bottom: 8px; white-space: normal; overflow-wrap: anywhere; overflow: visible; text-overflow: clip; }
.detail-scroll { min-height: 0; flex: 1; overflow: auto; padding: 0 0 16px; }
.detail-title { display: flex; height: 58px; align-items: flex-start; gap: 16px; }
.detail-title h1 { margin: 0; color: #1f1d18; font: 500 34px/44px 'Noto Serif SC', 'Songti SC', serif; }
.issue-status { display: inline-flex; box-sizing: border-box; min-width: 56px; height: 24px; align-items: center; justify-content: center; margin-top: 10px; padding: 0 8px; border: 0; border-radius: 999px; color: #faf9f5; font-family: 'Noto Sans SC', sans-serif; font-size: 12px; font-weight: 500; line-height: 18px; white-space: nowrap; }
.issue-status.is-pending { background: #3898ec; }.issue-status.is-issued { background: #4f7d4b; }.issue-status.is-returned { background: #b53333; }.issue-status.is-draft { background: #5e5d59; }
.return-banner, .error-banner { box-sizing: border-box; margin-bottom: 14px; border: 1px solid #efb9b5; border-radius: 4px; background: #fff0ed; color: #be221c; }
.return-banner { min-height: 72px; padding: 9px 15px; }.return-banner strong { font-size: 16px; }.return-banner p { margin: 6px 0 0; color: #4f4a43; }
.error-banner { display: flex; min-height: 84px; align-items: center; gap: 14px; justify-content: space-between; padding: 12px 20px; }.error-banner strong { font-size: 18px; }.error-banner p { margin: 5px 0 0; color: #4f4a43; }
.detail-basic { margin-bottom: 14px; padding: 10px 14px 12px; }.detail-basic h2, .detail-table h2, .audit-panel h2 { margin: 0 0 8px; font-size: 18px; }
.detail-fields { display: grid; grid-template-columns: minmax(250px, 1fr) minmax(260px, 1fr) minmax(280px, 1fr) 230px; gap: 30px; }
.field-column { display: flex; flex-direction: column; gap: 7px; }.field-column label { display: grid; grid-template-columns: 92px minmax(0, 1fr); align-items: center; font-size: 14px; }.field-column b { display: flex; min-width: 0; height: 36px; align-items: center; overflow: hidden; padding: 0 12px; border: 1px solid #ddd8cf; border-radius: 3px; background: #efebe4; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.product-preview { display: flex; align-items: center; gap: 10px; }.product-preview img { width: 104px; height: 104px; border: 1px solid #ddd8cf; border-radius: 3px; background: #fff; object-fit: contain; }.product-preview img.is-placeholder { opacity: .65; }.product-preview strong { font-size: 14px; line-height: 24px; }.product-preview p { margin: 6px 0 0; color: #6d675f; }
.detail-table { margin-bottom: 14px; padding: 9px 14px 12px; overflow: hidden; }.detail-table :deep(.el-table) { --el-table-border-color: #ddd6c9; --el-table-header-bg-color: #f0eadf; --el-table-row-hover-bg-color: #fff6ea; border-radius: 5px; color: #1f1d18; }.detail-table :deep(.el-table th.el-table__cell) { height: 44px !important; padding: 0 !important; background: #f0eadf; color: #6f6a61; font-weight: 500; }.detail-table :deep(.el-table td.el-table__cell) { height: 40px !important; padding: 0 !important; font-weight: 400; }.detail-table :deep(.el-table .cell) { padding-right: 16px !important; padding-left: 16px !important; white-space: nowrap; }.detail-table :deep(th .cell) { font-size: 11px; line-height: 16px; }.detail-table :deep(td .cell) { font-size: 12px; line-height: 18px; }.conflict { color: #b53333; font-weight: 600; }.craft-tag { border: 0; border-radius: 999px; background: #c96442; color: #faf9f5; }.snapshot-note { margin: 7px 0 0; color: #7a746b; font-size: 13px; }
.audit-panel { margin-bottom: 4px; padding: 9px 14px 12px; }.audit-timeline { display: flex; justify-content: space-between; margin: 18px 12% 0; position: relative; }.audit-timeline::before { position: absolute; top: 0; right: 0; left: 0; height: 2px; background: #c7bdac; content: ''; }.audit-timeline article { display: flex; width: 1px; align-items: center; flex-direction: column; position: relative; text-align: center; }.audit-timeline article i { width: 17px; height: 17px; margin-top: -7px; margin-bottom: 7px; border-radius: 50%; background: #c5bbaa; z-index: 1; }.audit-timeline article strong, .audit-timeline article span, .audit-timeline article time { line-height: 24px; white-space: nowrap; }.audit-timeline article strong { font-size: 14px; }.audit-timeline article span, .audit-timeline article time { color: #6d675f; font-size: 13px; }.audit-timeline.is-issued article.current i { background: #638d50; }.audit-timeline.is-returned article.current i { background: #c72b20; }.audit-timeline.is-returned article.current strong { color: #c72b20; }
.submission-meta { margin: 18px 0 0; padding-top: 12px; border-top: 1px solid #e2ded5; color: #5f5a52; font-size: 14px; }
.detail-footer { display: flex; box-sizing: border-box; min-height: 58px; flex: none; align-items: center; justify-content: space-between; border-top: 1px solid #ddd6c9; background: var(--erp-page-background); font-size: 14px; }.detail-footer > span { display: flex; align-items: center; }.detail-footer b { font-size: 16px; }.detail-footer i { width: 1px; height: 22px; margin: 0 18px; background: #aaa194; }.detail-footer > div { display: flex; gap: 12px; }.detail-footer :deep(.el-button) { min-width: 110px; height: 32px; min-height: 32px; margin: 0; border-radius: 5px; }.detail-footer :deep(.el-button--primary) { min-width: 140px; }
.detail-footer :deep(.el-button--primary) { border-color: #c84e28; background: #c84e28; color: #faf9f5; }.detail-footer :deep(.el-button--primary:hover) { border-color: #b74120; background: #b74120; }
.return-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 14px; }.return-summary div { display: grid; grid-template-columns: 80px 1fr; }.return-summary dt { color: #7a746b; }.return-summary dd { margin: 0; }.return-tip { margin: -8px 0 0; color: #7a746b; font-size: 12px; }
@media (max-width: 1450px) { .detail-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }.product-preview { grid-column: 1 / -1; }.product-preview img { width: 72px; height: 72px; } }
</style>
