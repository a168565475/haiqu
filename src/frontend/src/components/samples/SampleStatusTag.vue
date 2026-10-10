<script setup lang="ts">
import { computed } from 'vue'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import { sampleStatusTone } from '@/utils/samplePresentation'

const props = defineProps<{ status: string; label: string; appearance?: 'list' | 'page' }>()
const tone = computed(() => sampleStatusTone(props.status))
</script>

<template>
  <span v-if="appearance === 'page'" class="sample-page-status" :class="tone">{{ label }}</span>
  <CustomerActivityTag v-else :label="label" :tone="tone" />
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.sample-page-status { display: inline-flex; min-width: 108px; height: 34px; flex: none; align-items: center; justify-content: center; padding: 6px 16px; border-radius: 20px; color: token.$crm-neutral; background: token.$crm-color-page; font-size: 14px; font-weight: 500; line-height: 22px; white-space: nowrap; }
.success { color: token.$crm-success; background: token.$crm-success-soft; }
.warning { color: token.$crm-warning; background: token.$crm-warning-soft; }
.danger { color: token.$crm-danger; background: token.$crm-danger-soft; }
.info { color: token.$crm-info; background: token.$crm-info-soft; }
</style>
