<script setup lang="ts">
import { nextTick, onMounted } from 'vue'

withDefaults(
  defineProps<{
    width?: 'fluid' | 'contained'
    flush?: boolean
    fitViewport?: boolean
  }>(),
  {
    width: 'fluid',
    flush: false,
    fitViewport: false,
  },
)

onMounted(async () => {
  await nextTick()
  const main = document.getElementById('erp-main-content')
  if (!main) {
    return
  }
  main.scrollTo({ top: 0, left: 0 })
  main.focus({ preventScroll: true })
})
</script>

<template>
  <div
    class="page-container"
    :class="[`page-container--${width}`, { 'page-container--flush': flush, 'page-container--fit-viewport': fitViewport }]"
    data-page-container
  >
    <div class="page-container__content">
      <slot />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.page-container {
  width: 100%;
  min-height: 100%;
  padding: 14px;
  background: transparent;
}

.page-container--flush {
  padding: 14px;
}

.page-container--fit-viewport {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.page-container--fit-viewport .page-container__content {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.page-container--fit-viewport .page-container__content > :deep(*) {
  min-height: 0;
  flex: 1;
}

.page-container__content > :deep(*) {
  padding: 0 !important;
}

.page-container__content :deep(h1) {
  font-size: 34px !important;
  line-height: 44px !important;
}

.page-container--contained .page-container__content {
  width: min(1320px, 100%);
  margin-right: auto;
  margin-left: auto;
}

@media (max-width: 768px) {
  .page-container {
    padding: 14px;
  }
}

@media print {
  .page-container {
    padding: 0;
  }
}
</style>
