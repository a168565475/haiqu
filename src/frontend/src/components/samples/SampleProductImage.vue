<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ src?: string }>()
const failed = ref(false)
watch(() => props.src, () => { failed.value = false })
</script>
<template>
  <div class="sample-product-image"><img v-if="src && !failed" :src="src" alt="打样产品图片" @error="failed = true" /><span v-else>{{ failed ? '图片暂无法加载' : '暂无产品图片' }}</span></div>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.sample-product-image { display: grid; place-items: center; min-width: 0; overflow: hidden; color: token.$crm-text-muted; font-size: 12px; }
img { width: 100%; height: 100%; min-height: 0; object-fit: contain; }
</style>
