<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import CustomerCreateDialog from './CustomerCreateDialog.vue'

const router = useRouter()
const visible = ref(true)
function handleVisibility(value: boolean) {
  visible.value = value
}
function handleCreated(customerId: string, continueCreating: boolean) {
  if (!continueCreating) void router.replace({ name: 'customer-detail', params: { customerId } })
}
function openExisting(customerId: string) {
  void router.replace({ name: 'customer-detail', params: { customerId } })
}
</script>

<template>
  <CustomerCreateDialog :model-value="visible" @update:model-value="handleVisibility" @cancelled="router.replace({ name: 'customers' })" @created="handleCreated" @open-existing="openExisting" />
</template>
