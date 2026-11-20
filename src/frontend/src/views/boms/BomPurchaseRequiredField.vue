<script setup lang="ts">
const purchaseRequired = defineModel<boolean>({ default: true })
</script>

<template>
  <label class="drawer-field">
    <span>是否采购</span>
    <ElSelect v-model="purchaseRequired" aria-label="是否采购">
      <ElOption label="需要采购" :value="true" />
      <ElOption label="外供" :value="false" />
    </ElSelect>
  </label>
</template>
