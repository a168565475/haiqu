import type { BoardMetric, BoardOrder, BoardRow } from '@/types/board'

// 仅用于大屏布局演示。全部样本驻留内存，接入真实接口时集中删除本文件。
// 固定演示日与样本，不随系统日期或刷新随机变化，也不写入任何本地或服务端存储。
export const demoDate = '2026-10-16'

const products = [
  { code: 'DEMO-P-001', name: '轻量露营椅', specification: '沙色 / 铝合金架', openingStock: 1280 },
  { code: 'DEMO-P-002', name: '便携折叠桌', specification: '90 × 60 cm / 原木色', openingStock: 860 },
  { code: 'DEMO-P-003', name: '六角遮阳篷', specification: '3 × 3 m / 米白色', openingStock: 520 },
  { code: 'DEMO-P-004', name: '高背月亮椅', specification: '橄榄绿 / 加厚款', openingStock: 930 },
  { code: 'DEMO-P-005', name: '铝合金卷桌', specification: '120 × 70 cm / 黑色', openingStock: 740 },
  { code: 'DEMO-P-006', name: '庭院遮阳篷', specification: '3 × 4 m / 灰色', openingStock: 360 },
]

const processNames = ['裁切', '金工', '喷涂', '缝纫', '组装', '包装']
const orderSamples = [
  { productIndex: 0, planned: 1200, priority: '紧急', progress: [1200, 1200, 1200, 1100, 960, 800] },
  { productIndex: 1, planned: 800, priority: '优先', progress: [800, 800, 700, 680, 540, 400] },
  { productIndex: 2, planned: 1500, priority: '普通', progress: [1500, 1450, 1300, 1180, 920, 700] },
  { productIndex: 3, planned: 600, priority: '普通', progress: [600, 600, 600, 600, 600, 600] },
  { productIndex: 4, planned: 1000, priority: '优先', progress: [1000, 980, 900, 830, 600, 420] },
  { productIndex: 5, planned: 720, priority: '普通', progress: [720, 720, 720, 680, 640, 520] },
  { productIndex: 0, planned: 900, priority: '普通', progress: [900, 800, 720, 600, 450, 300] },
  { productIndex: 1, planned: 1100, priority: '紧急', progress: [1100, 1020, 960, 860, 680, 500] },
  { productIndex: 2, planned: 480, priority: '普通', progress: [480, 480, 460, 420, 300, 180] },
  { productIndex: 3, planned: 660, priority: '普通', progress: [660, 620, 580, 520, 400, 260] },
  { productIndex: 4, planned: 840, priority: '优先', progress: [840, 840, 800, 760, 660, 480] },
  { productIndex: 5, planned: 540, priority: '普通', progress: [540, 500, 440, 400, 300, 220] },
]

export const demoOrders: BoardOrder[] = orderSamples.map((sample, index) => {
  const product = products[sample.productIndex]!
  return {
    id: `DEMO-MO-${String(index + 1).padStart(3, '0')}`,
    productCode: product.code,
    product: product.name,
    specification: product.specification,
    planned: sample.planned,
    priority: sample.priority,
    processes: processNames.map((label, processIndex) => ({
      label,
      completed: sample.progress[processIndex]!,
      total: sample.planned,
    })),
  }
})

const reportSamples = [
  { orderIndex: 0, time: '10:48:12', worker: '员工A', process: '裁切', good: 336, defective: 4 },
  { orderIndex: 1, time: '10:45:36', worker: '员工B', process: '金工', good: 292, defective: 8 },
  { orderIndex: 2, time: '10:42:18', worker: '员工C', process: '缝纫', good: 410, defective: 10 },
  { orderIndex: 3, time: '10:38:42', worker: '员工D', process: '喷涂', good: 178, defective: 2 },
  { orderIndex: 4, time: '10:35:09', worker: '员工E', process: '组装', good: 250, defective: 5 },
  { orderIndex: 5, time: '10:31:24', worker: '员工F', process: '包装', good: 196, defective: 4 },
  { orderIndex: 6, time: '10:28:50', worker: '员工A', process: '金工', good: 315, defective: 5 },
  { orderIndex: 7, time: '10:25:17', worker: '员工B', process: '喷涂', good: 272, defective: 8 },
  { orderIndex: 8, time: '10:21:33', worker: '员工C', process: '缝纫', good: 232, defective: 3 },
  { orderIndex: 9, time: '10:18:46', worker: '员工D', process: '组装', good: 210, defective: 5 },
  { orderIndex: 10, time: '10:15:28', worker: '员工E', process: '包装', good: 284, defective: 6 },
  { orderIndex: 11, time: '10:12:05', worker: '员工F', process: '裁切', good: 255, defective: 5 },
]

export const workReportRows: BoardRow[] = reportSamples.map((report) => ({
  time: report.time,
  worker: report.worker,
  process: report.process,
  product: demoOrders[report.orderIndex]!.product,
  code: demoOrders[report.orderIndex]!.productCode,
  good: report.good,
  defective: report.defective,
}))

export const qualityRows: BoardRow[] = reportSamples.map((report) => ({
  time: report.time,
  worker: report.worker,
  process: report.process,
  product: demoOrders[report.orderIndex]!.product,
  reported: report.good + report.defective,
  defective: report.defective,
}))

export const taskRows: BoardRow[] = reportSamples.map((report) => ({
  order: demoOrders[report.orderIndex]!.id,
  process: report.process,
  worker: report.worker,
  planned: demoOrders[report.orderIndex]!.planned,
  good: report.good,
  defective: report.defective,
  remaining: demoOrders[report.orderIndex]!.planned - report.good - report.defective,
}))

const todayReported = reportSamples.reduce((sum, report) => sum + report.good + report.defective, 0)
const todayDefective = reportSamples.reduce((sum, report) => sum + report.defective, 0)

// 整月时间轴包含尚未发生的日期；未来值为 null，避免把未发生的数据画成零。
const reportedByDay = [0, 0, 0, 0, 1680, 2980, 320, 0, 0, 2860, 3020, 2940, 3180, 3070, 3210, todayReported]
const defectiveByDay = [0, 0, 0, 0, 38, 68, 8, 0, 0, 63, 75, 58, 72, 68, 70, todayDefective]
export const productionSamples = Array.from({ length: 31 }, (_, index) => ({
  day: `10-${String(index + 1).padStart(2, '0')}`,
  reported: reportedByDay[index] ?? null,
  defective: defectiveByDay[index] ?? null,
}))

export const defectSamples = [
  { name: '表面划伤', value: 12 },
  { name: '缝纫偏差', value: 8 },
  { name: '装配偏差', value: 7 },
  { name: '外观色差', value: 6 },
  { name: '布面起皱', value: 5 },
  { name: '涂层颗粒', value: 4 },
  { name: '钻孔毛边', value: 4 },
  { name: '尺寸公差', value: 4 },
  { name: '包装破损', value: 3 },
  { name: '标签漏贴', value: 3 },
  { name: '配件缺失', value: 2 },
  { name: '拉链卡滞', value: 2 },
  { name: '接缝松散', value: 2 },
  { name: '型材变形', value: 1 },
  { name: '粘接不牢', value: 1 },
  { name: '其他异常', value: 1 },
]

const weeklyEmployeeDefects = [64, 79, 67, 57, 68, 71]
const monthlyEmployeeDefects = [82, 101, 88, 73, 89, 87]
export const employeeRows = ['员工A', '员工B', '员工C', '员工D', '员工E', '员工F'].map((name, index) => {
  const reports = reportSamples.filter((report) => report.worker === name)
  const reported = reports.reduce((sum, report) => sum + report.good + report.defective, 0)
  const defective = reports.reduce((sum, report) => sum + report.defective, 0)
  return {
    name, reported, defective,
    weeklyDefective: defective + weeklyEmployeeDefects[index]!,
    totalDefective: defective + monthlyEmployeeDefects[index]!,
  }
}) satisfies BoardRow[]

// 人员轮播用零值占位，仅在演示数据入口添加，组件不自行补假数据；不参与指标汇总。
export const employeeDisplayRows = [
  ...employeeRows,
  ...['员工G', '员工H', '员工I', '员工J'].map(name => ({ name, reported: 0, defective: 0, weeklyDefective: 0, totalDefective: 0 })),
]

const completedOrders = demoOrders.filter((order) => order.processes.every((process) => process.completed === process.total)).length
const pendingOrders = demoOrders.filter((order) => order.processes.every((process) => process.completed === 0)).length

// 交期与逾期项的 7 / 2 / 4 仅为固定内存演示汇总，不代表真实交期规则或接口结果。
export const productionMetrics: BoardMetric[] = [
  { label: '待生产工单数', value: pendingOrders, tone: 'yellow' },
  { label: '进行中工单数', value: demoOrders.length - completedOrders - pendingOrders, tone: 'blue' },
  { label: '今日完成工单数', value: completedOrders, tone: 'green' },
  { label: '今日报工数', value: todayReported, tone: 'blue', comparison: '85 ↑' },
  { label: '今日不良品数', value: todayDefective, tone: 'red', comparison: '5 ↓' },
  { label: '今日不良品率', value: `${((todayDefective / todayReported) * 100).toFixed(2)}%`, tone: 'red', comparison: '0.21% ↓' },
  { label: '七天内待交货工单', value: 7, tone: 'green' },
  { label: '逾期工单数', value: 2, tone: 'red' },
  { label: '逾期任务数', value: 4, tone: 'red' },
]

const movementSamples = [
  { productIndex: 0, inbound: 420, outbound: 320 },
  { productIndex: 1, inbound: 260, outbound: 180 },
  { productIndex: 2, inbound: 180, outbound: 100 },
  { productIndex: 3, inbound: 300, outbound: 220 },
  { productIndex: 4, inbound: 240, outbound: 160 },
  { productIndex: 5, inbound: 120, outbound: 80 },
]

export const stockMovementRows: BoardRow[] = movementSamples.flatMap((movement, index) => {
  const product = products[movement.productIndex]!
  return [
    {
      order: `DEMO-IN-${String(index + 1).padStart(3, '0')}`,
      product: product.name,
      code: product.code,
      specification: product.specification,
      quantity: movement.inbound,
      type: '入库',
      warehouse: 'DEMO成品一库',
    },
    {
      order: `DEMO-OUT-${String(index + 1).padStart(3, '0')}`,
      product: product.name,
      code: product.code,
      specification: product.specification,
      quantity: movement.outbound,
      type: '出库',
      warehouse: 'DEMO成品一库',
    },
  ]
})

export const stockRows: BoardRow[] = products.map((product, index) => ({
  product: product.name,
  code: product.code,
  specification: product.specification,
  source: '生产入库',
  stock: product.openingStock + movementSamples[index]!.inbound - movementSamples[index]!.outbound,
}))

export const warehouseProductTotals = movementSamples.map((movement) => ({
  name: products[movement.productIndex]!.name,
  inbound: movement.inbound,
  outbound: movement.outbound,
}))

// 零值备用商品仅展示排行溢出轮播，不改变入库数量及库存汇总。
export const inboundRankingRows = [
  ...warehouseProductTotals.map(row => ({ name: row.name, value: row.inbound })),
  ...['演示备用商品A', '演示备用商品B', '演示备用商品C'].map(name => ({ name, value: 0 })),
]

const todayInbound = movementSamples.reduce((sum, movement) => sum + movement.inbound, 0)
const todayOutbound = movementSamples.reduce((sum, movement) => sum + movement.outbound, 0)

const inboundByDay = [0, 0, 0, 0, 720, 1320, 240, 0, 0, 1180, 1320, 1260, 1450, 1380, 1460, todayInbound]
const outboundByDay = [0, 0, 0, 0, 440, 820, 180, 0, 0, 920, 1040, 980, 1160, 1100, 1020, todayOutbound]
export const warehouseSamples = Array.from({ length: 31 }, (_, index) => ({
  day: `10-${String(index + 1).padStart(2, '0')}`,
  inbound: inboundByDay[index] ?? null,
  outbound: outboundByDay[index] ?? null,
}))

export const stockAgeSamples = [
  { name: '0–30 天', value: 3200 },
  { name: '31–60 天', value: 1260 },
  { name: '61–90 天', value: 520 },
  { name: '90 天以上', value: 170 },
]

export const warehouseMetrics: BoardMetric[] = [
  { label: '实时库存', value: stockRows.reduce((sum, row) => sum + Number(row.stock), 0), tone: 'yellow' },
  // 演示假设：统一库存上限 1200、下限 500；本批入出库全按采购/销售分类，退货为 0。
  { label: '超上限报警数', value: stockRows.filter((row) => Number(row.stock) > 1200).length, tone: 'red' },
  { label: '超下限报警数', value: stockRows.filter((row) => Number(row.stock) < 500).length, tone: 'red' },
  { label: '入库数量', value: todayInbound, tone: 'blue' },
  { label: '采购入库数', value: todayInbound, tone: 'green' },
  { label: '采购退货数', value: 0, tone: 'yellow' },
  { label: '出库数量', value: todayOutbound, tone: 'blue' },
  { label: '销售出库数', value: todayOutbound, tone: 'green' },
  { label: '销售退货数', value: 0, tone: 'yellow' },
]
