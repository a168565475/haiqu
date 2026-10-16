<script setup lang="ts">
import panelMark from '@/assets/boards/panel-mark.png'
defineProps<{ title: string; period?: string }>()
</script>

<template>
  <section class="board-panel" :aria-label="title">
    <header class="board-panel-header">
      <img class="board-panel-mark" :src="panelMark" alt="" aria-hidden="true" />
      <h2>{{ title }}</h2><span v-if="period" class="board-period">{{ period }}</span>
      <slot name="header" />
    </header>
    <div class="board-panel-content"><slot /></div>
  </section>
</template>
