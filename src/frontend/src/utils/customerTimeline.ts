/**
 * 时间线事件编码属于接口内部值，页面只展示中文业务名称。
 * 未识别的新编码也不直接暴露英文枚举，避免影响中文界面。
 */
const eventTypeLabels: Record<string, string> = {
  CUSTOMER_CREATED: '已创建客户',
  CUSTOMER_UPDATED: '已更新客户资料',
  CUSTOMER_ARCHIVED: '已归档客户',
  CUSTOMER_RESTORED: '已恢复客户',
  CUSTOMER_CLASSIFICATION_CHANGED: '已调整客户类型或标签',
  CUSTOMER_ATTENTION_CHANGED: '已更新客户关注状态',
  CUSTOMER_COLLABORATOR_ADDED: '已添加客户协同人',
  CUSTOMER_COLLABORATOR_ENDED: '已结束客户协同关系',
  CUSTOMER_TRANSFER_REQUESTED: '已提交客户转移申请',
  CUSTOMER_TRANSFER_APPROVED: '已通过客户转移申请',
  CUSTOMER_TRANSFER_REJECTED: '已驳回客户转移申请',
  CUSTOMER_TRANSFER_CANCELLED: '已取消客户转移申请',
  CUSTOMER_MERGED: '已完成客户合并',
  CUSTOMER_CONTACT_CREATED: '已新增客户联系人',
  CUSTOMER_CONTACT_UPDATED: '已更新客户联系人',
  CUSTOMER_CONTACT_LEFT: '客户联系人已离职',
  CUSTOMER_CONTACT_METHOD_UPDATED: '已更新联系人联系方式',
  CUSTOMER_CONTACT_PRIMARY_CHANGED: '已调整主要联系人',
  CUSTOMER_ENTITY_CREATED: '已新增客户主体',
  CUSTOMER_ENTITY_UPDATED: '已更新客户主体',
  CUSTOMER_ENTITY_ARCHIVED: '已归档客户主体',
  CUSTOMER_ENTITY_ADDRESS_CREATED: '已新增客户地址',
  CUSTOMER_ENTITY_ADDRESS_UPDATED: '已更新客户地址',
  CUSTOMER_ENTITY_ADDRESS_ARCHIVED: '已归档客户地址',
  CUSTOMER_TRANSACTION_ENTITY_CREATED: '已新增客户交易主体',
  CUSTOMER_TRANSACTION_ENTITY_UPDATED: '已更新客户交易主体',
  CUSTOMER_TRANSACTION_ENTITY_ARCHIVED: '已归档客户交易主体',
  COMMUNICATION_CREATED: '已记录沟通',
  COMMUNICATION_UPDATED: '已更新沟通记录',
  INQUIRY_CREATED: '已新建询盘',
  INQUIRY_UPDATED: '已更新询盘',
  INQUIRY_ITEM_CREATED: '已新增询盘明细',
  QUOTATION_CREATED: '已新建报价',
  QUOTATION_UPDATED: '已更新报价',
  QUOTATION_VERSION_CREATED: '已新建报价版本',
  QUOTATION_VERSION_UPDATED: '已更新报价版本',
  SAMPLE_CREATED: '已新建样品申请',
  SAMPLE_UPDATED: '已更新样品申请',
  SAMPLE_FEE_DECIDED: '已确认样品费用',
  SAMPLE_FEEDBACK_CREATED: '已记录样品反馈',
  TASK_CREATED: '已创建任务',
  TASK_STARTED: '已开始任务',
  TASK_COMPLETED: '已完成任务',
  TASK_CANCELLED: '已取消任务',
}

const sourceTypeLabels: Record<string, string> = {
  CUSTOMER: '客户',
  CUSTOMER_CONTACT: '客户联系人',
  CUSTOMER_CONTACT_METHOD: '联系人联系方式',
  CUSTOMER_ENTITY: '客户主体',
  CUSTOMER_ENTITY_ADDRESS: '客户地址',
  CUSTOMER_TRANSACTION_ENTITY: '客户交易主体',
  COMMUNICATION: '沟通记录',
  INQUIRY: '询盘',
  QUOTATION: '报价',
  QUOTATION_VERSION: '报价版本',
  SAMPLE_REQUEST: '样品申请',
  TASK: '任务',
}

export function getTimelineEventTypeLabel(eventType: string | null | undefined): string {
  return eventTypeLabels[eventType || ''] || '系统记录'
}

export function getTimelineSourceTypeLabel(sourceType: string | null | undefined): string {
  return sourceTypeLabels[sourceType || ''] || '业务记录'
}
