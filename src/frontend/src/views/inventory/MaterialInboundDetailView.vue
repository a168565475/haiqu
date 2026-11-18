<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import MaterialTransferForm from '@/components/inventory/MaterialTransferForm.vue'
import { canOpenPage } from '@/router/pageAccess'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const canViewRecords = computed(() => canOpenPage('material-inbound-records', auth))
</script>

<template>
  <MaterialTransferForm>
    <template #actions>
      <ElButton v-if="canViewRecords" class="erp-button-motion" @click="router.push({ name: 'material-inbound-records' })">收发记录</ElButton>
    </template>
  </MaterialTransferForm>
</template>
