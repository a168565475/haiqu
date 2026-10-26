import type { OutsourcingOrderDetail } from '@/types/outsourcing'
import type { OutsourcingPrintDocumentData, OutsourcingPrintKind } from '@/types/outsourcingPrint'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'

function value(value: string | number | null | undefined): string {
  return value == null || String(value).trim() === '' ? '—' : String(value).trim()
}

function dateTime(input: string | undefined): string {
  if (!input) return '—'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(date)
}

export function buildRegularPrintDocument(detail: OutsourcingOrderDetail): OutsourcingPrintDocumentData {
  const createdAt = dateTime(detail.created_at)
  return {
    kind: 'processing', title: '委外加工单', orderNumber: value(detail.order_number),
    submittedBy: value(detail.created_by?.name), submittedAt: createdAt, updatedAt: dateTime(detail.updated_at),
    craftName: value(detail.craft.name), factoryNames: value(detail.factory_names.join('、')),
    preparedBy: value(detail.created_by?.name), preparedDate: createdAt.slice(0, 10), deliveryDate: value(detail.delivery_date),
    productName: value([...new Set(detail.products.map(row => row.product.product_name).filter(Boolean))].join('、')),
    dispatchDate: '—', remark: detail.remark || '',
    plans: detail.products.map(product => ({
      id: product.id, completed: detail.status === 'COMPLETED' ? '是' : '否', orderNumber: value(detail.sales_order_number),
      itemNumber: value(product.product.item_number || product.product.product_number), productName: value(product.product.product_name),
      plannedQuantity: value(product.planned_quantity), color: value(product.product.color_name), specification: value(product.product.specification),
    })),
    materials: detail.products.flatMap(product => product.processing_items.flatMap(item => item.allocations.flatMap(allocation =>
      allocation.materials.map(material => ({
        id: material.id, orderNumber: value(detail.sales_order_number), name: value(material.name),
        unitConsumption: value(material.unit_consumption), orderQuantity: value(product.order_quantity),
        issueQuantity: value(material.planned_issue_quantity), unit: value(material.unit),
        specification: value(material.specification), color: value(material.color), material: value(material.material),
      })),
    ))),
    sprayRows: [],
  }
}

export function buildTubePrintDocument(detail: TubeOrderDetail, kind: OutsourcingPrintKind): OutsourcingPrintDocumentData {
  const createdAt = dateTime(detail.created_at)
  const orderNumber = value(detail.task_order_number)
  const materials = detail.materials || []
  const factoryNames = [...new Set([...detail.lines, ...materials].map(row => row.factory_name).filter(Boolean))]
  const isCutting = detail.category === 'cutting' || ['PUBLIC_CUTTING', 'SEWING'].includes(detail.source_kind)
  const outputUnit = detail.output_unit || (isCutting ? '套' : '支')
  return {
    kind, title: kind === 'spray' ? `${orderNumber}单 嗨趣休闲用品有限公司喷塑计划` : '委外加工单',
    orderNumber: value(detail.order_number), submittedBy: value(detail.created_by_name), submittedAt: createdAt,
    updatedAt: dateTime(detail.updated_at), craftName: value(detail.craft_name), factoryNames: value(factoryNames.join('、')),
    preparedBy: value(detail.created_by_name), preparedDate: createdAt.slice(0, 10), deliveryDate: value(detail.expected_return_date),
    productName: value(detail.product_name), dispatchDate: value(detail.actual_dispatch_date || detail.planned_dispatch_date), remark: detail.remark || '',
    plans: [{
      id: detail.schedule_product_id, completed: detail.status === 'COMPLETED' ? '是' : '否', orderNumber,
      itemNumber: value(detail.item_number || detail.product_number), productName: value(detail.product_name),
      plannedQuantity: value(detail.planned_quantity), color: value(detail.color), specification: value(detail.specification),
    }],
    materials: [
      ...detail.lines.map(line => ({
        id: line.id, orderNumber, name: value(line.part_name), unitConsumption: value(line.pieces_per_product),
        orderQuantity: value(detail.quantity), issueQuantity: value(line.quantity), unit: outputUnit,
        specification: value(line.specification) + (!isCutting && value(line.cutting_length_mm) !== '—' ? ` × ${value(line.cutting_length_mm)}mm` : ''),
        color: value(line.raw_color), material: value(line.material),
      })),
      ...materials.map(material => ({
        id: material.id, orderNumber, name: value(material.name), unitConsumption: value(material.unit_consumption),
        orderQuantity: value(detail.quantity), issueQuantity: value(material.quantity), unit: value(material.unit),
        specification: value(material.specification), color: value(material.color), material: value(material.material),
      })),
    ],
    sprayRows: detail.lines.map(line => ({
      id: line.id, factoryName: value(line.factory_name), partName: value(line.part_name),
      specification: value(line.tube_diameter || line.specification), cuttingLength: value(line.cutting_length_mm),
      unitConsumption: value(line.pieces_per_product), orderQuantity: value(detail.quantity), totalQuantity: value(line.quantity), sprayColor: value(line.spray_color),
    })),
  }
}
