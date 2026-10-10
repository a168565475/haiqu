import { shallowRef } from 'vue'
import type { SupplierPurchaseSheetStatus } from '@/types/purchaseOrder'

// 仅用于当前采购表的面包屑，权限和业务状态仍以页面接口为准。
export const purchaseSheetPageStatus = shallowRef<{ id: string; status: SupplierPurchaseSheetStatus } | null>(null)
