<script setup lang="ts">
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import type { ContactListItem } from '@/types/contact'
import type { CustomerTimelineEvent } from '@/types/customer'
import type { PublishedOption } from '@/types/referenceData'

interface TimelineFilters {
  keyword: string
  eventType: string
  occurredFrom: string
  occurredTo: string
}

interface CommunicationForm {
  type: string
  direction: 'INBOUND' | 'OUTBOUND' | 'INTERNAL'
  contactId: string
  occurredAt: string
  subject: string
  content: string
  createTask: boolean
  taskTitle: string
  taskDueAt: string
}

interface CommunicationSaveResult {
  type: 'success' | 'warning'
  message: string
  uncertain: boolean
}

const props = defineProps<{
  timeline: CustomerTimelineEvent[]
  timelineLoading: boolean
  timelineCursor: string | null
  timelineFilters: TimelineFilters
  contacts: ContactListItem[]
  communicationTypeOptions: PublishedOption[]
  communicationForm: CommunicationForm
  communicationResult: CommunicationSaveResult | null
  communicationSaving: boolean
  canTask: boolean
  canCommunicate: boolean
  formatDate: (value: string | null | undefined) => string
  getTimelineEventTypeLabel: (value: string | null | undefined) => string
  getTimelineSourceTypeLabel: (value: string | null | undefined) => string
}>()

const emit = defineEmits<{
  'load-timeline': [reset: boolean]
  'reset-filters': []
  export: []
  'clear-form': []
  'save-communication': []
}>()
</script>

<template>
  <main class="customer-timeline-v2 erp-glass-list">
    <section class="customer-timeline-v2__filters erp-list-filter erp-list-filters">
      <ElInput v-model="props.timelineFilters.keyword" placeholder="搜索主题、内容、编号" clearable @keyup.enter="emit('load-timeline', true)" />
      <ElSelect v-model="props.timelineFilters.eventType" clearable placeholder="类型：全部">
        <ElOption label="沟通" value="COMMUNICATION" />
        <ElOption label="任务" value="TASK" />
        <ElOption label="客户资料" value="CUSTOMER" />
      </ElSelect>
      <ElDatePicker v-model="props.timelineFilters.occurredFrom" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="开始时间" />
      <ElDatePicker v-model="props.timelineFilters.occurredTo" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="结束时间" />
      <div class="erp-list-filter-actions">
        <ElButton class="erp-button-motion" @click="emit('reset-filters')">重置</ElButton>
        <ElButton class="erp-button-motion" type="primary" @click="emit('load-timeline', true)">应用筛选</ElButton>
      </div>
    </section>

    <div class="customer-timeline-v2__workspace">
      <section v-loading="props.timelineLoading" class="customer-timeline-v2__list-panel erp-list-surface">
        <header>
          <div><h2>客户时间轴</h2><small>{{ props.timeline.length }} 条已加载</small></div>
          <ElButton class="erp-button-motion" @click="emit('export')">导出记录</ElButton>
        </header>
        <div v-if="props.timeline.length" class="customer-timeline-v2__list">
          <article v-for="event in props.timeline" :key="event.id" class="customer-timeline-v2__event">
            <time>{{ props.formatDate(event.occurred_at) }}</time>
            <span class="customer-timeline-v2__dot" aria-hidden="true" />
            <div>
              <div><CustomerActivityTag :label="props.getTimelineEventTypeLabel(event.event_type)" tone="info" /><strong :title="event.title">{{ event.title }}</strong></div>
              <p :title="event.summary || ''">{{ event.summary || '无补充摘要' }}</p>
              <small>来源：{{ props.getTimelineSourceTypeLabel(event.source_type) }} · 只读业务事实</small>
            </div>
          </article>
          <ElButton v-if="props.timelineCursor" class="customer-timeline-v2__more" :loading="props.timelineLoading" @click="emit('load-timeline', false)">加载更多记录</ElButton>
        </div>
        <ElEmpty v-else description="暂无符合条件的时间线记录" />
      </section>

      <section class="customer-timeline-v2__composer erp-list-surface erp-flat-form">
        <header><div><h2>记录沟通</h2><span>保存后写入客户时间轴</span></div></header>
        <ElAlert v-if="props.communicationResult" :title="props.communicationResult.message" :type="props.communicationResult.type" :closable="false" show-icon />
        <ElForm label-position="top" :disabled="props.communicationSaving || !!props.communicationResult">
          <ElFormItem label="沟通方式" required>
            <ElRadioGroup v-model="props.communicationForm.type">
              <ElRadioButton v-for="item in props.communicationTypeOptions" :key="item.id" :value="item.code">{{ item.label }}</ElRadioButton>
            </ElRadioGroup>
          </ElFormItem>
          <div class="customer-timeline-v2__form-grid">
            <ElFormItem label="联系人"><ElSelect v-model="props.communicationForm.contactId" clearable placeholder="选择联系人"><ElOption v-for="item in props.contacts" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="沟通方向" required><ElSelect v-model="props.communicationForm.direction"><ElOption label="去电 / 发出" value="OUTBOUND" /><ElOption label="来电 / 收到" value="INBOUND" /><ElOption label="内部沟通" value="INTERNAL" /></ElSelect></ElFormItem>
            <ElFormItem label="沟通时间" required><ElDatePicker v-model="props.communicationForm.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></ElFormItem>
          </div>
          <ElFormItem label="主题" required><ElInput v-model="props.communicationForm.subject" maxlength="250" placeholder="输入本次沟通主题" /></ElFormItem>
          <ElFormItem label="沟通内容" required><ElInput v-model="props.communicationForm.content" type="textarea" :rows="5" maxlength="5000" show-word-limit placeholder="记录关键需求、结论与待办" /></ElFormItem>
          <div class="customer-timeline-v2__attachment" title="当前沟通接口暂未接入附件字段"><strong>附件</strong><span>附件接口尚未接入，暂不可上传</span></div>
          <section class="customer-timeline-v2__followup">
            <ElCheckbox v-model="props.communicationForm.createTask" :disabled="!props.canTask">同时创建下一步跟进任务</ElCheckbox>
            <div v-if="props.communicationForm.createTask" class="customer-timeline-v2__form-grid customer-timeline-v2__form-grid--two"><ElFormItem label="任务标题"><ElInput v-model="props.communicationForm.taskTitle" /></ElFormItem><ElFormItem label="截止时间"><ElDatePicker v-model="props.communicationForm.taskDueAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></ElFormItem></div>
          </section>
        </ElForm>
        <footer><ElButton :disabled="props.communicationSaving" @click="emit('clear-form')">{{ props.communicationResult ? '开始新沟通' : '清空' }}</ElButton><ElButton type="primary" :disabled="!props.canCommunicate || !!props.communicationResult" :loading="props.communicationSaving" @click="emit('save-communication')">保存沟通</ElButton></footer>
      </section>
    </div>
  </main>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.customer-timeline-v2.erp-glass-list { height: auto; min-width: 0; padding: 0; font-size: 13px; line-height: 20px; }
.customer-timeline-v2__filters { gap: 8px; }
.customer-timeline-v2__filters :deep(.el-input) { width: 250px; max-width: 100%; }
.customer-timeline-v2__filters :deep(.el-select) { width: 150px; }
.customer-timeline-v2__filters :deep(.el-date-editor) { width: 185px; max-width: 100%; }
.customer-timeline-v2__filters :deep(.el-button) { margin: 0; }
.customer-timeline-v2__workspace { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); align-items: start; gap: 14px; }
.customer-timeline-v2__list-panel, .customer-timeline-v2__composer { min-width: 0; padding: 16px; }
.customer-timeline-v2__list-panel > header, .customer-timeline-v2__composer > header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.customer-timeline-v2__list-panel h2, .customer-timeline-v2__composer h2 { margin: 0; font-family: token.$crm-font-body; font-size: 16px; font-weight: 700; line-height: 24px; }
.customer-timeline-v2__list-panel header span, .customer-timeline-v2__composer header span, .customer-timeline-v2__list-panel header small { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.customer-timeline-v2__list-panel header div, .customer-timeline-v2__composer header div { display: flex; flex-direction: column; gap: 4px; }
.customer-timeline-v2__list { min-width: 0; }
.customer-timeline-v2__event { display: grid; grid-template-columns: 112px 12px minmax(0, 1fr); align-items: start; gap: 10px; padding: 14px 0; border-bottom: 1px solid token.$crm-border-subtle; }
.customer-timeline-v2__event:last-of-type { border-bottom: 0; }
.customer-timeline-v2__event time { color: token.$crm-text-muted; font-size: 12px; line-height: 20px; }
.customer-timeline-v2__dot { width: 8px; height: 8px; margin-top: 7px; border: 2px solid token.$crm-color-surface; border-radius: 50%; background: token.$crm-primary; box-shadow: 0 0 0 1px token.$crm-primary; }
.customer-timeline-v2__event > div { min-width: 0; }
.customer-timeline-v2__event > div > div { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px; }
.customer-timeline-v2__event strong { font-size: 13px; line-height: 20px; overflow-wrap: anywhere; }
.customer-timeline-v2__event p { margin: 6px 0; color: token.$crm-text-regular; font-size: 13px; line-height: 20px; overflow-wrap: anywhere; }
.customer-timeline-v2__event small { color: token.$crm-text-muted; font-size: 12px; overflow-wrap: anywhere; }
.customer-timeline-v2__more { width: 100%; margin: 12px 0 0; }
.customer-timeline-v2__composer :deep(.el-form-item) { margin-bottom: 14px; }
.customer-timeline-v2__composer :deep(.el-form-item__label) { height: auto; margin-bottom: 4px; color: token.$crm-text-regular; font-size: 12px; line-height: 20px; }
.customer-timeline-v2__composer :deep(.el-select), .customer-timeline-v2__composer :deep(.el-date-editor) { width: 100%; min-width: 0; }
.customer-timeline-v2__composer :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: 6px; }
.customer-timeline-v2__composer :deep(.el-radio-button__inner) { height: 32px; padding: 0 12px; border: 1px solid token.$crm-border-default; border-radius: var(--erp-radius-control); font-size: 12px; line-height: 30px; box-shadow: none; }
.customer-timeline-v2__form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.customer-timeline-v2__form-grid > :last-child:nth-child(odd) { grid-column: 1 / -1; }
.customer-timeline-v2__form-grid--two { margin-top: 12px; }
.customer-timeline-v2__attachment { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 12px; border: 1px dashed token.$crm-border-default; border-radius: var(--erp-radius-control); color: token.$crm-text-muted; background: token.$crm-color-subtle; font-size: 12px; }
.customer-timeline-v2__attachment strong { color: token.$crm-text-secondary; }
.customer-timeline-v2__followup { margin-top: 12px; padding-top: 12px; border-top: 1px solid token.$crm-border-subtle; }
.customer-timeline-v2__composer > footer { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid token.$crm-border-subtle; }
.customer-timeline-v2__composer > footer :deep(.el-button) { margin: 0; }

@media (max-width: 980px) {
  .customer-timeline-v2__workspace { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 600px) {
  .customer-timeline-v2__event { grid-template-columns: 12px minmax(0, 1fr); }
  .customer-timeline-v2__event time { grid-column: 1 / -1; }
  .customer-timeline-v2__form-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
