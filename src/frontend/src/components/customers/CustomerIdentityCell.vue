<script setup lang="ts">
import type { CustomerListItem } from '@/types/customer'

defineProps<{
  customer: CustomerListItem
}>()

defineEmits<{
  open: []
}>()
</script>

<template>
  <button type="button" class="customer-identity" :title="customer.account_name" @click="$emit('open')">
    <span class="customer-identity__name">{{ customer.account_name }}</span>
  </button>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/mixins' as mixin;

.customer-identity {
  @include mixin.reset-button;

  display: flex;
  width: 100%;
  min-width: 0;
  align-items: flex-start;
  cursor: pointer;
  text-align: left;
}

.customer-identity:focus-visible {
  @include mixin.focus-ring;

  border-radius: token.$crm-radius-1;
}

.customer-identity__name {
  @include mixin.text-ellipsis;

  width: 100%;
  color: token.$crm-text-primary;
  font-size: 13px;
  font-weight: 700;
  line-height: 20px;
}

.customer-identity:hover .customer-identity__name {
  color: token.$crm-primary-hover;
}

</style>
