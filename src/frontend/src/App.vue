<script setup lang="ts">
import ErpLayout from '@/layouts/ErpLayout.vue'
</script>

<template>
  <RouterView v-slot="{ Component, route }">
    <ErpLayout v-if="route.meta.layout === 'erp'">
      <component :is="Component" />
    </ErpLayout>
    <component :is="Component" v-else />
  </RouterView>
</template>
