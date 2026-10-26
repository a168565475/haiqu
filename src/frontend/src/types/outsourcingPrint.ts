export type OutsourcingPrintKind = 'processing' | 'spray'

export interface OutsourcingPrintPlanRow {
  id: string
  completed: string
  orderNumber: string
  itemNumber: string
  productName: string
  plannedQuantity: string
  color: string
  specification: string
}

export interface OutsourcingPrintMaterialRow {
  id: string
  orderNumber: string
  name: string
  unitConsumption: string
  orderQuantity: string
  issueQuantity: string
  unit: string
  specification: string
  color: string
  material: string
}

export interface OutsourcingPrintSprayRow {
  id: string
  factoryName: string
  partName: string
  specification: string
  cuttingLength: string
  unitConsumption: string
  orderQuantity: string
  totalQuantity: string
  sprayColor: string
}

export interface OutsourcingPrintDocumentData {
  kind: OutsourcingPrintKind
  title: string
  orderNumber: string
  submittedBy: string
  submittedAt: string
  updatedAt: string
  craftName: string
  factoryNames: string
  preparedBy: string
  preparedDate: string
  deliveryDate: string
  productName: string
  dispatchDate: string
  remark: string
  plans: OutsourcingPrintPlanRow[]
  materials: OutsourcingPrintMaterialRow[]
  sprayRows: OutsourcingPrintSprayRow[]
}
