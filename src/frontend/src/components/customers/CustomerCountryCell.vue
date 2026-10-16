<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  countryCode: string
  countryName: string
}>()

const flagFailed = ref(false)
const flagUrl = computed(() => {
  if (typeof props.countryCode !== 'string' || !/^[A-Za-z]{2}$/.test(props.countryCode)) return ''
  return `https://flagcdn.com/24x18/${props.countryCode.toLowerCase()}.png`
})

watch(() => props.countryCode, () => { flagFailed.value = false })
</script>

<template>
  <span class="customer-country" :title="countryName">
    <img v-if="flagUrl && !flagFailed" :key="flagUrl" class="customer-country__flag"
      :src="flagUrl" width="16" height="12" alt="" aria-hidden="true" loading="lazy" @error="flagFailed = true" />
    <span class="customer-country__name">{{ countryName }}</span>
  </span>
</template>

<style scoped lang="scss">
@use '@/styles/crm/mixins' as mixin;

.customer-country {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.customer-country__flag { flex: none; width: 16px; height: 12px; object-fit: cover; }
.customer-country__name { @include mixin.text-ellipsis; }
</style>
