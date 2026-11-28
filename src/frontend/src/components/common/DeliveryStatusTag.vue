<script setup lang="ts">
import { computed } from 'vue'
import type { DeliveryReminder, DeliveryReminderStatus } from '@/types/deliveryReminders'

const props = defineProps<{ reminder: Pick<DeliveryReminder, 'status' | 'label'> | null }>()

const tagType: Record<DeliveryReminderStatus, 'danger' | 'warning' | 'info'> = {
  OVERDUE: 'danger',
  DUE_TODAY: 'danger',
  NEAR_DUE: 'warning',
  REVIEW: 'warning',
  UPCOMING: 'info',
}
const reviewLabels = new Set(['未约定交期', '数量待核', '需求待核'])
const label = computed(() => {
  const reminder = props.reminder
  if (!reminder) return '无异常'
  if (reminder.status === 'UPCOMING') return '未临期'
  if (reminder.status === 'REVIEW' && !reviewLabels.has(reminder.label)) return '待核'
  return reminder.label
})
</script>

<template>
  <ElTag size="small" :type="reminder ? tagType[reminder.status] : 'info'">{{ label }}</ElTag>
</template>
