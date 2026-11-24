import { ElMessageBox } from 'element-plus'
import type { PurchaseGroup, VersionedPurchaseGroup } from '@/types/purchaseGroup'

export function purchaseGroupDeletionBlock(group: PurchaseGroup | null): string {
  return group?.deletion?.can_delete === true ? '' : group?.deletion?.blocked_reason || '删除条件待核对，请刷新后重试。'
}

export async function confirmPurchaseGroupDeletion(latest: VersionedPurchaseGroup): Promise<void> {
  const reason = purchaseGroupDeletionBlock(latest.data)
  if (reason) throw new Error(reason)
  if (!latest.etag) throw new Error('采购需求版本信息缺失，请刷新后重试。')
  await ElMessageBox.confirm(
    `确定彻底删除采购需求 ${latest.data.group_number} 及其未确认草稿批次吗？删除后不可恢复，可按最新 BOM 重新创建采购需求。`,
    '删除采购需求',
    { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
  )
}
