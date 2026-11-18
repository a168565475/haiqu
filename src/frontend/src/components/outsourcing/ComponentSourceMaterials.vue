<script setup lang="ts">
import type { ComponentSourceMaterial } from '@/types/processingMaterial'
import type { ComponentSourceField } from '@/utils/componentSourceColumns'

defineProps<{ sources?: ComponentSourceMaterial[]; field: ComponentSourceField }>()
</script>

<template>
  <div v-if="sources?.length" class="component-source-materials">
    <span v-for="(source, index) in sources" :key="`${source.source_bom_line_id}-${index}`" class="component-source-value" :title="source[field] || '未记录'">{{ source[field] || '未记录' }}</span>
  </div>
  <span v-else class="muted">{{ field === 'name' ? '来源布料未记录' : '—' }}</span>
</template>

<style scoped>
.component-source-materials { display: grid; gap: 4px; min-width: 0; text-align: left; }
.component-source-value { display: block; height: 20px; font-size: 12px; line-height: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
