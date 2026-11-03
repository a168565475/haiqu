<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { resolveMobileRedirect } from '@/utils/wecom'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const action = ref<'check' | 'logout' | null>(null)
const message = ref('')
const error = ref('')
const nextPath = computed(() => resolveMobileRedirect(route.query.next))
const employeeName = computed(() => auth.user?.employee?.display_name || auth.user?.display_name || auth.user?.username || '—')
function loginLocation() { return { path: '/login', query: { redirect: nextPath.value } } }
async function checkRole() {
  if (action.value) return
  action.value = 'check'
  message.value = ''; error.value = ''
  try {
    await auth.refresh(true)
    if (!auth.user) await router.replace(loginLocation())
    else if (!auth.user.waiting_for_role) await router.replace(nextPath.value)
    else message.value = '尚未分配有效访问权限，请联系管理员后再次检查。'
  } catch (cause) { error.value = errorMessage(cause, '暂时无法检查授权状态，请稍后重试') }
  finally { action.value = null }
}
async function logout() {
  if (action.value || auth.accountSwitch?.can_return) return
  action.value = 'logout'
  message.value = ''; error.value = ''
  try { await auth.logout(); await router.replace(loginLocation()) }
  catch (cause) { error.value = errorMessage(cause, '退出失败，当前登录尚未解除，请检查网络后重试') }
  finally { action.value = null }
}
</script>

<template>
  <main class="auth-page">
    <div class="auth-brand"><van-icon name="apps-o" aria-hidden="true" /><span>海趣车间</span></div>
    <section class="auth-card" aria-labelledby="waiting-title">
      <div class="auth-symbol" aria-hidden="true"><van-icon name="clock-o" size="32" /></div>
      <h1 id="waiting-title">等待管理员分配访问权限</h1>
      <p class="auth-description">当前账号还没有有效访问权限。管理员分配相应权限后，即可使用手机端。</p>
      <dl class="auth-identity"><dt>当前账号</dt><dd>{{ employeeName }}</dd></dl>
      <p v-if="message" class="auth-feedback" role="status">{{ message }}</p>
      <p v-if="error" class="error-panel" role="alert">{{ error }}</p>
      <div class="auth-actions">
        <van-button type="primary" block :loading="action === 'check'" :disabled="!!action" loading-text="正在检查授权状态" data-action="refresh-role" @click="checkRole">检查授权状态</van-button>
        <template v-if="auth.accountSwitch?.can_return">
          <p class="auth-description">当前仍可返回管理员账号，请在 ERP 中处理身份切换。</p>
          <a class="erp-link" href="/">返回 ERP</a>
        </template>
        <van-button v-else plain type="primary" block :loading="action === 'logout'" :disabled="!!action" loading-text="正在退出" data-action="logout" @click="logout">退出登录</van-button>
      </div>
    </section>
    <p class="auth-help">权限分配前，暂不能访问业务数据。</p>
  </main>
</template>

<style scoped>
.auth-page { max-width: 480px; margin-inline: auto; padding: max(28px, env(safe-area-inset-top)) 20px max(32px, env(safe-area-inset-bottom)); color: var(--mobile-text); }
.auth-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 28px; font-size: 20px; font-weight: 700; }
.auth-brand .van-icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 12px; color: var(--mobile-primary); background: var(--mobile-primary-soft); font-size: 24px; }
.auth-card { padding: 24px 20px; border: 1px solid var(--mobile-border); border-radius: 12px; background: var(--mobile-surface); }
.auth-symbol { display: grid; place-items: center; width: 64px; height: 64px; margin-bottom: 20px; border-radius: 16px; color: var(--mobile-primary); background: var(--mobile-primary-soft); }
h1 { margin: 0 0 12px; font-size: 20px; line-height: 1.5; }
.auth-description { margin: 0; color: var(--mobile-muted); font-size: 16px; line-height: 1.75; overflow-wrap: anywhere; }
.auth-identity { display: grid; grid-template-columns: auto 1fr; gap: 12px; margin: 20px 0 0; padding: 16px; border-radius: 10px; background: var(--mobile-canvas); font-size: 16px; line-height: 1.6; }
.auth-identity dt { color: var(--mobile-muted); }
.auth-identity dd { margin: 0; text-align: right; font-weight: 600; overflow-wrap: anywhere; }
.auth-feedback, .error-panel { margin: 16px 0 0; font-size: 15px; line-height: 1.7; overflow-wrap: anywhere; }
.auth-feedback { padding: 12px; border-radius: 10px; color: var(--mobile-text); background: var(--mobile-primary-soft); }
.auth-actions { display: flex; flex-direction: column; gap: 12px; margin-top: 24px; }
.auth-actions .van-button, .erp-link { min-height: 48px; border-radius: 10px; font-size: 16px; }
.erp-link { display: flex; align-items: center; justify-content: center; border: 1px solid var(--mobile-primary); color: var(--mobile-primary); text-decoration: none; }
.auth-help { margin: 18px 4px 0; color: var(--mobile-muted); font-size: 14px; line-height: 1.7; }
@media (max-width: 359px) { .auth-page { padding-inline: 16px; } .auth-card { padding-inline: 16px; } }
</style>
