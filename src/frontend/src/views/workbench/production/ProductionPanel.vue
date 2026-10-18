<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'

withDefaults(defineProps<{ title?: string; subtitle?: string; staticView?: boolean }>(), {
  title: '', subtitle: '', staticView: false,
})
</script>

<template>
  <section :key="String(staticView)" v-glass-spotlight.tilt="!staticView" class="pd-panel pd-glass">
    <header v-if="title || $slots.actions" class="pd-panel__header">
      <div><h2 v-if="title">{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div>
      <slot name="actions" />
    </header>
    <slot />
  </section>
</template>
