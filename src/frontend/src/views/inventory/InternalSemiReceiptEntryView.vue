<script setup lang="ts">
import { useRoute } from 'vue-router'
import InternalSemiReceiptView from './InternalSemiReceiptView.vue'
import MetalInternalReceiptView from './MetalInternalReceiptView.vue'

const route = useRoute()
</script>

<template>
  <MetalInternalReceiptView v-if="route.query.plan_category === 'METAL'" :key="String(route.query.schedule_product_id || '')" />
  <InternalSemiReceiptView v-else />
</template>
