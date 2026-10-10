<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'brand' | 'info' | 'success' | 'warning' | 'danger' | 'neutral'
}>(), {
  tone: 'neutral',
})
</script>

<template>
  <span class="quotation-status-tag is-strong" :class="`is-${tone}`">
    <slot />
  </span>
</template>

<style scoped lang="scss">
.quotation-status-tag {
  display: inline-flex;
  min-width: 56px;
  height: 24px;
  box-sizing: border-box;
  align-items: center;
  justify-content: center;
  flex: none;
  padding: 0 8px;
  border: 0;
  border-radius: 999px;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;
}

.is-strong { color: #faf9f5; }
.is-strong.is-brand { background: #c96442; }
.is-strong.is-info { background: #3898ec; }
.is-strong.is-success { background: #4f7d4b; }
.is-strong.is-warning { background: #b8781e; }
.is-strong.is-danger { background: #b53333; }
.is-strong.is-neutral { background: #5e5d59; }

</style>
