<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { apiClient } from '@/utils/request'

const props = defineProps<{ src: string | null; alt: string }>()
const imageUrl = ref('')
let controller: AbortController | undefined
function release() {
  controller?.abort()
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
}
watch(() => props.src, async (source) => {
  release()
  if (!source) return
  let target: URL
  try { target = new URL(source, window.location.origin) }
  catch { return }
  if (target.origin !== window.location.origin || !target.pathname.startsWith('/api/')) return
  const current = new AbortController()
  controller = current
  try {
    const { data } = await apiClient.get<Blob>(`${target.pathname}${target.search}`, { responseType: 'blob', signal: current.signal })
    if (current.signal.aborted || controller !== current) return
    if (data.size > 0 && /^image\/(png|jpeg|webp|gif|avif|bmp)$/i.test(data.type)) imageUrl.value = URL.createObjectURL(data)
  } catch {
    // 图片不可用时明确显示占位，身份失效仍由统一请求层处理。
    if (controller === current) imageUrl.value = ''
  }
}, { immediate: true })
onUnmounted(release)
</script>

<template>
  <img v-if="imageUrl" class="product-image" :src="imageUrl" :alt="alt">
  <div v-else class="product-image placeholder" role="img" :aria-label="`${alt}，图片不可用`"><van-icon name="photo-o" size="28" /><span>暂无图片</span></div>
</template>

<style scoped>
.product-image { width: 76px; height: 76px; object-fit: contain; border-radius: 10px; background: var(--mobile-canvas); flex-shrink: 0; }
.placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; color: var(--mobile-muted); }
.placeholder span { font-size: 11px; }
</style>
