<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { Button as VanButton, Cell as VanCell, DatePicker as VanDatePicker, Field as VanField, Icon as VanIcon, Loading as VanLoading, Popup as VanPopup, Search as VanSearch, showDialog } from 'vant'
import type { PickerConfirmEventParams, PickerOption } from 'vant'
import 'vant/es/button/style'
import 'vant/es/cell/style'
import 'vant/es/date-picker/style'
import 'vant/es/field/style'
import 'vant/es/icon/style'
import 'vant/es/loading/style'
import 'vant/es/popup/style'
import 'vant/es/search/style'
import WorkPage from '@/components/WorkPage.vue'
import { useAuthStore } from '@/stores/auth'
import { createFinishedReceipt, fetchFinishedReceiptOptions, fetchFinishedReceiptPreview } from '@/api/finishedReceipts'
import type { FinishedReceiptOptions, FinishedReceiptPreview, FinishedReceiptResult, PendingFinishedReceipt } from '@/types/finishedReceipts'
import { errorMessage } from '@/utils/errors'
import { createRequestId } from '@/utils/requestId'
import { shanghaiToday, validProductionDate } from '@/utils/reporting'
import { formatReceiptQuantity, parsePendingFinishedReceipt, positiveReceiptQuantity, receiptBlocker, receiptFailureIsDefinitive, receiptUuid, validateFinishedReceipt } from '@/utils/finishedReceipts'
import { createFinishedReceiptPending } from '@/utils/finishedReceiptPending'

const route = useRoute(), router = useRouter(), auth = useAuthStore()
const owner = { userId: auth.user?.id ?? null, generation: auth.generation }
let alive = true, sequence = 0, controller: AbortController | null = null
let store: ReturnType<typeof createFinishedReceiptPending> | null = null
let pendingRaw: string | null = null
const planId = computed(() => typeof route.query.schedule_product_id === 'string' && receiptUuid.test(route.query.schedule_product_id) ? route.query.schedule_product_id : '')
const canCreate = computed(() => auth.hasPermission('inventory.add_finishedgoodsreceipt'))
const preview = ref<FinishedReceiptPreview | null>(null), options = ref<FinishedReceiptOptions | null>(null)
const pending = ref<PendingFinishedReceipt | null>(null), result = ref<FinishedReceiptResult | null>(null)
const loading = ref(false), saving = ref(false), storageBlocked = ref(false), needsRefresh = ref(false)
const loadError = ref(''), actionError = ref('')
const quantity = ref(''), perBox = ref(''), receiptDate = ref(''), remark = ref('')
const warehouseId = ref(''), zoneId = ref(''), locationId = ref('')
const showDate = ref(false), pickerDate = ref<string[]>([]), showWarehouse = ref(false), showLocation = ref(false)
const draftZone = ref(''), locationSearch = ref('')
const current = () => alive && auth.user?.id === owner.userId && auth.generation === owner.generation
const locked = computed(() => saving.value || Boolean(pending.value) || storageBlocked.value || !current())
const warehouses = computed(() => options.value?.warehouses.filter(item => item.status === 'ACTIVE' && item.warehouse_type === 'FINISHED') ?? [])
const zones = computed(() => options.value?.zones.filter(item => item.status === 'ACTIVE' && item.warehouse === warehouseId.value) ?? [])
const locations = computed(() => options.value?.locations.filter(item => item.status === 'ACTIVE' && item.warehouse_id === warehouseId.value && item.zone === draftZone.value
  && zones.value.some(zone => zone.id === item.zone)) ?? [])
const filteredLocations = computed(() => locations.value.filter(item => item.location_number.toLocaleLowerCase().includes(locationSearch.value.trim().toLocaleLowerCase())))
const warehouseName = computed(() => warehouses.value.find(item => item.id === warehouseId.value)?.warehouse_name || '请选择成品仓')
const selectedLocation = computed(() => options.value?.locations.find(item => item.id === locationId.value))
const locationName = computed(() => selectedLocation.value ? `${options.value?.zones.find(item => item.id === zoneId.value)?.zone_name || ''} · ${selectedLocation.value.location_number}` : '请选择库区、库位')
const blocked = computed(() => preview.value ? receiptBlocker(preview.value) : '')
const parsedQuantity = computed(() => positiveReceiptQuantity(quantity.value)), parsedPack = computed(() => positiveReceiptQuantity(perBox.value))
const boxSlots = computed(() => parsedQuantity.value !== null && parsedPack.value !== null ? Math.ceil(parsedQuantity.value / parsedPack.value) : null)
const canSubmit = computed(() => canCreate.value && current() && !storageBlocked.value && !loading.value && !saving.value
  && (Boolean(pending.value) || Boolean(preview.value && options.value && !blocked.value && !needsRefresh.value)))
const minDate = computed(() => new Date(Math.min(Number(shanghaiToday().slice(0, 4)) - 10, Number(receiptDate.value.slice(0, 4)) || 9999), 0, 1))
const maxDate = computed(() => new Date(Math.max(Number(shanghaiToday().slice(0, 4)) + 10, Number(receiptDate.value.slice(0, 4)) || 0), 11, 31))
watch([locked, loading], ([isLocked, isLoading]) => { if (isLocked || isLoading) { showDate.value = false; showWarehouse.value = false; showLocation.value = false } })

function openDate() {
  if (locked.value || loading.value) return
  pickerDate.value = receiptDate.value.split('-'); showDate.value = true
}
function confirmDate({ selectedValues }: PickerConfirmEventParams) {
  if (locked.value || loading.value) return
  const value = selectedValues.join('-')
  if (validProductionDate(value)) { receiptDate.value = value; showDate.value = false }
}
function formatDate(type: string, option: PickerOption) { return { ...option, text: `${option.text}${({ year: '年', month: '月', day: '日' } as Record<string, string>)[type] || ''}` } }
function selectWarehouse(id: string) {
  if (locked.value || !warehouses.value.some(item => item.id === id)) return
  if (warehouseId.value !== id) { warehouseId.value = id; zoneId.value = ''; locationId.value = '' }
  showWarehouse.value = false
}
function openLocation() {
  if (locked.value || !warehouseId.value) return
  draftZone.value = zones.value.some(item => item.id === zoneId.value) ? zoneId.value : ''
  locationSearch.value = ''; showLocation.value = true
}
function selectLocation(id: string) {
  if (locked.value || !locations.value.some(item => item.id === id)) return
  locationId.value = id; zoneId.value = draftZone.value; showLocation.value = false
}
async function load() {
  if (!planId.value || !current() || storageBlocked.value || saving.value) return
  controller?.abort(); controller = new AbortController()
  const request = ++sequence, id = planId.value
  loading.value = true; loadError.value = ''; preview.value = null; options.value = null
  try {
    const [data, places] = await Promise.all([fetchFinishedReceiptPreview(id, controller.signal), fetchFinishedReceiptOptions(id, controller.signal)])
    if (!current() || request !== sequence) return
    preview.value = data; options.value = places; needsRefresh.value = false
    receiptDate.value ||= data.receipt_date
    const restoredLocation = places.locations.find(item => item.id === locationId.value)
    if (restoredLocation) { warehouseId.value = restoredLocation.warehouse_id; zoneId.value = restoredLocation.zone }
    else if (!warehouses.value.some(item => item.id === warehouseId.value)) {
      warehouseId.value = warehouses.value.length === 1 ? warehouses.value[0]!.id : ''
      if (!pending.value) { zoneId.value = ''; locationId.value = '' }
    }
  }
  catch (error) { if (current() && request === sequence) loadError.value = errorMessage(error, '入库信息加载失败，请重试。') }
  finally { if (current() && request === sequence) loading.value = false }
}
function initialize() {
  controller?.abort(); sequence++
  loading.value = false; saving.value = false; showDate.value = false; showWarehouse.value = false; showLocation.value = false
  pending.value = null; pendingRaw = null; result.value = null; storageBlocked.value = false; needsRefresh.value = false
  loadError.value = ''; actionError.value = ''; preview.value = null; options.value = null
  quantity.value = ''; perBox.value = ''; receiptDate.value = ''; remark.value = ''; warehouseId.value = ''; zoneId.value = ''; locationId.value = ''
  if (!planId.value) { loadError.value = '入库来源参数无效，请从装配计划重新进入成品入库。'; return }
  if (!canCreate.value) { loadError.value = '当前账号没有成品入库申请权限。'; return }
  store = createFinishedReceiptPending(planId.value, owner, () => ({ userId: alive ? auth.user?.id ?? null : null, generation: auth.generation }))
  try {
    pendingRaw = store.read()
    if (pendingRaw !== null) {
      pending.value = parsePendingFinishedReceipt(pendingRaw, planId.value)
      const payload = pending.value.payload
      quantity.value = String(payload.received_quantity); perBox.value = payload.quantity_per_box === null ? '' : String(payload.quantity_per_box)
      receiptDate.value = payload.receipt_date; remark.value = payload.remark; locationId.value = payload.location_id
    }
  }
  catch (error) { storageBlocked.value = true; loadError.value = errorMessage(error, '无法读取原提交记录，已保留并暂停提交，请联系管理员核对。'); return }
  void load()
}
async function submit() {
  if (!canSubmit.value || !store || result.value) return
  saving.value = true; actionError.value = ''
  const request = sequence, activeStore = store
  try {
    await auth.refresh(true)
    if (!current() || request !== sequence) return
    activeStore.assertCurrent()
    if (!canCreate.value) { actionError.value = '当前账号没有成品入库申请权限。'; return }
    if (!pending.value) {
      const message = validateFinishedReceipt(preview.value!, options.value!, { quantity: quantity.value, perBox: perBox.value, date: receiptDate.value, locationId: locationId.value })
      if (message) { actionError.value = message; return }
      const value: PendingFinishedReceipt = { etag: preview.value!.etag, payload: {
        request_id: createRequestId(), schedule_product_id: planId.value, location_id: locationId.value,
        receipt_date: receiptDate.value, received_quantity: parsedQuantity.value!, quantity_per_box: parsedPack.value,
        actual_color: preview.value!.actual_color, remark: remark.value.trim(),
      } }
      try {
        const raw = JSON.stringify(value)
        activeStore.write(raw); pendingRaw = raw; pending.value = value
      }
      catch (error) { storageBlocked.value = true; actionError.value = errorMessage(error, '无法保存提交编号，已暂停提交，请重新打开本页核对。'); return }
    }
    try { activeStore.assertUnchanged(pendingRaw!) }
    catch (error) { storageBlocked.value = true; actionError.value = errorMessage(error); return }
    try {
      const saved = await createFinishedReceipt(pending.value.payload, pending.value.etag)
      if (!current() || request !== sequence) return
      result.value = saved
      try { activeStore.consume(pendingRaw!); pending.value = null; pendingRaw = null }
      catch { storageBlocked.value = true; actionError.value = '申请已提交，但原请求记录未能清理；请保留单号并联系管理员核对，勿重复申请。' }
    }
    catch (error) {
      if (!current() || request !== sequence) return
      if (receiptFailureIsDefinitive(error)) {
        try { activeStore.consume(pendingRaw!); pending.value = null; pendingRaw = null; needsRefresh.value = true }
        catch { storageBlocked.value = true; actionError.value = '待核对记录无法更新，已保留并暂停提交，请联系管理员核对。'; return }
        actionError.value = `${errorMessage(error)} 请刷新额度后重新核对。`
      }
      else actionError.value = `${errorMessage(error)} 本次提交结果尚未确认，请使用原编号“核对本次提交”，勿另建单据。`
    }
  }
  catch (error) { if (current() && request === sequence) actionError.value = errorMessage(error, '身份核验失败，请重试。') }
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
watch(() => route.query.schedule_product_id, initialize, { immediate: true })
onBeforeUnmount(() => { alive = false; sequence++; controller?.abort(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <WorkPage class="receipt-work-page" title="成品入库" :subtitle="preview?.task_number || '装配'">
    <div class="page-stack receipt-page">
      <section v-if="result" class="section-card receipt-success" role="status">
        <VanIcon name="passed" size="40" />
        <h2>{{ result.status === 'CONFIRMED' ? '仓库已确认入库' : '申请已提交，待仓库确认' }}</h2>
        <strong>{{ result.receipt_number }}</strong>
        <p>{{ result.status === 'CONFIRMED' ? '原单已由仓库确认，请勿重复申请。' : '仓库在 ERP 确认后增加成品库存。' }}</p>
        <p v-if="actionError" class="receipt-error">{{ actionError }}</p>
        <VanButton block type="primary" @click="router.push('/')">返回生产列表</VanButton>
      </section>
      <template v-else>
        <div v-if="loading" class="receipt-loading" role="status"><VanLoading>正在读取入库额度…</VanLoading></div>
        <section v-if="loadError" class="error-panel" role="alert"><p>{{ loadError }}</p><VanButton v-if="planId && !storageBlocked && canCreate" block :disabled="saving || loading" @click="load">重新加载</VanButton></section>
        <section v-if="pending" class="receipt-pending section-card" role="status">
          <strong>原提交待核对，填写内容已锁定</strong>
          <p>{{ pending.payload.receipt_date }} · 本次数量 {{ pending.payload.received_quantity }} {{ preview?.unit_name }}</p>
          <p>刷新或网络中断后，继续使用原编号核对。</p>
        </section>
        <template v-if="preview">
          <details class="section-card receipt-product">
            <summary><span><strong>{{ preview.product_name }}</strong><small>{{ preview.task_number }}</small></span><span class="receipt-toggle">产品详情<VanIcon name="arrow-down" /></span></summary>
            <div class="receipt-product-details">
              <p>{{ preview.product_number }} · {{ preview.specification || '规格未填写' }}</p>
              <p>订单颜色：{{ (pending?.payload.actual_color ?? preview.actual_color) || '未填写' }}</p>
              <p>订单号：{{ preview.order_number || '未填写' }} · 装配计划：{{ preview.schedule_number }}</p>
              <p>货号：{{ preview.item_number || '未填写' }} · 入库人：{{ preview.actor_name }}</p>
              <p>订单 {{ preview.order_quantity }} {{ preview.unit_name }}，允许偏差 {{ preview.tolerance_percent }}%，订单上限 {{ preview.order_maximum }} {{ preview.unit_name }}。</p>
            </div>
          </details>
          <section class="section-card receipt-quota">
            <div><span>装配最低报工</span><b>{{ preview.reported_minimum }}</b></div><div><span>累计已提交</span><b>{{ preview.received_total }}</b></div><div class="receipt-available"><span>剩余可申请</span><b>{{ preview.remaining_receivable }} <small>{{ preview.unit_name }}</small></b></div>
            <details><summary>查看额度依据</summary><p>累计上限 {{ preview.maximum_receivable }} {{ preview.unit_name }}，取订单上限与装配最低报工量的较小值；待确认单据也占用额度，已出库不恢复额度。</p><p v-for="operation in preview.reporting_operations" :key="operation.work_item_id">{{ operation.operation }}：已报 {{ operation.reported_quantity }} {{ preview.unit_name }}</p></details>
          </section>
          <section v-if="blocked" class="error-panel" role="alert">{{ blocked }}</section>
          <section class="section-card receipt-form">
            <VanField v-model="quantity" class="receipt-quantity" label="本次入库" placeholder="请输入数量" type="text" inputmode="numeric" :formatter="value => formatReceiptQuantity(value, quantity)" :disabled="locked" aria-label="本次入库数量"><template #button><span>{{ preview.unit_name }}</span></template></VanField>
            <button class="receipt-choice receipt-date" type="button" :disabled="locked" aria-label="选择收货日期" aria-haspopup="dialog" @click="openDate"><span>收货日期</span><span>{{ receiptDate }}<VanIcon name="calendar-o" /></span></button>
            <button class="receipt-choice receipt-warehouse" type="button" :disabled="locked || !warehouses.length" aria-label="选择成品仓" aria-haspopup="dialog" @click="showWarehouse = true"><span>成品仓</span><span>{{ warehouseName }}<VanIcon name="arrow" /></span></button>
            <button class="receipt-choice receipt-location" type="button" :disabled="locked || !warehouseId" aria-label="选择库区和库位" aria-haspopup="dialog" @click="openLocation"><span>库区 / 库位</span><span>{{ locationName }}<VanIcon name="arrow" /></span></button>
            <p v-if="!warehouses.length" class="receipt-error">没有可用成品仓，请联系仓库维护。</p>
            <p v-else-if="warehouseId && !zones.length" class="receipt-error">当前成品仓没有可用库区，请联系仓库维护。</p>
          </section>
          <details class="section-card receipt-extra">
            <summary>包装与备注<span class="muted">选填<VanIcon name="arrow-down" /></span></summary>
            <VanField v-model="perBox" class="receipt-pack" label="每箱数量" placeholder="留空不计算箱位" type="text" inputmode="numeric" :formatter="value => formatReceiptQuantity(value, perBox)" :disabled="locked" />
            <p v-if="boxSlots !== null">整箱 {{ Math.floor(parsedQuantity! / parsedPack!) }} 箱，尾数 {{ parsedQuantity! % parsedPack! }} {{ preview.unit_name }}，占用 {{ boxSlots }} 箱位。</p>
            <p v-if="selectedLocation">当前库位{{ selectedLocation.remaining_box_slots === null ? '未设容量' : `剩余 ${selectedLocation.remaining_box_slots} 箱位` }}。</p>
            <VanField v-model="remark" type="textarea" label="备注" placeholder="有特殊要求再填写" maxlength="3000" autosize :disabled="locked" />
          </details>
        </template>
        <section v-if="actionError" class="error-panel" role="alert">{{ actionError }}</section>
        <VanButton v-if="needsRefresh" block :disabled="saving || loading || storageBlocked" @click="load">刷新入库额度</VanButton>
      </template>
    </div>
    <template v-if="!result" #footer>
      <p class="receipt-footer-note">提交后由仓库在 ERP 确认入库。</p>
      <VanButton block type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">{{ pending ? '核对本次提交' : '提交入库申请' }}</VanButton>
    </template>
    <VanPopup v-model:show="showDate" class="receipt-popup" position="bottom" round teleport="body" safe-area-inset-bottom><VanDatePicker v-model="pickerDate" title="选择收货日期" :columns-type="['year', 'month', 'day']" :min-date="minDate" :max-date="maxDate" :formatter="formatDate" @confirm="confirmDate" @cancel="showDate = false" /></VanPopup>
    <VanPopup v-model:show="showWarehouse" class="receipt-popup receipt-picker" position="bottom" round closeable teleport="body" safe-area-inset-bottom><h2>选择成品仓</h2><VanCell v-for="warehouse in warehouses" :key="warehouse.id" :title="warehouse.warehouse_name" :label="warehouse.warehouse_number" clickable is-link @click="selectWarehouse(warehouse.id)" /></VanPopup>
    <VanPopup v-model:show="showLocation" class="receipt-popup receipt-picker" position="bottom" round closeable teleport="body" safe-area-inset-bottom>
      <h2>{{ draftZone ? '选择库位' : '选择库区' }}</h2>
      <template v-if="draftZone"><button class="action-link" type="button" @click="draftZone = ''; locationSearch = ''">重新选择库区</button><VanSearch v-model="locationSearch" placeholder="搜索库位编号" /></template>
      <div class="receipt-options">
        <template v-if="!draftZone"><VanCell v-for="zone in zones" :key="zone.id" :title="zone.zone_name" clickable is-link @click="draftZone = zone.id" /><p v-if="!zones.length" class="muted">没有可用库区。</p></template>
        <template v-else><VanCell v-for="location in filteredLocations" :key="location.id" :title="location.location_number" :label="location.remaining_box_slots === null ? '未设容量' : `剩余 ${location.remaining_box_slots} 箱位`" clickable is-link @click="selectLocation(location.id)" /><p v-if="!filteredLocations.length" class="muted">没有匹配的可用库位。</p></template>
      </div>
    </VanPopup>
  </WorkPage>
</template>

<style scoped>
.receipt-work-page :deep(.van-nav-bar) { --van-nav-bar-height: 48px; }
.receipt-work-page :deep(.work-heading) { display: flex; align-items: baseline; gap: 8px; }
.receipt-work-page :deep(.work-heading h1) { font-size: 18px; }
.receipt-work-page :deep(.work-heading p) { margin: 0; font-size: 12px; }
.receipt-work-page :deep(.work-content) { padding: 10px 12px 120px; }
.receipt-page { gap: 10px; color: var(--mobile-text); }
.receipt-page p { margin: 8px 0; line-height: 1.6; overflow-wrap: anywhere; }
.receipt-page .section-card { padding: 10px 12px; border-radius: 12px; background: var(--mobile-surface); }
.receipt-page .receipt-product, .receipt-page .receipt-extra { padding-block: 0; }
.receipt-product > summary, .receipt-extra > summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 48px; cursor: pointer; list-style: none; }
.receipt-product > summary::-webkit-details-marker, .receipt-extra > summary::-webkit-details-marker { display: none; }
.receipt-product > summary > span:first-child { display: flex; flex-wrap: wrap; align-items: baseline; min-width: 0; gap: 4px 8px; padding-block: 8px; overflow-wrap: anywhere; }
.receipt-product small { color: var(--mobile-muted); font-size: 13px; }
.receipt-toggle { flex-shrink: 0; color: var(--mobile-primary); font-size: 13px; }
.receipt-product[open] .receipt-toggle .van-icon { transform: rotate(180deg); }
.receipt-product-details { padding-bottom: 4px; border-top: 1px solid var(--mobile-border); color: var(--mobile-muted); font-size: 13px; }
.receipt-quota { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.receipt-quota > div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.receipt-quota span { color: var(--mobile-muted); font-size: 12px; }
.receipt-quota b { font-size: 18px; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.receipt-quota small { font-size: 12px; font-weight: 400; }
.receipt-quota .receipt-available b { color: var(--mobile-primary); }
.receipt-quota details { grid-column: 1 / -1; font-size: 13px; color: var(--mobile-muted); }
.receipt-quota summary { padding-top: 4px; cursor: pointer; }
.receipt-page .receipt-form { padding-block: 8px 0; }
.receipt-choice { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 48px; width: 100%; padding: 8px 0; border: 0; border-top: 1px solid var(--mobile-border); background: transparent; color: var(--mobile-text); font: inherit; font-size: 14px; text-align: left; }
.receipt-choice > span:first-child { flex-shrink: 0; }
.receipt-choice > span:last-child { display: flex; align-items: center; justify-content: flex-end; gap: 8px; min-width: 0; text-align: right; overflow-wrap: anywhere; }
.receipt-choice .van-icon { flex-shrink: 0; color: var(--mobile-muted); }
.receipt-choice:disabled { color: var(--mobile-muted); }
.receipt-quantity { margin-bottom: 8px; padding: 0; border: 0; background: transparent; align-items: center; }
.receipt-quantity::after { border: 0; }
.receipt-quantity :deep(.van-field__label) { width: 4em; color: var(--mobile-text); font-weight: 600; }
.receipt-quantity :deep(.van-field__value) { min-width: 0; }
.receipt-quantity :deep(.van-field__body) { min-height: 44px; padding: 0 10px; border: 1px solid #9aafca; border-radius: 8px; background: var(--mobile-surface); }
.receipt-quantity :deep(.van-field__body:focus-within) { border-color: var(--mobile-primary); }
.receipt-quantity.van-field--disabled :deep(.van-field__body) { border-color: var(--mobile-border); background: var(--mobile-canvas); }
.receipt-quantity :deep(.van-field__control) { min-height: 42px; color: var(--mobile-text); font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.receipt-quantity :deep(.van-field__control::placeholder) { font-size: 14px; color: var(--mobile-muted); font-weight: 400; }
.receipt-quantity :deep(.van-field__control:disabled) { color: var(--mobile-muted); -webkit-text-fill-color: var(--mobile-muted); }
.receipt-quantity :deep(.van-field__button) { white-space: nowrap; color: var(--mobile-muted); font-size: 14px; }
.receipt-extra { font-size: 14px; }
.receipt-extra :deep(.van-cell) { padding: 10px 0; }
.receipt-error { color: var(--van-danger-color, #b42318); }
.receipt-pending { color: #92400e; background: #fffbeb !important; font-size: 14px; }
.receipt-pending p { margin-bottom: 0; }
.receipt-loading { padding: 24px; text-align: center; }
.receipt-footer-note { margin: 0 0 8px; color: var(--mobile-muted); font-size: 13px; text-align: center; }
.receipt-success { text-align: center; }
.receipt-success > .van-icon { color: var(--mobile-primary); }
.receipt-success h2 { font-size: 20px; }
.receipt-success .van-button { margin-top: 16px; }
.receipt-popup { width: min(100%, 640px); left: 0; right: 0; margin-inline: auto; }
.receipt-picker { max-height: 80dvh; padding-top: 16px; }
.receipt-picker h2 { margin: 0 48px 12px 16px; font-size: 18px; }
.receipt-options { max-height: 54dvh; overflow-y: auto; overscroll-behavior: contain; }
.receipt-options :deep(.van-cell) { min-height: 48px; }
.receipt-options > p { padding: 16px; }
.receipt-picker > .action-link { margin-left: 8px; }
.receipt-choice:focus-visible, summary:focus-visible { outline: 2px solid var(--mobile-primary); outline-offset: 2px; }
</style>
