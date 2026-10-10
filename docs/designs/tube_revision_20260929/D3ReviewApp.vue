<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Menu, Refresh, Search } from '@element-plus/icons-vue'
import Workbench from '@icon-park/vue-next/es/icons/Workbench'
import People from '@icon-park/vue-next/es/icons/People'
import Box from '@icon-park/vue-next/es/icons/Box'
import FactoryBuilding from '@icon-park/vue-next/es/icons/FactoryBuilding'
import ShoppingCart from '@icon-park/vue-next/es/icons/ShoppingCart'
import ConnectionPoint from '@icon-park/vue-next/es/icons/ConnectionPoint'
import Setting from '@icon-park/vue-next/es/icons/Setting'
import Truck from '@icon-park/vue-next/es/icons/Truck'
import Export from '@icon-park/vue-next/es/icons/Export'
import Order from '@icon-park/vue-next/es/icons/Order'
import AppWindowDialog from '../../../src/frontend/src/components/common/AppWindowDialog.vue'
import DesignTable from './DesignTable.vue'

// 独立待确认图稿：所有单据、库区及结果均为示例，不发送业务请求。
const params = new URLSearchParams(window.location.search)
const sourceOptions = [['RAW_PIPE', '原材料'], ['PUBLIC_SEMI', '未喷塑半成品'], ['METAL', '未入库半成品']]
const entryOptions = [['order', '外发单入口'], ['inventory', '半成品入口']]
const stateOptions = [['mixed', '混合回货'], ['full', '全部回货'], ['zero', '整单0回货'], ['blank', '整单空白'], ['long', '40行明细'], ['empty', '无明细'], ['loading', '读取中'], ['error', '读取失败'], ['forbidden', '无权限'], ['ended', '已结束结果'], ['result', '提交结果待核对'], ['invalid', '输入错误'], ['not-applicable', '待发不适用'], ['cancelled', '已取消不适用']]
const allowed = (options, value, fallback) => options.some(([key]) => key === value) ? value : fallback
const source = ref(allowed(sourceOptions, params.get('source'), 'RAW_PIPE'))
const entry = ref(allowed(entryOptions, params.get('entry'), 'order'))
const state = ref(allowed(stateOptions, params.get('state'), 'mixed'))
const orderSelected = ref(entry.value === 'order' || params.get('order') === 'selected')
const dialog = ref('')
const receiptDate = ref('2026-09-30')
const remark = ref('')
const warehouse = ref(['zero', 'blank'].includes(state.value) ? '' : 'semi')
const pendingWarehouse = ref('')
const search = ref('')
const pickerSource = ref('')
const warehouses = [
  { id: 'semi', label: '半成品管材仓', zones: [{ id: 'A', label: '一楼 A区' }, { id: 'B', label: '一楼 B区' }, { id: 'C', label: '一楼 C区' }] },
  { id: 'temporary', label: '半成品暂存仓', zones: [{ id: 'T1', label: '暂存一区' }, { id: 'T2', label: '暂存二区' }] },
]
const nav = [['工作台', Workbench], ['客户管理', People], ['样品管理', Box], ['产品管理', Box], ['生产管理', FactoryBuilding], ['采购管理', ShoppingCart], ['生产车间', ConnectionPoint]]
const subnav = [['生产配置', Setting], ['计划排产', Workbench], ['内部计划', FactoryBuilding], ['委外加工', Export], ['生产领料', Truck], ['工价方案', Box], ['报工记录', Order]]
const baseRows = [
  { id: 'front', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8', length: '650', color: '原料本色', coating: '黑色', factory: '海丰喷塑厂', sent: 200, received: '200', reason: '', zone: 'A' },
  { id: 'rear', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8', length: '720', color: '原料本色', coating: '黑色', factory: '海丰喷塑厂', sent: 300, received: '280', reason: '实际交回280支，其余20支未交回', zone: 'B' },
  { id: 'arm', part: '扶手管', material: 'Q195', spec: '椭圆管 30×15', thickness: '0.9', length: '520', color: '原料本色', coating: '黑色', factory: '永兴喷塑厂', sent: 120, received: '0', reason: '本部位本次未收到实物', zone: '' },
  { id: 'join', part: '连接管', material: 'Q195', spec: '圆管 Φ16', thickness: '0.7', length: '360', color: '原料本色', coating: '黑色', factory: '永兴喷塑厂', sent: 240, received: '', reason: '本部位未交回，按0支登记', zone: '' },
  { id: 'back', part: '靠背管', material: 'Q195', spec: '圆管 Φ19', thickness: '0.8', length: '880', color: '原料本色', coating: '黑色', factory: '海丰喷塑厂', sent: 160, received: '160', reason: '', zone: 'A' },
]
const rows = ref([])
const columns = [['part', '部位', 95], ['material', '材质', 65], ['spec', '规格', 125], ['thickness', '厚度 mm', 75], ['length', '切割长度 mm', 98], ['color', '原料颜色', 85], ['coating', '喷塑颜色', 80], ['factory', '加工厂', 120], ['sent', '实发（支）', 90, true], ['received', '实收（支）', 125, true], ['difference', '差额（支）', 85, true], ['reason', '差额原因', 230], ['zone', '入库库区', 150]].map(([key, label, width, num]) => ({ key, label, width, num }))
const sourceLabel = computed(() => sourceOptions.find(([key]) => key === source.value)?.[1] || '—')
const orderCode = computed(() => ({ RAW_PIPE: 'WWGC20260930001', PUBLIC_SEMI: 'WWGC20260930002', METAL: 'WWGC20260930003' })[source.value])
const zones = computed(() => warehouses.find(item => item.id === warehouse.value)?.zones || [])
const warehouseLabel = computed(() => warehouses.find(item => item.id === warehouse.value)?.label || '—')
const format = value => Number(value).toLocaleString('zh-CN')
function receivedValue(row) {
  const text = String(row.received ?? '').trim()
  if (!text) return 0
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  return Number.isSafeInteger(value) && value >= 0 && value <= row.sent ? value : null
}
function difference(row) { const amount = receivedValue(row); return amount === null ? null : row.sent - amount }
function zoneLabel(row) { return receivedValue(row) > 0 ? zones.value.find(item => item.id === row.zone)?.label || '—' : '—' }
const totalSent = computed(() => rows.value.reduce((sum, row) => sum + row.sent, 0))
const hasInvalidQuantity = computed(() => rows.value.some(row => receivedValue(row) === null))
const totalReceived = computed(() => rows.value.reduce((sum, row) => sum + (receivedValue(row) || 0), 0))
const totalDifference = computed(() => totalSent.value - totalReceived.value)
const positiveRows = computed(() => rows.value.filter(row => receivedValue(row) > 0))
const showDetails = computed(() => orderSelected.value && !['loading', 'error', 'forbidden', 'not-applicable', 'cancelled'].includes(state.value))
const canEdit = computed(() => showDetails.value && !['ended', 'result', 'not-applicable'].includes(state.value) && rows.value.length > 0)
const isEnded = computed(() => state.value === 'ended')
const info = computed(() => [
  ['生产任务单', 'SC20260929001'], ['订单号', 'DD20260921001'], ['排产单号', 'PC20260929001'], ['订单量', '1,000 把'], ['实际发出日', '2026-09-30'], ['预计回货日', '2026-10-15'],
  ['产品名称', '组合杯托折叠椅'], ['品号', 'CP000128'], ['货号', 'HT-806'], ['材料来源', sourceLabel.value], ['加工厂', '2 家'], ['入库状态', '已喷塑'],
])
const candidates = computed(() => sourceOptions.map(([id, label], index) => ({ id, number: `WWGC2026093000${index + 1}`, source: label, task: 'SC20260929001', product: '组合杯托折叠椅', factories: '海丰喷塑厂、永兴喷塑厂', sent: 1020, date: '2026-09-30', status: '加工中' })).filter(row => (!pickerSource.value || row.id === pickerSource.value) && (!search.value.trim() || [row.number, row.task, row.product, row.factories].join(' ').includes(search.value.trim()))))
const pickerColumns = [['number', '外发单号', 210], ['source', '材料来源', 160], ['task', '生产任务单', 190], ['product', '产品名称', 190], ['factories', '加工厂', 250], ['sent', '实发（支）', 100, true], ['date', '实际发出日', 130], ['status', '状态', 85], ['action', '操作', 125]].map(([key, label, width, num]) => ({ key, label, width, num }))
function warn(message) { ElMessage.closeAll(); ElMessage.warning({ message, duration: 4000 }) }
function previewOnly(message) { ElMessage.closeAll(); ElMessage.info({ message: `设计演示：${message}`, duration: 4000 }) }
function resetRows() {
  rows.value = state.value === 'empty' ? [] : (state.value === 'long' ? Array.from({ length: 40 }, (_, index) => ({ ...baseRows[index % 5], id: `part-${index}`, part: `${baseRows[index % 5].part}${index + 1}` })) : baseRows.map(row => ({ ...row })))
  if (state.value === 'full') rows.value.forEach(row => { row.received = String(row.sent); row.reason = ''; row.zone = 'A' })
  if (['zero', 'blank'].includes(state.value)) rows.value.forEach(row => { row.received = state.value === 'zero' ? '0' : ''; row.reason = '本部位本次未交回，按实际0支结束'; row.zone = '' })
  if (state.value === 'invalid' && rows.value.length) rows.value[0].received = '201'
}
function resetPreview() {
  dialog.value = ''; pendingWarehouse.value = ''; ElMessage.closeAll()
  warehouse.value = ['zero', 'blank'].includes(state.value) ? '' : 'semi'
  receiptDate.value = '2026-09-30'; remark.value = ''; resetRows()
}
function changeEntry() { orderSelected.value = entry.value === 'order'; resetPreview() }
function selectOrder(row) {
  if (state.value === 'result') return
  source.value = row.id; orderSelected.value = true
  if (['not-applicable', 'cancelled', 'ended'].includes(state.value)) state.value = 'mixed'
  resetPreview()
}
function closeDialog(value) { if (!value) { dialog.value = ''; pendingWarehouse.value = '' } }
function validateQuantity(row) {
  if (receivedValue(row) === null) { warn(`${row.part}：实收须为0至${format(row.sent)}的整数，空白按0支处理。`); return false }
  return true
}
function onReceivedChange(row) {
  if (receivedValue(row) > 0 && !row.zone && zones.value.length) row.zone = zones.value[0].id
}
function requestWarehouseChange(value) {
  if (value === warehouse.value) return
  if (warehouse.value && rows.value.some(row => row.zone)) { pendingWarehouse.value = value; dialog.value = 'warehouse'; return }
  warehouse.value = value; rows.value.forEach(row => { row.zone = '' })
}
function confirmWarehouseChange() {
  warehouse.value = pendingWarehouse.value; rows.value.forEach(row => { row.zone = '' })
  pendingWarehouse.value = ''; dialog.value = ''; previewOnly('已切换目标仓库；实收支数和差额原因保留，请重新选择正数行的库区。')
}
function validateReceipt() {
  if (!canEdit.value) { warn('当前外发单不能办理整单喷塑入库。'); return false }
  for (const row of rows.value) {
    if (!validateQuantity(row)) return false
    if (difference(row) > 0 && !row.reason.trim()) { warn(`${row.part}：少回${format(difference(row))}支，请填写差额原因。`); return false }
  }
  if (!receiptDate.value) { warn('请选择收货日期。'); return false }
  if (positiveRows.value.length && !warehouse.value) { warn('请选择有实收明细的入库仓库。'); return false }
  for (const row of positiveRows.value) {
    if (!zones.value.some(zone => zone.id === row.zone)) { warn(`${row.part}：请选择当前仓库下的入库库区。`); return false }
  }
  return true
}
function openConfirm() { if (validateReceipt()) dialog.value = 'confirm' }
function finishReceipt() {
  if (!validateReceipt()) return
  dialog.value = ''; state.value = 'ended'
  previewOnly(totalReceived.value ? '展示入库并结束结果，未增加库存、未提交业务接口。' : '展示整单0回货结束结果，未生成库存记录、未提交业务接口。')
}
resetRows()
if (params.get('dialog') === 'select' && state.value !== 'result') dialog.value = 'select'
else if (params.get('dialog') === 'confirm' && canEdit.value && !hasInvalidQuantity.value) dialog.value = 'confirm'
</script>

<template>
  <div class="shell d3-shell">
    <aside class="sidebar">
      <div class="brand-logo">HiTree</div>
      <div class="nav-list">
        <div v-for="[label, icon] in nav" :key="label" class="nav-item"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
        <template v-if="entry === 'order'"><div v-for="[label, icon] in subnav" :key="label" class="nav-item sub" :class="{ active: label === '委外加工' }"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div></template>
        <div class="nav-item"><Truck theme="filled" size="20"/><span>仓库管理</span></div>
        <template v-if="entry === 'inventory'"><div class="nav-item sub"><Box theme="filled" size="20"/><span>成品库存</span></div><div class="nav-item sub active"><Box theme="filled" size="20"/><span>半成品库存</span></div><div class="nav-item sub"><Box theme="filled" size="20"/><span>库存预警</span></div></template>
      </div>
      <div class="nav-bottom"><div class="nav-item"><Setting theme="filled" size="20"/><span>系统配置</span></div></div>
    </aside>
    <header class="topbar d3-topbar">
      <ElIcon><Menu/></ElIcon><span class="crumb">{{ entry === 'order' ? '生产车间 / 委外加工' : '仓库管理 / 半成品' }} / 喷塑入库</span><span class="spacer"/>
      <span class="preview-note">待确认设计 · 示例数据 · 未接入业务</span>
      <ElSelect v-model="source" class="d3-source-picker" aria-label="设计材料来源" popper-class="d3-select-popper" @change="resetPreview"><ElOption v-for="[value, label] in sourceOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <ElSelect v-model="entry" class="d3-entry-picker" aria-label="设计页面入口" popper-class="d3-select-popper" @change="changeEntry"><ElOption v-for="[value, label] in entryOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <ElSelect v-model="state" class="d3-state-picker" aria-label="设计显示情况" popper-class="d3-select-popper" @change="resetPreview"><ElOption v-for="[value, label] in stateOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <span class="d3-current-user">仓库管理员</span>
    </header>
    <main class="main">
      <section class="design-page d3-page">
        <header class="page-heading">
          <div class="title-row"><h1>喷塑入库</h1><span class="status">外发入库</span><template v-if="orderSelected"><span class="status" :class="isEnded ? 'success' : ['not-applicable', 'cancelled'].includes(state) ? 'neutral' : 'info'">{{ isEnded ? '已结束' : state === 'not-applicable' ? '待外发' : state === 'cancelled' ? '已取消' : '加工中' }}</span><span class="d3-order-code">{{ orderCode }}</span></template></div>
          <div class="actions"><ElButton v-if="entry === 'inventory' && !isEnded" :disabled="['forbidden', 'result'].includes(state)" @click="dialog = 'select'">选择外发单</ElButton><ElButton :icon="ArrowLeft" :disabled="state === 'result'" @click="previewOnly(entry === 'order' ? '返回外发单详情。' : '返回半成品库存。')">{{ entry === 'order' ? '返回外发单' : '返回半成品' }}</ElButton></div>
        </header>
        <template v-if="showDetails">
          <div class="panel d3-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value">{{ value }}</strong></div></div></div>
          <ElAlert v-if="state === 'result'" title="提交结果尚未确认，请核对本次原请求结果，避免重复入库或结束。当前填写内容已锁定。" type="warning" :closable="false" show-icon/>
          <div class="panel workspace d3-workspace">
            <div class="section-heading d3-section-heading"><div><h2>{{ isEnded ? '整单回货结果' : '整单实际回货' }}</h2><span class="muted">{{ isEnded ? '已喷塑 · 本单已登记结束' : '按实物逐部位填写 · 空白或0按未回货登记' }}</span></div><ElButton v-if="!isEnded" :icon="Refresh" :disabled="['not-applicable', 'result'].includes(state)" @click="previewOnly('重新核对原单实际发出支数，保留本次已填数量和原因。')">刷新原单</ElButton></div>
            <div class="field-grid d3-receipt-fields">
              <label class="form-field required"><span>收货日期</span><ElDatePicker v-model="receiptDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper d3-date-popper" placeholder="选择日期" aria-label="收货日期" :disabled="!canEdit"/></label>
              <label class="form-field" :class="{ required: positiveRows.length > 0 }"><span>入库仓库 <small v-if="!positiveRows.length" class="muted">无实收可不选</small></span><ElSelect :model-value="warehouse" :disabled="!canEdit" placeholder="选择目标仓库" aria-label="入库仓库" popper-class="d3-select-popper" @update:model-value="requestWarehouseChange"><ElOption v-for="item in warehouses" :key="item.id" :value="item.id" :label="item.label"/></ElSelect></label>
              <label class="form-field"><span>入库经办人</span><ElInput model-value="刘庆远" readonly aria-label="入库经办人"/></label>
              <label class="form-field"><span>入库状态</span><ElInput model-value="已喷塑" readonly aria-label="入库状态"/></label>
            </div>
            <DesignTable :columns="columns" :rows="rows" class="d3-lines" empty="此外发单没有可办理的实发管材明细">
              <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
              <template #cell-sent="{ row }">{{ format(row.sent) }}</template>
              <template #cell-received="{ row }"><strong v-if="!canEdit" class="brand">{{ receivedValue(row) === null ? '—' : format(receivedValue(row)) }}</strong><ElInput v-else v-model="row.received" inputmode="numeric" :aria-label="`${row.part}实收支数`" placeholder="0或空白" @input="onReceivedChange(row)" @blur="validateQuantity(row)"><template #suffix>支</template></ElInput></template>
              <template #cell-difference="{ row }"><strong :class="{ brand: difference(row) > 0 }">{{ difference(row) === null ? '—' : format(difference(row)) }}</strong></template>
              <template #cell-reason="{ row }"><span v-if="!canEdit" class="cell-text" :title="difference(row) > 0 ? row.reason : '—'">{{ difference(row) > 0 ? row.reason : '—' }}</span><ElInput v-else v-model="row.reason" class="reason" :disabled="difference(row) === 0" :aria-label="`${row.part}差额原因`" :placeholder="difference(row) === 0 ? '全回，无需填写' : '少回须填写原因'" maxlength="2000"/></template>
              <template #cell-zone="{ row }"><span v-if="!canEdit">{{ zoneLabel(row) }}</span><ElSelect v-else v-model="row.zone" :disabled="!(receivedValue(row) > 0) || !warehouse" :placeholder="receivedValue(row) > 0 ? '选择库区' : '不入库'" :aria-label="`${row.part}入库库区`" popper-class="d3-select-popper"><ElOption v-for="zone in zones" :key="zone.id" :value="zone.id" :label="zone.label"/></ElSelect></template>
            </DesignTable>
            <label class="form-field d3-remark"><span>入库备注 <small class="muted">选填</small></span><ElInput v-model="remark" type="textarea" :rows="2" :readonly="!canEdit" maxlength="2000" placeholder="填写本次收货或存放说明" aria-label="入库备注"/></label>
          </div>
        </template>
        <div v-else class="panel d3-fallback">
          <ElSkeleton v-if="orderSelected && state === 'loading'" :rows="9" animated/>
          <template v-else><ElEmpty :description="!orderSelected ? '请先选择加工中且未登记整单回货的外发单' : state === 'error' ? '外发单读取失败，请重新加载' : state === 'not-applicable' ? '此外发单尚未实际发出，不能办理喷塑入库' : state === 'cancelled' ? '此外发单已取消，不能办理喷塑入库' : '当前账号没有查看或办理此单的权限'"/><ElButton v-if="!orderSelected" type="primary" :disabled="['forbidden', 'result'].includes(state)" @click="dialog = 'select'">选择外发单</ElButton><ElButton v-else-if="state === 'error'" :icon="Refresh" @click="state = 'mixed'; resetPreview()">重新加载</ElButton></template>
        </div>
        <footer class="footer-bar d3-footer">
          <div class="d3-footer-total"><span>实发 <strong>{{ showDetails ? format(totalSent) : '—' }}</strong> 支</span><span>实收 <strong>{{ showDetails && !hasInvalidQuantity ? format(totalReceived) : '—' }}</strong> 支</span><span>差额 <strong>{{ showDetails && !hasInvalidQuantity ? format(totalDifference) : '—' }}</strong> 支</span><small v-if="isEnded">已结束 · {{ positiveRows.length ? `${positiveRows.length}个部位已入已喷塑公共库存` : '整单实收0支，未增加库存' }}</small></div>
          <ElButton v-if="isEnded" @click="previewOnly('查看本次整单回货入库记录。')">查看入库记录</ElButton>
          <ElButton v-else-if="state === 'result'" type="primary" @click="previewOnly('仅核对本次原请求结果；未重发入库请求、未解锁填写内容。')">核对本次提交</ElButton>
          <ElButton v-else type="primary" :disabled="!canEdit" @click="openConfirm">{{ !hasInvalidQuantity && totalReceived === 0 ? '确认整单结束' : '确认整单入库' }}</ElButton>
        </footer>
      </section>
    </main>
  </div>

  <AppWindowDialog :model-value="dialog === 'confirm'" :title="totalReceived ? '确认喷塑入库并结束外发单' : '确认整单0回货并结束外发单'" :width="1640" @update:model-value="closeDialog">
    <div class="d3-confirm">
      <div class="info-grid d3-confirm-context"><div class="info-cell"><span>外发单号</span><strong>{{ orderCode }}</strong></div><div class="info-cell"><span>生产任务单</span><strong>SC20260929001</strong></div><div class="info-cell"><span>产品名称</span><strong>组合杯托折叠椅</strong></div><div class="info-cell"><span>材料来源</span><strong>{{ sourceLabel }}</strong></div><div class="info-cell"><span>收货日期</span><strong>{{ receiptDate }}</strong></div><div class="info-cell"><span>经办人</span><strong>刘庆远</strong></div><div class="info-cell"><span>目标仓库</span><strong>{{ totalReceived ? warehouseLabel : '无实收，不增加库存' }}</strong></div><div class="info-cell"><span>入库状态</span><strong>已喷塑</strong></div></div>
      <DesignTable :columns="columns" :rows="rows" class="d3-confirm-lines">
        <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
        <template #cell-sent="{ row }">{{ format(row.sent) }}</template>
        <template #cell-received="{ row }"><strong class="brand">{{ format(receivedValue(row)) }}</strong></template>
        <template #cell-difference="{ row }"><strong :class="{ brand: difference(row) > 0 }">{{ format(difference(row)) }}</strong></template>
        <template #cell-reason="{ row }"><span class="cell-text" :title="row.reason">{{ difference(row) > 0 ? row.reason : '—' }}</span></template>
        <template #cell-zone="{ row }">{{ zoneLabel(row) }}</template>
      </DesignTable>
      <div class="d3-confirm-remark"><span class="muted">入库备注</span><p>{{ remark || '—' }}</p></div>
      <div class="notice warning d3-once-note"><strong>整单只登记一次。</strong> {{ totalReceived ? '仅实收大于0的部位按对应库区增加已喷塑公共库存。' : '本次实收全部为0，仅保存回货结果，不增加库存。' }}全部部位（含0支）共同结束，差额及原因保留；确认后不能追加回货或修改本次结果。</div>
    </div>
    <template #footer><div class="d3-confirm-footer"><div><span>实发 <strong>{{ format(totalSent) }}</strong> 支</span><span>实收 <strong>{{ format(totalReceived) }}</strong> 支</span><span>差额 <strong>{{ format(totalDifference) }}</strong> 支</span></div><ElButton @click="dialog = ''">返回核对</ElButton><ElButton type="primary" @click="finishReceipt">{{ totalReceived ? '确认入库并结束' : '确认结束' }}</ElButton></div></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'select'" title="选择喷塑待回货外发单" :width="1600" @update:model-value="closeDialog">
    <div class="d3-select-order"><div class="filterbar d3-picker-filter"><ElInput v-model="search" :prefix-icon="Search" placeholder="搜索外发单号、生产任务单、产品、加工厂" aria-label="搜索外发单"/><ElSelect v-model="pickerSource" clearable placeholder="全部材料来源" aria-label="筛选材料来源" popper-class="d3-select-popper"><ElOption v-for="[value, label] in sourceOptions" :key="value" :value="value" :label="label"/></ElSelect><span class="spacer"/><span class="muted">加工中 · 已实际发出 · 尚未登记整单回货</span><ElButton :icon="Refresh" @click="previewOnly('重新读取可办理的外发单列表。')">刷新</ElButton></div>
      <DesignTable :columns="pickerColumns" :rows="candidates" class="d3-picker-lines" empty="暂无符合条件的待回货外发单"><template #cell-sent="{ row }">{{ format(row.sent) }}</template><template #cell-status><span class="status info">加工中</span></template><template #cell-action="{ row }"><ElButton link :aria-label="`选择${row.number}`" @click="selectOrder(row)">选择并办理</ElButton></template></DesignTable>
    </div><template #footer><ElButton @click="dialog = ''">关闭</ElButton></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'warehouse'" title="切换目标仓库" :width="620" @update:model-value="closeDialog">
    <div class="d3-warehouse-confirm"><p>切换至<strong>{{ warehouses.find(item => item.id === pendingWarehouse)?.label }}</strong>后，各部位需要重新选择新仓库下的库区。</p><p class="muted">已填写的实收支数、差额原因和备注全部保留。</p></div><template #footer><ElButton @click="dialog = ''; pendingWarehouse = ''">保留原仓库</ElButton><ElButton type="primary" @click="confirmWarehouseChange">切换仓库</ElButton></template>
  </AppWindowDialog>
</template>
