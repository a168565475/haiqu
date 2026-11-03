<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useProtectedResourceUrl } from '@/composables/useProtectedResourceUrl'
const props = defineProps<{ src?: string }>()
const { url, error } = useProtectedResourceUrl(() => props.src)
const imageFailed = ref(false)
const failed = computed(() => imageFailed.value || error.value)
watch(() => props.src, () => { imageFailed.value = false }, { flush: 'sync' })
</script>
<template>
  <div class="sample-product-image"><img v-if="url && !failed" :key="url" :src="url" alt="打样产品图片" @error="imageFailed = true" /><span v-else>{{ failed ? '图片暂无法加载' : '暂无产品图片' }}</span></div>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.sample-product-image { display: grid; place-items: center; min-width: 0; overflow: hidden; color: token.$crm-text-muted; font-size: 12px; }
img { width: 100%; height: 100%; min-height: 0; object-fit: contain; }
</style>
