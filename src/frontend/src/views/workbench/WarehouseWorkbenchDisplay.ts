import inboundImage from '@/assets/purchase-workbench/due-today.png'
import purchaseImage from '@/assets/purchase-workbench/fabric.png'
import issueImage from '@/assets/purchase-workbench/shortage.png'
import dispatchImage from '@/assets/purchase-workbench/near-due.png'
import returnsImage from '@/assets/purchase-workbench/unstarted.png'
import { compactDecimal } from '@/utils/compactDecimal'
import type { WarehouseCard, WarehouseQueue, WarehouseRow } from '@/types/warehouseWorkbench'

export const queueLabels = {
  inbound: {
    title: '车间交仓待入库', short: '车间入库', link: '查看入库单', image: inboundImage,
    number: '入库单号', party: '交仓车间', date: '提交日期', required: '提交数量', done: '已确认', remaining: '待入库',
  },
  purchase: {
    title: '采购待收货', short: '采购收货', link: '查看采购单', image: purchaseImage,
    number: '采购单号', party: '供应商', date: '预计到货日', required: '订购数量', done: '已收货', remaining: '待收货',
  },
  issue: {
    title: '生产任务待发料', short: '生产发料', link: '查看待发料任务', image: issueImage,
    number: '领料单号', party: '领料车间', date: '提交日期', required: '申请数量', done: '已发料', remaining: '待发料',
  },
  dispatch: {
    title: '外发待发出', short: '外发发出', link: '查看外发单', image: dispatchImage,
    number: '外发单号', party: '加工厂', date: '计划外发日', required: '应发数量', done: '已发数量', remaining: '剩余待发',
  },
  returns: {
    title: '外发待收回', short: '外发收回', link: '查看外发单', image: returnsImage,
    number: '外发单号', party: '加工厂', date: '预计回货日', required: '应回数量', done: '累计实收', remaining: '尚待回仓',
  },
} as const

export const warehouseQueues: WarehouseQueue[] = ['inbound', 'purchase', 'issue', 'dispatch', 'returns']
export const periodLabels = { month: '本月', quarter: '本季', year: '本年' } as const

export function queueSubtitle(queue: WarehouseQueue, card: WarehouseCard) {
  if (!card.available) return '无查看权限'
  const b = card.breakdown
  switch (queue) {
    case 'inbound': return [b.semi == null ? '' : `半成品 ${b.semi} 张`, b.finished == null ? '' : `成品 ${b.finished} 张`].filter(Boolean).join(' · ')
    case 'purchase': return `其中 ${b.partial ?? 0} 张已部分收货`
    case 'issue': return `共 ${b.documents ?? 0} 张领料单待仓库审核`
    case 'dispatch': return `其中 ${b.partial ?? 0} 张已分批发出`
    case 'returns': return `${b.overdue ?? 0} 张逾期 · ${b.today ?? 0} 张今天应回`
  }
}

export function deadline(queue: WarehouseQueue, date: string | null, today: string) {
  if (!date) return '日期待定'
  const days = (Date.parse(today) - Date.parse(date)) / 86400000
  if (queue === 'purchase') return (days === 0 ? '今天' : date.slice(5).replace('-', '/')) + '应到'
  if (days > 0) return `逾期 ${days} 天`
  if (days === 0) return queue === 'returns' ? '今天应回' : '今天应发'
  return date.slice(5).replace('-', '/')
}

export function rowIdentity(row: WarehouseRow) {
  return row.task_number || row.number || '无关联生产任务'
}

export function kindLabel(row: WarehouseRow) {
  if (row.kind_label) return row.kind_label
  return row.kind === 'semi' ? '半成品' : row.kind === 'finished' ? '成品' : ''
}

export function quantity(value: string | null, unit: string) {
  return value === null ? '—' : [compactDecimal(value), unit].filter(Boolean).join(' ')
}
