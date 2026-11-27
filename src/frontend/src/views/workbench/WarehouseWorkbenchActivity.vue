<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { DataAnalysis } from '@element-plus/icons-vue'
import { getWarehouseActivity } from '@/api/warehouseWorkbench'
import type { WarehouseActivity, WarehouseDrill, WarehousePeriod } from '@/types/warehouseWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import { periodLabels, queueLabels, warehouseQueues } from './WarehouseWorkbenchDisplay'

const emit = defineEmits<{ select: [view: WarehouseDrill] }>()
const period = ref<WarehousePeriod>('month'), result = ref<WarehouseActivity | null>(null)
const error = ref(''), retry = ref(0)
const counts = computed(() => Object.values(result.value?.counts ?? {}).filter((n): n is number => n !== null))
const max = computed(() => Math.max(1, ...counts.value))
const total = computed(() => counts.value.reduce((a, n) => a + n, 0))
watch([period, retry], async ([selected], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  error.value = ''
  result.value = null
  try {
    const { data } = await getWarehouseActivity(selected, 'all', 1, request.signal, true)
    if (!request.signal.aborted) result.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载仓库收发汇总')
  }
}, { immediate: true })
</script>

<template>
  <section class="panel warehouse-activity">
    <header><h2><DataAnalysis />仓库收发汇总</h2><div class="period-switch">
      <button v-for="(label, key) in periodLabels" :key="key" :aria-pressed="period === key" @click="period = key">{{ label }}</button>
    </div></header>
    <p v-if="error" role="alert" class="empty">{{ error }} <button class="action" @click="retry++">重试</button></p>
    <p v-else-if="!result" role="status" class="empty">正在加载汇总…</p>
    <template v-else>
      <p class="range">{{ result.start_date }} 至 {{ result.end_date }}</p>
      <div class="bars">
        <button v-for="queue in warehouseQueues" :key="queue" class="bar-row" :data-activity="queue" :disabled="result.counts[queue] === null"
          @click="emit('select', { type: 'activity', period, queue })">
          <span>{{ queueLabels[queue].short }}</span>
          <span class="track" aria-hidden="true"><i :style="{ width: ((result.counts[queue] ?? 0) / max * 100) + '%' }" /></span>
          <strong v-if="result.counts[queue] !== null">{{ result.counts[queue] }}<small>笔</small></strong>
          <small v-else>无权限</small>
        </button>
      </div>
      <footer><span>{{ counts.length ? '已办收发 ' + total + ' 笔' : '无可查看的收发记录' }}</span>
        <button class="action" :disabled="!counts.length" @click="emit('select', { type: 'activity', period, queue: 'all' })">查看收发记录 ›</button>
      </footer>
    </template>
  </section>
</template>
