<script setup lang="ts">
defineProps<{ canEdit: boolean }>()
</script>

<template>
  <ElTableColumn label="是否采购" width="120">
    <template #default="{ row }">
      <ElSelect v-if="canEdit" :model-value="row.purchase_required ?? true" aria-label="是否采购"
        @update:model-value="row.purchase_required = $event">
        <ElOption label="需要采购" :value="true" />
        <ElOption label="外供" :value="false" />
      </ElSelect>
      <span v-else>{{ row.purchase_required === false ? '外供' : '需要采购' }}</span>
    </template>
  </ElTableColumn>
</template>
