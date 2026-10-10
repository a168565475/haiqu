<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Menu, Refresh, Document } from '@element-plus/icons-vue'
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

// 仅设计图：示例数量与状态切换不读取或提交业务接口。
const source = ref('PUBLIC_SEMI'), scenario = ref('mixed'), view = ref('normal'), dialog = ref(false)
const sourceOptions = [['RAW_PIPE', '原材料'], ['PUBLIC_SEMI', '未喷塑半成品'], ['METAL', '未入库半成品']]
const scenarioOptions = [['mixed', '少回及0回货'], ['full', '整单全回'], ['zero', '整单0回货']]
const viewOptions = [['normal', '正常'], ['long', '40行长表'], ['loading', '加载中'], ['missing', '凭证缺失'], ['mismatch', '历史明细缺失'], ['error', '读取失败'], ['denied', '无权限'], ['not_found', '不存在']]
const nav = [['工作台', Workbench], ['客户管理', People], ['样品管理', Box], ['产品管理', Box], ['生产管理', FactoryBuilding], ['采购管理', ShoppingCart], ['生产车间', FactoryBuilding]]
const subnav = [['生产配置', Setting], ['计划排产', ConnectionPoint], ['内部计划', FactoryBuilding], ['委外加工', Export], ['生产领料', Box], ['工价方案', Order], ['报工记录', Order]]
const sourceLabel = computed(() => sourceOptions.find(item => item[0] === source.value)[1])
const sourcePosition = computed(() => source.value === 'RAW_PIPE' ? '原料管材仓 / 一楼A区' : source.value === 'PUBLIC_SEMI' ? '半成品管材仓 / 一楼A区' : '金工车间 · 已报工未入库')
const showDetails = computed(() => ['normal', 'long', 'mismatch'].includes(view.value))
const hasOrder = computed(() => showDetails.value || view.value === 'missing')
const canReadReceipt = computed(() => showDetails.value && view.value !== 'mismatch')
const samples = [
  { id: 'front', part: '前脚管', material: '铁', specification: '20×28', thickness: '1.0', length: '415', raw_color: '本色', spray_color: '黑色', factory: '海丰喷塑加工厂', cuts: '10', raw_length: '4.20', sent: 2000, roots: 200, meters: '840.00', mixed: 1960, reason: '40支未交回，本单按实际数量结束', zone: '一楼A区' },
  { id: 'back', part: '后脚管', material: '铁', specification: '20×28', thickness: '1.0', length: '460', raw_color: '本色', spray_color: '黑色', factory: '海丰喷塑加工厂', cuts: '10', raw_length: '4.65', sent: 2000, roots: 200, meters: '930.00', mixed: 2000, reason: '', zone: '一楼A区' },
  { id: 'arm', part: '扶手管', material: '铁', specification: '20×28', thickness: '1.0', length: '505', raw_color: '本色', spray_color: '黑色', factory: '永兴喷塑加工厂', cuts: '8', raw_length: '4.09', sent: 1000, roots: 125, meters: '511.25', mixed: 960, reason: '40支未交回，本单按实际数量结束', zone: '一楼B区' },
  { id: 'support', part: '支撑管', material: '铁', specification: '20×28', thickness: '1.0', length: '550', raw_color: '本色', spray_color: '黑色', factory: '永兴喷塑加工厂', cuts: '8', raw_length: '4.45', sent: 2000, roots: 250, meters: '1112.50', mixed: 1980, reason: '20支未交回，本单按实际数量结束', zone: '一楼B区' },
  { id: 'cross', part: '横梁管', material: '铁', specification: '10×20', thickness: '1.0', length: '595', raw_color: '本色', spray_color: '黑色', factory: '永兴喷塑加工厂', cuts: '8', raw_length: '4.81', sent: 1000, roots: 125, meters: '601.25', mixed: 0, reason: '本部位未收到实物，按0支结束', zone: '' },
]
const rows = computed(() => {
  const result = samples.map(row => {
    const received = scenario.value === 'full' ? row.sent : scenario.value === 'zero' ? 0 : row.mixed
    return { ...row, received, shortage: row.sent - received,
      specification: view.value === 'mismatch' && source.value !== 'RAW_PIPE' && row.id === 'front' ? '—' : row.specification,
      reason: received === row.sent ? '' : scenario.value === 'zero' ? '本部位本次未交回，按0支一次登记结束' : row.reason,
      zone: received ? row.zone || '一楼B区' : '',
      roots: view.value === 'mismatch' && row.id === 'front' ? null : row.roots,
      meters: view.value === 'mismatch' && row.id === 'front' ? null : row.meters }
  })
  return view.value === 'long' ? Array.from({ length: 40 }, (_, index) => ({ ...result[index % result.length], id: 'long-' + index, part: '部位' + (index + 1), specification: index === 39 ? '长规格示例：圆管 Φ22／原单记录长度与截面' : result[index % result.length].specification })) : result
})
const totalSent = computed(() => rows.value.reduce((sum, row) => sum + row.sent, 0))
const totalReceived = computed(() => rows.value.reduce((sum, row) => sum + row.received, 0))
const totalShortage = computed(() => totalSent.value - totalReceived.value)
const warehouse = computed(() => totalReceived.value ? '半成品管材仓' : '未入库')
const info = [
  ['生产任务单', 'SC20260929001'], ['订单号', 'DD20260921001'], ['排产单号', 'PC20260929001'],
  ['当前订单量', '1,000 把'], ['计划发出日', '2026-09-30'], ['预计回货日', '2026-10-15'],
  ['产品名称', '组合杯托折叠椅'], ['品号', 'CP000128'], ['货号', 'HT-806'],
  ['订单颜色', '黑色'], ['建单日期', '2026-09-30'], ['建单人', '刘庆远'],
]
const receiptNumber = 'WEHK20260930001'
const meta = computed(() => [['实际发出日', '2026-09-30'], ['发出经办人', '刘庆远'], ['发出来源位置', sourcePosition.value], ['入库状态', totalReceived.value ? '已喷塑' : '未新增库存'], ['收货日期', '2026-09-30'], ['入库经办人', '陈香'], ['入库仓库', warehouse.value], ['入库凭证号', receiptNumber]])
const receiptInfo = computed(() => [['入库凭证号', receiptNumber], ['外发单号', 'WWGC20260930001'], ['生产任务单', 'SC20260929001'], ['材料来源', sourceLabel.value], ['收货日期', '2026-09-30'], ['确认时间', '2026-09-30 14:30'], ['入库经办人', '陈香'], ['入库仓库', totalReceived.value ? warehouse.value : '无实收，无需仓库']])
const columns = computed(() => {
  const raw = source.value === 'RAW_PIPE'
  const widths = raw ? [85, 60, 100, 65, 90, 65, 65, 100, 115, 115, 85, 75, 85, 85, 85, 170, 105] : [95, 65, 125, 75, 100, 85, 85, 120, 100, 100, 95, 230, 150]
  const definitions = [['part', '部位'], ['material', '材质'], ['specification', '规格'], ['thickness', '厚度 mm'], ['length', '切割长度 mm'], ['raw_color', '原料颜色'], ['spray_color', '喷塑颜色'], ['factory', '加工厂'], ...(raw ? [['cuts', '切割支数 支/根', true], ['raw_length', '原材料长度 米/根', true]] : []), ['sent', '实发（支）', true], ...(raw ? [['roots', '发出扣根', true], ['meters', '发出扣米', true]] : []), ['received', '实收（支）', true], ['shortage', '差额（支）', true], ['reason', '差额原因'], ['zone', '入库库区']]
  return definitions.map(([key, label, num], index) => ({ key, label, num: Boolean(num), width: widths[index] }))
})
const receiptRemark = computed(() => scenario.value === 'zero' ? '本次没有收到实物，全部部位按0登记，原单一次结束。' : '按各部位实际到货数量收货；少回部位原因已保留。')
function format(value) { return value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString('zh-CN') }
function resetPreview() { dialog.value = false; ElMessage.closeAll() }
function previewOnly(message) { ElMessage.closeAll(); ElMessage.info({ message: '设计演示：' + message, duration: 3500 }) }
function refresh() { view.value = 'normal'; previewOnly('仅读取原单和最终入库凭证，不产生任何库存操作。') }
function closeDialog(value) { if (!value) dialog.value = false }
</script>

<template>
  <div class="shell d4-ended-shell">
    <aside class="sidebar"><div class="brand-logo">HiTree</div><div class="nav-list">
      <div v-for="[label, icon] in nav" :key="label" class="nav-item"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
      <div v-for="[label, icon] in subnav" :key="label" class="nav-item sub" :class="{ active: label === '委外加工' }"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
      <div class="nav-item"><Truck theme="filled" size="20"/><span>仓库管理</span></div>
    </div><div class="nav-bottom"><div class="nav-item"><Setting theme="filled" size="20"/><span>系统配置</span></div></div></aside>
    <header class="topbar d4-ended-topbar"><ElIcon><Menu/></ElIcon><span class="crumb">生产车间 / 委外加工 / 管材外发单</span><span class="spacer"/><span class="preview-note">待确认设计 · 示例数据 · 未接入业务</span>
      <ElSelect v-model="source" class="source-picker" aria-label="设计材料来源" @change="resetPreview"><ElOption v-for="[value, label] in sourceOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <ElSelect v-model="scenario" class="scenario-picker" aria-label="设计回货情况" @change="resetPreview"><ElOption v-for="[value, label] in scenarioOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <ElSelect v-model="view" class="view-picker" aria-label="设计显示情况" @change="resetPreview"><ElOption v-for="[value, label] in viewOptions" :key="value" :value="value" :label="label"/></ElSelect><span class="current-user">车间管理员</span>
    </header>
    <main class="main"><section class="design-page d4-ended-page">
      <header class="page-heading"><div class="title-row"><h1>管材外发单</h1><template v-if="hasOrder"><span class="status success">已结束</span><span class="status">{{ sourceLabel }}</span><span class="d4-order-code">WWGC20260930001</span></template></div><ElButton :icon="ArrowLeft" @click="previewOnly('返回统一外发列表；列表将在下一页单独审图后接入。')">返回列表</ElButton></header>
      <template v-if="showDetails">
        <div class="panel d4-ended-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value">{{ value }}</strong></div></div></div>
        <div class="panel workspace d4-ended-workspace">
          <div class="section-heading"><div><h2>整单回货结果</h2><span class="muted">{{ totalReceived ? '已喷塑 · 全部部位保留' : '实收0支 · 未新增库存' }}</span></div><ElButton :icon="Refresh" @click="refresh">刷新</ElButton></div>
          <div class="d4-ended-meta info-grid"><div v-for="[label, value] in meta" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value">{{ value }}</strong></div></div>
          <ElAlert v-if="view === 'mismatch'" type="warning" :closable="false" show-icon title="部分原单历史明细无法完整对应，缺失字段显示“—”。请核对原凭证，不补算或补登记。"/>
          <DesignTable :columns="columns" :rows="rows" class="d4-ended-lines">
            <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
            <template #cell-sent="{ row }">{{ format(row.sent) }}</template>
            <template #cell-roots="{ row }">{{ format(row.roots) }}</template>
            <template #cell-received="{ row }"><strong class="brand">{{ format(row.received) }}</strong></template>
            <template #cell-shortage="{ row }"><strong :class="{ brand: row.shortage > 0 }">{{ format(row.shortage) }}</strong></template>
            <template #cell-reason="{ row }"><span class="cell-text" :title="row.reason || '—'">{{ row.reason || '—' }}</span></template>
            <template #cell-zone="{ row }"><span :class="{ muted: !row.received }">{{ row.received ? row.zone : '未入库' }}</span></template>
          </DesignTable>
          <div class="d4-ended-remarks"><div><span class="muted">原单备注</span><p>按本单各部位明细喷塑，分别交至对应加工厂。</p></div><div><span class="muted">入库备注</span><p>{{ receiptRemark }}</p></div></div>
        </div>
      </template>
      <div v-else class="panel d4-ended-fallback"><ElSkeleton v-if="view === 'loading'" :rows="9" animated/><template v-else><ElEmpty :description="view === 'missing' ? '原单已结束，但最终入库凭证未能读取，请刷新核对' : view === 'denied' ? '当前账号没有查看此单的权限' : view === 'not_found' ? '外发单不存在或不在当前范围' : '外发单及入库凭证读取失败，请重试'"/><ElButton v-if="['missing', 'error'].includes(view)" :icon="Refresh" @click="refresh">重新加载</ElButton></template></div>
      <footer class="footer-bar d4-ended-footer"><div class="totals"><span>实发 <strong>{{ showDetails ? format(totalSent) : '—' }}</strong> 支</span><span>实收 <strong>{{ showDetails ? format(totalReceived) : '—' }}</strong> 支</span><span>差额 <strong>{{ showDetails ? format(totalShortage) : '—' }}</strong> 支</span><small>{{ showDetails ? totalReceived ? '已结束 · 实收已入已喷塑公共库存' : '已结束 · 整单实收0支，未新增库存' : '仅读取历史结果，不办理入库' }}</small></div><ElButton type="primary" :icon="Document" :disabled="!canReadReceipt" @click="dialog = true">查看入库凭证</ElButton></footer>
    </section></main>
  </div>
  <AppWindowDialog :model-value="dialog" title="喷塑入库凭证 · 只读" :width="1640" class="d4-ended-dialog" @update:model-value="closeDialog">
    <div class="d4-ended-receipt"><div class="info-grid d4-ended-receipt-context"><div v-for="[label, value] in receiptInfo" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value">{{ value }}</strong></div></div>
      <div class="d4-ended-receipt-heading"><h2>全部部位入库结果</h2><span class="muted">{{ totalReceived ? '已喷塑' : '实收0支 · 未新增库存' }}</span></div>
      <DesignTable :columns="columns" :rows="rows" class="d4-ended-receipt-lines">
        <template #cell-sent="{ row }">{{ format(row.sent) }}</template><template #cell-roots="{ row }">{{ format(row.roots) }}</template>
        <template #cell-received="{ row }"><strong class="brand">{{ format(row.received) }}</strong></template>
        <template #cell-shortage="{ row }"><strong :class="{ brand: row.shortage > 0 }">{{ format(row.shortage) }}</strong></template>
        <template #cell-reason="{ row }"><span class="cell-text" :title="row.reason || '—'">{{ row.reason || '—' }}</span></template>
        <template #cell-zone="{ row }">{{ row.received ? row.zone : '未入库' }}</template>
      </DesignTable>
      <div class="d4-ended-receipt-remark"><span class="muted">入库备注</span><p>{{ receiptRemark }}</p></div>
    </div>
    <template #footer><div class="d4-ended-receipt-footer"><span>实发 <strong>{{ format(totalSent) }}</strong> 支</span><span>实收 <strong>{{ format(totalReceived) }}</strong> 支</span><span>差额 <strong>{{ format(totalShortage) }}</strong> 支</span><span class="spacer"/><ElButton type="primary" @click="dialog = false">关闭</ElButton></div></template>
  </AppWindowDialog>
</template>
