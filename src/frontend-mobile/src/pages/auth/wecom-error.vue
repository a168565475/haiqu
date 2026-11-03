<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { isWeComBrowser, resolveMobileRedirect, startWeComLogin } from '@/utils/wecom'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const busy = ref(false)
const message = ref('')
const inWeCom = isWeComBrowser()
const nextPath = computed(() => resolveMobileRedirect(route.query.next))
const retryInstruction = inWeCom ? '请重新尝试登录' : '请在企业微信中重新打开，或使用 ERP 账号登录'
const messages: Record<string, string> = {
  STATE_INVALID: `登录请求已过期或已使用，${retryInstruction}。`,
  CONFIGURATION_ERROR: '企业微信接入配置尚未就绪，请联系管理员检查应用配置。',
  IDENTITY_MISMATCH: '当前 ERP 登录账号与企业微信成员不一致。原会话未切换，请联系管理员核对身份。',
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
async function retry() {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    await auth.refresh(true)
    if (auth.user) await router.replace(nextPath.value)
    else if (auth.accountSwitch?.can_return) {
      message.value = '当前仍可返回管理员账号，请先返回 ERP 处理身份切换。'
    }
    else if (!startWeComLogin(nextPath.value)) message.value = '暂时无法发起企业微信登录，请从企业微信工作台重新打开，或使用 ERP 账号登录。'
  } catch (error) { message.value = errorMessage(error, '暂时无法确认登录状态，请稍后重试') }
  finally { busy.value = false }
}
function passwordLogin() {
  if (busy.value || (!auth.user && auth.accountSwitch?.can_return)) return
  void router.replace({ path: '/login', query: { redirect: nextPath.value } })
}
</script>

<template>
  <main class="auth-page">
    <div class="auth-brand"><van-icon name="apps-o" aria-hidden="true" /><span>海趣车间</span></div>
    <section class="auth-card" aria-labelledby="error-title">
      <div class="auth-symbol" aria-hidden="true"><van-icon name="warning-o" size="32" /></div>
      <h1 id="error-title">企业微信登录未完成</h1>
      <p class="auth-description" role="alert">{{ description }}</p>
      <p v-if="message" class="error-panel" role="alert">{{ message }}</p>
      <div v-if="!auth.user && auth.accountSwitch?.can_return" class="auth-actions">
        <p class="auth-description">当前仍可返回管理员账号，请先返回 ERP 处理身份切换。</p>
        <a class="erp-link" href="/">返回 ERP</a>
      </div>
      <div v-else class="auth-actions">
        <van-button v-if="inWeCom" type="primary" block :loading="busy" loading-text="正在检查登录状态" data-action="retry" @click="retry">{{ auth.user ? '返回当前账号' : '重新尝试企业微信登录' }}</van-button>
        <van-button :plain="inWeCom" type="primary" block :disabled="busy" data-action="password-login" @click="passwordLogin">使用 ERP 账号登录</van-button>
      </div>
    </section>
    <p class="auth-help">请从登录入口重新尝试，不要重复使用旧回调地址。</p>
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
.error-panel { margin: 16px 0 0; font-size: 15px; line-height: 1.7; overflow-wrap: anywhere; }
.auth-actions { display: flex; flex-direction: column; gap: 12px; margin-top: 24px; }
.auth-actions .van-button, .erp-link { min-height: 48px; border-radius: 10px; font-size: 16px; }
.erp-link { display: flex; align-items: center; justify-content: center; color: #fff; background: var(--mobile-primary); text-decoration: none; }
.auth-help { margin: 18px 4px 0; color: var(--mobile-muted); font-size: 14px; line-height: 1.7; }
@media (max-width: 359px) { .auth-page { padding-inline: 16px; } .auth-card { padding-inline: 16px; } }
</style>
