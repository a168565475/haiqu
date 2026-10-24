<script setup lang="ts">
import { computed } from 'vue'
import { ElAlert } from 'element-plus'
import { useRoute } from 'vue-router'
import InternalSemiReceiptView from './InternalSemiReceiptView.vue'
import MetalInternalReceiptView from './MetalInternalReceiptView.vue'

const route = useRoute()
const validSource = computed(() => typeof route.query.schedule_product_id === 'string'
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(route.query.schedule_product_id)
  && (route.query.plan_category === 'METAL' || route.query.plan_category === 'SEWING'))
const sourceError = computed(() => {
  const category = route.query.plan_category === 'METAL' ? '金工' : route.query.plan_category === 'SEWING' ? '车缝' : '金工或车缝'
  return `入库来源参数无效，请从${category}内部计划的产品行进入半成品入库。`
})
</script>

<template>
  <section v-if="!validSource" class="semi-receipt-source-error">
    <ElAlert :title="sourceError" type="error" :closable="false" show-icon />
  </section>
  <MetalInternalReceiptView v-else-if="route.query.plan_category === 'METAL'" :key="String(route.query.schedule_product_id || '')" />
  <InternalSemiReceiptView v-else />
</template>
