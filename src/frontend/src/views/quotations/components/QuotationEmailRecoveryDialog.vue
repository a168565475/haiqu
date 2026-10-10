<script setup lang="ts">
import { computed } from 'vue'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { QuotationEmailDispatchAttempt } from '@/types/quotation'
import type { QuotationWorkflowStateDefinition } from '../workflow/quotationWorkflow'
import QuotationWorkflowStatus from './QuotationWorkflowStatus.vue'

const props = defineProps<{
  visible: boolean
  attempt: QuotationEmailDispatchAttempt | null
  state: QuotationWorkflowStateDefinition
  result: 'ACCEPTED' | 'NOT_SENT'
  note: string
  loading: boolean
}>()

const emit = defineEmits<{
  close: []
  submit: []
  'update:result': [value: 'ACCEPTED' | 'NOT_SENT']
  'update:note': [value: string]
}>()

const formattedTime = computed(() => {
  if (!props.attempt) return ''
  const date = new Date(props.attempt.created_at)
  return Number.isNaN(date.getTime()) ? props.attempt.created_at : date.toLocaleString('zh-CN', { hour12: false })
})
</script>

<template>
  <AppWindowDialog :model-value="visible" title="邮件结果待核对" :width="680" :height="520" :close-on-click-modal="false" :show-close="false" @update:model-value="value => { if (!value) emit('close') }">
    <QuotationWorkflowStatus :state="state" />
    <dl v-if="attempt" class="attempt-summary">
      <dt>收件人</dt><dd>{{ attempt.recipient }}</dd>
      <dt>主题</dt><dd>{{ attempt.subject }}</dd>
      <dt>附件</dt><dd>{{ attempt.attachment_snapshot.filename || '正式报价附件' }}</dd>
      <dt>发起时间</dt><dd>{{ formattedTime }}</dd>
    </dl>
    <ElAlert title="请先在实际发件箱中核对这封邮件。这里的确认不会再次调用邮件服务。" type="warning" :closable="false" show-icon />
    <ElForm label-position="top" class="resolution-form">
      <ElFormItem label="核对结果 *"><ElRadioGroup :model-value="result" @update:model-value="emit('update:result', $event)"><ElRadio value="ACCEPTED">确认已投递</ElRadio><ElRadio value="NOT_SENT">确认未投递</ElRadio></ElRadioGroup></ElFormItem>
      <ElFormItem label="核对说明 *"><ElInput :model-value="note" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="说明核对了哪个发件箱、时间和结果。" @update:model-value="emit('update:note', $event)" /></ElFormItem>
    </ElForm>
    <template #footer><ElButton @click="emit('close')">暂不处理</ElButton><ElButton class="black-button" :loading="loading" @click="emit('submit')">提交核对结果</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.attempt-summary{display:grid;grid-template-columns:92px 1fr;gap:8px 12px;margin:14px 0;padding:14px;border:1px solid #e4e4e7;border-radius:8px;background:#f7f7f8;font-size:12px}.attempt-summary dt{color:#71717a}.attempt-summary dd{min-width:0;margin:0;overflow-wrap:anywhere}.resolution-form{margin-top:14px}.black-button{color:#fff!important;border-color:#18181b!important;background:#18181b!important}
</style>
