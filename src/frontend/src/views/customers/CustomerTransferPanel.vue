<script setup lang="ts">
import type {
  CustomerDetail,
  CustomerOptions,
  CustomerSummary,
  CustomerTransferRequest,
} from '@/types/customer'

interface TransferForm {
  ownerId: string
  reason: string
  taskPolicy: string
}

const props = defineProps<{
  customer: CustomerDetail
  summary: CustomerSummary | null
  options: CustomerOptions | null
  transferForm: TransferForm
  transferRequests: CustomerTransferRequest[]
  transferLoading: boolean
  canTransfer: boolean
  canApproveTransfer: boolean
  canCancelTransfer: (item: CustomerTransferRequest) => boolean
  formatDate: (value: string | null | undefined) => string
}>()

const emit = defineEmits<{
  cancel: []
  submit: []
  decide: [item: CustomerTransferRequest, action: 'approve' | 'reject' | 'cancel']
}>()
</script>

<template>
  <main class="transfer-page erp-glass-list">
    <header class="section-heading erp-list-surface">
      <div>
        <h2>客户转移申请</h2>
        <p>转移客户归属，不修改历史订单和财务事实。</p>
      </div>
      <ElButton class="erp-button-motion" @click="emit('cancel')">取消</ElButton>
    </header>

    <section class="transfer-grid">
      <ElCard shadow="never">
        <template #header><strong>转移设置</strong></template>
        <ElAlert :title="`当前负责人：${props.customer.primary_owner?.display_name || '未分配'}`" type="info" :closable="false" />
        <ElForm label-position="top">
          <ElFormItem label="接收人" required>
            <ElSelect v-model="props.transferForm.ownerId" filterable>
              <ElOption
                v-for="owner in props.options?.owner_options.filter((item) => item.id !== props.customer.primary_owner?.id)"
                :key="owner.id"
                :label="owner.display_name"
                :value="owner.id"
              />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="转移原因" required>
            <ElInput v-model="props.transferForm.reason" type="textarea" :rows="4" maxlength="2000" />
          </ElFormItem>
          <ElCheckbox checked disabled>通知原负责人和接收人</ElCheckbox>
        </ElForm>
        <ElButton type="primary" :loading="props.transferLoading" :disabled="!props.canTransfer" @click="emit('submit')">预览并提交</ElButton>
      </ElCard>

      <ElCard shadow="never">
        <template #header><strong>关联对象影响</strong></template>
        <ElDescriptions :column="1" border>
          <ElDescriptionsItem label="联系人">{{ props.summary?.counts.contacts || 0 }} 个，保持归属客户不变</ElDescriptionsItem>
          <ElDescriptionsItem label="进行中询价">{{ props.summary?.counts.open_inquiries || 0 }} 个，自动归属接收人可见范围</ElDescriptionsItem>
          <ElDescriptionsItem label="有效报价">{{ props.summary?.counts.open_quotations || 0 }} 个，历史版本不改写</ElDescriptionsItem>
          <ElDescriptionsItem label="样品跟进">{{ props.summary?.counts.active_samples || 0 }} 个，状态不变</ElDescriptionsItem>
          <ElDescriptionsItem label="未完成任务">{{ props.summary?.counts.open_tasks || 0 }} 个，审批执行时按后端策略处理</ElDescriptionsItem>
        </ElDescriptions>
      </ElCard>

      <ElCard shadow="never">
        <template #header><strong>审批与历史</strong></template>
        <ElAlert title="未完成任务保留原任务事实与负责人；客户可见范围在转移获批后随新归属更新。" type="warning" :closable="false" show-icon />
        <ElTimeline v-if="props.transferRequests.length">
          <ElTimelineItem v-for="item in props.transferRequests" :key="item.id" :timestamp="props.formatDate(item.submitted_at)">
            <strong>{{ item.from_employee.display_name }} → {{ item.to_employee.display_name }}</strong>
            <p>{{ item.request_reason }}</p>
            <p v-if="item.decision_note" class="muted">处理说明：{{ item.decision_note }}</p>
            <div class="transfer-actions">
              <ElTag>{{ item.status }}</ElTag>
              <template v-if="item.status === 'PENDING'">
                <ElButton v-if="props.canApproveTransfer" size="small" type="success" :loading="props.transferLoading" @click="emit('decide', item, 'approve')">审批通过</ElButton>
                <ElButton v-if="props.canApproveTransfer" size="small" type="danger" plain :loading="props.transferLoading" @click="emit('decide', item, 'reject')">驳回</ElButton>
                <ElButton v-if="props.canCancelTransfer(item)" size="small" :loading="props.transferLoading" @click="emit('decide', item, 'cancel')">取消申请</ElButton>
              </template>
            </div>
          </ElTimelineItem>
        </ElTimeline>
        <ElEmpty v-else description="暂无转移申请" :image-size="70" />
      </ElCard>
    </section>
  </main>
</template>

<style scoped lang="scss">
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-heading p {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--erp-color-text-regular);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transfer-grid {
  display: grid;
  grid-template-columns: 1.1fr 1fr 1fr;
  gap: 14px;
  min-width: 0;
  align-items: start;
}

.transfer-grid :deep(.el-select) {
  width: 100%;
}

.transfer-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.transfer-page.erp-glass-list {
  height: auto;
  margin: 0;
  font-size: 13px;
  line-height: 20px;
}

.transfer-page .section-heading {
  margin: 0;
  padding: 16px;
}

.transfer-page .section-heading h2 {
  margin: 0 0 4px;
  font-size: 16px;
  line-height: 24px;
}

.transfer-page .section-heading p {
  white-space: normal;
}

.transfer-grid :deep(.el-card) {
  min-width: 0;
  border: 1px solid var(--erp-glass-border);
  border-radius: var(--erp-glass-radius);
  background: var(--erp-glass-surface);
  box-shadow: var(--erp-glass-shadow);
  backdrop-filter: var(--erp-glass-backdrop);
}

.transfer-grid :deep(.el-card__header) {
  padding: 14px 16px;
  border-bottom: 1px solid var(--erp-color-border);
  font-size: 16px;
}

.transfer-grid :deep(.el-card__body) {
  padding: 16px;
}

.transfer-grid :deep(.el-form) {
  margin-top: 14px;
}

.transfer-grid :deep(.el-form-item__label) {
  font-size: 12px;
  line-height: 20px;
}

.transfer-grid :deep(.el-alert),
.transfer-grid :deep(.el-timeline) {
  margin-bottom: 14px;
}

.transfer-grid :deep(.el-timeline) {
  padding-left: 12px;
}

.transfer-grid :deep(.el-descriptions__cell) {
  font-size: 13px;
  overflow-wrap: anywhere;
}

@media (max-width: 1200px) {
  .transfer-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 800px) {
  .section-heading {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
