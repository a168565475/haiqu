<script setup lang="ts">
import type { DeliveryFollowUp } from '@/types/deliveryReminders'

withDefaults(defineProps<{ ownerLabel?: string }>(), { ownerLabel: '责任方' })

const followUp = defineModel<DeliveryFollowUp>('followUp', { required: true })
const owner = defineModel<string>('owner', { required: true })
const emit = defineEmits<{ apply: [] }>()

const statuses: { value: DeliveryFollowUp; label: string }[] = [
  { value: 'ALL', label: '全部交期状态' },
  { value: 'FOLLOW_UP', label: '需跟进' },
  { value: 'OVERDUE', label: '逾期' },
  { value: 'DUE_TODAY', label: '今天到期' },
  { value: 'NEAR_DUE', label: '临期' },
  { value: 'REVIEW', label: '待核对' },
]
</script>

<template>
  <ElSelect v-model="followUp" class="delivery-status-filter" aria-label="交期状态" @change="emit('apply')">
    <ElOption v-for="status in statuses" :key="status.value" :value="status.value" :label="status.label" />
  </ElSelect>
  <ElInput v-model="owner" class="delivery-owner-filter" maxlength="150" clearable
    :placeholder="ownerLabel" :aria-label="ownerLabel" @clear="emit('apply')" />
</template>

<style scoped>
.delivery-status-filter { width: min(100%, 150px); }
.delivery-owner-filter { width: min(100%, 176px); }
</style>
