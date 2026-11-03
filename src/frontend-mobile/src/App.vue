<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { resolveMobileRedirect } from '@/utils/wecom'

const auth = useAuthStore()
const router = useRouter()
function expire() { auth.expire() }
function requireRole() {
  auth.expire()
  void router.replace({ path: '/auth/waiting-role', query: { next: resolveMobileRedirect(router.currentRoute.value.fullPath) } })
}
function invalidate() {
  auth.clear()
  void router.replace({ path: '/login', query: { reason: 'identity' } })
}
onMounted(() => {
  window.addEventListener('focus', expire)
  document.addEventListener('visibilitychange', expire)
  window.addEventListener('mobile-session-invalid', invalidate)
  window.addEventListener('mobile-role-required', requireRole)
})
onUnmounted(() => {
  window.removeEventListener('focus', expire)
  document.removeEventListener('visibilitychange', expire)
  window.removeEventListener('mobile-session-invalid', invalidate)
  window.removeEventListener('mobile-role-required', requireRole)
})
</script>

<template>
  <van-config-provider theme="light">
    <router-view v-slot="{ Component, route }">
      <component :is="Component" :key="`${auth.generation}:${route.path}`" />
    </router-view>
  </van-config-provider>
</template>
