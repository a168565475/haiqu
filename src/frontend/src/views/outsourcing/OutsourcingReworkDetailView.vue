<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MetalProcessingP4View from './MetalProcessingP4View.vue'

const route = useRoute()
const orderId = computed(() => String(route.params.orderId || ''))
</script>

<template>
  <MetalProcessingP4View mode="rework" :external-order-id="orderId" />
</template>
