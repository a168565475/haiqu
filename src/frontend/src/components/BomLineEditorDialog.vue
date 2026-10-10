<script setup lang="ts">
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

defineProps<{ modelValue: boolean; title: string; beforeClose: (done: () => void) => void | Promise<void> }>()
defineEmits<{ 'update:modelValue': [value: boolean]; closed: [] }>()
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    :title="title"
    class="bom-line-editor-dialog hardware-picker-dialog"
    :width="1000"
    height="auto"
    destroy-on-close
    :close-on-click-modal="false"
    :before-close="beforeClose"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="$emit('closed')"
  >
    <slot />
    <template #footer><slot name="footer" /></template>
  </AppWindowDialog>
</template>
