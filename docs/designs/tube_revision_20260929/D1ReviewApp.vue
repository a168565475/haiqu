<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Document, Menu, Refresh } from '@element-plus/icons-vue'
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

// 独立审图原型：仅示例数据，不读取或写入任何业务接口。
const state = ref('normal')
const states = [['normal', '正常填写'], ['empty', '无管材明细'], ['loading', '读取中'], ['error', '读取失败'], ['forbidden', '无入库权限'], ['future', '后续工价约束'], ['pending', '提交结果待核对']]
const date = ref('2026-09-29'), warehouse = ref('W1'), zone = ref('Z1'), remark = ref('')
const warehouses = [{ id: 'W1', name: '半成品管材仓', zones: [{ id: 'Z1', name: '一楼 A区' }, { id: 'Z2', name: '一楼 B区' }] }, { id: 'W2', name: '半成品备用仓', zones: [{ id: 'Z3', name: '二楼 A区' }] }]
const zones = computed(() => warehouses.find(item => item.id === warehouse.value)?.zones || [])
const warehouseName = computed(() => warehouses.find(item => item.id === warehouse.value)?.name || '—')
const zoneName = computed(() => zones.value.find(item => item.id === zone.value)?.name || '—')
const nav = [['工作台', Workbench], ['客户管理', People], ['样品管理', Box], ['产品管理', Box], ['生产管理', FactoryBuilding], ['采购管理', ShoppingCart], ['生产车间', ConnectionPoint]]
const subnav = [['生产配置', Setting], ['计划排产', Workbench], ['内部计划', FactoryBuilding], ['委外加工', Export], ['生产领料', Truck], ['工价方案', Box], ['报工记录', Order]]
const info = [['生产任务单号', 'SC20260929001'], ['排产单号', 'PC20260929001'], ['订单量', '1,000 把'], ['订单喷塑色', '黑色'], ['入库人', '当前仓管'], ['产品名称', '组合杯托折叠椅'], ['品号', 'CP000128'], ['货号', 'HT-806'], ['入库来源', '厂内金工'], ['加工状态', '未喷塑']]
const rows = ref([
  { id: 'front', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8', length: '650', color: '原料本色', usage: 2, required: 2000, issued: 1800, received: 400, sent: 200, reserved: 100, quantity: '300', operations: [{ name: '弯管', amount: 1400 }, { name: '冲孔', amount: 1200 }] },
  { id: 'rear', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8', length: '720', color: '原料本色', usage: 2, required: 2000, issued: 1600, received: 200, sent: 300, reserved: 0, quantity: '200', operations: [{ name: '弯管', amount: 1000 }, { name: '冲孔', amount: 1200 }] },
  { id: 'arm', part: '扶手管', material: 'Q195', spec: '椭圆管 30×15', thickness: '0.9', length: '520', color: '原料本色', usage: 2, required: 2000, issued: 600, received: 400, sent: 0, reserved: 0, quantity: '', operations: [{ name: '弯管', amount: 800 }, { name: '冲孔', amount: 900 }] },
  { id: 'join', part: '连接管', material: 'Q195', spec: '圆管 Φ16', thickness: '0.7', length: '360', color: '原料本色', usage: 4, required: 4000, issued: 1200, received: 0, sent: 0, reserved: 0, quantity: '', operations: [], missing: '未找到连接管当前适用且已批准的工价方案，请先完善工价方案。' },
  { id: 'back', part: '靠背管', material: 'Q195', spec: '圆管 Φ19', thickness: '0.8', length: '880', color: '原料本色', usage: 2, required: 2000, issued: 800, received: 0, sent: 0, reserved: 0, quantity: '', operations: [{ name: '弯管', amount: 0 }, { name: '冲孔', amount: 200 }] },
])
function minimum(row) { return row.missing ? null : Math.min(...row.operations.map(item => item.amount)) }
function capacity(row) { return row.missing ? 0 : Math.max(0, Math.min(row.required, row.issued, minimum(row)) - row.received - row.sent - row.reserved) }
const visibleRows = computed(() => state.value === 'empty' ? [] : rows.value)
const columns = [
  ['part', '部位', 90], ['material', '材质', 60], ['spec', '规格', 120], ['thickness', '厚度 mm', 70], ['length', '切割长度 mm', 100], ['color', '原料颜色', 85], ['usage', '单耗 支/把', 80, true], ['required', '订单需求', 90, true], ['issued', '实领投入', 90, true], ['minimum', '最低报工', 100, true], ['received', '已入库', 80, true], ['sent', '已直发', 80, true], ['reserved', '待发预留', 90, true], ['available', '可入库', 90, true], ['quantity', '本次入库（支）', 140],
].map(([key, label, width, num]) => ({ key, label, width, num }))
const operationColumns = [{ key: 'name', label: '必需工序', width: 250 }, { key: 'amount', label: '有效累计报工（支）', width: 240, num: true }, { key: 'basis', label: '完成依据', width: 250 }]
const confirmColumns = [['part', '部位', 120], ['spec', '规格', 150], ['thickness', '厚度 mm', 90], ['length', '切割长度 mm', 120], ['color', '原料颜色', 120], ['available', '本次可入（支）', 120, true], ['quantity', '本次入库（支）', 130, true]].map(([key, label, width, num]) => ({ key, label, width, num }))
const entered = computed(() => visibleRows.value.filter(row => /^\d+$/.test(row.quantity.trim()) && Number.isSafeInteger(Number(row.quantity)) && Number(row.quantity) > 0))
const total = computed(() => entered.value.reduce((sum, row) => sum + Number(row.quantity), 0))
const dialog = ref(''), selectedPart = ref(rows.value[0])
const formLocked = computed(() => state.value !== 'normal')
const showForm = computed(() => !['loading', 'error', 'forbidden'].includes(state.value))
const format = value => value === null ? '—' : Number(value).toLocaleString('zh-CN')
function warn(message) { ElMessage.closeAll(); ElMessage.warning({ message, duration: 4500 }) }
function previewOnly(message) { ElMessage.info({ message: message || '此处为待确认设计预览，未登记库存。', duration: 3500 }) }
function openBasis(row) { selectedPart.value = row; dialog.value = 'basis' }
function validQuantity(row) {
  const value = row.quantity.trim()
  if (!value) return true
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) { warn(`${row.part}：请填写整数支数，不支持负数、小数或文字。`); return false }
  if (Number(value) > capacity(row)) { warn(`${row.part}：本次最多可入 ${format(capacity(row))} 支。`); return false }
  return true
}
function confirmReceipt() {
  if (state.value === 'pending') { previewOnly('正式页面将核对原请求的入库结果，避免重复入库。此处不请求业务接口。'); return }
  if (formLocked.value) return
  for (const row of rows.value) if (!validQuantity(row)) return
  if (!entered.value.length) { warn('请至少填写一项大于 0 的本次入库数量。'); return }
  if (!date.value || !warehouse.value || !zone.value) { warn('请选择收货日期、材料仓和库区。'); return }
  dialog.value = 'confirm'
}
function reset() { rows.value.forEach(row => { row.quantity = '' }); ElMessage.closeAll() }
function changeState() { dialog.value = ''; ElMessage.closeAll() }
</script>

<template>
  <div class="shell d1-shell">
    <aside class="sidebar">
      <div class="brand-logo">HiTree</div>
      <div class="nav-list">
        <div v-for="[label, icon] in nav" :key="label" class="nav-item"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
        <div v-for="[label, icon] in subnav" :key="label" class="nav-item sub" :class="{ active: label === '内部计划' }"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
        <div class="nav-item"><Truck theme="filled" size="20"/><span>仓库管理</span></div>
      </div>
      <div class="nav-bottom"><div class="nav-item"><Setting theme="filled" size="20"/><span>系统配置</span></div></div>
    </aside>
    <header class="topbar"><ElIcon><Menu/></ElIcon><span class="crumb">生产车间 / 内部计划 / 金工 / 半成品入库</span><span class="spacer"/><span class="preview-note">待确认设计 · 示例数据 · 未接入业务</span><ElSelect v-model="state" class="design-picker" aria-label="设计状态" @change="changeState"><ElOption v-for="[value, label] in states" :key="value" :value="value" :label="label"/></ElSelect><span>仓库管理员</span></header>
    <main class="main">
      <section class="design-page d1-page">
        <header class="page-heading"><div class="title-row"><h1>半成品入库</h1><span class="status info">厂内金工</span></div><ElButton :icon="Document" @click="previewOnly('正式页面沿用现有半成品入库记录入口。')">入库记录</ElButton></header>
        <ElAlert v-if="state === 'future'" type="warning" :closable="false" show-icon title="已批准的后续工价方案无法覆盖本次入库数量，请先核对工价方案和报工记录。"/>
        <ElAlert v-if="state === 'pending'" type="warning" :closable="false" show-icon title="提交结果尚未确认，请点击“核对本次提交”，避免重复入库。"/>
        <template v-if="showForm">
          <div class="panel d1-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :class="{ brand: label === '加工状态' }">{{ value }}</strong></div></div></div>
          <div class="panel workspace d1-workspace">
            <div class="section-heading"><div><h2>本次入库</h2><span class="muted">填写数量即可办理 · 数量单位：支</span></div><ElButton :icon="Refresh" :disabled="formLocked" @click="previewOnly('正式页面将重新读取当前额度；本页仅展示设计。')">刷新</ElButton></div>
            <div class="field-grid d1-fields">
              <label class="form-field required"><span>收货日期</span><ElDatePicker v-model="date" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper" placeholder="选择日期" aria-label="收货日期" :disabled="formLocked"/></label>
              <label class="form-field required"><span>材料仓</span><ElSelect v-model="warehouse" aria-label="材料仓" :disabled="formLocked" @change="zone = ''"><ElOption v-for="item in warehouses" :key="item.id" :value="item.id" :label="item.name"/></ElSelect></label>
              <label class="form-field required"><span>库区</span><ElSelect v-model="zone" aria-label="库区" placeholder="请选择库区" :disabled="formLocked"><ElOption v-for="item in zones" :key="item.id" :value="item.id" :label="item.name"/></ElSelect></label>
              <label class="form-field"><span>加工状态</span><ElInput model-value="未喷塑" aria-label="加工状态" disabled/></label>
            </div>
            <DesignTable :columns="columns" :rows="visibleRows" class="d1-lines" empty="此金工计划暂无管材明细">
              <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
              <template #cell-required="{ row }">{{ format(row.required) }}</template>
              <template #cell-issued="{ row }">{{ format(row.issued) }}</template>
              <template #cell-minimum="{ row }"><ElTooltip :content="row.missing || '点击查看必需工序和可入库数量依据'" placement="top"><ElButton link :aria-label="`${row.part}最低报工`" @click="openBasis(row)">{{ row.missing ? '— 查看原因' : format(minimum(row)) }}</ElButton></ElTooltip></template>
              <template #cell-received="{ row }">{{ format(row.received) }}</template>
              <template #cell-sent="{ row }">{{ format(row.sent) }}</template>
              <template #cell-reserved="{ row }">{{ format(row.reserved) }}</template>
              <template #cell-available="{ row }"><strong :class="capacity(row) > 0 ? 'brand' : 'muted'">{{ row.missing ? '—' : format(capacity(row)) }}</strong></template>
              <template #cell-quantity="{ row }"><ElInput v-model="row.quantity" :aria-label="`${row.part}本次入库`" inputmode="numeric" :placeholder="row.missing ? '依据不完整' : capacity(row) ? '填写数量' : '暂无可入'" :disabled="formLocked || !capacity(row)" @blur="validQuantity(row)"><template v-if="capacity(row) > 0" #suffix><span class="d1-unit">支</span></template></ElInput></template>
            </DesignTable>
            <label class="form-field d1-remark"><span>入库备注 <small class="muted">选填</small></span><ElInput v-model="remark" type="textarea" :rows="3" maxlength="2000" :disabled="formLocked" placeholder="填写本次收货或存放说明" aria-label="入库备注"/></label>
          </div>
        </template>
        <div v-else class="panel d1-fallback">
          <ElSkeleton v-if="state === 'loading'" :rows="9" animated/>
          <template v-else-if="state === 'error'"><ElEmpty description="入库资料读取失败，请重试"/><ElButton :icon="Refresh" @click="state = 'normal'">重新加载</ElButton></template>
          <ElEmpty v-else description="当前账号没有半成品入库权限，请联系管理员"/>
        </div>
        <footer class="footer-bar"><div>本次入库 <strong>{{ showForm ? format(total) : '—' }}</strong> 支 <span v-if="showForm" class="muted"> · {{ entered.length }} 个部位</span><small>确认后增加未喷塑公共半成品库存</small></div><ElButton :icon="ArrowLeft" @click="previewOnly('正式页面返回内部计划，继续沿用产品行“更多 → 半成品入库”入口。')">返回</ElButton><ElButton :icon="Refresh" :disabled="formLocked" @click="reset">重填</ElButton><ElButton type="primary" :disabled="formLocked && state !== 'pending'" @click="confirmReceipt">{{ state === 'pending' ? '核对本次提交' : '确认入库' }}</ElButton></footer>
      </section>
    </main>
  </div>

  <AppWindowDialog :model-value="dialog === 'basis'" :title="`${selectedPart.part} · 加工完成依据`" :width="960" @update:model-value="value => !value && (dialog = '')">
    <div class="d1-basis">
      <ElAlert v-if="selectedPart.missing" type="warning" :closable="false" show-icon :title="selectedPart.missing"/>
      <template v-else>
        <div class="info-grid d1-basis-info"><div class="info-cell"><span>已批准方案</span><strong>GJ20260928001 · V2</strong></div><div class="info-cell"><span>生效日期</span><strong>2026-09-28</strong></div><div class="info-cell"><span>核算截至</span><strong>2026-09-29</strong></div></div>
        <DesignTable :columns="operationColumns" :rows="selectedPart.operations" class="d1-operations"><template #cell-amount="{ row }">{{ format(row.amount) }}</template><template #cell-basis="{ row }"><span v-if="row.amount === minimum(selectedPart)" class="status info">{{ row.amount === 0 ? '尚未报工 · 最低值' : '最低值' }}</span><span v-else class="muted">已累计</span></template></DesignTable>
        <p class="muted d1-basis-note">按本生产任务产品的同一部位、同一工序，累计不同人员和日期的有效报工。</p>
        <div class="d1-cap-grid"><div><span>订单净需求</span><strong>{{ format(selectedPart.required) }} <small>支</small></strong></div><div><span>实领投入</span><strong>{{ format(selectedPart.issued) }} <small>支</small></strong></div><div><span>最低报工</span><strong>{{ format(minimum(selectedPart)) }} <small>支</small></strong></div><div class="d1-cap-result"><span>三项取小 · 首次产出上限</span><strong>{{ format(Math.min(selectedPart.required, selectedPart.issued, minimum(selectedPart))) }} <small>支</small></strong></div></div>
        <div class="d1-cap-grid d1-occupied"><div><span>减：已首次入库</span><strong>{{ format(selectedPart.received) }} <small>支</small></strong></div><div><span>减：已直接发出</span><strong>{{ format(selectedPart.sent) }} <small>支</small></strong></div><div><span>减：有效待发预留</span><strong>{{ format(selectedPart.reserved) }} <small>支</small></strong></div><div class="d1-cap-result"><span>本次最多可入</span><strong class="brand">{{ format(capacity(selectedPart)) }} <small>支</small></strong></div></div>
        <p class="muted d1-basis-note">入库与加工件直接外发共用该部位额度；半成品后续领走或外发，不恢复首次产出额度。</p>
      </template>
    </div>
    <template #footer><ElButton type="primary" @click="dialog = ''">我知道了</ElButton></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'confirm'" title="确认半成品入库" :width="1120" @update:model-value="value => !value && (dialog = '')">
    <div class="d1-confirm">
      <div class="info-grid"><div class="info-cell"><span>收货日期</span><strong>{{ date }}</strong></div><div class="info-cell"><span>材料仓</span><strong>{{ warehouseName }}</strong></div><div class="info-cell"><span>库区</span><strong>{{ zoneName }}</strong></div><div class="info-cell"><span>生产任务单号</span><strong>SC20260929001</strong></div><div class="info-cell"><span>产品</span><strong>组合杯托折叠椅</strong></div><div class="info-cell"><span>加工状态</span><strong>未喷塑</strong></div></div>
      <DesignTable :columns="confirmColumns" :rows="entered" class="d1-confirm-lines"><template #cell-available="{ row }">{{ format(capacity(row)) }}</template><template #cell-quantity="{ row }"><strong class="brand">{{ format(row.quantity) }}</strong></template></DesignTable>
      <p v-if="remark" class="d1-confirm-remark"><span class="muted">入库备注：</span>{{ remark }}</p>
      <div class="d1-confirm-total">本次入库 <strong class="brand">{{ format(total) }}</strong> 支 · {{ entered.length }} 个部位</div>
      <p class="muted d1-basis-note">确认后增加未喷塑公共半成品库存，已领原料不重复扣减。</p>
    </div>
    <template #footer><ElButton @click="dialog = ''">返回修改</ElButton><ElButton type="primary" @click="dialog = ''; previewOnly()">确认入库</ElButton></template>
  </AppWindowDialog>
</template>
