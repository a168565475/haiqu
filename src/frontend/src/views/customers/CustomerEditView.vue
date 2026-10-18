<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CustomerEditDialog from './CustomerEditDialog.vue'

const route = useRoute()
const router = useRouter()
const customerId = computed(() => String(route.params.customerId || ''))
const visible = ref(true)
function returnToCustomer(id = customerId.value) { void router.replace({ name: 'customer-detail', params: { customerId: id } }) }
function handleSaved(id: string, closeAfterSave: boolean) { if (closeAfterSave) returnToCustomer(id) }
</script>

<template>
  <CustomerEditDialog v-model="visible" :customer-id="customerId" @cancelled="returnToCustomer()" @saved="handleSaved" />
</template>
