<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useProtectedResourceUrl } from '@/composables/useProtectedResourceUrl'

const props = defineProps<{ src?: string | null }>()
const emit = defineEmits<{ error: [event: Event]; load: [event: Event] }>()
const image = ref<HTMLImageElement>()
const { url, error, active } = useProtectedResourceUrl(() => props.src)
function imageEvent(event: Event) {
  if (!active.value || event.target !== image.value) return
  if (event.type === 'error') emit('error', event)
  else emit('load', event)
}
watch(error, async failed => {
  if (!failed) return
  const source = props.src
  await nextTick()
  if (!active.value || !error.value || props.src !== source || !image.value) return
  // 保留调用方现有的图片失败占位处理，event.target 仍是实际 img。
  image.value.dispatchEvent(new Event('error'))
}, { immediate: true })
</script>

<template>
  <img v-if="active" :key="url" ref="image" :src="url || undefined" crossorigin="anonymous" referrerpolicy="no-referrer" @error="imageEvent" @load="imageEvent" />
</template>
