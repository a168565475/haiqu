<script setup lang="ts">
import { computed } from 'vue'
import { ElDropdownItem, ElIcon } from 'element-plus'
import { Refresh, Switch, UserFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

defineProps<{ busy: boolean; error?: string }>()
const auth = useAuthStore()
const hasReturn = computed(() => auth.accountSwitch?.can_return === true)
</script>

<template>
  <ElDropdownItem v-if="auth.canSwitchAccount" command="switch-account" :disabled="busy" data-switch-account-action>
    <ElIcon><Switch /></ElIcon><span>切换员工</span>
  </ElDropdownItem>
  <ElDropdownItem v-if="auth.canSwitchAccount || hasReturn" command="return-admin" :disabled="busy || !auth.canReturnAdmin" data-return-admin>
    <ElIcon><UserFilled /></ElIcon><span>超级管理</span>
  </ElDropdownItem>
  <ElDropdownItem v-if="auth.identityRevalidationRequired || error || (hasReturn && !auth.canReturnAdmin)" command="verify-identity" :disabled="busy" data-verify-identity>
    <ElIcon><Refresh /></ElIcon><span>重新核验身份</span>
  </ElDropdownItem>
  <ElDropdownItem v-if="error" disabled><span role="alert" class="account-switch-menu-error">{{ error }}</span></ElDropdownItem>
</template>

<style scoped>
.account-switch-menu-error { max-width: 260px; white-space: normal; overflow-wrap: anywhere; color: var(--erp-color-danger); }
</style>
