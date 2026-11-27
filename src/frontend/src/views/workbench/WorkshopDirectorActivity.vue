<script setup lang="ts">
import { ref, watch } from 'vue'
import { DataAnalysis, Files } from '@element-plus/icons-vue'
import { getDirectorActivity } from '@/api/workshopDirectorWorkbench'
import type { DirectorActivity, DirectorPeriod, DirectorSelection, DirectorWorkshop } from '@/types/workshopDirectorWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import { amount, workshopName } from './WorkshopDirectorDisplay'

const props = defineProps<{ workshop: DirectorWorkshop }>()
const emit = defineEmits<{ select: [DirectorSelection] }>()
const period = ref<DirectorPeriod>('month'), result = ref<DirectorActivity | null>(null)
const retry = ref(0), error = ref('')
const periods = { month: '本月', quarter: '本季', year: '本年' } as const
watch([period, retry], async ([current], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  result.value = null
  error.value = ''
  try {
    const response = await getDirectorActivity(props.workshop, current, 1, request.signal, 1)
    if (!request.signal.aborted) result.value = response.data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载车间汇总')
  }
}, { immediate: true })
</script>

<template>
  <section class="glass director-activity">
    <header class="summary-top"><h2><DataAnalysis />{{ workshopName[workshop] }}{{ workshop === 'ASSEMBLY' ? '入库' : '报工' }}汇总</h2>
      <div class="period-switch"><button v-for="(title, key) in periods" :key="key" type="button" :aria-pressed="key === period" @click="period = key">{{ title }}</button></div>
    </header>
    <p v-if="error" role="alert" class="empty">{{ error }} <button class="action" @click="retry++">重试</button></p>
    <p v-else-if="!result" role="status" class="empty">正在加载汇总…</p>
    <template v-else><p class="context">{{ result.start_date }} 至 {{ result.end_date }}</p>
      <p v-if="!result.available" class="empty">当前账号没有查看{{ workshop === 'ASSEMBLY' ? '入库' : '报工' }}记录的权限。</p>
      <template v-else>
        <div class="kpi-row"><div>
          <div class="kpi-values" :class="{ multiple: workshop === 'ASSEMBLY' && result.quantities.length > 1 }">
            <template v-if="workshop === 'ASSEMBLY'"><strong v-for="item in result.quantities" :key="item.unit">{{ amount(item.quantity) }}<small>{{ item.unit }}</small></strong>
              <strong v-if="!result.quantities.length">{{ result.record_count ? '—' : '0' }}</strong></template>
            <strong v-else>{{ result.task_count }}<small>张</small></strong>
          </div><p class="context">{{ workshop === 'ASSEMBLY' ? '成品入库数量' : '有报工的生产任务' }}</p>
        </div><span class="metric-icon"><Files /></span></div>
        <div class="subtotals"><div><strong>{{ workshop === 'ASSEMBLY' ? result.task_count : result.record_count }}</strong><small>{{ workshop === 'ASSEMBLY' ? '涉及任务（张）' : '报工记录（笔）' }}</small></div>
          <div><strong>{{ workshop === 'ASSEMBLY' ? result.record_count : result.day_count }}</strong><small>{{ workshop === 'ASSEMBLY' ? '入库记录（笔）' : '报工天数（天）' }}</small></div></div>
        <footer class="board-foot"><span>{{ periods[period] }}{{ workshop === 'ASSEMBLY' ? '成品入库' : '车间报工' }}</span><button class="action" @click="emit('select', { kind: 'records', period, title: periods[period] + workshopName[workshop] + (workshop === 'ASSEMBLY' ? '入库记录' : '报工记录') })">查看记录 ›</button></footer>
      </template>
    </template>
  </section>
</template>
