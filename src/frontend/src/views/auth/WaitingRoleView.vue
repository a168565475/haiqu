<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import headerLogo from '@/assets/navigation/hitree-header-logo.png'
import { useAuthStore } from '@/stores/auth'
import { isWeComBrowser } from '@/utils/wecom'

const auth = useAuthStore()
const router = useRouter()
const inWeCom = isWeComBrowser()
const busy = ref(false), message = ref(''), error = ref('')
async function refreshRole() {
  if (busy.value) return
  busy.value = true; message.value = ''; error.value = ''
  try {
    await auth.initialize(true)
    if (!auth.isAuthenticated) await router.replace({ name: 'login' })
    else if (!auth.waitingForRole) await router.replace({ name: 'home' })
    else message.value = '尚未分配有效角色，请联系管理员后再次检查。'
  } catch { error.value = '暂时无法检查授权状态，当前会话已保留，请稍后重试。' }
  finally { busy.value = false }
}
async function logout() {
  if (inWeCom || busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await auth.logout(); await router.replace({ name: 'login' }) }
  catch { error.value = '退出失败，当前登录尚未解除，请检查网络后重试。' }
  finally { busy.value = false }
}
</script>

<template>
  <main class="wecom-auth-page"><section class="wecom-auth-card">
    <img class="wecom-auth-logo" :src="headerLogo" alt="HiTree">
    <div class="wecom-auth-symbol" aria-hidden="true"><svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11"/><path d="M16 9v7l5 3"/></svg></div>
    <h1>等待管理员分配角色</h1><p>已识别你的企业微信身份。<br>管理员分配角色后，即可进入 ERP。</p>
    <dl class="wecom-auth-identity"><div><dt>员工</dt><dd>{{ auth.user?.employee?.display_name || auth.user?.display_name }}</dd></div><div><dt>登录方式</dt><dd>企业微信</dd></div></dl>
    <p v-if="message" class="wecom-auth-feedback" role="status">{{ message }}</p><p v-if="error" class="wecom-auth-feedback error" role="alert">{{ error }}</p>
    <div class="wecom-auth-actions"><button class="primary" data-action="refresh-role" :disabled="busy" @click="refreshRole">{{ busy ? '正在处理…' : '检查授权状态' }}</button><button v-if="!inWeCom" data-action="logout" :disabled="busy" @click="logout">退出登录</button></div>
    <small>角色分配前，暂不能访问业务数据。</small>
  </section></main>
</template>

<style scoped lang="scss" src="./wecom-auth.scss"></style>
