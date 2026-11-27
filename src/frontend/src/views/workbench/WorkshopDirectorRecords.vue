<script setup lang="ts">
import type { DirectorRecord } from '@/types/workshopDirectorWorkbench'
import { amount } from './WorkshopDirectorDisplay'

defineProps<{ records: DirectorRecord[]; drill?: boolean }>()
const emit = defineEmits<{ open: [string] }>()
</script>

<template>
  <div class="director-table-scroll"><table><thead><tr><th>生产任务单号</th><th>日期</th><th>单据号</th><th>产品 / 工序</th><th>数量</th></tr></thead>
    <tbody><tr v-for="record in records" :key="record.id">
      <td><button v-if="drill && record.job_id" class="action" @click="emit('open', record.job_id)">{{ record.task_number }}</button><b v-else>{{ record.task_number }}</b></td>
      <td>{{ record.date }}</td><td>{{ record.number || '—' }}</td><td>{{ record.product_name }}<small v-if="record.name && record.name !== record.product_name">{{ record.name }}</small></td><td>{{ amount(record.quantity, record.unit) }}</td>
    </tr></tbody></table></div>
</template>
