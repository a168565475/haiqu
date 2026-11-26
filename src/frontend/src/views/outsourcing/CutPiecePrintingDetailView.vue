<script setup lang="ts">
import { watch, ref } from 'vue'
import { useRoute } from 'vue-router'
import { isAxiosError } from 'axios'
import { fetchPrintOrder } from '@/api/cutPiecePrinting'
import TubeOutsourcingPlanDetail from '@/components/outsourcing/TubeOutsourcingPlanDetail.vue'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'

const route = useRoute()
const order = ref<TubeOrderDetail>(), error = ref(''), loading = ref(false)
let sequence = 0
async function load() {
  const current = ++sequence
  order.value = undefined
  error.value = ''
  loading.value = true
  try {
    const result = await fetchPrintOrder(String(route.params.id))
    if (current === sequence) order.value = result
  } catch (cause) {
    if (current === sequence) error.value = (isAxiosError(cause) && cause.response?.data?.error?.message) || '丝印外发单读取失败。'
  } finally {
    if (current === sequence) loading.value = false
  }
}
watch(() => route.params.id, load, { immediate: true })
</script>

<template>
  <section v-loading="loading" class="tube-outsourcing-page tube-outsourcing-detail">
    <header class="page-heading"><h1>裁片丝印外发单</h1><RouterLink class="el-button" :to="{ name: 'workshop-outsourcing' }">返回委外加工</RouterLink></header>
    <template v-if="error"><ElAlert :title="error" type="error" :closable="false" /><ElButton @click="load">重新读取</ElButton></template>
    <TubeOutsourcingPlanDetail v-else-if="order" :key="order.id" :order="order" :warehouse="false" read-only @refresh="load" />
  </section>
</template>
