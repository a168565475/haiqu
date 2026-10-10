<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Menu, Refresh, Search, ArrowDown } from '@element-plus/icons-vue'
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

// 仅设计图。数据和切换均在浏览器中模拟，不读取或提交业务接口。
const view = ref('normal'), search = ref(''), source = ref(''), status = ref(''), craft = ref(''), factory = ref('')
const applied = ref({ search: '', source: '', status: '', craft: '', factory: '' })
const page = ref(1), pageSize = ref(50)
const views = [['normal', '正常列表'], ['long', '40行长表'], ['empty', '空列表'], ['loading', '加载中'], ['error', '读取失败'], ['denied', '无权限'], ['missing', '管材凭证缺失']]
const nav = [['工作台', Workbench], ['客户管理', People], ['样品管理', Box], ['产品管理', Box], ['生产管理', FactoryBuilding], ['采购管理', ShoppingCart], ['生产车间', FactoryBuilding]]
const subnav = [['生产配置', Setting], ['计划排产', ConnectionPoint], ['内部计划', FactoryBuilding], ['委外加工', Export], ['生产领料', Box], ['工价方案', Order], ['报工记录', Order]]
const sourceOptions = [['RAW', '原材料'], ['TUBE_PUBLIC', '未喷塑半成品'], ['TUBE_METAL', '未入库半成品'], ['OLD_METAL', '金工加工件（旧流程）'], ['REWORK', '重加工件（旧流程）'], ['UNSELECTED', '待选择（旧流程）']]
const statusOptions = [['PENDING_DISPATCH', '待外发'], ['PENDING_HANDOFF', '待交接（旧流程）'], ['PROCESSING', '加工中'], ['PARTIAL_RETURN', '部分回货（旧流程）'], ['COMPLETED', '已完成 / 已结束'], ['CLOSED', '已结清（旧流程）'], ['CANCELLED', '已取消']]
const factories = [['haifeng', '海丰喷塑加工厂'], ['yongxing', '永兴喷塑加工厂'], ['sewing', '华盛车缝加工厂']]
const columns = [
  ['number', '外发单号', 170], ['task', '生产任务单', 130], ['product', '产品名称', 155], ['product_number', '品号', 95], ['item_number', '货号', 85], ['color', '订单颜色', 75],
  ['source', '材料来源', 125], ['craft', '加工工艺', 80], ['factories', '加工厂', 135], ['sent', '发出数量', 95, true], ['received', '回货数量', 95, true], ['shortage', '管材差额', 90, true],
  ['return_date', '预计回货日', 110], ['status', '状态', 90], ['operation', '操作', 70],
].map(([key, label, width, num]) => ({ key, label, width, num: Boolean(num) }))
function line(factoryId, sent, received, unit = '支', returnUnit = unit) { return { factoryId, sent, received, unit, returnUnit } }
function tube(number, sourceValue, statusValue, receipt, lines) {
  return { key: 'TUBE:' + number, type: 'TUBE', number: 'WWGC20260930' + number, task: 'SC20260929001', product: '组合杯托折叠椅', product_number: 'CP000128', item_number: 'HT-806', color: '黑色', source: sourceValue, craft: '喷塑', status: statusValue, receipt, return_date: '2026-10-15', lines }
}
const samples = [
  tube('001', 'RAW', 'COMPLETED', true, [line('haifeng', 4000, 3960), line('yongxing', 4000, 2940)]),
  tube('002', 'TUBE_PUBLIC', 'COMPLETED', true, [line('haifeng', 2000, 2000)]),
  tube('003', 'TUBE_METAL', 'COMPLETED', true, [line('yongxing', 2000, 0)]),
  tube('004', 'RAW', 'PROCESSING', false, [line('haifeng', 4000, null)]),
  tube('005', 'TUBE_PUBLIC', 'PENDING_DISPATCH', false, [line('haifeng', 2000, null)]),
  tube('006', 'TUBE_METAL', 'CANCELLED', false, [line('yongxing', 2000, null)]),
  { key: 'ORIGINAL:007', type: 'ORIGINAL', number: 'WWJG20260923007', task: 'SC20260923001', product: '折叠休闲椅', product_number: 'CP000096', item_number: 'HT-602', color: '米色', source: 'RAW', craft: '车缝', status: 'PARTIAL_RETURN', receipt: true, return_date: '2026-10-08', lines: [line('sewing', 183.75, 120, '米', '套')] },
  { key: 'ORIGINAL:008', type: 'ORIGINAL', number: 'WWJG20260923008', task: '—', product: '—', product_number: '—', item_number: '—', color: '—', source: 'OLD_METAL', craft: '—', status: 'COMPLETED', receipt: true, return_date: '—', lines: [line('haifeng', 2000, 2000)] },
  { key: 'REWORK:009', type: 'REWORK', number: 'ZGJG20260923009', task: 'SC20260923002', product: '—', product_number: '—', item_number: '—', color: '—', source: 'REWORK', craft: '喷塑', status: 'CLOSED', receipt: true, return_date: '—', lines: [line('yongxing', 100, 90)] },
  { key: 'ORIGINAL:010', type: 'ORIGINAL', number: 'WWJG20260923010', task: 'SC20260923003', product: '组合杯托折叠椅', product_number: 'CP000128', item_number: 'HT-806', color: '黑色', source: 'UNSELECTED', craft: '喷塑', status: 'PENDING_DISPATCH', receipt: false, detail_access: 'REGULAR', direct_handoff: false, can_delete: true, can_revoke_dispatched: false, return_date: '2026-10-10', lines: [line('haifeng', null, null)] },
  { key: 'ORIGINAL:011', type: 'ORIGINAL', number: 'WWJG20260923011', task: 'SC20260923004', product: '带棚扶手椅等2款', product_number: '多款', item_number: '多款', color: '多款', source: 'RAW', craft: '喷塑', status: 'COMPLETED', receipt: true, return_date: '2026-10-08', lines: [line('haifeng', 4000, 4000)] },
  { key: 'REWORK:012', type: 'REWORK', number: 'ZGJG20260923012', task: 'SC20260923002', product: '—', product_number: '—', item_number: '—', color: '—', source: 'REWORK', craft: '喷塑', status: 'PENDING_HANDOFF', receipt: false, return_date: '—', lines: [line('yongxing', 0, 0)] },
  { key: 'ORIGINAL:013', type: 'ORIGINAL', number: 'WWJG20260923013', task: 'SC20260923005', product: '组合杯托折叠椅', product_number: 'CP000128', item_number: 'HT-806', color: '黑色', source: 'RAW', craft: '喷塑', status: 'CANCELLED', receipt: false, return_date: '2026-10-08', lines: [line('haifeng', 100, null)] },
]
const readable = computed(() => ['normal', 'long', 'empty', 'missing'].includes(view.value))
const sourceRows = computed(() => {
  if (!readable.value || view.value === 'empty') return []
  if (view.value === 'long') return Array.from({ length: 40 }, (_, i) => ({ ...samples[i % samples.length], key: samples[i % samples.length].type + ':long-' + i, number: samples[i % samples.length].number.replace(/\d{3}$/, String(i + 1).padStart(3, '0')), product: i === 39 ? '长产品名称示例：带棚组合杯托加宽扶手折叠休闲椅' : samples[i % samples.length].product }))
  if (view.value === 'missing') return [{ ...samples[0], receipt: null }]
  return samples
})
function quantities(lines, property, unitProperty) {
  const totals = new Map()
  for (const item of lines) { const value = item[property]; if (value !== null) totals.set(item[unitProperty], (totals.get(item[unitProperty]) || 0) + value) }
  return Array.from(totals, ([unit, value]) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) + ' ' + unit).join(' / ') || '—'
}
function decorate(row) {
  // 加工厂筛选只投影该厂数量，仍然展示整单状态与整单详情入口。
  const lines = applied.value.factory ? row.lines.filter(item => item.factoryId === applied.value.factory) : row.lines
  const names = [...new Set(lines.map(item => factories.find(([id]) => id === item.factoryId)?.[1] || '—'))]
  const sent = row.type === 'TUBE' && ['PENDING_DISPATCH', 'CANCELLED'].includes(row.status) ? '未发出' : quantities(lines, 'sent', 'unit')
  const received = row.type !== 'TUBE' ? quantities(lines, 'received', 'returnUnit') : row.receipt === null ? '—' : row.receipt ? quantities(lines, 'received', 'returnUnit') : row.status !== 'CANCELLED' ? '未回货' : '—'
  const shortage = row.type === 'TUBE' && row.receipt === true ? quantities(lines.map(item => ({ ...item, difference: item.sent - item.received })), 'difference', 'unit') : '—'
  return { ...row, sent, received, shortage, factories: names.length > 1 ? names[0] + '等' + names.length + '家' : names[0], factoryTitle: names.join('、'), sourceLabel: sourceOptions.find(([value]) => value === row.source)?.[1].replace('（旧流程）', '') || '—', statusLabel: row.type === 'TUBE' && row.status === 'COMPLETED' ? '已结束' : statusOptions.find(([value]) => value === row.status)?.[1].replace('（旧流程）', '').replace(' / 已结束', '') || '—' }
}
const rows = computed(() => sourceRows.value.filter(row => (!applied.value.source || applied.value.source === row.source) && (!applied.value.status || applied.value.status === row.status) && (!applied.value.craft || applied.value.craft === row.craft) && (!applied.value.factory || row.lines.some(item => item.factoryId === applied.value.factory)) && (!applied.value.search || [row.number, row.task, row.product, row.product_number, row.item_number].some(value => value.includes(applied.value.search)))).map(decorate))
const visibleRows = computed(() => rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
function applyFilters() { applied.value = { search: search.value.trim(), source: source.value, status: status.value, craft: craft.value, factory: factory.value }; page.value = 1 }
function reset() { search.value = ''; source.value = ''; status.value = ''; craft.value = ''; factory.value = ''; applyFilters(); ElMessage.closeAll() }
function changeView() { reset(); pageSize.value = 50 }
function demo(message) { ElMessage.closeAll(); ElMessage.info({ message: '设计演示：' + message, duration: 3500 }) }
function detail(row) { demo(row.type === 'TUBE' ? '进入新管材整单详情；回货登记仍按整单一次办理。' : '沿用该历史单原有详情和操作。') }
function canRemoveOld(row) { return row.type === 'ORIGINAL' && row.detail_access === 'REGULAR' && !row.direct_handoff && row.source !== 'OLD_METAL' && (row.can_delete || row.can_revoke_dispatched) }
function statusClass(row) { return row.status === 'COMPLETED' ? 'success' : ['CANCELLED', 'CLOSED'].includes(row.status) ? 'neutral' : ['PROCESSING', 'PARTIAL_RETURN'].includes(row.status) ? 'warning' : '' }
</script>

<template>
  <div class="shell d4-list-shell">
    <aside class="sidebar"><div class="brand-logo">HiTree</div><div class="nav-list">
      <div v-for="[label, icon] in nav" :key="label" class="nav-item"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
      <div v-for="[label, icon] in subnav" :key="label" class="nav-item sub" :class="{ active: label === '委外加工' }"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
      <div class="nav-item"><Truck theme="filled" size="20"/><span>仓库管理</span></div>
    </div><div class="nav-bottom"><div class="nav-item"><Setting theme="filled" size="20"/><span>系统配置</span></div></div></aside>
    <header class="topbar"><ElIcon><Menu/></ElIcon><span class="crumb">生产车间 / 委外加工</span><span class="spacer"/><span class="preview-note">待确认设计 · 示例数据 · 未接入业务</span>
      <ElSelect v-model="view" class="view-picker" aria-label="设计显示情况" @change="changeView"><ElOption v-for="[value, label] in views" :key="value" :value="value" :label="label"/></ElSelect><span>车间管理员</span>
    </header>
    <main class="main"><section class="design-page d4-list-page">
      <header class="page-heading"><div class="title-row"><h1>委外加工</h1><span class="muted">统一查看外发与回货</span></div><div class="actions"><ElButton @click="demo('沿用加工厂管理。')">加工厂管理</ElButton><ElButton :disabled="view === 'denied'" @click="demo('沿用现有外发创建入口，本次不删除历史流程。')">新建外发单</ElButton><ElButton type="primary" :disabled="view === 'denied'" @click="demo('打开已确认的新建管材外发单页面。')">新建管材外发单</ElButton></div></header>
      <div class="tabs"><button class="tab active" type="button">外发单 <span class="tab-count">{{ readable ? rows.length : '—' }}</span></button><button class="tab" type="button" @click="demo('待外发材料沿用已有页面，不属于本次列表改动。')">待外发材料</button></div>
      <div class="filterbar d4-list-filters">
        <ElInput v-model="search" class="search" clearable aria-label="搜索外发单" placeholder="外发单号、任务单、产品名称、品号、货号" @keyup.enter="applyFilters"/>
        <ElSelect v-model="source" clearable placeholder="全部材料来源" aria-label="材料来源"><ElOption v-for="[value, label] in sourceOptions" :key="value" :value="value" :label="label"/></ElSelect>
        <ElSelect v-model="status" clearable placeholder="全部状态" aria-label="状态"><ElOption v-for="[value, label] in statusOptions" :key="value" :value="value" :label="label"/></ElSelect>
        <ElSelect v-model="craft" clearable placeholder="全部工艺" aria-label="加工工艺"><ElOption label="喷塑" value="喷塑"/><ElOption label="车缝" value="车缝"/><ElOption label="丝印" value="丝印"/></ElSelect>
        <ElSelect v-model="factory" class="factory-picker" clearable placeholder="全部加工厂" aria-label="加工厂"><ElOption v-for="[value, label] in factories" :key="value" :value="value" :label="label"/></ElSelect>
        <ElButton type="primary" :icon="Search" :disabled="view === 'denied' || view === 'loading'" @click="applyFilters">查询</ElButton><ElButton :disabled="view === 'denied' || view === 'loading'" @click="reset">重置</ElButton>
      </div>
      <div class="toolbar d4-list-toolbar"><h2>外发单明细</h2><span v-if="applied.factory" class="factory-note">数量仅含所选加工厂 · 状态仍为整单</span><span class="spacer"/><ElButton :icon="Refresh" :disabled="view === 'loading'" @click="demo('重新读取列表，不执行发料或入库。')">刷新</ElButton></div>
      <div class="d4-list-frame">
        <div class="d4-list-table-area">
          <ElTable :data="visibleRows" row-key="key" border height="100%" class="d4-list-table" :tooltip-options="{ placement: 'top' }" @row-click="detail">
            <ElTableColumn v-for="column in columns" :key="column.key" :prop="column.key" :label="column.label" :width="column.key === 'product' ? undefined : column.width" :min-width="column.key === 'product' ? column.width : undefined" :align="column.num ? 'right' : 'left'" :class-name="column.num ? 'num' : ''" :show-overflow-tooltip="!['source', 'craft', 'status', 'operation'].includes(column.key)">
              <template #header><ElTooltip v-if="column.key === 'received'" content="新管材按最终实收支数；其他外发沿用原合格回货口径。" placement="top"><span>{{ column.label }}</span></ElTooltip><ElTooltip v-else-if="column.key === 'shortage'" content="只显示新管材最终登记后的实发减实收。面料等不同单位不相减。" placement="top"><span>{{ column.label }}</span></ElTooltip><span v-else>{{ column.label }}</span></template>
              <template #default="{ row }">
                <span v-if="column.key === 'source'" class="source-tag" :title="row.type === 'TUBE' ? row.sourceLabel : row.sourceLabel + '（旧流程）'">{{ row.sourceLabel }}</span>
                <span v-else-if="column.key === 'craft' && row.craft !== '—'" class="craft-tag" :class="row.craft === '喷塑' ? 'spray' : 'sewing'">{{ row.craft }}</span>
                <span v-else-if="column.key === 'status'" class="status" :class="statusClass(row)">{{ row.statusLabel }}</span>
                <div v-else-if="column.key === 'operation'" class="cell-actions" @click.stop><ElButton v-if="row.type === 'TUBE'" link type="primary" @click="detail(row)">查看</ElButton><ElDropdown v-else trigger="click" placement="bottom-end" @command="demo('沿用历史单原有菜单；新管材不显示这些操作。')"><ElButton link type="primary">更多<ElIcon><ArrowDown/></ElIcon></ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem command="detail">查看详情</ElDropdownItem><ElDropdownItem v-if="canRemoveOld(row)" command="remove" divided>{{ row.can_delete ? '删除' : '撤销并退料' }}</ElDropdownItem></ElDropdownMenu></template></ElDropdown></div>
                <span v-else-if="column.key === 'factories'" :title="row.factoryTitle">{{ row.factories }}</span>
                <ElTooltip v-else-if="row.receipt === null && ['received', 'shortage'].includes(column.key)" content="已结束，但最终凭证尚无法核对；不当作0回货。" placement="top"><span class="muted">—</span></ElTooltip>
                <span v-else :class="{ 'brand': column.key === 'shortage' && row.shortage !== '—' && !row.shortage.startsWith('0 '), 'muted': ['未发出', '未回货', '—', '多款'].includes(row[column.key]) }">{{ row[column.key] }}</span>
              </template>
            </ElTableColumn>
            <template #empty><div class="d4-list-empty"><template v-if="view === 'loading'"><ElIcon class="is-loading"><Refresh/></ElIcon><strong>正在读取外发单</strong><span>读取完成后显示数量与状态</span></template><template v-else-if="view === 'error'"><strong>外发单读取失败</strong><span>请重试，尚未取得的数量不显示为0</span><ElButton @click="view = 'normal'">重新读取</ElButton></template><template v-else-if="view === 'denied'"><strong>暂无查看外发单权限</strong><span>请联系管理员核对权限</span></template><template v-else><strong>{{ applied.search || applied.source || applied.status || applied.craft || applied.factory ? '没有符合条件的外发单' : '暂无外发单' }}</strong><span>可调整筛选条件或新建外发单</span></template></div></template>
          </ElTable>
        </div>
        <div class="pager d4-list-pager"><span>{{ readable ? '共 ' + rows.length + ' 条' : '数量待读取' }}</span><template v-if="readable"><ElSelect v-model="pageSize" aria-label="每页条数" @change="page = 1"><ElOption :value="20" label="20 条 / 页"/><ElOption :value="50" label="50 条 / 页"/></ElSelect><ElPagination v-model:current-page="page" :page-size="pageSize" :total="rows.length" layout="prev, pager, next" background/></template><span v-else class="muted">页数 —</span></div>
      </div>
    </section></main>
  </div>
</template>
