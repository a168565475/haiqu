<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { Button as VanButton, Cell as VanCell, DatePicker as VanDatePicker, Field as VanField, Icon as VanIcon, Loading as VanLoading, Popup as VanPopup, showDialog } from 'vant'
import type { PickerConfirmEventParams, PickerOption } from 'vant'
import 'vant/es/button/style'
import 'vant/es/cell/style'
import 'vant/es/date-picker/style'
import 'vant/es/field/style'
import 'vant/es/icon/style'
import 'vant/es/loading/style'
import 'vant/es/popup/style'
import WorkPage from '@/components/WorkPage.vue'
import { useAuthStore } from '@/stores/auth'
import { createSemiReceipt, fetchSemiReceiptPreview, findSemiReceipt } from '@/api/semiReceipts'
import type { PendingSemiReceipt, SemiReceiptLine, SemiReceiptPreview, SemiReceiptResult } from '@/types/semiReceipts'
import { errorMessage } from '@/utils/errors'
import { createRequestId } from '@/utils/requestId'
import { quantityText, shanghaiToday, validProductionDate } from '@/utils/reporting'
import { formatSemiQuantity, parsePendingSemiReceipt, semiAttributeLabels, semiLineError, semiLineName, semiPageBlockers, semiPreviewWhole, semiReceiptFailure, semiReceiptLines, semiReceiptScope, semiWhole } from '@/utils/semiReceipts'
import { createSemiReceiptPending } from '@/utils/semiReceiptPending'

const route = useRoute(), router = useRouter(), auth = useAuthStore()
const owner = { userId: auth.user?.id ?? null, generation: auth.generation }
let alive = true, sequence = 0, controller: AbortController | null = null
let store: ReturnType<typeof createSemiReceiptPending> | null = null, pendingRaw: string | null = null
const scope = computed(() => semiReceiptScope(route.query))
const canView = computed(() => auth.hasPermission('inventory.view_internalsemifinishedreceipt'))
const canCreate = computed(() => canView.value && auth.hasPermission('inventory.add_internalsemifinishedreceipt'))
const preview = ref<SemiReceiptPreview | null>(null), pending = ref<PendingSemiReceipt | null>(null), result = ref<SemiReceiptResult | null>(null)
const quantities = ref<Record<string, string>>({}), receiptDate = ref(''), remark = ref(''), warehouseId = ref(''), zoneId = ref('')
const loading = ref(false), saving = ref(false), storageBlocked = ref(false), needsRefresh = ref(false)
const loadError = ref(''), actionError = ref('')
const showDate = ref(false), pickerDate = ref<string[]>([]), showWarehouse = ref(false), showZone = ref(false)
const current = () => alive && auth.user?.id === owner.userId && auth.generation === owner.generation
const blockers = computed(() => preview.value ? semiPageBlockers(preview.value) : [])
const locked = computed(() => loading.value || saving.value || Boolean(pending.value) || storageBlocked.value || needsRefresh.value || !current() || !canCreate.value || Boolean(blockers.value.length))
const warehouseKey = (zone: SemiReceiptPreview['zones'][number]) => zone.warehouse_id || zone.warehouse
const warehouses = computed(() => Array.from(new Map((preview.value?.zones ?? []).map(zone => [warehouseKey(zone), { id: warehouseKey(zone), name: zone.warehouse }])).values()))
const zones = computed(() => preview.value?.zones.filter(zone => warehouseKey(zone) === warehouseId.value) ?? [])
const warehouseName = computed(() => warehouses.value.find(item => item.id === warehouseId.value)?.name || '请选择半成品仓')
const zoneName = computed(() => preview.value?.zones.find(item => item.id === zoneId.value)?.name || '请选择库区')
const selectedLines = computed(() => (preview.value?.lines ?? []).filter(line => (semiWhole(quantities.value[line.bom_line_id] || '') ?? 0n) > 0n))
const total = computed(() => String(selectedLines.value.reduce((sum, line) => sum + (semiWhole(quantities.value[line.bom_line_id]) ?? 0n), 0n)))
const available = (line: SemiReceiptLine) => (semiPreviewWhole(line.can_receive) ?? 0n) > 0n && (scope.value?.plan_category !== 'METAL' || line.metal_processing?.basis_ready)
const hasAvailable = computed(() => preview.value?.lines.some(available) ?? false)
const canSubmit = computed(() => current() && !storageBlocked.value && !saving.value && !loading.value && !result.value
  && (pending.value ? canView.value && !pending.value.conflict : canCreate.value && preview.value && !needsRefresh.value && !blockers.value.length && hasAvailable.value))
const minDate = computed(() => new Date(Math.min(Number(shanghaiToday().slice(0, 4)) - 10, Number(receiptDate.value.slice(0, 4)) || 9999), 0, 1))
const maxDate = computed(() => new Date(Math.max(Number(shanghaiToday().slice(0, 4)) + 10, Number(receiptDate.value.slice(0, 4)) || 0), 11, 31))
const conflictMessage = '原请求编号存在内容冲突，已保留原请求，请联系管理员在 ERP 核对入库记录，勿重新申请。'
watch(locked, value => { if (value) { showDate.value = false; showWarehouse.value = false; showZone.value = false } })

function openDate() { if (!locked.value) { pickerDate.value = receiptDate.value.split('-'); showDate.value = true } }
function confirmDate({ selectedValues }: PickerConfirmEventParams) {
  if (locked.value) return
  const value = selectedValues.join('-')
  if (validProductionDate(value)) { receiptDate.value = value; showDate.value = false }
}
function formatDate(type: string, option: PickerOption) { return { ...option, text: `${option.text}${({ year: '年', month: '月', day: '日' } as Record<string, string>)[type] || ''}` } }
function selectWarehouse(id: string) {
  if (locked.value || !warehouses.value.some(item => item.id === id)) return
  if (warehouseId.value !== id) { warehouseId.value = id; zoneId.value = '' }
  showWarehouse.value = false
}
function selectZone(id: string) {
  if (locked.value || !zones.value.some(item => item.id === id)) return
  zoneId.value = id; showZone.value = false
}
async function load() {
  if (!scope.value || !current() || storageBlocked.value || saving.value || !canView.value) return
  controller?.abort(); controller = new AbortController()
  const request = ++sequence, source = scope.value
  loading.value = true; loadError.value = ''; preview.value = null
  try {
    const data = await fetchSemiReceiptPreview(source.schedule_product_id, source.plan_category, controller.signal)
    if (!current() || request !== sequence) return
    preview.value = data; needsRefresh.value = false; receiptDate.value ||= data.receipt_date
    if (!pending.value) quantities.value = Object.fromEntries(data.lines.map(line => [line.bom_line_id, quantities.value[line.bom_line_id] || '']))
    const restoredZone = data.zones.find(zone => zone.id === zoneId.value)
    if (restoredZone) warehouseId.value = warehouseKey(restoredZone)
    else if (!pending.value) {
      zoneId.value = ''
      if (!warehouses.value.some(item => item.id === warehouseId.value)) warehouseId.value = warehouses.value.length === 1 ? warehouses.value[0]!.id : ''
    }
    if (!warehouseId.value && warehouses.value.length === 1) warehouseId.value = warehouses.value[0]!.id
  }
  catch (error) { if (current() && request === sequence) loadError.value = errorMessage(error, '半成品入库信息加载失败，请重试。') }
  finally { if (current() && request === sequence) loading.value = false }
}
function initialize() {
  controller?.abort(); sequence++; store = null
  loading.value = false; saving.value = false; showDate.value = false; showWarehouse.value = false; showZone.value = false
  pending.value = null; pendingRaw = null; result.value = null; storageBlocked.value = false; needsRefresh.value = false
  loadError.value = ''; actionError.value = ''; preview.value = null; quantities.value = {}; receiptDate.value = ''; remark.value = ''; warehouseId.value = ''; zoneId.value = ''
  if (!scope.value) { loadError.value = '入库来源参数无效，请从金工或车缝计划重新进入半成品入库。'; return }
  store = createSemiReceiptPending(scope.value.schedule_product_id, scope.value.plan_category, owner, () => ({ userId: alive ? auth.user?.id ?? null : null, generation: auth.generation }))
  try {
    pendingRaw = store.read()
    if (pendingRaw !== null) {
      pending.value = parsePendingSemiReceipt(pendingRaw, scope.value.schedule_product_id, scope.value.plan_category)
      const payload = pending.value.payload
      quantities.value = Object.fromEntries(payload.lines.map(line => [line.bom_line_id, String(line.quantity)]))
      receiptDate.value = payload.receipt_date; remark.value = payload.remark; zoneId.value = payload.zone_id
      if (pending.value.conflict) actionError.value = conflictMessage
    }
  }
  catch (error) { storageBlocked.value = true; loadError.value = errorMessage(error, '无法读取原提交记录，已保留并暂停提交。'); return }
  if (!canView.value || !pending.value && !canCreate.value) { loadError.value = '当前账号没有半成品入库查看和申请权限。'; return }
  void load()
}
function finish(saved: SemiReceiptResult, activeStore: NonNullable<typeof store>, raw: string) {
  result.value = saved
  try { activeStore.consume(raw); pending.value = null; pendingRaw = null }
  catch { storageBlocked.value = true; actionError.value = '申请已提交，但原请求记录未能清理；请保留单号并联系管理员核对，勿重复申请。' }
}
function verifyPending(activeStore: NonNullable<typeof store>, raw: string) {
  try { activeStore.assertUnchanged(raw) }
  catch (error) { storageBlocked.value = true; throw error }
}
async function postPending(activeStore: NonNullable<typeof store>, request: number, recovering: boolean) {
  const original = pending.value!, raw = pendingRaw!
  verifyPending(activeStore, raw)
  try {
    const saved = await createSemiReceipt(original.payload, original.etag)
    if (!current() || request !== sequence) return
    finish(saved, activeStore, raw)
  }
  catch (error) {
    if (!current() || request !== sequence) return
    const kind = semiReceiptFailure(error, recovering)
    if (kind === 'conflict') {
      const conflict = { ...original, conflict: true }, nextRaw = JSON.stringify(conflict)
      try { activeStore.replace(raw, nextRaw); pending.value = conflict; pendingRaw = nextRaw; actionError.value = conflictMessage }
      catch { storageBlocked.value = true; actionError.value = '冲突记录无法保存，已保留原记录并暂停提交，请联系管理员核对。' }
    }
    else if (kind === 'deleted' || kind === 'rejected') {
      try { activeStore.consume(raw); pending.value = null; pendingRaw = null; needsRefresh.value = true }
      catch { storageBlocked.value = true; actionError.value = '待核对记录无法更新，已保留并暂停提交，请联系管理员核对。'; return }
      actionError.value = `${errorMessage(error)} 请刷新入库额度后重新核对。`
    }
    else actionError.value = `${errorMessage(error)} 本次提交结果尚未确认，请使用原编号“核对本次提交”，勿另建单据。`
  }
}
async function recoverPending(activeStore: NonNullable<typeof store>, request: number) {
  const original = pending.value!, raw = pendingRaw!
  verifyPending(activeStore, raw)
  try {
    const saved = await findSemiReceipt(original.payload.request_id)
    if (current() && request === sequence) finish(saved, activeStore, raw)
  }
  catch (error) {
    if (!current() || request !== sequence) return
    if ((error as { response?: { status?: number } })?.response?.status === 404) {
      if (!canCreate.value) { actionError.value = '尚未查到原单，当前账号没有申请权限；原请求已保留，请联系管理员核对。'; return }
      await postPending(activeStore, request, true)
    }
    else actionError.value = `${errorMessage(error)} 原提交已保留，请稍后继续核对。`
  }
}
async function submit() {
  if (!canSubmit.value || !store || !scope.value) return
  saving.value = true; actionError.value = ''
  const request = sequence, activeStore = store
  try {
    await auth.refresh(true)
    if (!current() || request !== sequence) return
    if (!canView.value || !pending.value && !canCreate.value) { actionError.value = '当前账号没有半成品入库查看和申请权限。'; return }
    if (pending.value) {
      if (pending.value.conflict) { actionError.value = conflictMessage; return }
      await recoverPending(activeStore, request)
      return
    }
    if (!preview.value || needsRefresh.value) return
    if (!validProductionDate(receiptDate.value)) { actionError.value = '请选择有效收货日期。'; return }
    if (!zones.value.some(zone => zone.id === zoneId.value)) { actionError.value = '请选择当前半成品仓的有效库区。'; return }
    const lines = semiReceiptLines(preview.value, quantities.value)
    const original: PendingSemiReceipt = { etag: preview.value.etag, payload: { request_id: createRequestId(), ...scope.value, zone_id: zoneId.value, receipt_date: receiptDate.value, remark: remark.value.trim(), lines } }
    try {
      const raw = JSON.stringify(original)
      activeStore.write(raw); pending.value = original; pendingRaw = raw
    }
    catch (error) { storageBlocked.value = true; actionError.value = errorMessage(error, '无法保存提交编号，已暂停提交，请重新打开本页核对。'); return }
    await postPending(activeStore, request, false)
  }
  catch (error) {
    if (current() && request === sequence) {
      actionError.value = errorMessage(error, '提交核验失败，请重试。')
    }
  }
  finally { if (current() && request === sequence) saving.value = false }
}
async function allowLeave(to: { path: string }) {
  if (['/login', '/auth/waiting-role'].includes(to.path) || result.value || !saving.value && !pending.value) return true
  await showDialog({ title: '请先核对本次提交', message: '入库提交结果尚未确认，请留在当前页面核对原请求，避免重复申请。' })
  return false
}
function beforeUnload(event: BeforeUnloadEvent) { if (!result.value && (saving.value || pending.value)) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(allowLeave); onBeforeRouteUpdate(allowLeave)
window.addEventListener('beforeunload', beforeUnload)
watch(() => [route.query.schedule_product_id, route.query.plan_category], initialize, { immediate: true })
onBeforeUnmount(() => { alive = false; sequence++; controller?.abort(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <WorkPage class="semi-work-page" title="半成品入库" :subtitle="preview?.production_order || (scope?.plan_category === 'METAL' ? '金工' : '车缝')">
    <div class="page-stack semi-page">
      <section v-if="result" class="section-card semi-success" role="status">
        <VanIcon name="passed" size="40" /><h2>{{ result.status === 'CONFIRMED' ? '仓库已确认入库' : '申请已提交，待仓库确认' }}</h2><strong>{{ result.receipt_number }}</strong>
        <p>{{ result.status === 'CONFIRMED' ? '原单已由仓库确认，请勿重复申请。' : '仓库在 ERP 确认后增加半成品库存。' }}</p>
        <p v-if="actionError" class="semi-error">{{ actionError }}</p><VanButton block type="primary" @click="router.push('/')">返回生产列表</VanButton>
      </section>
      <template v-else>
        <div v-if="loading" class="semi-loading" role="status"><VanLoading>正在读取入库额度…</VanLoading></div>
        <section v-if="loadError" class="error-panel" role="alert"><p>{{ loadError }}</p><VanButton v-if="scope && !storageBlocked && canView" block :disabled="saving || loading" @click="load">重新加载</VanButton></section>
        <section v-if="pending" class="section-card semi-pending" role="status"><strong>原提交待核对，填写内容已锁定</strong><p>{{ pending.payload.receipt_date }} · {{ pending.payload.lines.length }} 项入库明细</p><p>刷新或网络中断后继续使用原编号核对。<br />{{ pending.payload.request_id }}</p></section>
        <template v-if="preview">
          <details class="section-card semi-product">
            <summary><span><strong>{{ preview.product }}</strong><small>{{ preview.production_order }}</small></span><span class="semi-toggle">产品详情<VanIcon name="arrow-down" /></span></summary>
            <div class="semi-product-details"><p v-if="preview.product_number">产品编号：{{ preview.product_number }} · 货号：{{ preview.item_number || '未填写' }}</p><p v-if="preview.order_number || preview.schedule_number">订单：{{ preview.order_number || '未填写' }} · 计划：{{ preview.schedule_number || '未填写' }}</p><p v-if="preview.product_color">订单颜色：{{ preview.product_color }}</p><p>订单数量：{{ quantityText(preview.order_quantity) }} {{ preview.product_unit || '' }} · 入库人：{{ preview.actor }}</p></div>
          </details>
          <section class="section-card semi-form">
            <button type="button" class="semi-choice semi-date" :disabled="locked" aria-label="选择收货日期" aria-haspopup="dialog" @click="openDate"><span>收货日期</span><span>{{ receiptDate }}<VanIcon name="calendar-o" /></span></button>
            <button type="button" class="semi-choice semi-warehouse" :disabled="locked || !warehouses.length" aria-label="选择半成品仓" aria-haspopup="dialog" @click="showWarehouse = true"><span>半成品仓</span><span>{{ warehouseName }}<VanIcon name="arrow" /></span></button>
            <button type="button" class="semi-choice semi-zone" :disabled="locked || !warehouseId" aria-label="选择库区" aria-haspopup="dialog" @click="showZone = true"><span>库区</span><span>{{ zoneName }}<VanIcon name="arrow" /></span></button>
            <p v-if="preview.processing_state" class="semi-stage">加工状态：{{ preview.processing_state }} · 仓库确认后增加该阶段半成品库存</p>
            <p v-if="!preview.zones.length" class="semi-error">没有可用半成品库区，请联系仓库维护。</p>
          </section>
          <section v-if="blockers.length" class="error-panel" role="alert"><p v-for="message in blockers" :key="message">{{ message }}</p></section>
          <section v-if="!hasAvailable && !blockers.length" class="section-card muted">当前暂无可入库数量，请查看各明细的数量依据。</section>
          <article v-for="line in preview.lines" :key="line.bom_line_id" class="section-card semi-material" :data-line-id="line.bom_line_id">
            <div class="semi-material-heading"><strong>{{ semiLineName(line) }}</strong><span>{{ line.stage }}</span></div>
            <p class="semi-material-spec">{{ [line.specification || line.attributes.specification, line.attributes.material, line.attributes.color].filter(Boolean).join(' · ') || '规格未填写' }}</p>
            <div class="semi-quantities"><div><span>订单需求</span><b>{{ quantityText(line.required) }}</b></div><div><span>{{ preview.plan_category === 'SEWING' ? '累计入库/待确认' : '累计已提交' }}</span><b>{{ quantityText(line.received) }}</b></div><div class="semi-available"><span>本次可入</span><b>{{ line.metal_processing && !line.metal_processing.basis_ready ? '—' : quantityText(line.can_receive) }} <small>{{ line.attributes.unit_name }}</small></b></div></div>
            <VanField v-model="quantities[line.bom_line_id]" class="semi-quantity" label="本次入库" type="text" inputmode="numeric" :placeholder="available(line) ? '请输入数量' : '暂无可入'" :formatter="value => formatSemiQuantity(value, quantities[line.bom_line_id] || '')" :disabled="locked || !available(line)" :aria-label="`${semiLineName(line)}本次入库数量`" :error-message="semiLineError(preview, line, quantities[line.bom_line_id] || '')"><template #button><span>{{ line.attributes.unit_name }}</span></template></VanField>
            <p v-if="line.metal_processing?.blockers.length" class="semi-error">{{ line.metal_processing.blockers.join('；') }}</p>
            <p v-if="line.metal_processing?.future_blockers.length" class="semi-error">{{ line.metal_processing.future_blockers.join('；') }}</p>
            <p v-if="line.processing_not_enabled_reason" class="semi-error">{{ line.processing_not_enabled_reason }}</p>
            <details class="semi-details"><summary>材料详情与数量依据<VanIcon name="arrow-down" /></summary>
              <p>单位用量：{{ line.usage }} · 加工状态：{{ line.stage }}</p>
              <p v-if="line.attributes.category">类别：{{ line.attributes.category }}</p>
              <p v-if="line.attributes.tube_diameter || line.attributes.tube_thickness || line.attributes.cutting_length_mm">管径：{{ line.attributes.tube_diameter || '—' }} · 管厚：{{ line.attributes.tube_thickness || '—' }} · 下料长度：{{ line.attributes.cutting_length_mm ?? '—' }} mm</p>
              <p v-if="line.attributes.thickness">厚度：{{ line.attributes.thickness }}</p>
              <template v-for="(snapshot, index) in [line.input_material_selection_snapshot, line.output_material_selection_snapshot]" :key="index"><div v-if="snapshot?.name" class="semi-snapshot"><strong>{{ index === 0 ? '投入材料' : '入库半成品' }}：{{ snapshot.name }}</strong><p v-if="snapshot.processing_stage">加工状态：{{ snapshot.processing_stage }}</p><p v-for="(value, name) in snapshot.attributes" :key="name">{{ semiAttributeLabels[name] || name }}：{{ value }}</p></div></template>
              <template v-if="line.metal_processing"><p>实领投入 {{ quantityText(line.metal_processing.issued) }} · 最低报工 {{ quantityText(line.metal_processing.reported_minimum) }} · 首次产出上限 {{ quantityText(line.metal_processing.first_output_limit) }} {{ line.attributes.unit_name }}</p><p>已外发 {{ quantityText(line.metal_processing.dispatched) }} · 已预留 {{ quantityText(line.metal_processing.reserved) }} · 当前余量 {{ quantityText(line.metal_processing.current_remaining) }} {{ line.attributes.unit_name }}</p><p v-for="operation in line.metal_processing.operations" :key="operation.work_item_id">{{ operation.name }}：已报 {{ quantityText(operation.quantity) }} {{ line.attributes.unit_name }}</p><p v-for="scheme in line.metal_processing.schemes" :key="scheme.id">加工依据：{{ scheme.scheme_number }} · V{{ scheme.version }} · {{ scheme.effective_from }} 生效</p><p>核算截至：{{ line.metal_processing.as_of }}</p></template>
              <template v-else><p>累计数量含外发同阶段入库和厂内入库（含待确认），可入数量还会扣除已直发及待发预留。</p><p v-if="line.directly_committed != null">已直发及待发预留：{{ quantityText(line.directly_committed) }} {{ line.attributes.unit_name }}</p><p v-if="line.input_remaining != null">原料剩余：{{ quantityText(line.input_remaining) }}</p><p v-if="line.input_supported != null">原料支持数量：{{ quantityText(line.input_supported) }}</p></template>
            </details>
          </article>
          <section v-if="preview.excluded.length" class="section-card semi-excluded"><strong>以下明细不在本次入库范围</strong><p v-for="name in preview.excluded" :key="name">{{ name }}</p></section>
          <details class="section-card semi-extra"><summary>备注<span class="muted">选填<VanIcon name="arrow-down" /></span></summary><VanField v-model="remark" type="textarea" label="备注" placeholder="有特殊要求再填写" maxlength="2000" autosize :disabled="locked" /></details>
          <VanButton block :disabled="saving || loading || storageBlocked" @click="load">刷新入库额度</VanButton>
        </template>
        <section v-if="actionError" class="error-panel" role="alert">{{ actionError }}</section>
      </template>
    </div>
    <template v-if="!result" #footer><p class="semi-footer-note">{{ pending ? '原编号核对结果，勿重复申请' : `本次 ${selectedLines.length} 项 · ${total} ${scope?.plan_category === 'METAL' ? '支' : '套'}` }} · 仓库确认后入库</p><VanButton block type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">{{ pending ? '核对本次提交' : '提交入库申请' }}</VanButton></template>
    <VanPopup v-model:show="showDate" position="bottom" round teleport="body" class="semi-popup"><VanDatePicker v-model="pickerDate" title="收货日期" :columns-type="['year', 'month', 'day']" :min-date="minDate" :max-date="maxDate" :formatter="formatDate" @confirm="confirmDate" @cancel="showDate = false" /></VanPopup>
    <VanPopup v-model:show="showWarehouse" position="bottom" round closeable teleport="body" class="semi-popup semi-picker"><h2>选择半成品仓</h2><div class="semi-options"><VanCell v-for="warehouse in warehouses" :key="warehouse.id" :title="warehouse.name" clickable :icon="warehouse.id === warehouseId ? 'success' : undefined" @click="selectWarehouse(warehouse.id)" /></div></VanPopup>
    <VanPopup v-model:show="showZone" position="bottom" round closeable teleport="body" class="semi-popup semi-picker"><h2>{{ warehouseName }} · 选择库区</h2><div class="semi-options"><VanCell v-for="zone in zones" :key="zone.id" :title="zone.name" clickable :icon="zone.id === zoneId ? 'success' : undefined" @click="selectZone(zone.id)" /><p v-if="!zones.length">当前仓库没有可用库区。</p></div></VanPopup>
  </WorkPage>
</template>

<style scoped>
.semi-work-page :deep(.work-header .van-nav-bar__content) { height: 48px; }
.semi-work-page :deep(.work-heading) { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.semi-work-page :deep(.work-heading h1) { font-size: 18px; }
.semi-work-page :deep(.work-heading p) { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.semi-work-page :deep(.work-content) { padding: 10px 12px; }
.semi-page { gap: 10px; }
.semi-page .section-card { padding: 12px; border-radius: 12px; }
.semi-page p { margin-block: 6px; overflow-wrap: anywhere; }
.semi-product summary, .semi-extra summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; list-style: none; cursor: pointer; }
summary::-webkit-details-marker { display: none; }
.semi-product summary > span:first-child { min-width: 0; }
.semi-product summary strong { display: block; font-size: 16px; overflow-wrap: anywhere; }
.semi-product summary small { display: block; color: var(--mobile-muted); margin-top: 3px; }
.semi-toggle, .semi-extra summary > span { display: flex; align-items: center; gap: 4px; white-space: nowrap; color: var(--mobile-muted); font-size: 12px; }
.semi-product-details { margin-top: 10px; border-top: 1px solid var(--mobile-border); padding-top: 4px; color: var(--mobile-muted); font-size: 13px; }
.semi-page .semi-form { padding-block: 0; }
.semi-stage { padding-bottom: 8px; color: var(--mobile-muted); font-size: 13px; }
.semi-choice { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; width: 100%; padding: 8px 0; border: 0; border-top: 1px solid var(--mobile-border); background: transparent; color: var(--mobile-text); font: inherit; font-size: 14px; text-align: left; }
.semi-choice:first-child { border-top: 0; }
.semi-choice > span:first-child { flex-shrink: 0; }
.semi-choice > span:last-child { display: flex; align-items: center; justify-content: flex-end; gap: 8px; min-width: 0; text-align: right; overflow-wrap: anywhere; }
.semi-choice .van-icon { flex-shrink: 0; color: var(--mobile-muted); }
.semi-choice:disabled { color: var(--mobile-muted); }
.semi-material-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.semi-material-heading strong { font-size: 18px; font-weight: 700; overflow-wrap: anywhere; }
.semi-material-heading span { flex-shrink: 0; color: #166534; background: #dcfce7; border-radius: 4px; padding: 2px 6px; font-size: 12px; font-weight: 600; }
.semi-material-spec { font-size: 13px; color: var(--mobile-muted); }
.semi-quantities { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0; }
.semi-quantities > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.semi-quantities span { color: var(--mobile-muted); font-size: 12px; }
.semi-quantities b { font-size: 16px; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.semi-quantities small { font-size: 12px; font-weight: 400; }
.semi-available b { color: var(--mobile-primary); }
.semi-quantity { padding: 0; border: 0; background: transparent; align-items: center; }
.semi-quantity::after { border: 0; }
.semi-quantity :deep(.van-field__label) { width: 4em; color: var(--mobile-text); font-weight: 600; }
.semi-quantity :deep(.van-field__value) { min-width: 0; }
.semi-quantity :deep(.van-field__body) { min-height: 44px; padding: 0 10px; border: 1px solid #9aafca; border-radius: 8px; background: var(--mobile-surface); }
.semi-quantity :deep(.van-field__body:focus-within) { border-color: var(--mobile-primary); }
.semi-quantity.van-field--disabled :deep(.van-field__body) { border-color: var(--mobile-border); background: var(--mobile-canvas); }
.semi-quantity :deep(.van-field__control) { min-height: 42px; color: var(--mobile-text); font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.semi-quantity :deep(.van-field__control::placeholder) { font-size: 14px; color: var(--mobile-muted); font-weight: 400; }
.semi-quantity :deep(.van-field__control:disabled) { color: var(--mobile-muted); -webkit-text-fill-color: var(--mobile-muted); }
.semi-quantity :deep(.van-field__button) { white-space: nowrap; color: var(--mobile-muted); font-size: 14px; }
.semi-details { margin-top: 8px; color: var(--mobile-muted); font-size: 13px; }
.semi-details summary { display: flex; justify-content: space-between; align-items: center; min-height: 28px; cursor: pointer; list-style: none; }
.semi-details p { line-height: 1.6; }
.semi-snapshot { padding-top: 8px; border-top: 1px solid var(--mobile-border); }
.semi-extra { font-size: 14px; }
.semi-extra :deep(.van-cell) { padding: 10px 0; }
.semi-error { color: var(--van-danger-color, #b42318); font-size: 13px; }
.semi-pending { color: #92400e; background: #fffbeb !important; font-size: 13px; }
.semi-excluded { font-size: 13px; color: var(--mobile-muted); }
.semi-loading { padding: 24px; text-align: center; }
.semi-footer-note { margin: 0 0 8px; color: var(--mobile-muted); font-size: 13px; text-align: center; }
.semi-success { text-align: center; }
.semi-success > .van-icon { color: var(--mobile-primary); }
.semi-success h2 { font-size: 20px; }
.semi-success .van-button { margin-top: 16px; }
.semi-popup { width: min(100%, 640px); left: 0; right: 0; margin-inline: auto; }
.semi-picker { max-height: 75dvh; padding-top: 16px; }
.semi-picker h2 { margin: 0 48px 12px 16px; font-size: 18px; }
.semi-options { max-height: 60dvh; overflow-y: auto; overscroll-behavior: contain; }
.semi-options :deep(.van-cell) { min-height: 48px; }
.semi-options > p { padding: 16px; }
.semi-choice:focus-visible, summary:focus-visible { outline: 2px solid var(--mobile-primary); outline-offset: 2px; }
</style>
