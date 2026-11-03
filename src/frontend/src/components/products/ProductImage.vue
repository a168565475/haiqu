<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Picture } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useProtectedResourceUrl } from '@/composables/useProtectedResourceUrl'
const props = withDefaults(defineProps<{ src: string; name?: string; large?: boolean }>(), { name: '产品图片', large: false })
const emit = defineEmits<{ 'resource-error': [] }>()
const { url, error, active } = useProtectedResourceUrl(() => props.src)
const open = ref(false), imageFailed = ref(false)
const failed = computed(() => imageFailed.value || error.value)
watch(() => props.src, () => { imageFailed.value = false; open.value = false }, { flush: 'sync' })
watch([url, active], () => { if (!url.value || !active.value) open.value = false }, { flush: 'sync' })
watch(error, value => { if (value) emit('resource-error') }, { immediate: true, flush: 'sync' })
</script>
<template>
  <button type="button" class="product-image" :class="{ large }" :disabled="!url || failed || !active" :aria-label="failed ? `${name}加载失败` : src ? `查看${name}` : '暂无产品图片'" :title="failed ? '图片暂无法加载' : src ? '查看产品图片' : '暂无产品图片'" @click="open = true"><img v-if="url && !failed" :key="url" :src="url" :alt="name" @error="imageFailed = true; emit('resource-error')"/><el-icon v-else><Picture/></el-icon></button>
  <AppWindowDialog v-model="open" class="product-image-preview-window" :title="name" :width="1000" :height="680" destroy-on-close><div class="product-image-stage"><img v-if="url && !failed" :key="url" :src="url" :alt="name" @error="imageFailed = true; emit('resource-error')"/><p v-else role="alert">图片暂无法加载，请关闭后重新打开单据。</p></div><template #footer><el-button @click="open = false">关闭</el-button></template></AppWindowDialog>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.product-image { display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; width: 32px; height: 32px; padding: 1px; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; color: token.$crm-text-secondary; cursor: pointer; img { width: 28px; height: 28px; object-fit: contain; } &:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; } &:disabled { cursor: default; } &.large { width: 80px; height: 80px; flex-shrink: 0; background: token.$crm-color-page; img { width: 76px; height: 76px; } :deep(.el-icon) { font-size: 28px; color: token.$crm-text-secondary; } } }
.product-image-stage { height: 100%; display: grid; place-items: center; min-height: 0; background: token.$crm-color-surface; img { width: 100%; height: 100%; min-height: 0; object-fit: contain; } p { color: token.$crm-text-secondary; } }
</style>
<style lang="scss">
.product-image-preview-window.app-window-dialog .app-window-dialog__body { padding: 16px; }
</style>
