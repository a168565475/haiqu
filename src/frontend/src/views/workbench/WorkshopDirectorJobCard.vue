<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, Calendar, Document, Tools } from '@element-plus/icons-vue'
import type { DirectorJob, DirectorWorkshop } from '@/types/workshopDirectorWorkbench'
import { amount, countdown, deadlineLabel, dueTone, shortDate } from './WorkshopDirectorDisplay'

const props = defineProps<{ job: DirectorJob; workshop: DirectorWorkshop; today: string }>()
const isAssembly = computed(() => props.workshop === 'ASSEMBLY')
const progress = computed(() => {
  const { target, done } = props.job.quantity
  return target !== null && Number(target) > 0 && done !== null ? Math.min(100, Math.max(0, Number(done) / Number(target) * 100)) : null
})
</script>

<template>
  <button type="button" class="glass job-card">
    <span class="card-head"><strong class="task-code"><Document />{{ job.task_number }}</strong><span class="jump">查看明细 <ArrowRight /></span></span>
    <strong class="product">{{ job.product_name }}</strong>
    <span class="workstep"><Tools /><span>{{ job.latest_date ? (job.latest_date === today ? '今日报工' : '最近报工 ' + shortDate(job.latest_date)) : '最近工序' }} · {{ job.latest_operation || job.craft_name || '暂无记录' }}</span></span>
    <span class="deadline"><span><small>{{ deadlineLabel[workshop] }}</small><strong><Calendar />{{ job.due_date }}</strong></span><b :class="dueTone(job.days_remaining)">{{ countdown(job.days_remaining) }}</b></span>
    <template v-if="progress !== null">
      <span class="meter-head"><span>{{ isAssembly ? '累计成品入库' : '该工序已报' }}</span><strong>{{ amount(job.quantity.done) }} <small>/ {{ amount(job.quantity.target, job.quantity.unit) }}</small></strong></span>
      <span class="meter" aria-hidden="true"><i :style="{ width: progress + '%' }" /></span>
      <span class="counts"><span>{{ isAssembly ? '需求' : '工序要求' }} <b>{{ amount(job.quantity.target, job.quantity.unit) }}</b></span>
        <span>{{ isAssembly ? '还差入库' : '该工序还差' }} <b>{{ amount(job.quantity.remaining, job.quantity.unit) }}</b></span></span>
    </template>
    <template v-else>
      <span v-if="job.quantity.done !== null" class="meter-head"><span>{{ isAssembly ? '累计成品入库' : '该工序已报' }}</span><strong>{{ amount(job.quantity.done, job.quantity.unit) }}</strong></span>
      <span class="quantity-note">{{ job.quantity.reason || '暂无可核算的进度数量' }}</span>
    </template>
  </button>
</template>
