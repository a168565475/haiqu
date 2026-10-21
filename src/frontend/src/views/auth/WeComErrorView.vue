<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import headerLogo from '@/assets/navigation/hitree-header-logo.png'
import { useAuthStore } from '@/stores/auth'
import { isWeComBrowser } from '@/utils/wecom'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const inWeCom = isWeComBrowser()
const retryInstruction = inWeCom ? '请重新从企业微信工作台打开 ERP' : '请返回登录页重新扫码'
const loggingOut = ref(false), logoutError = ref('')
const messages: Record<string, string> = {
  STATE_INVALID: `登录请求已过期或已使用，${retryInstruction}。`,
  CONFIGURATION_ERROR: '企业微信接入配置尚未就绪，请联系管理员检查应用配置。',
  IDENTITY_MISMATCH: inWeCom
    ? '当前 ERP 登录账号与企业微信成员不一致。原会话未切换，请联系管理员核对身份。'
    : '当前 ERP 登录账号与企业微信成员不一致。原会话未切换，请先退出原账号后重试。',
  MEMBER_REJECTED: '当前成员无法使用此应用，请联系管理员核对在职状态、应用可见范围和员工绑定。',
  BINDING_REQUIRED: '成员身份需要管理员核对关联，请联系管理员确认对应的 ERP 员工后重新登录。',
  ACCOUNT_INACTIVE: '对应的 ERP 员工或账号当前不可用，请联系管理员核对员工状态及账号是否启用。',
  UPSTREAM_UNAVAILABLE: `企业微信服务暂时无法连接，${retryInstruction}。`,
  LOGIN_FAILED: `企业微信登录未完成，${retryInstruction}；仍失败时联系管理员。`,
}
const description = computed(() => {
  const reason = route.query.reason
  return typeof reason === 'string' && Object.hasOwn(messages, reason) ? messages[reason] : messages.LOGIN_FAILED
})
async function logout() {
  if (inWeCom || loggingOut.value) return
  loggingOut.value = true; logoutError.value = ''
  try { await auth.logout(); await router.replace({ name: 'login' }) }
  catch { logoutError.value = '退出失败，原会话仍保留，请检查网络后重试。' }
  finally { loggingOut.value = false }
}
</script>

<template>
  <main class="wecom-auth-page"><section class="wecom-auth-card">
    <img class="wecom-auth-logo" :src="headerLogo" alt="HiTree"><h1>企业微信登录未完成</h1><p role="alert">{{ description }}</p>
    <p v-if="logoutError" class="wecom-auth-feedback error" role="alert">{{ logoutError }}</p>
    <div class="wecom-auth-actions"><button v-if="auth.isAuthenticated && !inWeCom" class="primary" :disabled="loggingOut" @click="logout">{{ loggingOut ? '正在退出…' : '退出当前账号' }}</button><button v-else-if="auth.isAuthenticated" class="primary" @click="router.replace({ name: 'home' })">返回当前账号</button><button v-else class="primary" @click="router.replace({ name: 'login' })">返回登录页</button></div>
    <small>{{ inWeCom ? '请从企业微信工作台重新进入' : '请返回登录页重新扫码' }}，不要重复使用旧回调地址。</small>
  </section></main>
</template>

<style scoped lang="scss" src="./wecom-auth.scss"></style>
