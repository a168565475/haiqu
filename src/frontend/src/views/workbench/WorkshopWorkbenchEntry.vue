<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import WorkshopDirectorWorkbench from './WorkshopDirectorWorkbench.vue'
import ProductionDashboardView from './production/ProductionDashboardView.vue'

defineProps<{ role: 'workshop' }>()
const auth = useAuthStore()
</script>

<template>
  <WorkshopDirectorWorkbench
    v-if="auth.isWorkshopDirector || (auth.user?.is_superuser && auth.user.employee?.status === 'ACTIVE')"
    :key="auth.identityGeneration"
  />
  <ProductionDashboardView v-else :role="role" />
</template>
